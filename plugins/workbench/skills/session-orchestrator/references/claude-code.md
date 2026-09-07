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
| Archive/reopen | No archive vocabulary. Model archive as stopped-and-retained; attach/resume the same ID. Include completed workers in listings when supported. |
| Cleanup | Removal deletes the session and its worktree. Never remove before integration/handoff; never supply a discard-unpushed guard without explicit destructive authority. |
| Worktree/integration | Record the actual cwd/worktree and confirm with git; background launch alone does not prove isolation or integration. |

Do not use `--resume <id> --bg <prompt>` as live messaging: when the session is
already running it may create a copy, introducing duplicate-worker risk.
