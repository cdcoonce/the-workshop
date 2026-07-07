# /sync — Manual Git Sync

Manually trigger git synchronization. Useful when switching machines or wanting to sync mid-session.

## Usage

```
/sync          — commit and push all changes
/sync pull     — pull latest from remote (with rebase)
/sync status   — show git status without syncing
```

## Process

### Push (default)

1. Run `git add .` to stage all changes
2. Generate a descriptive commit message from the changes
3. Run `git commit` with the message
4. **`git pull --rebase` first** — the vault syncs across two machines, so the remote has often moved since this session started. Rebase onto it _before_ pushing instead of letting the push get rejected. If the rebase conflicts: abort it, list the conflicting files, alert the user — never auto-resolve.
5. Run `git push` to sync with remote

### Pull

1. Run `git pull --rebase`
2. If conflict: abort rebase, list conflicting files, alert user
3. If success: report what was pulled

### Status

1. Run `git status` and `git log --oneline -5`
2. Report: uncommitted changes, untracked files, recent commits

## Constraints

- Never auto-resolve merge conflicts
- Never force-push
- Push always rebases onto the remote first (see step 4) — don't rely on the reactive "pull if rejected" path
- **Never let an accumulating/derived artifact into the synced vault.** Counters, indexes, caches, and frequency maps (e.g. a term-frequency tally) conflict on every two-machine sync because git can't merge two diverged counters. They're regenerable state, not source of truth — keep them machine-local (gitignored) and let each machine rebuild. If a conflict keeps recurring on the same generated file, that file should be untracked, not repeatedly merged. See `brain/Gotchas.md`.
- Show clear error messages on failure
