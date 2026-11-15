#!/usr/bin/env python3
"""budget_burn — compute Claude Code API spend across all local projects.

The monthly budget is *total* API spend, so this sums token usage across
every project transcript under ``~/.claude/projects/*/``, not just this vault.
Cost is computed deterministically from the per-message ``usage`` blocks
(input / output / cache-read / 5-minute and 1-hour cache-write) times the
published per-model prices, through ``pricing`` (the only place tokens become
dollars), so it needs no cost API and works headless on both machines. A call
whose model is not in the price table is listed under ``unpriced`` and adds no
dollars.

Surfaces the feedback loop the Conductor + Workers operating model was missing
(see brain/Key Decisions.md 2026-06-16): a per-model breakdown shows whether
judgment is staying on Opus while bulk work runs on the cheap tier.

Project aliases, per-model price overrides (``MODEL_PRICES``), and the monthly
budget are instance config (scaffold-owned ``budget_burn_config.py``, see
``_from_config``) — they change with prices, budgets, and renamed project dirs,
and shouldn't require an engine release. ``budget_burn_defaults.py`` and
``pricing_defaults.py`` ship today's values as the managed-tier fallback, so a
vault vendored before the config existed still reports its burn. The old
tier-keyed ``RATES`` no longer affects any dollar figure.

Usage:
    python3 budget_burn.py            # current month, human report
    python3 budget_burn.py --json     # machine-readable
    python3 budget_burn.py --month 2026-05
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from budget_burn_defaults import MONTHLY_BUDGET as DEFAULT_MONTHLY_BUDGET
from budget_burn_defaults import PROJECT_ALIASES as DEFAULT_PROJECT_ALIASES
import pricing
import transcript_reader
import vault_utils

try:  # Scaffold-owned config; absent in a vault vendored before it existed.
    import budget_burn_config as _config
except ImportError:
    _config = None


class BudgetBurnConfigError(RuntimeError):
    """Raised when the scaffold-owned budget_burn config defines a bad value."""


# What each configurable name has to be for the scan arithmetic to hold.
_CONFIG_TYPES: dict[str, type | tuple[type, ...]] = {
    "PROJECT_ALIASES": dict,
    "MODEL_PRICES": dict,
    "MONTHLY_BUDGET": (int, float),
}


def _from_config(name: str, default: object) -> object:
    """Value for ``name`` from the scaffold config, else the shipped default.

    A config that never defines ``name`` — or a vault vendored before the
    config existed at all — falls back to ``budget_burn_defaults``: that is
    the scaffold contract, and the default is today's shipped value, not a
    zero. A config that *does* define it as something unusable raises
    ``BudgetBurnConfigError`` naming the config file, so a mistyped price
    table surfaces as a diagnostic instead of a silently wrong burn.
    """
    if _config is None:
        return default
    value = getattr(_config, name, None)
    if value is None:
        return default
    expected = _CONFIG_TYPES[name]
    if not isinstance(value, expected):
        allowed = expected if isinstance(expected, tuple) else (expected,)
        wanted = " or ".join(t.__name__ for t in allowed)
        config_path = getattr(_config, "__file__", None)
        if config_path is None:
            config_path = "budget_burn_config.py"
        raise BudgetBurnConfigError(
            f"budget_burn: {name} in {config_path} must be {wanted}, "
            f"got {type(value).__name__} — fix it there, or delete the name to "
            "fall back to the shipped default."
        )
    return value


_PROJECT_ALIASES: dict[str, str] = _from_config(
    "PROJECT_ALIASES", DEFAULT_PROJECT_ALIASES
)
# MODEL_PRICES merges per key over the shipped table (an overridden key replaces
# its row, other rows remain, a new key adds one), so a vault that only re-prices
# one model does not lose the rest. A malformed row is a config error too.
def _model_prices() -> dict[str, dict]:
    overrides = _from_config("MODEL_PRICES", None)
    try:
        return pricing.merge_table(overrides)
    except pricing.PriceTableError as exc:
        config_path = getattr(_config, "__file__", None) or "budget_burn_config.py"
        raise BudgetBurnConfigError(
            f"budget_burn: MODEL_PRICES in {config_path} is malformed: {exc} — "
            "fix it there, or delete the name to fall back to the shipped default."
        ) from exc


MODEL_PRICES: dict[str, dict] = _model_prices()
MONTHLY_BUDGET: float = _from_config("MONTHLY_BUDGET", DEFAULT_MONTHLY_BUDGET)


def _tier(model: str) -> str | None:
    """Map a model id to a rate tier, or None for non-billable rows."""
    if not model:
        return None
    m = model.lower()
    if "fable" in m:
        return "fable"
    if "opus" in m:
        return "opus"
    if "sonnet" in m:
        return "sonnet"
    if "haiku" in m:
        return "haiku"
    return None  # synthetic/unknown — don't guess a rate


def _month_of(call: transcript_reader.Call) -> str:
    """YYYY-MM for a call, from its ISO timestamp, else its file's month."""
    ts = call.timestamp
    if isinstance(ts, str) and len(ts) >= 7:
        return ts[:7]
    return datetime.fromtimestamp(call.file_mtime, tz=timezone.utc).strftime("%Y-%m")


