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
`pending`, not retired. Workers never merge: they may push and open the review
artifact allowed by their contract, then record a merge-ready handoff containing
the worktree, PR URL, branch, exact head, target, checks, and blockers. The
originating controller independently revalidates that exact head and checks,
obtains required owner authorization, and alone merges. An open or approved PR,
green checks, auto-merge availability, and `handed-off` status are not durable
integration. Promotion is a separate controller-owned gate. Cleanup remains
forbidden until target reachability is proven.

## Terminal retirement

A worker final response begins verification; it does not retire the task. In order:

1. prove the authorized deliverable is reachable from its intended integration target;
2. run and record every required validation gate;
3. write the durable project/controller status and record its location;
4. confirm no follow-up, dependency, or human decision remains assigned;
5. perform the adapter's non-destructive archive/stop-retain operation and confirm it;
6. atomically move the worker from active monitoring/registry to retained history.

Any failed or unresolved gate leaves the worker active. In particular, explicit
handoff is not durable integration, and `waiting`, `blocked`, or `lost` workers are
not terminal. If platform archival fails, record the failure and keep the completed
worker active. If platform archival succeeds but registry archival fails, reconcile
the same retained identity; never create a replacement or delete its history.

## Archived/stopped workers

Reopen the same retained identity when a durable update belongs to its history.
Send and verify the update, then re-archive/stop only after its new output is
integrated and every terminal gate passes again. If the platform cannot reopen, append the update to the
controller registry and project record; do not fabricate a new worker identity.
