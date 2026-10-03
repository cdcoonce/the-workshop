# PR #896 — binding spec (title + body, verbatim)

TITLE: feat(workbench): collapse unpushed session commits at the wrap-up sync boundary

Implements #892 — `/wrap-up` now collapses this session's unpushed vault commits into the single wrap-up commit at the sync boundary, before `/sync`'s `git pull --rebase`, so a conflicted rebase replays one session commit instead of N.

## What changed

- **`plugins/workbench/skills/vault-wrap-up/scripts/sync_boundary_squash.py`** (new, stdlib-only): runs from the vault root immediately after the wrap-up commit. Soft-resets to the squash base and re-commits with `commit -C <old HEAD>`, so the tree is preserved byte-for-byte and the wrap-up message/authorship carry over. Exit 0 for `squashed`/`none`/`skipped`; the boundary is strictly fail-open — every guard refusal leaves the repository untouched and `/sync` proceeds exactly as today.
- **`references/command.md`** step 10: wires the script in between the wrap-up commit and `git pull --rebase`, and instructs treating `skipped`/`none`/non-zero identically (proceed as today, never re-attempt with hand-rolled git).
- **`tests.md`**: behavioral row T29 for the boundary.
- **workbench `8.10.1` → `8.11.0`** (behavior addition to a shipped skill, no component change) plus the stamped propagation (platform manifests, marketplace, README, plugins reference).

`plugins/workbench/skills/vault-sync/**` is untouched — that is companion issue #893's footprint.

## Guards (per the issue spec)

- "Unpushed" is decided by a **fresh `git ls-remote`**, never the remote-tracking ref; when the remote tip is an object this clone never fetched (the common two-machine case), the branch is fetched once purely to make the ancestry test possible.
- A session commit already on the remote is **never rewritten**: the newest pushed session commit becomes the squash base and only the commits after it collapse.
- Ambiguity skips: a merge commit in the session range (e.g. a hand-built recovery merge), an interleaved pushed/unpushed classification, staged-but-uncommitted changes, an unreachable remote, detached HEAD, a base that is not an ancestor, and a net-empty unpushed run all report `skipped` and change nothing.
- Mid-session durability-commit practice is unchanged; only granularity at the sync boundary changes.

## Verification

- **Acceptance tests** (22, all green; real bare-remote + clone fixtures, script run as a subprocess):
  - (a) 3+ unpushed commits touching the same file → exactly one commit before `pull --rebase`, tree identical, wrap-up message kept; plus an integration test that actually runs `git pull --rebase` onto a moved remote and pushes.
  - (b) first session commit already pushed → its SHA survives; squash base is that commit.
  - (c) a fabricated lying tracking ref (claims pushed when the remote never got it) and a deleted tracking ref (hides a real push) both classify correctly via ls-remote.
  - (d) merge commit in the session range → `skipped`, repository byte-identical.
- **Teeth** (`scripts/tests/sync_boundary_squash.teeth.json`, run via `detector-teeth-check`): 10/10 mutants killed, each on its predicted test, all against the real git dependency (no doubles); the declared reorder control survived with its inertness argument. Anchors verified with `--check-anchors`.
- **Full gate**: `make stamp` committed; `VERSION_BASE=origin/dev make test` green (root suite 1107 passed / 6 skipped, all skill-script suites, machinery + parity suites, `stamp --check`, version-bump gate); `uv run python -m scripts.smoke_test workbench` PASS.

