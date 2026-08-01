#!/usr/bin/env python3
"""budget_burn — compute Claude Code API spend across all local projects.

The monthly budget is *total* API spend, so this sums token usage across
every project transcript under ``~/.claude/projects/*/``, not just this vault.
Cost is computed deterministically from the per-message ``usage`` blocks
(input / output / cache-read / cache-write) times the published per-model
rates, so it needs no cost API and works headless on both machines.

Surfaces the feedback loop the Conductor + Workers operating model was missing
(see brain/Key Decisions.md 2026-06-16): a per-model breakdown shows whether
judgment is staying on Opus while bulk work runs on the cheap tier.

Project aliases, the price table, and the monthly budget are instance config
(scaffold-owned ``budget_burn_config.py``, see ``_from_config``) — they change
with prices, budgets, and renamed project dirs, and shouldn't require an engine
release. ``budget_burn_defaults.py`` ships today's values as the managed-tier
fallback, so a vault vendored before the config existed still reports its burn.

Usage:
    python3 budget_burn.py            # current month, human report
    python3 budget_burn.py --json     # machine-readable
    python3 budget_burn.py --month 2026-05
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path

from budget_burn_defaults import MONTHLY_BUDGET as DEFAULT_MONTHLY_BUDGET
from budget_burn_defaults import PROJECT_ALIASES as DEFAULT_PROJECT_ALIASES
from budget_burn_defaults import RATES as DEFAULT_RATES
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
    "RATES": dict,
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
RATES: dict[str, tuple[float, float]] = _from_config("RATES", DEFAULT_RATES)
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


def _record_cost(usage: dict, tier: str) -> float:
    """USD for one usage block at the given tier's rates."""
    rate_in, rate_out = RATES[tier]
    inp = usage.get("input_tokens", 0) or 0
    out = usage.get("output_tokens", 0) or 0
    cache_read = usage.get("cache_read_input_tokens", 0) or 0
    cache_write = usage.get("cache_creation_input_tokens", 0) or 0
    return (
        inp * rate_in
        + out * rate_out
        + cache_read * (rate_in * 0.1)
        + cache_write * (rate_in * 1.25)
    ) / 1_000_000


def _month_of(record: dict, fallback: str) -> str:
    """YYYY-MM for a record, from its ISO timestamp, else the file's month."""
    ts = record.get("timestamp")
    if isinstance(ts, str) and len(ts) >= 7:
        return ts[:7]
    return fallback


def scan(projects_root: Path, target_month: str) -> dict:
    """Sum cost for ``target_month`` (YYYY-MM) across all project transcripts."""
    by_tier: dict[str, float] = {}
    by_project: dict[str, float] = {}
    by_day: dict[str, float] = {}
    total = 0.0
    # Claude Code writes the SAME message.usage on multiple transcript lines per
    # response (one per content block / streaming chunk). Summing every record
    # over-counts ~2.7x — dedup by requestId so each real API call counts once.
    seen: set[str] = set()

    for transcript in projects_root.glob("*/*.jsonl"):
        project = transcript.parent.name
        for legacy, current in _PROJECT_ALIASES.items():
            if project.startswith(legacy):
                project = current + project[len(legacy) :]
                break
        file_month = datetime.fromtimestamp(
            transcript.stat().st_mtime, tz=timezone.utc
        ).strftime("%Y-%m")
        for line in transcript.read_text(errors="ignore").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = rec.get("message") or {}
            usage = msg.get("usage") or rec.get("usage")
            model = msg.get("model") or rec.get("model")
            tier = _tier(model)
            if not usage or not tier:
                continue
            if _month_of(rec, file_month) != target_month:
                continue
            rid = rec.get("requestId") or msg.get("id")
            if rid is not None:
                if rid in seen:
                    continue  # same API call, duplicate transcript record
                seen.add(rid)
            cost = _record_cost(usage, tier)
            total += cost
            by_tier[tier] = by_tier.get(tier, 0.0) + cost
            by_project[project] = by_project.get(project, 0.0) + cost
            day = (rec.get("timestamp") or "")[:10]
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
        print(f"  Spent: ${spent:.2f} / ${args.budget:.0f}  ({spent / args.budget * 100:.0f}% of cap)")
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
