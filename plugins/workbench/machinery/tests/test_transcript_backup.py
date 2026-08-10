"""Tests for transcript_backup — backup naming + retention for the PreCompact hook."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(SCRIPTS_DIR))

from transcript_backup import (
    DEFAULT_MAX_BACKUPS,
    RETENTION_GLOB,
    backup_transcript,
    enforce_retention,
)


def _make_log(log_dir: Path, name: str, mtime: float) -> Path:
    path = log_dir / name
    path.write_text("{}\n", encoding="utf-8")
    os.utime(path, (mtime, mtime))
    return path


class TestEnforceRetention:
    def test_deletes_only_oldest_past_cap(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "session-logs"
        log_dir.mkdir()
        # Create 5 logs with increasing mtimes (0 = oldest, 4 = newest).
        base = time.time()
        for i in range(5):
            _make_log(log_dir, f"session_manual_2026010{i}_000000.jsonl", base + i)

        enforce_retention(log_dir, max_backups=3)

        survivors = sorted(p.name for p in log_dir.glob(RETENTION_GLOB))
        # Exactly max_backups survive...
        assert len(survivors) == 3
        # ...and they are the 3 newest (indices 2,3,4); oldest two are gone.
        assert survivors == [
            "session_manual_20260102_000000.jsonl",
            "session_manual_20260103_000000.jsonl",
            "session_manual_20260104_000000.jsonl",
        ]

    def test_keeps_all_when_under_cap(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "session-logs"
        log_dir.mkdir()
        base = time.time()
        for i in range(2):
            _make_log(log_dir, f"session_auto_2026010{i}_000000.jsonl", base + i)

        enforce_retention(log_dir, max_backups=DEFAULT_MAX_BACKUPS)

        assert len(list(log_dir.glob(RETENTION_GLOB))) == 2

    def test_missing_dir_is_noop(self, tmp_path: Path) -> None:
        # Should not raise on a non-existent directory.
        enforce_retention(tmp_path / "does-not-exist", max_backups=3)

    def test_ignores_non_matching_files(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "session-logs"
        log_dir.mkdir()
        base = time.time()
        for i in range(4):
            _make_log(log_dir, f"session_manual_2026010{i}_000000.jsonl", base + i)
        # An unrelated file must never be deleted or counted.
        other = log_dir / "notes.txt"
        other.write_text("keep me", encoding="utf-8")

        enforce_retention(log_dir, max_backups=2)

        assert other.exists()
        assert len(list(log_dir.glob(RETENTION_GLOB))) == 2


class TestBackupTranscript:
    def test_creates_dest_and_returns_path(self, tmp_path: Path) -> None:
        source = tmp_path / "transcript.jsonl"
        source.write_text('{"a": 1}\n', encoding="utf-8")
        log_dir = tmp_path / "session-logs"

        dest = backup_transcript(source, log_dir, "manual", "20260101_120000")

        assert dest is not None
        assert dest.exists()
        assert dest.read_text(encoding="utf-8") == '{"a": 1}\n'

    def test_generated_name_matches_retention_glob(self, tmp_path: Path) -> None:
        source = tmp_path / "transcript.jsonl"
        source.write_text("{}\n", encoding="utf-8")
        log_dir = tmp_path / "session-logs"

        dest = backup_transcript(source, log_dir, "auto", "20260101_120000")

        assert dest is not None
        # The name this module produces must be found by the retention glob,
        # otherwise retention would silently never prune real backups.
        matched = list(log_dir.glob(RETENTION_GLOB))
        assert dest in matched

    def test_missing_source_returns_none(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "session-logs"
        result = backup_transcript(
            tmp_path / "nope.jsonl", log_dir, "manual", "20260101_120000"
        )
        assert result is None

    def test_backup_then_retention_round_trip(self, tmp_path: Path) -> None:
        source = tmp_path / "transcript.jsonl"
        source.write_text("{}\n", encoding="utf-8")
        log_dir = tmp_path / "session-logs"

        # Produce more backups than the cap, each with a distinct mtime.
        for i in range(4):
            dest = backup_transcript(
                source, log_dir, "manual", f"2026010{i}_000000"
            )
            assert dest is not None
            mtime = time.time() + i
            os.utime(dest, (mtime, mtime))

        enforce_retention(log_dir, max_backups=2)
        assert len(list(log_dir.glob(RETENTION_GLOB))) == 2
