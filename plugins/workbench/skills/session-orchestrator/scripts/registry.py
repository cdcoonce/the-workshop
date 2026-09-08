#!/usr/bin/env python3
"""Maintain a session-orchestrator worker registry with safety invariants."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class RegistryError(ValueError):
    """Raised when a registry transition would violate the orchestration contract."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SessionRegistry:
    """Atomically persist controller-side worker identity and lifecycle state."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 3, "workers": {}, "archived_workers": {}}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        data.setdefault("archived_workers", {})
        for name, worker in list(data.get("workers", {}).items()):
            if worker.get("state") == "retired":
                data["archived_workers"][name] = data["workers"].pop(name)
        for worker in (*data.get("workers", {}).values(), *data["archived_workers"].values()):
            if "origin_project" not in worker:
                worker["origin_project"] = worker.pop("project", "")
            else:
                worker.pop("project", None)
            worker.setdefault("pending_follow_up", "")
            worker.setdefault("manual_identity_evidence", "")
            worker.setdefault("platform_retirement_action", "")
            worker.setdefault("platform_retirement_evidence", "")
            worker.setdefault("status_evidence", "")
            worker.setdefault("status_recorded", False)
            worker.setdefault("validation_evidence", "")
            worker.setdefault("validation_passed", False)
        data["version"] = 3
        return data

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temp.replace(self.path)

    @staticmethod
    def _event(worker: dict[str, Any], kind: str, detail: str) -> None:
        worker.setdefault("events", []).append(
            {"at": _now(), "detail": detail, "kind": kind}
        )

    def get(self, name: str) -> dict[str, Any]:
        """Return one worker, rejecting unknown human-readable names."""
        data = self._load()
        worker = data["workers"].get(name) or data["archived_workers"].get(name)
        if worker is None:
            raise RegistryError(f"worker {name!r} does not exist")
        return worker

    def add(
        self,
        name: str,
        *,
        origin_project: str = "",
        adapter: str,
        repository: str = "",
        workspace: str = "",
        client_id: str = "",
        dependencies: list[str] | None = None,
        project: str | None = None,
    ) -> None:
        """Add a uniquely named worker in provisioning state."""
        if project is not None:
            if origin_project and origin_project != project:
                raise RegistryError("origin project and legacy project must match")
            origin_project = project
        if not origin_project.strip():
            raise RegistryError("origin project cannot be empty")
        data = self._load()
        if name in data["workers"] or name in data["archived_workers"]:
            raise RegistryError(f"worker {name!r} already exists")
        timestamp = _now()
        data["workers"][name] = {
            "adapter": adapter,
            "client_id": client_id,
            "dependencies": dependencies or [],
            "events": [],
            "integration_evidence": "",
            "integration_status": "pending",
            "last_meaningful_update": timestamp,
            "last_observation": "created",
            "manual_identity_evidence": "",
            "message_verified": False,
            "pending_follow_up": "",
            "platform_retirement_action": "",
            "platform_retirement_evidence": "",
            "origin_project": origin_project,
            "recovery_attempts": 0,
            "repository": repository,
            "session_id": "",
            "state": "provisioning",
            "status_evidence": "",
            "status_recorded": False,
            "validation_evidence": "",
            "validation_passed": False,
            "workspace": workspace,
        }
        self._event(data["workers"][name], "created", "worker registered")
        self._save(data)

    def set_session_id(self, name: str, session_id: str) -> None:
        """Record the platform's real addressable session identity."""
        if not session_id.strip():
            raise RegistryError("session ID cannot be empty")
        data = self._load()
        if name not in data["workers"]:
            raise RegistryError(f"active worker {name!r} does not exist")
        data["workers"][name]["session_id"] = session_id
        self._event(data["workers"][name], "session", session_id)
        self._save(data)

    def mark_attached(self, name: str, *, message_verified: bool = False) -> None:
        """Mark a worker running only after identity and messaging are verified."""
        data = self._load()
        worker = data["workers"].get(name)
        if not worker or not worker["session_id"] or not message_verified:
            raise RegistryError("attachment requires an addressable session ID and verified message exchange")
        if worker["state"] == "retired":
            raise RegistryError("reopen a retired worker before attachment")
        if worker["state"] not in {"provisioning", "waiting", "blocked"}:
            raise RegistryError(f"attachment is invalid from state {worker['state']}")
        worker["state"] = "running"
        worker["message_verified"] = True
        worker["last_meaningful_update"] = _now()
        worker["last_observation"] = "attached"
        self._event(worker, "attached", "controller message exchange verified")
        self._save(data)

    def mark_manual_attached(
        self,
        name: str,
        *,
        identity_evidence: str,
        message_verified: bool = False,
    ) -> None:
        """Attach a manually controlled Cortex session without inventing a native ID."""
        data = self._load()
        worker = data["workers"].get(name)
        if (
            worker is None
            or worker["adapter"] != "cortex-code"
            or worker["state"] != "provisioning"
            or not identity_evidence.strip()
            or not message_verified
        ):
            raise RegistryError(
                "manual attachment requires a provisioning Cortex worker, exact identity evidence, and verified exchange"
            )
        worker["state"] = "running"
        worker["manual_identity_evidence"] = identity_evidence
        worker["message_verified"] = True
        worker["last_meaningful_update"] = _now()
        worker["last_observation"] = "manually attached"
        self._event(worker, "manual-attached", identity_evidence)
        self._save(data)

    def set_state(self, name: str, state: str, *, evidence: str) -> None:
        """Set an observable lifecycle state with durable evidence."""
        allowed = {"provisioning", "running", "waiting", "blocked", "completed", "lost"}
        if state not in allowed or not evidence.strip():
            raise RegistryError("state transition requires an active state and evidence")
        data = self._load()
        worker = data["workers"].get(name)
        if worker is None:
            raise RegistryError(f"worker {name!r} does not exist")
        if worker["state"] == "retired":
            raise RegistryError("reopen a retired worker before changing its state")
        transitions = {
            "provisioning": {"waiting", "blocked", "lost"},
            "running": {"waiting", "blocked", "completed", "lost"},
            "waiting": {"running", "blocked", "completed", "lost"},
            "blocked": {"running", "waiting", "completed", "lost"},
            "completed": {"blocked", "lost"},
            "lost": {"blocked"},
        }
        if state not in transitions.get(worker["state"], set()):
            if state == "running" and not worker["message_verified"]:
                raise RegistryError("running state requires verified attachment")
            raise RegistryError(f"invalid state transition: {worker['state']} -> {state}")
        if state == "running" and (not worker["session_id"] or not worker["message_verified"]):
            raise RegistryError("running state requires verified attachment")
        worker["state"] = state
        worker["last_meaningful_update"] = _now()
        worker["last_observation"] = evidence
        self._event(worker, "state", f"{state}: {evidence}")
        self._save(data)

    def record_update(self, name: str, observation: str, *, meaningful: bool = False) -> None:
        """Record every observation without treating unchanged polls as milestones."""
        data = self._load()
        worker = data["workers"].get(name)
        if worker is None:
            raise RegistryError(f"worker {name!r} does not exist")
        worker["last_observation"] = observation
        if meaningful:
            worker["last_meaningful_update"] = _now()
        self._event(worker, "milestone" if meaningful else "observation", observation)
        self._save(data)

    def record_recovery(self, name: str, evidence: str) -> None:
        """Append one identity-reconciliation attempt and its evidence."""
        data = self._load()
        worker = data["workers"].get(name)
        if worker is None:
            raise RegistryError(f"worker {name!r} does not exist")
        if worker.get("recovery_attempts", 0) >= 3:
            raise RegistryError("three recovery attempts exhausted; transition to blocked or lost")
        worker["recovery_attempts"] = worker.get("recovery_attempts", 0) + 1
        worker["last_observation"] = evidence
        self._event(worker, "recovery", evidence)
        self._save(data)

    def amend_contract(self, name: str, amendment: str) -> None:
        """Append an explicit scope or authorization amendment."""
        if not amendment.strip():
            raise RegistryError("contract amendment cannot be empty")
        data = self._load()
        worker = data["workers"].get(name)
        if worker is None:
            raise RegistryError(f"worker {name!r} does not exist")
        worker["last_meaningful_update"] = _now()
        self._event(worker, "contract-amendment", amendment)
        self._save(data)

    def set_integration(self, name: str, status: str, *, evidence: str) -> None:
        """Record verified integration or an explicit durable handoff."""
        if status not in {"integrated", "handed-off"} or not evidence.strip():
            raise RegistryError("integration requires integrated/handed-off status and evidence")
        data = self._load()
        worker = data["workers"].get(name)
        if worker is None:
            raise RegistryError(f"worker {name!r} does not exist")
        valid_states = (
            {"running", "completed"}
            if status == "integrated"
            else {"running", "blocked", "completed", "lost"}
        )
        if worker["state"] not in valid_states:
            raise RegistryError(
                f"integration status {status!r} is invalid for lifecycle state {worker['state']!r}"
            )
        worker["integration_status"] = status
        worker["integration_evidence"] = evidence
        worker["last_meaningful_update"] = _now()
        self._event(worker, "integration", f"{status}: {evidence}")
        self._save(data)

    def set_validation(self, name: str, *, passed: bool, evidence: str) -> None:
        """Record the required validation result and exact evidence."""
        if not evidence.strip():
            raise RegistryError("validation evidence cannot be empty")
        data = self._load()
        worker = data["workers"].get(name)
        if worker is None:
            raise RegistryError(f"active worker {name!r} does not exist")
        worker["validation_passed"] = passed
        worker["validation_evidence"] = evidence
        self._event(worker, "validation", f"{'passed' if passed else 'failed'}: {evidence}")
        self._save(data)

    def record_durable_status(self, name: str, evidence: str) -> None:
        """Record where the worker's durable completion status was written."""
        if not evidence.strip():
            raise RegistryError("durable status evidence cannot be empty")
        data = self._load()
        worker = data["workers"].get(name)
        if worker is None:
            raise RegistryError(f"active worker {name!r} does not exist")
        worker["status_recorded"] = True
        worker["status_evidence"] = evidence
        self._event(worker, "durable-status", evidence)
        self._save(data)

    def set_follow_up(self, name: str, assignment: str) -> None:
        """Record or clear the worker's remaining assigned follow-up."""
        data = self._load()
        worker = data["workers"].get(name)
        if worker is None:
            raise RegistryError(f"active worker {name!r} does not exist")
        worker["pending_follow_up"] = assignment
        self._event(worker, "follow-up", assignment or "none")
        self._save(data)

    def retire(
        self,
        name: str,
        *,
        platform_action: str,
        platform_evidence: str,
    ) -> None:
        """Archive a terminal worker and remove it from the active registry."""
        data = self._load()
        worker = data["workers"].get(name)
        if worker is None:
            raise RegistryError(f"active worker {name!r} does not exist")
        if worker["state"] != "completed":
            raise RegistryError("retirement requires completed state; blocked or waiting workers stay active")
        if worker["integration_status"] != "integrated" or not worker["integration_evidence"]:
            raise RegistryError("retirement requires durable integration evidence")
        if not worker["validation_passed"] or not worker["validation_evidence"]:
            raise RegistryError("retirement requires passing validation evidence")
        if not worker["status_recorded"] or not worker["status_evidence"]:
            raise RegistryError("retirement requires durable status evidence")
        if worker["pending_follow_up"]:
            raise RegistryError("retirement requires no assigned follow-up")
        has_identity = bool(worker["session_id"])
        if worker["adapter"] == "cortex-code":
            has_identity = bool(worker["manual_identity_evidence"])
        if not has_identity or not worker["message_verified"]:
            raise RegistryError("retirement requires a verified attached identity")
        expected_actions = {
            "codex": "codex-archived",
            "claude-code": "claude-stopped-retained",
            "cortex-code": "cortex-manual-retained",
        }
        expected_action = expected_actions.get(worker["adapter"])
        if platform_action != expected_action:
            raise RegistryError(
                f"retirement action {platform_action!r} does not match adapter {worker['adapter']!r}"
            )
        if not platform_evidence.strip():
            raise RegistryError("retirement requires platform archive or stop-retain evidence")
        worker["state"] = "retired"
        worker["platform_retirement_action"] = platform_action
        worker["platform_retirement_evidence"] = platform_evidence
        worker["last_meaningful_update"] = _now()
        self._event(worker, "retired", platform_evidence)
        data["archived_workers"][name] = data["workers"].pop(name)
        self._save(data)

    def record_archived_update(self, name: str, evidence: str) -> None:
        """Append durable history when a retained identity cannot be reopened."""
        if not evidence.strip():
            raise RegistryError("archived update evidence cannot be empty")
        data = self._load()
        worker = data["archived_workers"].get(name)
        if worker is None:
            raise RegistryError(f"archived worker {name!r} does not exist")
        self._event(worker, "archived-update", evidence)
        self._save(data)

    def reopen(self, name: str, *, evidence: str) -> None:
        """Reopen a retained worker without replacing its session identity."""
        data = self._load()
        worker = data["archived_workers"].get(name)
        if worker is None:
            raise RegistryError(f"worker {name!r} does not exist")
        if worker["state"] != "retired" or not worker["session_id"] or not evidence.strip():
            raise RegistryError("reopen requires a retired addressable worker and evidence")
        worker["state"] = "provisioning"
        worker["message_verified"] = False
        worker["integration_status"] = "pending"
        worker["integration_evidence"] = ""
        worker["pending_follow_up"] = ""
        worker["platform_retirement_evidence"] = ""
        worker["platform_retirement_action"] = ""
        worker["status_evidence"] = ""
        worker["status_recorded"] = False
        worker["validation_evidence"] = ""
        worker["validation_passed"] = False
        worker["last_meaningful_update"] = _now()
        worker["last_observation"] = evidence
        self._event(worker, "reopened", evidence)
        data["workers"][name] = data["archived_workers"].pop(name)
        self._save(data)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=Path.home() / ".workshop/session-orchestrator/registry.json")
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add")
    add.add_argument("name")
    add.add_argument("--origin-project", "--project", dest="origin_project", required=True)
    add.add_argument("--adapter", required=True, choices=("codex", "claude-code", "cortex-code"))
    add.add_argument("--repository", default="")
    add.add_argument("--workspace", default="")
    add.add_argument("--client-id", default="")
    add.add_argument("--depends-on", action="append", default=[])
    session = sub.add_parser("session")
    session.add_argument("name")
    session.add_argument("session_id")
    attach = sub.add_parser("attach")
    attach.add_argument("name")
    attach.add_argument("--message-verified", action="store_true")
    manual_attach = sub.add_parser("manual-attach")
    manual_attach.add_argument("name")
    manual_attach.add_argument("identity_evidence")
    manual_attach.add_argument("--message-verified", action="store_true")
    update = sub.add_parser("update")
    update.add_argument("name")
    update.add_argument("observation")
    update.add_argument("--meaningful", action="store_true")
    state = sub.add_parser("state")
    state.add_argument("name")
    state.add_argument("state", choices=("provisioning", "running", "waiting", "blocked", "completed", "lost"))
    state.add_argument("evidence")
    recovery = sub.add_parser("recovery")
    recovery.add_argument("name")
    recovery.add_argument("evidence")
    amend = sub.add_parser("amend")
    amend.add_argument("name")
    amend.add_argument("amendment")
    integrate = sub.add_parser("integrate")
    integrate.add_argument("name")
    integrate.add_argument("status", choices=("integrated", "handed-off"))
    integrate.add_argument("evidence")
    validate = sub.add_parser("validate")
    validate.add_argument("name")
    validation_result = validate.add_mutually_exclusive_group(required=True)
    validation_result.add_argument("--passed", action="store_true")
    validation_result.add_argument("--failed", action="store_true")
    validate.add_argument("evidence")
    status_record = sub.add_parser("status-record")
    status_record.add_argument("name")
    status_record.add_argument("evidence")
    follow_up = sub.add_parser("follow-up")
    follow_up.add_argument("name")
    follow_up.add_argument("assignment", nargs="?", default="")
    retire = sub.add_parser("retire")
    retire.add_argument("name")
    retire.add_argument(
        "platform_action",
        choices=("codex-archived", "claude-stopped-retained", "cortex-manual-retained"),
    )
    retire.add_argument("platform_evidence")
    reopen = sub.add_parser("reopen")
    reopen.add_argument("name")
    reopen.add_argument("evidence")
    archived_update = sub.add_parser("archived-update")
    archived_update.add_argument("name")
    archived_update.add_argument("evidence")
    show = sub.add_parser("show")
    show.add_argument("name", nargs="?")
    show.add_argument("--archived", action="store_true")
    return parser


