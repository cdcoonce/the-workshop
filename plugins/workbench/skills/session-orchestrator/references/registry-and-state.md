# Registry and State

Default machine-local state to `~/.workshop/session-orchestrator/registry.json`.
An explicit destination is authoritative. Do not put central run state in a target
repository; only that project's durable artifacts belong there.

Each unique human-readable task name records:

| Field | Meaning |
| --- | --- |
| `project`, `repository`, `workspace` | Ownership and exact execution location |
| `adapter` | `codex`, `claude-code`, or `cortex-code` |
| `session_id`, `client_id` | Addressable identity versus provisional receipt |
| `state` | `provisioning`, `running`, `waiting`, `blocked`, `completed`, `retired`, `lost` |
| `dependencies` | Named workers/milestones that gate execution |
| `last_meaningful_update` | Timestamp changed only by a milestone, question, blocker, or completion |
| `last_observation` | Latest poll result, even when unchanged |
| `integration_status`, `integration_evidence` | `pending`, `integrated`, or `handed-off`, plus reachability/handoff proof |
| `message_verified` | Whether controller-to-worker exchange succeeded |
| `recovery_attempts`, `events` | Bounded reconciliation count and append-only evidence/history |

Use `scripts/registry.py` for deterministic changes. It writes atomically, rejects
duplicate names, refuses attachment without both a session ID and verified exchange,
and refuses retirement without integration or explicit handoff evidence.

```bash
python scripts/registry.py add ledger --project household-ledger --adapter codex
python scripts/registry.py session ledger thread-123
python scripts/registry.py attach ledger --message-verified
python scripts/registry.py state ledger waiting "owner deployment decision required"
python scripts/registry.py recovery ledger "listing stale; commit abc123 preserved"
python scripts/registry.py amend ledger "deployment explicitly authorized for staging"
python scripts/registry.py update ledger "migration committed" --meaningful
python scripts/registry.py integrate ledger handed-off "commit abc123 owned by controller"
python scripts/registry.py retire ledger
python scripts/registry.py reopen ledger "durable factual correction requested"
python scripts/registry.py show ledger
```

Never overwrite an existing task name to represent a replacement; add a suffixed
candidate only after reconciliation proves replacement is safe and record the link
as an event. Keep policy answers, recovery evidence, and contract amendments in the
append-only event history rather than relying only on the latest observation.
