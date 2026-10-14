# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""UserPromptSubmit hook: tell the user (not the agent) once the session's context grows large.

Claude Code exposes no context-window size to hooks, so this derives it from the
transcript. The most recent assistant message's usage
(``input_tokens + cache_read_input_tokens + cache_creation_input_tokens``) is the
token count sent on that request — i.e. the live context size. When it crosses a
threshold (default 300k, override with ``WORKSHOP_HANDOFF_CONTEXT_TOKENS``) the hook
prints one top-level ``systemMessage`` reporting the reading, and nothing else.

The audience is the point. ``additionalContext`` and plain stdout reach the model as
a system-reminder the agent treats as the user's voice, and the user never sees
them. The session lifecycle is the user's call — the vault forbids agents suggesting
``/wrap-up`` or a fresh session — so this hook cannot steer it from that channel.
``systemMessage`` is shown to the user and is not added to the model's context. The
owner kept the 300k instrument (#518, 2026-07-26), so only the audience changed.
stdout must be exactly one JSON object: any stray output turns the whole of it into
plain-text context for the agent. The script name, env var, and marker dir keep
their historical "handoff" spelling so installed configs and overrides keep working.

Fires at most once per large-context episode: a marker file keyed on ``session_id``
(or, when a host omits one, a hash of the transcript path) is written on first trigger,
holding the measured token count, and suppresses later turns. ``/clear`` and compaction
keep the ``session_id`` but collapse the measured context, so while the marker is armed
the transcript is still measured: a reading below the re-arm floor (``threshold // 2``)
deletes the marker, and the next crossing warns again. A legacy empty or unreadable
marker counts as armed-with-unknown-count.

Agnostic + fail-open by design: stdlib only, no bash. A malformed payload, an
unreadable transcript, or a host that never sends ``transcript_path`` (Codex, Cortex
Code) all make it a silent no-op that exits 0 — it can never block a prompt.
"""

from __future__ import annotations

# scripts/stamp.py statically reads this constant to build hooks/hooks.json.
WORKSHOP_HOOK = {"event": "UserPromptSubmit"}

import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

DEFAULT_THRESHOLD = 300_000
_MARKER_DIRNAME = "workshop-handoff-gate"


def _threshold() -> int:
    """Context-token threshold; overridable via WORKSHOP_HANDOFF_CONTEXT_TOKENS."""
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

    Scans the JSONL transcript from the end and returns the first main-thread
    (non-sidechain) assistant usage found as input + cache-read + cache-creation tokens. Returns None when the file
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
        if record.get("isSidechain") is True:
            continue  # subagent turn: its usage is not the main thread's context
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


def _rearm_if_collapsed(marker: Path, context_tokens: int | None, threshold: int) -> bool:
    """Delete the marker when context fell below the re-arm floor.

    Returns True when the marker was removed (the hook is armed again). An
    unreadable transcript (``None``) never re-arms.
    """
    if context_tokens is None or context_tokens >= threshold // 2:
        return False
    try:
        marker.unlink(missing_ok=True)
    except OSError:
        return False
    return True


def _arm(marker: Path, context_tokens: int = 0) -> None:
    """Best-effort marker write; failure just means a possible repeat warning."""
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(str(context_tokens), encoding="utf-8")
    except OSError:
        pass


def _message(context_tokens: int, threshold: int) -> str:
    used_k = round(context_tokens / 1000)
    limit_k = round(threshold / 1000)
    return (
        f"Context checkpoint: this session's context is ~{used_k}k tokens "
        f"(threshold {limit_k}k; set WORKSHOP_HANDOFF_CONTEXT_TOKENS to change it)."
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
    threshold = _threshold()
    context_tokens = _context_tokens(Path(transcript_path))
    if _already_warned(marker) and not _rearm_if_collapsed(
        marker, context_tokens, threshold
    ):
        return 0  # armed and context has not collapsed: once per episode

    if context_tokens is None or context_tokens < threshold:
        return 0

    _arm(marker, context_tokens)
    print(json.dumps({"systemMessage": _message(context_tokens, threshold)}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # Never let the context-checkpoint hook break a prompt.
        sys.exit(0)
