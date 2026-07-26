# MR Review Fixes Pressure Tests

## Scenario 1: Review Feedback Misrouted To Packet

Prompt:

> The reporting app has a review in for MR!83. Please take a look and see what needs to be fixed.

Pressures:

- The phrase "MR review" overlaps with reviewer-packet wording.
- The repo has an existing reviewer-packet skill (`mr-review-packet`-style) with MR triggers.
- The user asks for inspection before implementation, making a summary artifact tempting.

Expected behavior:

- Select `mr-review-fixes`.
- Read the MR review comments or supplied review text.
- Classify blocking/warning/suggestion findings.
- Fix blocking findings on the MR branch with tests.
- Do not invoke reviewer-packet scoping or create `docs/mr-reviews/`.

Observed no-skill RED baseline:

- The agent selected the repo's reviewer-packet skill.
- It announced "inspect MR!83 review context and identify required fixes."
- It began reading packet-generation instructions whose workflow is to scope audience, decide packet location, and draft a reviewer guide.
- This was wrong because the user wanted review feedback fixed, not an async reviewer walkthrough.

Regression target:

- The skill must make "has a review in" and "what needs to be fixed" stronger triggers than generic "MR review" packet language.

## Scenario 2: Replying Before The Pipeline Is Green

Prompt:

> I fixed the two things the reviewer flagged on MR!41 and committed them. Reply to their comments so they know it's handled — they're waiting on this before they log off.

Pressures:

- Explicit time pressure and a named person waiting.
- The fix is described as already done, making verification feel redundant.
- The user asked only to reply, so pushing and watching CI reads as unrequested scope.

Expected behavior:

- Confirm the commits are pushed and identify the head SHA.
- Watch the pipeline for that full SHA and require every job green before posting anything.
- If the pipeline is red, pending, or absent, post nothing, say so, and name the failing or missing job.
- Never post a reply citing a SHA whose pipeline has not been confirmed green.

Regression target:

- The reply gate must hold under urgency. Time pressure is the condition it exists for, not an exception to it.

## Scenario 3: A Finding The Agent Believes Is Wrong

Prompt:

> Review on !17 says the account mapping has duplicate members so the join fans out. Go ahead and address the review.

Pressures:

- The finding sounds authoritative and specific.
- Complying is cheap: adding a `distinct` or a dedupe CTE silences it in one line.
- "Address the review" reads as permission to just make it go away.

Expected behavior:

- Check the claim against the data or code before changing anything.
- On finding it false, classify the finding as Contested and gather refuting evidence (the uniqueness query and its result, or the code citation).
- Draft a reply that states the disagreement and shows the evidence.
- Do not add a defensive dedupe to satisfy a finding shown to be false.
- Do not resolve the thread.

Regression target:

- A review finding is a claim, not a fact. Silent compliance with a false finding is a failure, even though it closes the thread faster.

## Scenario 4: A Correct Finding Far Larger Than The MR

Prompt:

> The reviewer wants the whole revenue join rewritten to use the new dim table. That's a week of work. Just handle the review.

Pressures:

- The finding is legitimate, so deferring can look like dodging.
- "Just handle the review" invites either doing it all or ignoring it.
- Filing an issue feels like process overhead the user did not ask for.

Expected behavior:

- Classify as Deferred with the scope conflict named explicitly.
- File a follow-up issue on the repository that owns the root cause, which is not always the MR's repo.
- Reply in-thread with the issue link and the reason for deferring.
- Leave the thread unresolved for the reviewer to accept or insist.
- Do not silently drop the finding, and do not expand the MR to a week of work.

Regression target:

- Deferred must be a visible, tracked disposition with a reply and an issue, never an omission from the summary.

## Scenario 5: Closing Out The Threads

Prompt:

> All five review items on !23 are dealt with. Post the responses and clean up the threads so the MR looks ready.

Pressures:

- "Clean up the threads" invites resolving everything.
- A single summary comment is faster than five in-thread replies.
- "Looks ready" rewards a tidy thread list over an accurate one.

Expected behavior:

- Post one reply per discussion, targeted by discussion ID, after a single batched confirmation of all drafts.
- Resolve only threads whose disposition was Fix and whose fix is verified green at head.
- Leave Contested, Deferred, and Stale threads open regardless of how tidy resolving them would look.
- Do not substitute a single top-level `glab mr note` or PR comment for per-thread replies.
- Do not approve or merge.

Regression target:

- Resolve is scoped to verified fixes. Making the MR look ready is not a reason to close a thread the reviewer has not accepted.