def scan(projects_root: Path, target_month: str) -> dict:
    """Sum cost for ``target_month`` (YYYY-MM) across all project transcripts.

    Calls come only from ``transcript_reader``: main and subagent transcripts,
    each API call counted once for the whole scan (``(message.id, requestId)``,
    usage from the line with the largest output), keyed to the top-level project.
    """
    pricer = pricing.Pricer(MODEL_PRICES)
    by_tier: dict[str, float] = {}
    by_project: dict[str, float] = {}
    by_day: dict[str, float] = {}
    total = 0.0

    for call in transcript_reader.read(projects_root).calls:
        if _month_of(call) != target_month:
            continue
        priced = pricer.price(call)
        if not priced.priced:
            continue
        tier = _tier(call.model)
        if tier is None and priced.total_usd == 0:
            continue  # zero-usage record (e.g. <synthetic>): nothing to bucket
        tier = tier or "other"
        project = call.project
        for legacy, current in _PROJECT_ALIASES.items():
            if project.startswith(legacy):
                project = current + project[len(legacy) :]
                break
        cost = priced.total_usd
        total += cost
        by_tier[tier] = by_tier.get(tier, 0.0) + cost
        by_project[project] = by_project.get(project, 0.0) + cost
        day = (call.timestamp or "")[:10]
        if day:
            by_day[day] = by_day.get(day, 0.0) + cost

    return {
        "month": target_month,
        "total": round(total, 2),
        "by_tier": {k: round(v, 2) for k, v in sorted(by_tier.items())},
        "by_project": {
            k: round(v, 2)
            for k, v in sorted(by_project.items(), key=lambda kv: -kv[1])[:10]
        },
        "by_day": {k: round(v, 2) for k, v in sorted(by_day.items())},
        "unpriced": pricer.unpriced(),
    }


def _pace(spent: float, today: date, budget: float) -> dict:
    """Budget pace: spend so far vs the linear month expectation + EOM projection."""
    import calendar

    days_in_month = calendar.monthrange(today.year, today.month)[1]
    day = today.day
    expected = budget * (day / days_in_month)
    projected = (spent / day * days_in_month) if day else spent
    return {
        "days_elapsed": day,
        "days_in_month": days_in_month,
        "expected_to_date": round(expected, 2),
        "delta": round(spent - expected, 2),  # + = ahead of (over) pace
        "projected_eom": round(projected, 2),
    }


def _tier_lines(result: dict) -> list[str]:
    spent = result["total"]
    opus_pct = (result["by_tier"].get("opus", 0) / spent * 100) if spent else 0
    lines = ["  By tier (Opus % = conductor-health — lower means more on the cheap tier):"]
    for tier, cost in result["by_tier"].items():
        pct = (cost / spent * 100) if spent else 0
        lines.append(f"    {tier:7} ${cost:8.2f}  ({pct:.0f}%)")
    lines.append(f"  → Opus is {opus_pct:.0f}% of spend.")
    return lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--month", default=None, help="YYYY-MM (default: current)")
    ap.add_argument("--context", default=None, help="work|personal (default: auto)")
    ap.add_argument("--budget", type=float, default=MONTHLY_BUDGET)
    ap.add_argument(
        "--projects-root",
        default=str(Path.home() / ".claude" / "projects"),
    )
    args = ap.parse_args()

    dead = pricing.deprecated_config_names(_config)
    if dead:
        config_path = getattr(_config, "__file__", None) or "budget_burn_config.py"
        print(
            f"budget_burn: {', '.join(dead)} in {config_path} no longer affects any "
            "dollar figure; price per model with MODEL_PRICES there instead.",
            file=sys.stderr,
        )

    today = date.today()
    month = args.month or today.strftime("%Y-%m")
    if args.context is not None:
        context = args.context
    else:
        root = vault_utils.find_vault_root(Path(__file__).parent)
        context = (
            vault_utils.read_vault_context(root, default="personal")
            if root is not None
            else "personal"
        )
    result = scan(Path(args.projects_root), month)
    spent = result["total"]

    if args.json:
        result["context"] = context
        if context == "work":
            result["pace"] = _pace(spent, today, args.budget)
        print(json.dumps(result, indent=2))
        return 0

    if context == "work":
        # GATE mode — the enterprise account is capped; spend matters.
        pace = _pace(spent, today, args.budget)
        over = pace["delta"] > 0
        print(f"Budget burn — {month} (work / enterprise · ${args.budget:.0f} cap)")
        share = f"  ({spent / args.budget * 100:.0f}% of cap)" if args.budget else ""
        print(f"  Spent: ${spent:.2f} / ${args.budget:.0f}{share}")
        print(
            f"  Pace: day {pace['days_elapsed']}/{pace['days_in_month']} → "
            f"expected ${pace['expected_to_date']:.2f}; "
            f"{'OVER' if over else 'under'} by ${abs(pace['delta']):.2f}"
        )
        print(f"  Projected month-end: ${pace['projected_eom']:.2f}"
              f"{'  ⚠️ over cap' if pace['projected_eom'] > args.budget else ''}")
    else:
        # VALUE-METER mode — personal subscription has no per-token cap; show worth.
        print(f"Subscription value — {month} (personal)")
        print(f"  API-equivalent value delivered: ${spent:.2f}")
        print("  (flat subscription fee buys this — no per-token cap)")
    for line in _tier_lines(result):
        print(line)
    for row in result["unpriced"]:
        tokens = sum(row["tokens"].values())
        print(
            f"  Unpriced: {row['model']} x{row['calls']} ({tokens:,} tokens) — {row['reason']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
