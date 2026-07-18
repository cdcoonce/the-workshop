# Required Outputs

All of these sections are mandatory deliverables of the review.

## "NOT in scope" section

List work considered and explicitly deferred, with one-line rationale each.

## "What already exists" section

List existing code/flows that partially solve sub-problems and whether the plan reuses them.

## "Dream state delta" section

Where this plan leaves us relative to the 12-month ideal.

## Error & Rescue Registry (from Section 2)

Complete table of every method that can fail, every exception class, handled status, handling action, user impact.

## Failure Modes Registry

```
  CODEPATH | FAILURE MODE   | HANDLED? | TEST? | USER SEES?     | LOGGED?
  ---------|----------------|----------|-------|----------------|--------
```

Any row with HANDLED=N, TEST=N, USER SEES=Silent → **CRITICAL GAP**.

## Deferred Work Items

Present each potential deferred item as its own individual AskUserQuestion. Never batch — one per question. Never silently skip this step.

For each item, describe:

- **What:** One-line description of the work.
- **Why:** The concrete problem it solves or value it unlocks.
- **Pros:** What you gain by doing this work.
- **Cons:** Cost, complexity, or risks of doing it.
- **Context:** Enough detail that someone picking this up in 3 months understands the motivation, the current state, and where to start.
- **Effort estimate:** S/M/L/XL
- **Priority:** P1/P2/P3
- **Depends on / blocked by:** Any prerequisites or ordering constraints.

Then present options: **A)** Add to `docs/plans/` as a tracked plan **B)** Skip — not valuable enough **C)** Build it now in this PR instead of deferring.

## Delight Opportunities (EXPANSION mode only)

Identify at least 5 "bonus chunk" opportunities (<30 min each) that would make users think "oh nice, they thought of that." Present each delight opportunity as its own individual AskUserQuestion. Never batch them. For each one, describe what it is, why it would delight users, and effort estimate. Then present options: **A)** Add to `docs/plans/` as a vision item **B)** Skip **C)** Build it now in this PR.

## Diagrams (mandatory, produce all that apply)

1. System architecture
2. Data flow (including shadow paths)
3. State machine
4. Error flow
5. Deployment sequence
6. Rollback flowchart

## Stale Diagram Audit

List every ASCII diagram in files this plan touches. Still accurate?

## Completion Summary

```
  +====================================================================+
  |            MEGA PLAN REVIEW — COMPLETION SUMMARY                   |
  +====================================================================+
  | Mode selected        | EXPANSION / HOLD / REDUCTION                |
  | System Audit         | [key findings]                              |
  | Step 0               | [mode + key decisions]                      |
  | Section 1  (Arch)    | ___ issues found                            |
  | Section 2  (Errors)  | ___ error paths mapped, ___ GAPS            |
  | Section 3  (Security)| ___ issues found, ___ High severity         |
  | Section 4  (Data/UX) | ___ edge cases mapped, ___ unhandled        |
  | Section 5  (Quality) | ___ issues found                            |
  | Section 6  (Tests)   | Diagram produced, ___ gaps                  |
  | Section 7  (Perf)    | ___ issues found                            |
  | Section 8  (Observ)  | ___ gaps found                              |
  | Section 9  (Deploy)  | ___ risks flagged                           |
  | Section 10 (Future)  | Reversibility: _/5, debt items: ___         |
  +--------------------------------------------------------------------+
  | NOT in scope         | written (___ items)                          |
  | What already exists  | written                                     |
  | Dream state delta    | written                                     |
  | Error/rescue registry| ___ methods, ___ CRITICAL GAPS              |
  | Failure modes        | ___ total, ___ CRITICAL GAPS                |
  | Deferred work items  | ___ items proposed                          |
  | Delight opportunities| ___ identified (EXPANSION only)             |
  | Diagrams produced    | ___ (list types)                            |
  | Stale diagrams found | ___                                         |
  | Unresolved decisions | ___ (listed below)                          |
  +====================================================================+
```

## Unresolved Decisions

If any AskUserQuestion goes unanswered, note it here. Never silently default.
