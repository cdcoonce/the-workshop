"""Tests for the work task manager — CRUD for work/Tasks.md with sections."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

# Add scripts dir to path
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(SCRIPTS_DIR))

from work_task_manager import (
    SECTIONS,
    WorkTask,
    add_work_task,
    complete_work_task,
    ensure_work_tasks_file,
    has_duplicate,
    parse_work_tasks,
    rollover_work_tasks,
    _iso_week_string,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def vault(tmp_path: Path) -> Path:
    """Create a minimal vault structure for testing."""
    (tmp_path / "CLAUDE.md").write_text("# Vault")
    (tmp_path / "work").mkdir()
    return tmp_path


@pytest.fixture
def tasks_file(vault: Path) -> Path:
    """Create a vault with a pre-populated Tasks.md containing all sections."""
    path = ensure_work_tasks_file(vault)
    return path


# ---------------------------------------------------------------------------
# TestParseWorkTasks
# ---------------------------------------------------------------------------

class TestParseWorkTasks:
    def test_parses_active_tasks(self, tasks_file: Path) -> None:
        """An active unchecked task under ## Active is parsed correctly."""
        content = tasks_file.read_text(encoding="utf-8")
        # Insert a task under ## Active
        content = content.replace(
            "## Active\n",
            "## Active\n- [ ] **Build pipeline** set up staging env\n",
        )
        tasks_file.write_text(content, encoding="utf-8")

        tasks = parse_work_tasks(tasks_file)
        active = [t for t in tasks if t.section == "Active"]
        assert len(active) == 1
        assert active[0].title == "Build pipeline"
        assert active[0].completed is False
        assert "set up staging env" in active[0].rest

    def test_parses_all_sections(self, tasks_file: Path) -> None:
        """Tasks placed under different section headers get the right section."""
        content = tasks_file.read_text(encoding="utf-8")
        content = content.replace(
            "## Active\n",
            "## Active\n- [ ] **Task A** active stuff\n",
        )
        content = content.replace(
            "## Waiting On\n",
            "## Waiting On\n- [ ] **Task B** waiting stuff\n",
        )
        content = content.replace(
            "## Someday\n",
            "## Someday\n- [ ] **Task C** someday stuff\n",
        )
        content = content.replace(
            "## Done\n",
            "## Done\n- [x] **Task D** done stuff\n",
        )
        tasks_file.write_text(content, encoding="utf-8")

        tasks = parse_work_tasks(tasks_file)
        sections_found = {t.section for t in tasks}
        assert sections_found == {"Active", "Waiting On", "Someday", "Done"}

    def test_parses_provenance(self, tasks_file: Path) -> None:
        """The (from: ...) annotation is extracted into provenance."""
        content = tasks_file.read_text(encoding="utf-8")
        content = content.replace(
            "## Active\n",
            "## Active\n- [ ] **Fix auth bug** investigate (from: standup 2026-04-01)\n",
        )
        tasks_file.write_text(content, encoding="utf-8")

        tasks = parse_work_tasks(tasks_file)
        assert tasks[0].provenance == "standup 2026-04-01"

    def test_parses_completed_status(self, tasks_file: Path) -> None:
        """A [x] checkbox is parsed as completed=True."""
        content = tasks_file.read_text(encoding="utf-8")
        content = content.replace(
            "## Done\n",
            "## Done\n- [x] **Ship feature** deployed (from: sprint)\n",
        )
        tasks_file.write_text(content, encoding="utf-8")

        tasks = parse_work_tasks(tasks_file)
        done = [t for t in tasks if t.section == "Done"]
        assert len(done) == 1
        assert done[0].completed is True

    def test_empty_file_returns_empty_list(self, tasks_file: Path) -> None:
        """A Tasks.md with only frontmatter and headers returns no tasks."""
        tasks = parse_work_tasks(tasks_file)
        assert tasks == []


# ---------------------------------------------------------------------------
# TestAddWorkTask
# ---------------------------------------------------------------------------

class TestAddWorkTask:
    def test_adds_to_active(self, vault: Path) -> None:
        """A task added to Active appears under the ## Active header."""
        ensure_work_tasks_file(vault)
        add_work_task(vault, "Write tests", "Active")

        path = vault / "work" / "Tasks.md"
        content = path.read_text(encoding="utf-8")
        assert "- [ ] **Write tests**" in content

    def test_adds_with_wikilinks(self, vault: Path) -> None:
        """Links are appended as wikilinks to the task line."""
        ensure_work_tasks_file(vault)
        add_work_task(vault, "Review PR", "Active", links=["Pipeline Redesign", "Jane Smith"])

        path = vault / "work" / "Tasks.md"
        content = path.read_text(encoding="utf-8")
        assert "[[Pipeline Redesign]]" in content
        assert "[[Jane Smith]]" in content

    def test_adds_to_waiting_on(self, vault: Path) -> None:
        """A task can be added to the Waiting On section."""
        ensure_work_tasks_file(vault)
        add_work_task(vault, "Await approval", "Waiting On", provenance="1:1 with boss")

        path = vault / "work" / "Tasks.md"
        content = path.read_text(encoding="utf-8")
        assert "- [ ] **Await approval**" in content
        assert "(from: 1:1 with boss)" in content
        # Verify it's in the Waiting On section by parsing
        tasks = parse_work_tasks(path)
        waiting = [t for t in tasks if t.section == "Waiting On"]
        assert len(waiting) == 1
        assert waiting[0].title == "Await approval"

    def test_raises_on_missing_section(self, vault: Path) -> None:
        """Adding a task to a nonexistent section raises ValueError."""
        ensure_work_tasks_file(vault)
        with pytest.raises(ValueError, match="section"):
            add_work_task(vault, "Bad task", "Nonexistent")


