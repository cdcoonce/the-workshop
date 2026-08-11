# Claim Taxonomy

The ledger is the whole review in miniature. A claim that never reaches the ledger
is never attacked, and its absence is invisible — there is no blank row where an
unenumerated claim should have been. So enumeration is the step to over-do.

## Where claims hide

Work asserts things in more places than it states them.

| Surface                         | The claim it carries                                                  |
| ------------------------------- | --------------------------------------------------------------------- |
| Commit subject                  | This change does exactly this, and only this                          |
| Commit body / MR description    | This was the cause; this is the effect; this is the blast radius      |
| `Fixes #N` / linked issue       | The reported symptom no longer reproduces                             |
| Test name                       | This behavior is covered, and covered by _this_ test                  |
| Docstring / type hints          | These are the accepted inputs and the returned shape                  |
| Comment explaining a workaround | The thing being worked around is real and still real                  |
| An agent's "done" summary       | Each bullet is an independent claim, usually the least-checked kind   |
| A removed guard or check        | Nothing still depends on it                                           |
| A changed default               | No caller relied on the old one                                       |
| Green CI on the head SHA        | The suite ran, on this code, and would have failed on the alternative |

## Implicit claims

Explicit claims are the easy half. Every change also asserts things nobody wrote:

- **A changed line asserts the old line was wrong.** Was it? Sometimes the old
  behavior was load-bearing somewhere the author did not look.
- **A new test asserts the behavior was previously untested.** Check whether an
  existing test already covered it — and whether the new one is a duplicate that
  makes coverage look better than it got.
- **A narrowed type or validation asserts nothing sends the wider input.** Callers
  disagree more often than authors expect.
- **A deleted file asserts nothing imports it.** Grep, do not assume.
- **A migration asserts it is reversible, or that irreversibility is acceptable.**
- **A performance change asserts the old path was the bottleneck.**
- **An added dependency asserts the capability did not already exist in-tree.**

## Non-code work

The ledger is medium-agnostic. The surfaces change; the method does not.

- **Plans and PRDs** — every "we will" is a claim about feasibility; every effort
  estimate is a claim about scope; every "this is blocked by X" is a claim about X
  that is a claim, not a fact, until checked.
- **Analysis and query results** — the number is a claim about the population it
  was computed over. Attack the filter, the join grain, the null handling, and the
  time window before attacking the arithmetic.
- **Documentation** — every code example is a claim that it runs; every path is a
  claim that it exists; every flag is a claim that it is still supported.
- **Incident findings and postmortems** — "root cause" is the single most
  over-claimed phrase in engineering writing.

## Sizing the ledger

There is no right row count, but there is a wrong one. If the ledger has fewer
rows than the change has moving parts — files touched, behaviors altered, bullets
in the summary — enumeration stopped early. Go back to the surfaces table.

Ledger rows are cheap. Attacks are what cost. Enumerate generously, then triage
which rows are worth the expensive disproof and say in the report which rows you
chose not to attack — an unattacked row is unverified coverage, not a pass.
