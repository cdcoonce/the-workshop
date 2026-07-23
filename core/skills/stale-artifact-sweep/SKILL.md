---
name: stale-artifact-sweep
description: Use before acting on any recorded artifact — an issue, a review finding, a "do not merge" comment, a TODO or blocker doc, a plan prerequisite, a branch someone said still needs reviving. Re-verifies each against current reality and classifies it with evidence. Read-only.
---

# Stale Artifact Sweep

A recorded artifact is a **claim about state, not a fact**. It was true when written. Between
then and now the issue got closed, the fix landed, the file was rewritten, the branch was half
merged. Acting on the record without re-deriving it is how you re-implement shipped work, revive
a branch for zero gain, block a merge on a finding that no longer reproduces, or merge a doc that
was accurate at write time and is a regression by merge time.

All four of those happened in a single session. That session is why this skill exists.

This is classification only. It never checks out, merges, closes, comments, or pushes. Acting on
the result is a separate, explicit step.

## When to run it

Before `mr-merge-order`, `mr-review-fixes`, `triage-issue`, or any "pick up where we left off"
work. Those skills all assume the artifacts they are handed are true. This is the step that earns
that assumption.

## Verdicts

Every artifact gets exactly one, and every verdict carries the evidence that produced it. A bare
verdict is the failure this skill exists to prevent — never emit one.

| Verdict                | Meaning                                                              |
| ---------------------- | -------------------------------------------------------------------- |
| `STILL_VALID`          | Re-derived against current state and still true.                     |
| `ALREADY_DONE`         | The work is present in the target already.                           |
| `SUPERSEDED`           | Something else changed the ground under it; the record is now wrong. |
| `NO_LONGER_REPRODUCES` | The check that produced it was re-run and passed.                    |
| `UNVERIFIABLE`         | Could not be decided from available evidence. Say what is missing.   |

`NO_LONGER_REPRODUCES` requires an **actual re-run**. "The fix probably landed" is
`UNVERIFIABLE`, not a clean bill of health.

## Procedure

### 1. Git-mechanical checks — run the script

```bash
uv run python core/skills/stale-artifact-sweep/scripts/stale_check.py --repo <path> --target dev commit <sha>
```

- `branch <name>` — per-commit containment. Tells you which commits to **drop** and which are
  genuinely additive, so a half-landed branch is not revived wholesale.
- `finding <reviewed-sha> --file <path>` — has the ground under a review finding moved since the
  commit the review cites?

Prefer the script over doing this by hand. "Is it in the target?" has four distinct answers
(ancestor, cherry-equivalent, effect-present, additive) and eyeballing a log finds only the first.

### 2. Issue and ticket state — check by hand

The script does not make network calls, so unattended runs cannot be blocked by them.

- Is the issue **already closed**? A closed issue in an old plan is not open work.
- Is the described behaviour **already present** in the target branch? An open issue can still be
  done — closing lags shipping. Read the code, not the ticket.

### 3. Review findings and "do not merge" comments — re-run the check

A blocker declared on commit X says nothing about head Y.

- Compare the commit the review cites against the current branch head.
- If the cited files moved, **re-run the original check** — the CI job, the scanner, the test.
- Only a passing re-run justifies `NO_LONGER_REPRODUCES`. A newer green pipeline on a _different_
  commit does not count.

### 4. Semantic staleness — read the content

The check no script can do, and the one that regresses documentation.

A commit can be textually clean and still **wrong** after something else lands: a doc correcting
a five-row CI stage table is accurate when written and a regression once a sibling change adds
three stages. When an artifact _describes_ something another change modified, read what it says
against current reality. Textual cleanliness is not correctness.

## Reporting rules

- One verdict per artifact, each with its evidence. Name shas, files, and runs.
- State that the sweep was read-only and that nothing was acted on.
- Recommend the action separately from the verdict, and let the user take it.
- When a verdict is `UNVERIFIABLE`, say precisely what would settle it. That is a work item, not
  a shrug.
- Do not upgrade confidence to make the report tidier. `UNVERIFIABLE` on four of six artifacts is
  a useful result.