# ---------------------------------------------------------------------------
# TestHasDuplicate
# ---------------------------------------------------------------------------

class TestHasDuplicate:
    def test_detects_duplicate(self, vault: Path) -> None:
        """An exact title match is flagged as a duplicate."""
        ensure_work_tasks_file(vault)
        add_work_task(vault, "Write tests", "Active")
        assert has_duplicate(vault, "Write tests") is True

    def test_case_insensitive(self, vault: Path) -> None:
        """Duplicate detection is case-insensitive."""
        ensure_work_tasks_file(vault)
        add_work_task(vault, "Write Tests", "Active")
        assert has_duplicate(vault, "write tests") is True

    def test_no_false_positive(self, vault: Path) -> None:
        """A title that doesn't exist returns False."""
        ensure_work_tasks_file(vault)
        add_work_task(vault, "Write tests", "Active")
        assert has_duplicate(vault, "Deploy service") is False

    def test_ignores_completed(self, vault: Path) -> None:
        """Completed tasks are not counted as duplicates."""
        ensure_work_tasks_file(vault)
        add_work_task(vault, "Write tests", "Active")
        complete_work_task(vault, "Write tests")
        assert has_duplicate(vault, "Write tests") is False


# ---------------------------------------------------------------------------
# TestCompleteWorkTask
# ---------------------------------------------------------------------------

class TestCompleteWorkTask:
    def test_marks_complete_and_moves_to_done(self, vault: Path) -> None:
        """Completing a task checks the box, appends date, moves to Done."""
        ensure_work_tasks_file(vault)
        add_work_task(vault, "Write tests", "Active")

        result = complete_work_task(vault, "Write tests")
        assert result is True

        path = vault / "work" / "Tasks.md"
        tasks = parse_work_tasks(path)
        done = [t for t in tasks if t.section == "Done"]
        assert len(done) == 1
        assert done[0].title == "Write tests"
        assert done[0].completed is True
        # Completion date should be in the line
        content = path.read_text(encoding="utf-8")
        assert date.today().isoformat() in content

    def test_returns_false_for_missing(self, vault: Path) -> None:
        """Completing a task that doesn't exist returns False."""
        ensure_work_tasks_file(vault)
        result = complete_work_task(vault, "Nonexistent task")
        assert result is False

    def test_restores_task_when_done_section_missing(self, vault: Path) -> None:
        """No ## Done section → the task is NOT lost: it's restored and False returned.

        Guards the data-loss-prevention branch (the task is popped from its line
        before the Done section is located; if Done is absent it must be put back).
        """
        path = vault / "work" / "Tasks.md"
        # A Tasks.md with an Active task but deliberately NO ## Done section.
        path.write_text(
            "---\n"
            "date: 2026-06-28\n"
            'description: "Work tasks"\n'
            "tags:\n  - tasks\n"
            "---\n\n"
            "## Active\n"
            "- [ ] **Orphan task** do the thing\n\n"
            "## Waiting On\n\n"
            "## Someday\n",
            encoding="utf-8",
        )

        result = complete_work_task(vault, "Orphan task")

        assert result is False  # could not complete — no Done section to move into
        content = path.read_text(encoding="utf-8")
        assert "- [ ] **Orphan task** do the thing" in content  # restored, not lost
        assert "[x]" not in content  # never marked complete
        assert "(completed:" not in content  # no stray completion stamp


# ---------------------------------------------------------------------------
# TestEnsureWorkTasksFile
# ---------------------------------------------------------------------------

class TestEnsureWorkTasksFile:
    def test_creates_file_with_sections(self, vault: Path) -> None:
        """The file is created with frontmatter and all four section headers."""
        path = ensure_work_tasks_file(vault)
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "---" in content  # frontmatter present
        for section in SECTIONS:
            assert f"## {section}" in content

    def test_idempotent(self, vault: Path) -> None:
        """Calling ensure twice does not overwrite existing content."""
        path1 = ensure_work_tasks_file(vault)
        # Add a task so content changes
        add_work_task(vault, "Existing task", "Active")
        content_before = path1.read_text(encoding="utf-8")

        path2 = ensure_work_tasks_file(vault)
        content_after = path2.read_text(encoding="utf-8")

        assert path1 == path2
        assert content_before == content_after


