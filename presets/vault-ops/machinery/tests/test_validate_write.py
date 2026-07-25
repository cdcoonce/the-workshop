"""Exit-code contract tests for the validate-write.py PostToolUse hook.

The hook is invoked by Claude Code as a subprocess with a hook-event JSON on
stdin. Its documented contract is:
    exit 0 — validation passed (or file excluded / no-op)
    exit 1 — blocking validation errors
    exit 2 — non-blocking warnings only (e.g. YAML parse errors)

These tests drive the script exactly that way (subprocess + stdin) so the
stdin parsing and exit-code mapping are covered, not just the underlying
frontmatter_engine.validate (which is tested separately). Tests are hermetic:
they build a throwaway vault under tmp_path with its own CLAUDE.md root.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "engine"
HOOK = SCRIPTS_DIR / "validate-write.py"

VALID_FRONTMATTER = """---
date: 2026-06-07
description: "A hermetic test note used to exercise the validate-write hook contract"
tags:
  - test
---

# A Note

Body content that links to [[Something]] so the wikilink rule is satisfied.
"""

# Well-formed YAML frontmatter that is missing the required `tags` field →
# blocking error (severity "error", exit 1), distinct from a parse warning.
MISSING_REQUIRED_FIELD = """---
date: 2026-06-07
description: "A note whose frontmatter parses but omits the required tags field"
---

# A Note

Body content that links to [[Something]].
"""

# Opening fence with a closing fence but invalid YAML inside → parse warning.
BAD_YAML_FRONTMATTER = """---
date: 2026-06-07
description: "x
tags: [unclosed
---

# A Note

Body.
"""


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    (tmp_path / "CLAUDE.md").write_text("# Vault", encoding="utf-8")
    (tmp_path / "work").mkdir()
    return tmp_path


def _run_hook(file_path: Path | str | None) -> subprocess.CompletedProcess[str]:
    """Invoke the hook with a PostToolUse-shaped event on stdin."""
    if file_path is None:
        event = "{}"
    else:
        event = json.dumps({"tool_input": {"file_path": str(file_path)}})
    return _run_hook_raw(event)


def _run_hook_raw(stdin: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=stdin,
        capture_output=True,
        text=True,
    )


class TestValidWrite:
    def test_valid_note_exits_zero(self, vault: Path) -> None:
        note = vault / "work" / "note.md"
        note.write_text(VALID_FRONTMATTER, encoding="utf-8")

        result = _run_hook(note)

        assert result.returncode == 0, result.stderr


class TestBlockingError:
    def test_missing_required_field_exits_one(self, vault: Path) -> None:
        note = vault / "work" / "broken.md"
        note.write_text(MISSING_REQUIRED_FIELD, encoding="utf-8")

        result = _run_hook(note)

        assert result.returncode == 1, result.stderr
        # Blocking failures must emit structured hookSpecificOutput.
        payload = json.loads(result.stdout)
        assert "hookSpecificOutput" in payload
        assert "failed" in payload["hookSpecificOutput"].lower()


class TestNoFrontmatter:
    def test_missing_fence_is_warning_exit_two(self, vault: Path) -> None:
        # A file that does not start with --- parses as a frontmatter warning
        # (severity "warning") per the engine, which the hook maps to exit 2.
        note = vault / "work" / "no-fm.md"
        note.write_text(
            "# A Note\n\nNo frontmatter fence at all.\n", encoding="utf-8"
        )

        result = _run_hook(note)

        assert result.returncode == 2, result.stderr
        assert "hookSpecificOutput" in json.loads(result.stdout)


class TestWarningOnly:
    def test_yaml_parse_error_exits_two(self, vault: Path) -> None:
        note = vault / "work" / "bad-yaml.md"
        note.write_text(BAD_YAML_FRONTMATTER, encoding="utf-8")

        result = _run_hook(note)

        assert result.returncode == 2, result.stderr
        payload = json.loads(result.stdout)
        assert "hookSpecificOutput" in payload


class TestExcludedAndNoop:
    def test_non_markdown_path_exits_zero(self, vault: Path) -> None:
        other = vault / "work" / "data.json"
        other.write_text("{}", encoding="utf-8")

        result = _run_hook(other)

        assert result.returncode == 0, result.stderr

    def test_excluded_claude_md_exits_zero(self, vault: Path) -> None:
        # CLAUDE.md is excluded at any depth; even with no frontmatter it passes.
        result = _run_hook(vault / "CLAUDE.md")
        assert result.returncode == 0, result.stderr

    def test_excluded_agents_md_exits_zero(self, vault: Path) -> None:
        agents = vault / "work" / "AGENTS.md"
        agents.write_text("# Work rules\nNo frontmatter.\n", encoding="utf-8")
        result = _run_hook(agents)
        assert result.returncode == 0, result.stderr

    def test_missing_file_path_exits_zero(self, vault: Path) -> None:
        # Event with no file_path → no-op.
        result = _run_hook(None)
        assert result.returncode == 0, result.stderr

    def test_empty_stdin_exits_zero(self) -> None:
        result = _run_hook_raw("")
        assert result.returncode == 0, result.stderr

    def test_whitespace_stdin_exits_zero(self) -> None:
        result = _run_hook_raw("   \n  ")
        assert result.returncode == 0, result.stderr

    def test_garbage_stdin_exits_zero(self) -> None:
        # Malformed JSON must not crash the hook.
        result = _run_hook_raw("this is not json {{{")
        assert result.returncode == 0, result.stderr
