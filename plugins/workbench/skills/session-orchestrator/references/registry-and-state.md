# Registry and State

Default machine-local state to `~/.workshop/session-orchestrator/registry.json`.
An explicit destination is authoritative. Do not put central run state in a target
repository; only that project's durable artifacts belong there.

Schema v3 separates active `workers` from retained `archived_workers`. It also names
the user-visible Vault origin explicitly instead of overloading `project` for the
target repository. A v1/v2 `project` field is migrated to `origin_project` on load.
Monitor only
the active map. A v1 retired record is normalized into the archive on load and the
v3 shape is persisted on the next mutation. Each unique task name records:

| Field | Meaning |
| --- | --- |
| `origin_project`, `repository`, `workspace` | User-visible Vault task identity, target repository, and exact isolated execution location |
| `adapter` | `codex`, `claude-code`, or `cortex-code` |
| `session_id`, `client_id` | Addressable identity versus provisional receipt |
| `state` | `provisioning`, `running`, `waiting`, `blocked`, `completed`, `retired`, `lost` |
| `dependencies` | Named workers/milestones that gate execution |
| `last_meaningful_update` | Timestamp changed only by a milestone, question, blocker, or completion |
| `last_observation` | Latest poll result, even when unchanged |
| `integration_status`, `integration_evidence` | `pending`, `integrated`, or `handed-off`, plus reachability/handoff proof |
| `message_verified` | Whether controller-to-worker exchange succeeded |
| `manual_identity_evidence` | Exact manually controlled Cortex session evidence when no native ID exists |
| `recovery_attempts`, `events` | Bounded reconciliation count and append-only evidence/history |
| `validation_passed`, `validation_evidence` | Required gate result and exact command/result evidence |
| `status_recorded`, `status_evidence` | Where durable project/controller status was written |
| `pending_follow_up` | Remaining assignment; non-empty means retirement is forbidden |
| `platform_retirement_action`, `platform_retirement_evidence` | Adapter-matched action plus confirmed Codex archive, Claude stop-retain, or explicit Cortex manual retention |

Use `scripts/registry.py` for deterministic changes. It writes atomically, rejects
duplicate names, refuses attachment without both a session ID and verified exchange,
and atomically archives only a fully terminal worker.

```bash
python scripts/registry.py add ledger --origin-project the-vault --repository /repo --workspace /repo/.worktrees/ledger --adapter codex
python scripts/registry.py session ledger thread-123
python scripts/registry.py attach ledger --message-verified
# Cortex manual-only: manual-attach cortex "exact Sessions UI evidence" --message-verified
python scripts/registry.py state ledger waiting "owner deployment decision required"
python scripts/registry.py recovery ledger "listing stale; commit abc123 preserved"
python scripts/registry.py amend ledger "deployment explicitly authorized for staging"
python scripts/registry.py update ledger "migration committed" --meaningful
python scripts/registry.py integrate ledger integrated "reachable from origin/dev"
python scripts/registry.py validate ledger --passed "make test passed"
python scripts/registry.py status-record ledger "project record commit abc123"
python scripts/registry.py follow-up ledger
python scripts/registry.py retire ledger codex-archived "Codex archived thread-123"
python scripts/registry.py reopen ledger "durable factual correction requested"
python scripts/registry.py archived-update ledger "correction recorded at commit def456"
python scripts/registry.py show ledger
python scripts/registry.py show --archived
```

Never overwrite an existing task name to represent a replacement; add a suffixed
candidate only after reconciliation proves replacement is safe and record the link
as an event. Keep policy answers, recovery evidence, and contract amendments in the
append-only event history rather than relying only on the latest observation.
Reopening moves the same identity back to active provisioning and clears every
terminal attestation; the worker must earn all gates again before re-archival.
When an adapter cannot reopen retained history, `archived-update` appends evidence
without returning the worker to active monitoring.
