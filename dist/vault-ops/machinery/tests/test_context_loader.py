"""Tests for the context loader — machine detection and context assembly."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(SCRIPTS_DIR))

import context_loader
import context_paths_defaults
from context_loader import (
    HANDOFF_MAX_BYTES,
    HANDOFF_RESUME_ENTRIES,
    SUMMARY_ITEM_CHARS,
    SUMMARY_PREVIEW,
    SessionContext,
    condense_digest,
    load_context,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def vault(tmp_path: Path) -> Path:
    """Create a minimal vault structure."""
    (tmp_path / "CLAUDE.md").write_text("# Vault")
    (tmp_path / "brain").mkdir()
    (tmp_path / "work").mkdir()
    (tmp_path / "personal").mkdir()

    (tmp_path / "brain" / "North Star.md").write_text(
        "---\ndate: 2026-04-04\ndescription: goals\ntags:\n  - north-star\n---\n\n"
        "# North Star\n\n## Current Focus\n\nBuild the data warehouse.\n"
    )

    (tmp_path / "work" / "Index.md").write_text(
        "---\ndate: 2026-04-04\ndescription: work index\ntags:\n  - index\n---\n\n"
        "# Work Index\n\n## Active Projects\n\n"
        "- [[Pipeline Redesign]]\n"
        "- [[Data Quality Dashboard]]\n\n"
        "## Completed by Quarter\n\n### Q1 2026\n"
    )

    (tmp_path / "personal" / "Index.md").write_text(
        "---\ndate: 2026-04-04\ndescription: personal index\ntags:\n  - index\n---\n\n"
        "# Personal Index\n\n## Learning\n\n"
        "- [[Advanced SQL]]\n\n"
        "## Side Projects\n\n"
        "- [[CLI Data Profiler]]\n\n"
        "## Ideas\n\n"
    )

    return tmp_path


# ---------------------------------------------------------------------------
# Machine detection
# ---------------------------------------------------------------------------

class TestMachineDetection:
    def test_work_context(self, vault: Path) -> None:
        (vault / ".vault-context").write_text("work")
        ctx = load_context(vault)
        assert ctx.machine == "work"

    def test_personal_context(self, vault: Path) -> None:
        (vault / ".vault-context").write_text("personal")
        ctx = load_context(vault)
        assert ctx.machine == "personal"

    def test_missing_context_file(self, vault: Path) -> None:
        ctx = load_context(vault)
        assert ctx.machine == "unknown"

    def test_invalid_context_value(self, vault: Path) -> None:
        (vault / ".vault-context").write_text("laptop")
        ctx = load_context(vault)
        assert ctx.machine == "unknown"

    def test_whitespace_handling(self, vault: Path) -> None:
        (vault / ".vault-context").write_text("  work  \n")
        ctx = load_context(vault)
        assert ctx.machine == "work"

    def test_case_insensitive(self, vault: Path) -> None:
        (vault / ".vault-context").write_text("PERSONAL")
        ctx = load_context(vault)
        assert ctx.machine == "personal"


# ---------------------------------------------------------------------------
# Context assembly
# ---------------------------------------------------------------------------

class TestContextAssembly:
    def test_loads_north_star(self, vault: Path) -> None:
        (vault / ".vault-context").write_text("work")
        ctx = load_context(vault)
        assert "North Star" in ctx.north_star
        assert "data warehouse" in ctx.north_star

    def test_loads_active_work(self, vault: Path) -> None:
        (vault / ".vault-context").write_text("work")
        ctx = load_context(vault)
        assert len(ctx.active_work) == 2
        assert "[[Pipeline Redesign]]" in ctx.active_work
        assert "[[Data Quality Dashboard]]" in ctx.active_work

    def test_loads_active_personal(self, vault: Path) -> None:
        (vault / ".vault-context").write_text("personal")
        ctx = load_context(vault)
        assert "[[Advanced SQL]]" in ctx.active_personal
        assert "[[CLI Data Profiler]]" in ctx.active_personal

    def test_summary_includes_machine(self, vault: Path) -> None:
        (vault / ".vault-context").write_text("work")
        ctx = load_context(vault)
        assert "work" in ctx.summary.lower()

    def test_summary_includes_project_count(self, vault: Path) -> None:
        (vault / ".vault-context").write_text("work")
        ctx = load_context(vault)
        assert "2" in ctx.summary  # 2 active projects


# ---------------------------------------------------------------------------
# Configurable note paths
# ---------------------------------------------------------------------------

@pytest.fixture
def scaffolded_config():
    """Reload context_loader against a stand-in scaffolded context_paths module.

    The real config is scaffold-rendered into the vault's script dir, so the
    seam under test is the module-level import — not the flattened lookup it
    produces. Each call re-executes context_loader with the given sections;
    teardown restores the shipped defaults.
    """

    def _configure(
        common: dict[str, str], per_context: dict[str, dict[str, str]]
    ) -> ModuleType:
        module = ModuleType("context_paths")
        module.COMMON_NOTE_PATHS = common
        module.CONTEXT_NOTE_PATHS = per_context
        sys.modules["context_paths"] = module
        return importlib.reload(context_loader)

    yield _configure

    sys.modules.pop("context_paths", None)
    importlib.reload(context_loader)


class TestConfigurableNotePaths:
    """Digest-source paths come from config, not literals in the loader."""

    def test_configured_paths_are_read(self, vault: Path, scaffolded_config) -> None:
        (vault / "brain" / "Goals.md").write_text(
            "---\ndate: 2026-04-04\ndescription: goals\ntags:\n  - north-star\n---\n\n"
            "# Goals\n\nCustom north star location.\n"
        )
        (vault / "projects").mkdir()
        (vault / "projects" / "Index.md").write_text(
            "---\ndate: 2026-04-04\ndescription: work index\ntags:\n  - index\n---\n\n"
            "# Projects\n\n## Active Projects\n\n- [[Warehouse Cutover]]\n"
        )
        loader = scaffolded_config(
            {"north_star": "brain/Goals.md"},
            {"work": {"work_index": "projects/Index.md"}},
        )

        ctx = loader.load_context(vault)

        assert "Custom north star location" in ctx.north_star
        assert ctx.active_work == ["[[Warehouse Cutover]]"]

    def test_configured_pointer_names_the_configured_path(
        self, vault: Path, scaffolded_config
    ) -> None:
        (vault / "projects").mkdir()
        (vault / "projects" / "Index.md").write_text(
            "---\ndate: 2026-04-04\ndescription: work index\ntags:\n  - index\n---\n\n"
            "# Projects\n\n## Active Projects\n\n"
            + "".join(f"- [[Project {n}]]\n" for n in range(SUMMARY_PREVIEW + 2))
        )
        loader = scaffolded_config({}, {"work": {"work_index": "projects/Index.md"}})

        ctx = loader.load_context(vault)

        assert "projects/Index.md" in ctx.summary

    def test_missing_configured_note_degrades_to_empty(
        self, vault: Path, scaffolded_config
    ) -> None:
        loader = scaffolded_config({"north_star": "brain/Does-Not-Exist.md"}, {})

        ctx = loader.load_context(vault)

        assert ctx.north_star == ""

    def test_dropped_config_name_falls_back_to_shipped_default(
        self, vault: Path, scaffolded_config
    ) -> None:
        """An owner deleting a section they have no notes for must not crash."""
        loader = scaffolded_config({"north_star": "brain/North Star.md"}, {})

        ctx = loader.load_context(vault)

        assert loader.NOTE_PATHS["personal_index"] == "personal/Index.md"
        assert "[[Advanced SQL]]" in ctx.active_personal

    def test_unmapped_name_degrades_to_empty(self, vault: Path, monkeypatch) -> None:
        """A name absent from both config and defaults reads as a missing note."""
        monkeypatch.setattr(context_loader, "NOTE_PATHS", {})

        ctx = load_context(vault)

        assert ctx.north_star == ""
        assert ctx.active_work == []

    def test_absent_config_module_uses_shipped_defaults(self, vault: Path) -> None:
        """A vault vendored before the scaffold config exists still digests."""
        assert "context_paths" not in sys.modules
        assert context_loader.NOTE_PATHS == {
            **context_paths_defaults.COMMON_NOTE_PATHS,
            **context_paths_defaults.CONTEXT_NOTE_PATHS["work"],
            **context_paths_defaults.CONTEXT_NOTE_PATHS["personal"],
        }

        ctx = load_context(vault)

        assert "data warehouse" in ctx.north_star


# ---------------------------------------------------------------------------
# Bootstrap / empty vault
# ---------------------------------------------------------------------------

class TestEmptyVault:
    def test_empty_vault_no_crash(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE.md").write_text("# Vault")
        ctx = load_context(tmp_path)
        assert ctx.machine == "unknown"
        assert ctx.active_work == []
        assert ctx.active_personal == []
        assert "New vault" in ctx.summary or "no projects" in ctx.summary.lower() or ctx.summary != ""

    def test_missing_north_star(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE.md").write_text("# Vault")
        ctx = load_context(tmp_path)
        assert ctx.north_star == ""

    def test_missing_indexes(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE.md").write_text("# Vault")
        ctx = load_context(tmp_path)
        assert ctx.active_work == []
        assert ctx.active_personal == []


# ---------------------------------------------------------------------------
# Git log parsing
# ---------------------------------------------------------------------------

class TestGitLog:
    @patch("context_loader.subprocess.run")
    def test_git_log_success(self, mock_run, vault: Path) -> None:
        mock_run.return_value = type("Result", (), {
            "returncode": 0,
            "stdout": "abc1234 feat: add pipeline module\ndef5678 fix: query timeout",
            "stderr": "",
        })()
        (vault / ".vault-context").write_text("work")
        ctx = load_context(vault)
        assert "pipeline module" in ctx.recent_git

    @patch("context_loader.subprocess.run")
    def test_git_not_available(self, mock_run, vault: Path) -> None:
        mock_run.side_effect = FileNotFoundError("git not found")
        (vault / ".vault-context").write_text("work")
        ctx = load_context(vault)
        assert ctx.recent_git == ""

    @patch("context_loader.subprocess.run")
    def test_git_timeout(self, mock_run, vault: Path) -> None:
        from subprocess import TimeoutExpired
        mock_run.side_effect = TimeoutExpired("git", 10)
        (vault / ".vault-context").write_text("work")
        ctx = load_context(vault)
        assert ctx.recent_git == ""


# ---------------------------------------------------------------------------
# Quick-Reference loading
# ---------------------------------------------------------------------------

class TestQuickReferenceLoading:
    def test_loads_quick_ref(self, vault: Path) -> None:
        (vault / "brain" / "Quick-Reference.md").write_text(
            "---\ndate: 2026-04-05\ndescription: hot cache\ntags:\n  - reference\n---\n"
            "# Quick Reference\n## People\n| Name | Role | Context |\n|---|---|---|\n"
            "| **Biodun** | Manager | 1:1 weekly |\n",
            encoding="utf-8",
        )
        ctx = load_context(vault)
        assert ctx.quick_reference != ""
        assert "Biodun" in ctx.quick_reference

    def test_empty_without_file(self, vault: Path) -> None:
        ctx = load_context(vault)
        assert ctx.quick_reference == ""


# ---------------------------------------------------------------------------
# SessionStart context budget
# ---------------------------------------------------------------------------

def _index(title: str, items: list[str]) -> str:
    body = "\n".join(f"- [[{item}]]" for item in items)
    return (
        f"---\ndate: 2026-04-04\ndescription: idx\ntags:\n  - index\n---\n\n"
        f"# {title}\n\n## Active Projects\n\n{body}\n"
    )


class TestSummaryBudget:
    """The summary is resident all session, so it pays for orientation only."""

    def test_caps_bullets_and_points_at_the_index(self, vault: Path) -> None:
        (vault / "work" / "Index.md").write_text(
            _index("Work Index", [f"Project {n}" for n in range(12)]), encoding="utf-8"
        )
        (vault / ".vault-context").write_text("work")

        summary = load_context(vault).summary

        assert "Active work projects: 12" in summary
        assert summary.count("  • ") == SUMMARY_PREVIEW
        assert f"+{12 - SUMMARY_PREVIEW} more" in summary
        assert "work/Index.md" in summary

    def test_clips_a_long_item(self, vault: Path) -> None:
        (vault / "work" / "Index.md").write_text(
            _index("Work Index", ["X" * 400]), encoding="utf-8"
        )
        (vault / ".vault-context").write_text("work")

        bullet = next(
            line for line in load_context(vault).summary.splitlines()
            if line.startswith("  • ")
        )

        assert len(bullet) <= SUMMARY_ITEM_CHARS + 8
        assert bullet.endswith("…")

    def test_full_lists_stay_uncapped_on_the_context_object(self, vault: Path) -> None:
        """Only the rendered summary is budgeted — consumers still get everything."""
        (vault / "work" / "Index.md").write_text(
            _index("Work Index", [f"Project {n}" for n in range(12)]), encoding="utf-8"
        )
        (vault / ".vault-context").write_text("work")

        assert len(load_context(vault).active_work) == 12


class TestCondenseDigest:
    """The handoff digest is injected verbatim today; budget its entry stack."""

    @staticmethod
    def _handoff(entry_count: int, body_chars: int = 200) -> str:
        entries = "\n\n".join(
            f"**▶ 2026-07-{20 - n:02d} SESSION RESULT**\n\n{'detail. ' * (body_chars // 8)}"
            for n in range(entry_count)
        )
        return (
            "# Handoff\n\n## Where we are\n\nMid-flight.\n\n"
            f"## Resume from here\n\n{entries}\n\n## Mode\n\nAutonomous.\n"
        )

    def test_keeps_newest_entry_and_counts_the_rest(self) -> None:
        out = condense_digest(self._handoff(4), ".brain/handoff-personal.md")

        assert "2026-07-20" in out
        assert "2026-07-17" not in out
        assert f"+{4 - HANDOFF_RESUME_ENTRIES} older session entries elided" in out
        assert ".brain/handoff-personal.md" in out

    def test_preserves_the_other_sections(self) -> None:
        out = condense_digest(self._handoff(4), ".brain/handoff-personal.md")

        assert "## Where we are" in out
        assert "Mid-flight." in out

    def test_small_digest_round_trips(self) -> None:
        """handoff-work.md has no '▶' entries and must not regress."""
        small = "# Handoff\n\n## Where we are\n\n- **Thing** — done.\n"

        assert condense_digest(small, ".brain/handoff-work.md").strip() == small.strip()

    def test_respects_the_byte_ceiling(self) -> None:
        out = condense_digest(self._handoff(8, body_chars=4000), ".brain/h.md")

        assert len(out.encode("utf-8")) <= HANDOFF_MAX_BYTES + 400

    def test_is_idempotent(self) -> None:
        once = condense_digest(self._handoff(4), ".brain/h.md")

        assert condense_digest(once, ".brain/h.md") == once
