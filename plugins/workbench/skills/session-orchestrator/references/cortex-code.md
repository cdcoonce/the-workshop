# Cortex Code Adapter

The documented Cortex Code CLI can open windows, session UI, and a chat prompt, but
does not expose a controller-addressable chat identifier or lifecycle API.

| Operation | Status |
| --- | --- |
| Create | Manual/user-visible chat launch is available, but automated creation cannot satisfy attachment. |
| Verify attachment | Automated attachment is unsupported. A manually controlled session may attach only after the owner/controller identifies the exact retained Sessions UI record and verifies a manual message exchange. Window/process IDs are not chat identities. |
| Message | Unsupported for an existing chat. |
| Wait/monitor | Unsupported: no documented event, log, or structured status interface. |
| Interrupt | Unsupported. |
| Complete | Manual report plus independent filesystem/git verification only. |
| Merge/handoff | Workers never merge or promote. A manually controlled Cortex worker may push/open a PR only when contracted, then returns a merge-ready handoff with PR URL, exact head, integration target, checks, and blockers. The originating controller independently revalidates and merges. |
| Archive/reopen | Automated archive is unsupported. Require explicit manual archive/retention confirmation before registry retirement; otherwise keep the worker active. |
| Worktree/integration | No documented session-worktree lifecycle. Inspect git/filesystem directly and apply the shared integration gate. |

Fail attachment preflight and offer a manual handoff when Cortex is the required
platform unless exact manual session identity and exchange evidence are available.
Record that evidence with `manual-attach`; do not invent a native ID or emulate
missing operations through GUI window IDs, process IDs,
edit-history traces, or another platform's API.
Manual confirmation is evidence, not an invented adapter operation. Never delete a
chat or local history to simulate archival.
Record only confirmed manual retention as `cortex-manual-retained`; do not label it
as native archival.
