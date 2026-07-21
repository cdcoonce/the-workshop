# MR Review Fixes Pressure Tests

## Scenario 1: Review Feedback Misrouted To Packet

Prompt:

> AMRT has a review in for MR!83. Please take a look and see what needs to be fixed.

Pressures:

- The phrase "MR review" overlaps with reviewer-packet wording.
- The repo has an existing `vault-mr-review-packet` skill with MR triggers.
- The user asks for inspection before implementation, making a summary artifact tempting.

Expected behavior:

- Select `mr-review-fixes`.
- Read the MR review comments or supplied review text.
- Classify blocking/warning/suggestion findings.
- Fix blocking findings on the MR branch with tests.
- Do not invoke reviewer-packet scoping or create `docs/mr-reviews/`.

Observed no-skill RED baseline:

- The agent selected `vault-ops:vault-mr-review-packet`.
- It announced "inspect MR!83 review context and identify required fixes."
- It began reading packet-generation instructions whose workflow is to scope audience, decide packet location, and draft a reviewer guide.
- This was wrong because the user wanted review feedback fixed, not an async reviewer walkthrough.

Regression target:

- The skill must make "has a review in" and "what needs to be fixed" stronger triggers than generic "MR review" packet language.
