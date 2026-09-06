---
name: prd-to-issues
description: Break a PRD into tracer-bullet vertical slices, output as either independently-grabbable GitHub issues with executor-ready bodies (default) or a phased implementation plan saved to docs/plans/ (`--plan`). Use when user wants to convert a PRD to issues, create implementation tickets, break down a PRD into work items, break down a PRD into an implementation plan, plan phases from a PRD, or mentions "tracer bullets".
---

# PRD to Issues

Break a PRD into vertical slices (tracer bullets), each a thin cut through every integration layer end-to-end rather than a horizontal slice of one layer. Default output is GitHub issues written to stand alone: an executor — human or autonomous agent — builds from the issue text, not from this conversation. `--plan` output is a single Markdown plan instead, for work the user intends to build themselves.

## Usage

- `/prd-to-issues` — locate the PRD via a GitHub issue, file dependency-ordered GitHub issues.
- `/prd-to-issues --plan` — locate the PRD from context, a paste, or a local file; write `docs/plans/<feature>.md`.

## Process

### 1. Locate the PRD

Default: ask the user for the PRD's GitHub issue number (or URL). If it is not already in your context window, fetch it with `gh issue view <number>` (with comments).

`--plan`: filing an issue is not required. If the PRD isn't already in the conversation, ask the user to paste it or point you to a local file.

### 2. Explore the codebase

If you have not already explored the codebase, do so to understand the current architecture, existing patterns, and integration layers.

### 3. Identify durable architectural decisions (`--plan` only)

Before slicing, identify high-level decisions unlikely to change through implementation: route structures / URL patterns, database schema shape, key data models, authentication / authorization approach, third-party service boundaries. These go in the plan header so every phase can reference them. Issue mode skips this step — each issue references the PRD directly instead.

### 4. Draft vertical slices

<vertical-slice-rules>
- Each slice delivers a narrow but COMPLETE path through every layer (schema, API, UI, tests)
- A completed slice is demoable or verifiable on its own
- Prefer many thin slices over few thick ones
- Default: slices may be HITL (needs human interaction — an architectural decision, a design review) or AFK (implementable and mergeable without one); prefer AFK where possible. An AFK slice is one concern with clear acceptance criteria; if it needs a new module or spans multiple concerns, mark it HITL or split it.
- `--plan`: do NOT name specific files or functions likely to change as later phases land. DO pin durable decisions — route paths, schema shapes, data model names.
</vertical-slice-rules>

### 5. Quiz the user

Present the proposed breakdown as a numbered list. For each slice show a **Title** and the **user stories** it covers; default mode also shows **Type** (HITL / AFK) and **Blocked by**.

Ask the user:

- Does the granularity feel right? (too coarse / too fine)
- Should any slices be merged or split further?
- Default only: Are the dependency relationships correct? Are the correct slices marked HITL and AFK?

Iterate until the user approves the breakdown.

### 6. Produce the output

**Default — create the GitHub issues.** For each approved slice, create a GitHub issue using `gh issue create`. Use the issue body template below. Create issues in dependency order (blockers first) so you can reference real issue numbers in the "Blocked by" field.

<issue-template>
## Parent PRD

#<prd-issue-number>

## Problem

What this slice delivers and why it matters — the end-to-end behavior, not layer-by-layer implementation. Reference specific sections of the parent PRD rather than duplicating content.

## Proposed behavior

Concrete enough to build cold: exact commands, messages, flags, or UI states where relevant. The executor gets this body, not the planning conversation — no "as discussed" references.

## Acceptance criteria

- [ ] Criterion 1
- [ ] Criterion 2
- [ ] Tests cover the new behavior (every slice MUST include a test criterion)

## Budget

~N units of work · one line of sizing rationale.

## Blocked by

- Blocked by #<issue-number> (if any)

Or "None - can start immediately" if no blockers.

## User stories addressed

Reference by number from the parent PRD:

- User story 3
- User story 7

</issue-template>

If the target repo has pipeline labels (e.g. `proposed`, `afk-sized`), apply them to AFK slices so the autonomous pipeline can pick them up; otherwise plain issues are fine — the body shape carries the contract.

Do NOT close or modify the parent PRD issue.

**`--plan` — write the plan file.** Create `docs/plans/` if it doesn't exist. Write the plan as a Markdown file named after the feature (e.g. `docs/plans/user-onboarding.md`), a process directory that `repo-docs` never classifies or moves. Use the template at [references/plan-template.md](references/plan-template.md).
