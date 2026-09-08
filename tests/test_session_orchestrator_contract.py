"""Distribution and safety contract for the session-orchestrator skill."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "plugins" / "workbench" / "skills" / "session-orchestrator"


def test_shared_core_and_three_named_adapters_ship_together() -> None:
    assert (SKILL / "SKILL.md").is_file()
    for name in ("codex.md", "claude-code.md", "cortex-code.md"):
        assert (SKILL / "references" / name).is_file()


def test_worker_contract_carries_every_authorization_boundary() -> None:
    text = (SKILL / "references" / "worker-contract.md").read_text()
    for field in (
        "Objective",
        "Ownership",
        "Allowed mutations",
        "Prohibitions",
        "Verification gates",
        "Reporting protocol",
        "Integration obligations",
        "Terminal conditions",
    ):
        assert field in text
    for authority in ("merge", "deployment", "live data", "destructive", "external disclosure"):
        assert authority in text.lower()


def test_attachment_and_retirement_invariants_are_invocation_loaded() -> None:
    text = (SKILL / "SKILL.md").read_text()
    assert "NO WORKER EXISTS WITHOUT AN ADDRESSABLE SESSION IDENTIFIER" in text
    assert "NO WORKER RETIRES BEFORE EVERY TERMINAL GATE PASSES" in text
    for requirement in (
        "durably integrated",
        "validation",
        "durable status",
        "no follow-up",
        "archive, never delete",
        "active monitoring",
    ):
        assert requirement in text.lower()


def test_adapters_define_terminal_archive_semantics_without_deletion() -> None:
    codex = (SKILL / "references" / "codex.md").read_text().lower()
    claude = (SKILL / "references" / "claude-code.md").read_text().lower()
    cortex = (SKILL / "references" / "cortex-code.md").read_text().lower()
    assert "confirm" in codex and "archive" in codex and "never delete" in codex
    assert "stop-and-retain" in claude and "never" in claude and "remove" in claude
    assert "unsupported" in cortex and "manual" in cortex and "archive" in cortex


def test_merge_authority_stays_with_originating_controller() -> None:
    core = (SKILL / "SKILL.md").read_text().lower()
    contract = (SKILL / "references" / "worker-contract.md").read_text().lower()
    lifecycle = (SKILL / "references" / "lifecycle-and-recovery.md").read_text().lower()
    for text in (core, contract, lifecycle):
        assert "workers never merge" in text
        assert "originating controller" in text
        assert "independently revalidate" in text
    assert "merge-ready handoff" in contract
    assert "owner authorization" in lifecycle


def test_no_adapter_infers_worker_side_merge_authority() -> None:
    for name in ("codex.md", "claude-code.md", "cortex-code.md"):
        text = (SKILL / "references" / name).read_text().lower()
        assert "workers never merge" in text, name
        assert "originating controller" in text, name
        assert "merge-ready handoff" in text, name


def test_recovery_contract_prefers_progress_evidence_over_stale_listing() -> None:
    text = (SKILL / "references" / "lifecycle-and-recovery.md").read_text().lower()
    assert "stale listing" in text
    assert "filesystem evidence" in text
    assert "do not replace" in text


def test_skill_entrypoint_stays_progressively_disclosed() -> None:
    assert len((SKILL / "SKILL.md").read_text().splitlines()) < 100
