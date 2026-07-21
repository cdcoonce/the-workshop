---
name: mr-review-fixes
description: Use when a user says an MR, PR, merge request, or pull request has review feedback, review comments, changes requested, an approval blocker, or asks to see what needs to be fixed after review. Covers GitLab and GitHub review-followup work.
---

# MR Review Fixes

Use this skill when the user wants review feedback inspected and fixed. This is not a reviewer packet, code review, or issue triage workflow; the artifact already exists and the job is to land the smallest correct follow-up change.

## Intent

Turn review feedback into a verified branch update.

NO REVIEW-FEEDBACK REQUEST BECOMES A REVIEW PACKET UNLESS THE USER ASKS FOR A PACKET.

Default to acting:

- Read the review feedback from the platform if possible.
- Identify blocking findings first, then warnings that are cheap and relevant.
- Patch the MR branch directly, preserving unrelated local changes.
- Add or adjust tests for the reviewed behavior.
- Run the narrowest useful verification.
- Report what was fixed and what remains.

## Trigger Guard

Choose this skill instead of review-packet or review skills when the user says phrases like:

- "has a review in"
- "changes requested"
- "see what needs to be fixed"
- "fix the review comments"
- "address MR feedback"
- "last outstanding MR review"

Do not create a reviewer walkthrough unless the user explicitly asks for a packet, walkthrough, or reading guide.

## Pressure Checks

| Excuse | Reality |
| --- | --- |
| "The user mentioned MR review, so the MR packet skill is close enough." | A packet helps a reviewer read a large diff; review feedback asks for fixes. |
| "I should inspect everything first and decide later." | The first routing decision determines whether you create docs or patch code. |
| "The existing review text is long, so it needs a packet." | Long feedback is still feedback; extract findings and fix blockers. |

Red flags:

- You are drafting `docs/mr-reviews/` before reading the requested review findings.
- You are asking who the reviewer packet audience is.
- You are summarizing the MR instead of classifying review findings.

After 2 failed attempts to access platform review feedback, continue from pasted or local review context and name the access gap.

## Process

1. Locate the active repo and MR/PR branch.
2. Check worktree state before edits; do not disturb unrelated user changes.
3. Fetch or read review feedback from the platform. If network access is unavailable, use any pasted review text or local MR metadata already in context.
4. Classify feedback:
   - Blocking: must fix before merge.
   - Warning: fix when local and low risk.
   - Suggestion/Low: only fix when it naturally falls out of the blocking change.
5. Implement with TDD discipline:
   - Add the failing regression test for the reviewed gap first.
   - Make the smallest production change.
   - Keep scope to the MR's stated intent.
6. Verify:
   - Run targeted tests for changed behavior.
   - Run lint/format checks that cover touched files.
   - If docs or generated artifacts are part of the repo contract, regenerate them.
7. Summarize:
   - Name each review finding fixed.
   - Name tests/checks run.
   - Call out any review item intentionally left unfixed.

## Boundaries

- Do not open a new issue unless the review asks for backlog tracking.
- Do not rewrite the MR description unless the implementation changes the user-facing summary.
- Do not merge, approve, or resolve review threads unless explicitly asked.
- Do not run broad cleanup unrelated to the review.
