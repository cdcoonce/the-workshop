# Phase 4: Iterate

Run the benchmark-driven improvement loop on the `improve/{slug}` branch.

## Branch Setup

Check if `improve/{slug}` branch exists:

```
git branch --list improve/{slug}
```

- **Branch exists:** Check it out. Note: "Resuming improvement branch `improve/{slug}`."
- **Branch not found:** Create from current HEAD: `git checkout -b improve/{slug}`. Note: "Created improvement branch `improve/{slug}`."

## Initialization (before the loop)

Before starting the loop: read `baseline_score` from state. If `best_score` is blank (i.e., first run of Phase 4, not a resume), set `best_score` to `baseline_score` and `best_iteration` to `0`. Note: `best_iteration: 0` stays as is (0 is valid). Also read `stall_count` from the state file (for resume support); if absent, treat as `0`.

## Exit Conditions (check at the START of each iteration)

Before running any step, check:

1. `current_score >= target_pass_rate` → exit with reason "target reached"
2. `current_iteration >= max_iterations` → exit with reason "budget exhausted"

On exit: append log entry `{YYYY-MM-DD} — Loop exited: {exit_reason}. Final score: {current_score}%.` Do NOT advance `current_phase` yet — that happens in Phase 5.

## Iteration Steps

Repeat the following steps A–H until an exit condition is met.

### Step A — Read current skill

Read `{skill_path}`. On the first iteration (iteration 1), if `core/skills/{slug}/.best_skill.md` does not exist yet, read from `{skill_path}` directly. On subsequent iterations, `{skill_path}` always reflects the best version (regression handling in Step G ensures this).

### Step B — Read annotated failures

Read `{tests_path}`. Extract all rows where Result = `fail`. These are the failure cases to address. If a `## RED Baseline (no-skill)` table is present, also extract it.

### Step C — Dispatch Skill Writer

Adopt the `skill-writer` agent identity. Provide:

- Full skill content (from Step A)
- Annotated failure rows (from Step B)
- The `## RED Baseline (no-skill)` table, if present (from Step B) — the verbatim no-skill rationalizations tell the writer what loophole a failing test actually exploits, not just its Expected Behavior text
- Strategy guidance (if available from Step H of a previous iteration)

Receive: complete rewritten SKILL.md content (valid Markdown with YAML frontmatter, ≤100 lines).

**Malformed output handling:** If output is not valid Markdown with frontmatter, or exceeds 100 lines, retry once. If the second attempt also fails, pause and prompt the user:

> "Skill Writer produced malformed output twice. Please inspect and advise before continuing."

### Step D — Commit rewrite

Overwrite `{skill_path}` with the Skill Writer output. Commit to the improve branch:

```text
feat({slug}): skill improvement iteration {n}
```

### Step E — Dispatch QA Tester

Adopt the `qa-tester` agent identity. Provide the full skill content and the full test suite from `{tests_path}`.

Receive: annotated test table (with Result and Reason columns filled) and a score summary line.

**Malformed output handling:** If output lacks a valid table or score summary, retry once. If the second attempt also fails, pause and prompt the user:

> "QA Tester produced malformed output twice. Please inspect and advise before continuing."

### Step F — Record score

1. Write the annotated table back to `{tests_path}` (overwrite).
2. Add a row to the Scores table in the state file: `| {n} | {pct}% | |`
3. Increment `current_iteration` in the state file.
4. Append log entry: `{YYYY-MM-DD} — Iteration {n}: {pct}%. Previous best: {best_score}%.`

### Step G — Update best / handle regression

Compare `new_score` to `best_score`:

- **Improvement** (`new_score > best_score`): Update `best_score` and `best_iteration` in the state file. Copy `{skill_path}` content to `core/skills/{slug}/.best_skill.md` and commit: `chore({slug}): update best-version sidecar (iteration {n})`. Reset `stall_count` to `0` in the state file. Note: "New best: {pct}%."
- **Regression** (`new_score < best_score`): Warn the user. Read `core/skills/{slug}/.best_skill.md` and overwrite `{skill_path}` with its contents. Commit: `revert({slug}): revert to best version (iteration {best_iteration})`. Note: "Regression ({new_pct}% < {best_pct}%). Reverted to best version."
- **No change** (`new_score == best_score`): Increment `stall_count` in the state file. Note: "No improvement. Stall count: {stall_count}."

### Step H — Strategy agent check

If `stall_count` (from the state file) is ≥ 2:

1. Adopt the `strategy` agent identity. Provide:
   - Full current skill content
   - All iteration scores from the Scores table
   - All annotated failure tables from this run
2. Receive: a concrete rewrite strategy (plain text).
3. Store strategy text to pass as additional context in the next Step C call.
4. Reset `stall_count` to `0` in the state file.
5. Note: "Strategy agent dispatched. Stall count reset."

Whether or not Step H ran, return to the exit-condition check to begin the next iteration.
