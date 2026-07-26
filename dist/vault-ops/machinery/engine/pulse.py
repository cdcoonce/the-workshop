#!/usr/bin/env python3
"""pulse — weekly work-quantification ledger across tools and machines.

Answers "is my output trending down?" with measured rows instead of vibes:
one CSV row per local-timezone ISO week per machine, derived entirely from
data that already exists on disk. Nothing here asks the human to log time.

Collected per week:
- ATTENTION (leading indicator): gap-clustered interactive hours from Claude
  Code transcripts (``~/.claude/projects``), Codex rollouts
  (``~/.codex/sessions``) and Cortex Code (``~/Library/Application Support/
  Cortex Code``), union-merged so parallel sessions cannot exceed wall clock,
  split by project domain. Headless traffic (sdk entrypoints, sidechains,
  ``codex_exec``) is never attention.
- OUTPUT (lagging): afk slices merged / first-attempt rate / quarantine rate
  and cost across every enrolled repo's ``telemetry.jsonl``; deliberate vault
  commits and auto-sync session proxies per machine from the vault's git
  history (the one feed that sees BOTH machines); tasks completed from weekly
  snapshots; wins from the Brag Doc.
- MANUAL: ``energy`` and ``satisfaction`` columns are yours to fill at
  wrap-up; the upsert never overwrites them.

The ledger is per-machine (``perf/metrics/pulse-<machine>.csv``) so the two
machines never merge-conflict; consumers union at read time. A run recomputes
only a trailing window — older rows are frozen because their sources
(transcripts especially) get pruned.

Usage:
    python3 pulse.py                # recompute trailing weeks, upsert, report
    python3 pulse.py --backfill     # add missing older rows, rewrite nothing
    python3 pulse.py --json
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import budget_burn
from pulse_defaults import AUTHOR_MACHINE_RULES as DEFAULT_AUTHOR_MACHINE_RULES
from pulse_defaults import (
    AUTOMATION_SUBJECT_PATTERNS as DEFAULT_AUTOMATION_SUBJECT_PATTERNS,
)
from pulse_defaults import AUTOSYNC_PREFIX as DEFAULT_AUTOSYNC_PREFIX
from pulse_defaults import BACKFILL_WEEKS as DEFAULT_BACKFILL_WEEKS
from pulse_defaults import DOMAIN_RULES as DEFAULT_DOMAIN_RULES
from pulse_defaults import GAP_MINUTES as DEFAULT_GAP_MINUTES
from pulse_defaults import RECOMPUTE_WEEKS as DEFAULT_RECOMPUTE_WEEKS

try:  # Scaffold-owned config; absent in a vault vendored before it existed.
    import pulse_config as _config
except ImportError:
    _config = None


class PulseConfigError(RuntimeError):
    """Raised when the scaffold-owned pulse config defines a bad value."""


_CONFIG_TYPES: dict[str, type | tuple[type, ...]] = {
    "GAP_MINUTES": (int, float),
    "RECOMPUTE_WEEKS": int,
    "BACKFILL_WEEKS": int,
    "DOMAIN_RULES": tuple,
    "AUTHOR_MACHINE_RULES": tuple,
    "AUTOSYNC_PREFIX": str,
    "AUTOMATION_SUBJECT_PATTERNS": tuple,
}


def _from_config(name: str, default: object) -> object:
    """Value for ``name`` from the scaffold config, else the shipped default.

    Same contract as budget_burn: a config that never defines the name falls
    back to the shipped default; a config that defines it as something
    unusable raises ``PulseConfigError`` naming the file, so a typo surfaces
    as a diagnostic instead of a silently wrong ledger.
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
        config_path = getattr(_config, "__file__", None) or "pulse_config.py"
        raise PulseConfigError(
            f"pulse: {name} in {config_path} must be {wanted}, got "
            f"{type(value).__name__} — fix it there, or delete the name to "
            "fall back to the shipped default."
        )
    return value


GAP_MINUTES: float = _from_config("GAP_MINUTES", DEFAULT_GAP_MINUTES)
RECOMPUTE_WEEKS: int = _from_config("RECOMPUTE_WEEKS", DEFAULT_RECOMPUTE_WEEKS)
BACKFILL_WEEKS: int = _from_config("BACKFILL_WEEKS", DEFAULT_BACKFILL_WEEKS)
DOMAIN_RULES: tuple = _from_config("DOMAIN_RULES", DEFAULT_DOMAIN_RULES)
AUTHOR_MACHINE_RULES: tuple = _from_config(
    "AUTHOR_MACHINE_RULES", DEFAULT_AUTHOR_MACHINE_RULES
)
AUTOSYNC_PREFIX: str = _from_config("AUTOSYNC_PREFIX", DEFAULT_AUTOSYNC_PREFIX)
AUTOMATION_SUBJECT_PATTERNS: tuple = _from_config(
    "AUTOMATION_SUBJECT_PATTERNS", DEFAULT_AUTOMATION_SUBJECT_PATTERNS
)

DOMAINS = ("vault", "build", "home", "school", "other")

LEDGER_COLUMNS = [
    "week",
    "machine",
    "computed_at",
    "attn_total_h",
    "attn_vault_h",
    "attn_build_h",
    "attn_home_h",
    "attn_school_h",
    "attn_other_h",
    "claude_sessions",
    "codex_sessions",
    "cortex_sessions",
    "tokens_m",
    "spend_usd",
    "vault_sessions_personal",
    "vault_sessions_work",
    "deliberate_commits_personal",
    "deliberate_commits_work",
    "afk_merged",
    "afk_first_attempt_pct",
    "afk_quarantine_pct",
    "afk_cost_usd",
    "tasks_done",
    "wins",
    "energy",
    "satisfaction",
]

