---
name: mr-review-fixes
description: Use when a user says an MR, PR, merge request, or pull request has review feedback, review comments, changes requested, an approval blocker, or asks to see what needs to be fixed, answered, or replied to after review. Covers reading review threads, triaging findings, landing the fix, and replying to the reviewer in-thread on GitLab and GitHub.
---

# MR Review Fixes

Use this skill when the user wants review feedback inspected, fixed, and answered. This is not a reviewer packet, code review, or issue triage workflow; the artifact already exists and the job is to land the smallest correct follow-up change and close the loop with the reviewer.

## Intent

Turn a human reviewer's comments into a verified branch update and an in-thread reply for every finding.

NO REVIEW-FEEDBACK REQUEST BECOMES A REVIEW PACKET UNLESS THE USER ASKS FOR A PACKET.

Default to acting: read the threads keeping each finding's discussion ID, give every finding a disposition before writing code, patch the MR branch without disturbing unrelated local changes, test the reviewed behavior, then push, watch CI, and answer the reviewer.

**Check each finding against the current head before fixing it.** A review states what was true at the commit it cites; the fix may have landed since, leaving the MR blocked on something that no longer reproduces. Fetch before trusting a local branch as head — a stale local checkout silently re-runs the cited case against an old commit, which can misreport a live finding as already fixed. When the branch has moved on, invoke the `stale-artifact-sweep` skill if available, otherwise re-run the cited case at head yourself. Only ever claim a finding is resolved on the strength of a re-run, never a guess.

## Trigger Guard

Choose this skill over review-packet or review skills on phrases like "has a review in", "changes requested", "see what needs to be fixed", "fix the review comments", "address MR feedback", "reply to the review", "answer the reviewer", "respond to the comments", "last outstanding MR review".

Do not create a reviewer walkthrough unless the user explicitly asks for a packet, walkthrough, or reading guide.

## Pressure Checks

| Excuse                                                                  | Reality                                                                        |
| ----------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| "The user mentioned MR review, so the MR packet skill is close enough." | A packet helps a reviewer read a large diff; review feedback asks for fixes.   |
| "I should inspect everything first and decide later."                   | The first routing decision determines whether you create docs or patch code.   |
| "The existing review text is long, so it needs a packet."               | Long feedback is still feedback; extract findings and fix blockers.            |
| "The finding is wrong, so I'll just quietly do it their way."           | A review finding is a claim, not a fact. Contest it with evidence, or fix it.  |
| "The fix is obviously right, so I can reply before CI finishes."        | A reply cites a SHA. An unverified SHA makes the reply a guess, in public.     |
| "The thread is handled, so I'll resolve it and move on."                | Resolve is only for findings you fixed and verified green. Nothing else.       |
| "The user says all of it is dealt with, so every disposition is Fix."   | A user's "dealt with" is a status report, not a triage record. Reconstruct it. |

Red flags:

- You are drafting `docs/mr-reviews/` before reading the requested review findings.
- You are asking who the reviewer packet audience is.
- You are summarizing the MR instead of classifying review findings.
- You are posting a reply while the pipeline for that SHA is red, pending, or unpushed.
- You are resolving a thread you argued with, deferred, or never gave a disposition.

After 2 failed attempts to access platform review feedback, continue from pasted or local review context and name the access gap. Never invent discussion IDs; without them, draft replies for the user to post manually and say so.

## Process

**1. Locate** — find the active repo and MR/PR branch. Check worktree state before edits; do not disturb unrelated user changes.

**2. Read** — fetch the review threads, one record per finding: discussion ID, author, file/line, quoted text, resolved state. [references/respond.md](references/respond.md) has the exact GitLab and GitHub commands. Without network access, use pasted review text or local MR metadata already in context.

**3. Triage** — every finding gets a severity and a disposition, both, for all findings, before any code changes.

Severity: **Blocking** (must fix before merge), **Warning** (fix when local and low risk), **Suggestion/Low** (fix only when it falls out of the blocking change).

