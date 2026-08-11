---
name: worktree-audit
description: Inventory git worktrees across one repo or a whole directory of repos and classify each as reapable, keep, or too-recent, with the evidence that decided it. Use when `git worktree list` has become noise, when a repo or agent system is leaking worktrees or session branches, before cleaning up any worktree, or when asked to tidy or audit worktrees.
---

# Worktree Audit

Long-lived repos accumulate worktrees nothing cleans up: agent sessions, dispatched
slices, one-off checkouts. The sweep is easy; the predicate is where the danger is.

**Reap on "did this worktree author anything?" — never on "is its branch merged?"**

Those come apart constantly. `git worktree add -B <branch> <path> HEAD` cuts the branch
from whatever the launch checkout is on, so a worktree created while the repo sits on a
feature branch is ahead of the trunk **through no fault of its own**, and stays that way
until an unrelated branch merges — possibly never. A sweep gated on "merged" preserves
those forever. One nightly leaked 50 clean, empty worktrees this way while the sweep
meant to reap them ran the whole time and could never succeed.

## Run it

Read-only unless you pass `--reap`.

```
uv run python plugins/workbench/skills/worktree-audit/scripts/worktree_audit.py --root ~/Developer/GitHub
```

- `--repo <path>` — one repo instead of a sweep. No flags at all audits the cwd.
- `--branch-prefix session/` — **the scope.** Names what a disposable session branch looks
  like in this repo. Nothing is reapable without it, and it also enables the orphan-branch
  scan.
- `--all-ages` — ignore the 24h guard. Reach for this rather than faking a clock (see below).
- `--reap` — remove the `reap` verdicts. Run without it first, always.
- `--json` — machine-readable, for scripting a fleet sweep.

## Reading the output

- `✗ reap` — in scope, clean, no commits of its own, older than the age guard.
- `✓ keep` — uncommitted changes, or commits reachable from no other ref. Never touched.
- `· recent` — in scope and empty but touched recently, so it may belong to a live session.
- `? unscoped` — clean and empty, but no `--branch-prefix` claims it.

Verdicts always carry their reason. If one surprises you, that is the signal to stop and
read, not to pass `--reap` harder.

**Why nothing is reapable by default.** "Clean and authored nothing" is not on its own
grounds to delete — it is exactly what a long-lived _infrastructure_ worktree looks like
between merges. A live fleet run flagged afk's persistent integration worktree
(`staging-wt`) as reapable in four repos while the test suite said the predicate was
correct; the suite only ever saw session worktrees, because those were the only ones it
created. Naming the scope is how you say which worktrees are disposable, and it is the
one thing the tool cannot infer for you.

## Why the script rather than doing it by hand

The check is three git flags deep and each omission fails silently toward data loss.
Prefer the script; if you must reconstruct it, these are the traps:

- **`--single-worktree` is load-bearing.** Since git 2.7 `rev-list --all` also expands
  every _other_ worktree's HEAD. A branch checked out in its own worktree is therefore
  always reachable from itself, every count comes back 0, and the reaper deletes
  committed work. Measured: an authored commit counts `0` without the flag, `1` with it.
- **Exclude the branch under test, and its siblings.** Two worktrees cut from the same
  base each make the other's commits "reachable elsewhere". And once a worktree is gone,
  its branch is an ordinary ref inside `--all` and vouches for its own commits — so an
  orphaned branch holding the only copy of its work reads as empty.
- **Never fake the clock to force a sweep.** Passing `now=0` to an age check makes every
  delta negative, which reads as _everything is fresh_ and reaps nothing. That is what
  `--all-ages` is for.
- **`git branch -D` refuses a branch checked out in a worktree.** That refusal is a real
  guard, so an existence check before it is churn avoidance, not safety.

## Before reaping anything

A clean tree is not proof nobody is using it. If the repo has background agents or
scheduled runs, read **shared-tree-safety** first — verdicts describe git state, not
whether a live worker is mid-task. `recent` exists precisely because a working session's
tree is clean between commits.

If a leak keeps recurring after a sweep, the sweep is not the fix. Look for the **pair**
of bugs holding the door open: something creating worktrees that nothing can clean up,
_and_ a predicate that can never clear them. Either alone is bounded; together they
accumulate without limit.
