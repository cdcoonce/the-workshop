"""Tests that the eval-suite conductor skill documents its full contract.

``.claude/skills/eval-suite/SKILL.md`` is a repo-local Claude Code skill: it
is loaded and followed by hand, never executed by any script, CI job, or afk
child. These tests only check that its documented content covers what #995's
acceptance criteria require it to cover — they never invoke the skill.
"""

from __future__ import annotations

from pathlib import Path

_SKILL_PATH = (
    Path(__file__).resolve().parents[3] / ".claude" / "skills" / "eval-suite" / "SKILL.md"
)

_REQUIRED_ENTRY_POINTS = {
    "dispatch.snapshot_end_state",
    "dispatch.score_attempt",
    "scorer.classify_attempt",
    "scorer.should_retry",
    "scorer.compute_verdict",
    "calibration.fixture_fingerprint",
    "ledger.write_run",
    "report.write_report",
}


def _skill_text() -> str:
    return _SKILL_PATH.read_text(encoding="utf-8")


def _backticked_table_cells(text: str) -> set[str]:
    """Every backticked first-column cell of a markdown table row in *text*."""
    cells: set[str] = set()
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        row_cells = [cell.strip() for cell in line.strip("|").split("|")]
        if not row_cells:
            continue
        first = row_cells[0]
        if first.startswith("`") and first.endswith("`") and len(first) > 2:
            cells.add(first.strip("`"))
    return cells


def test_skill_file_exists():
    assert _SKILL_PATH.is_file()


def test_skill_documents_fixture_preparation():
    text = _skill_text()
    assert "fixture" in text
    assert "build_fixture.py" in text or "builder" in text
    assert "fixture_fingerprint" in text


def test_skill_documents_gated_item_derivation():
    text = _skill_text()
    assert "checks.manifest" in text
    assert "gated" in text
    assert "trend" in text
    assert "gated_ids" in text


def test_skill_documents_dispatch_modes_and_lens_agent_responsibility():
    text = _skill_text()
    assert "subagent" in text
    assert "inline" in text
    assert "lens" in text.lower()


def test_skill_states_the_retry_rule_exactly():
    text = _skill_text()
    assert "should_retry" in text
    assert "counted_attempts reaches 3" in text
    assert "reserve of 2" in text
    assert "counted_attempts + reserve_used" in text
    assert "reaches 5" in text


def test_skill_documents_the_end_state_snapshot():
    text = _skill_text()
    assert "snapshot_end_state" in text
    assert "end_state" in text


def test_skill_documents_every_named_harness_entry_point():
    """Checks the entry-points table specifically, not prose elsewhere.

    A table-scoped check survives incidental prose redundancy: a mutant that
    drops one row from the table is still caught, even if that function is
    also mentioned in passing somewhere else in the document.
    """
    table_cells = _backticked_table_cells(_skill_text())
    missing = _REQUIRED_ENTRY_POINTS - table_cells
    assert missing == set()


def test_skill_states_it_executes_nothing_itself():
    text = _skill_text()
    assert "executes nothing" in text or "never invoked by an afk child" in text
    assert "#989" in text
