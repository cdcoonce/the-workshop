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

## Horizontal vs. Vertical Slicing

**DO NOT write all tests first, then all implementation.** This is "horizontal slicing" — treating RED as "write all tests" and GREEN as "write all code."

This produces **crap tests**:

- Tests written in bulk test _imagined_ behavior, not _actual_ behavior
- You end up testing the _shape_ of things (data structures, function signatures) rather than user-facing behavior
- Tests become insensitive to real changes - they pass when behavior breaks, fail when behavior is fine
- You outrun your headlights, committing to test structure before understanding the implementation

**Correct approach**: Vertical slices via tracer bullets. One test → one implementation → repeat. Each test responds to what you learned from the previous cycle. Because you just wrote the code, you know exactly what behavior matters and how to verify it.

```
WRONG (horizontal):
  RED:   test1, test2, test3, test4, test5
  GREEN: impl1, impl2, impl3, impl4, impl5

RIGHT (vertical):
  RED→GREEN: test1→impl1
  RED→GREEN: test2→impl2
  RED→GREEN: test3→impl3
  ...
```

## Red Flags (expanded)

- Test passed on the first run, without your having watched it fail with the expected error message
- Reasoning that includes "should work" / "probably works" / "this will likely pass" instead of a run you actually observed
- A test assertion that's true regardless of the implementation (e.g. asserting a mock was called instead of asserting the real behavior)
- Writing multiple tests in a batch before writing any implementation ("horizontal slicing" — see the [Horizontal vs. Vertical Slicing](#horizontal-vs-vertical-slicing) section above)
