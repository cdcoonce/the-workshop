# Session Orchestrator Design Brief

## Decision

Add `session-orchestrator` to the universal `workbench` plugin: one shared
controller contract with thin, explicit Codex, Claude Code, and Cortex Code
adapters. The originating Household Ledger controller is the proving use case,
not a baked-in dependency.

## Chosen architecture

- A lean invocation-loaded core owns worker contracts, registry state,
  authorization, milestones, integration verification, and retirement.
- Flat adapter references fill the same lifecycle matrix using only documented
  platform capabilities. Unsupported operations are first-class outcomes.
- Machine-local controller state defaults to
  `~/.workshop/session-orchestrator/`; project commits and artifacts remain in
  their repositories.
- A deterministic Python helper owns atomic registry transitions. This avoids
  repeatedly reimplementing the two failure-prone gates: attachment requires an
  addressable ID plus message exchange, and retirement requires integration or
  explicit handoff evidence.

## Alternatives rejected

1. **Three platform skills.** Rejected because the authorization, contract,
   registry, recovery, and integration invariants would drift independently.
2. **One undifferentiated procedure.** Rejected because it encourages invented
   parity: Codex has addressable desktop tasks, Claude Code lacks safe live
   controller messaging in its documented CLI, and Cortex Code lacks an
   addressable lifecycle API.
3. **Extend `using-workflow`.** Rejected because it resolves repository policy and
   process selection; it does not own session creation or lifecycle state.
4. **Reuse vault dispatch/context delegation.** Rejected as the core because those
   skills are vault/AFK-specific. Their prompt discipline informs the shared
   contract without importing their scope.
5. **Prose-only registry.** Rejected because duplicate names, provisional IDs,
   quiet polling timestamps, and retirement gates are deterministic repeated
   state transitions.

## Success criteria

- Two independent projects can run concurrently with distinct ownership and
  human-readable registry entries.
- Creation is not reported successful until a real session ID is addressable and
  controller messaging succeeds.
- Routine policy questions stay with the controller; new owner authority is
  escalated.
- Stale listings never erase direct git/filesystem evidence or trigger blind
  replacement.
- Worktree completion remains pending until commits/durable outputs are reachable
  from the intended integration target or explicitly handed off.
- Monitoring emits only meaningful changes; retirement preserves history and
  occurs only after integration/handoff.

## Failure modes guarded

- queued-only creation, stalled provisioning, and interrupted waits;
- stale listings, duplicate replacement, and progressed-but-unaddressable workers;
- inferred merge/deploy/live-data/destructive/external-disclosure authority;
- completed work stranded in a worktree;
- destructive cleanup before reachability proof;
- archived/stopped worker updates losing identity continuity;
- fabricated platform APIs or treating process/window IDs as session IDs.

## Non-goals

- Replacing repository-specific workflow routing or CI policy.
- Providing a universal daemon, scheduler, or hosted control plane.
- Making Cortex automation appear supported before it exposes addressable sessions.
- Granting merge, release, deployment, live-data, destructive, or disclosure
  authority.
- Publishing, promoting, or merging the plugin as part of this change.
