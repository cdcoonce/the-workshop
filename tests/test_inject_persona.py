"""Tests for the inject_persona SessionStart hook.

``inject_persona.py`` has no package ``__init__.py`` alongside it (unlike
``scripts/``), so it is loaded directly from its file path rather than
imported as a module path.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

HOOK_PATH = Path(__file__).resolve().parents[1] / "core" / "hooks" / "inject_persona.py"

_spec = importlib.util.spec_from_file_location("inject_persona", HOOK_PATH)
inject_persona = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(inject_persona)

_strip_frontmatter = inject_persona._strip_frontmatter
main = inject_persona.main


class TestStripFrontmatter:
    def test_strips_leading_frontmatter_block(self) -> None:
        text = "---\nname: grumpy-reviewer\n---\n# Grumpy Reviewer\n\nBe grumpy.\n"

        assert _strip_frontmatter(text) == "# Grumpy Reviewer\n\nBe grumpy."

    def test_returns_trimmed_text_unchanged_when_no_frontmatter(self) -> None:
        text = "\n# Just a persona\n\nNo frontmatter here.\n"

        assert _strip_frontmatter(text) == "# Just a persona\n\nNo frontmatter here."

    def test_handles_dashes_sequence_inside_body(self) -> None:
        text = "---\nname: x\n---\nBody text\n---\nmore dashes below\n"

        assert _strip_frontmatter(text) == "Body text\n---\nmore dashes below"


class TestMainFailSafe:
    def test_returns_0_and_prints_nothing_when_plugin_root_unset(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)

        assert main() == 0
        assert capsys.readouterr().out == ""

    def test_returns_0_and_prints_nothing_when_no_markdown_styles(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
    ) -> None:
        (tmp_path / "output-styles").mkdir()
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))

        assert main() == 0
        assert capsys.readouterr().out == ""

    def test_returns_0_and_prints_nothing_when_stripped_body_is_empty(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
    ) -> None:
        styles = tmp_path / "output-styles"
        styles.mkdir()
        (styles / "persona.md").write_text("---\nname: empty\n---\n\n")
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))

        assert main() == 0
        assert capsys.readouterr().out == ""


class TestMainSuccess:
    def test_emits_hook_specific_output_with_stripped_body(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
    ) -> None:
        styles = tmp_path / "output-styles"
        styles.mkdir()
        (styles / "persona.md").write_text(
            "---\nname: grumpy-reviewer\ndescription: A grumpy reviewer\n---\n"
            "# Grumpy Reviewer\n\nBe grumpy.\n"
        )
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))

        assert main() == 0
        output = json.loads(capsys.readouterr().out)

        assert output == {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": "# Grumpy Reviewer\n\nBe grumpy.",
            }
        }
        assert "---" not in output["hookSpecificOutput"]["additionalContext"]
