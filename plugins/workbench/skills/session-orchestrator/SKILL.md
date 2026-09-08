---
name: session-orchestrator
description: >
  Supervises user-visible worker sessions across projects and platforms. Use when
  a controller must create, coordinate, monitor, redirect, integrate, or retire
  multiple Codex, Claude Code, or Cortex Code worker tasks.
---

# Session Orchestrator

Coordinate durable, user-visible workers after `using-workflow` has resolved each
project's policy. This skill owns orchestration, not process routing.

## Iron Laws

**NO WORKER EXISTS WITHOUT AN ADDRESSABLE SESSION IDENTIFIER.**

**NO WORKER RETIRES BEFORE EVERY TERMINAL GATE PASSES.**

**WORKERS NEVER MERGE OR PROMOTE.**

A queued record, process, window, or worktree is evidence of provisioning, not an
attached worker. A worker's completion claim is evidence to verify, not project
completion.

## Start

1. Resolve each repository's instructions, integration target, authorization
   boundary, current worktrees, status, log, and reflog.
2. Read [worker-contract.md](references/worker-contract.md) and issue one complete
   contract per worker. Parallelize only disjoint projects or explicitly disjoint
   ownership; serialize shared footprints and dependencies.
3. Read [registry-and-state.md](references/registry-and-state.md). Create the
   controller registry before launching workers.
4. Read only the selected platform adapter:
   [Codex](references/codex.md), [Claude Code](references/claude-code.md), or
   [Cortex Code](references/cortex-code.md). Never substitute another platform's
   operations.
5. Mark `running` only after the adapter yields a real session ID and a verified
   message exchange. Unsupported attachment stops automated dispatch.

## Control Loop

- Consume milestones, blockers, questions, and completion reports. Record only
  meaningful changes as milestones; unchanged polls stay quiet.
- Answer routine questions from established project policy. Escalate genuine
  owner decisions without broadening the worker's scope meanwhile.
- Scope expansion requires a new explicit contract amendment. Workers never infer
  deployment, live-data, destructive, or external-disclosure authority. They may
  implement, test, adversarially review, push, open PRs, and produce an exact
  merge-ready handoff; the originating controller independently revalidates the
  exact head and checks, obtains required owner authorization, and performs merges.
- On completion, independently inspect commits, durable outputs, verification
  gates, and reachability from the intended integration target.
- Read [lifecycle-and-recovery.md](references/lifecycle-and-recovery.md) for
  provisioning gaps, stale listings, stalled workers, stranded worktrees,
  duplicate risk, interruption, and reopening.

## Retirement

Archive, never delete. Retire only when the deliverable is durably integrated,
required validation passed, durable status is recorded, no follow-up remains, and
the adapter confirms archival or stop-and-retain. Then remove the worker from
active monitoring and the active registry while preserving its addressable history.
A final response alone is never terminal. Blocked, lost, integration-pending, or
awaiting-human-gate workers stay active and quietly monitored.

## Counter-Rationalization

| Temptation | Reality |
| --- | --- |
| "The worktree proves creation worked" | It proves files exist, not that the controller can address the worker. |
| "The listing is empty, so replace it" | Listings can be stale; inspect filesystem and git evidence first. |
| "The worker said done" | Worktree completion says nothing about integration reachability. |
| "Its final response closes the task" | Validation, status, follow-up, and platform archival are separate gates. |
| "Deployment is the natural next step" | Natural sequencing is not authorization. |

Red flags: duplicate launches without identity reconciliation; polling commentary
with no state change; cleanup before reachability proof; policy questions sent to
the owner; or any adapter operation absent from its reference. After three failed
attachment/reconciliation attempts, stop retrying and escalate the capability gap.

Behavioral regressions and RED evidence live in [tests.md](tests.md).
