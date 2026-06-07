# Phase 2: Grill

Build a test suite using the skill-analyst agent and a user challenge loop.

## Step 1 — Dispatch Skill Analyst

Read `{skill_path}`. Adopt the `skill-analyst` agent identity. Provide the full SKILL.md content pasted inline.

If `{tests_path}` exists: also read it, extract one-line summaries of each test (ID + Scenario), and include them as existing test summaries in the analyst input.

Receive: a three-tier weakness report (Surface Gaps, Behavioral Edge Cases, Adversarial Probes) with proposed test cases.

**Malformed output handling:** If the output is missing any tier or has fewer than 2 findings per tier, retry once. If the second attempt is also malformed, pause and prompt the user:

> "Skill analyst produced malformed output twice. Please inspect and advise before continuing."

Log: `{YYYY-MM-DD} — Skill analyst dispatched. Findings: {n} surface, {n} behavioral, {n} adversarial.`

## Step 2 — User Challenge Loop

Present the analyst's findings to the user tier-by-tier. For each tier (Surface Gaps → Behavioral Edge Cases → Adversarial Probes):

**If AskUserQuestion is available:** Present the findings as a multiSelect list (all selected by default). Ask:

> "Review these **{tier name}** findings. Deselect any that aren't real gaps, and note any domain-specific gaps the analysis missed."

**If AskUserQuestion is NOT available:** List findings numbered, ask user to type which numbers to reject and any additions.

After each tier, collect:

- Which findings the user accepted (kept selected)
- Any domain-specific gaps the user added (create proposed tests for these)

**Full-rejection guard:** After all three tiers are processed, if zero findings were accepted across all tiers: warn the user and re-run the analyst (maximum 2 re-analyses). Ask what kind of gaps they are looking for. Log: `{YYYY-MM-DD} — All findings rejected. Re-running analyst with user guidance.` Then return to Step 1 with the user's guidance passed as additional context to the analyst. If the user rejects all findings a second time, proceed with user-authored tests only (prompt user to describe tests manually).

Log: `{YYYY-MM-DD} — Challenge complete. Accepted: {n}/{total} findings. User added: {n}.`

## Step 3 — Assemble Test Suite

**If `{tests_path}` exists (append mode):** Read existing tests. Determine the highest existing T-number. Number new rows starting from the next available ID. Append accepted findings as new rows grouped by tier. Do not remove, modify, or renumber existing rows. Do not duplicate T00.

**If `{tests_path}` does not exist (new suite):** Create the file with columns `| ID | Scenario | Expected Behavior | Result | Reason |`. T00 is always first: Scenario = "Skill SKILL.md must be ≤100 lines", Expected = "Claude counts lines; if >100, reports the violation and halts execution." Number accepted findings T01, T02, etc., grouped by tier.

For each accepted finding, convert its proposed test into a table row:

- **Scenario** = the proposed test's scenario text
- **Expected Behavior** = the proposed test's expected behavior text

Ask user to confirm the total test count. If the count would be 0 (excluding T00), re-prompt once.

## Step 4 — Set Config

Ask target pass rate (default 90%) and max iterations (default 5). Record in state file. Advance `current_phase` to `baseline`. Log: `{YYYY-MM-DD} — Grill complete. Suite: {total} tests. Target: {rate}%. Max: {max} iterations.`

## Step 5 — Commit

`git add {tests_path} docs/skill-improve/{slug}.state.md && git commit -m "test({slug}): add benchmark test suite"`
