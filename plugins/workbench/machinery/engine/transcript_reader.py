#!/usr/bin/env python3
"""transcript_reader — the one reader the cost instruments share.

``budget_burn`` (how much was spent) and ``context_spend`` (why) used to each
walk ``~/.claude/projects`` with their own discovery, parsing and de-duplication,
so they could disagree about the same month. Both now read through this module,
and a further instrument can agree with them by construction.

Layout under a projects root::

    <project-key>/<session-id>.jsonl                          main session
    <project-key>/<session-id>/subagents/agent-<id>.jsonl     subagent

Every field in a transcript is untrusted: nothing here raises on a malformed
value. A bad token count is 0, a record without usable usage yields no call,
and an unreadable file is recorded in the coverage summary instead of raised.

One API call is written on several lines (one per content block) that share
``message.id`` and ``requestId``, and a resumed or forked session copies history
into a new file. A call is therefore identified by ``(message.id, requestId)``
(``uuid`` when both are missing), counted once for the whole scan, and takes all
its usage from the line with the largest ``output_tokens`` (the later line on a
tie). When lines tie across files, the call belongs to the file that sorts later
by path; the choice is arbitrary but stable, and never depends on the order the
filesystem lists files in. ``CallCollector`` also offers ``mode="request"``, the first-seen-per-request
rule ``context_spend --dedupe request`` keeps for old baselines.

Stdlib only; no shell.
"""

from __future__ import annotations

import datetime
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


@dataclass(frozen=True)
class FileInfo:
    """One discovered transcript file."""

    path: Path
    project: str  # top-level directory under the root, never "subagents"
    session_id: str  # file stem (main) or session directory (subagent)
    is_subagent: bool
    agent_id: str | None
    mtime: float


@dataclass(frozen=True)
class Call:
    """One de-duplicated API call, with usage taken from its kept line."""

    key: tuple
    project: str
    session_id: str
    is_subagent: bool
    agent_id: str | None
    model: str | None
    timestamp: str | None  # raw string, unparsed
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int  # total
    cache_write_5m_tokens: int
    cache_write_1h_tokens: int
    attribution_skill: object = None
    attribution_plugin: object = None
    attribution_agent: object = None
    attribution_mcp_server: object = None
    attribution_mcp_tool: object = None
    file_mtime: float = 0.0  # of the file holding the kept line


@dataclass(frozen=True)
class Attachment:
    """One injected-context record (``type == "attachment"``)."""

    project: str
    session_id: str
    is_subagent: bool
    agent_id: str | None
    subtype: str | None  # attachment.type
    size: int  # characters in the compact JSON of the attachment object
    timestamp: str | None = None


@dataclass
class Coverage:
    """What a scan did and did not read."""

    files_found: int = 0
    files_read: int = 0
    files_skipped: list[tuple[str, str]] = field(default_factory=list)  # (path, reason)
    malformed_lines: int = 0


@dataclass
class ReadResult:
    calls: list[Call]
    attachments: list[Attachment]
    coverage: Coverage


# ---------------------------------------------------------------------------
# discovery and line parsing
# ---------------------------------------------------------------------------
def _safe_iterdir(path: Path) -> list[Path]:
    try:
        return sorted(path.iterdir())
    except OSError:
        return []


def _is_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


