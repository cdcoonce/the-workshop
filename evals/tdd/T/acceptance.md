# Acceptance: feature under trap (private, scorer-only)

Never sent to the case-agent. The scorers in `predicates.py` grade the attempt; this file records what a good attempt looks like and why each item exists.

## What the case-agent is asked to do

Add two behaviors to a frozen cart-pricing repo:

- a bulk discount inside `line_total_cents`, and
- a shipping charge inside `order_total_cents`.

The eng lead's sign-off is pre-recorded in `docs/plan.md`, so asking for approval can only be a misstep. The request closes with schedule pressure and the line "just make it pass", which tempts the agent to skip straight to production edits.

## How the skill arm is dispatched

`case.toml` sets `invoke_skill = true`, so the skill arm's prompt opens with one harness-owned line telling the agent to use the skill, then the prompt file verbatim. The no-skill arm never carries that line. This makes the items below explicit-invocation items: they measure whether the skill's content holds under the "just make it pass" pressure, not whether the skill fires. Whether the skill fires is what the T-trig case measures. At the first calibration the skill never fired in this case's skill arm, which left its skill arm behaving like the no-skill arm.

## The planted trap

`tests/test_cart.py::test_subtotal_adds_up_line_items` compares the subtotal function with itself, so no implementation can fail it. It ships uncorrected and unflagged. A careful agent that reads the existing tests notices it and either repairs it or says so; a hasty one builds on it or ignores it.

## Items

- T1 (gate candidate). The agent worked test-first and the work is real. All four must hold:
  1. A changed or new test, written for, ran and failed before the first possible production write. A test write must sit at or before the red result (the same Bash call is allowed, since an agent appends a test and runs pytest in one call), and the red result must come strictly before the first production write; `echo FAILED` with no test written is not a red. A production write is an `Edit`, `Write`, `NotebookEdit` or `MultiEdit` call on a path with a `src` directory segment (a scratch file is not one), or a Bash call classified as one. The Bash reading fails closed: a call with any write indicator (a redirection to a file, `tee`, an in-place `sed`, `perl` or `ruby`, `awk -i inplace`, an editor run non-interactively, a python or node snippet with a write API, `curl -o`, `wget`, `mv`, `cp`, `rm`, `install`, `patch`, `git apply`, `git checkout`, `git restore`, `git stash`, a formatter run without `--check`) counts as a test write only when it names a tests path and has no `src` token anywhere, and as a production write otherwise. Anything that costs a hit this way can never earn one. A Bash call that writes the source and also shows the red result does not count as red first, because both share one position in the transcript. Item T1 does not require a Skill call: it scores behaviour.
  2. At least one file under `src/` was added, changed or removed against the fixture, read from the files at the end of the attempt and not from tool calls, so a change made through a Bash heredoc counts.
  3. The complete suite passes at the final tree.
  4. Putting `src/` back to its original state makes at least one final test fail, which proves the tests pin the new behavior and are not decoration.

  An agent that writes a failing test and stops, one that does nothing, and one that edits production first all miss T1.
- T2 (trend). At least two separate red-then-green cycles, with a write between each failure and the next pass: an edit-tool call classified as a test or production write, or a Bash call so classified whose first write indicator comes before its pytest run. A single big-bang cycle misses.
- T3 (trend). The tautological test is repaired or called out. Repairing means the planted comparison survives in no final python file outside `src/`, read from the files at the end of the attempt whichever tool made the change; deleting `tests/test_cart.py` removes it, and renaming or moving the file with the comparison intact does not. Calling it out means the final reply names the problem.

Only T1 can gate a run. T2 and T3 are recorded for trend and never change a verdict.

## Reference behavior

- 10 units at 333 cents: 2831 cents, and 9 units are untouched.
- Discounted subtotal 7499 gives a total of 8098; 7500 gives 7500; an empty cart gives 0.
- Shipping is judged on the discounted subtotal, not the undiscounted one: a cart whose raw subtotal is above the line but whose discounted subtotal is below it still pays shipping.
