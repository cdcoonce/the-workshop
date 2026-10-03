# Gaps

Guarded behaviors that cannot be exercised as a single-prompt case, one line of reason each.

- three-attempt ceiling on a real barrier: every barrier in the settlement fixture is reachable, and tests.md records the ceiling as unfalsified, so a single-prompt case cannot make the agent reach it
- PLAUSIBLE ceiling for reasoning with no reproduction: all three planted defects reproduce in one command, so nothing is left for the agent to grade on reasoning alone
- refusing an author's pressure to approve without proof: A1 is a self-review with zero user turns, so no second party pushes for a yes or no
- refutation pass over surviving lens findings: A2 scores the lens agents' own findings, and the three refuters need a second dispatch that consumes those findings, which a single prompt per lens cannot exercise
- freeze the tree before dispatching the lenses: A2's diff and spec are two frozen files, so there is no live tree an edit could move mid-run and no way to break the rule
- zero findings read against the run journal: the inline run keeps no Workflow journal.jsonl, so the one-record-per-lens check has nothing to read, and a silent lens shows only as a missing transcript
- inverted bias for credential-exposure findings: the doctored diff carries no secret, token or live network call, so the credential lens (and its uphold-unless-impossible refuter) never fires
