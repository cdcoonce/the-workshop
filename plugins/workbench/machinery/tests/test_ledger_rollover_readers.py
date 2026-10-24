"""Readers keep working after the quarterly ledger rollover (#1303, B5)."""

from __future__ import annotations

import sys
from pathlib import Path
from zoneinfo import ZoneInfo

ENGINE_DIR = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(ENGINE_DIR))

import graph_gardener  # noqa: E402
import ledger_rollover  # noqa: E402
import vault_audit  # noqa: E402
from pulse import collect_wins  # noqa: E402

TZ = ZoneInfo("America/Denver")

ARCHIVED = (
    "---\ndate: 2026-10-24\ndescription: x\ntags:\n  - brag-doc-archive\n---\n"
    "# Brag 2026 Q3\n\nBack to [[Brag Doc]].\n\n## Q3 2026\n\n### Wins\n\n"
    "- **2026-07-22 (x) archived win**\n- **2026-07-21 (x) another**\n"
)


def test_collect_wins_counts_archived_wins_beside_the_live_file(tmp_path: Path) -> None:
    perf = tmp_path / "perf"
    (perf / "archive").mkdir(parents=True)
    live = perf / "Brag Doc.md"
    live.write_text("# Brag\n## Q4 2026\n- **2026-10-20 (x) live win**\n")
    (perf / "archive" / "brag-2026-Q3.md").write_text(ARCHIVED)
    got = collect_wins(live, TZ)
    assert got == {"2026-W43": 1, "2026-W30": 2}


def test_collect_wins_history_does_not_shrink_after_a_rollover(tmp_path: Path) -> None:
    perf = tmp_path / "perf"
    perf.mkdir()
    live = perf / "Brag Doc.md"
    before_text = (
        "---\ndate: 2026-01-01\ndescription: b\ntags:\n  - brag-doc\n---\n# Brag Doc\n\n"
        "## Q4 2026\n\n### Wins\n\n- **2026-10-20 (x) a**\n\n"
        "## Q3 2026\n\n### Wins\n\n- **2026-07-22 (x) b**\n- **2026-07-21 (x) c**\n"
    )
    live.write_text(before_text)
    before = collect_wins(live, TZ)
    from datetime import date

    ledger_rollover.rollover_ledgers(tmp_path, today=date(2026, 10, 24), apply=True)
    assert "## Q3 2026" not in live.read_text()
    assert collect_wins(live, TZ) == before


def test_collect_wins_reads_archives_when_the_live_file_is_absent(tmp_path: Path) -> None:
    (tmp_path / "perf" / "archive").mkdir(parents=True)
    (tmp_path / "perf" / "archive" / "brag-2026-Q3.md").write_text(ARCHIVED)
    assert collect_wins(tmp_path / "perf" / "Brag Doc.md", TZ) == {"2026-W30": 2}


def test_collect_wins_ignores_non_brag_files_in_the_archive_dir(tmp_path: Path) -> None:
    perf = tmp_path / "perf"
    (perf / "archive").mkdir(parents=True)
    (perf / "archive" / "notes.md").write_text("- **2026-07-22 (x) not a brag archive**\n")
    assert collect_wins(perf / "Brag Doc.md", TZ) == {}


ARCHIVE_PATHS = [
    "brain/archive/key-decisions/2026-Q3.md",
    "perf/archive/brag-2026-Q3.md",
]


def test_archive_paths_match_the_rollover_layout() -> None:
    assert ledger_rollover.archive_path_key_decisions("2026-Q3") == ARCHIVE_PATHS[0]
    assert ledger_rollover.archive_path_brag("2026-Q3") == ARCHIVE_PATHS[1]


def test_vault_audit_hub_set_covers_archive_paths() -> None:
    for rel in ARCHIVE_PATHS:
        assert vault_audit.is_accumulating_hub(rel)
    assert not vault_audit.is_accumulating_hub("brain/Decision Log.md")
    assert not vault_audit.is_accumulating_hub("perf/archive/other.md")
    assert vault_audit.is_accumulating_hub("brain/Key Decisions.md")


def test_vault_audit_orphan_check_exempts_archive_files(tmp_path: Path) -> None:
    (tmp_path / "perf" / "archive").mkdir(parents=True)
    body = "---\ndate: 2026-10-24\ndescription: x\ntags:\n  - brag-doc-archive\n---\n" + "text " * 120
    (tmp_path / ARCHIVE_PATHS[1]).write_text(body + "\n[[Somewhere]]\n")
    (tmp_path / "perf" / "Somewhere.md").write_text("---\ndate: 2026-01-01\ndescription: x\ntags:\n  - t\n---\n" + "x" * 400)
    report = vault_audit.audit(tmp_path)
    assert ARCHIVE_PATHS[1] not in [i.file for i in report["orphans"]]


def test_gardener_lane_b_exclusion_covers_archive_paths() -> None:
    for rel in ARCHIVE_PATHS:
        assert graph_gardener.is_lane_b_excluded(rel)
    assert graph_gardener.is_lane_b_excluded("brain/Key Decisions.md")
    assert not graph_gardener.is_lane_b_excluded("brain/Patterns2.md")
    assert not graph_gardener.is_lane_b_excluded("perf/archive/other.md")
