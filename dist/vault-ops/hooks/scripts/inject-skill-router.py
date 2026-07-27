# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""SessionStart hook: inject the skill router and preset conventions as additionalContext.

Shipped inside every project preset plugin. On session start Claude Code runs it via
`uv run`; it reads the plugin's `skills/using-workflow/SKILL.md`, strips the YAML
frontmatter, and appends the preset's `conventions.json` (written by build_preset.py)
as a bullet list, then emits the combined text as SessionStart `additionalContext` so
the skill-invocation rules and project conventions are layered on top of the default
engineering instructions (purely additive — it never replaces the base prompt).

The router body is byte-identical in every preset that ships this hook, and Claude
Code runs each installed copy on SessionStart — so the body is claimed once per
`session_id` and later copies emit only their own conventions. Deduplication is a
pure optimization: if the claim cannot be recorded, the body is emitted anyway.

Cross-platform by design: pure Python via `uv run`, no bash. Fails safe — any error
prints nothing and exits 0, so an unbuilt or broken plugin can never break a session.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path


def _strip_frontmatter(text: str) -> str:
    """Return the markdown body with a leading YAML frontmatter block removed."""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return parts[2].strip()
    return text.strip()


def _format_conventions(conventions: list[str]) -> str:
    """Render a preset's conventions array as a markdown bullet list."""
    bullets = "\n".join(f"- {convention}" for convention in conventions)
    return f"## Project Conventions\n\n{bullets}"


def _claim_router_body(session_id: str | None) -> bool:
    """Return True if this process is the one that should emit the router body.

    The claim is an exclusive-create of a per-session marker, so concurrent hook
    copies cannot both win. Any failure to record the claim returns True: a
    duplicated router is a wasted paragraph, a missing one changes behavior.
    """
    if not session_id:
        return True
    try:
        # `TMPDIR` first, uncached: `tempfile.gettempdir()` memoizes its answer and
        # silently discards a TMPDIR that is not a usable directory, which would
        # send markers to the real /tmp instead of reporting the failure.
        base = os.environ.get("TMPDIR") or tempfile.gettempdir()
        marker_dir = Path(base, "the-workshop-skill-router")
        marker_dir.mkdir(parents=True, exist_ok=True)
        safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in session_id)
        os.close(
            os.open(
                marker_dir / f"{safe_id}.claim",
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
        )
    except FileExistsError:
        return False
    except OSError:
        return True
    return True


def _read_session_id() -> str | None:
    """Read `session_id` from the SessionStart payload, if a payload arrives at all."""
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return None
        raw = sys.stdin.read()
    except (OSError, ValueError):
        return None
    if not raw.strip():
        return None  # Codex delivers hooks no stdin payload.
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    session_id = data.get("session_id") if isinstance(data, dict) else None
    return session_id if isinstance(session_id, str) else None


def main(session_id: str | None = None) -> int:
    root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if not root:
        return 0  # fail safe: nothing to inject

    skill_path = Path(root, "skills", "using-workflow", "SKILL.md")
    if not skill_path.is_file():
        return 0

    body = _strip_frontmatter(skill_path.read_text(encoding="utf-8"))
    if not body:
        return 0

    conventions_path = Path(root, "conventions.json")
    if not conventions_path.is_file():
        return 0

    try:
        data = json.loads(conventions_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return 0

    conventions = data.get("conventions") if isinstance(data, dict) else None
    if not isinstance(conventions, list) or not all(
        isinstance(c, str) for c in conventions
    ):
        return 0

    formatted_conventions = _format_conventions(conventions)
    context = (
        f"{body}\n\n{formatted_conventions}"
        if _claim_router_body(session_id)
        else formatted_conventions
    )

    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": context,
                }
            }
        )
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(session_id=_read_session_id()))
    except Exception:
        # Never let the skill router hook break a session.
        sys.exit(0)
