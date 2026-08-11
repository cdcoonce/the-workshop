---
name: grill-me
description: Interview the user relentlessly about a plan or design until reaching shared understanding, resolving each branch of the decision tree. Use when user wants to stress-test a plan, get grilled on their design, or mentions "grill me".
---

# Grill Me — Shared Understanding Through Systematic Interrogation

## Philosophy

The purpose of grilling is to build **shared understanding** between the agent and the user. Every plan contains implicit assumptions, unstated constraints, and ambiguous decisions. Grilling walks through every branch of the decision tree, one by one, until both parties are fully aligned. The goal is zero unexamined assumptions before implementation begins.

## Pre-Interrogation Setup

Before asking any questions, build context silently: read the plan or design document, explore the codebase for existing patterns and constraints, check recent git history for context, and read project.md and CLAUDE.md for conventions. Then present a brief summary of what you understand, organized by interrogation domain, so the user can correct major misunderstandings before branch-by-branch questioning begins.

## Interrogation Domains

Work through the domains defined in [references/interrogation-domains.md](references/interrogation-domains.md). Adapt the order to the plan — start with the domain most central to what's being built and work outward. Skip domains that are clearly irrelevant.

## Interrogation Process

1. Read and summarize your understanding of the plan; the user confirms or corrects it.
2. For each interrogation domain, ordered by relevance: identify all decision points and assumptions in that domain, group related ones into batches of up to 4 questions, invoke one `AskUserQuestion` call per batch (recommendation first, every selected option recorded).
3. After resolving all points in a domain, summarize its decisions as rows in the decisions log below.
4. After all domains are covered: present the complete decisions log, flag any unresolved or deferred items, and ask if any domain needs revisiting.

Decisions log format:

| #   | Domain | Topic | Decision | Notes                                                |
| --- | ------ | ----- | -------- | ---------------------------------------------------- |
| 1   | Intent | Goal  | Other    | Internal dashboard for ops team, not customer-facing |

## Directives

1. **Use `AskUserQuestion` for every question.** Never output a question as plain text.
2. **Batch within domains.** Up to 4 related questions from the same domain per call; never mix domains in one call.
3. **Lead with your recommendation.** First option always carries `(Recommended)` in its label.
4. **Explore before asking.** If the codebase, docs, or existing patterns answer it, don't ask — only ask what requires the user's judgment.
5. **Resolve dependencies in order.** Identify the dependency chain among decisions and resolve upstream ones first. State the dependency (or "No dependencies") in each question's text.
6. **Track everything.** Maintain a decisions log table (domain, topic, selected option label, custom text if 'Other') in conversation context — no file I/O.
7. **No assumptions survive.** Surface anything implied but unstated; confirm anything that seems obvious. Shared understanding means explicit agreement, not comfortable silence.
8. **Stay concrete.** Frame questions around specific behaviors, data flows, and user-visible outcomes — not abstractions. "How should we handle errors?" is too vague; "When the Oura API returns a 429, retry with backoff or queue for next run?" is specific.
9. **Respect tool constraints.** 2-4 options per question, headers max 12 characters, `multiSelect: true` only when options aren't mutually exclusive.
10. **Filter options.** When more than 4 valid choices exist, present the 3 most relevant based on codebase context; the user can pick "Other" for anything else.
11. **Show your work.** If a recommendation comes from the codebase, cite the file and line.
12. **Accept the answer.** Record the decision and move on — don't re-litigate unless a later decision conflicts with it.

See [references/interrogation-domains.md](references/interrogation-domains.md) for full `AskUserQuestion` JSON examples — single question, batched questions, and preview usage.

## Previews

Use the `preview` field on options when the user needs to visually compare concrete artifacts — code snippets, architecture diagrams, schema shapes, or configuration examples. Previews render as markdown in a monospace box with side-by-side comparison. Previews are single-select only (`multiSelect: false`); if you need multi-select, omit previews and use descriptions instead.

## Fallback (no `AskUserQuestion` available)

If `AskUserQuestion` is not available in the runtime environment, fall back to this text format:

**[Header] — [Topic]**

[Clear statement of the question]

**Recommended:** [Your recommendation and why]

**Alternatives:**

- (A) [Option] — [trade-off]
- (B) [Option] — [trade-off]

## When to Stop

The grill is complete when:

- Every relevant interrogation domain has been covered
- All decision branches have been resolved or explicitly deferred
- The user confirms shared understanding
