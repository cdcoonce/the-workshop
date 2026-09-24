# Vault sync: resolve the sync target, not the current branch

Source: vault wrap-up observation, 2026-09-24 (worktree `admiring-merkle-298be3`,
branch `claude/clever-benz-86822f`, hand-resolved as vault `883fb37a`).

## Root cause

Every vault sync path answers "where does this session's work integrate?" with
HEAD's short branch name. That is only true in the primary checkout on `main`.
The desktop app runs sessions in linked worktrees on unpublished `claude/*`
branches (8 of the vault's 9 checkouts on 2026-09-24; 39 of 41 local `claude/*`
branches have no upstream), and Codex runs them on a detached HEAD. The existing
suites for #896/#897 build only clones on `main`, which is why this shipped.

| Path | Uses the branch name to | In a `claude/*` worktree | Severity |
| --- | --- | --- | --- |
| `vault-sync` command.md step 6, bare `git push` | pick the push destination | fails; git's hint is `--set-upstream origin claude/<x>`, which strands the work on a stray remote branch | **silent loss, observed twice** |
| `sync_boundary_squash.py` | `ls-remote refs/heads/<branch>` for pushed-ness | branch absent → every commit "unpushed" → rewrites commits `origin/main` already has | **silent rewrite, reproduced** |
| `entry_replay.py` | `fetch origin <branch>` | refuses; the scripted fallback cannot run | loud; forced hand resolution (observed) |
| `sync_manager.pull` (SessionStart) | `pull --rebase origin <branch>` | fails; session starts from stale local `main`, widening wrap-up divergence | loud |
| `sync_manager.pull` abort | unconditional `rebase --abort` | reports "Repo left mid-rebase" when no rebase ran | false alarm |
| `sync_manager.push` | `push -u origin <branch>` | gated off by `session-stop` on non-default branches; would strand if reached | latent |

Evidence of loss: vault remote branches `claude/confident-ellis-4041f9` (3
commits, 2026-09-20 wrap-up) and `claude/nostalgic-bohr-d70378` (1 commit,
2026-09-10 wrap-up). `git cherry` shows none of their patches on `main`, and
spot checks find their Key Decisions / Brag Doc entries, a lesson note, and the
commit-gate files absent from `main` (one 09-10 Gotchas topic did land).

## Design

One concept, the **sync target**: the remote branch this checkout's session
work integrates into. Resolved fresh per operation, by one rule, in every path:

1. HEAD is on a branch with an upstream on `<remote>` → that branch. Read from
   `branch.<name>.remote`/`.merge` config, not `@{u}`, which fails whenever
   the remote-tracking ref is missing.
2. HEAD is on a branch that exists on `<remote>` under its own name (fresh
   `ls-remote`) → that branch.
3. Otherwise (detached HEAD, or an unpublished local branch) → `<remote>`'s
   default branch, read fresh from `git ls-remote --symref <remote> HEAD`. If
   the remote names none, the target is unresolved: pull falls back to git's
   own upstream handling, squash skips, replay refuses. Never guess `main`, and
   never trust a local `refs/remotes/<remote>/HEAD` — it is unset in fresh
   clones of an empty remote and goes stale if the default branch moves.

Rules 1–2 reproduce today's behavior everywhere today works; rule 3 fires only
where today fails or answers wrongly. No path pushes `--set-upstream` to a
same-named unpublished branch, so no new strays are created.

**Local branch vs. target.** Scripts keep moving the *local* branch (the session
container) and never touch local `main`, which the primary checkout owns. The
push is always `HEAD:<target>`. Every report carries `target` and
`target_source` (`upstream` | `same-name` | `remote-default`) next to `branch`.

**Known limit (accepted).** A human-named branch that was never pushed (a fresh
`feat/x`) resolves to the default branch under rule 3. Today that case fails the
same way a `claude/*` branch does. Publishing the branch first keeps it on its
own name; `target_source: remote-default` makes the choice visible in every
report. Rejected alternative: scoping rule 3 to detached HEAD plus a hardcoded
`claude/*` prefix — narrower, but vendor-specific and blind to the next tool's
naming.

