#!/usr/bin/env python3
"""Audit a ``/cold-read`` reader's transcript and print what the reader did.

Incident: on 2026-10-10 three of the first six cold reads were degraded (no
probe build, earlier verdicts seen, a detector command denied), and each was
found only because the reader said so in its own report. Nothing in the engine
inspected what a reader actually did, so a reader that did not notice would
have passed. The report is the reader's own account; the transcript is the
record. This script reads the record. ``is_error`` is true for any non-zero
exit status, so it cannot stand in for a refusal: a refusal is a
``toolDenialKind`` or ``permissionDecision`` on the result's record, or an
error whose text begins ``Permission for this action``.

Usage::

    python3 "<engine>/cold_read_audit.py" --transcript FILE --issue N
        [--role cold|fidelity] [--scratch-dir DIR] [--meta FILE]
        [--expect-agent-type TYPE] [--allow-partial] [--details] [--json]

The transcript is one JSON object per line (observed in Claude Code 2.1.293).
A ``tool_use`` is a block of an assistant record's ``message.content``; its
``tool_result`` is a block of a later user record, matched by ``tool_use_id``
and never by adjacency. A line ends at ``\\n`` only. A line that is not a JSON
object is counted in ``bad_lines`` and skipped. Every field of the file is
untrusted, and the file is decoded with ``errors="replace"``.

The report is one line ``AUDIT key=value ...`` with the keys, in order,
``version``, ``complete``, ``bad_lines``, ``agent_type``, ``model``,
``bash_calls``, ``scratch``, ``probe_build``, ``gh_calls``, ``comments_fetch``,
``comments_seen``, ``denied``, ``preflight`` and ``flags``; ``--json`` prints
the same keys as one object (counts are integers, ``flags`` is one string).
``--details`` adds one ``DETAIL`` line per flagged ``Bash`` command, so the
conductor confirms a flag before acting on it. The rules behind each token are
the ``Tokens`` section of the-workshop#1179.

Exit codes: 0 audited, 2 usage error or a transcript path that is missing or
unreadable, 3 transcript incomplete without ``--allow-partial`` (the report is
printed first). The transcript and the meta file are opened for reading only.
The script never posts a comment, applies a label, voids a read or edits an
issue, and imports no module that could. Stdlib only: ``evals/`` is not
shipped in the plugin, so the JSONL is parsed here.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

UNKNOWN = "unknown"
BASH_TOOL = "Bash"
HANDBACK_TOOL = "SubagentHandback"
PREFLIGHT_OK = "PREFLIGHT ok"
PREFLIGHT_FAILED = "PREFLIGHT failed"
DENIAL_PREFIX = "Permission for this action"
COLD_READ_MARKER = "## Cold read"
COMMAND_LIMIT = 170
RESULT_LIMIT = 120

TOKEN_ORDER = (
    "version",
    "complete",
    "bad_lines",
    "agent_type",
    "model",
    "bash_calls",
    "scratch",
    "probe_build",
    "gh_calls",
    "comments_fetch",
    "comments_seen",
    "denied",
    "preflight",
    "flags",
)

# `scratch` without --scratch-dir, and `probe_build`: both read the whole
# command, heredoc bodies included, because a mutation driver or a scratch
# directory made inside a heredoc is still one.
SCRATCH_PATTERN = re.compile(r"\bmktemp\b|\bmkdir\b|\btempfile\b|\bgit\s+(archive|clone|worktree\s+add)\b")
PROBE_PATTERN = re.compile(r"(?<![\w./-])pytest(?![\w/-])|teeth_check\.py|(?<![\w./-])make\s+\S")

# A heredoc opener: <<W, <<'W', <<"W" or <<-W; <<< is a here-string.
HEREDOC_PATTERN = re.compile(r"(?<!<)<<(?!<)(-?)(?:\x27([^\x27\n]*)\x27|\x22([^\x22\n]*)\x22|([^\s;&|<>()\x27\x22`]+))")

# `gh` as a program at a command position: the start of the command or of any
# line, after a separator or a keyword, after leading NAME=value assignments.
SEPARATORS = r"[;&|(`]"
KEYWORDS = r"(?<![\w./-])(?:do|then|else|if|xargs)(?![\w./-])"
BANG = r"(?<!\S)!(?=\s)"
COMMAND_POSITION = rf"(?:^|{SEPARATORS}|{KEYWORDS}|{BANG})"
ASSIGNMENT = r"(?:[A-Za-z_]\w*=(?:\x22[^\x22]*\x22|\x27[^\x27]*\x27|\S*)\s+)*"
PROGRAM = r"(?P<program>(?:[^\s;&|()`\x22\x27]*/)?gh)(?![\w./=-])"
GH_PATTERN = re.compile(COMMAND_POSITION + r"\s*" + ASSIGNMENT + PROGRAM, re.MULTILINE)
SEGMENT_END = re.compile(r"[;&|\n]")
VIEW_PATTERN = re.compile(r"(?<![\w-])(?:issue|pr)\s+view(?![\w-])")
COMMENTS_ARGUMENT = re.compile(r"(?<!\S)(?:-c|--comments)(?!\S)")
COMMENTS_LIST_PATTERN = re.compile(r'"comments":\s*\[\s*\{')


@dataclass
class ToolResult:
    """One ``tool_result``: its flattened text, its error flag, and whether it was denied."""

    text: str
    is_error: bool
    denied: bool


@dataclass
class ToolUse:
    """One ``tool_use`` and what the audit works out about it."""

    id: object
    name: object
    command: str
    result: ToolResult | None = None
    preflight: str | None = None
    gh: bool = False
    fetch: bool = False
    seen: bool = False


def _token(value: str) -> str:
    """Return *value* with every run of whitespace made one ``_``, so it fits one report token."""
    return "_".join(value.split())


def parse_lines(data: bytes) -> tuple[list[dict], int]:
    """Parse *data* as JSON Lines, returning the records and the count of bad lines.

    A line ends at ``\\n`` only; U+2028, U+2029 and U+0085 inside a line do not
    end it. A blank line is skipped and not counted; any other line that is not
    a JSON object is counted and skipped.

    Parameters
    ----------
    data : bytes
        The transcript file's bytes, decoded here with ``errors="replace"``.

    Returns
    -------
    tuple[list[dict], int]
        The records in file order and the number of non-blank lines that are
        not a JSON object.
    """
    records: list[dict] = []
    bad_lines = 0
    for line in data.decode("utf-8", errors="replace").split("\n"):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except (ValueError, RecursionError):
            record = None
        if isinstance(record, dict):
            records.append(record)
        else:
            bad_lines += 1
    return records, bad_lines


def _text_of(content: object) -> str:
    """Flatten a result's ``content`` (a string, or a list of text blocks) to text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "\n".join(parts)
    return ""


