# Phase 3: Baseline — Detailed Instructions

Run the QA Tester agent against the original skill to establish a baseline score.

## Step 1 — Read skill content

Read the full content of `{skill_path}` (resolved in Phase 1).

## Step 2 — Read test suite

Read `{tests_path}`. This is the test table with columns:
`| ID | Scenario | Expected Behavior | Result | Reason |`

The Result and Reason columns are blank — either cleared after a previous run or freshly created. Do not modify them before dispatching the QA Tester.

## Step 3 — RED: No-Skill Baseline

Read `new_test_ids` from the state file. If blank or missing, skip this step entirely and proceed to Step 4 (there is nothing new to RED-test this session).

For each test ID in `new_test_ids`, look up its `Scenario` and `Expected Behavior` row in `{tests_path}`. For each such row:

1. Dispatch a subagent using the `qa-tester` agent identity in **scenario-execution mode** (see `core/agents/qa-tester/AGENT.md`), with **no skill loaded** — do not paste any SKILL.md content into the dispatch.
2. Instruct the subagent to act out the `Scenario` as if it were a real task and to record its verbatim behavior and any rationalization for deviating from the `Expected Behavior`.
3. Compare the subagent's actual behavior to the `Expected Behavior`:
   - **Fails to produce Expected Behavior:** Keep the row. Record the subagent's verbatim rationalization text.
   - **Already produces Expected Behavior with no skill loaded:** Discard the row — this test measures nothing, since the behavior it wants already happens by default. Remove it from `{tests_path}` and from `new_test_ids`.

**Discard rule:** Any test the no-skill baseline already passes must be discarded from the suite, not merely flagged. A test that a no-skill agent satisfies unprompted cannot tell you whether the skill is doing any work.

**All-discarded guard:** If every test in `new_test_ids` is discarded, warn the user that this Grill session produced no tests capable of detecting an unskilled failure, and ask whether to re-run Step 2 of Phase 2 (Grill) with guidance to probe harder, or proceed with the existing suite unchanged.

Append the surviving rows' verbatim rationalizations as a `## RED Baseline (no-skill)` table to `{tests_path}` (columns: `ID`, `No-Skill Behavior`, `Rationalization`). This table becomes input to Phase 4 Step C so rewrites close the actual observed loophole, not just the Expected Behavior text.

Clear `new_test_ids` in the state file once this step completes (whether rows were kept, discarded, or the step was skipped).

## Step 4 — Dispatch QA Tester

Dispatch a subagent using the `qa-tester` agent identity (defined in Phase 6) in **static text-judge mode**. **Model is required** — set it per the rubric in `.claude/docs/agent-matching.md#model-selection` (QA Tester is a reviewer role: never below `mid` tier). An omitted model silently inherits the orchestrator's own model.

Provide the subagent with:

- The **full SKILL.md content** (paste the entire file text — do not give the path)
- The **full test suite table** (paste the entire table — do not give the path)

Instruct the QA Tester to:

1. For each test row, evaluate whether the skill content would cause Claude to produce the Expected Behavior for the given Scenario.
2. Fill in `Result` as `pass` or `fail` for every row.
3. Fill in `Reason` with a concise one-sentence explanation for every row.
4. Return the fully annotated table.
5. Return a summary line in the format: `Score: {N}/{total} = {pct}%`

Wait for the QA Tester subagent to return before proceeding.

If the returned output does not contain a line matching `Score: {N}/{total} = {pct}%`, or if any Result/Reason cells are empty, report the malformed response to the user and halt. Do not write any state.

## Step 5 — Record baseline

After the QA Tester returns:

1. **Write the annotated table** back to `{tests_path}` (overwrite the file with the annotated version).

2. **Update the state file** (`docs/skill-improve/{slug}.state.md`):
   - Set `baseline_score: {pct}` (integer percentage, e.g. `73`). Record `baseline_score` as an integer (strip the `%` sign). Example: if score is 60%, record `baseline_score: 60`.
   - Add a row to the Scores table: `| 0 | {pct}% | Baseline |`

3. **Append a log entry**:
   ```
   {YYYY-MM-DD} — Baseline score: {pct}%. {N}/{total} tests passed.
   ```

## Step 6 — Check baseline vs target

Compare `baseline_score` to `target_pass_rate` (both from state file).

**If `baseline_score >= target_pass_rate`:**

Inform the user:

> Baseline score ({pct}%) already meets or exceeds the target ({target}%). Please raise the target pass rate before we proceed.
> Current target: {target}%. Suggested new target: {suggested}% (10 percentage points above baseline, capped at 100%).

Wait for the user to provide a new target. Validate that the new target is:

- A percentage between 1 and 100
- Strictly greater than `baseline_score`

Update `target_pass_rate` in the state file with the new value. Append a log entry:

```
{YYYY-MM-DD} — Target raised to {new_target}% (was {old_target}%) because baseline already met target.
```

Do **not** start Phase 4 until the target is raised and validated.

Advance `current_phase` to `iterate`. Proceed to Phase 4.

**If `baseline_score < target_pass_rate`:**

Report to the user:

> Baseline: {pct}% ({N}/{total} tests passed). Target: {target}%. Gap: {gap} percentage points. Starting improvement loop.

Advance `current_phase` to `iterate`. Proceed immediately to Phase 4.
