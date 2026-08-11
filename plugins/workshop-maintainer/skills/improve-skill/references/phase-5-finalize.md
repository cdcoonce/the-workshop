# Phase 5: Finalize — Detailed Instructions

Write best skill, clear tests, generate report, update score ledger, commit, open PR, archive state.

**Initialization:** Write `current_phase: finalize` to the state file. Append log: `{date} — Phase 5 started.`

## Step 1 — Write best skill

Read `core/skills/{slug}/.best_skill.md` (the sidecar written by Phase 4 Step G).
Overwrite `{skill_path}` with its full content. This is the final best version.
Then run `git rm core/skills/{slug}/.best_skill.md` to remove the sidecar — it is a temporary artifact and should not remain in the repository after finalization.

## Step 2 — Clear tests.md Result/Reason columns

Read `{tests_path}`. For every data row (all rows except the header and separator),
clear the `Result` and `Reason` cells — leave them blank. Write the file back. The ID, Scenario,
and Expected Behavior columns are untouched. T00 is never removed. The file is now ready for
the next run.

## Step 3 — Generate report

Write `docs/skill-improve/{slug}-report.md` with the following sections:

### Summary

| Field           | Value                                                  |
| --------------- | ------------------------------------------------------ |
| Skill           | {slug}                                                 |
| Date            | {YYYY-MM-DD}                                           |
| Baseline score  | {baseline}%                                            |
| Final score     | {final}%                                               |
| Iterations used | {n}                                                    |
| Target met      | Yes / Not met — reached {final}%, target was {target}% |

### Scores per iteration

Copy the Scores table from the state file as-is:

```
| Iteration | Score | Notes |
```

### Tests fixed this run

List IDs of tests that had Result = `fail` in the baseline (iteration 0) and Result = `pass` in
the final iteration. If none, write "None."

### Tests still failing

List IDs of tests that still have Result = `fail` after the final iteration. If none, write "None."

## Step 4 — Append score ledger row

File: `docs/skill-scores.md`

If the file does not exist, create it with this header:

```
| Slug | Date | Tests | Baseline | Final | Iterations | Target Met |
| ---- | ---- | ----- | -------- | ----- | ---------- | ---------- |
```

Append one row:

```
| {slug} | {date} | {total} | {baseline}% | {final}% | {n} | Yes / No |
```

## Step 5 — Commit and PR

1. Invoke the `commit` skill to commit all changes on `improve/{slug}` branch.
   Use conventional commit message: `feat({slug}): finalize skill improvement — score {final}%`

2. Detect the default branch: run `gh repo view --json defaultBranchRef -q .defaultBranchRef.name`
   (fallback: `git remote show origin | grep 'HEAD branch'`).

3. Open PR with `gh pr create`:
   - Title: `improve({slug}): benchmark-driven skill improvement`
   - Body must include:
     - One-paragraph summary of what was improved and the score gain
     - Scores-per-iteration table (copy from state)
     - Read `prd_issue` from state file. If present, add `Closes #{prd_issue}` on its own line in the PR body. If blank or absent, omit.

## Step 6 — Archive state

1. Set `current_phase: finalize` in the state file (`docs/skill-improve/{slug}.state.md`).
2. Set `status: completed` in the state file.
3. Append log entry: `{YYYY-MM-DD} — Run complete. Final: {final}%. PR opened.`
4. Create `docs/archive/skill-improve/` if it does not exist.
5. Move state file: `git mv docs/skill-improve/{slug}.state.md docs/archive/skill-improve/{slug}.state.md`

## Completion message

Report to the user:

> **Improve-skill complete for `{slug}`.**
> Baseline: {baseline}% → Final: {final}% ({delta:+d}pp). Target {target}%: {met/not met}.
> PR: {pr_url}
> Report: `docs/skill-improve/{slug}-report.md`
> Score ledger updated: `docs/skill-scores.md`
