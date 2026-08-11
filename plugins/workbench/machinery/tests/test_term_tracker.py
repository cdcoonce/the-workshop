"""Tests for the term tracker — frequency counting and promote/demote logic."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(SCRIPTS_DIR))

from term_tracker import (
    DEMOTE_THRESHOLD,
    PROMOTE_THRESHOLD,
    get_demotions,
    get_promotions,
    load_frequencies,
    record_terms,
    save_frequencies,
)


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    """Minimal vault root with .claude/data/ available."""
    return tmp_path


def _freq_path(vault: Path) -> Path:
    return vault / ".claude" / "data" / "term-frequency.json"


# ---------------------------------------------------------------------------
# TestLoadSave
# ---------------------------------------------------------------------------


class TestLoadSave:
    def test_load_existing(self, vault: Path) -> None:
        """load_frequencies returns parsed data from an existing JSON file."""
        path = _freq_path(vault)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"REC": {"count": 3, "sessions": 2}}
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

        result = load_frequencies(vault)
        assert result == {"REC": {"count": 3, "sessions": 2}}

    def test_load_missing_returns_empty(self, vault: Path) -> None:
        """load_frequencies returns {} when the file does not exist."""
        result = load_frequencies(vault)
        assert result == {}

    def test_roundtrip(self, vault: Path) -> None:
        """save then load preserves the data exactly."""
        data = {
            "PCI": {"count": 10, "sessions": 5},
            "AMRT": {"count": 1, "sessions": 1},
        }
        save_frequencies(vault, data)
        loaded = load_frequencies(vault)
        assert loaded == data

        # Verify trailing newline is preserved
        raw = _freq_path(vault).read_text(encoding="utf-8")
        assert raw.endswith("\n")


# ---------------------------------------------------------------------------
# TestRecordTerms
# ---------------------------------------------------------------------------


class TestRecordTerms:
    def test_increments_existing(self, vault: Path) -> None:
        """record_terms increments count and sessions for a known term."""
        initial = {"REC": {"count": 3, "sessions": 2}}
        save_frequencies(vault, initial)

        record_terms(vault, ["REC"])

        data = load_frequencies(vault)
        assert data["REC"]["count"] == 4
        assert data["REC"]["sessions"] == 3

    def test_creates_new_entry(self, vault: Path) -> None:
        """record_terms creates a fresh entry for an unknown term."""
        record_terms(vault, ["SFTP"])

        data = load_frequencies(vault)
        assert "SFTP" in data
        assert data["SFTP"]["count"] == 1
        assert data["SFTP"]["sessions"] == 1

    def test_case_preserved(self, vault: Path) -> None:
        """Term keys retain their original casing."""
        record_terms(vault, ["BigQuery"])

        data = load_frequencies(vault)
        assert "BigQuery" in data
        assert "bigquery" not in data

    def test_count_is_total_occurrences_sessions_is_one(self, vault: Path) -> None:
        """A term occurring N times in one call: count += N, sessions += 1.

        This pins the new semantics — count means total occurrences seen
        across all time, sessions means distinct sessions the term appeared in.
        """
        record_terms(vault, ["REC", "REC", "REC"])

        data = load_frequencies(vault)
        assert data["REC"]["count"] == 3
        assert data["REC"]["sessions"] == 1

    def test_count_and_sessions_accumulate_across_calls(self, vault: Path) -> None:
        """Two separate calls: sessions -> 2, count -> combined occurrences."""
        record_terms(vault, ["REC", "REC"])  # 2 occurrences, session 1
        record_terms(vault, ["REC", "REC", "REC"])  # 3 occurrences, session 2

        data = load_frequencies(vault)
        assert data["REC"]["count"] == 5
        assert data["REC"]["sessions"] == 2

    def test_mixed_terms_distinct_occurrence_counts(self, vault: Path) -> None:
        """Different terms in one call accrue their own occurrence counts."""
        record_terms(vault, ["REC", "REC", "PCI"])

        data = load_frequencies(vault)
        assert data["REC"]["count"] == 2
        assert data["REC"]["sessions"] == 1
        assert data["PCI"]["count"] == 1
        assert data["PCI"]["sessions"] == 1


# ---------------------------------------------------------------------------
# TestPromotions
# ---------------------------------------------------------------------------


class TestPromotions:
    def test_promotes_high_frequency(self, vault: Path) -> None:
        """Terms at or above PROMOTE_THRESHOLD appear in promotions list."""
        data = {
            "REC": {"count": 20, "sessions": PROMOTE_THRESHOLD},
            "PCI": {"count": 30, "sessions": PROMOTE_THRESHOLD + 2},
        }
        save_frequencies(vault, data)

        result = get_promotions(vault, quick_ref_names=[])
        assert sorted(result) == ["PCI", "REC"]

    def test_skips_already_in_quick_ref(self, vault: Path) -> None:
        """Terms already in quick_ref_names are excluded from promotions."""
        data = {
            "REC": {"count": 20, "sessions": PROMOTE_THRESHOLD},
            "PCI": {"count": 30, "sessions": PROMOTE_THRESHOLD + 2},
        }
        save_frequencies(vault, data)

        result = get_promotions(vault, quick_ref_names=["REC"])
        assert result == ["PCI"]


# ---------------------------------------------------------------------------
# TestDemotions
# ---------------------------------------------------------------------------


class TestDemotions:
    def test_demotes_zero_sessions(self, vault: Path) -> None:
        """quick_ref names with sessions <= DEMOTE_THRESHOLD are flagged."""
        data = {
            "REC": {"count": 0, "sessions": 0},
            "PCI": {"count": 10, "sessions": 5},
        }
        save_frequencies(vault, data)

        result = get_demotions(vault, quick_ref_names=["REC", "PCI"])
        assert result == ["REC"]

    def test_demotes_missing_from_frequency_data(self, vault: Path) -> None:
        """quick_ref names absent from frequency data are flagged for demotion."""
        data = {"PCI": {"count": 10, "sessions": 5}}
        save_frequencies(vault, data)

        result = get_demotions(vault, quick_ref_names=["REC", "PCI"])
        assert result == ["REC"]
