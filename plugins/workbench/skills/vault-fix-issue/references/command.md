# /fix-issue — Resolve an Issue with Teeth-Verified Tests

Take one issue (a filed GitHub issue or a known defect) and drive it to a committed, closed fix under a fixed quality bar — the non-negotiable part being that **a test is only trusted once it has been proven to fail against a broken source**.

## When to run

- Clearing a backlog of filed issues (scout-filed, triage-filed, or hand-filed) one at a time.
- Any bug fix or defect resolution where you want TDD discipline enforced, not just "make it green."

## Process

1. **Read the issue and the target.** `gh issue view <N>`; read the function/module it names. Classify it:
   - **Behavior change / bug fix** → needs a new failing test.
   - **Behavior-preserving refactor or dead-code removal** → the existing suite is the safety net; no new test needed, but the suite must already cover the behavior (verify it does — don't assume).
   - **Needs a human decision** (ambiguous intent, competing valid fixes) → stop and ask. Don't guess a direction.

2. **TDD or characterization, depending on classification.**
   - *Behavior change / bug fix:* write the failing test FIRST (RED), watch it fail for the right reason (not an import error or typo), then write the minimal fix (GREEN).
   - *Adding coverage to existing correct code:* the test passes immediately, which proves nothing on its own — go to step 3's mutation check to give it teeth.

3. **Teeth check (the step that makes this worth doing).** Mutate the source so the behavior the test guards is broken (e.g. drop a restore line, make a match case-sensitive, remove a dedup guard), run the test, **confirm it fails**, then revert the mutation exactly — keep a backup and confirm `git diff` is clean on the source afterward. A test that doesn't fail against a plausible mutation isn't testing what you think it's testing.

4. **Keep tests in the project's canonical test location.** Never colocate ad-hoc test files next to source. "Suite green" means running the **whole** test directory, not the one file you touched — a locally-green single file can hide a regression elsewhere.

5. **Review the diff, then commit and close.** If a subagent did the work, read its actual diff before trusting its report — a "done" claim is not evidence. One focused commit per issue (or one commit closing a tight, clearly-related cluster), with `closes #N` in the commit body, then `gh issue close <N>` with a one-line note on what evidence closed it (test name, mutation confirmed, etc.).

## Constraints

- No production change ships without: a failing-then-passing test (bug fixes), a mutation-proven characterization test (coverage adds), or a green existing suite plus a static argument for why it's behavior-preserving (pure refactors).
- Never trust a subagent's "done" without reading the diff yourself.
- A needs-a-decision issue is surfaced to the human, not guessed at.
- "Behavior-preserving" claims must be backed by the static argument *and* the green suite — green alone is not sufficient, since a missing test can't fail.

## Related

- [[Gotchas]] — mutation-teeth-check and single-test-dir lessons this skill encodes
- [[Patterns]] — broader TDD/quality patterns this fits into
