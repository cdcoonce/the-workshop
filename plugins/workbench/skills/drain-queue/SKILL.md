---
name: drain-queue
description: Build a queue of filed, specced issues to empty by hand, one isolated worker per issue, with an adversarial spec gate before each build and a review of every diff before it lands. Use when several ready issues must be built and merged as a batch, when an unattended executor is unavailable and its backlog still has to move, or when the user says "work the queue", "drain the backlog", "land these tickets", or "build these by hand".
---

# Drain Queue

A queue is not a bigger ticket. Working several specced issues to empty fails in ways one
issue never does: a spec that reads fine to the person who wrote it an hour ago, two workers
editing the same file from what they each believe is an isolated tree, a batch of individually
green pull requests that lands a red integration branch. Two roles keep those apart. The
**conductor** holds the queue, the specs, and the merge button. Each **worker** builds exactly
one issue and merges nothing.

Do not use this to shape work. The queue is filed issues whose bodies are already complete
specs. Shaping belongs to `brainstorm`, `write-a-prd`, and `prd-to-issues`.

## Step zero: pin the integration target

Read the repository's own policy — project instructions, CI config, protected-branch rules —
and name the integration branch before dispatching anything. Never infer it from the hosting
provider's default branch. The target is baked into every worker's worktree base and every
pull request base; discovering it was wrong at merge time means rebasing the whole queue.

Then partition the queue by file footprint. List the files each issue actually touches and
group the overlaps. **Sequential is the default.** Run workers concurrently only across groups
you have enumerated as disjoint — eyeballing disjointness is how two workers end up in one
file, and a worktree does not protect a file two workers both edit.

## The loop, per issue

**1. Gate the spec cold.** Dispatch a fresh reader using
[cold-reader.md](references/cold-reader.md). The reader must not have seen the conversation
that shaped the spec — that is the entire mechanism, and everything else in the reader prompt
is a checklist. Gate specs you wrote yourself, especially the ones you wrote this session:
authorship is what blinds you to an unbound referent. Three verdicts:

- **BUILD** — no blocking findings. Proceed.
- **REWRITE** — fixable by editing the issue body. Apply the reader's exact replacement text,
  then re-state BUILD. This is the common case, not a failure.
- **NOT-DISPATCH-READY** — the issue leaves the queue and goes back to shaping. Do not build
  it, and do not quietly rescope it into something buildable.

The reader writes its own verdict comment on the issue before returning. The ticket is the
memory store; a verdict that lives only in the conductor's context dies with the session.

**2. Dispatch one worker into one worktree.** Build the prompt from
[builder-dispatch.md](references/builder-dispatch.md). Every worker gets its own worktree cut
from a freshly fetched integration branch, an explicit list of files it may touch, an explicit
list it may not, and an instruction not to merge.

**3. Review the diff yourself.** You hold the spec and the file allowlist; a reviewer who does
not cannot see that a diff touches a forbidden file. Hunt four signatures: existing tests
inverted or weakened to make a build pass, files outside the allowlist, deviation from the
spec (judge it — a good deviation is a spec bug worth keeping, not an automatic reject), and
a new test that passes for the wrong reason. Then re-run the repository's full gate yourself,
in the worker's worktree, with your own hands. A worker reporting green is a claim.

**4. Land and tear down.**

```bash
cd <worktree> && <repo gate command> \
  && cd <main checkout> && gh pr merge <PR> --squash \
  && gh issue view <N> --json state --jq .state \
  && git worktree remove <worktree> && git branch -D <branch> \
  && git fetch origin && git log --oneline -1 origin/<integration-branch>
```

Confirm the issue actually closed. A linked-issue keyword that silently failed to fire leaves
the ticket open and the queue miscounted. The next issue starts from the newly fetched tip.

## Iron rules

- **Every pull request carries teeth evidence** in its body: the named mutation, the red
  output it produced, the restore, the green re-run. See `detector-teeth-check` for method. A
  teeth run audits the test as much as the code — it is what catches a test that passes
  through a clause the feature does not own.
- **Workers never merge.** One hand builds, another lands. Collapsing the roles removes the
  only independent check in the loop.
- **Never `git add .`** in a worker prompt or a conductor fix. Stage the allowlist explicitly.

## When a worker comes back wrong

- **A bounded correction** — a missing guard, a narrow validation gap. Fix it yourself in that
  worktree and say so in the pull request. Cheaper than a dispatch cycle.
- **A wrong approach** — the diff solves a different problem, or ignores a pin. Discard it and
  dispatch a fresh worker. Do not negotiate a bad diff into a good one.
- **A defect that traces to the spec, not the build** — park the issue, rewrite the body, and
  re-gate it cold. Re-dispatching against a bad spec only spends another worker.

## When the queue is empty

Check out the integration branch fresh, pull, and run the full gate there — not in a worktree.
Squash-merges from concurrently-cut branches each pass their own gate and can still combine
into a red tree. Confirm the remote CI legs went green rather than assuming they did. Then
report a ledger, one row per issue: issue, pull request, cold-read verdict, teeth evidence,
and outcome. The ledger is what distinguishes a queue that was gated from one that was
rubber-stamped.
