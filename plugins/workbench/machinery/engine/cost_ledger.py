#!/usr/bin/env python3
"""cost_ledger — spend per session and per agent over a date window.

Where ``budget_burn`` answers "how much this month", this answers "which
sessions, and which agents inside them". It reads through
``transcript_reader`` (one de-duplicated call list) and prices through
``pricing.Pricer`` with the same merged table ``budget_burn`` uses, so its
totals agree with theirs by construction. The only parsing it does itself is
the optional ``agent-<id>.meta.json`` next to a subagent transcript, which
names the subagent's type.

Usage:
    python3 cost_ledger.py                              # current month, report
    python3 cost_ledger.py --since 2026-11-01 --until 2026-11-14
    python3 cost_ledger.py --json ledger.json           # also write the rows
"""

from __future__ import annotations

import argparse
import calendar
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import budget_burn
import pricing
import transcript_reader

SCHEMA_VERSION = 1
KINDS = ("input", "output", "cache_read", "write_5m", "write_1h")
_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
_TOP_SESSIONS = 10


# ---------------------------------------------------------------------------
# window
# ---------------------------------------------------------------------------
def month_window(today: date) -> tuple[str, str]:
    """First and last day of ``today``'s calendar month, as YYYY-MM-DD."""
    last = calendar.monthrange(today.year, today.month)[1]
    return today.replace(day=1).isoformat(), today.replace(day=last).isoformat()


def _instant(ts: object) -> datetime | None:
    """The moment ``ts`` names, in UTC, or None when it is not a usable timestamp.

    Accepts an ISO-8601 string with a trailing ``Z`` or a numeric offset. A
    string with no offset is read as UTC. Anything else, including a non-string,
    is undated (L3).
    """
    if not isinstance(ts, str):
        return None
    text = ts.strip()
    if text[-1:] in ("Z", "z"):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def utc_day(ts: object) -> str | None:
    """The UTC calendar date (YYYY-MM-DD) of ``ts``, or None when undated."""
    moment = _instant(ts)
    return None if moment is None else moment.date().isoformat()


def _day_in_window(day: str, since: str | None, until: str | None) -> bool:
    return (since is None or day >= since) and (until is None or day <= until)


def parse_day(text: str) -> str:
    """``text`` as a valid YYYY-MM-DD string, else ValueError."""
    if not _DAY.fullmatch(text):
        raise ValueError(f"not a YYYY-MM-DD date: {text!r}")
    date.fromisoformat(text)  # rejects 2026-13-01
    return text


# ---------------------------------------------------------------------------
# aggregation
# ---------------------------------------------------------------------------
class _Acc:
    """Running measures for one row."""

    def __init__(self) -> None:
        self.calls = 0
        self.unpriced_calls = 0
        self.tokens = {k: 0 for k in KINDS}
        self.usd_breakdown = {k: 0.0 for k in KINDS}
        self.usd = 0.0
        self.timestamps: list[str] = []
        self.models: list[str | None] = []
        self.attributions: set[str] = set()
        self.by_model: dict[str, dict] = {}

    def add(self, call: transcript_reader.Call, priced: pricing.PricedCall) -> None:
        self.calls += 1
        if not priced.priced:
            self.unpriced_calls += 1
        self.tokens["input"] += call.input_tokens
        self.tokens["output"] += call.output_tokens
        self.tokens["cache_read"] += call.cache_read_tokens
        self.tokens["write_5m"] += call.cache_write_5m_tokens
        self.tokens["write_1h"] += call.cache_write_1h_tokens
        parts = {
            "input": priced.input_usd,
            "output": priced.output_usd,
            "cache_read": priced.cache_read_usd,
            "write_5m": priced.write_5m_usd,
            "write_1h": priced.write_1h_usd,
        }
        for k, v in parts.items():
            self.usd_breakdown[k] += v
        self.usd += priced.total_usd
        self.timestamps.append(call.timestamp)
        self.models.append(call.model)
        if isinstance(call.attribution_agent, str) and call.attribution_agent:
            self.attributions.add(call.attribution_agent)
        name = call.model if call.model else "unknown"
        row = self.by_model.setdefault(name, {"calls": 0, "usd": 0.0})
        row["calls"] += 1
        row["usd"] += priced.total_usd


