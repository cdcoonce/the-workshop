"""Canonical vault scope rules shared by validation, graph, and search tools."""

from __future__ import annotations

from pathlib import Path

# Governed notes must carry frontmatter and obey the wikilink rule.
GOVERNED_NOTE_DIRS = ("brain", "work", "personal", "org", "perf", "reference")

# Graph/search notes include working drafts so backlinks can surface promotion
# candidates, but operating manuals and generated/session state are excluded.
GRAPH_NOTE_DIRS = (*GOVERNED_NOTE_DIRS, "thinking")

GRAPH_EXCLUDED_DIRS = {
    ".afk",
    ".brain",
    ".claude",
    ".codex",
    ".obsidian",
    ".pytest_cache",
    ".superpowers",
    ".venv",
    "session-logs",
    "templates",
}

VALIDATION_EXCLUDED_DIRS = {
    *GRAPH_EXCLUDED_DIRS,
    "docs",
    "thinking",
}

OPERATING_FILENAMES = {
    "AGENTS.md",
    "AGENTS.local.md",
    "CLAUDE.md",
    "CLAUDE.local.md",
}

ROOT_EXCLUDED_FILENAMES = {
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "README.md",
    "SETUP.md",
}

TRANSIENT_PREFIXES = (
    "work/Tasks.md",
    "personal/tasks/",
    "personal/archive/tasks/",
    "work/tasks/",
    "work/archive/tasks/",
    "work/archive/2026/tasks/",
)

# Task-file locations and section names — owner-configurable; task_manager and
# work_task_manager read these rather than hardcoding paths.
TASKS_DIR = "personal/tasks"
ARCHIVE_TASKS_DIR = "personal/archive/tasks"

WORK_TASKS_DIR = "work"
WORK_TASKS_FILENAME = "Tasks.md"
WORK_TASKS_ARCHIVE_DIR = "work/archive/tasks"
WORK_TASK_SECTIONS: tuple[str, ...] = ("Active", "Waiting On", "Someday", "Done")
WORK_TASKS_DONE_SECTION = "Done"


def rel_posix(path: Path, vault_root: Path) -> str | None:
    """Return a vault-relative POSIX path, or None when outside the vault."""
    try:
        return path.relative_to(vault_root).as_posix()
    except ValueError:
        return None


def _rel_parts(path: Path, vault_root: Path) -> tuple[str, ...] | None:
    try:
        return path.relative_to(vault_root).parts
    except ValueError:
        return None


def is_operating_file(path: Path) -> bool:
    """True for agent operating manuals, which are policy rather than notes."""
    return path.name in OPERATING_FILENAMES


def is_root_excluded_file(path: Path, vault_root: Path) -> bool:
    """True for root-level repo docs that are not vault notes."""
    parts = _rel_parts(path, vault_root)
    return bool(parts and len(parts) == 1 and path.name in ROOT_EXCLUDED_FILENAMES)


def is_transient_note(path: Path, vault_root: Path) -> bool:
    """True for task ledgers/state files that are governed but not graph knowledge."""
    rel = rel_posix(path, vault_root)
    return bool(rel and rel.startswith(TRANSIENT_PREFIXES))


def is_under_excluded_dir(
    path: Path,
    vault_root: Path,
    excluded_dirs: set[str],
) -> bool:
    """True when any path component is an excluded directory."""
    parts = _rel_parts(path, vault_root)
    if not parts:
        return True
    return any(part in excluded_dirs or part.startswith(".") for part in parts[:-1])


def is_graph_excluded(path: Path, vault_root: Path) -> bool:
    """True when a Markdown file exists but should not enter graph/search scope."""
    return (
        is_operating_file(path)
        or is_root_excluded_file(path, vault_root)
        or is_transient_note(path, vault_root)
        or is_under_excluded_dir(path, vault_root, GRAPH_EXCLUDED_DIRS)
    )


def is_governed_excluded(path: Path, vault_root: Path) -> bool:
    """True when a Markdown file is intentionally exempt from note validation."""
    return (
        is_operating_file(path)
        or is_root_excluded_file(path, vault_root)
        or is_under_excluded_dir(path, vault_root, VALIDATION_EXCLUDED_DIRS)
    )


def is_markdown_in_dirs(path: Path, vault_root: Path, dirs: tuple[str, ...]) -> bool:
    """True for Markdown files under one of the given top-level directories."""
    if path.suffix.lower() != ".md":
        return False
    parts = _rel_parts(path, vault_root)
    return bool(parts and parts[0] in dirs)


def is_graph_markdown_note(path: Path, vault_root: Path) -> bool:
    """True for Markdown notes that participate in graph/search operations."""
    return (
        is_markdown_in_dirs(path, vault_root, GRAPH_NOTE_DIRS)
        and not is_graph_excluded(path, vault_root)
    )


def is_governed_markdown_note(path: Path, vault_root: Path) -> bool:
    """True for Markdown notes that must satisfy vault note validation."""
    return (
        is_markdown_in_dirs(path, vault_root, GOVERNED_NOTE_DIRS)
        and not is_governed_excluded(path, vault_root)
    )


def iter_graph_markdown_notes(vault_root: Path) -> list[Path]:
    """Sorted graph/search Markdown notes."""
    notes: list[Path] = []
    for folder_name in GRAPH_NOTE_DIRS:
        folder = vault_root / folder_name
        if not folder.is_dir():
            continue
        notes.extend(
            p for p in folder.rglob("*.md")
            if is_graph_markdown_note(p, vault_root)
        )
    return sorted(notes)


def iter_governed_markdown_notes(vault_root: Path) -> list[Path]:
    """Sorted governed Markdown notes."""
    notes: list[Path] = []
    for folder_name in GOVERNED_NOTE_DIRS:
        folder = vault_root / folder_name
        if not folder.is_dir():
            continue
        notes.extend(
            p for p in folder.rglob("*.md")
            if is_governed_markdown_note(p, vault_root)
        )
    return sorted(notes)
