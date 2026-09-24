# /sync — Manual Git Sync

Manually trigger git synchronization. Useful when switching machines or wanting to sync mid-session.

**Concurrency model:** the vault is written by N same-day Claude sessions _plus_ two machines — on busy days five or more sessions each write the same four accumulating hub files before pushing, hours apart. Divergence at sync time is therefore normal, not exceptional: expect the remote to have moved, and expect conflicts on the hub files to be structural (every session inserts at the same anchors per workshop #871), not a sign anything went wrong.

## Usage

```
/sync          — commit and push all changes
/sync pull     — pull latest from remote (with rebase)
/sync status   — show git status without syncing
```

## Process

### Push (default)

1. **Run the vault-health durability gate immediately before staging:** `uv run --script ci/vault_health.py`. If the configured script fails, times out, or cannot run, stop: leave all edits uncommitted and do not pull or push. A vault without this script remains compatible and may proceed.
2. Stage the intended changes explicitly
3. Generate a descriptive commit message from the changes
4. Run `git commit` with the message
5. **Resolve the sync target, then `git pull --rebase origin <target>` first.** Run `python3 "<skill>/scripts/sync_target.py"` and read `target` from its JSON: the remote branch this checkout's work integrates into. It is **not** the current branch's name. In a desktop-app worktree on an unpublished `claude/*` branch (or a detached HEAD) it is origin's default branch (`source: remote-default`), because that branch name exists nowhere on the remote. Exit 1 (`error`) means nothing resolved: stop and alert the user. Under the concurrency model above (N same-day sessions plus two machines) the remote has usually moved since this session started, so rebase onto the target _before_ pushing instead of letting the push get rejected. If the rebase conflicts: abort it, then check the entry-replay fallback below — if every conflicting file is on its allowlist, run the fallback; otherwise list the conflicting files and alert the user. Never auto-resolve by hand.
6. Run `git push origin HEAD:<target>` to sync with remote. Never accept git's `--set-upstream origin <branch>` hint for a session branch: it publishes a stray `claude/*` branch that no other session or machine pulls, which is how the 2026-09-10 and 2026-09-20 wrap-ups were stranded off `main`.

### Entry-replay fallback (allowlisted hub files only)

When the aborted rebase's conflicts are confined to the four accumulating hub files — `brain/Gotchas.md`, `brain/Key Decisions.md`, `perf/Brag Doc.md`, `.brain/handoff-*.md` — run the scripted replay instead of escalating immediately:

```bash
python3 "<skill>/scripts/entry_replay.py" --base <commit before this session's first commit> --json
```

`<skill>` is this skill's announced base directory (the directory holding SKILL.md); `--base` is the same session base the wrap-up audit and the #892 sync-boundary squash use. The script trusts nothing from the caller: it resolves the sync target itself (the same rule as `sync_target.py`), re-fetches it from origin, re-derives both sides' changes from the base, and re-checks the allowlist itself, so running it on a mis-diagnosed conflict is safe — it refuses.

What it does (issue #893, codifying the vault's `3164dec0` hand-built union):

- Builds the merged result on a fresh branch from fetched `origin/<target>`, starting from **origin's copy** of every file, and carries the session's non-conflicting changes along. Only the session's own local branch is moved to the result; local `main` belongs to the primary checkout and is never touched. On a detached HEAD (Codex runs vault sessions in detached worktrees) no branch moves at all: HEAD is left detached at the result.
- **Ledger rule** (Gotchas, Key Decisions, Brag Doc): the session's diff must be _pure insertions_ of dated entries under a recognized anchor heading. They are re-inserted under that anchor in origin's copy, then all entries under the anchor are **re-sorted newest-first by date** — anchored insert (#871) stays the write-time rule, and the deterministic re-sort restores its ordering guarantee under concurrency. #871's ordering-drift detector stays on as the tooth.
- **Handoff rule**: origin's file wins wholesale; only the `##` section(s) this session touched (the `handoff_sections` collector's section model) are re-applied, and the session's `description:` clause is re-applied **additively** — origin's paragraph plus the session's added clauses, never the session's whole rewritten paragraph.
- **Assertions, fail-closed**: before every replacement it asserts origin's corresponding span is byte-identical to the session-base version, with spans drawn _per entry / per section_ — as narrow as possible (narrowness is spec). Any assertion failure, any non-insertion ledger change (an in-place correction), or any conflict outside the allowlist → it stops, lists the files, and restores the repository. The escalation path is unchanged.
- Runs `uv run --script ci/vault_health.py` on the replayed tree before anything is pushed; a failure restores the original state.

Read the outcome, don't infer it: `replayed` (exit 0) means HEAD — the session's local branch, or a still-detached HEAD (the report's `branch` is `null`) — now sits on the tip of `origin/<target>` (the report's `target`) and step 6's `git push origin HEAD:<target>` is a fast-forward — proceed. `none` (exit 0) means the fallback had nothing to do — proceed exactly as today. `refused` (exit 1) means a fail-closed guard fired — including an in-flight rebase, merge, or bisect — and the repository is already restored to its original branch or detached commit; list the files from the report, alert the user, and never re-attempt the merge with hand-rolled git commands.

### Pull

1. Resolve the sync target as in Push step 5, then run `git pull --rebase origin <target>`
2. If conflict: abort rebase, list conflicting files, alert user
3. If success: report what was pulled

### Status

1. Run `git status` and `git log --oneline -5`
2. Report: uncommitted changes, untracked files, recent commits

## Constraints

- Never auto-resolve merge conflicts
- Never force-push
- Forward references are allowed during editing, but every wikilink must resolve before the health gate permits commit/sync. "Banked as/in `[[X]]`" means `X` exists or is created, linked, and indexed in the same durability transaction.
- Push always rebases onto the remote first (see step 4) — don't rely on the reactive "pull if rejected" path
- **Never let a regenerable derived artifact into the synced vault.** Counters, indexes, caches, and frequency maps (e.g. a term-frequency tally) conflict on every sync because git can't merge two diverged counters. They're regenerable state, not source of truth — keep them machine-local (gitignored) and let each machine rebuild. If a conflict keeps recurring on the same _generated_ file, that file should be untracked, not repeatedly merged. **This rule is scoped to regenerable state.** The hand-authored accumulating ledgers (Gotchas, Key Decisions, Brag Doc, the handoff) are source of truth: they stay in git and merge by entry-replay (the fallback above) — never by untracking them, and never by `.gitattributes merge=union`, which reports no conflict and silently mangles in-place entry corrections. See `brain/Gotchas.md`.
- Show clear error messages on failure
