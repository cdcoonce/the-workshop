#!/usr/bin/env python3
"""PostToolUse hook script — validates frontmatter on every Write/Edit to .md files.

Called by Claude Code after Write/Edit tool completions.
Reads hook event JSON from stdin, validates the target file, and outputs
structured feedback via hookSpecificOutput.

Also warns — never blocks — when the write cites an auto-memory that was never
promoted into the vault (see ``unpromoted_memory``). That lane is advisory by
design: a forward reference, where the target note is written moments later, is
ordinary practice, so blocking it would make the correct workflow impossible.

Exit codes:
    0 — validation passed (or file excluded)
    1 — blocking validation errors found
    2 — non-blocking warnings only (YAML parse errors, unpromoted memory links)
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

# Add scripts dir to path so we can import frontmatter_engine
SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from frontmatter_engine import validate, ValidationError
import vault_utils


def _unpromoted_memory_lines(file_path: Path, vault_root: Path) -> list[str]:
    """Advisory lines for auto-memories cited but never promoted. Never raises.

    Import is deferred and the whole lane is wrapped: it reaches graphmark through a
    subprocess, and no failure there may cost the author their frontmatter feedback.
    The cheap pre-filter runs first so the ordinary write pays no subprocess at all.
    """
    try:
        from unpromoted_memory import (
            format_warning,
            has_candidate_memory_link,
            unpromoted_memory_links,
        )

        if not has_candidate_memory_link(file_path, vault_root):
            return []
        rel = str(file_path.resolve().relative_to(vault_root.resolve()))
        return format_warning(unpromoted_memory_links(vault_root, rel))
    except Exception:
        traceback.print_exc(file=sys.stderr)
        return []


def main() -> int:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return 0

        event = json.loads(raw)
    except Exception:
        # Malformed input — silently exit, don't crash the hook
        return 0

    # Extract the file path from the hook event
    # Claude Code PostToolUse events include tool_input with file_path
    tool_input = event.get("tool_input", {})
    file_path_str = tool_input.get("file_path", "")

    if not file_path_str:
        return 0

    file_path = Path(file_path_str)

    # Only validate markdown files
    if file_path.suffix.lower() != ".md":
        return 0

    vault_root = vault_utils.find_vault_root(file_path.parent)

    if vault_root is None:
        return 0  # Not in a vault — skip

    # Run validation
    try:
        errors = validate(file_path, vault_root)
    except Exception:
        # Engine crash — output traceback to stderr, don't block
        traceback.print_exc(file=sys.stderr)
        msg = json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": "⚠️ Frontmatter validation crashed. Check stderr for details.",
            }
        })
        print(msg)
        return 2

    # Advisory lane. Deliberately NOT gated on _is_excluded: that answers "must this
    # file carry frontmatter?", which is a different question from "do this file's
    # wikilinks count in the graph?". `thinking/` is exempt from the first and fully
    # subject to the second, so gating on it silenced the check on notes that can
    # still fail vault_health. graphmark is the authority — a file outside graph
    # scope never appears in its broken map, so no gate is needed here.
    memory_lines = _unpromoted_memory_lines(file_path, vault_root)

    if not errors and not memory_lines:
        return 0

    # Separate blocking errors from warnings
    blocking = [e for e in errors if e.severity == "error"]
    warnings = [e for e in errors if e.severity == "warning"]

    lines: list[str] = []

    if memory_lines:
        lines.extend(memory_lines)
        lines.append("")

    if warnings:
        lines.append("⚠️ Frontmatter warnings:")
        for w in warnings:
            lines.append(f"  • {w.field}: {w.message}")
        lines.append("")

    if blocking:
        lines.append("❌ Frontmatter validation failed:")
        for e in blocking:
            lines.append(f"  • {e.field}: {e.message}")
        lines.append("")
        lines.append("Fix these issues before proceeding.")

    output = json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": "\n".join(lines),
        }
    })
    print(output)

    return 1 if blocking else 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc(file=sys.stderr)
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": "⚠️ Frontmatter hook crashed unexpectedly. Check stderr.",
            }
        }))
        sys.exit(2)
