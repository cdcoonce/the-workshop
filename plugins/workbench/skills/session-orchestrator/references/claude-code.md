# Claude Code Adapter

Use documented background-agent CLI operations only; probe `claude --help` and
subcommand help because availability can differ by installed version.

| Operation | Supported procedure |
| --- | --- |
| Create | Start a background agent with explicit name, cwd/workspace, permissions, and prompt. Parse the returned session ID. |
| Verify attachment | Confirm the ID through agent listing or logs. A launch without a recognized ID is not attached. |
| Message | Live controller-to-running-worker injection is unsupported by the documented CLI. Interactive attach is manual. Stop plus identity-confirmed resume may redirect only when authorized. |
| Wait/monitor | No documented cursor wait; poll JSON listing/logs with bounded backoff and report only meaningful changes. |
| Interrupt | Stop retains the conversation. Do not confuse stop with deletion. |
| Complete | Inspect logs/report and repository evidence independently. |
| Merge/handoff | Workers never merge or promote. A Claude worker may push/open a PR only when contracted, then returns a merge-ready handoff with PR URL, exact head, integration target, checks, and blockers. The originating controller independently revalidates and merges. |
| Archive/reopen | No archive vocabulary. After every shared terminal gate passes, confirm stop-and-retain, then remove the ID from active polls/registry; attach/resume the same retained ID. |
| Cleanup | Removal deletes the session and its worktree. Never remove before integration/handoff; never supply a discard-unpushed guard without explicit destructive authority. |
| Worktree/integration | Record the actual cwd/worktree and confirm with git; background launch alone does not prove isolation or integration. |

Do not use `--resume <id> --bg <prompt>` as live messaging: when the session is
already running it may create a copy, introducing duplicate-worker risk.
Never use `rm` for retirement: removal deletes the session and worktree. A failed
stop or retention check leaves the worker completed but active.
Record the registry action as `claude-stopped-retained`; `rm` is never a synonym.
