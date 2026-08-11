"""Tests for the inject-skill-router SessionStart hook.

``inject-skill-router.py`` is a standalone script shipped inside project preset
plugins (not part of the ``scripts`` package), so it is loaded directly from its
file path rather than imported as a module path.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

HOOK_PATH = (
    Path(__file__).resolve().parents[1]
    / "plugins"
    / "workbench"
    / "hooks"
    / "scripts"
    / "inject-skill-router.py"
)

_spec = importlib.util.spec_from_file_location("inject_skill_router", HOOK_PATH)
inject_skill_router = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(inject_skill_router)

_strip_frontmatter = inject_skill_router._strip_frontmatter
main = inject_skill_router.main


def _write_skill(root: Path, body: str = "# Using Workflow\n\nRouter skill.\n") -> None:
    skill_dir = root / "skills" / "using-workflow"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: using-workflow\ndescription: Router skill\n---\n{body}"
    )


def _write_conventions(root: Path, conventions: object) -> None:
    (root / "conventions.json").write_text(json.dumps({"conventions": conventions}))


class TestStripFrontmatter:
    def test_strips_leading_frontmatter_block(self) -> None:
        text = "---\nname: using-workflow\n---\n# Using Workflow\n\nRoute skills.\n"

        assert _strip_frontmatter(text) == "# Using Workflow\n\nRoute skills."

    def test_returns_trimmed_text_unchanged_when_no_frontmatter(self) -> None:
        text = "\n# Just a skill\n\nNo frontmatter here.\n"

        assert _strip_frontmatter(text) == "# Just a skill\n\nNo frontmatter here."

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

    def test_returns_0_and_prints_nothing_when_skill_file_missing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
    ) -> None:
        _write_conventions(tmp_path, ["Type hints on public functions"])
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))

        assert main() == 0
        assert capsys.readouterr().out == ""

    def test_returns_0_and_prints_nothing_when_skill_body_is_empty(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
    ) -> None:
        skill_dir = tmp_path / "skills" / "using-workflow"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("---\nname: using-workflow\n---\n\n")
        _write_conventions(tmp_path, ["Type hints on public functions"])
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))

        assert main() == 0
        assert capsys.readouterr().out == ""

    def test_returns_0_and_prints_nothing_when_conventions_file_missing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
    ) -> None:
        _write_skill(tmp_path)
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))

        assert main() == 0
        assert capsys.readouterr().out == ""

    def test_returns_0_and_prints_nothing_when_conventions_file_is_malformed_json(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
    ) -> None:
        _write_skill(tmp_path)
        (tmp_path / "conventions.json").write_text("{not valid json")
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))

        assert main() == 0
        assert capsys.readouterr().out == ""

    def test_returns_0_and_prints_nothing_when_conventions_is_not_a_list(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
    ) -> None:
        _write_skill(tmp_path)
        _write_conventions(tmp_path, "not a list")
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))

        assert main() == 0
        assert capsys.readouterr().out == ""

    def test_returns_0_and_prints_nothing_when_conventions_has_non_string_entries(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
    ) -> None:
        _write_skill(tmp_path)
        _write_conventions(tmp_path, ["Ruff for linting", 42])
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))

        assert main() == 0
        assert capsys.readouterr().out == ""


class TestMainSuccess:
    def test_emits_hook_specific_output_with_skill_body_and_conventions(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
    ) -> None:
        _write_skill(tmp_path, "# Using Workflow\n\nRoute skills before responding.\n")
        _write_conventions(
            tmp_path,
            ["Ruff for linting and formatting", "Type hints on public functions"],
        )
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))

        assert main() == 0
        output = json.loads(capsys.readouterr().out)

        assert output["hookSpecificOutput"]["hookEventName"] == "SessionStart"
        additional_context = output["hookSpecificOutput"]["additionalContext"]
        assert "Route skills before responding." in additional_context
        assert "Ruff for linting and formatting" in additional_context
        assert "Type hints on public functions" in additional_context


class TestRouterBodyDeduplication:
    """The router body is identical in every preset — inject it once per session.

    Several presets ship this hook, and Claude Code runs each installed copy on
    SessionStart. Without a session-scoped claim the same ~1500-word router is
    pasted into context once per preset. Conventions differ per preset, so those
    are always emitted; only the shared body is deduplicated.
    """

    def _setup(self, monkeypatch: pytest.MonkeyPatch, root: Path, convention: str) -> None:
        root.mkdir(parents=True, exist_ok=True)
        _write_skill(root, "# Using Workflow\n\nRoute skills before responding.\n")
        _write_conventions(root, [convention])
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(root))

    def test_second_preset_in_a_session_emits_conventions_without_the_router_body(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
    ) -> None:
        monkeypatch.setenv("TMPDIR", str(tmp_path / "tmp"))

        self._setup(monkeypatch, tmp_path / "first", "Inventory before reorganizing")
        assert main(session_id="s-1") == 0
        first = json.loads(capsys.readouterr().out)["hookSpecificOutput"][
            "additionalContext"
        ]

        self._setup(monkeypatch, tmp_path / "second", "Conventional commits only")
        assert main(session_id="s-1") == 0
        second = json.loads(capsys.readouterr().out)["hookSpecificOutput"][
            "additionalContext"
        ]

        assert "Route skills before responding." in first
        assert "Inventory before reorganizing" in first

        assert "Route skills before responding." not in second
        assert "Conventional commits only" in second

    def test_a_different_session_gets_the_router_body_again(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
    ) -> None:
        monkeypatch.setenv("TMPDIR", str(tmp_path / "tmp"))
        self._setup(monkeypatch, tmp_path / "p", "Inventory before reorganizing")

        assert main(session_id="s-1") == 0
        capsys.readouterr()
        assert main(session_id="s-2") == 0

        assert "Route skills before responding." in capsys.readouterr().out

    def test_without_a_session_id_the_body_is_always_emitted(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
    ) -> None:
        """Codex delivers no stdin payload; a missing id must not suppress the router."""
        monkeypatch.setenv("TMPDIR", str(tmp_path / "tmp"))
        self._setup(monkeypatch, tmp_path / "p", "Inventory before reorganizing")

        assert main() == 0
        assert "Route skills before responding." in capsys.readouterr().out
        assert main() == 0
        assert "Route skills before responding." in capsys.readouterr().out

    def test_an_unwritable_marker_directory_still_emits_the_router(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
    ) -> None:
        """Dedup is an optimization — it must never cost a session its router."""
        blocker = tmp_path / "tmp"
        blocker.write_text("not a directory")
        monkeypatch.setenv("TMPDIR", str(blocker))
        self._setup(monkeypatch, tmp_path / "p", "Inventory before reorganizing")

        assert main(session_id="s-1") == 0
        assert "Route skills before responding." in capsys.readouterr().out
