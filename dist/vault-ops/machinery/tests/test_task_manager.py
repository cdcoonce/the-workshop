"""Tests for the task manager — weekly file creation, task CRUD, and rollover."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

# Add scripts dir to path
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(SCRIPTS_DIR))

from task_manager import (
    Task,
    add_task,
    get_open_tasks,
    get_or_create_weekly_file,
    parse_tasks,
    rollover_tasks,
    _format_task_line,
    _week_string,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def vault(tmp_path: Path) -> Path:
    """Create a minimal vault structure for testing."""
    (tmp_path / "CLAUDE.md").write_text("# Vault")
    (tmp_path / "personal" / "tasks").mkdir(parents=True)
    return tmp_path


# ---------------------------------------------------------------------------
# ISO week string helper
# ---------------------------------------------------------------------------

class TestWeekString:
    def test_normal_date(self) -> None:
        # 2026-04-04 is a Saturday in ISO week 14
        assert _week_string(date(2026, 4, 4)) == "2026-W14"

    def test_zero_padding(self) -> None:
        # Week 1 must be W01, not W1
        assert _week_string(date(2026, 1, 5)) == "2026-W02"
        result = _week_string(date(2026, 1, 1))
        assert "-W0" in result  # must be zero-padded

    def test_year_boundary_dec_29_2025(self) -> None:
        # Dec 29, 2025 is a Monday — ISO week 2026-W01
        assert _week_string(date(2025, 12, 29)) == "2026-W01"

    def test_week_53(self) -> None:
        # 2020-12-31 is in ISO week 53
        assert _week_string(date(2020, 12, 31)) == "2020-W53"


# ---------------------------------------------------------------------------
# _format_task_line — a dateless task must render without a date stamp (#56)
# ---------------------------------------------------------------------------

class TestFormatTaskLine:
    def test_omits_date_when_none(self) -> None:
        assert _format_task_line("Buy milk", None) == "- [ ] Buy milk"

    def test_keeps_explicit_date(self) -> None:
        assert _format_task_line("Dated task", date(2026, 1, 2)) == "- [ ] 2026-01-02 Dated task"


# ---------------------------------------------------------------------------
# get_or_create_weekly_file
# ---------------------------------------------------------------------------

class TestGetOrCreateWeeklyFile:
    def test_creates_new_file(self, vault: Path) -> None:
        path = get_or_create_weekly_file(vault, "2026-W14")
        assert path.exists()
        assert path.name == "2026-W14-tasks.md"

    def test_idempotent(self, vault: Path) -> None:
        path1 = get_or_create_weekly_file(vault, "2026-W14")
        content1 = path1.read_text(encoding="utf-8")
        path2 = get_or_create_weekly_file(vault, "2026-W14")
        content2 = path2.read_text(encoding="utf-8")
        assert path1 == path2
        assert content1 == content2

    def test_frontmatter_has_required_fields(self, vault: Path) -> None:
        path = get_or_create_weekly_file(vault, "2026-W14")
        content = path.read_text(encoding="utf-8")
        assert "date:" in content
        assert "description:" in content
        assert "tags:" in content
        assert "week:" in content
        assert "2026-W14" in content

    def test_heading_present(self, vault: Path) -> None:
        path = get_or_create_weekly_file(vault, "2026-W14")
        content = path.read_text(encoding="utf-8")
        assert "# Tasks — 2026-W14" in content

    def test_creates_tasks_dir_if_missing(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE.md").write_text("# Vault")
        # Don't create personal/tasks/ — let the function do it
        path = get_or_create_weekly_file(tmp_path, "2026-W14")
        assert path.exists()
        assert (tmp_path / "personal" / "tasks").is_dir()

    def test_defaults_to_current_week(self, vault: Path) -> None:
        path = get_or_create_weekly_file(vault)
        expected_week = _week_string(date.today())
        assert expected_week in path.name

    def test_week_53_file(self, vault: Path) -> None:
        path = get_or_create_weekly_file(vault, "2020-W53")
        assert path.name == "2020-W53-tasks.md"
        content = path.read_text(encoding="utf-8")
        assert "2020-W53" in content


# ---------------------------------------------------------------------------
# add_task
# ---------------------------------------------------------------------------

class TestAddTask:
    def test_adds_task_to_file(self, vault: Path) -> None:
        # add_task always writes to the CURRENT week's file (the due date is
        # only the line's date stamp, not a router), so assert against the
        # path it returns rather than a hardcoded week — keeps the test from
        # rotting as the calendar advances.
        path = add_task(vault, "Pick up prescription", date(2026, 4, 7))
        content = path.read_text(encoding="utf-8")
        assert "- [ ] 2026-04-07 Pick up prescription" in content

    def test_defaults_due_date_to_today(self, vault: Path) -> None:
        add_task(vault, "Buy groceries")
        path = get_or_create_weekly_file(vault)
        content = path.read_text(encoding="utf-8")
        assert f"- [ ] {date.today().isoformat()} Buy groceries" in content

    def test_adds_wikilinks(self, vault: Path) -> None:
        add_task(vault, "Call about lease", links=["Housing"])
        path = get_or_create_weekly_file(vault)
        content = path.read_text(encoding="utf-8")
        assert "[[Housing]]" in content

    def test_does_not_duplicate_existing_wikilinks(self, vault: Path) -> None:
        add_task(vault, "Review [[Housing]] docs", links=["Housing"])
        path = get_or_create_weekly_file(vault)
        content = path.read_text(encoding="utf-8")
        # Should only appear once
        assert content.count("[[Housing]]") == 1

    def test_raises_on_empty_text(self, vault: Path) -> None:
        with pytest.raises(ValueError, match="empty"):
            add_task(vault, "")

    def test_raises_on_whitespace_text(self, vault: Path) -> None:
        with pytest.raises(ValueError, match="empty"):
            add_task(vault, "   ")

    def test_returns_file_path(self, vault: Path) -> None:
        result = add_task(vault, "Test task")
        assert isinstance(result, Path)
        assert result.exists()

    def test_multiple_tasks_appended(self, vault: Path) -> None:
        add_task(vault, "Task one", date(2026, 4, 7))
        add_task(vault, "Task two", date(2026, 4, 8))
        path = get_or_create_weekly_file(vault)
        content = path.read_text(encoding="utf-8")
        assert "Task one" in content
        assert "Task two" in content

    def test_ends_with_single_trailing_newline(self, vault: Path) -> None:
        # #51 — after add_task the weekly file must end in exactly one newline.
        path = add_task(vault, "Single task", date(2026, 4, 7))
        content = path.read_text(encoding="utf-8")
        assert content.endswith("\n")
        assert not content.endswith("\n\n")

    def test_trailing_newline_after_multiple_adds(self, vault: Path) -> None:
        # Repeated appends must not accumulate blank lines or drop the newline.
        add_task(vault, "Task one", date(2026, 4, 7))
        path = add_task(vault, "Task two", date(2026, 4, 8))
        content = path.read_text(encoding="utf-8")
        assert content.endswith("\n")
        assert not content.endswith("\n\n")


# ---------------------------------------------------------------------------
# parse_tasks
# ---------------------------------------------------------------------------

class TestParseTasks:
    def test_parses_open_task(self, vault: Path) -> None:
        add_task(vault, "Pick up prescription", date(2026, 4, 7))
        path = get_or_create_weekly_file(vault)
        tasks = parse_tasks(path)
        assert len(tasks) == 1
        assert tasks[0].text == "Pick up prescription"
        assert tasks[0].due == date(2026, 4, 7)
        assert tasks[0].completed is False
        assert tasks[0].rolled is False

    def test_parses_completed_task(self, vault: Path) -> None:
        path = get_or_create_weekly_file(vault, "2026-W14")
        content = path.read_text(encoding="utf-8")
        content += "\n- [x] 2026-04-04 Done task"
        path.write_text(content, encoding="utf-8")
        tasks = parse_tasks(path)
        assert len(tasks) == 1
        assert tasks[0].completed is True

    def test_parses_rolled_task(self, vault: Path) -> None:
        path = get_or_create_weekly_file(vault, "2026-W14")
        content = path.read_text(encoding="utf-8")
        content += "\n- [>] 2026-04-04 Rolled task"
        path.write_text(content, encoding="utf-8")
        tasks = parse_tasks(path)
        assert len(tasks) == 1
        assert tasks[0].rolled is True

    def test_extracts_wikilinks(self, vault: Path) -> None:
        add_task(vault, "Review [[Housing]] and [[Finances]]", date(2026, 4, 7))
        path = get_or_create_weekly_file(vault)
        tasks = parse_tasks(path)
        assert tasks[0].links == ["Housing", "Finances"]

    def test_empty_file_returns_empty_list(self, vault: Path) -> None:
        path = get_or_create_weekly_file(vault, "2026-W14")
        tasks = parse_tasks(path)
        assert tasks == []

    def test_nonexistent_file_returns_empty_list(self, vault: Path) -> None:
        tasks = parse_tasks(vault / "personal" / "tasks" / "nonexistent.md")
        assert tasks == []

    def test_tracks_source_file(self, vault: Path) -> None:
        add_task(vault, "Test task", date(2026, 4, 7))
        path = get_or_create_weekly_file(vault)
        tasks = parse_tasks(path)
        assert tasks[0].source_file == path

    def test_tracks_line_number(self, vault: Path) -> None:
        add_task(vault, "Task one", date(2026, 4, 7))
        add_task(vault, "Task two", date(2026, 4, 8))
        path = get_or_create_weekly_file(vault)
        tasks = parse_tasks(path)
        assert tasks[0].line_number > 0
        assert tasks[1].line_number > tasks[0].line_number

    def test_skips_non_task_lines(self, vault: Path) -> None:
        path = get_or_create_weekly_file(vault, "2026-W14")
        content = path.read_text(encoding="utf-8")
        content += "\nSome random text\n- [ ] 2026-04-07 Real task\n## A heading"
        path.write_text(content, encoding="utf-8")
        tasks = parse_tasks(path)
        assert len(tasks) == 1
        assert tasks[0].text == "Real task"


# ---------------------------------------------------------------------------
# get_open_tasks
# ---------------------------------------------------------------------------

class TestGetOpenTasks:
    def test_returns_open_tasks_from_current_week(self, vault: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("task_manager.date", type("MockDate", (date,), {
            "today": staticmethod(lambda: date(2026, 4, 6)),  # Monday W15
        }))
        get_or_create_weekly_file(vault, "2026-W15")
        add_task(vault, "Open task", date(2026, 4, 7))
        tasks = get_open_tasks(vault)
        assert len(tasks) == 1

    def test_excludes_completed_tasks(self, vault: Path) -> None:
        path = get_or_create_weekly_file(vault, _week_string(date.today()))
        add_task(vault, "Open task", date.today())
        # Manually add a completed task
        with path.open("a", encoding="utf-8") as f:
            f.write(f"\n- [x] {date.today().isoformat()} Done task")
        tasks = get_open_tasks(vault)
        assert len(tasks) == 1
        assert tasks[0].text == "Open task"

    def test_excludes_rolled_tasks(self, vault: Path) -> None:
        path = get_or_create_weekly_file(vault, _week_string(date.today()))
        add_task(vault, "Open task", date.today())
        with path.open("a", encoding="utf-8") as f:
            f.write(f"\n- [>] {date.today().isoformat()} Rolled task")
        tasks = get_open_tasks(vault)
        assert len(tasks) == 1
        assert tasks[0].text == "Open task"

    def test_include_past_weeks(self, vault: Path) -> None:
        # Create tasks in two different weeks
        path_old = get_or_create_weekly_file(vault, "2026-W13")
        with path_old.open("a", encoding="utf-8") as f:
            f.write("\n- [ ] 2026-03-27 Old task")

        path_new = get_or_create_weekly_file(vault, "2026-W14")
        with path_new.open("a", encoding="utf-8") as f:
            f.write("\n- [ ] 2026-04-04 New task")

        tasks = get_open_tasks(vault, include_past_weeks=True)
        assert len(tasks) == 2

    def test_include_past_weeks_scans_archive(self, vault: Path) -> None:
        # A stray open (non-rolled, non-completed) task left in an already
        # archived week — e.g. from before the rollover-archives-source
        # behavior existed — must still surface as a safety net.
        archive_dir = vault / "personal" / "archive" / "tasks"
        archive_dir.mkdir(parents=True)
        (archive_dir / "2026-W13-tasks.md").write_text(
            "---\ndate: 2026-03-27\ndescription: \"x\"\ntags:\n  - tasks\nweek: \"2026-W13\"\n---\n"
            "\n- [ ] 2026-03-27 Missed task\n",
            encoding="utf-8",
        )

        tasks = get_open_tasks(vault, include_past_weeks=True)
        assert len(tasks) == 1
        assert tasks[0].text == "Missed task"

    def test_sorted_by_due_date(self, vault: Path) -> None:
        path = get_or_create_weekly_file(vault, _week_string(date.today()))
        with path.open("a", encoding="utf-8") as f:
            f.write("\n- [ ] 2026-04-09 Later task")
            f.write("\n- [ ] 2026-04-05 Earlier task")
        tasks = get_open_tasks(vault)
        assert tasks[0].due < tasks[1].due

    def test_empty_vault_returns_empty(self, vault: Path) -> None:
        tasks = get_open_tasks(vault)
        assert tasks == []

    def test_no_tasks_dir_returns_empty(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE.md").write_text("# Vault")
        tasks = get_open_tasks(tmp_path)
        assert tasks == []


# ---------------------------------------------------------------------------
# rollover_tasks
# ---------------------------------------------------------------------------

class TestRolloverTasks:
    def test_rolls_incomplete_tasks(self, vault: Path) -> None:
        path = get_or_create_weekly_file(vault, "2026-W13")
        with path.open("a", encoding="utf-8") as f:
            f.write("\n- [ ] 2026-03-27 Incomplete task")
            f.write("\n- [x] 2026-03-28 Done task")

        count = rollover_tasks(vault, "2026-W13", "2026-W14")
        assert count == 1

        # Target should have the task
        target = vault / "personal" / "tasks" / "2026-W14-tasks.md"
        target_content = target.read_text(encoding="utf-8")
        assert "Incomplete task" in target_content

    def test_marks_source_as_rolled(self, vault: Path) -> None:
        path = get_or_create_weekly_file(vault, "2026-W13")
        with path.open("a", encoding="utf-8") as f:
            f.write("\n- [ ] 2026-03-27 Task to roll")

        rollover_tasks(vault, "2026-W13", "2026-W14")

        archived = vault / "personal" / "archive" / "tasks" / "2026-W13-tasks.md"
        source_content = archived.read_text(encoding="utf-8")
        assert "- [>]" in source_content
        assert "- [ ] 2026-03-27 Task to roll" not in source_content

    def test_leaves_completed_in_source(self, vault: Path) -> None:
        path = get_or_create_weekly_file(vault, "2026-W13")
        with path.open("a", encoding="utf-8") as f:
            f.write("\n- [x] 2026-03-28 Done task")
            f.write("\n- [ ] 2026-03-27 Incomplete")

        rollover_tasks(vault, "2026-W13", "2026-W14")

        archived = vault / "personal" / "archive" / "tasks" / "2026-W13-tasks.md"
        source_content = archived.read_text(encoding="utf-8")
        assert "- [x] 2026-03-28 Done task" in source_content

    def test_creates_target_if_missing(self, vault: Path) -> None:
        path = get_or_create_weekly_file(vault, "2026-W13")
        with path.open("a", encoding="utf-8") as f:
            f.write("\n- [ ] 2026-03-27 Task")

        rollover_tasks(vault, "2026-W13", "2026-W14")

        target = vault / "personal" / "tasks" / "2026-W14-tasks.md"
        assert target.exists()

    def test_returns_zero_when_no_incomplete(self, vault: Path) -> None:
        path = get_or_create_weekly_file(vault, "2026-W13")
        with path.open("a", encoding="utf-8") as f:
            f.write("\n- [x] 2026-03-28 Done task")

        count = rollover_tasks(vault, "2026-W13", "2026-W14")
        assert count == 0

    def test_raises_on_missing_source(self, vault: Path) -> None:
        with pytest.raises(FileNotFoundError):
            rollover_tasks(vault, "2026-W01", "2026-W02")

    def test_archives_source_out_of_live_tasks_dir(self, vault: Path) -> None:
        path = get_or_create_weekly_file(vault, "2026-W13")
        with path.open("a", encoding="utf-8") as f:
            f.write("\n- [ ] 2026-03-27 Task to roll")

        rollover_tasks(vault, "2026-W13", "2026-W14")

        assert not path.exists()
        archived = vault / "personal" / "archive" / "tasks" / "2026-W13-tasks.md"
        assert archived.exists()

    def test_archives_source_even_when_no_incomplete(self, vault: Path) -> None:
        path = get_or_create_weekly_file(vault, "2026-W13")
        with path.open("a", encoding="utf-8") as f:
            f.write("\n- [x] 2026-03-28 Done task")

        rollover_tasks(vault, "2026-W13", "2026-W14")

        assert not path.exists()
        archived = vault / "personal" / "archive" / "tasks" / "2026-W13-tasks.md"
        assert archived.exists()
        assert "Done task" in archived.read_text(encoding="utf-8")

    def test_skips_already_rolled_tasks(self, vault: Path) -> None:
        path = get_or_create_weekly_file(vault, "2026-W13")
        with path.open("a", encoding="utf-8") as f:
            f.write("\n- [>] 2026-03-26 Already rolled")
            f.write("\n- [ ] 2026-03-27 New incomplete")

        count = rollover_tasks(vault, "2026-W13", "2026-W14")
        assert count == 1

    def test_rollover_preserves_wikilinks(self, vault: Path) -> None:
        path = get_or_create_weekly_file(vault, "2026-W13")
        with path.open("a", encoding="utf-8") as f:
            f.write("\n- [ ] 2026-03-27 Call about [[Housing]] lease")

        rollover_tasks(vault, "2026-W13", "2026-W14")

        target = vault / "personal" / "tasks" / "2026-W14-tasks.md"
        target_content = target.read_text(encoding="utf-8")
        assert "[[Housing]]" in target_content

    def test_multiple_rollover(self, vault: Path) -> None:
        path = get_or_create_weekly_file(vault, "2026-W13")
        with path.open("a", encoding="utf-8") as f:
            f.write("\n- [ ] 2026-03-27 Task A")
            f.write("\n- [ ] 2026-03-28 Task B")
            f.write("\n- [x] 2026-03-29 Done C")

        count = rollover_tasks(vault, "2026-W13", "2026-W14")
        assert count == 2

        target = vault / "personal" / "tasks" / "2026-W14-tasks.md"
        target_content = target.read_text(encoding="utf-8")
        assert "Task A" in target_content
        assert "Task B" in target_content
        assert "Done C" not in target_content

    def test_target_ends_with_single_trailing_newline(self, vault: Path) -> None:
        # #51 — the rollover target writer must leave the file ending in exactly
        # one trailing newline (POSIX-clean, no missing or double newline).
        path = get_or_create_weekly_file(vault, "2026-W13")
        with path.open("a", encoding="utf-8") as f:
            f.write("\n- [ ] 2026-03-27 Task to roll")

        rollover_tasks(vault, "2026-W13", "2026-W14")

        target = vault / "personal" / "tasks" / "2026-W14-tasks.md"
        content = target.read_text(encoding="utf-8")
        assert content.endswith("\n")
        assert not content.endswith("\n\n")

    def test_source_ends_with_single_trailing_newline(self, vault: Path) -> None:
        # #51 — the rollover source rewrite must also end in exactly one newline.
        path = get_or_create_weekly_file(vault, "2026-W13")
        with path.open("a", encoding="utf-8") as f:
            f.write("\n- [ ] 2026-03-27 Task to roll")

        rollover_tasks(vault, "2026-W13", "2026-W14")

        archived = vault / "personal" / "archive" / "tasks" / "2026-W13-tasks.md"
        content = archived.read_text(encoding="utf-8")
        assert content.endswith("\n")
        assert not content.endswith("\n\n")

    def test_preserves_dateless_task(self, vault: Path) -> None:
        # A task with no date stamp must roll over WITHOUT being stamped with
        # today's date (the #56 bug — rollover re-stamped dateless tasks).
        path = get_or_create_weekly_file(vault, "2026-W13")
        with path.open("a", encoding="utf-8") as f:
            f.write("\n- [ ] Buy milk")  # dateless
            f.write("\n- [ ] 2026-03-30 Dated task")

        count = rollover_tasks(vault, "2026-W13", "2026-W14")
        assert count == 2

        target = vault / "personal" / "tasks" / "2026-W14-tasks.md"
        target_content = target.read_text(encoding="utf-8")
        assert "- [ ] Buy milk" in target_content                 # dateless preserved
        assert "- [ ] 2026-03-30 Dated task" in target_content    # dated preserved
        assert f"- [ ] {date.today().isoformat()} Buy milk" not in target_content  # NOT re-stamped
