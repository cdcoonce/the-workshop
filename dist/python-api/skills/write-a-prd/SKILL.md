---
name: write-a-prd
description: Create a PRD through user interview, codebase exploration, and module design, then submit as a GitHub issue. Use when user wants to write a PRD, create a product requirements document, or plan a new feature.
---

This skill will be invoked when the user wants to create a PRD. You may skip steps if you don't consider them necessary.

**IMPORTANT: Use the `AskUserQuestion` tool for ALL user-facing questions throughout this skill.** Structure every question with clear options, descriptions, and appropriate use of multiSelect. This replaces plain-text questions — never ask a question via text output when `AskUserQuestion` can be used instead. Use text output only for sharing findings, summaries, or context that doesn't require a decision.

1. Use `AskUserQuestion` to gather the problem description. Ask about:
   - The problem domain (header: "Domain")
   - Whether they have existing solution ideas (header: "Ideas")
   
   Follow up with additional `AskUserQuestion` calls to drill into specifics based on their answers. Use the `preview` field when presenting concrete alternatives (e.g., different architectural approaches).

2. Explore the repo to verify their assertions and understand the current state of the codebase.

3. Interview the user relentlessly about every aspect of this plan until you reach a shared understanding. Walk down each branch of the design tree, resolving dependencies between decisions one-by-one.

   Use `AskUserQuestion` for each decision point:
   - Batch related questions (up to 4) into a single `AskUserQuestion` call when they are independent of each other.
   - Use `multiSelect: true` when choices are not mutually exclusive (e.g., "Which of these concerns apply?").
   - Use the `preview` field to show concrete alternatives side-by-side (e.g., API shapes, schema options, data flow diagrams).
   - When a decision depends on a previous answer, ask it in a follow-up call, not the same batch.

4. Sketch out the major modules you will need to build or modify to complete the implementation. Actively look for opportunities to extract deep modules that can be tested in isolation.

A deep module (as opposed to a shallow module) is one which encapsulates a lot of functionality in a simple, testable interface which rarely changes.

Use `AskUserQuestion` to confirm module design:
- Present the proposed modules and ask if they match expectations (header: "Modules").
- Ask which modules need tests using `multiSelect: true` (header: "Testing"), listing each module as an option with a description of what would be tested.

5. Once you have a complete understanding of the problem and solution, use the template below to write the PRD. The PRD should be submitted as a GitHub issue.

<prd-template>

## Problem Statement

The problem that the user is facing, from the user's perspective.

## Solution

The solution to the problem, from the user's perspective.

## User Stories

A LONG, numbered list of user stories. Each user story should be in the format of:

1. As an <actor>, I want a <feature>, so that <benefit>

<user-story-example>
1. As a mobile bank customer, I want to see balance on my accounts, so that I can make better informed decisions about my spending
</user-story-example>

This list of user stories should be extremely extensive and cover all aspects of the feature.

## Implementation Decisions

A list of implementation decisions that were made. This can include:

- The modules that will be built/modified
- The interfaces of those modules that will be modified
- Technical clarifications from the developer
- Architectural decisions
- Schema changes
- API contracts
- Specific interactions

Do NOT include specific file paths or code snippets. They may end up being outdated very quickly.

## Testing Decisions

A list of testing decisions that were made. Include:

- A description of what makes a good test (only test external behavior, not implementation details)
- Which modules will be tested
- Prior art for the tests (i.e. similar types of tests in the codebase)

## Out of Scope

A description of the things that are out of scope for this PRD.

## Further Notes

Any further notes about the feature.

</prd-template>
