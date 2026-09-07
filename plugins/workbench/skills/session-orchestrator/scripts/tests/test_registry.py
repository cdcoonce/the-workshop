"""Behavior tests for the deterministic controller-side registry."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from registry import RegistryError, SessionRegistry  # noqa: E402


def test_queued_client_record_is_not_attached(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path / "registry.json")
    registry.add("ledger", project="household-ledger", adapter="codex", client_id="queued-1")

    assert registry.get("ledger")["state"] == "provisioning"
    with pytest.raises(RegistryError, match="addressable"):
        registry.mark_attached("ledger")


def test_real_session_id_can_be_attached_and_messaged(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path / "registry.json")
    registry.add("ledger", project="household-ledger", adapter="codex")
    registry.set_session_id("ledger", "thread-123")
    registry.mark_attached("ledger", message_verified=True)

    worker = registry.get("ledger")
    assert worker["state"] == "running"
    assert worker["message_verified"] is True


def test_unchanged_poll_does_not_replace_meaningful_update(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path / "registry.json")
    registry.add("ledger", project="household-ledger", adapter="codex")
    registry.record_update("ledger", "migration committed", meaningful=True)
    meaningful_at = registry.get("ledger")["last_meaningful_update"]
    registry.record_update("ledger", "still running", meaningful=False)

    worker = registry.get("ledger")
    assert worker["last_meaningful_update"] == meaningful_at
    assert worker["last_observation"] == "still running"


def test_retirement_requires_integration_or_explicit_handoff(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path / "registry.json")
    registry.add("ledger", project="household-ledger", adapter="codex")
    registry.set_state("ledger", "lost", evidence="worker unaddressable; work preserved")
    with pytest.raises(RegistryError, match="integration"):
        registry.retire("ledger")

    registry.set_integration("ledger", "handed-off", evidence="commit abc123")
    registry.retire("ledger")
    assert registry.get("ledger")["state"] == "retired"


def test_duplicate_human_name_is_rejected(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path / "registry.json")
    registry.add("ledger", project="one", adapter="codex")
    with pytest.raises(RegistryError, match="already exists"):
        registry.add("ledger", project="two", adapter="claude-code")


def test_lifecycle_state_dependencies_and_recovery_are_durable(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path / "registry.json")
    registry.add(
        "ledger",
        project="household-ledger",
        adapter="codex",
        dependencies=["seed-plan"],
    )
    registry.set_state("ledger", "waiting", evidence="awaiting owner deployment decision")
    registry.record_recovery("ledger", "listing stale; commit abc123 preserved")

    worker = registry.get("ledger")
    assert worker["dependencies"] == ["seed-plan"]
    assert worker["state"] == "waiting"
    assert worker["recovery_attempts"] == 1
    assert [event["kind"] for event in worker["events"]] == ["created", "state", "recovery"]


def test_contract_amendments_and_observations_are_append_only(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path / "registry.json")
    registry.add("ledger", project="household-ledger", adapter="codex")
    registry.record_update("ledger", "policy answer: branch from dev", meaningful=True)
    registry.amend_contract("ledger", "deployment remains prohibited")
    registry.record_update("ledger", "still waiting", meaningful=False)

    worker = registry.get("ledger")
    assert [event["kind"] for event in worker["events"]] == [
        "created",
        "milestone",
        "contract-amendment",
        "observation",
    ]


def test_retired_worker_can_reopen_same_identity(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path / "registry.json")
    registry.add("ledger", project="household-ledger", adapter="codex")
    registry.set_session_id("ledger", "thread-123")
    registry.mark_attached("ledger", message_verified=True)
    registry.set_state("ledger", "completed", evidence="gates green")
    registry.set_integration("ledger", "integrated", evidence="reachable from origin/dev")
    registry.retire("ledger")
    registry.reopen("ledger", evidence="durable factual correction requested")

    worker = registry.get("ledger")
    assert worker["state"] == "provisioning"
    assert worker["session_id"] == "thread-123"
    assert worker["message_verified"] is False
    assert worker["integration_status"] == "pending"
    assert worker["events"][-1]["kind"] == "reopened"

    registry.mark_attached("ledger", message_verified=True)
    assert registry.get("ledger")["state"] == "running"


def test_state_command_cannot_bypass_attachment_or_jump_backwards(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path / "registry.json")
    registry.add("ledger", project="household-ledger", adapter="codex")
    with pytest.raises(RegistryError, match="attachment"):
        registry.set_state("ledger", "running", evidence="looks alive")
    with pytest.raises(RegistryError, match="transition"):
        registry.set_state("ledger", "completed", evidence="not even attached")


def test_recovery_attempts_stop_at_three(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path / "registry.json")
    registry.add("ledger", project="household-ledger", adapter="codex")
    for number in range(3):
        registry.record_recovery("ledger", f"attempt {number + 1}")
    with pytest.raises(RegistryError, match="three"):
        registry.record_recovery("ledger", "attempt 4")


def test_attach_cannot_reanimate_retired_worker_without_reopen(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path / "registry.json")
    registry.add("ledger", project="household-ledger", adapter="codex")
    registry.set_session_id("ledger", "thread-123")
    registry.mark_attached("ledger", message_verified=True)
    registry.set_state("ledger", "completed", evidence="gates green")
    registry.set_integration("ledger", "integrated", evidence="reachable from origin/dev")
    registry.retire("ledger")
    with pytest.raises(RegistryError, match="reopen"):
        registry.mark_attached("ledger", message_verified=True)


def test_never_attached_provisioning_record_cannot_integrate_or_retire(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path / "registry.json")
    registry.add("ledger", project="household-ledger", adapter="codex")
    with pytest.raises(RegistryError, match="lifecycle"):
        registry.set_integration("ledger", "integrated", evidence="claimed reachable")
    with pytest.raises(RegistryError, match="state"):
        registry.retire("ledger")
