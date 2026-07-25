from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(SCRIPTS_DIR))

from vault_scope import (  # noqa: E402
    is_governed_markdown_note,
    is_graph_markdown_note,
    is_transient_note,
    iter_governed_markdown_notes,
    iter_graph_markdown_notes,
)


def _write(root: Path, rel: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")
    return path


def test_governed_scope_excludes_docs_thinking_and_operating_files(tmp_path: Path) -> None:
    governed = _write(tmp_path, "brain/North Star.md")
    docs = _write(tmp_path, "docs/plan.md")
    thinking = _write(tmp_path, "thinking/draft.md")
    manual = _write(tmp_path, "work/AGENTS.md")

    assert is_governed_markdown_note(governed, tmp_path) is True
    assert is_governed_markdown_note(docs, tmp_path) is False
    assert is_governed_markdown_note(thinking, tmp_path) is False
    assert is_governed_markdown_note(manual, tmp_path) is False


def test_graph_scope_includes_thinking_but_excludes_docs_and_operating_files(tmp_path: Path) -> None:
    governed = _write(tmp_path, "brain/North Star.md")
    thinking = _write(tmp_path, "thinking/draft.md")
    docs = _write(tmp_path, "docs/plan.md")
    manual = _write(tmp_path, "personal/CLAUDE.md")
    session_log = _write(tmp_path, "thinking/session-logs/transcript.md")

    assert is_graph_markdown_note(governed, tmp_path) is True
    assert is_graph_markdown_note(thinking, tmp_path) is True
    assert is_graph_markdown_note(docs, tmp_path) is False
    assert is_graph_markdown_note(manual, tmp_path) is False
    assert is_graph_markdown_note(session_log, tmp_path) is False


def test_task_ledgers_are_governed_but_not_graph_notes(tmp_path: Path) -> None:
    current_work = _write(tmp_path, "work/Tasks.md")
    archived_personal = _write(tmp_path, "personal/archive/tasks/2026-W14-tasks.md")
    archived_work = _write(tmp_path, "work/archive/2026/tasks/2026-W14-tasks.md")

    assert is_transient_note(current_work, tmp_path) is True
    assert is_governed_markdown_note(current_work, tmp_path) is True
    assert is_graph_markdown_note(current_work, tmp_path) is False
    assert is_governed_markdown_note(archived_personal, tmp_path) is True
    assert is_graph_markdown_note(archived_personal, tmp_path) is False
    assert is_governed_markdown_note(archived_work, tmp_path) is True
    assert is_graph_markdown_note(archived_work, tmp_path) is False


def test_iterators_are_sorted_and_profile_specific(tmp_path: Path) -> None:
    _write(tmp_path, "personal/b.md")
    _write(tmp_path, "personal/a.md")
    _write(tmp_path, "thinking/draft.md")
    _write(tmp_path, "work/AGENTS.md")

    governed = [p.relative_to(tmp_path).as_posix() for p in iter_governed_markdown_notes(tmp_path)]
    graph = [p.relative_to(tmp_path).as_posix() for p in iter_graph_markdown_notes(tmp_path)]

    assert governed == ["personal/a.md", "personal/b.md"]
    assert graph == ["personal/a.md", "personal/b.md", "thinking/draft.md"]
