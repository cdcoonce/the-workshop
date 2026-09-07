# Lifecycle and Recovery

## Provision and attach

Creation moves `planned -> provisioning`. Do not move to `running` until the
adapter returns a real addressable session ID and controller messaging succeeds.
For queued-only creation or stalled provisioning:

1. Preserve the client receipt and proposed workspace.
2. Reconcile platform listings, creation output, filesystem, `git worktree list`,
   status, log, reflog, and live processes.
3. Retry identity reconciliation at bounded backoff, not creation itself.
4. After three failed attempts, mark the worker `lost` or `blocked` and escalate
   the capability gap. Do not launch a duplicate over unexplained progress.

## Stale listing or unaddressable progress

A stale listing is not proof that a worker vanished. If filesystem evidence shows
progress, do not replace the original worker. Freeze overlapping mutations, record
the commits/files/process evidence, and try adapter-supported identity recovery.
If the progressed worker cannot be addressed, preserve its tree and explicitly
hand off either the durable outputs or a takeover plan; never reset or clean it.

## Monitoring and interruption

Prefer event/cursor waits. Otherwise poll with bounded backoff and compare state to
the registry. Emit controller updates only for milestones, blockers, questions,
completion, or required user action. An interrupted wait changes no worker state;
resume monitoring from the saved cursor/observation. Use interruption only when the
adapter supports it and the contract authorizes the reason.

## Completion and stranded worktrees

On `COMPLETE`, independently verify:

1. working-tree status and authored commits;
2. claimed tests and the repository's required full gate;
3. durable artifacts at their declared paths;
4. commit reachability from the intended local and remote integration target;
5. preservation of unrelated user work.

If results exist only in the worker worktree, state is `completed` with integration
`pending`, not retired. Integrate through the authorized repository workflow or
record an explicit handoff containing the worktree, branch, commit IDs, gates, and
next owner. Cleanup remains forbidden until reachability is proven.

## Archived/stopped workers

Reopen the same retained identity when a durable update belongs to its history.
Send and verify the update, then re-archive/stop only after its new output is
integrated or handed off. If the platform cannot reopen, append the update to the
controller registry and project record; do not fabricate a new worker identity.
