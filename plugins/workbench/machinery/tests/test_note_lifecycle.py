"""Tests for note_lifecycle.sweep_stale_prep (#773)."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(ENGINE_DIR))

from note_lifecycle import sweep_stale_prep

TODAY = date(2026, 6, 15)


def _note(day: str, status: str = "active", tag: str = "meeting-prep") -> str:
    return (
        f"---\ndate: {day}\nstatus: {status}\ntags:\n  - {tag}\n---\n# Body\n\ntext\n"
    )


def _write(root: Path, name: str, text: str, *, newline: str | None = None) -> Path:
    path = root / "work" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline=newline) as f:
        f.write(text)
    return path


def test_past_prep_note_flips_to_completed(tmp_path: Path) -> None:
    path = _write(tmp_path, "prep.md", _note("2026-06-01"))
    result = sweep_stale_prep(tmp_path, today=TODAY)
    assert result == {"flipped": ["work/prep.md"], "count": 1}
    assert "status: completed" in path.read_text(encoding="utf-8")


def test_future_dated_note_untouched(tmp_path: Path) -> None:
    text = _note("2026-07-01")
    path = _write(tmp_path, "prep.md", text)
    assert sweep_stale_prep(tmp_path, today=TODAY)["count"] == 0
    assert path.read_text(encoding="utf-8") == text


def test_note_without_prep_tag_untouched(tmp_path: Path) -> None:
    text = _note("2026-06-01", tag="other")
    path = _write(tmp_path, "n.md", text)
    assert sweep_stale_prep(tmp_path, today=TODAY)["count"] == 0
    assert path.read_text(encoding="utf-8") == text


def test_already_completed_is_idempotent(tmp_path: Path) -> None:
    text = _note("2026-06-01", status="completed")
    path = _write(tmp_path, "n.md", text)
    assert sweep_stale_prep(tmp_path, today=TODAY)["count"] == 0
    assert path.read_text(encoding="utf-8") == text
    _write(tmp_path, "p.md", _note("2026-06-01"))
    assert sweep_stale_prep(tmp_path, today=TODAY)["count"] == 1
    assert sweep_stale_prep(tmp_path, today=TODAY)["count"] == 0


def test_only_status_line_changes(tmp_path: Path) -> None:
    text = _note("2026-06-01")
    path = _write(tmp_path, "prep.md", text)
    sweep_stale_prep(tmp_path, today=TODAY)
    assert path.read_text(encoding="utf-8") == text.replace(
        "status: active", "status: completed"
    )


def test_missing_work_dir(tmp_path: Path) -> None:
    assert sweep_stale_prep(tmp_path, today=TODAY) == {"flipped": [], "count": 0}


def test_crlf_note_is_detected_and_flipped(tmp_path: Path) -> None:
    text = _note("2026-06-01").replace("\n", "\r\n")
    path = _write(tmp_path, "prep.md", text, newline="")
    result = sweep_stale_prep(tmp_path, today=TODAY)
    assert result["count"] == 1
    assert path.read_bytes() == text.replace("status: active", "status: completed").encode()
