# Claude Code Adapter

One platform, two hosts. Prefer the desktop app's session tools (`spawn_task`
chips, `ccd_session_mgmt` messaging and inspection, `Monitor`) whenever the
controller's environment exposes them: their receipts prove attachment. Use the
standalone background-agent CLI only when those tools are absent, and treat a
CLI worker as unproven until a real exchange round-trips — org policy can block
standalone-CLI subscription auth on a machine whose desktop sessions
authenticate fine, and that failure surfaces only at the worker's first API
call, after launch and listing both look healthy.

| Operation            | Supported procedure (desktop host)                                                                                                                                                                                                                                                                                                                                                                                             |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Create               | Require an existing user-visible Vault project task before dispatch; fail closed if it cannot be created or addressed, and do not substitute a projectless Claude session. Issue one `spawn_task` chip per complete worker contract. The chip is a provisional receipt: the owner's click launches the visible session in a fresh worktree, so the worker stays `provisioning` — an unclicked chip never satisfies attachment. |
| Verify attachment    | Resolve the launched session's real ID (`list_sessions` or the chip's spawned session), send the contract with `send_message`, and require the delivered receipt and message ID before recording `message_verified`.                                                                                                                                                                                                           |
| Message              | `send_message` to the same session ID; keep receipts as evidence.                                                                                                                                                                                                                                                                                                                                                              |
| Wait/monitor         | Contract workers to append to an append-only status file; tail it with `Monitor` and corroborate with `get_session`/`list_events`. Report only meaningful changes.                                                                                                                                                                                                                                                             |
| Interrupt            | No documented forced stop; redirect by message. Stop-and-retain is observed, not commanded: `get_session` showing not running and un-archived is the retention evidence.                                                                                                                                                                                                                                                       |
| Complete             | Inspect the report and repository evidence independently.                                                                                                                                                                                                                                                                                                                                                                      |
| Merge/handoff        | Workers never merge or promote. A Claude worker may push/open a PR only when contracted, then returns a merge-ready handoff with PR URL, exact head, integration target, checks, and blockers. The originating controller independently revalidates and merges.                                                                                                                                                                |
| Archive/reopen       | After every shared terminal gate passes, confirm stop-and-retain via `get_session` (not running, un-archived) or archive via `archive_session`; then remove the ID from active polls/registry. Reopen by messaging the same retained session ID.                                                                                                                                                                               |
| Cleanup              | Never delete a session or its worktree before integration/handoff proof; never supply a discard-unpushed guard without explicit destructive authority.                                                                                                                                                                                                                                                                         |
| Worktree/integration | Record the actual worktree path the launch created and confirm with git; a visible session alone does not prove isolation or integration.                                                                                                                                                                                                                                                                                      |

## Standalone CLI host (fallback)

Probe `claude --help` and subcommand help first; availability differs by
version. Create with explicit target repository, isolated cwd, permissions the
launch can actually grant, and the complete contract as the sole positional
argument; parse the returned session ID. Live controller-to-worker messaging is
unsupported and there is no cursor wait: poll JSON listing/logs with bounded
backoff. Stop retains the conversation; removal deletes the session and its
worktree. Field-verified traps (2026-09-09, managed macOS):

- `bypassPermissions` has no unattended path — its disclaimer must be accepted
  interactively once. Do not plan an unattended launch that depends on it.
- A variadic flag such as `--allowedTools <tools...>` placed before the
  positional prompt swallows the prompt silently: the session lists as
  idle/blocked with an empty input and no error. A listed ID whose contract
  never arrived is not attached.
- `--bg --resume <id>` with any flags starts a copy under a new ID (a
  background session keeps its own saved options) — duplicate-worker risk.
  Resume bare, with the message as the sole positional argument.
- Org policy may disable standalone-CLI subscription auth entirely ("use an
  API key instead"). If a worker's first call dies this way, abandon the CLI
  host: re-dispatch via the desktop host if available, otherwise escalate the
  capability gap. Do not retry launches.

On either host, record the registry action as `claude-stopped-retained`; `rm`
is never a synonym, and a failed stop or retention check leaves the worker
completed but active.
