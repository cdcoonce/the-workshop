# Codex Adapter

Use the Codex desktop task tools when available. CLI commands do not imply parity.

| Operation | Supported procedure |
| --- | --- |
| Create | Resolve the existing Vault saved project and create the user-visible worker task there. Fail closed if the Vault project cannot be resolved or task creation is unavailable; never silently fall back to a projectless or target-repository task. Put the target repository and exact isolated workspace in the registry and complete contract. |
| Verify attachment | Only a returned `threadId` is addressable. A queued `clientThreadId` remains `provisioning` and must never be passed to task tools. Verify with a controller message. |
| Message | Send a follow-up to the exact `threadId`/`hostId`. |
| Wait/monitor | Prefer cursor-based task waiting; use deliberate reads for investigation. Preserve cursors and stay quiet on unchanged timeout snapshots. |
| Interrupt | General task interruption is unsupported. A handoff may interrupt as a side effect but is not a stop API. |
| Complete | Verify the final report and repository evidence independently. |
| Merge/handoff | Workers never merge or promote. A Codex worker may push/open a PR only when contracted, then returns a merge-ready handoff with PR URL, exact head, integration target, checks, and blockers. The originating controller independently revalidates and merges. |
| Archive/reopen | After every shared terminal gate passes, archive the exact task and confirm it appears archived; then remove it from active monitor targets/registry. Never delete. Set archived false to reopen the same identity. |
| Worktree/integration | Creation may provision a Codex worktree; handoff may move another task's git state. Neither proves the commit reached the repository's integration target. |

Queued recovery has no documented `clientThreadId` status API. Reconcile listings
and filesystem/git evidence without retrying creation blindly. If a task exists but
cannot be addressed, preserve its worktree and use the shared handoff path.
If the archive call or confirmation fails, keep the completed worker active; a final
response never substitutes for confirmed archival.
Record the registry action as `codex-archived`; another adapter's action is invalid.
