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
    python3 cost_ledger.py --meter-usd 41.50            # compare with the usage view
    python3 cost_ledger.py --export-aggregates agg.json # shareable, no identifiers
"""

from __future__ import annotations

import argparse
import calendar
import json
import math
import os
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import budget_burn
import pricing
import transcript_reader

SCHEMA_VERSION = 3
AGGREGATES_VERSION = 1
KINDS = ("input", "output", "cache_read", "write_5m", "write_1h")
_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
_TOP_SESSIONS = 10
_TOP_SKILLS = 15


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


class _SkillAcc(_Acc):
    """Running measures for one skill row, or the unattributed bucket."""

    def __init__(self) -> None:
        super().__init__()
        self.sessions: set[tuple[str, str]] = set()

    def add(self, call: transcript_reader.Call, priced: pricing.PricedCall) -> None:
        super().add(call, priced)
        self.sessions.add((call.project, call.session_id))


def _skill_of(call: transcript_reader.Call) -> str | None:
    """The call's own ``attributionSkill`` exactly as written, else None (S1).

    Nothing is inferred from Skill tool calls, neighbouring calls or the plugin.
    """
    value = call.attribution_skill
    return value if isinstance(value, str) and value else None


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


def _recorded_cost(rows: list[dict], result: transcript_reader.ReadResult,
                   since: str | None, until: str | None) -> dict:
    """The recorded-cost check (X1, X3) over the session ``rows``.

    A session is comparable when it has a recorded figure whose record does not
    flag an unknown model cost, no unpriced call, and every dated call of the
    session (main and subagents, in or out of the window) inside the window.
    """
    dated = [(c, _instant(c.timestamp)) for c in result.calls]
    outside = {
        (c.project, c.session_id)
        for c, at in dated
        if at is not None and not _day_in_window(at.date().isoformat(), since, until)
    }
    states = {(c.project, c.session_id): c for c in result.cost_states}
    ledger = recorded = flagged_ledger = flagged_recorded = 0.0
    comparable = flagged = 0
    for row in rows:
        skey = (row["project"], row["session_id"])
        state = states.get(skey)
        if state is None or row["unpriced_calls"] or skey in outside:
            continue
        if state.has_unknown_model_cost:
            flagged += 1
            flagged_ledger += row["usd"]
            flagged_recorded += state.total_cost_usd
        else:
            comparable += 1
            ledger += row["usd"]
            recorded += state.total_cost_usd
    return {
        "sessions_in_window": len(rows),
        "sessions_comparable": comparable,
        "ledger_usd": _r(ledger),
        "recorded_usd": _r(recorded),
        "difference_usd": _r(ledger - recorded),
        "gap_percent": _r(abs(ledger - recorded) / recorded * 100) if recorded else None,
        "flagged_unknown_sessions": flagged,
        "flagged_ledger_usd": _r(flagged_ledger),
        "flagged_recorded_usd": _r(flagged_recorded),
    }


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
    skills: dict[str, _SkillAcc] = {}
    unattributed = _SkillAcc()
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
        skill = _skill_of(call)
        if skill is None:
            unattributed.add(call, priced)
        else:
            skills.setdefault(skill, _SkillAcc()).add(call, priced)
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

    skill_rows = []
    for name in sorted(skills):
        row = {"skill": name, "sessions": len(skills[name].sessions)}
        row.update(_measures(skills[name]))
        skill_rows.append(row)
    unattributed_row = {"sessions": len(unattributed.sessions)}
    unattributed_row.update(_measures(unattributed))

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
        "skills": skill_rows,
        "unattributed": unattributed_row,
        "meter": None,
        "recorded_cost": _recorded_cost(rows, result, since, until),
    }


def meter_check(ledger_usd: float, meter_usd: float) -> dict:
    """The meter block (M2, M4): the ledger total against a hand-read meter figure.

    ``difference_usd`` is ledger minus meter, signed. The flag is set strictly above
    10 percent of the meter, in either direction; exactly 10 percent does not flag.
    The gap percent is rounded to six places before the comparison, so a gap that
    is 10 percent in decimal (0.33 against 0.3) is not pushed over by float noise.
    """
    difference = ledger_usd - meter_usd
    gap_percent = abs(difference) / meter_usd * 100
    return {
        "meter_usd": _r(meter_usd),
        "ledger_usd": _r(ledger_usd),
        "difference_usd": _r(difference),
        "gap_percent": _r(gap_percent),
        "gap_flag": round(gap_percent, 6) > 10,
    }


def apply_meter(ledger: dict, meter_usd: float) -> dict:
    """Set ``ledger["meter"]`` from ``meter_usd`` and return the ledger."""
    ledger["meter"] = meter_check(ledger["totals"]["usd"], meter_usd)
    return ledger


def parse_meter(text: str) -> float:
    """``text`` as a finite number greater than 0, else ValueError."""
    try:
        value = float(text)
    except ValueError:
        raise ValueError(f"--meter-usd must be a number greater than 0: {text!r}") from None
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"--meter-usd must be a finite number greater than 0: {text!r}")
    return value


def distribution(values: list[float]) -> dict:
    """Min, quartiles and max of ``values`` (E3); linear interpolation at (n-1)q."""
    names = (("min", 0.0), ("p25", 0.25), ("median", 0.5), ("p75", 0.75), ("max", 1.0))
    if not values:
        return {name: None for name, _ in names}
    ordered = sorted(values)
    out = {}
    for name, q in names:
        pos = (len(ordered) - 1) * q
        lo = math.floor(pos)
        hi = math.ceil(pos)
        out[name] = _r(ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo))
    return out


def build_aggregates(ledger: dict) -> dict:
    """The aggregates-only export (E2), built field by field from an allow-list.

    Nothing is copied wholesale from the ledger: no project key, path, session id,
    agent id or call timestamp has a place in the object.
    """
    by_type: dict[str, dict] = {}
    by_model: dict[str, dict] = {}
    for session in ledger["sessions"]:
        for agent in session["agents"]:
            if agent["agent_id"] != "main":
                slot = by_type.setdefault(agent["agent_type"], {"calls": 0, "usd": 0.0})
                slot["calls"] += agent["calls"]
                slot["usd"] += agent["usd"]
            for model, share in agent["by_model"].items():
                slot = by_model.setdefault(model, {"calls": 0, "usd": 0.0})
                slot["calls"] += share["calls"]
                slot["usd"] += share["usd"]

    def shares(table: dict[str, dict]) -> dict:
        return {k: {"calls": v["calls"], "usd": _r(v["usd"])} for k, v in sorted(table.items())}

    t = ledger["totals"]
    un = ledger["unattributed"]
    cov = ledger["coverage"]
    return {
        "aggregates_version": AGGREGATES_VERSION,
        "window": {"since": ledger["window"]["since"], "until": ledger["window"]["until"]},
        "totals": {
            "calls": t["calls"],
            "unpriced_calls": t["unpriced_calls"],
            "usd": t["usd"],
            "tokens": {k: t["tokens"][k] for k in KINDS},
            "usd_breakdown": {k: t["usd_breakdown"][k] for k in KINDS},
            "main_usd": t["main_usd"],
            "subagent_usd": t["subagent_usd"],
        },
        "subagent_by_agent_type": shares(by_type),
        "by_model": shares(by_model),
        "skills": [
            {"skill": r["skill"], "calls": r["calls"], "usd": r["usd"], "sessions": r["sessions"]}
            for r in sorted(ledger["skills"], key=lambda r: r["skill"])
        ],
        "unattributed": {"calls": un["calls"], "usd": un["usd"], "sessions": un["sessions"]},
        "session_count": len(ledger["sessions"]),
        "session_usd_distribution": distribution([s["usd"] for s in ledger["sessions"]]),
        "coverage": {
            k: cov[k]
            for k in ("files_found", "files_read", "files_skipped", "malformed_lines", "undated_calls")
        },
        "unpriced": [
            {
                "model": u["model"],
                "reason": u["reason"],
                "calls": u["calls"],
                "tokens": {k: u["tokens"][k] for k in KINDS},
            }
            for u in ledger["unpriced"]
        ],
        "meter": None if ledger["meter"] is None else dict(ledger["meter"]),
        "recorded_cost": dict(ledger["recorded_cost"]),
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


def _skill_lines(ledger: dict) -> list[str]:
    total = ledger["totals"]["usd"]
    ranked = sorted(ledger["skills"], key=lambda r: (-r["usd"], r["skill"]))
    shown, rest = ranked[:_TOP_SKILLS], ranked[_TOP_SKILLS:]
    lines = [f"  Top {_TOP_SKILLS} skills by dollars:"]
    lines += [f"    {r['skill']:24} {_usd(r['usd'])}  {r['calls']:,} calls" for r in shown] or ["    (none)"]
    if rest:
        noun = "skill" if len(rest) == 1 else "skills"
        lines.append(f"    {len(rest)} more {noun} {_usd(sum(r['usd'] for r in rest))}")
    un = ledger["unattributed"]
    lines.append(f"    {'(unattributed)':24} {_usd(un['usd'])}  {un['calls']:,} calls  ({_pct(un['usd'], total)}%)")
    lines.append(
        "  Skill rows are a lower bound: the invoking call and later-turn work are not counted."
    )
    return lines


def _signed_usd(x: float) -> str:
    sign = "+" if x > 0 else "-" if x < 0 else ""
    return f"{sign}${abs(x):,.2f}"


def _meter_lines(meter: dict) -> list[str]:
    lines = []
    if meter["gap_flag"]:
        lines.append(
            f"METER GAP: ledger and meter differ by {meter['gap_percent']:.1f}%, more than 10%"
        )
    lines += [
        "Meter check (figure read by hand from the usage view)",
        f"  Ledger total: ${meter['ledger_usd']:,.2f}",
        f"  Meter:        ${meter['meter_usd']:,.2f}",
        f"  Difference:   {_signed_usd(meter['difference_usd'])} (ledger minus meter)",
        f"  Gap:          {meter['gap_percent']:.1f}%",
    ]
    return lines


def _recorded_lines(rc: dict) -> list[str]:
    gap = "n/a" if rc["gap_percent"] is None else f"{rc['gap_percent']:.1f}%"
    lines = [
        f"  Recorded-cost check: {rc['sessions_comparable']} of {rc['sessions_in_window']} sessions "
        f"comparable; ledger ${rc['ledger_usd']:,.2f} vs recorded ${rc['recorded_usd']:,.2f}, gap {gap}"
    ]
    if rc["flagged_unknown_sessions"]:
        n = rc["flagged_unknown_sessions"]
        lines.append(
            f"  Recorded-cost check: {n} {'session' if n == 1 else 'sessions'} not comparable "
            f"(unknown model cost); ledger ${rc['flagged_ledger_usd']:,.2f} "
            f"vs recorded ${rc['flagged_recorded_usd']:,.2f}"
        )
    return lines


def report(ledger: dict) -> str:
    win = ledger["window"]
    t = ledger["totals"]
    total = t["usd"]
    lines = _meter_lines(ledger["meter"]) if ledger.get("meter") else []
    lines += [
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
    lines += _skill_lines(ledger)
    if ledger.get("recorded_cost"):
        lines += _recorded_lines(ledger["recorded_cost"])
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


def _write_all(outputs: list[tuple[str, str, str]]) -> str | None:
    """Write every ``(flag, path, text)`` or none: stage each beside its target, then rename.

    Returns an error message, or ``None`` on success. On failure no destination is
    created or changed and no staging file is left behind.
    """
    staged: list[tuple[Path, Path]] = []
    try:
        for flag, name, text in outputs:
            dest = Path(name)
            if dest.is_dir():
                return f"cannot write {flag} {name}: is a directory"
            tmp = dest.with_name(f".{dest.name}.{os.getpid()}.tmp")
            try:
                tmp.write_text(text, encoding="utf-8")
            except OSError as exc:
                return f"cannot write {flag} {name}: {exc.strerror or exc}"
            staged.append((tmp, dest))
        for (tmp, dest), (flag, name, _) in zip(staged, outputs):
            try:
                os.replace(tmp, dest)
            except OSError as exc:
                return f"cannot write {flag} {name}: {exc.strerror or exc}"
        staged.clear()
        return None
    finally:
        for tmp, _ in staged:
            tmp.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Spend per session and per agent.")
    ap.add_argument("--since", default=None, help="YYYY-MM-DD, inclusive")
    ap.add_argument("--until", default=None, help="YYYY-MM-DD, inclusive")
    ap.add_argument("--json", default=None, metavar="PATH", help="also write the ledger here")
    ap.add_argument(
        "--meter-usd", default=None, metavar="N",
        help="dollar figure read by hand from the usage view; adds the meter check",
    )
    ap.add_argument(
        "--export-aggregates", default=None, metavar="PATH",
        help="write an aggregates-only JSON file with no identifiers",
    )
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

    meter = None
    if args.meter_usd is not None:
        try:
            meter = parse_meter(args.meter_usd)
        except ValueError as exc:
            return _fail(str(exc))

    root = Path(args.projects_root)
    if not root.is_dir():
        return _fail(f"--projects-root is not a directory: {root}")
    ledger = build_ledger(root, since=since, until=until, today=date.today())
    if meter is not None:
        apply_meter(ledger, meter)
    outputs: list[tuple[str, str, str]] = []
    if args.json is not None:
        outputs.append(("--json", args.json, dumps(ledger)))
    if args.export_aggregates is not None:
        outputs.append(("--export-aggregates", args.export_aggregates, dumps(build_aggregates(ledger))))
    error = _write_all(outputs)
    if error is not None:
        return _fail(error)
    sys.stdout.write(report(ledger))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
