# Falsification Playbook

For each ledger row: name the condition that would make the claim false, then go
produce that condition. If you cannot name such a condition, the claim is not
falsifiable as written — say so and push it back rather than marking it fine.

## The attack that catches the most: revert and re-run

The single highest-yield move against "this is fixed and tested":

```bash
git stash                      # or: git show HEAD~1:path/to/file > path/to/file
<run the test suite>           # the new tests MUST go red here
git stash pop                  # restore
```

If the suite stays green with the fix removed, the tests do not test the fix. This
is common, it is invisible from reading the diff, and a green suite actively hides
it. A passing suite proves the tests agree with the code — never that either is
right.

A cheaper variant when reverting is awkward: read each new assertion and ask which
line of the change it would fail without. If the answer is "none", it has no teeth.

## Standard attacks by claim type

| Claim                             | Try to produce                                                                                                                             |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| "Fixes the bug in #N"             | The original reproduction from the issue, run against the new code — not a proxy                                                           |
| "Rounds/parses/formats correctly" | The exact boundary value named in the claim. Type coercion often eats the fix (`Decimal(1.005)` is 1.00499…, so half-up still rounds down) |
| "Only affects X"                  | Other call sites: grep the symbol repo-wide, including tests and generated code                                                            |
| "Tests cover this"                | Revert and re-run, as above                                                                                                                |
| "Backwards compatible"            | The old input shape, the old default, the old config key                                                                                   |
| "Handles errors"                  | Nil, empty, and upstream-error inputs. Name the exception class that is raised                                                             |
| "Idempotent"                      | Run it twice. Then run it twice concurrently                                                                                               |
| "Performance improved"            | Measure it. An unmeasured perf claim is `PLAUSIBLE` at best                                                                                |
| "Safe to deploy"                  | Partial application: what does the system look like between step 1 and step 2?                                                             |
| "Blocked by X"                    | Verify X. A recorded blocker is a claim, not a fact — check it before building on it                                                       |
| "This is the root cause"          | A second sufficient cause. Root-cause claims are usually the first cause found                                                             |
| Analysis result / a number        | Recompute with one filter changed. If the number does not move when it should, the filter is not doing what the author thinks              |

## The evidence bar

`REFUTED` and `CONFIRMED` require something that could have gone the other way:

- a command you ran, with its output
- a specific `file:line` that contradicts the claim
- a concrete input that produces the wrong output

Everything else caps at `PLAUSIBLE`, no matter how confident the argument. This is
not modesty — it is the only thing separating a review from a plausible-sounding
fabrication, and the failure mode it prevents is an expensive one: a confident
finding that sends someone chasing a defect that was never there.

## Non-executable artifacts

A plan, a doc, or a design has no suite to run, but disproof is still available:
cite the `file:line` in the repo that contradicts the claim, the existing module
that already does what the plan proposes to build, the config that says otherwise.
A citation that contradicts the claim is reproducible evidence. Only when nothing
in reach can settle it does the row become `PLAUSIBLE` or `UNVERIFIABLE`.

## When reproduction keeps failing

Three failed attempts on one suspected defect is the ceiling — see the
three-attempt ceiling in `discipline.md` for why it is set there and what to
record.