# Human-owned columns: the upsert must never overwrite a value already there.
MANUAL_COLUMNS = ("energy", "satisfaction")

# cwd prefixes that mean "not a real project checkout" (desktop-app temp dirs,
# session scratchpads). They get one STABLE bucket rather than a clever guess:
# a consistent bucket trends; a flaky mapping lies.
_TEMP_PREFIXES = ("/private/var/folders", "/var/folders", "/private/tmp", "/tmp")

# Cortex Code is a VS Code fork; this is its macOS Application Support tree.
CORTEX_ROOT_DEFAULT = str(
    Path.home() / "Library" / "Application Support" / "Cortex Code"
)


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def _parse_ts(ts: object) -> datetime | None:
    """ISO-8601 string WITH a zone (Z or offset) → aware UTC datetime.

    Naive and date-only strings return None: they carry no zone, so treating
    them as UTC would shift a local-midnight record into the previous day.
    ``_week_key`` handles that shape itself, taking it at face value as local.
    """
    if not isinstance(ts, str) or len(ts) < 10:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return dt.astimezone(timezone.utc)


def _week_of_date(d: date) -> str:
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"


def _week_key(ts: object, tz: ZoneInfo) -> str | None:
    """LOCAL-timezone ISO week ('2026-W30') for an ISO timestamp, else None.

    Zoned records convert to local first — a Sunday 21:00 in Denver is Monday
    03:00 UTC and belongs to Sunday's week. A naive or date-only value has no
    zone to convert, so it is taken at face value as local (the same reading
    ``collect_wins`` gives a bare Brag Doc date); anything else returns None.
    """
    dt = _parse_ts(ts)
    if dt is not None:
        return _week_of_date(dt.astimezone(tz).date())
    if isinstance(ts, str) and len(ts) >= 10:
        try:
            naive = datetime.fromisoformat(ts)
        except ValueError:
            return None
        if naive.tzinfo is None:
            return _week_of_date(naive.date())
    return None


_WEEK_KEY_RE = re.compile(r"^(\d{4})-W(\d{2})$")


def _week_ordinal(week_key: str) -> int | None:
    """A week key as a monotonic week count, for comparing across years."""
    m = _WEEK_KEY_RE.match(week_key)
    if not m:
        return None
    try:
        monday = date.fromisocalendar(int(m.group(1)), int(m.group(2)), 1)
    except ValueError:
        return None
    return monday.toordinal() // 7


def _covered_weeks(weeks_seen: set[str], window: list[str], max_gap: int = 2) -> set[str]:
    """Which window weeks a collector can actually speak to.

    Distinguishes two things a bare zero conflates: a week whose sources were
    pruned (no data — the column must stay blank) and a week where the sources
    exist and the human simply did nothing (a real, and very interesting,
    zero). Walks back from the newest week with records and keeps going across
    gaps of up to ``max_gap`` weeks, since a fortnight off is a plausible
    quiet spell while retention pruning leaves a long unbroken emptiness.
    A lone ancient transcript therefore cannot declare a year of pruned weeks
    covered, and a two-week holiday still reads as measured zeros.
    """
    if not weeks_seen or not window:
        return set()
    # Gaps are measured in calendar weeks, never in list positions: scan may
    # be handed a sparse window, and two adjacent entries in it can be months
    # apart.
    seen = sorted(_week_ordinal(w) for w in weeks_seen if _week_ordinal(w))
    if not seen:
        return set()
    floor = seen[-1]
    for older, newer in zip(reversed(seen[:-1]), reversed(seen[1:])):
        if newer - older > max_gap + 1:
            break
        floor = older
    return {
        w
        for w in window
        if (o := _week_ordinal(w)) is not None and o >= floor
    }


def _last_week_keys(today_local: date, n: int) -> list[str]:
    """The n trailing ISO week keys ending with today's week, oldest first."""
    return [_week_of_date(today_local - timedelta(weeks=k)) for k in range(n - 1, -1, -1)]


# ---------------------------------------------------------------------------
# Attention: gap clustering and interval union
# ---------------------------------------------------------------------------
def _cluster(
    times: list[datetime], gap_minutes: float
) -> list[tuple[datetime, datetime]]:
    """Sorted activity timestamps → (start, end) blocks split on silence.

    A gap strictly greater than the threshold closes a block; a lone
    timestamp yields a zero-length block (no padding — the bias is constant,
    so trends survive it)."""
    if not times:
        return []
    ordered = sorted(times)
    gap = timedelta(minutes=gap_minutes)
    blocks: list[tuple[datetime, datetime]] = []
    start = prev = ordered[0]
    for t in ordered[1:]:
        if t - prev > gap:
            blocks.append((start, prev))
            start = t
        prev = t
    blocks.append((start, prev))
    return blocks


def _union_hours(intervals: list[tuple[datetime, datetime]]) -> float:
    """Total hours covered by the union of intervals (overlaps count once)."""
    if not intervals:
        return 0.0
    ordered = sorted(intervals)
    total = timedelta()
    cur_start, cur_end = ordered[0]
    for start, end in ordered[1:]:
        if start <= cur_end:
            cur_end = max(cur_end, end)
        else:
            total += cur_end - cur_start
            cur_start, cur_end = start, end
    total += cur_end - cur_start
    return total.total_seconds() / 3600.0


# ---------------------------------------------------------------------------
# Project / domain attribution
# ---------------------------------------------------------------------------
def _normalize_project(cwd: object) -> str:
    """A cwd → a stable project key (worktrees collapse to their repo)."""
    if not isinstance(cwd, str) or not cwd:
        return "_unknown"
    if any(cwd.startswith(p) for p in _TEMP_PREFIXES):
        return "_desktop-temp"
    parts = [p for p in cwd.split("/") if p]
    for i, part in enumerate(parts):
        if part == "worktrees" and i >= 2 and parts[i - 1] in (".afk", ".claude"):
            return parts[i - 2]
    return parts[-1] if parts else "_unknown"