def _r(x: float) -> float:
    return round(x, 6)


def _measures(acc: _Acc) -> dict:
    return {
        "calls": acc.calls,
        "unpriced_calls": acc.unpriced_calls,
        "usd": _r(acc.usd),
        "tokens": dict(acc.tokens),
        "usd_breakdown": {k: _r(v) for k, v in acc.usd_breakdown.items()},
    }


def _model_of(models: list[str | None]) -> str:
    distinct = set(models)
    if distinct == {None} or distinct == {""}:
        return "unknown"
    if len(distinct) == 1:
        return next(iter(distinct))
    return "mixed"


def _meta_type(root: Path, project: str, session: str, agent_id: str) -> str | None:
    path = Path(root) / project / session / "subagents" / f"agent-{agent_id}.meta.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return None
    if isinstance(data, dict):
        value = data.get("agentType")
        if isinstance(value, str) and value:
            return value
    return None


def _agent_type(root: Path, project: str, session: str, agent_id: str, acc: _Acc) -> str:
    from_meta = _meta_type(root, project, session, agent_id)
    if from_meta is not None:
        return from_meta
    if len(acc.attributions) == 1:
        return next(iter(acc.attributions))
    return "unknown"


def build_ledger(
    root: Path,
    *,
    since: str | None = None,
    until: str | None = None,
    today: date,
) -> dict:
    """The ledger object (L8) for ``root``.

    With neither ``since`` nor ``until`` the window is the calendar month of
    ``today``; one alone leaves the other end open. The library never reads the
    clock: ``today`` is the caller's.
    """
    if since is None and until is None:
        since, until = month_window(today)
    result = transcript_reader.read(Path(root))
    pricer = pricing.Pricer(budget_burn.MODEL_PRICES)

    undated = 0
    sessions: dict[tuple[str, str], _Acc] = {}
    agents: dict[tuple[str, str], dict[str, tuple[_Acc, bool]]] = {}
    total = _Acc()
    main_usd = 0.0
    subagent_usd = 0.0
    for call in result.calls:
        instant = _instant(call.timestamp)
        if instant is None:
            undated += 1
            continue
        day = instant.date().isoformat()
        if not _day_in_window(day, since, until):
            continue
        priced = pricer.price(call)
        skey = (call.project, call.session_id)
        agent_id = (call.agent_id or "unknown") if call.is_subagent else "main"
        sessions.setdefault(skey, _Acc()).add(call, priced)
        slot = agents.setdefault(skey, {})
        if agent_id not in slot:
            slot[agent_id] = (_Acc(), call.is_subagent)
        slot[agent_id][0].add(call, priced)
        total.add(call, priced)
        if call.is_subagent:
            subagent_usd += priced.total_usd
        else:
            main_usd += priced.total_usd

    rows = []
    for skey in sorted(sessions):
        acc = sessions[skey]
        agent_rows = []
        for agent_id in sorted(agents[skey], key=lambda a: (a != "main", a)):
            a_acc, is_sub = agents[skey][agent_id]
            row = {
                "agent_id": agent_id,
                "agent_type": _agent_type(Path(root), skey[0], skey[1], agent_id, a_acc)
                if is_sub
                else "main",
                "model": _model_of(a_acc.models),
                "by_model": {
                    m: {"calls": v["calls"], "usd": _r(v["usd"])}
                    for m, v in sorted(a_acc.by_model.items())
                },
            }
            row.update(_measures(a_acc))
            agent_rows.append(row)
        srow = {
            "project": skey[0],
            "session_id": skey[1],
            "first_timestamp": min(acc.timestamps, key=_instant),
            "last_timestamp": max(acc.timestamps, key=_instant),
            "agents": agent_rows,
        }
        srow.update(_measures(acc))
        rows.append(srow)

    cov = result.coverage
    totals = _measures(total)
    totals["main_usd"] = _r(main_usd)
    totals["subagent_usd"] = _r(subagent_usd)
    return {
        "schema_version": SCHEMA_VERSION,
        "window": {"since": since, "until": until},
        "totals": totals,
        "coverage": {
            "files_found": cov.files_found,
            "files_read": cov.files_read,
            "files_skipped": len(cov.files_skipped),
            "malformed_lines": cov.malformed_lines,
            "undated_calls": undated,
        },
        "unpriced": pricer.unpriced(),
        "sessions": rows,
    }


