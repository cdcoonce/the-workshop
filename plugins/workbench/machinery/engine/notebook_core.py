"""Pure helpers for session-notebook distillation.

Extracted from the hyphenated (non-importable) ``notebook-distill.py`` hook so the
transcript-parsing and prompt-building logic is unit-testable — mirrors how
``session_terms.py`` was extracted from ``session-stop.py`` and
``transcript_backup.py`` from ``pre-compact.py``. These functions do no network
or model I/O; ``latest_turn`` reads a transcript file but is otherwise pure.
"""

from __future__ import annotations

import json
from pathlib import Path

MAX_TURN_CHARS = 3000  # cap per side fed to the distiller

NOTEBOOK_SKELETON = """\
# Session Notebook — {context_title}

_Live session state · updated {stamp} · session {sid}_

## Now

(what we're actively doing — 1-2 sentences)

## Established (don't re-derive)

(durable facts and decisions locked this session — the "don't make me repeat myself" list)

## Open loops

(unfinished threads / next steps this session)

## Touched

(files or notes created or edited this session)
"""


def valid_session_id(value: object) -> bool:
    """Whether an opaque session identity is safe inside a notebook filename.

    Parameters
    ----------
    value : object
        The session identity supplied by the runtime event.

    Returns
    -------
    bool
        True for a nonempty string without path separators or NUL characters.
        No platform-specific UUID shape is assumed.
    """
    return isinstance(value, str) and bool(value) and not any(c in value for c in "/\\\0")


def _block_text(message: dict) -> str:
    """Flatten an assistant/user message's content blocks to plain text."""
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    parts: list[str] = []
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") in ("text", "input_text", "output_text"):
                text = block.get("text", "")
                if isinstance(text, str):
                    parts.append(text)
    return "\n".join(parts)


def latest_turn(transcript_path: Path, max_turn_chars: int = MAX_TURN_CHARS) -> tuple[str, str]:
    """Return the latest user/assistant text from a Claude or Codex transcript.

    Each side is truncated to its last ``max_turn_chars`` characters. Fail-soft:
    a missing/unreadable file or malformed lines yield empty strings, never a raise.
    """
    try:
        content = transcript_path.read_text(encoding="utf-8")
    except OSError:
        return "", ""
    return latest_turn_from_text(content, max_turn_chars)


def latest_turn_from_text(content: str, max_turn_chars: int = MAX_TURN_CHARS) -> tuple[str, str]:
    """Parse the latest turn from one already-read transcript snapshot.

    Parameters
    ----------
    content : str
        Claude or Codex JSONL transcript text. Malformed records are skipped.
    max_turn_chars : int
        Maximum characters retained from the end of each side's latest text.

    Returns
    -------
    tuple[str, str]
        Latest user and assistant text; either side is empty when absent.
    """
    last_user = ""
    last_assistant = ""
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        etype = entry.get("type")
        message = entry.get("message")
        if etype == "response_item":
            # Native Codex rollout records wrap conversation messages in
            # payload. event_msg contains duplicate notifications, not an
            # additional turn, so only response_item is adapted here.
            message = entry.get("payload")
            if not isinstance(message, dict) or message.get("type") != "message":
                continue
            etype = message.get("role")
        if not isinstance(message, dict):
            continue
        text = _block_text(message).strip()
        if not text:
            continue
        if etype == "user":
            last_user = text
        elif etype == "assistant":
            last_assistant = text
    return last_user[-max_turn_chars:], last_assistant[-max_turn_chars:]


def build_prompt(current_notebook: str, user_text: str, assistant_text: str) -> str:
    return f"""\
You maintain a LIVE SESSION NOTEBOOK for an AI pair-working session. It is the \
session's short-term memory — the thing that lets the assistant resume cleanly \
after the raw conversation history is cleared.

Given the CURRENT NOTEBOOK and the LATEST TURN, output the UPDATED notebook.

Rules:
- MERGE new signal into the right section. Do not blindly append.
- Preserve durable facts and decisions already captured under "Established".
- Drop noise: acknowledgements, tool chatter, restated context, pleasantries.
- Keep the whole notebook under ~350 words. Tighten old entries if needed.
- Use [[wikilinks]] for vault notes, people, and projects when they appear.
- Keep the exact section skeleton (Now / Established / Open loops / Touched).
- If the turn adds nothing durable, return the notebook essentially unchanged.
- Output ONLY the notebook markdown. No preamble, no code fences, no commentary.

=== CURRENT NOTEBOOK ===
{current_notebook}

=== LATEST TURN (user) ===
{user_text}

=== LATEST TURN (assistant) ===
{assistant_text}
"""