def _repo_pattern(repos_root: Path) -> re.Pattern:
    """Regex capturing (repo, path-within-repo) under the repos root."""
    return re.compile(
        re.escape(str(repos_root)) + r"/([A-Za-z0-9_.-]+)((?:/[A-Za-z0-9_.-]+)*)"
    )


def _tool_use_payload(rec: dict) -> str:
    """The record's tool-call inputs, serialized — its paths, not its metadata.

    Scoped to tool_use blocks on purpose: every record carries the launch
    ``cwd``, so scanning the whole line would add one vote for the launch
    repo every time and drown the repo actually being edited.
    """
    blocks = (rec.get("message") or {}).get("content")
    if not isinstance(blocks, list):
        return ""
    return "".join(
        json.dumps(b.get("input"))
        for b in blocks
        if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("input")
    )


def _touched_scope(text: str, pattern: re.Pattern) -> str | None:
    """What this text is clearly about, as ``repo/dir/subdir``, else None.

    Repo alone is too coarse: coursework lives INSIDE the vault, so a
    repo-level key books school hours to ``vault`` — inflating the very
    number whose decline the ledger exists to detect. Keeping the directory
    path lets ``_domain`` separate them.

    Text naming several places equally (a listing, a survey) carries no
    signal and returns None, so the caller keeps the session's current scope.
    """
    hits = pattern.findall(text)
    if not hits:
        return None
    counts: dict[str, int] = {}
    for repo, rest in hits:
        # A repo's worktree sibling dir (foo-worktrees/) is still foo's work.
        if repo.endswith("-worktrees"):
            repo = repo[: -len("-worktrees")]
        # Keep directories, drop the filename; two levels is enough to name a
        # course or an area without exploding into per-file scopes.
        parts = [p for p in rest.split("/") if p][:-1]
        scope = "/".join([repo, *parts[:2]]) if parts else repo
        counts[scope] = counts.get(scope, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return None
    return ranked[0][0]


def _scope_repo(scope: str) -> str:
    """The repo a scope belongs to — the clustering bucket key.

    Blocks cluster per repo, not per scope: a session hopping between
    directories inside one repo is one stretch of work, and bucketing finer
    would chop it into many tiny blocks.
    """
    return scope.split("/", 1)[0]


def _domain(project: str, rules: tuple = DOMAIN_RULES) -> str:
    for substring, domain in rules:
        if substring in project:
            return domain
    return "other"


# ---------------------------------------------------------------------------
# Collector: Claude Code transcripts
# ---------------------------------------------------------------------------
def collect_claude(
    projects_root: Path, tz: ZoneInfo, repos_root: Path | None = None
) -> dict:
    """Interactive attention events + deduped token/spend sums.

    Attention is decided PER SESSION, not per record: a transcript's records
    are buffered and only admitted once the whole file has been read and the
    session's entrypoint is known. Real transcripts open with two timestamped
    ``queue-operation`` records before the entrypoint appears, so a per-record
    decision would leak the opening moments of every headless run into
    attention (measured: +35% on a real week). A session that never declares
    an entrypoint is untrusted and contributes neither hours nor a count.

    Project attribution follows the repo whose paths the session touches,
    falling back to the launch cwd until one appears (see ``_touched_scope``).

    Tokens/spend: EVERY session (headless work costs real money), deduped by
    requestId across all files exactly like budget_burn — a resumed session
    re-writes its earlier records into a new transcript.
    """
    events: list[tuple[datetime, str]] = []
    session_weeks: dict[str, set[str]] = {}
    tokens_by_week: dict[str, int] = {}
    spend_by_week: dict[str, float] = {}
    seen: set[str] = set()
    weeks_seen: set[str] = set()
    pattern = _repo_pattern(repos_root) if repos_root else None

    for transcript in sorted(projects_root.glob("*/*.jsonl")):
        try:
            lines = transcript.read_text(errors="ignore").splitlines()
        except OSError:
            continue
        entrypoint: str | None = None
        interactive_weeks: set[str] = set()
        pending: list[tuple[datetime, str]] = []
        current_scope: str | None = None
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if pattern is not None:
                touched = _touched_scope(_tool_use_payload(rec), pattern)
                if touched is not None:
                    current_scope = touched
            if entrypoint is None and isinstance(rec.get("entrypoint"), str):
                entrypoint = rec["entrypoint"]
            dt = _parse_ts(rec.get("timestamp"))
            week = _week_key(rec.get("timestamp"), tz)
            if week is not None:
                weeks_seen.add(week)

            # Tokens/spend for every record with a billable usage block.
            msg = rec.get("message") or {}
            usage = msg.get("usage") or rec.get("usage")
            model = msg.get("model") or rec.get("model")
            tier = budget_burn._tier(model)
            if usage and tier and week:
                rid = rec.get("requestId") or msg.get("id")
                if rid is None or rid not in seen:
                    if rid is not None:
                        seen.add(rid)
                    toks = sum(
                        usage.get(k, 0) or 0
                        for k in (
                            "input_tokens",
                            "output_tokens",
                            "cache_read_input_tokens",
                            "cache_creation_input_tokens",
                        )
                    )
                    tokens_by_week[week] = tokens_by_week.get(week, 0) + toks
                    spend_by_week[week] = spend_by_week.get(
                        week, 0.0
                    ) + budget_burn._record_cost(usage, tier)

            # Candidate attention events: non-sidechain and timestamped. The
            # session-level entrypoint verdict is applied after the loop.
            if dt is not None and week is not None and rec.get("isSidechain") is not True:
                scope = current_scope or _normalize_project(rec.get("cwd"))
                pending.append((dt, scope))
                interactive_weeks.add(week)

        # Session verdict: an undeclared entrypoint is untrusted (it is what
        # the opening queue-operation records look like), so it earns neither
        # hours nor a count.
        if entrypoint is None or entrypoint.startswith("sdk"):
            continue
        events.extend(pending)
        for week in interactive_weeks:
            # Key by basename (the session UUID): the dir-rename reconciliation
            # left 141 byte-identical transcripts in two project dirs, and a
            # path key would count each of those sessions twice.
            session_weeks.setdefault(week, set()).add(transcript.name)

    return {
        "events": events,
        "sessions_by_week": {k: len(v) for k, v in session_weeks.items()},
        "tokens_by_week": tokens_by_week,
        "spend_by_week": spend_by_week,
        "weeks_seen": weeks_seen,
    }


# ---------------------------------------------------------------------------
# Collector: Codex rollouts
# ---------------------------------------------------------------------------
def collect_codex(codex_root: Path, tz: ZoneInfo) -> dict:
    """Interactive Codex sessions → attention events + per-week token deltas.

    Automation is excluded entirely: ``codex_exec`` / ``source=exec`` (afk
    slices, scripted probes) and subagent sessions, whose ``source`` is a dict
    like ``{"subagent": {...}}`` rather than a string.

    ``total_token_usage`` is cumulative per turn, so tokens are booked as
    per-week DELTAS of that counter — summing would overcount, and taking only
    the final total would bill a Sunday-to-Monday session entirely to Monday
    while its attention hours split across both weeks.
    """
    events: list[tuple[datetime, str]] = []
    session_weeks: dict[str, set[str]] = {}
    tokens_by_week: dict[str, int] = {}
    weeks_seen: set[str] = set()

    for rollout in sorted(codex_root.rglob("rollout-*.jsonl")):
        try:
            lines = rollout.read_text(errors="ignore").splitlines()
        except OSError:
            continue
        project: str | None = None
        interactive = True
        session_events: list[datetime] = []
        # Cumulative counter readings in encounter order, tagged with the week
        # they were observed in — differenced after the loop.
        readings: list[tuple[str, int]] = []
        last_week: str | None = None
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            payload = rec.get("payload") or {}
            if rec.get("type") == "session_meta":
                source = payload.get("source")
                if (
                    payload.get("originator") == "codex_exec"
                    or source == "exec"
                    or (isinstance(source, dict) and "subagent" in source)
                ):
                    interactive = False
                    break
                project = _normalize_project(payload.get("cwd"))
            dt = _parse_ts(rec.get("timestamp"))
            if dt is not None:
                session_events.append(dt)
                week = _week_key(rec.get("timestamp"), tz)
                if week:
                    last_week = week
                    weeks_seen.add(week)
            if payload.get("type") == "token_count":
                info = payload.get("info") or {}
                total = (info.get("total_token_usage") or {}).get("total_tokens")
                if isinstance(total, int) and last_week is not None:
                    readings.append((last_week, total))
        if not interactive or not session_events:
            continue
        proj = project or "_unknown"
        weeks: set[str] = set()
        for dt in session_events:
            events.append((dt, proj))
            weeks.add(_week_of_date(dt.astimezone(tz).date()))
        for week in weeks:
            session_weeks.setdefault(week, set()).add(rollout.name)
        prev = 0
        for week, total in readings:
            # A counter that goes backwards means a reset, not negative work.
            delta = max(total - prev, 0)
            tokens_by_week[week] = tokens_by_week.get(week, 0) + delta
            prev = max(total, prev)

    return {
        "events": events,
        "sessions_by_week": {k: len(v) for k, v in session_weeks.items()},
        "tokens_by_week": tokens_by_week,
        "weeks_seen": weeks_seen,
    }


# ---------------------------------------------------------------------------
# Collector: afk telemetry across enrolled repos
# ---------------------------------------------------------------------------
_CORTEX_LOG_DIR_RE = re.compile(r"^(\d{8})T(\d{6})$")


def collect_cortex(
    cortex_root: Path, tz: ZoneInfo, repos_root: Path | None = None
) -> dict:
    """Cortex Code activity — a third tool, and the one the work machine runs.

    Cortex Code is a VS Code fork, so it leaves two usable traces:

    - ``User/History/*/entries.json`` — local edit history. Each record has a
      ``resource`` file URI and epoch-millisecond ``timestamp`` per entry, so
      an edit is an attention event attributed by the path it touched, which
      is strictly better than a session-level cwd.
    - ``logs/<YYYYMMDDTHHMMSS>/`` — one directory per app launch, named in
      LOCAL time (verified against ``telemetry.firstSessionDate``: a
      ``20260702T185606`` directory corresponds to 01:56:06 GMT the next day).
      Launches count as sessions and as activity in their own right, since a
      session spent only chatting writes no files.

    The ``source`` field on each entry holds the operator's literal prompt.
    On a work machine that is customer, ticket and project detail, so it is
    read past and never returned — this collector emits timestamps and paths
    only. Cortex exposes no token accounting, so there is nothing to bill.
    """
    events: list[tuple[datetime, str]] = []
    session_weeks: dict[str, set[str]] = {}
    weeks_seen: set[str] = set()
    pattern = _repo_pattern(repos_root) if repos_root else None

    for entries in sorted((cortex_root / "User" / "History").glob("*/entries.json")):
        try:
            record = json.loads(entries.read_text(errors="ignore"))
        except (OSError, json.JSONDecodeError):
            continue
        resource = record.get("resource")
        path = ""
        if isinstance(resource, str):
            path = resource[len("file://") :] if resource.startswith("file://") else resource
        scope = None
        if pattern is not None and path:
            scope = _touched_scope(path, pattern)
        if scope is None:
            # A file OUTSIDE the repos root gets one stable bucket, never a
            # derived name: `_normalize_project` expects a directory, so a
            # file path would yield the FILENAME ("plugin.json") as a scope —
            # meaningless, and one fake project per filename.
            scope = "_cortex"
        for entry in record.get("entries") or []:
            stamp = entry.get("timestamp") if isinstance(entry, dict) else None
            if not isinstance(stamp, (int, float)):
                continue
            dt = datetime.fromtimestamp(stamp / 1000.0, tz=timezone.utc)
            events.append((dt, scope))
            weeks_seen.add(_week_of_date(dt.astimezone(tz).date()))

    logs = cortex_root / "logs"
    if logs.is_dir():
        for entry in sorted(logs.iterdir()):
            m = _CORTEX_LOG_DIR_RE.match(entry.name)
            if not m or not entry.is_dir():
                continue
            try:
                local = datetime.strptime(entry.name, "%Y%m%dT%H%M%S")
            except ValueError:
                continue
            started = local.replace(tzinfo=tz)
            week = _week_of_date(started.date())
            session_weeks.setdefault(week, set()).add(entry.name)
            weeks_seen.add(week)
            events.append((started.astimezone(timezone.utc), "_cortex"))

    return {
        "events": events,
        "sessions_by_week": {k: len(v) for k, v in session_weeks.items()},
        "weeks_seen": weeks_seen,
    }


def collect_afk(repos_root: Path, tz: ZoneInfo) -> dict:
    """Weekly pipeline-output metrics from every repo's telemetry.jsonl.

    Slice outcomes are the records with a ``status`` and no ``record_type``.
    Cost also sums ``orchestrator_cost`` and ``conductor_resume`` records;
    attestations are provenance (generation_attestation repeats the slice's
    cost) and ``auto_promote_decision`` is deduped upstream — neither is a
    countable series (see the vault's deduped-logs-fake-a-trend memory).
    """
    weekly: dict[str, dict[str, float]] = {}
    if not repos_root.is_dir():
        return {}

    def wk(week: str) -> dict[str, float]:
        return weekly.setdefault(
            week,
            {
                "merged": 0,
                "outcomes": 0,
                "first_attempt_ok": 0,
                "first_attempt_den": 0,
                "quarantined": 0,
                "cost_usd": 0.0,
            },
        )

    for telemetry in sorted(repos_root.glob("*/docs/dev-cycle/telemetry.jsonl")):
        try:
            lines = telemetry.read_text(errors="ignore").splitlines()
        except OSError:
            continue
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            week = _week_key(rec.get("ts"), tz)
            if week is None:
                continue
            record_type = rec.get("record_type")
            if record_type is None and "status" in rec:
                w = wk(week)
                w["outcomes"] += 1
                status = rec.get("status")
                if status == "merged":
                    w["merged"] += 1
                if status == "quarantined":
                    w["quarantined"] += 1
                if status in ("merged", "published"):
                    w["first_attempt_den"] += 1
                    if rec.get("attempts") == 1:
                        w["first_attempt_ok"] += 1
                cost = rec.get("cost")
                if isinstance(cost, (int, float)):
                    w["cost_usd"] += cost
            elif record_type in ("orchestrator_cost", "conductor_resume"):
                cost = rec.get("cost")
                if isinstance(cost, (int, float)):
                    wk(week)["cost_usd"] += cost

    out: dict[str, dict[str, float]] = {}
    for week, w in weekly.items():
        den = w["first_attempt_den"]
        outcomes = w["outcomes"]
        out[week] = {
            "merged": int(w["merged"]),
            "outcomes": int(outcomes),
            "first_attempt_pct": round(w["first_attempt_ok"] / den * 100, 1)
            if den
            else 0.0,
            "quarantine_pct": round(w["quarantined"] / outcomes * 100, 1)
            if outcomes
            else 0.0,
            "cost_usd": round(w["cost_usd"], 2),
        }
    return out


# ---------------------------------------------------------------------------
# Collector: vault git history (the only cross-machine feed)
# ---------------------------------------------------------------------------
def _author_machine(email: str) -> str:
    for substring, machine in AUTHOR_MACHINE_RULES:
        if substring in email:
            return machine
    return "personal"


def _classify_vault_commits(
    entries: list[tuple[str, str, str]], tz: ZoneInfo
) -> dict:
    """(author_email, iso_ts, subject) rows → weekly per-machine counts.

    Auto-sync commits are the session-activity proxy; merges and other
    mechanical subjects are dropped; the rest is deliberate work.
    """
    weekly: dict[str, dict[str, int]] = {}
    automation = [re.compile(p) for p in AUTOMATION_SUBJECT_PATTERNS]
    for email, ts, subject in entries:
        week = _week_key(ts, tz)
        if week is None:
            continue
        machine = _author_machine(email)
        w = weekly.setdefault(
            week,
            {
                "autosync_work": 0,
                "autosync_personal": 0,
                "deliberate_work": 0,
                "deliberate_personal": 0,
            },
        )
        if subject.startswith(AUTOSYNC_PREFIX):
            w[f"autosync_{machine}"] += 1
        elif any(p.search(subject) for p in automation):
            continue
        else:
            w[f"deliberate_{machine}"] += 1
    return weekly


def collect_vault_git(vault_root: Path, tz: ZoneInfo, since: date) -> dict | None:
    """Weekly commit classification from the vault repo.

    Returns None when git itself failed (missing, timeout, not a repo) so the
    caller can leave the columns untouched — an empty dict means "repo read
    fine, no commits", and conflating the two would overwrite good ledger
    values with zeros and call it a quiet week.
    """
    try:
        out = subprocess.run(
            [
                "git",
                "-C",
                str(vault_root),
                "log",
                f"--since={since.isoformat()}",
                "--format=%ae%x09%aI%x09%s",
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        print(
            f"pulse: vault git collector failed ({exc.__class__.__name__}); "
            "cross-machine columns left untouched",
            file=sys.stderr,
        )
        return None
    entries: list[tuple[str, str, str]] = []
    for line in out.stdout.splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3:
            entries.append((parts[0], parts[1], parts[2]))
    return _classify_vault_commits(entries, tz)


# ---------------------------------------------------------------------------
# Collectors: Brag Doc wins, weekly task snapshots
# ---------------------------------------------------------------------------
_WIN_RE = re.compile(r"^- \*\*(\d{4})-(\d{2})-(\d{2})")


def collect_wins(brag_path: Path, tz: ZoneInfo) -> dict[str, int]:
    """Dated Brag Doc bullets → wins per week. Dates are already local."""
    if not brag_path.is_file():
        return {}
    out: dict[str, int] = {}
    for line in brag_path.read_text(errors="ignore").splitlines():
        m = _WIN_RE.match(line)
        if not m:
            continue
        try:
            d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            continue
        week = _week_of_date(d)
        out[week] = out.get(week, 0) + 1
    return out


_SNAPSHOT_RE = re.compile(r"(\d{4}-W\d{2})-tasks\.md$")
_CHECKED_RE = re.compile(r"^\s*- \[x\]", re.IGNORECASE | re.MULTILINE)
_TASKS_WEEK_RE = re.compile(r'^week:\s*"?(\d{4})-(\d{2})-(\d{2})"?', re.MULTILINE)


def collect_tasks(vault_root: Path) -> dict[str, int]:
    """Completed-task LEVEL per week from snapshots + the live Tasks.md.

    This is a level (checked boxes present that week), not a flow — tasks
    get archived out between weeks, so week-over-week deltas are directional
    only. The live file wins over a snapshot for the same week."""
    out: dict[str, int] = {}
    archive = vault_root / "work" / "archive"
    if archive.is_dir():
        # Both layouts exist in the real vault: work/archive/<year>/tasks/ and
        # work/archive/tasks/. _SNAPSHOT_RE rejects anything else.
        for snapshot in sorted(archive.glob("**/*-tasks.md")):
            m = _SNAPSHOT_RE.search(snapshot.name)
            if not m:
                continue
            try:
                text = snapshot.read_text(errors="ignore")
            except OSError:
                continue
            out[m.group(1)] = len(_CHECKED_RE.findall(text))
    live = vault_root / "work" / "Tasks.md"
    if live.is_file():
        text = live.read_text(errors="ignore")
        m = _TASKS_WEEK_RE.search(text)
        if m:
            try:
                d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                d = None
            if d is not None:
                out[_week_of_date(d)] = len(_CHECKED_RE.findall(text))
    return out


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------
def upsert_ledger(
    ledger_path: Path, new_rows: dict[str, dict[str, str]], *, machine: str
) -> None:
    """Upsert computed rows into the per-machine CSV ledger.

    Rows not named in ``new_rows`` are untouched (frozen history), including
    columns this engine doesn't know about — a newer engine's column must
    survive an older engine's run, because frozen weeks can never be
    recomputed. For named rows, computed columns overwrite and MANUAL_COLUMNS
    keep whatever a human already wrote. A duplicate week (only reachable via
    a hand edit or a keep-both merge resolution) raises rather than silently
    dropping one row's manual values. Deterministic: same inputs, same bytes.
    """
    existing: dict[str, dict[str, str]] = {}
    extras: list[str] = []
    if ledger_path.is_file():
        with ledger_path.open(newline="") as fh:
            reader = csv.DictReader(fh)
            extras = [
                c
                for c in (reader.fieldnames or [])
                if c and c not in LEDGER_COLUMNS
            ]
            for row in reader:
                week = row.get("week")
                if not week:
                    continue
                if week in existing:
                    raise ValueError(
                        f"pulse: duplicate row for {week} in {ledger_path} — "
                        "merge them by hand before rerunning (keeping both "
                        "would silently drop one row's energy/satisfaction)."
                    )
                existing[week] = row
    fields = LEDGER_COLUMNS + extras
    for week, computed in new_rows.items():
        base = {c: "" for c in fields}
        prior = existing.get(week, {})
        base.update({k: v for k, v in prior.items() if k in fields})
        base.update({k: v for k, v in computed.items() if k in LEDGER_COLUMNS})
        for col in MANUAL_COLUMNS:
            if prior.get(col):
                base[col] = prior[col]
        base["week"] = week
        base["machine"] = base.get("machine") or machine
        existing[week] = base
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for week in sorted(existing):
            writer.writerow({c: existing[week].get(c) or "" for c in fields})


# ---------------------------------------------------------------------------
# scan — one pass over every source, rows for the requested weeks
# ---------------------------------------------------------------------------
def scan(
    *,
    projects_root: Path,
    codex_root: Path,
    repos_root: Path,
    cortex_root: Path | None = None,
    vault_root: Path,
    week_keys: list[str],
    tz: ZoneInfo,
    include_vault_git: bool = False,
    computed_at: str = "",
) -> dict[str, dict[str, str]]:
    """Compute a ledger row per requested week. Every collector fails open."""
    wanted = set(week_keys)
    claude = collect_claude(projects_root, tz, repos_root=repos_root)
    codex = collect_codex(codex_root, tz)
    # None means "this caller has no Cortex root", NOT "go find the real one":
    # scan must never reach into $HOME on its own or tests stop being hermetic.
    cortex = (
        collect_cortex(cortex_root, tz, repos_root=repos_root)
        if cortex_root is not None
        else {"events": [], "sessions_by_week": {}, "weeks_seen": set()}
    )
    afk = collect_afk(repos_root, tz)
    wins = collect_wins(vault_root / "perf" / "Brag Doc.md", tz)
    tasks = collect_tasks(vault_root)
    vault_git: dict | None = None
    if include_vault_git and week_keys:
        # Log window: today minus the requested span plus a 2-week margin —
        # cheaper than inverting week keys, and _week_key filters precisely.
        since = datetime.now(tz).date() - timedelta(weeks=len(week_keys) + 2)
        vault_git = collect_vault_git(vault_root, tz, since)

    # Attention: bucket events by (week, tool, scope), cluster per bucket,
    # then union per week (total) and per domain. Scope carries the directory
    # path, so switching between coursework and vault work inside one repo
    # ends one block and starts another — which is what keeps school hours
    # out of the vault column.
    by_bucket: dict[tuple[str, str, str], list[datetime]] = {}
    for tool, data in (("claude", claude), ("codex", codex), ("cortex", cortex)):
        for dt, scope in data["events"]:
            week = _week_of_date(dt.astimezone(tz).date())
            if week in wanted:
                by_bucket.setdefault((week, tool, scope), []).append(dt)
    intervals_by_week: dict[str, list[tuple[str, tuple[datetime, datetime]]]] = {}
    for (week, _tool, scope), times in by_bucket.items():
        for block in _cluster(times, GAP_MINUTES):
            intervals_by_week.setdefault(week, []).append((scope, block))

    # Coverage: which weeks a collector actually has records for. Transcripts
    # and rollouts get pruned and afk telemetry starts at enrollment, so a
    # week with no records has NO data — writing 0.00 there would render on a
    # chart as a work stoppage that never happened. Those columns stay blank.
    # Deliberately a per-week set, not an earliest-record floor: one stray old
    # transcript would otherwise declare a year of pruned weeks "covered".
    # Git history, Brag Doc, and task snapshots are never pruned — no gating.
    attn_weeks = _covered_weeks(
        claude["weeks_seen"] | codex["weeks_seen"] | cortex["weeks_seen"], week_keys
    )
    afk_weeks = _covered_weeks(set(afk), week_keys)

    rows: dict[str, dict[str, str]] = {}
    for week in week_keys:
        tagged = intervals_by_week.get(week, [])
        all_blocks = [b for _, b in tagged]
        row: dict[str, str] = {"week": week, "computed_at": computed_at}
        if week in attn_weeks:
            row["attn_total_h"] = f"{_union_hours(all_blocks):.2f}"
            for dom in DOMAINS:
                blocks = [b for p, b in tagged if _domain(p, DOMAIN_RULES) == dom]
                row[f"attn_{dom}_h"] = f"{_union_hours(blocks):.2f}"
            row["claude_sessions"] = str(claude["sessions_by_week"].get(week, 0))
            row["codex_sessions"] = str(codex["sessions_by_week"].get(week, 0))
            row["cortex_sessions"] = str(cortex["sessions_by_week"].get(week, 0))
            tokens = claude["tokens_by_week"].get(week, 0) + codex[
                "tokens_by_week"
            ].get(week, 0)
            row["tokens_m"] = f"{tokens / 1_000_000:.2f}"
            row["spend_usd"] = f"{claude['spend_by_week'].get(week, 0.0):.2f}"
        # None = the collector failed; omit the keys so the upsert preserves
        # whatever the ledger already holds instead of zeroing it.
        if vault_git is not None:
            git_week = vault_git.get(week, {})
            row["vault_sessions_personal"] = str(git_week.get("autosync_personal", 0))
            row["vault_sessions_work"] = str(git_week.get("autosync_work", 0))
            row["deliberate_commits_personal"] = str(
                git_week.get("deliberate_personal", 0)
            )
            row["deliberate_commits_work"] = str(git_week.get("deliberate_work", 0))
        if week in afk_weeks:
            afk_week = afk.get(week)
            row["afk_merged"] = str(afk_week["merged"]) if afk_week else "0"
            row["afk_first_attempt_pct"] = (
                f"{afk_week['first_attempt_pct']:.1f}" if afk_week else "0.0"
            )
            row["afk_quarantine_pct"] = (
                f"{afk_week['quarantine_pct']:.1f}" if afk_week else "0.0"
            )
            row["afk_cost_usd"] = (
                f"{afk_week['cost_usd']:.2f}" if afk_week else "0.00"
            )
        if week in tasks:
            row["tasks_done"] = str(tasks[week])
        row["wins"] = str(wins.get(week, 0))
        rows[week] = row
    return rows


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _positive_int(raw: str) -> int:
    """argparse type: reject 0 and negatives instead of silently defaulting."""
    value = int(raw)
    if value < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return value


def has_evidence(row: dict[str, str]) -> bool:
    """True if any source actually measured something for this week.

    A week that predates every surviving source computes to all zeros, and a
    zero row is not the same claim as no row: written into the ledger it reads
    as "measured, and the answer was nothing", which drags any rolling median
    down and invents a collapse that never happened. Backfill writes a row
    only when something is behind it.
    """
    for column, value in row.items():
        if column in ("week", "machine", "computed_at") or not value:
            continue
        try:
            if float(value) != 0.0:
                return True
        except ValueError:
            return True  # a non-numeric value is content, not a zero
    return False


def existing_weeks(ledger_path: Path) -> set[str]:
    """Week keys already present in the ledger (empty if it has none)."""
    if not ledger_path.is_file():
        return set()
    with ledger_path.open(newline="") as fh:
        return {row["week"] for row in csv.DictReader(fh) if row.get("week")}


def _detect_vault_root(start: str) -> Path | None:
    """Walk up from the script for the vault root (holds `.vault-context`)."""
    p = Path(start).resolve()
    for parent in [p, *p.parents]:
        if (parent / ".vault-context").exists():
            return parent
    return None


def _machine_for(vault_root: Path) -> str:
    vc = vault_root / ".vault-context"
    if vc.is_file():
        text = vc.read_text().strip().lower()
        if text:
            return text
    return "personal"


def _report_lines(rows: dict[str, dict[str, str]], machine: str) -> list[str]:
    lines = [
        f"Pulse — weekly work ledger ({machine})",
        f"  {'week':9} {'attn(h)':>8} {'vault':>6} {'build':>6} {'home':>6} "
        f"{'school':>7} {'afk✓':>5} {'wins':>5} {'tasks':>6}",
    ]
    for week in sorted(rows):
        r = rows[week]

        def cell(name: str) -> str:
            # "—" means no data from that collector for the week, which is a
            # different claim from a measured zero.
            return r.get(name) or "—"

        lines.append(
            f"  {week:9} {cell('attn_total_h'):>8} {cell('attn_vault_h'):>6} "
            f"{cell('attn_build_h'):>6} {cell('attn_home_h'):>6} "
            f"{cell('attn_school_h'):>7} {cell('afk_merged'):>5} "
            f"{cell('wins'):>5} {cell('tasks_done'):>6}"
        )
    lines.append(
        "  attn = hours an interactive Claude/Codex session was active "
        "(union — parallel sessions count once, but a long autonomous run "
        "inside a session counts as active)."
    )
    lines.append(
        "  Domain columns are each a union and OVERLAP: two repos worked in "
        "parallel occupy the same wall clock, so they need not sum to attn."
    )
    lines.append(
        "  afk✓ = pipeline slices merged — the autonomous pipeline's output, "
        "not your attention. Read the two side by side, never blended."
    )
    return lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument(
        "--weeks",
        type=_positive_int,
        default=None,
        help=f"trailing ISO weeks to recompute (default: {RECOMPUTE_WEEKS})",
    )
    ap.add_argument(
        "--backfill",
        action="store_true",
        help=(
            f"add missing rows across the trailing {BACKFILL_WEEKS} weeks; "
            "rows the ledger already has are never rewritten"
        ),
    )
    ap.add_argument("--machine", default=None, help="ledger key (default: .vault-context)")
    ap.add_argument("--vault-root", default=None)
    ap.add_argument(
        "--projects-root", default=str(Path.home() / ".claude" / "projects")
    )
    ap.add_argument("--codex-root", default=str(Path.home() / ".codex" / "sessions"))
    ap.add_argument("--cortex-root", default=CORTEX_ROOT_DEFAULT)
    ap.add_argument(
        "--repos-root", default=str(Path.home() / "Developer" / "GitHub")
    )
    ap.add_argument("--ledger", default=None)
    ap.add_argument(
        "--no-vault-git",
        action="store_true",
        help="skip the vault git collector (cross-machine columns stay empty)",
    )
    ap.add_argument("--tz", default=None, help="IANA zone (default: system local)")
    args = ap.parse_args()

    vault_root = (
        Path(args.vault_root).resolve()
        if args.vault_root
        else _detect_vault_root(__file__)
    )
    if vault_root is None:
        print("pulse: no vault root found (.vault-context) — pass --vault-root")
        return 1
    tz = (
        ZoneInfo(args.tz)
        if args.tz
        else datetime.now().astimezone().tzinfo or timezone.utc
    )
    machine = args.machine or _machine_for(vault_root)
    ledger = (
        Path(args.ledger)
        if args.ledger
        else vault_root / "perf" / "metrics" / f"pulse-{machine}.csv"
    )
    if args.weeks is not None:
        weeks = args.weeks
    else:
        weeks = BACKFILL_WEEKS if args.backfill else RECOMPUTE_WEEKS
    week_keys = _last_week_keys(datetime.now(tz).date(), weeks)
    if args.backfill:
        # Fill-only: a week whose transcripts have since been pruned would
        # recompute to zero, so backfill never touches a row that exists.
        have = existing_weeks(ledger)
        skipped = [w for w in week_keys if w in have]
        week_keys = [w for w in week_keys if w not in have]
        if skipped:
            print(
                f"pulse: backfill skipped {len(skipped)} week(s) already in "
                f"the ledger ({skipped[0]}..{skipped[-1]})",
                file=sys.stderr,
            )
    rows = scan(
        projects_root=Path(args.projects_root),
        codex_root=Path(args.codex_root),
        cortex_root=Path(args.cortex_root),
        repos_root=Path(args.repos_root),
        vault_root=vault_root,
        week_keys=week_keys,
        tz=tz,
        include_vault_git=not args.no_vault_git,
        computed_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    if args.backfill:
        empty = [w for w, r in rows.items() if not has_evidence(r)]
        for week in empty:
            del rows[week]
        if empty:
            print(
                f"pulse: backfill wrote no row for {len(empty)} week(s) with "
                "no surviving evidence (absent ≠ measured zero)",
                file=sys.stderr,
            )
    upsert_ledger(ledger, rows, machine=machine)

    if args.json:
        print(
            json.dumps(
                {
                    "machine": machine,
                    "ledger": str(ledger),
                    "weeks": week_keys,
                    "rows": [rows[w] for w in sorted(rows)],
                },
                indent=2,
            )
        )
        return 0
    for line in _report_lines(rows, machine):
        print(line)
    print(f"  ledger: {ledger}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
