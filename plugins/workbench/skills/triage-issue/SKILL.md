---
name: triage-issue
description: Use when user reports a bug, wants to file an issue, mentions "triage", or wants to investigate and plan a fix for a problem. Finds the root cause and files a GitHub issue with a TDD-based fix plan.
---

# Triage Issue

Investigate a reported problem, find its root cause, and create a GitHub issue with a TDD fix plan. This is a mostly hands-off workflow - minimize questions to the user.

## Process

### 1. Capture the problem

Get a brief description of the issue from the user. If they haven't provided one, ask ONE question: "What's the problem you're seeing?" — no follow-ups; start investigating immediately. If the report comes from a recorded artifact rather than the user's live observation — an existing issue, a TODO, a note from a past session — reproduce it against current code first (`stale-artifact-sweep`); a report can be fixed, closed, or superseded between filing and now.

### 2. Explore and diagnose

Use the Agent tool with subagent_type=Explore to deeply investigate the codebase. Your goal is to find:

- **Where** the bug manifests (entry points, UI, API responses)
- **What** code path is involved (trace the flow)
- **Why** it fails (the root cause, not just the symptom)
- **What** related code exists (similar patterns, tests, adjacent modules)

Look at related source files and their dependencies, existing tests (what's tested, what's missing), recent changes to affected files (`git log` on relevant files), error handling in the code path, and similar patterns elsewhere in the codebase that work correctly.

### 3. Identify the fix approach

Based on your investigation, determine:

- The minimal change needed to fix the root cause
- Which modules/interfaces are affected
- What behaviors need to be verified via tests
- Whether this is a regression, missing feature, or design flaw

### 4. Design TDD fix plan

Create a concrete, ordered list of RED-GREEN cycles. Each cycle is one vertical slice:

- **RED**: Describe a specific test that captures the broken/missing behavior
- **GREEN**: Describe the minimal code change to make that test pass

Rules:

- Tests verify behavior through public interfaces, not implementation details
- One test at a time, vertical slices (NOT all tests first, then all code)
- Each test should survive internal refactors
- Include a final refactor step if needed
- **Durability**: Only suggest fixes that would survive radical codebase changes. Describe behaviors and contracts, not internal structure. Tests assert on observable outcomes (API responses, UI state, user-visible effects), not internal state. A good suggestion reads like a spec; a bad one reads like a diff.

### 5. Create the GitHub issue

Create a GitHub issue using `gh issue create` with the template below. Do NOT ask the user to review before creating - just create it and share the URL.

<issue-template>

## Problem

A clear description of the bug or issue: what happens (actual), what should happen (expected), and how to reproduce (if applicable).

## Root Cause Analysis

Describe what you found during investigation:

- The code path involved
- Why the current code fails
- Any contributing factors

Do NOT include specific file paths, line numbers, or implementation details that couple to current code layout. Describe modules, behaviors, and contracts instead. The issue should remain useful even after major refactors.

## TDD Fix Plan

A numbered list of RED-GREEN cycles:

1. **RED**: Write a test that [describes expected behavior]
   **GREEN**: [Minimal change to make it pass]

2. **RED**: Write a test that [describes next behavior]
   **GREEN**: [Minimal change to make it pass]

...

**REFACTOR**: [Any cleanup needed after all tests pass]

## Acceptance Criteria

- [ ] Criterion 1
- [ ] Criterion 2
- [ ] All new tests pass
- [ ] Existing tests still pass

## Budget

~N units of work · one line of sizing rationale.
</issue-template>

The issue body must stand alone: an executor — human or autonomous agent — builds from the issue text, not from this conversation. No "as discussed" references. If the target repo has autonomous-agent labels (e.g. `proposed`, `afk-sized`), apply them to single-concern fixes; otherwise plain issues are fine.

After creating the issue, print the issue URL and a one-line summary of the root cause.
