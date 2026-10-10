"""Behavior tests for the deterministic controller-side registry."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from registry import RegistryError, SessionRegistry, main  # noqa: E402


def _completed_worker(registry: SessionRegistry) -> None:
    registry.add("ledger", project="household-ledger", adapter="codex")
    registry.set_session_id("ledger", "thread-123")
    registry.mark_attached("ledger", message_verified=True)
    registry.set_state("ledger", "completed", evidence="worker final received")
    registry.set_integration("ledger", "integrated", evidence="reachable from origin/dev")
    registry.set_validation("ledger", passed=True, evidence="make test passed")
    registry.record_durable_status("ledger", "project note updated at commit abc123")


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


def test_successful_retirement_moves_worker_out_of_active_registry(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path / "registry.json")
    _completed_worker(registry)
    registry.set_follow_up("ledger", "")
    registry.retire(
        "ledger",
        platform_action="codex-archived",
        platform_evidence="Codex archived thread-123",
    )

    data = registry._load()
    assert "ledger" not in data["workers"]
    assert data["archived_workers"]["ledger"]["state"] == "retired"


@pytest.mark.parametrize(
    "gate",
    ("integration", "validation", "status", "follow-up", "platform-archive"),
)
def test_unresolved_terminal_gate_keeps_worker_active(tmp_path: Path, gate: str) -> None:
    registry = SessionRegistry(tmp_path / "registry.json")
    _completed_worker(registry)
    worker = registry._load()["workers"]["ledger"]
    if gate == "integration":
        worker["integration_status"] = "pending"
        worker["integration_evidence"] = ""
    elif gate == "validation":
        worker["validation_passed"] = False
    elif gate == "status":
        worker["status_recorded"] = False
    elif gate == "follow-up":
        worker["pending_follow_up"] = "await owner merge decision"
    registry._save({"version": 2, "workers": {"ledger": worker}, "archived_workers": {}})

    with pytest.raises(RegistryError):
        registry.retire(
            "ledger",
            platform_action="codex-archived",
            platform_evidence="" if gate == "platform-archive" else "Codex archived thread-123",
        )
    assert "ledger" in registry._load()["workers"]


def test_merge_ready_handoff_is_not_integration_or_retirement(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path / "registry.json")
    _completed_worker(registry)
    registry.set_integration(
        "ledger",
        "handed-off",
        evidence="PR #48 exact head abc123 has green checks and owner approval",
    )

    with pytest.raises(RegistryError, match="durable integration"):
        registry.retire(
            "ledger",
            platform_action="codex-archived",
            platform_evidence="Codex archived thread-123",
        )

    worker = registry._load()["workers"]["ledger"]
    assert worker["state"] == "completed"
    assert worker["integration_status"] == "handed-off"


def test_v1_retired_record_migrates_out_of_active_registry(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    path.write_text(
        '{"version": 1, "workers": {"ledger": {"state": "retired", "session_id": "thread-123"}}}\n'
    )

    data = SessionRegistry(path)._load()

    assert data["version"] == 3
    assert data["workers"] == {}
    assert data["archived_workers"]["ledger"]["session_id"] == "thread-123"


def test_duplicate_human_name_is_rejected(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path / "registry.json")
    registry.add("ledger", project="one", adapter="codex")
    with pytest.raises(RegistryError, match="already exists"):
        registry.add("ledger", project="two", adapter="claude-code")


def test_legacy_project_field_migrates_to_explicit_origin_project(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    path.write_text(
        '{"version": 2, "workers": {"ledger": '
        '{"project": "the-vault", "state": "provisioning"}}}\n'
    )

    worker = SessionRegistry(path).get("ledger")

    assert worker["origin_project"] == "the-vault"
    assert "project" not in worker


def test_origin_project_is_required(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path / "registry.json")

    with pytest.raises(RegistryError, match="origin project"):
        registry.add("ledger", adapter="codex")


def test_registry_separates_vault_origin_from_target_repository_and_workspace(
    tmp_path: Path,
) -> None:
    registry = SessionRegistry(tmp_path / "registry.json")
    registry.add(
        "ledger",
        origin_project="the-vault",
        repository="/Users/Charles.Coonce/Dev/the-workshop",
        workspace="/Users/Charles.Coonce/Dev/the-workshop/.claude/worktrees/ledger",
        adapter="codex",
    )

    worker = registry.get("ledger")
    assert worker["origin_project"] == "the-vault"
    assert worker["repository"] == "/Users/Charles.Coonce/Dev/the-workshop"
    assert worker["workspace"].endswith("/.claude/worktrees/ledger")


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
    _completed_worker(registry)
    registry.retire(
        "ledger",
        platform_action="codex-archived",
        platform_evidence="Codex archived thread-123",
    )
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
    _completed_worker(registry)
    registry.retire(
        "ledger",
        platform_action="codex-archived",
        platform_evidence="Codex archived thread-123",
    )
    with pytest.raises(RegistryError, match="attachment"):
        registry.mark_attached("ledger", message_verified=True)


def test_never_attached_provisioning_record_cannot_integrate_or_retire(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path / "registry.json")
    registry.add("ledger", project="household-ledger", adapter="codex")
    with pytest.raises(RegistryError, match="lifecycle"):
        registry.set_integration("ledger", "integrated", evidence="claimed reachable")
    with pytest.raises(RegistryError, match="completed"):
        registry.retire(
            "ledger",
            platform_action="codex-archived",
            platform_evidence="claimed archive",
        )


@pytest.mark.parametrize("state", ("waiting", "blocked", "lost"))
def test_unresolved_or_human_gated_worker_remains_active(tmp_path: Path, state: str) -> None:
    registry = SessionRegistry(tmp_path / "registry.json")
    registry.add("ledger", project="household-ledger", adapter="codex")
    registry.set_session_id("ledger", "thread-123")
    registry.mark_attached("ledger", message_verified=True)
    registry.set_state("ledger", state, evidence="owner decision remains")

    with pytest.raises(RegistryError, match="completed"):
        registry.retire(
            "ledger",
            platform_action="codex-archived",
            platform_evidence="claimed archive",
        )
    assert "ledger" in registry._load()["workers"]


def test_retirement_requires_verified_attached_identity(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path / "registry.json")
    registry.add("ledger", project="household-ledger", adapter="codex")
    registry.set_state("ledger", "waiting", evidence="manual progress observed")
    registry.set_state("ledger", "completed", evidence="claimed final")
    registry.set_integration("ledger", "integrated", evidence="reachable from origin/dev")
    registry.set_validation("ledger", passed=True, evidence="make test passed")
    registry.record_durable_status("ledger", "project status committed")

    with pytest.raises(RegistryError, match="attached"):
        registry.retire(
            "ledger",
            platform_action="codex-archived",
            platform_evidence="claimed archive",
        )


def test_retirement_action_must_match_adapter(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path / "registry.json")
    _completed_worker(registry)

    with pytest.raises(RegistryError, match="adapter"):
        registry.retire(
            "ledger",
            platform_action="cortex-manual-retained",
            platform_evidence="anything",
        )


def test_archived_identity_accepts_durable_update_without_reopen(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path / "registry.json")
    _completed_worker(registry)
    registry.retire(
        "ledger",
        platform_action="codex-archived",
        platform_evidence="Codex archived thread-123",
    )

    registry.record_archived_update("ledger", "corrected durable status at commit def456")

    worker = registry.get("ledger")
    assert worker["events"][-1]["kind"] == "archived-update"
    assert "def456" in worker["events"][-1]["detail"]


def test_cortex_manual_identity_can_retire_without_fabricated_native_id(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path / "registry.json")
    registry.add("cortex", project="household-ledger", adapter="cortex-code")
    registry.mark_manual_attached(
        "cortex",
        identity_evidence="owner confirmed exact retained session in Cortex Sessions UI",
        message_verified=True,
    )
    registry.set_state("cortex", "completed", evidence="worker final received")
    registry.set_integration("cortex", "integrated", evidence="reachable from origin/dev")
    registry.set_validation("cortex", passed=True, evidence="make test passed")
    registry.record_durable_status("cortex", "project status committed")

    registry.retire(
        "cortex",
        platform_action="cortex-manual-retained",
        platform_evidence="owner confirmed exact session retained",
    )

    worker = registry.get("cortex")
    assert worker["state"] == "retired"
    assert worker["session_id"] == ""
    assert worker["manual_identity_evidence"]


def _cli(registry_path: Path, *argv: str) -> int:
    return main(["--registry", str(registry_path), *argv])


def _on_disk(registry_path: Path) -> dict:
    return json.loads(registry_path.read_text(encoding="utf-8"))


def test_cli_add_session_attach_state_retire_lifecycle(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"

    assert _cli(path, "add", "ledger", "--origin-project", "household-ledger", "--adapter", "codex") == 0
    worker = _on_disk(path)["workers"]["ledger"]
    assert worker["origin_project"] == "household-ledger"
    assert worker["adapter"] == "codex"
    assert worker["state"] == "provisioning"

    assert _cli(path, "session", "ledger", "thread-123") == 0
    assert _on_disk(path)["workers"]["ledger"]["session_id"] == "thread-123"

    assert _cli(path, "attach", "ledger", "--message-verified") == 0
    worker = _on_disk(path)["workers"]["ledger"]
    assert worker["state"] == "running"
    assert worker["message_verified"] is True

    assert _cli(path, "state", "ledger", "completed", "worker final received") == 0
    worker = _on_disk(path)["workers"]["ledger"]
    assert worker["state"] == "completed"
    assert worker["last_observation"] == "worker final received"

    assert _cli(path, "integrate", "ledger", "integrated", "reachable from origin/dev") == 0
    assert _cli(path, "validate", "ledger", "--passed", "make test passed") == 0
    assert _cli(path, "status-record", "ledger", "note committed") == 0
    assert _cli(path, "retire", "ledger", "codex-archived", "thread archived in app") == 0

    data = _on_disk(path)
    assert "ledger" not in data["workers"]
    archived = data["archived_workers"]["ledger"]
    assert archived["state"] == "retired"
    assert archived["session_id"] == "thread-123"
    assert archived["platform_retirement_action"] == "codex-archived"
    assert archived["platform_retirement_evidence"] == "thread archived in app"
    assert archived["integration_evidence"] == "reachable from origin/dev"
    assert archived["validation_evidence"] == "make test passed"
    assert archived["status_evidence"] == "note committed"


def test_cli_state_positional_order_is_name_state_evidence(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    _cli(path, "add", "ledger", "--origin-project", "p", "--adapter", "codex")
    _cli(path, "session", "ledger", "thread-1")
    _cli(path, "attach", "ledger", "--message-verified")

    _cli(path, "state", "ledger", "waiting", "needs owner input")

    worker = _on_disk(path)["workers"]["ledger"]
    assert worker["state"] == "waiting"
    assert worker["last_observation"] == "needs owner input"


def test_cli_rejects_state_with_swapped_positionals(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    _cli(path, "add", "ledger", "--origin-project", "p", "--adapter", "codex")

    with pytest.raises(SystemExit):
        _cli(path, "state", "ledger", "needs owner input", "waiting")


def test_cli_session_positional_order_is_name_then_id(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    _cli(path, "add", "ledger", "--origin-project", "p", "--adapter", "codex")

    _cli(path, "session", "ledger", "thread-9")

    assert _on_disk(path)["workers"]["ledger"]["session_id"] == "thread-9"


def test_cli_attach_without_flag_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    _cli(path, "add", "ledger", "--origin-project", "p", "--adapter", "codex")
    _cli(path, "session", "ledger", "thread-1")

    with pytest.raises(RegistryError, match="verified message exchange"):
        _cli(path, "attach", "ledger")


def test_cli_add_rejects_unknown_adapter(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        _cli(tmp_path / "registry.json", "add", "x", "--origin-project", "p", "--adapter", "bogus")


def test_all_workers_returns_active_and_archived_maps(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path / "registry.json")
    _completed_worker(registry)
    registry.set_follow_up("ledger", "")
    registry.retire("ledger", platform_action="codex-archived", platform_evidence="archived")
    registry.add("live", project="household-ledger", adapter="codex")

    everything = registry.all_workers()

    assert set(everything) == {"workers", "archived_workers"}
    assert set(everything["workers"]) == {"live"}
    assert set(everything["archived_workers"]) == {"ledger"}
    assert everything["archived_workers"]["ledger"]["state"] == "retired"


def test_all_workers_on_missing_file_is_empty(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path / "absent.json")

    assert registry.all_workers() == {"workers": {}, "archived_workers": {}}


def test_show_branch_goes_through_public_accessor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "registry.json"
    SessionRegistry(path).add("live", project="p", adapter="codex")

    real_load = SessionRegistry._load

    def _guarded_load(self: SessionRegistry) -> dict:
        if sys._getframe(1).f_code.co_name == "main":
            raise AssertionError("show must not call the private _load from main()")
        return real_load(self)

    calls: list[str] = []
    real = SessionRegistry.all_workers

    def _spy(self: SessionRegistry) -> dict:
        calls.append("all_workers")
        return real(self)

    monkeypatch.setattr(SessionRegistry, "all_workers", _spy)
    monkeypatch.setattr(SessionRegistry, "_load", _guarded_load)

    assert _cli(path, "show") == 0
    assert calls == ["all_workers"]
    assert "live" in json.loads(capsys.readouterr().out)


def test_show_prints_active_then_archived_unchanged(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "registry.json"
    registry = SessionRegistry(path)
    _completed_worker(registry)
    registry.set_follow_up("ledger", "")
    registry.retire("ledger", platform_action="codex-archived", platform_evidence="archived")
    registry.add("live", project="p", adapter="codex")

    _cli(path, "show")
    assert set(json.loads(capsys.readouterr().out)) == {"live"}
    _cli(path, "show", "--archived")
    assert set(json.loads(capsys.readouterr().out)) == {"ledger"}
    _cli(path, "show", "ledger")
    assert json.loads(capsys.readouterr().out)["state"] == "retired"
