# Cortex Code Adapter

The documented Cortex Code CLI can open windows, session UI, and a chat prompt, but
does not expose a controller-addressable chat identifier or lifecycle API.

| Operation | Status |
| --- | --- |
| Create | Manual/user-visible chat launch is available, but automated creation cannot satisfy attachment. |
| Verify attachment | Unsupported: no returned addressable session ID or message round trip. Window/process IDs are not chat identities. |
| Message | Unsupported for an existing chat. |
| Wait/monitor | Unsupported: no documented event, log, or structured status interface. |
| Interrupt | Unsupported. |
| Complete | Manual report plus independent filesystem/git verification only. |
| Archive/reopen | Unsupported. Use explicit manual handoff without fabricating identity. |
| Worktree/integration | No documented session-worktree lifecycle. Inspect git/filesystem directly and apply the shared integration gate. |

Fail attachment preflight and offer a manual handoff when Cortex is the required
platform. Do not emulate missing operations through GUI window IDs, process IDs,
edit-history traces, or another platform's API.