Disposition. **No finding gets a disposition, including Fix, until its claim has been checked at head** — run the query, execute the case, read the code. A finding that sounds authoritative and specific is still a claim; agreeing without checking is the same failure as disputing without checking, and it is the more common one.

- **Fix** — checked, correct, in scope.
- **Contested** — checked, and the claim does not hold. Gather the evidence that refutes it (a test run, a code citation, a query result). Never silently comply with a finding you have shown to be wrong; that encodes the error and hides the disagreement.
- **Acknowledged** — a Suggestion/Low finding that is valid but not being taken here. **Never use Acknowledged when the reason is scope or effort — that is Deferred, and Deferred costs an issue.** Severity is your own call, so this is the seam where a large finding gets quietly downgraded to avoid filing one. Otherwise: reply saying so; do not fix, file, or resolve.
- **Deferred** — correct, but far larger than this MR's scope. File a follow-up issue on the repository that owns the root cause, which is not always this one, and carry the issue link into the reply.
- **Stale** — no longer reproduces at head. Prove it with a re-run before claiming it.

Present the triage table to the user. It is an FYI, not a gate — continue into step 4 without waiting. The only confirmation this workflow waits on is the batched reply approval in step 6.

**An unknown disposition is not Fix.** Entering mid-workflow — the user says the findings are already handled, or the session has no triage record — reconstruct each thread's disposition from the thread text and the landed commits, or ask. Until a thread has a recorded disposition it cannot be replied to as fixed and cannot be resolved. Audit those landed commits, not just their existence: a fix with no regression test is one step 4 would have rejected, and a green pipeline over an untested change proves nothing about the finding. Add the missing test before replying.

**4. Fix** — TDD discipline, **one commit per finding**: failing regression test for the reviewed gap first, then the smallest production change, then commit that finding alone so a reviewer can verify one finding by reading one commit. Keep scope to the MR's stated intent.

**5. Verify — the reply gate.** Unconditional. No reply and no resolve happens until it passes.

- Run targeted tests for changed behavior and lint/format over touched files.
- If docs or generated artifacts are part of the repo contract, regenerate them.
- Push the branch, then watch the pipeline for the pushed head SHA and confirm every job is green.

If the pipeline is red, still pending, or absent for that SHA: stop, post nothing, and name the failing or missing job. An absent pipeline usually means the commit was never pushed; it is never a pass. Fix, re-push, watch again. A pre-existing failure unrelated to your change still blocks the automated reply — report it and let the user decide.

Per-finding commits are verified in aggregate at head, so a reply cites its own finding's commit **and** states that head is green; it never claims the individual commit was independently piped. **When a finding produced no commit** — everything is Contested, Stale, or Acknowledged, so there is nothing to push — the gate is satisfied by confirming the existing head is pushed and green, and the reply says no code changed. Never present a pipeline from an earlier head as verification of the current one.

**6. Respond**

- Draft one reply per discussion thread. A single summary note never stands in for per-thread replies.
- Show the user every drafted reply at once and get one batched confirmation before posting anything.
- Post each reply into its own thread using the discussion ID. A bare `glab mr note` or top-level PR comment is not a thread reply.
- **Resolve only threads whose disposition was Fix and whose fix is verified green.** Never resolve a Contested, Deferred, Stale, or Acknowledged thread — those are the reviewer's call, and resolving them buries the disagreement.

Reply content, per finding: the disposition, what changed, the commit SHA, the test or check that proves it, plus refuting evidence for Contested and the issue link for Deferred.

**7. Summarize** — each finding with its disposition and commit; tests/checks run and the pipeline result; every reply posted and thread resolved; any finding intentionally left unfixed and why.

## Boundaries

- Do not open a new issue except for a Deferred finding or when the review asks for backlog tracking.
- Do not rewrite the MR description unless the implementation changes the user-facing summary.
- Do not merge or approve.
- Do not resolve threads outside the Fix-and-green rule above.
- Do not run broad cleanup unrelated to the review.