def _blocks(message: dict) -> list[dict]:
    """Return the object blocks of ``message.content``; a plain-string content carries none."""
    content = message.get("content")
    if not isinstance(content, list):
        return []
    return [block for block in content if isinstance(block, dict)]


def _is_denied(record: dict, text: str, is_error: bool) -> bool:
    """Whether the result held by *record* was refused, as opposed to merely failing."""
    kind = record.get("toolDenialKind")
    if kind and kind != "interrupted":
        return True
    decision = record.get("permissionDecision")
    if isinstance(decision, dict) and decision.get("decision") == "reject":
        return True
    return is_error and text.startswith(DENIAL_PREFIX)


def _tool_use(block: dict) -> ToolUse:
    tool_input = block.get("input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    return ToolUse(block.get("id"), block.get("name"), command if isinstance(command, str) else "")


_EXIT_CODE_LINE = re.compile(r"^Exit code [0-9]+\n")


def _preflight_kind(text: str) -> str | None:
    """``ok`` or ``failed`` when *text* begins a preflight result, else ``None``.

    One first line ``Exit code <N>``, which the harness writes for a command
    that exits non-zero, is skipped; the words must begin the rest.
    """
    text = _EXIT_CODE_LINE.sub("", text, count=1)
    if text.startswith(PREFLIGHT_OK):
        return "ok"
    if text.startswith(PREFLIGHT_FAILED):
        return "failed"
    return None


def _strip_heredocs(command: str) -> str:
    """Remove the bodies of the heredocs in *command*, keeping every other line.

    A body starts on the line after its opener and ends at a line equal to the
    word (tabs allowed before it for ``<<-`` only), or at the end of the
    command when there is none. The opener's own line stays.
    """
    kept: list[str] = []
    waiting: list[tuple[str, bool]] = []
    for line in command.split("\n"):
        if waiting:
            word, dashed = waiting[0]
            if (line.lstrip("\t") if dashed else line) == word:
                waiting.pop(0)
            continue
        kept.append(line)
        for match in HEREDOC_PATTERN.finditer(line):
            word = next(group for group in match.group(2, 3, 4) if group is not None)
            waiting.append((word, match.group(1) == "-"))
    return "\n".join(kept)


def _gh_segments(command: str) -> list[str]:
    """Return the segment of every ``gh`` invocation in *command*.

    A segment runs from ``gh`` to the next ``;``, ``&``, ``|`` or newline.
    Heredoc bodies are removed first.
    """
    body = _strip_heredocs(command)
    segments = []
    for match in GH_PATTERN.finditer(body):
        start = match.end("program") - len("gh")
        end = SEGMENT_END.search(body, match.end("program"))
        segments.append(body[start : end.start() if end else len(body)])
    return segments


def _fetches_comments(segment: str, issue: int) -> bool:
    """Whether a ``gh`` segment reads the comments of issue *issue*."""
    if not re.search(rf"(?<!\w){re.escape(str(issue))}(?!\w)", segment):
        return False
    if "comments" in segment:
        return True
    return bool(COMMENTS_ARGUMENT.search(segment) and VIEW_PATTERN.search(segment))


def _comments_seen(text: str) -> bool:
    """Whether a comments-fetch result shows that comments came back."""
    if COLD_READ_MARKER in text:
        return True
    if COMMENTS_LIST_PATTERN.search(text):
        return True
    try:
        payload = json.loads(text)
    except (ValueError, RecursionError):
        return False
    comments = payload.get("comments") if isinstance(payload, dict) else None
    return isinstance(comments, list) and bool(comments)


def _scratch_dir_pattern(scratch_dir: str) -> re.Pattern[str]:
    """A pattern matching *scratch_dir* as a whole path, not as the prefix of a longer name."""
    path = scratch_dir.rstrip("/") or "/"
    return re.compile(re.escape(path) + r"(?![\w-])")


def _scratch(role: str, bash_uses: list[ToolUse], scratch_dir: str | None) -> str:
    if role != "cold":
        return "na"
    pattern = _scratch_dir_pattern(scratch_dir) if scratch_dir else SCRATCH_PATTERN
    for use in bash_uses:
        if use.preflight or use.result is None or use.result.is_error:
            continue
        if pattern.search(use.command):
            return "ok"
    return "none"


def _probe_build(role: str, bash_uses: list[ToolUse]) -> str:
    if role != "cold":
        return "na"
    for use in bash_uses:
        if use.preflight or use.result is None:
            continue
        if PROBE_PATTERN.search(use.command):
            return "ran"
    return "none"


def _read_agent_type(path: Path) -> str:
    """``agentType`` of the meta file at *path*, or ``unknown`` when it cannot be read."""
    try:
        payload = json.loads(path.read_bytes().decode("utf-8", errors="replace"))
    except (OSError, ValueError, RecursionError):
        return UNKNOWN
    agent = payload.get("agentType") if isinstance(payload, dict) else None
    if isinstance(agent, str) and _token(agent):
        return _token(agent)
    return UNKNOWN


def _sibling_meta(transcript: Path) -> Path:
    """The meta file beside *transcript* with the same stem (``agent-<id>.meta.json``)."""
    return transcript.with_name(transcript.stem + ".meta.json")


def audit(
    data: bytes,
    *,
    issue: int,
    role: str,
    scratch_dir: str | None,
    agent_type: str,
    expect_agent_type: str | None,
    details: bool,
) -> dict:
    """Audit one transcript.

    Parameters
    ----------
    data : bytes
        The transcript file's bytes.
    issue : int
        The issue the reader was reading; decides which ``gh`` calls fetch its comments.
    role : str
        ``cold`` or ``fidelity``.
    scratch_dir : str | None
        The reader's scratch directory, when the conductor knows it.
    agent_type : str
        The ``agentType`` of the meta file, or ``unknown``.
    expect_agent_type : str | None
        The agent type the reader should have been dispatched as.
    details : bool
        Whether to add the ``details`` list.

    Returns
    -------
    dict
        The tokens, keyed in ``TOKEN_ORDER`` with counts as integers, plus
        ``details`` when requested. ``complete`` is an integer 0 or 1.
    """
    records, bad_lines = parse_lines(data)
    version = UNKNOWN
    models: list[str] = []
    uses: list[ToolUse] = []
    use_ids: set[str] = set()
    results: dict[str, ToolResult] = {}
    denied = 0
    last_stop: object = None
    for record in records:
        recorded = record.get("version")
        if version == UNKNOWN and isinstance(recorded, str) and _token(recorded):
            version = _token(recorded)
        message = record.get("message")
        if not isinstance(message, dict):
            continue
        model = message.get("model")
        if isinstance(model, str) and _token(model) and _token(model) not in models:
            models.append(_token(model))
        kind = record.get("type")
        if kind == "assistant":
            last_stop = message.get("stop_reason")
            for block in _blocks(message):
                if block.get("type") != "tool_use":
                    continue
                use = _tool_use(block)
                if isinstance(use.id, str):
                    if use.id in use_ids:
                        continue
                    use_ids.add(use.id)
                uses.append(use)
        elif kind == "user":
            for block in _blocks(message):
                if block.get("type") != "tool_result":
                    continue
                text = _text_of(block.get("content"))
                is_error = block.get("is_error") is True
                result = ToolResult(text, is_error, _is_denied(record, text, is_error))
                tool_use_id = block.get("tool_use_id")
                if isinstance(tool_use_id, str):
                    if tool_use_id in results:
                        continue
                    results[tool_use_id] = result
                denied += result.denied
    for use in uses:
        if isinstance(use.id, str):
            use.result = results.get(use.id)
    bash_uses = [use for use in uses if use.name == BASH_TOOL]
    for use in bash_uses:
        if use.result is not None:
            use.preflight = _preflight_kind(use.result.text)
        segments = _gh_segments(use.command)
        use.gh = bool(segments)
        use.fetch = any(_fetches_comments(segment, issue) for segment in segments)
        use.seen = use.fetch and use.result is not None and _comments_seen(use.result.text)
    complete = last_stop == "end_turn" or any(use.name == HANDBACK_TOOL for use in uses)
    preflight_uses = [use for use in bash_uses if use.preflight]
    preflight = preflight_uses[0].preflight if preflight_uses else "none"
    scratch = _scratch(role, bash_uses, scratch_dir)
    probe_build = _probe_build(role, bash_uses)
    gh_calls = sum(use.gh for use in bash_uses)
    comments_seen = int(any(use.seen for use in bash_uses))
    mismatch = expect_agent_type is not None and agent_type != UNKNOWN and agent_type != _token(expect_agent_type)
    failed_then_went_on = preflight == "failed" and any(
        use is not preflight_uses[0] and use.name != HANDBACK_TOOL for use in uses
    )
    flags = []
    if role == "cold" and scratch == "none":
        flags.append("scratch-none")
    if role == "cold" and probe_build == "none":
        flags.append("no-probe-build")
    if comments_seen:
        flags.append("comments-read")
    if gh_calls:
        flags.append("gh-used")
    if denied:
        flags.append("denied")
    if mismatch:
        flags.append("agent-type")
    if preflight == "none":
        flags.append("preflight-none")
    if failed_then_went_on:
        flags.append("preflight-failed")
    report: dict = {
        "version": version,
        "complete": int(complete),
        "bad_lines": bad_lines,
        "agent_type": agent_type,
        "model": ",".join(sorted(models)) or UNKNOWN,
        "bash_calls": len(bash_uses),
        "scratch": scratch,
        "probe_build": probe_build,
        "gh_calls": gh_calls,
        "comments_fetch": sum(use.fetch for use in bash_uses),
        "comments_seen": comments_seen,
        "denied": denied,
        "preflight": preflight,
        "flags": ",".join(flags) or "none",
    }
    if details:
        report["details"] = _details(bash_uses)
    return report


def _details(bash_uses: list[ToolUse]) -> list[dict]:
    """One entry per ``Bash`` command that carries ``comments-read``, ``gh-used`` or ``denied``."""
    entries = []
    for use in bash_uses:
        carried = []
        if use.seen:
            carried.append("comments-read")
        if use.gh:
            carried.append("gh-used")
        if use.result is not None and use.result.denied:
            carried.append("denied")
        if not carried:
            continue
        entries.append(
            {
                "id": _token(str(use.id)),
                "flags": ",".join(carried),
                "command": use.command[:COMMAND_LIMIT],
                "result": None if use.result is None else use.result.text[:RESULT_LIMIT],
            }
        )
    return entries


def _render(report: dict) -> str:
    lines = ["AUDIT " + " ".join(f"{key}={report[key]}" for key in TOKEN_ORDER)]
    for entry in report.get("details", []):
        lines.append(
            f"DETAIL id={entry['id']} flags={entry['flags']} "
            f"command={json.dumps(entry['command'])} result={json.dumps(entry['result'])}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--transcript", required=True, metavar="FILE", help="the reader's transcript, JSON Lines")
    parser.add_argument("--issue", required=True, type=int, metavar="N", help="the issue the reader read")
    parser.add_argument("--role", choices=("cold", "fidelity"), default="cold", help="the reader's role")
    parser.add_argument("--scratch-dir", metavar="DIR", help="the reader's scratch directory")
    parser.add_argument("--meta", metavar="FILE", help="the reader's meta file (default: beside the transcript)")
    parser.add_argument("--expect-agent-type", metavar="TYPE", help="the agent type the reader should be")
    parser.add_argument("--allow-partial", action="store_true", help="exit 0 on an incomplete transcript")
    parser.add_argument("--details", action="store_true", help="list the flagged commands")
    parser.add_argument("--json", action="store_true", help="print one JSON object instead of the AUDIT line")
    args = parser.parse_args(argv)
    transcript = Path(args.transcript)
    try:
        data = transcript.read_bytes()
    except OSError as error:
        print(f"cold_read_audit: cannot read transcript {transcript}: {error.strerror or error}", file=sys.stderr)
        return 2
    meta = Path(args.meta) if args.meta else _sibling_meta(transcript)
    report = audit(
        data,
        issue=args.issue,
        role=args.role,
        scratch_dir=args.scratch_dir,
        agent_type=_read_agent_type(meta),
        expect_agent_type=args.expect_agent_type,
        details=args.details,
    )
    print(json.dumps(report) if args.json else _render(report))
    if not report["complete"] and not args.allow_partial:
        print("cold_read_audit: transcript incomplete (no end_turn, no hand-back call)", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
