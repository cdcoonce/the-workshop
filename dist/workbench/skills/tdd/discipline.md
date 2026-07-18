# TDD Discipline: Excuses, Reality, and Delete-Means-Delete

Counter-rationalization reference for the [tdd](SKILL.md) skill's Iron Law. See [core/docs/tdd.md](../../docs/tdd.md) for the full narrative walkthrough this table summarizes.

## Excuse → Reality

| Excuse                                   | Reality                                                        |
| ---------------------------------------- | -------------------------------------------------------------- |
| "Too simple to test"                     | Simple code breaks too. The test takes 30 seconds to write.    |
| "I'll test after"                        | A test that passes immediately proves nothing was verified.    |
| "Already manually tested"                | Ad-hoc verification isn't systematic. No record, can't re-run. |
| "Deleting this working code is wasteful" | Sunk cost fallacy. Unverified code is debt, not an asset.      |
| "TDD will slow me down here"             | Debugging untested code is slower than writing the test first. |

## Delete-Means-Delete

When production code was written before its test, "delete it" has exactly one meaning. These are not loopholes:

- **Don't comment it out.** Commented code is still there, still tempting you to uncomment it instead of rewriting from the test.
- **Don't keep it as reference.** "I'll just glance at it while I rewrite" reintroduces the untested implementation's shape and biases the new one.
- **Don't stash it.** A stash is a promise to come back to code that skipped the Iron Law — don't make that promise.
- **Don't move it to a scratch file.** Same code, different address. Still didn't come from a failing test.

Delete the code, write the test, watch it fail, then write new code to pass it. The new code is allowed to end up identical to the deleted code — that's fine. What's not allowed is skipping the fail-first step to get there.

## Red Flags (expanded)

- Test passed on the first run, without your having watched it fail with the expected error message
- Reasoning that includes "should work" / "probably works" / "this will likely pass" instead of a run you actually observed
- A test assertion that's true regardless of the implementation (e.g. asserting a mock was called instead of asserting the real behavior)
- Writing multiple tests in a batch before writing any implementation ("horizontal slicing" — see the main [SKILL.md](SKILL.md) Anti-Pattern section)
