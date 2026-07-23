---
name: request-refactor-plan
description: Use when user wants to plan a refactor, create a refactoring RFC, break a refactor into safe incremental steps, or find architectural improvement opportunities (deepening shallow modules, consolidating tightly-coupled code, making a codebase more testable or AI-navigable). Produces a detailed refactor plan with tiny commits, filed as a GitHub issue.
---

# Request Refactor Plan

Two entry modes, one output: a refactor RFC filed as a GitHub issue.

- **Directed mode** — the user already knows what they want refactored. Start at Step 1.
- **Discovery mode** — the user wants to _find_ refactoring opportunities ("improve the architecture", "make this more testable"). Start at Step 0, then continue from Step 4.

## Step 0: Discovery (only when the user has no specific target)

Explore the codebase like an AI would and let friction be the signal. A **deep module** (John Ousterhout, "A Philosophy of Software Design") has a small interface hiding a large implementation — deep modules are more testable, more AI-navigable, and let you test at the boundary instead of inside.

Use the Agent tool with subagent_type=Explore to navigate organically — no rigid heuristics — noting:

- Where does understanding one concept require bouncing between many small files?
- Where are modules so shallow the interface is nearly as complex as the implementation?
- Where have pure functions been extracted just for testability, while the real bugs hide in how they're called?
- Where do tightly-coupled modules create integration risk in the seams between them?
- Which parts of the codebase are untested, or hard to test?

Present a numbered list of deepening candidates. For each: the **cluster** of modules involved, **why they're coupled**, the **dependency category** (see [REFERENCE.md](REFERENCE.md)), and **test impact** (which existing tests boundary tests would replace). Do NOT propose interfaces yet — ask the user which candidate to pursue, then continue at Step 4 with that candidate as the problem.

For a chosen deepening candidate, consider spawning 3+ parallel sub-agents to design **radically different** interfaces (minimal / flexible / common-caller-optimized / ports-and-adapters), compare them in prose, and give an opinionated recommendation before planning commits.

## Directed mode

1. Ask the user for a long, detailed description of the problem they want to solve and any potential ideas for solutions.

2. Explore the repo to verify their assertions and understand the current state of the codebase.

3. Ask whether they have considered other options, and present other options to them.

4. Interview the user about the implementation. Be extremely detailed and thorough.

5. Hammer out the exact scope of the implementation. Work out what you plan to change and what you plan not to change.

6. Look in the codebase to check for test coverage of this area of the codebase. If there is insufficient test coverage, ask the user what their plans for testing are. For module-deepening refactors, follow the **replace, don't layer** testing strategy in [REFERENCE.md](REFERENCE.md).

7. Break the implementation into a plan of tiny commits. Remember Martin Fowler's advice to "make each refactoring step as small as possible, so that you can always see the program working."

8. Create a GitHub issue with the refactor plan. Use the following template for the issue description:

<refactor-plan-template>

## Problem Statement

The problem that the developer is facing, from the developer's perspective.

## Solution

The solution to the problem, from the developer's perspective.

## Commits

A LONG, detailed implementation plan. Write the plan in plain English, breaking down the implementation into the tiniest commits possible. Each commit should leave the codebase in a working state.

## Decision Document

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

A description of the things that are out of scope for this refactor.

## Further Notes (optional)

Any further notes about the refactor.

</refactor-plan-template>
