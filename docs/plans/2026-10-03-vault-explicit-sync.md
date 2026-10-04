# Scoped explicit Vault sync

Date: 2026-10-03

The user authorized constraining explicit sync to intended changes. The helper
must require `--explicit-sync` plus repeatable `--path` arguments before running
Git. Ordinary Stop events must never manufacture this authorization (the root
agent owns wrapper and generated wiring changes).

The public Python `push` API retains its existing behavior when `intended_paths`
is omitted. An explicit empty list does nothing. A nonempty list names exact
vault-relative files, including both endpoints of a rename, without directory
or Git pathspec expansion. Scope means whole working-tree files, including any
unstaged portions of a selected file. Foreign pre-staged paths cause refusal
before mutation; the helper never resets or unstages another session's index.
The commit itself uses literal paths and `--only` so late foreign staging cannot
enter it. Staged rename sources/deletions are excluded from `add` when already
absent from the index, but remain in the commit's authorized path list.

When a whole-tree health callback is supplied, any foreign changed path causes
refusal before that callback. This conservatively prevents an uncommitted note
outside the scope from satisfying a graph dependency in the proposed commit.
Scope is checked again after the callback. A future prospective-tree health
check could permit benign unrelated changes; this slice does not construct a
new snapshot workflow. Plain scoped API calls without a health callback may
still leave unrelated unstaged/untracked work in place.

## Validation plan

Use red/green vertical slices for the CLI refusal and argument forwarding,
empty scope, selective commit, foreign staged refusal, literal special-character
paths, rename/deletion handling, invalid paths, and health-gate preservation.
Use only temporary local bare Git remotes and existing machinery test fixtures.
Run the complete sync-manager and session-stop test files after the slices.

## Verification completed

The missing-path CLI guard, forwarding, empty scope, selective commit, foreign
staged refusal, literal filename handling, invalid scope, staged rename handling,
late foreign staging, and health-check scope guards were each observed failing
before their implementation and passing afterward. Additional real-Git cases
cover both rename endpoints, an already-staged deletion, whole-file semantics,
and preserving the index and working tree when health fails.

Both owned machinery test files passed together: **88 passed**. Local bare
remotes were used; Git hooks and commit signing were disabled in their fixtures.
`git diff --check` passed. Full project/version/stamp gates are deferred to the
root agent; this slice does not claim release readiness.

## Deliberate limits

The scope constrains newly committed changes, not existing local commit history
that a push may publish. Path-limited commits exclude unrelated staged content,
but do not provide atomic isolation for same-file edits or concurrent rebase and
index operations. Shared live checkouts still require coordination or isolation.
The existing whole-tree health gate,
rebase-first flow, sync target resolution, and conflict handling stay in place.

No installed caches, live registrations, external remotes, commits, version
files, or generated stamp outputs are changed by this slice.