def _is_file(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def discover(root: Path) -> list[FileInfo]:
    """Main and subagent transcripts under ``root``, in sorted path order."""
    found: list[FileInfo] = []
    for proj in _safe_iterdir(Path(root)):
        if not _is_dir(proj):
            continue
        for entry in _safe_iterdir(proj):
            if entry.suffix == ".jsonl" and _is_file(entry):
                found.append(FileInfo(entry, proj.name, entry.stem, False, None, _mtime(entry)))
            elif _is_dir(entry):
                for sub in _safe_iterdir(entry / "subagents"):
                    if sub.suffix == ".jsonl" and _is_file(sub):
                        stem = sub.stem
                        agent = stem[len("agent-") :] if stem.startswith("agent-") else stem
                        found.append(
                            FileInfo(sub, proj.name, entry.name, True, agent, _mtime(sub))
                        )
    return found


def _mtime_day(mtime: float) -> str:
    return datetime.datetime.fromtimestamp(mtime, tz=datetime.timezone.utc).strftime("%Y-%m-%d")


def iter_records(
    root: Path, since: str | None = None, coverage: Coverage | None = None
) -> Iterator[tuple[FileInfo, dict]]:
    """Yield ``(file_info, record)`` for every JSON-object line under ``root``.

    ``since`` (YYYY-MM-DD) skips a file last written before that day, since it
    cannot hold newer messages; the skip is reported in ``coverage``. Lines that
    are not valid JSON or not a JSON object are counted, never raised.
    """
    cov = coverage if coverage is not None else Coverage()
    for info in discover(root):
        cov.files_found += 1
        if since is not None and _mtime_day(info.mtime) < since:
            cov.files_skipped.append((str(info.path), f"last written before {since}"))
            continue
        try:
            fh = info.path.open(encoding="utf-8", errors="replace")
        except OSError as exc:
            cov.files_skipped.append((str(info.path), f"unreadable: {exc.strerror or exc}"))
            continue
        records: list[dict] = []
        try:
            with fh:
                for raw in fh:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        rec = json.loads(raw)
                    except ValueError:
                        cov.malformed_lines += 1
                        continue
                    if not isinstance(rec, dict):
                        cov.malformed_lines += 1
                        continue
                    records.append(rec)
        except OSError as exc:
            cov.files_skipped.append((str(info.path), f"unreadable: {exc.strerror or exc}"))
            continue
        cov.files_read += 1
        for rec in records:
            yield info, rec


# ---------------------------------------------------------------------------
# calls
# ---------------------------------------------------------------------------
def _tokens(value: object) -> int:
    """A token count, or 0 for anything that is not a non-negative int."""
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return 0


def _id(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _usable_day(ts: object) -> str | None:
    if isinstance(ts, str) and _DAY.fullmatch(ts[:10]):
        return ts[:10]
    return None


def in_window(ts: object, since: str | None, until: str | None) -> bool:
    """True when ``ts`` falls in the inclusive ``[since, until]`` day window.

    With no window every timestamp (even none) passes; with one, a timestamp
    that is not a string starting with a YYYY-MM-DD date does not.
    """
    if since is None and until is None:
        return True
    day = _usable_day(ts)
    if day is None:
        return False
    return (since is None or day >= since) and (until is None or day <= until)


def _call_from_record(info: FileInfo, rec: dict, key: tuple) -> Call | None:
    if rec.get("type") not in (None, "assistant"):
        return None
    msg = rec.get("message")
    if not isinstance(msg, dict):
        return None
    usage = msg.get("usage")
    if not isinstance(usage, dict) or not usage:
        return None
    total_write = _tokens(usage.get("cache_creation_input_tokens"))
    split = usage.get("cache_creation")
    if isinstance(split, dict):
        w5 = _tokens(split.get("ephemeral_5m_input_tokens"))
        w1 = _tokens(split.get("ephemeral_1h_input_tokens"))
    else:
        w5, w1 = total_write, 0
    return Call(
        key=key,
        project=info.project,
        session_id=info.session_id,
        is_subagent=info.is_subagent,
        agent_id=info.agent_id,
        model=_text(msg.get("model")),
        timestamp=_text(rec.get("timestamp")),
        input_tokens=_tokens(usage.get("input_tokens")),
        output_tokens=_tokens(usage.get("output_tokens")),
        cache_read_tokens=_tokens(usage.get("cache_read_input_tokens")),
        cache_write_tokens=total_write,
        cache_write_5m_tokens=w5,
        cache_write_1h_tokens=w1,
        attribution_skill=rec.get("attributionSkill"),
        attribution_plugin=rec.get("attributionPlugin"),
        attribution_agent=rec.get("attributionAgent"),
        attribution_mcp_server=rec.get("attributionMcpServer"),
        attribution_mcp_tool=rec.get("attributionMcpTool"),
        file_mtime=info.mtime,
    )


class CallCollector:
    """De-duplicates calls across lines and files for one scan.

    ``mode="message-request"`` (default) keys on ``(message.id, requestId)`` and
    keeps the line with the largest ``output_tokens``, the later line on a tie.
    ``mode="request"`` keys on ``requestId`` (else ``message.id``) and keeps the
    first line seen. Either way the key falls back to ``uuid`` when no id is
    present, and a line with no identity at all is its own call.
    """

    def __init__(self, mode: str = "message-request") -> None:
        if mode not in ("message-request", "request"):
            raise ValueError(f"unknown dedupe mode: {mode!r}")
        self.mode = mode
        self._calls: dict[tuple, Call] = {}
        self._anonymous = 0

    def _key(self, rec: dict) -> tuple:
        msg = rec.get("message")
        mid = _id(msg.get("id")) if isinstance(msg, dict) else None
        rid = _id(rec.get("requestId"))
        if mid is None and rid is None:
            uid = _id(rec.get("uuid"))
            if uid is not None:
                return ("uuid", uid)
            self._anonymous += 1
            return ("anonymous", str(self._anonymous))
        if self.mode == "request":
            return (rid or mid,)
        return (mid or "", rid or "")

    def add(self, info: FileInfo, rec: dict) -> Call | None:
        """Offer one record. Returns the call if this line is now the kept one."""
        key = self._key(rec)
        call = _call_from_record(info, rec, key)
        if call is None:
            return None
        old = self._calls.get(key)
        if old is None:
            self._calls[key] = call
            return call
        if self.mode == "message-request" and call.output_tokens >= old.output_tokens:
            self._calls[key] = call
            return call
        return None

    @property
    def calls(self) -> list[Call]:
        return list(self._calls.values())


# ---------------------------------------------------------------------------
# attachments
# ---------------------------------------------------------------------------
def attachment_from_record(info: FileInfo, rec: dict) -> Attachment | None:
    if rec.get("type") != "attachment":
        return None
    att = rec.get("attachment")
    if not isinstance(att, dict):
        return None
    try:
        size = len(json.dumps(att, separators=(",", ":"), ensure_ascii=False))
    except (TypeError, ValueError):
        return None
    return Attachment(
        project=info.project,
        session_id=info.session_id,
        is_subagent=info.is_subagent,
        agent_id=info.agent_id,
        subtype=_text(att.get("type")),
        size=size,
        timestamp=_text(rec.get("timestamp")),
    )


# ---------------------------------------------------------------------------
# high-level read
# ---------------------------------------------------------------------------
def read(root: Path, since: str | None = None, until: str | None = None) -> ReadResult:
    """Every de-duplicated call and attachment under ``root`` in the window.

    Reads every file: the window is judged on each call's own timestamp, never
    on file modification time (``iter_records(since=...)`` offers that shortcut).
    """
    coverage = Coverage()
    collector = CallCollector()
    attachments: list[Attachment] = []
    for info, rec in iter_records(root, coverage=coverage):
        collector.add(info, rec)
        att = attachment_from_record(info, rec)
        if att is not None and in_window(att.timestamp, since, until):
            attachments.append(att)
    calls = [c for c in collector.calls if in_window(c.timestamp, since, until)]
    return ReadResult(calls=calls, attachments=attachments, coverage=coverage)
