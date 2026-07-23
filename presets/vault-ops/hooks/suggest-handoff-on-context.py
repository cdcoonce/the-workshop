# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""UserPromptSubmit hook: suggest /handoff once the session's context grows large.

Claude Code exposes no context-window size to hooks, so this derives it from the
transcript. The most recent assistant message's usage
(``input_tokens + cache_read_input_tokens + cache_creation_input_tokens``) is the
token count sent on that request — i.e. the live context size. When it crosses a
threshold (default 300k, override with ``WORKSHOP_HANDOFF_CONTEXT_TOKENS``) the hook
emits UserPromptSubmit ``additionalContext`` telling Claude to suggest the user run
``/handoff`` to refresh the rolling orchestrator handoff. It suggests, never invokes.

Fires at most once per session: a marker file keyed on ``session_id`` (or, when a host
omits one, a hash of the transcript path) is written on first trigger and suppresses
every later turn. The marker is checked before the transcript is parsed, so once armed
the hook is effectively free.

Agnostic + fail-open by design: stdlib only, no bash. A malformed payload, an
unreadable transcript, or a host that never sends ``transcript_path`` (Codex, Cortex
Code) all make it a silent no-op that exits 0 — it can never block a prompt.
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

DEFAULT_THRESHOLD = 300_000
_MARKER_DIRNAME = "claude-workflow-handoff-gate"


def _threshold() -> int:
    """Context-token threshold; overridable via WORKSHOP_HANDOFF_CONTEXT_TOKENS."""
    import os

    raw = os.environ.get("WORKSHOP_HANDOFF_CONTEXT_TOKENS")
    if raw:
        try:
            value = int(raw)
        except ValueError:
            return DEFAULT_THRESHOLD
        if value > 0:
            return value
    return DEFAULT_THRESHOLD


def _context_tokens(transcript_path: Path) -> int | None:
    """Return the live context size from the last assistant message's usage.

    Scans the JSONL transcript from the end and returns the first assistant usage
    found as input + cache-read + cache-creation tokens. Returns None when the file
    is unreadable or contains no usage-bearing assistant message.
    """
    try:
        lines = transcript_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None

    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict) or record.get("type") != "assistant":
            continue
        message = record.get("message")
        if not isinstance(message, dict):
            continue
        usage = message.get("usage")
        if not isinstance(usage, dict):
            continue
        total = 0
        for field in (
            "input_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
        ):
            value = usage.get(field)
            if isinstance(value, int):
                total += value
        return total
    return None


def _session_key(data: dict, transcript_path: str) -> str:
    """Stable per-session key: session_id when present, else a transcript hash."""
    session_id = data.get("session_id")
    if isinstance(session_id, str) and session_id:
        raw = session_id
    else:
        raw = transcript_path
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _marker_path(key: str) -> Path:
    return Path(tempfile.gettempdir(), _MARKER_DIRNAME, key)


def _already_warned(marker: Path) -> bool:
    return marker.exists()


def _arm(marker: Path) -> None:
    """Best-effort marker write; failure just means a possible repeat warning."""
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("", encoding="utf-8")
    except OSError:
        pass


def _message(context_tokens: int, threshold: int) -> str:
    used_k = round(context_tokens / 1000)
    limit_k = round(threshold / 1000)
    return (
        f"[context checkpoint] This session has used ~{used_k}k tokens of context "
        f"(threshold {limit_k}k). Tell the user it's a good moment to run `/handoff` "
        "to refresh the rolling orchestrator handoff so work can continue cleanly in a "
        "fresh session. Mention it once, then carry on with their request — do not run "
        "`/handoff` automatically."
    )


def main() -> int:
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return 0
    if not isinstance(data, dict):
        return 0

    transcript_path = data.get("transcript_path")
    if not isinstance(transcript_path, str) or not transcript_path:
        return 0  # agnostic: hosts without a transcript can't be measured
    if not Path(transcript_path).is_file():
        return 0

    marker = _marker_path(_session_key(data, transcript_path))
    if _already_warned(marker):
        return 0  # once per session — cheap short-circuit before parsing

    context_tokens = _context_tokens(Path(transcript_path))
    if context_tokens is None or context_tokens < _threshold():
        return 0

    _arm(marker)
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": _message(context_tokens, _threshold()),
                }
            }
        )
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # Never let the handoff-suggestion hook break a prompt.
        sys.exit(0)
