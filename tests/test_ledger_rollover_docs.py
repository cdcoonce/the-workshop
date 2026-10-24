"""Docs contract for the quarterly ledger rollover (#1303, B4, B5, B6)."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKBENCH = REPO_ROOT / "plugins" / "workbench"
STANDUP = WORKBENCH / "skills" / "vault-standup" / "references" / "command.md"
SYNC = WORKBENCH / "skills" / "vault-sync" / "references" / "command.md"
SPOTTER = WORKBENCH / "agents" / "brag-spotter" / "AGENT.md"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_brag_spotter_checks_archive_files_before_calling_a_win_uncaptured() -> None:
    text = _text(SPOTTER)
    assert "perf/archive/brag-" in text
    assert re.search(r"(?i)before (calling|reporting|declaring|suggesting)[^.\n]*uncaptured", text)


def test_brag_spotter_still_reads_the_live_brag_doc_first() -> None:
    text = _text(SPOTTER)
    assert text.index("perf/Brag Doc.md") < text.index("perf/archive/brag-")


def test_standup_runs_the_rollover_on_the_first_standup_of_a_new_quarter() -> None:
    text = _text(STANDUP)
    assert "ledger_rollover" in text
    assert re.search(r"(?i)first standup of (a|the) new quarter", text)
    assert "rollover_ledgers" in text


def test_standup_rollover_step_sits_beside_the_weekly_rollover_and_names_the_layout() -> None:
    text = _text(STANDUP)
    assert text.index("Weekly Work Task Rollover") < text.index("Quarterly Ledger Rollover")
    assert "brain/archive/key-decisions/YYYY-QN.md" in text
    assert "perf/archive/brag-YYYY-QN.md" in text
    assert "## Archive" in text


def test_standup_documents_the_dry_run_cli_and_the_apply_flag() -> None:
    text = _text(STANDUP)
    assert "ledger_rollover.py rollover" in text
    assert "--apply" in text
    assert re.search(r"(?i)dry", text)


def test_vault_sync_docs_say_a_rollover_is_synced_alone() -> None:
    text = _text(SYNC).lower()
    assert "rollover" in text and "alone" in text
    assert "brain/archive/key-decisions" in text
