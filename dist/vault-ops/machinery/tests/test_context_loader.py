"""Tests for the context loader — machine detection and context assembly."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(SCRIPTS_DIR))

from context_loader import SessionContext, load_context


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
