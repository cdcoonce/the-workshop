"""A ledger rollover commit under the entry replay (#1303, B5).

Choice made for #1303: the replay does NOT learn to recognise a pure move. A
quarterly rollover deletes many entries from a ledger and adds archive files,
and the replay refuses any entry deletion, so a rollover that has to be
replayed fails closed instead of dropping or duplicating entries. The vault-sync
docs therefore say a rollover must be synced alone, on a tree that already
matches origin. These tests pin both halves: the refusal, and that the docs say
what to do about it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))

from entry_replay import RefusalError, is_allowlisted, ledger_merge  # noqa: E402

HEAD = "---\ndate: 2026-01-01\ndescription: d\ntags:\n  - t\n---\n# Key Decisions\n\n## Recent\n\nRule.\n\n"
OLD = "### 2026-06-30 (c) - old\n\nOld body.\n\n"
NEW = "### 2026-10-20 (c) - new\n\nNew body.\n\n"
ORIGIN_NEW = "### 2026-10-23 (c) - from the other machine\n\nBody.\n\n"
KD = "brain/Key Decisions.md"


def test_archive_files_are_not_replayable_hub_files() -> None:
    assert not is_allowlisted("brain/archive/key-decisions/2026-Q2.md")
    assert not is_allowlisted("perf/archive/brag-2026-Q2.md")
    assert is_allowlisted(KD)


def test_replay_refuses_a_rollover_commit_instead_of_losing_the_moved_entries() -> None:
    base = HEAD + NEW + OLD
    rolled_tip = HEAD + NEW  # the rollover removed OLD from the live file
    origin = HEAD + ORIGIN_NEW + NEW + OLD  # origin moved on meanwhile
    with pytest.raises(RefusalError, match="(?i)delet"):
        ledger_merge(base, rolled_tip, origin, KD)


def test_vault_sync_docs_say_a_rollover_is_synced_alone() -> None:
    text = (SCRIPTS_DIR.parent / "references" / "command.md").read_text(encoding="utf-8").lower()
    assert "rollover" in text
    assert "alone" in text
    assert "ledger_rollover.py" in text
    assert "refuses" in text and "deletion" in text
