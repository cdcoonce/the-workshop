---
name: shared-tree-safety
description: >
  Check who else uses a git tree, index, venv or cache before you reset,
  rebuild, delete, prune or call it dormant: live processes, MCP and launchd
  registrations, other sessions. Use before `reset --hard`, `clean`,
  `reindex --force` or rm.
---

# Shared Tree Safety

A working tree you're in may not be yours alone: background agents, other sessions, and scheduled runs commit, branch, and reset concurrently. Destructive git commands assume exclusive ownership — verify it first.

## Before assuming the tree is yours

1. `git worktree list` — know every checkout of this repo before reasoning about any of them.
2. `git log --oneline -5`, `git status`, and `git reflog -10` — recent commits or reflog entries you don't recognize mean another actor is (or was) active.
3. Check for a live worker: look for running processes rooted in the directory (e.g. `lsof +D <dir>` (an open-handle probe misses stores opened per query; see the section below) or inspecting the process tree for agent PIDs whose ancestry traces to a dispatcher). A "stalled" delegating dispatch may still have a real terminal worker committing.

## Before changing something others may read

A repo grep cannot see who reads an artifact: MCP servers, launchd jobs and cron entries register it by literal path in user-level files no repository contains, and an open-handle probe sees nothing when a reader opens the store per query. Before you recommend or run any rebuild, delete, prune, retire, unload, or call something "dormant", "unreferenced" or "safe to remove", ask the process table and the registrations.

Run `readers.py` with the artifact's path and the name of its consumer (script, venv or server):

```bash
uv run --no-project --python ">=3.11" python "<skill base directory>/scripts/readers.py" <needle> ...
```

This runs under Python 3.11 or newer whatever interpreter the working directory pins and creates or changes nothing in it. Without `--no-project`, `uv run` writes a `.venv` and a lock file into a directory that has a project file, which would sync the very environment under inspection; the repo-relative form resolves only inside the workshop checkout.

- Write `Live check: <command> -> <READERS line>, exit <code>` into the option text or the report, with the needle strings visible in the command. Where you did not check a surface, write `Not checked: <surface>`.
- **exit 3** means stop and name the readers (the process lines, and the holders it lists). Read the listed holders, not just the exit code: `--holders <plugin cache dir>` lists every version's markers.
- Exit 0 with `declared` above zero: do not call it dormant. Name each registration as a reader that starts on next use.
- A repo grep, an open-handle probe and a tool's own green status line are not reader evidence.

When to pass the flags:

- `--repo <path>` to scan that repository's `.mcp.json` (repeat the flag for more repositories).
- `--holders <plugin cache dir>` for a plugin's cache, which holds `<version>/.in_use/<pid>` markers written by the plugin runtime.
- `--ignore-pid <the session's own pid>`: the plugin runtime writes a marker for the very session running the script, so without it a `--holders` call exits 3 on the caller itself. Find the pid with this command, which walks up from the shell to the `claude` process whose pid the runtime records; the marker names that process, which is neither `$$` nor `$PPID` of a tool shell:

  ```bash
  p=$$; while [ "$p" -gt 1 ]; do c=$(ps -o comm= -p "$p"); case "$c" in claude|*/claude) echo "$p"; break;; esac; p=$(ps -o ppid= -p "$p" | tr -d ' '); done
  ```

  An empty result means the pid was not found (for example `claude` running as `node` on Linux); it does not mean holders are clear. Look the pid up another way, or read the listed holders and judge each.

The `Live check:` and `Not checked:` form is guidance local to this skill.

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
