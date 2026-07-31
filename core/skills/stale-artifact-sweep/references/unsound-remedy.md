# Sound finding, unsound remedy

Every verdict above asks whether the record went **stale**. A finding can be perfectly
current — reproduces on head, cites the right files, nothing moved under it — and still be
**wrong on the merits**. `STILL_VALID` then reads as authorization to implement it, which is
how a review hands you a defect.

Two failure shapes, both seen in one curve-audit review:

- **The finding quotes a comment as its contract.** A comment describing a column contradicted
  the module that defines it; the finding believed the consumer over the producer. Check the
  definition, not the description — and when two sources disagree, that disagreement is the
  finding.
- **The evidence was built from the misreading.** A "confirmed by execution" note turned out to
  be a fixture that encoded the wrong reading, so running it could only confirm it. Executing a
  claim is not the same as executing the *right* claim.

To settle it, **apply the prescribed fix and watch what the suite does** — that is
`detector-teeth-check`, not a second copy of it here. If the prescribed fix turns a failing case
green, the remedy is unsound however sound the complaint was. Record `REMEDY_UNSOUND` with the
mutation result as evidence, say what the finding got right, and propose the corrected fix
separately.

Cheap tell: a finding whose scale premise is a number nobody measured. Check the number first —
it is the fastest way to find out whether anyone verified the rest.
