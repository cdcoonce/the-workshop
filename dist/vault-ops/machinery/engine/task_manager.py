"""Task Manager — manages weekly task files in the configured tasks directory.

Public interface:
    get_or_create_weekly_file(vault_root, week?) → Path
    add_task(vault_root, text, due_date?, links?) → Path
    parse_tasks(file_path) → list[Task]
    get_open_tasks(vault_root, include_past_weeks?) → list[Task]
    rollover_tasks(vault_root, source_week, target_week) → int
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

# Add scripts dir to path for imports
import sys
SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from frontmatter_engine import generate
from vault_scope_resolved import ARCHIVE_TASKS_DIR, TASKS_DIR
from vault_utils import WIKILINK_CAPTURE_RE, iso_week_string


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

@dataclass
class Task:
    """A single parsed task from a weekly file."""
    text: str
    due: date | None = None
    completed: bool = False
    rolled: bool = False
    links: list[str] = field(default_factory=list)
    source_file: Path | None = None
    line_number: int = 0


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TASK_RE = re.compile(
    r"^- \[(?P<status>[ x>])\] "
    r"(?:(?P<due>\d{4}-\d{2}-\d{2}) )?"
    r"(?P<text>.+)$"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _week_string(d: date) -> str:
    """Format a date as an ISO week string (YYYY-W##)."""
    return iso_week_string(d)


def _tasks_dir(vault_root: Path) -> Path:
    """Return the tasks directory path, creating it if needed."""
    d = vault_root / TASKS_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _weekly_filename(week: str) -> str:
    """Convert a week string to a filename."""
    return f"{week}-tasks.md"


def _format_task_line(text: str, due_date: date | None = None, links: list[str] | None = None) -> str:
    """Format a task as a markdown checkbox line.

    A ``None`` due date is preserved as a dateless line (``- [ ] text``) — the parser treats the date as
    optional, so rollover must not invent one. Callers wanting a default (e.g. add_task) pass it in.
    """
    task_text = text.strip()

    # Append wikilinks that aren't already in the text
    if links:
        for link in links:
            wikilink = f"[[{link}]]"
            if wikilink not in task_text:
                task_text = f"{task_text} {wikilink}"

    if due_date is None:
        return f"- [ ] {task_text}"
    return f"- [ ] {due_date.isoformat()} {task_text}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_or_create_weekly_file(vault_root: Path, week: str | None = None) -> Path:
    """Get or create the weekly task file for a given week.

    Args:
        vault_root: Path to the vault root.
        week: ISO week string (e.g., "2026-W14"). Defaults to current week.

    Returns:
        Path to the weekly task file.
    """
    if week is None:
        week = _week_string(date.today())

    tasks_dir = _tasks_dir(vault_root)
    file_path = tasks_dir / _weekly_filename(week)

    if file_path.exists():
        return file_path

    # Parse week string for metadata
    parts = week.split("-W")
    year = parts[0]
    week_num = parts[1]

    # Generate frontmatter using the engine (tasks type includes week field)
    frontmatter = generate("tasks", {
        "date": date.today().isoformat(),
        "description": f"Personal tasks for week {week_num}, {year}",
        "tags": ["tasks"],
        "week": week,
    })

    content = f"{frontmatter}\n# Tasks — {week}\n"
    file_path.write_text(content, encoding="utf-8")

    return file_path


def add_task(
    vault_root: Path,
    text: str,
    due_date: date | None = None,
    links: list[str] | None = None,
) -> Path:
    """Add a task to the current week's task file.

    Args:
        vault_root: Path to the vault root.
        text: Task description text.
        due_date: Optional due date. Defaults to today.
        links: Optional list of wikilink targets (without brackets).

    Returns:
        Path to the weekly task file the task was added to.

    Raises:
        ValueError: If text is empty.
    """
    if not text or not text.strip():
        raise ValueError("Task text cannot be empty")

    file_path = get_or_create_weekly_file(vault_root)
    # add_task defaults a missing due date to today (documented behavior); _format_task_line itself
    # preserves None as dateless, so the default is applied here rather than in the formatter.
    task_line = _format_task_line(text, due_date or date.today(), links)

    # Read-modify-write so the file always ends with exactly one trailing
    # newline (#51): strip any trailing whitespace, re-append the new task, and
    # terminate with a single newline. Tasks stay contiguous below the heading.
    existing = file_path.read_text(encoding="utf-8").rstrip("\n")
    file_path.write_text(f"{existing}\n{task_line}\n", encoding="utf-8")

    return file_path


def parse_tasks(file_path: Path) -> list[Task]:
    """Parse tasks from a weekly task file.

    Args:
        file_path: Path to a weekly task file.

    Returns:
        List of Task objects. Empty list if file doesn't exist or has no tasks.
    """
    if not file_path.exists():
        return []

    content = file_path.read_text(encoding="utf-8")
    tasks: list[Task] = []

    for line_num, line in enumerate(content.splitlines(), 1):
        match = TASK_RE.match(line.strip())
        if not match:
            continue

        status = match.group("status")
        due_str = match.group("due")
        text = match.group("text")

        # Extract wikilinks from text
        links = WIKILINK_CAPTURE_RE.findall(text)

        due = None
        if due_str:
            try:
                parts = due_str.split("-")
                due = date(int(parts[0]), int(parts[1]), int(parts[2]))
            except (ValueError, IndexError):
                pass

        tasks.append(Task(
            text=text,
            due=due,
            completed=(status == "x"),
            rolled=(status == ">"),
            links=links,
            source_file=file_path,
            line_number=line_num,
        ))

    return tasks


def get_open_tasks(vault_root: Path, include_past_weeks: bool = False) -> list[Task]:
    """Get all open (unchecked) tasks.

    Args:
        vault_root: Path to the vault root.
        include_past_weeks: If True, include tasks from past week files.
            If False, only return tasks from the current week.

    Returns:
        List of open Task objects, sorted by due date.
    """
    tasks_dir = vault_root / TASKS_DIR
    current_week = _week_string(date.today())
    open_tasks: list[Task] = []

    search_dirs = [tasks_dir]
    if include_past_weeks:
        archive_dir = vault_root / ARCHIVE_TASKS_DIR
        if archive_dir.exists():
            search_dirs.append(archive_dir)

    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        for task_file in sorted(search_dir.glob("*-tasks.md")):
            # Extract week from filename (e.g., "2026-W14-tasks.md" → "2026-W14")
            week = task_file.stem.replace("-tasks", "")

            if not include_past_weeks and week != current_week:
                continue

            for task in parse_tasks(task_file):
                if not task.completed and not task.rolled:
                    open_tasks.append(task)

    # Sort by due date (None last)
    open_tasks.sort(key=lambda t: t.due or date.max)
    return open_tasks


def rollover_tasks(vault_root: Path, source_week: str, target_week: str) -> int:
    """Roll incomplete tasks from one week to another, then archive the source week.

    Incomplete tasks are copied to the target week's file and marked as rolled
    (- [>]) in the source file. The source week's file is then moved to
    ``personal/archive/tasks/`` — mirroring ``work_task_manager``'s
    immediate-archive-on-rollover pattern — so resolved weeks don't pile up
    unarchived in ``personal/tasks/``.

    Args:
        vault_root: Path to the vault root.
        source_week: ISO week string for the source (e.g., "2026-W13").
        target_week: ISO week string for the target (e.g., "2026-W14").

    Returns:
        Number of tasks rolled over.

    Raises:
        FileNotFoundError: If the source week file doesn't exist.
    """
    tasks_dir = vault_root / TASKS_DIR
    source_path = tasks_dir / _weekly_filename(source_week)

    if not source_path.exists():
        raise FileNotFoundError(f"Source week file not found: {source_path}")

    # Parse source tasks
    source_tasks = parse_tasks(source_path)
    incomplete = [t for t in source_tasks if not t.completed and not t.rolled]

    if incomplete:
        # Ensure target file exists
        target_path = get_or_create_weekly_file(vault_root, target_week)

        # Append incomplete tasks to target, ending with exactly one trailing
        # newline (#51). Read-modify-write keeps tasks contiguous below the heading.
        rolled_lines = [
            # Re-format the task line — wikilinks are already embedded in task.text
            _format_task_line(task.text, task.due)
            for task in incomplete
        ]
        target_existing = target_path.read_text(encoding="utf-8").rstrip("\n")
        target_path.write_text(
            target_existing + "\n" + "\n".join(rolled_lines) + "\n",
            encoding="utf-8",
        )

        # Mark source tasks as rolled
        source_content = source_path.read_text(encoding="utf-8")
        source_lines = source_content.splitlines()

        for task in incomplete:
            if 0 < task.line_number <= len(source_lines):
                line = source_lines[task.line_number - 1]
                source_lines[task.line_number - 1] = line.replace("- [ ]", "- [>]", 1)

        source_path.write_text("\n".join(source_lines) + "\n", encoding="utf-8")

    # The source week is now fully resolved (rolled or all-complete) — archive
    # it so it stops appearing alongside the live current-week file.
    archive_dir = vault_root / ARCHIVE_TASKS_DIR
    archive_dir.mkdir(parents=True, exist_ok=True)
    source_path.replace(archive_dir / _weekly_filename(source_week))

    return len(incomplete)

    return len(incomplete)
