"""Work Task Manager — CRUD for the configured work tasks file with section-based organization.

Public interface:
    ensure_work_tasks_file(vault_root) -> Path
    parse_work_tasks(file_path) -> list[WorkTask]
    add_work_task(vault_root, title, section, provenance?, links?) -> None
    complete_work_task(vault_root, title) -> bool
    has_duplicate(vault_root, title) -> bool
    rollover_work_tasks(vault_root, today?) -> dict
    SECTIONS constant
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Imports from sibling scripts
# ---------------------------------------------------------------------------

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from frontmatter_engine import generate
from vault_scope import (
    WORK_TASK_SECTIONS as SECTIONS,
    WORK_TASKS_ARCHIVE_DIR,
    WORK_TASKS_DIR,
    WORK_TASKS_DONE_SECTION,
    WORK_TASKS_FILENAME,
)
from vault_utils import WIKILINK_CAPTURE_RE, iso_week_string

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TASK_RE = re.compile(
    r"^- \[(?P<status>[ x])\] "
    r"\*\*(?P<title>[^*]+)\*\*"
    r"(?P<rest>.*)"
)
PROVENANCE_RE = re.compile(r"\(from:\s*(?P<prov>[^)]+)\)")


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

@dataclass
class WorkTask:
    title: str
    section: str
    completed: bool = False
    provenance: str = ""
    rest: str = ""
    links: list[str] = field(default_factory=list)
    line_number: int = 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _work_tasks_dir(vault_root: Path) -> Path:
    """Return the work tasks directory path, creating it if needed."""
    d = vault_root / WORK_TASKS_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _work_tasks_path(vault_root: Path) -> Path:
    """Return the path to the work tasks file (may not exist)."""
    return vault_root / WORK_TASKS_DIR / WORK_TASKS_FILENAME


def _find_section_end(lines: list[str], header_idx: int) -> int:
    """Return the index where new content should be inserted after a section header.

    Walks past existing task lines and blank lines following the header.
    """
    j = header_idx + 1
    while j < len(lines):
        stripped = lines[j].strip()
        if stripped.startswith("- [") or stripped == "":
            j += 1
        else:
            break
    return j


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def ensure_work_tasks_file(vault_root: Path) -> Path:
    """Create work/Tasks.md with frontmatter and section headers if it doesn't exist.

    Returns the path to the file.
    """
    vault_root = Path(vault_root)
    tasks_dir = _work_tasks_dir(vault_root)
    tasks_path = tasks_dir / WORK_TASKS_FILENAME

    if tasks_path.exists():
        return tasks_path

    frontmatter = generate("tasks", {
        "description": "Active work tasks organized by status",
        "tags": ["tasks", "work"],
        "week": date.today().isoformat(),
    })

    lines = [frontmatter, "# Work Tasks\n\n"]
    for section in SECTIONS:
        lines.append(f"## {section}\n\n")

    tasks_path.write_text("".join(lines), encoding="utf-8")
    return tasks_path


def parse_work_tasks(file_path: Path) -> list[WorkTask]:
    """Parse all tasks from a work Tasks.md file, grouped by section headers.

    Returns a list of WorkTask objects.
    """
    file_path = Path(file_path)
    if not file_path.exists():
        return []

    content = file_path.read_text(encoding="utf-8")
    lines = content.splitlines()

    tasks: list[WorkTask] = []
    current_section = ""

    for line_num, line in enumerate(lines, start=1):
        # Detect section headers
        if line.startswith("## "):
            header = line[3:].strip()
            if header in SECTIONS:
                current_section = header
            continue

        # Try to match a task line
        match = TASK_RE.match(line)
        if match and current_section:
            status = match.group("status")
            title = match.group("title").strip()
            rest = match.group("rest").strip()

            # Extract provenance
            provenance = ""
            prov_match = PROVENANCE_RE.search(rest)
            if prov_match:
                provenance = prov_match.group("prov").strip()

            # Extract wikilinks
            links = WIKILINK_CAPTURE_RE.findall(rest)

            tasks.append(WorkTask(
                title=title,
                section=current_section,
                completed=(status == "x"),
                provenance=provenance,
                rest=rest,
                links=links,
                line_number=line_num,
            ))

    return tasks


def add_work_task(
    vault_root: Path,
    title: str,
    section: str,
    provenance: str = "",
    links: list[str] | None = None,
) -> None:
    """Add a task line under the specified section in work/Tasks.md.

    Raises ValueError if the section name is not in SECTIONS.
    """
    if section not in SECTIONS:
        raise ValueError(
            f"Invalid section '{section}'. Must be one of: {', '.join(SECTIONS)}"
        )

    vault_root = Path(vault_root)
    tasks_path = ensure_work_tasks_file(vault_root)
    content = tasks_path.read_text(encoding="utf-8")
    lines = content.splitlines()

    # Build the task line
    task_line = f"- [ ] **{title}**"
    if provenance:
        task_line += f" (from: {provenance})"
    if links:
        link_strs = [f" [[{link}]]" for link in links]
        task_line += "".join(link_strs)

    # Find the section header and insert after existing tasks
    section_header = f"## {section}"
    insert_idx = None

    for i, line in enumerate(lines):
        if line.strip() == section_header:
            insert_idx = _find_section_end(lines, i)
            break

    if insert_idx is not None:
        lines.insert(insert_idx, task_line)
    else:
        # Shouldn't happen if ensure_work_tasks_file ran, but fallback
        lines.append(task_line)

    tasks_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def complete_work_task(vault_root: Path, title: str) -> bool:
    """Mark a task as complete, move it to Done section, append completion date.

    Returns True if the task was found and completed, False otherwise.
    """
    vault_root = Path(vault_root)
    tasks_path = _work_tasks_path(vault_root)
    if not tasks_path.exists():
        return False

    content = tasks_path.read_text(encoding="utf-8")
    lines = content.splitlines()

    # Find the task line
    task_line_idx = None
    for i, line in enumerate(lines):
        match = TASK_RE.match(line)
        if match and match.group("status") == " ":
            if match.group("title").strip().lower() == title.lower():
                task_line_idx = i
                break

    if task_line_idx is None:
        return False

    # Extract the original line and build the completed version
    original_line = lines[task_line_idx]
    match = TASK_RE.match(original_line)
    task_title = match.group("title").strip()
    rest = match.group("rest").strip()
    completed_line = f"- [x] **{task_title}**"
    if rest:
        completed_line += f" {rest}"
    completed_line += f" (completed: {date.today().isoformat()})"

    # Remove from current position
    lines.pop(task_line_idx)

    # Find the done section and insert there
    done_header = f"## {WORK_TASKS_DONE_SECTION}"
    inserted = False
    for i, line in enumerate(lines):
        if line.strip() == done_header:
            insert_at = _find_section_end(lines, i)
            lines.insert(insert_at, completed_line)
            inserted = True
            break

    if not inserted:
        # Done section missing — restore the task to avoid data loss
        lines.insert(task_line_idx, original_line)
        tasks_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return False

    tasks_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True


def _iso_week_string(d: date) -> str:
    return iso_week_string(d)


def _strip_task_fields(content: str) -> str:
    """Remove non-schema ``status:``/``project:`` lines from a task file's frontmatter.

    The ``tasks`` note type's frontmatter is date/description/tags/week only; a
    stray ``status: active`` on an archived week makes it read as a live project
    in status-based views (e.g. Obsidian Bases). Only the leading frontmatter
    block is touched; the body is left byte-for-byte intact.
    """
    lines = content.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\n") != "---":
        return content
    end = None
    for i in range(1, len(lines)):
        if lines[i].rstrip("\n") == "---":
            end = i
            break
    if end is None:
        return content
    kept = [lines[0]]
    kept += [l for l in lines[1:end] if not re.match(r"^(status|project):\s", l)]
    kept += lines[end:]
    return "".join(kept)


def rollover_work_tasks(vault_root: Path, today: date | None = None) -> dict:
    """Archive current work/Tasks.md and rewrite it with only open items carrying forward.

    Carries forward: all `[ ]` items from Active, Waiting On, and Someday sections,
    preserving `### [[Project]]` subsection headers unless every task under them is
    now complete. Drops: all `[x]` items and the entire Done section (lives in the
    archive). Updates the frontmatter `week:` field to the Monday of today's ISO week.

    Idempotent: if the frontmatter week already matches today's ISO week, does nothing.

    Returns dict with keys:
        rolled_over (bool)
        reason (str) — why no-op when rolled_over is False
        archive_path (Path) — on success
        archived_week (str) — e.g., "2026-W17"
        new_week (str) — e.g., "2026-W18"
        done_items (list[str]) — `[x]` lines from the Done section for Brag Doc scan
    """
    today = today or date.today()
    vault_root = Path(vault_root)
    tasks_path = _work_tasks_path(vault_root)

    if not tasks_path.exists():
        return {"rolled_over": False, "reason": f"{WORK_TASKS_DIR}/{WORK_TASKS_FILENAME} not found"}

    content = tasks_path.read_text(encoding="utf-8")

    fm_match = re.search(
        r'^week:\s*"?(\d{4}-\d{2}-\d{2})"?\s*$',
        content,
        flags=re.MULTILINE,
    )
    if not fm_match:
        return {"rolled_over": False, "reason": "No week field in frontmatter"}

    try:
        fm_week_date = date.fromisoformat(fm_match.group(1))
    except ValueError:
        return {"rolled_over": False, "reason": f"Invalid week date: {fm_match.group(1)}"}

    fm_iso = _iso_week_string(fm_week_date)
    today_iso = _iso_week_string(today)

    if fm_iso == today_iso:
        return {"rolled_over": False, "reason": f"Already in {today_iso}"}

    # Archive the current file, stripping non-schema status/project fields so
    # archived weeks aren't miscategorized as live projects (the tasks-type
    # frontmatter is date/description/tags/week only). See _strip_task_fields.
    archive_dir = vault_root / WORK_TASKS_ARCHIVE_DIR
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_path = archive_dir / f"{fm_iso}-tasks.md"
    archive_path.write_text(_strip_task_fields(content), encoding="utf-8")

    lines = content.splitlines()

    fm_end = 0
    if lines and lines[0] == "---":
        for i in range(1, len(lines)):
            if lines[i] == "---":
                fm_end = i
                break

    # Rewrite frontmatter with today's Monday in the week field
    today_monday = today - timedelta(days=today.isoweekday() - 1)
    fm_lines: list[str] = []
    for i in range(fm_end + 1):
        line = lines[i]
        if re.match(r"^week:\s", line):
            fm_lines.append(f'week: "{today_monday.isoformat()}"')
        else:
            fm_lines.append(line)

    # Partition body into sections by H2 header
    body_lines = lines[fm_end + 1:]
    sections: dict[str, list[str]] = {"_preamble": []}
    current_section = "_preamble"

    for line in body_lines:
        if line.startswith("## "):
            current_section = line[3:].strip()
            sections[current_section] = []
            continue
        sections[current_section].append(line)

    # Capture done items for the Brag Doc scan before discarding
    done_items: list[str] = []
    for line in sections.get(WORK_TASKS_DONE_SECTION, []):
        if re.match(r"^\s*- \[x\]", line):
            done_items.append(line.strip())

    def _filter_carry_forward(section_lines: list[str]) -> list[str]:
        """Keep `[ ]` task lines and the `### ...` subsection headers that still
        have at least one open task. Drop `[x]` lines and empty subsections."""
        groups: list[tuple[str | None, list[str]]] = []
        current_header: str | None = None
        current_body: list[str] = []

        for ln in section_lines:
            if ln.startswith("### "):
                groups.append((current_header, current_body))
                current_header = ln
                current_body = []
            else:
                current_body.append(ln)
        groups.append((current_header, current_body))

        output: list[str] = []
        for header, body in groups:
            kept = [ln for ln in body if not re.match(r"^\s*- \[x\]", ln)]
            has_open = any(re.match(r"^\s*- \[ \]", ln) for ln in kept)
            if has_open:
                if header is not None:
                    output.append(header)
                output.extend(kept)
            # else: drop — either preamble with no open tasks or empty subsection

        while output and not output[0].strip():
            output.pop(0)
        while output and not output[-1].strip():
            output.pop()

        return output

    new_lines = fm_lines + ["", "# Work Tasks", ""]
    for section in SECTIONS:
        new_lines.append(f"## {section}")
        new_lines.append("")
        if section == WORK_TASKS_DONE_SECTION:
            continue
        filtered = _filter_carry_forward(sections.get(section, []))
        if filtered:
            new_lines.extend(filtered)
            new_lines.append("")

    tasks_path.write_text("\n".join(new_lines).rstrip() + "\n", encoding="utf-8")

    return {
        "rolled_over": True,
        "archive_path": archive_path,
        "archived_week": fm_iso,
        "new_week": today_iso,
        "done_items": done_items,
    }


def has_duplicate(vault_root: Path, title: str) -> bool:
    """Check if an uncompleted task with the same title (case-insensitive) exists.

    Ignores completed tasks.
    """
    vault_root = Path(vault_root)
    tasks_path = _work_tasks_path(vault_root)
    if not tasks_path.exists():
        return False

    tasks = parse_work_tasks(tasks_path)
    title_lower = title.lower()
    return any(
        t.title.lower() == title_lower and not t.completed
        for t in tasks
    )