def dumps(ledger: dict) -> str:
    """The ledger as the file text: sorted keys, 2-space indent, trailing newline."""
    return json.dumps(ledger, sort_keys=True, indent=2) + "\n"


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------
def _pct(part: float, whole: float) -> int:
    return round(part / whole * 100) if whole else 0


def _usd(x: float) -> str:
    return f"${x:,.2f}".rjust(11)


def report(ledger: dict) -> str:
    win = ledger["window"]
    t = ledger["totals"]
    total = t["usd"]
    lines = [
        f"Cost ledger — {win['since'] or 'start'} to {win['until'] or 'now'}",
        f"  Window total: ${total:,.2f} over {t['calls']:,} calls",
        "  Main versus subagents:",
        f"    main      {_usd(t['main_usd'])}  ({_pct(t['main_usd'], total)}%)",
        f"    subagents {_usd(t['subagent_usd'])}  ({_pct(t['subagent_usd'], total)}%)",
    ]
    by_type: dict[str, float] = {}
    by_model: dict[str, float] = {}
    for s in ledger["sessions"]:
        for a in s["agents"]:
            if a["agent_id"] == "main":
                continue
            by_type[a["agent_type"]] = by_type.get(a["agent_type"], 0.0) + a["usd"]
            for model, v in a["by_model"].items():
                by_model[model] = by_model.get(model, 0.0) + v["usd"]
    lines.append("  Subagent dollars by agent type:")
    lines += [f"    {k:24} {_usd(v)}" for k, v in sorted(by_type.items(), key=lambda kv: (-kv[1], kv[0]))] or ["    (none)"]
    lines.append("  Subagent dollars by model:")
    lines += [f"    {k:24} {_usd(v)}" for k, v in sorted(by_model.items(), key=lambda kv: (-kv[1], kv[0]))] or ["    (none)"]
    top = sorted(ledger["sessions"], key=lambda s: (-s["usd"], s["project"], s["session_id"]))[:_TOP_SESSIONS]
    lines.append(f"  Top {_TOP_SESSIONS} sessions:")
    lines += [f"    {_usd(s['usd'])}  {s['project']}  {s['session_id']}" for s in top] or ["    (none)"]
    c = ledger["coverage"]
    lines.append(
        f"  Coverage: files found {c['files_found']}, read {c['files_read']}, "
        f"skipped {c['files_skipped']}; malformed lines {c['malformed_lines']}; "
        f"undated calls {c['undated_calls']}"
    )
    for row in ledger["unpriced"]:
        lines.append(f"  Unpriced: {row['model'] or '(no model)'} x{row['calls']} — {row['reason']}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _fail(message: str) -> int:
    print(f"cost_ledger: {message}", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Spend per session and per agent.")
    ap.add_argument("--since", default=None, help="YYYY-MM-DD, inclusive")
    ap.add_argument("--until", default=None, help="YYYY-MM-DD, inclusive")
    ap.add_argument("--json", default=None, metavar="PATH", help="also write the ledger here")
    ap.add_argument(
        "--projects-root",
        default=str(Path.home() / ".claude" / "projects"),
    )
    args = ap.parse_args(argv)
    try:
        since = parse_day(args.since) if args.since is not None else None
        until = parse_day(args.until) if args.until is not None else None
    except ValueError as exc:
        return _fail(str(exc))
    if since is not None and until is not None and since > until:
        return _fail(f"--since {since} is after --until {until}")

    root = Path(args.projects_root)
    if not root.is_dir():
        return _fail(f"--projects-root is not a directory: {root}")
    ledger = build_ledger(root, since=since, until=until, today=date.today())
    if args.json is not None:
        try:
            Path(args.json).write_text(dumps(ledger), encoding="utf-8")
        except OSError as exc:
            return _fail(f"cannot write --json {args.json}: {exc.strerror or exc}")
    sys.stdout.write(report(ledger))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