# ---------------------------------------------------------------------------
# _iso_week_string
# ---------------------------------------------------------------------------

class TestIsoWeekString:
    def test_zero_padded(self) -> None:
        assert _iso_week_string(date(2026, 1, 5)) == "2026-W02"

    def test_year_boundary_belongs_to_next_iso_year(self) -> None:
        # 2025-12-29 (Monday) is ISO week 1 of 2026.
        assert _iso_week_string(date(2025, 12, 29)) == "2026-W01"


# ---------------------------------------------------------------------------
# rollover_work_tasks
# ---------------------------------------------------------------------------

def _write_work_tasks(vault: Path, week: str, body: str) -> Path:
    """Write a work/Tasks.md with a given frontmatter week and section body."""
    path = vault / "work" / "Tasks.md"
    path.write_text(
        "---\n"
        "date: 2026-01-01\n"
        'description: "Work tasks"\n'
        "tags:\n  - tasks\n"
        f'week: "{week}"\n'
        "---\n\n"
        "# Work Tasks\n\n" + body,
        encoding="utf-8",
    )
    return path


class TestRolloverWorkTasks:
    def test_no_file_is_noop(self, vault: Path) -> None:
        result = rollover_work_tasks(vault, today=date(2026, 4, 20))
        assert result["rolled_over"] is False
        assert "not found" in result["reason"]

    def test_missing_week_field_is_noop(self, vault: Path) -> None:
        (vault / "work" / "Tasks.md").write_text(
            "---\ndate: 2026-01-01\ndescription: \"x\"\ntags:\n  - tasks\n---\n\n"
            "# Work Tasks\n\n## Active\n",
            encoding="utf-8",
        )
        result = rollover_work_tasks(vault, today=date(2026, 4, 20))
        assert result["rolled_over"] is False
        assert "week field" in result["reason"].lower()

    def test_invalid_week_date_is_noop(self, vault: Path) -> None:
        _write_work_tasks(vault, "2026-13-99", "## Active\n")
        result = rollover_work_tasks(vault, today=date(2026, 4, 20))
        assert result["rolled_over"] is False
        assert "invalid week" in result["reason"].lower()

    def test_same_iso_week_is_noop(self, vault: Path) -> None:
        # fm week 2026-04-20 (W17); today 2026-04-22 (also W17) → idempotent no-op.
        _write_work_tasks(vault, "2026-04-20", "## Active\n- [ ] **Task** wip\n")
        result = rollover_work_tasks(vault, today=date(2026, 4, 22))
        assert result["rolled_over"] is False
        assert "already in" in result["reason"].lower()

    def test_carries_open_archives_and_drops_done(self, vault: Path) -> None:
        body = (
            "## Active\n- [ ] **Open A** wip\n- [x] **Closed A** done\n\n"
            "## Waiting On\n- [ ] **Waiting B** blocked\n\n"
            "## Someday\n\n"
            "## Done\n- [x] **Shipped thing** (completed: 2026-04-15)\n"
        )
        _write_work_tasks(vault, "2026-04-13", body)  # W16
        result = rollover_work_tasks(vault, today=date(2026, 4, 20))  # W17

        assert result["rolled_over"] is True
        assert result["archived_week"] == "2026-W16"
        assert result["new_week"] == "2026-W17"

        # The archive is a verbatim copy (keeps the completed items too).
        archive = result["archive_path"]
        assert archive.exists()
        assert archive.name == "2026-W16-tasks.md"
        assert "**Closed A**" in archive.read_text(encoding="utf-8")

        # done_items captured for the Brag Doc scan.
        assert any("Shipped thing" in d for d in result["done_items"])

        new = (vault / "work" / "Tasks.md").read_text(encoding="utf-8")
        assert "**Open A**" in new          # open carried forward
        assert "**Waiting B**" in new       # open carried forward
        assert "**Closed A**" not in new    # [x] dropped
        assert "**Shipped thing**" not in new  # whole Done section dropped
        assert 'week: "2026-04-20"' in new  # frontmatter week → today's Monday

    def test_drops_all_complete_subsection_keeps_open_one(self, vault: Path) -> None:
        body = (
            "## Active\n"
            "### [[Project X]]\n- [x] **All done here** (completed: 2026-04-15)\n\n"
            "### [[Project Y]]\n- [ ] **Still open** wip\n\n"
            "## Waiting On\n\n## Someday\n\n## Done\n"
        )
        _write_work_tasks(vault, "2026-04-13", body)
        result = rollover_work_tasks(vault, today=date(2026, 4, 20))

        assert result["rolled_over"] is True
        new = (vault / "work" / "Tasks.md").read_text(encoding="utf-8")
        assert "[[Project Y]]" in new       # subsection with an open task kept
        assert "**Still open**" in new
        assert "[[Project X]]" not in new   # all-complete subsection dropped
