---
name: build-review-land
description: Ships one PR via a builder, a blind mutation reviewer who commits a re-runnable teeth spec, a RED-confirm fixer, and a pinned landing. Use for "worker-per-PR + mutation review", "build this PR with a worker and a reviewer", or the skywatch recipe.
---

# build-review-land

One PR, four steps, three cheap workers. The conductor writes the spec and the
mutation intents, dispatches, judges verdicts, and lands. It never bulk-reads
and never injects a mutation by hand.

**Reuses:** `drain-queue/references/builder-dispatch.md` (builder), `detector-teeth-check`
(spec format, `teeth_check.py`), `github-pr-land` (`pr_land.py land`). **Not**
issue-driven and no cold-read; `drain-queue` may call this per issue.

## Step 0 — the conductor writes three things

1. **Spec.** Behaviors, allowed files, gate command, integration branch, required
   check name. A behavior is a sentence a test can grade.
2. **Mutation intents, before the PR exists and never shown to the builder.**
   One row per named behavior: `# | behavior | intended break | predicted test name`.
   Blindness is the point: a builder's own teeth pick mutations its tests already
   catch. Add one intent you expect to **survive** as a control, marked so.
3. **Spec path**, beside the tests its command runs and named like the nearest committed
   spec. Never a fixed directory: a gate may infer a spec's cwd from where it sits.

## Step 1 — builder (sonnet, own worktree)

Dispatch `builder-dispatch.md` with the spec inline in the `<normative docs>`
slot, `Closes #N` only when an issue exists, and **no** `<teeth mutations>` slot
(the reviewer owns teeth). It returns the PR URL, files with line counts, gate
result, and a `Deviations` section in the PR body for every departure from the
spec. It does not merge and does not remove the worktree.

## Step 2 — reviewer (sonnet, same worktree, after the builder returns)

Dispatch `references/reviewer.md` with the intents, spec, spec path, PR number and
worktree path. The reviewer:

- Anchors each intent as a `<spec path>` row (`label`, `file`, `oracle`, `find`, `replace`),
  the control with `"expect": "survived"` and `why`. Never edits source by hand to mutate it.
- Runs `teeth_check.py` once, full. A red baseline or an ambiguous anchor stops the review.
- Runs the spec-deviation probe: each `Deviations` item against the spec, plus
  two untrusted or edge inputs the spec implies and no test names.
- Posts **one PR comment**: the ledger with columns
  `# | behavior | mutation | predicted test | result | red line`, result in
  `RED-predicted | RED-other | GREEN | UNANCHORED | CONTROL`, then probe
  findings, then the verdict `LAND` or `FIX FIRST` with a proposed test per
  GREEN or UNANCHORED row (name, what it asserts, which mutation reds it).
- Commits the spec on the PR branch and finishes with an empty `git status`.

`RED-other` (the named guard did not bite; another did) and `UNANCHORED` (a spec or
structure problem) are findings, not passes.

## Step 3 — fixer (sonnet, same worktree) only on FIX FIRST

Dispatch `references/fixer.md` with the reviewer's comment. For each proposed
test: write it, show it RED under its stated mutation (re-run the spec with
`--changed-since <base>`), then green. A fixer may change a test's **inputs** so
it discriminates and must record `as proposed | as landed | why`; it may not
change the mutation. It ends with one full `teeth_check.py` run, that count in
its own PR comment, gate green, empty `git status`.

## Step 4 — land (conductor)

```bash
python3 "<github-pr-land skill dir>/scripts/pr_land.py" land <pr> --method squash --gate "<gate>" --gate-evidence passed --require <check>
```

Then `git worktree remove` the builder's tree and prune.
`<github-pr-land skill dir>` is the absolute path its loader announces.

## Slots

| slot                 | used by  | meaning                                                        |
| -------------------- | -------- | -------------------------------------------------------------- |
| `<pr number>`        | both     | The pull request under review or repair.                       |
| `<repo>`             | both     | `owner/name`.                                                  |
| `<worktree path>`    | both     | The builder's worktree; nothing else runs there.               |
| `<branch>`           | both     | The PR branch the worktree is on.                              |
| `<spec path>`        | both     | Step 0's teeth spec path, repo-relative.                       |
| `<gate command>`     | both     | The repository's real lint and test commands, quoted exactly.  |
| `<path to>`          | both     | Directory holding `teeth_check.py` (`detector-teeth-check`).   |
| `<log>`              | both     | Log file a long command writes to; read `rc=` after it.        |
| `<spec>`             | reviewer | The normative spec, inline.                                    |
| `<intent rows>`      | reviewer | Step 0 intents, one per behavior, one marked `[control]`.      |
| `<probe hints>`      | reviewer | Optional inputs the spec implies and no test names.            |
| `<reviewer comment>` | fixer    | The reviewer's PR comment, verbatim.                           |
| `<base>`             | fixer    | Integration branch for `--changed-since`.                      |

## Rules that are not optional

- Serial, one worktree, no concurrent suites: a teeth run beside a suite contaminates it.
  Never commit while a teeth run or the gate is live (either may hold a mutant in source); read `git diff --staged` first.
- Workers never merge, never spawn agents, never use artifact, task-spawning
  or memory tools, never wait on timers.
- The reviewer's voice is a comment; the builder's is the body. Nobody edits
  another role's text.
- The committed spec is the deliverable of review; prose counts are not.
