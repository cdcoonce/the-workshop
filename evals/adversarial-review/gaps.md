# Gaps

Guarded behaviors that cannot be exercised as a single-prompt case, one line of reason each.

- refutation pass over surviving lens findings: A2 scores the lens agents' own findings, and the three refuters need a second dispatch that consumes those findings, which a single prompt per lens cannot exercise
- freeze the tree before dispatching the lenses: A2's diff and spec are two frozen files, so there is no live tree an edit could move mid-run and no way to break the rule
- zero findings read against the run journal: the inline run keeps no Workflow journal.jsonl, so the one-record-per-lens check has nothing to read, and a silent lens shows only as a missing transcript
- inverted bias for credential-exposure findings: the doctored diff carries no secret, token or live network call, so the credential lens (and its uphold-unless-impossible refuter) never fires
