---
name: shared-tree-safety
description: Protect work when a git working tree or worktree may be shared with a live autonomous agent or another session. Use before resetting, force-checkouting, or cleaning any tree an agent might be using, when a working tree changes unexpectedly mid-task, or when taking over a directory another process was working in.
---

# Shared Tree Safety

A working tree you're in may not be yours alone: background agents, other sessions, and scheduled runs commit, branch, and reset concurrently. Destructive git commands assume exclusive ownership — verify it first.

## Before assuming the tree is yours

1. `git worktree list` — know every checkout of this repo before reasoning about any of them.
2. `git log --oneline -5`, `git status`, and `git reflog -10` — recent commits or reflog entries you don't recognize mean another actor is (or was) active.
3. Check for a live worker: look for running processes rooted in the directory (e.g. `lsof +D <dir>` or inspecting the process tree for agent PIDs whose ancestry traces to a dispatcher). A "stalled" delegating dispatch may still have a real terminal worker committing.

## Iron rules

- **Never `git reset --hard`, `git checkout -f`, or `git clean` a tree a live agent may be working.** You will fight the worker commit-for-commit and corrupt both efforts. Kill or confirm the worker dead first.
- **Never assume failure from silence.** Check log/status/reflog before declaring another agent's work abandoned — it may be mid-task.
- **Never rewrite pushed shared history** to fix cosmetic issues (trailers, message style); the rewrite costs more than the blemish.

## Takeover protocol (when you must land work in a contested tree)

1. **Protect your files first**: `git stash push -- <only your files>` — scoped, never a bare `git stash` that grabs the other actor's changes. Note the stash SHA (`git rev-parse stash@{0}`).
2. **Leave the contested tree alone.** Create an isolated worktree from the fresh remote integration branch:
   `git fetch origin && git worktree add <new-dir> -b <branch> origin/<integration-branch>`
3. **Apply your stash by SHA** in the isolated worktree (`git stash apply <sha>`) — index positions shift when other actors stash; the SHA doesn't.
4. Land the work (commit, push, PR) from the isolated worktree, then `git worktree remove` it when merged.

## When you find a live worker

Prefer waiting or coordinating over killing. If you must stop it, kill the _dispatcher's_ process subtree (found via PID ancestry), not just the visible leaf process — orphaned workers keep committing.