def main() -> int:
    """Run the registry CLI."""
    args = _parser().parse_args()
    registry = SessionRegistry(args.registry)
    if args.command == "add":
        registry.add(args.name, origin_project=args.origin_project, adapter=args.adapter, repository=args.repository, workspace=args.workspace, client_id=args.client_id, dependencies=args.depends_on)
    elif args.command == "session":
        registry.set_session_id(args.name, args.session_id)
    elif args.command == "attach":
        registry.mark_attached(args.name, message_verified=args.message_verified)
    elif args.command == "manual-attach":
        registry.mark_manual_attached(
            args.name,
            identity_evidence=args.identity_evidence,
            message_verified=args.message_verified,
        )
    elif args.command == "update":
        registry.record_update(args.name, args.observation, meaningful=args.meaningful)
    elif args.command == "state":
        registry.set_state(args.name, args.state, evidence=args.evidence)
    elif args.command == "recovery":
        registry.record_recovery(args.name, args.evidence)
    elif args.command == "amend":
        registry.amend_contract(args.name, args.amendment)
    elif args.command == "integrate":
        registry.set_integration(args.name, args.status, evidence=args.evidence)
    elif args.command == "validate":
        registry.set_validation(args.name, passed=args.passed, evidence=args.evidence)
    elif args.command == "status-record":
        registry.record_durable_status(args.name, args.evidence)
    elif args.command == "follow-up":
        registry.set_follow_up(args.name, args.assignment)
    elif args.command == "retire":
        registry.retire(
            args.name,
            platform_action=args.platform_action,
            platform_evidence=args.platform_evidence,
        )
    elif args.command == "reopen":
        registry.reopen(args.name, evidence=args.evidence)
    elif args.command == "archived-update":
        registry.record_archived_update(args.name, args.evidence)
    else:
        data = registry._load()
        if args.name:
            output = registry.get(args.name)
        else:
            output = data["archived_workers"] if args.archived else data["workers"]
        print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
