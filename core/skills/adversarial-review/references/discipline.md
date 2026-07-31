# Discipline

Counter-rationalization machinery for the Iron Law — the skill-specific instance
of the Workshop's discipline-toolkit taxonomy (see the `workshop-skill-creator`
skill).

## What the RED baselines actually found

Five no-skill pressure runs were executed against a real fixture repo before this
skill was written. The result was not what the skill was originally shaped for.

Unaided agents attack claims **well**. Given a real repo, they reverted the change
and re-ran the suite, executed `Decimal(1.005)` rather than reasoning about it, and
grepped for missed call sites — unprompted, under time and authority pressure, and
found every planted defect. The Iron Law is worth stating, but it is not where
agents fail.

Both observed failures were the same failure, and it was the other half: **the
review presented a closed account with no statement of what went unexamined.** One
had never executed the asset at all; the other had swept one function while the
rest of the settlement path went untouched. Neither said so. A reader of either
report would reasonably take the findings list as complete.

That is why `Could not verify` is a REQUIRED slot and not a nicety. It is the one
thing this skill exists to force.

## Excuse → reality

Rows 1–3 are verbatim from observed no-skill failures. Rows 4–6 are reasoned from
the same failure shape and have not been observed.

| Excuse                                                                           | Reality                                                                                                                                                                                                                                                                            |
| -------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| "'I can't reproduce it' is a statement about my tooling, not about the code."    | True, and irrelevant. A tooling limit is a fact about **your coverage**, so it belongs in the review's scope statement — not filed as a caveat on one finding and dropped. This exact sentence is what licensed a finished-looking verdict on an MR whose code was never executed. |
| Closing with "repo is back to committed state, only `__pycache__` is untracked." | Repo hygiene is not an epistemic boundary. It occupies the position where the limits statement belongs and reads like one, which is worse than silence.                                                                                                                            |
| "My summary's three load-bearing claims are all false."                          | A statement about the claims you checked, phrased as a statement about the work. Findings this strong make the missing scope line _more_ load-bearing, not less — a reader takes the remediation list as complete.                                                                 |
| "I found real defects, so the review did its job."                               | Finding defects and bounding coverage are independent. A review that finds three real bugs in the 10% it examined, and does not say it examined 10%, ships a false all-clear on the other 90%.                                                                                     |
| "Listing what I didn't check makes the review look weak."                        | It is the only thing that makes the rest of it trustworthy. A findings list with no stated boundary cannot be acted on, because nobody can tell what the silence covers.                                                                                                           |
| "The unverified part isn't where the risk is."                                   | You are asserting a fact about the code you did not read. That assertion is itself an unattacked claim, and it belongs in the ledger.                                                                                                                                              |

## Red flags — the law already broke

- `Could not verify` is empty, absent, or filled with repo hygiene instead of scope
- Every ledger verdict is `CONFIRMED`
- No command was run anywhere in the review
- A finding is graded `CONFIRMED` or `REFUTED` with no command output, `file:line`, or breaking input
- The ledger has fewer rows than the change has moving parts
- A reproduction limit appears attached to one finding and nowhere else
- You started proposing or applying fixes
- The report reads as finished and you cannot name what you did not look at

## The three-attempt ceiling

Three failed reproduction attempts on one suspected defect is the limit. Record
what you tried, grade it `PLAUSIBLE`, and move on.

The ceiling protects coverage, not the author. Every extra minute on the defect you
cannot demonstrate is another ledger row that goes unattacked — and, on the
evidence above, unmentioned.
