#!/usr/bin/env python3
"""PostToolUse hook script — validates frontmatter on every Write/Edit to .md files.

Called by Claude Code after Write/Edit tool completions.
Reads hook event JSON from stdin, validates the target file, and outputs
structured feedback via hookSpecificOutput.

Exit codes:
    0 — validation passed (or file excluded)
    1 — blocking validation errors found
    2 — non-blocking warnings only (YAML parse errors)
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

    # Find vault root by walking up to AGENTS.md or CLAUDE.md
    vault_root = None
    for parent in [file_path.parent, *file_path.parents]:
        if (parent / "AGENTS.md").exists() or (parent / "CLAUDE.md").exists():
            vault_root = parent
            break

    if vault_root is None:
        return 0  # Not in a vault — skip

    # Run validation
    try:
        errors = validate(file_path, vault_root)
    except Exception:
        # Engine crash — output traceback to stderr, don't block
        traceback.print_exc(file=sys.stderr)
        msg = json.dumps({
            "hookSpecificOutput": "⚠️ Frontmatter validation crashed. Check stderr for details."
        })
        print(msg)
        return 2

    if not errors:
        return 0

    # Separate blocking errors from warnings
    blocking = [e for e in errors if e.severity == "error"]
    warnings = [e for e in errors if e.severity == "warning"]

    lines: list[str] = []

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

    output = json.dumps({"hookSpecificOutput": "\n".join(lines)})
    print(output)

    return 1 if blocking else 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc(file=sys.stderr)
        print(json.dumps({
            "hookSpecificOutput": "⚠️ Frontmatter hook crashed unexpectedly. Check stderr."
        }))
        sys.exit(2)
