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

Cross-platform by design: pure Python via `uv run`, no bash. Fails safe — any error
prints nothing and exits 0, so an unbuilt or broken plugin can never break a session.
"""

from __future__ import annotations

import json
import os
import sys
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


def main() -> int:
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

    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": f"{body}\n\n{_format_conventions(conventions)}",
                }
            }
        )
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # Never let the skill router hook break a session.
        sys.exit(0)