### Per component

- `machinery/engine/sync_manager.py` — `pull()` rebases onto the target; runs
  `rebase --abort` only when `rebase-merge`/`rebase-apply` exists and never
  claims "mid-rebase" otherwise. `push()` pushes `HEAD:<target>`, with `-u`
  only when target equals the branch name.
- `skills/vault-wrap-up/scripts/sync_boundary_squash.py` — pushed-ness from
  `ls-remote` of the target; unresolved target → `skipped`.
- `skills/vault-sync/scripts/entry_replay.py` — fetch, label, and replay onto
  the target; still `branch -f <local branch>` at the end.
- `skills/vault-sync/scripts/sync_target.py` and a byte-identical
  `skills/vault-wrap-up/scripts/sync_target.py` (new scripts, no new
  component) — `resolve()` plus a CLI printing `{remote, branch, target,
  source}`; `entry_replay.py` and `sync_boundary_squash.py` import their
  sibling copy.
- `skills/vault-sync/references/command.md` — steps 5–6 call `sync_target.py`,
  then `git pull --rebase <remote> <target>` and `git push <remote> HEAD:<target>`;
  never accept git's `--set-upstream` hint; `replayed` means
  `push <remote> HEAD:<target>` is a fast-forward.
- `skills/vault-wrap-up/references/command.md` — squash paragraph notes that
  pushed-ness is measured against the target, not the branch.

**Resolver placement.** Two byte-identical skill copies (each skill ships
self-contained) plus the rule inline in the engine's `sync_manager.py` — inline
because the engine is vendored into the vault file by file, and a new module
would need its own vendor-map entry to keep SessionStart importable. The
repo-root `tests/test_sync_target_parity.py` enforces the skill copies'
identity and runs one checkout-shape matrix through both implementations.
Stamping copies from one source (as `stamp.py` does for `inject_persona.py`) is
the upgrade path if a fourth consumer appears.

**Detached HEAD.** The resolver answers it (rule 3) and `sync_manager.pull`
uses that answer. The squash and the replay keep their existing detached-HEAD
guards (`skipped` / `refused`): the replay's final branch move and restore
assume a local branch, so detached support there is its own change.

## Tests (red first)

Fixture shape: bare remote, clone on `main`, and
`git worktree add -b claude/x <path> main` — the desktop layout.

- squash: session commit 1 pushed as `HEAD:main`, commit 2 local → commit 1
  survives in HEAD's history (red today: it is rewritten).
- replay: hub-file conflict against `origin/main` from the `claude/x` worktree →
  `replayed`; local `claude/x` at the new head; `git push origin HEAD:main` is a
  fast-forward; local `main` untouched.
- pull: `claude/x` worktree with origin ahead → rebased onto `origin/main`; a
  failed fetch → message contains no "mid-rebase".
- resolver matrix: upstream set / same-name on remote / unpublished / detached /
  default branch unreadable.
- regression: primary checkout on `main` behaves exactly as before on all paths.

Teeth per `detector-teeth-check`: re-inject the branch-name derivation in each
path and require the named test to go red.

## Versioning

workbench `8.15.2 → 8.15.3` (patch: behavior fix, component inventory
unchanged). Gate with `VERSION_BASE=origin/dev make test`.

## Out of scope

- Recovering the two stranded wrap-ups: vault-side, needs a per-entry call
  (partial overlap with later `main` entries; `confident-ellis` also carries
  commit-gate tooling that may have been superseded). Delete the stray remote
  branches afterwards.
- `entry_replay.py` on a detached HEAD (Codex worktrees): the resolver yields
  the target, but the final branch move and restore assume a local branch.
- `session-stop.py` auto-sync stays paused off the default branch, including on
  `claude/*`; unchanged by design.
