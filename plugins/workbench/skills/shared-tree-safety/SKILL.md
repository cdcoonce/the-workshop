---
name: shared-tree-safety
description: >
  Protect work when a git tree may be shared with a live autonomous agent or
  another session. Use before `reset --hard`, force-checkout, or `clean` on
  any tree an agent might be using, or when taking over a directory mid-task.
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

## Advancing a branch checked out in a shared tree

`git reset --keep <target>` keeps working-tree files but **resets the index**. Another session's staged work (a staged rename comes back as an unstaged delete plus an untracked file) is silently lost, with exit 0. Moving a branch that is checked out in a tree another session may be using needs the index preserved explicitly:

1. **Use `git merge --ff-only <target>`.** It keeps the index on a fast-forward and refuses (exit 128, branch and index untouched) on divergence.
2. **If it refuses and the local commits are confirmed superseded upstream** (their content is already in `<target>`), reset with the index preserved. Run this with `TARGET` set to the target ref:

   ```bash
   snap=$(mktemp -d)
   git diff --cached --binary > "$snap/cached.patch"
   git diff --binary > "$snap/worktree.patch"
   git status --porcelain > "$snap/status.txt"
   git reset --keep "$TARGET"
   if [ -s "$snap/cached.patch" ]; then git apply --cached "$snap/cached.patch"; fi
   git status --porcelain | cmp -s - "$snap/status.txt" || { echo "index not restored: hand back"; exit 1; }
   ```

   If the final check fails, stop and hand back to the other session's owner with the snapshots in `$snap`.
3. **Otherwise leave the branch alone** and hand off to the owner. Never run a bare `reset --keep` or `reset --hard` on a tree another session may be using.

## When you find a live worker

Prefer waiting or coordinating over killing. If you must stop it, kill the _dispatcher's_ process subtree (found via PID ancestry), not just the visible leaf process — orphaned workers keep committing.
