---
name: grill-me
description: Interview the user relentlessly about a plan or design until reaching shared understanding, resolving each branch of the decision tree. Use when user wants to stress-test a plan, get grilled on their design, or mentions "grill me".
---

# Grill Me — Shared Understanding Through Systematic Interrogation

## Philosophy

The purpose of grilling is to build **shared understanding** between the agent and the user. Every plan contains implicit assumptions, unstated constraints, and ambiguous decisions. Grilling walks through every branch of the decision tree, one by one, until both parties are fully aligned.

The goal is zero unexamined assumptions before implementation begins.

## Prime Directives

1. **Use AskUserQuestion for every question.** All interrogation questions must go through the `AskUserQuestion` tool. Never output a question as plain text.
2. **Batch within domains.** Group up to 4 related questions within the same interrogation domain into a single `AskUserQuestion` call. Never mix questions from different domains in one call.
3. **Lead with your recommendation.** Your recommended answer is always the first option, with `(Recommended)` appended to the label.
4. **Explore before asking.** If a question can be answered by reading the codebase, reading docs, or checking existing patterns — do that instead of asking. Only ask the user about decisions that require their judgment.
5. **Resolve dependencies in order.** Some decisions depend on others. Identify the dependency chain and resolve upstream decisions first.
6. **Track everything with structured records.** Maintain a decisions log as a structured table. For each resolved question, record: domain, topic (header), selected option label, and any custom text if 'Other' was chosen. Present the log in conversation context — no file I/O.
7. **No assumptions survive.** If something is implied but not stated, surface it. If something seems obvious, confirm it. Shared understanding means explicit agreement, not comfortable silence.
8. **Stay concrete.** Frame questions around specific behaviors, data flows, and user-visible outcomes — not abstract concepts.

## Pre-Interrogation Setup

Before asking any questions, build context silently:

1. Read the plan or design document the user wants grilled
2. Explore the codebase for existing patterns, constraints, and relevant code
3. Check recent git history for context on current work
4. Read project.md and CLAUDE.md for project conventions

Then present a brief summary of what you understand so far, organized by the interrogation domains. This gives the user a chance to correct major misunderstandings before diving into branch-by-branch questioning.

## Interrogation Domains

Work through the domains defined in [references/interrogation-domains.md](references/interrogation-domains.md). Adapt the order to the plan — start with the domain most central to what's being built and work outward. Skip domains that are clearly irrelevant.

## Interrogation Process

```
1. Read and summarize your understanding of the plan
2. User confirms or corrects the summary
3. For each interrogation domain (ordered by relevance):
   a. Identify all decision points and assumptions in this domain
   b. Group related decision points into batches of up to 4 questions
   c. For each batch, invoke a single AskUserQuestion call
      (recommendation first for each question). Record all selected options.
   d. After resolving all points in a domain, summarize decisions made
      Present the domain's decisions as rows in the structured table format.
4. After all domains are covered:
   - Present the complete decisions log as a structured table:
     | # | Domain | Topic | Decision | Notes |
     |---|--------|-------|----------|-------|
     | 1 | Intent | Goal  | Other | Internal dashboard for ops team, not customer-facing |
   - Flag any unresolved or deferred items
   - Ask if any domain needs revisiting
```

## Question Format

Every question MUST be asked via the `AskUserQuestion` tool. Structure each call as follows:

```json
{
  "question": "When the Oura API returns a 429, how should we handle rate limiting?",
  "header": "Rate Limits",
  "options": [
    {
      "label": "Exponential backoff (Recommended)",
      "description": "Retry with exponential backoff (1s, 2s, 4s). Handles transient limits gracefully and matches the retry pattern already used in src/api_client.py."
    },
    {
      "label": "Queue for next run",
      "description": "Skip the request and add it to the next scheduled run. Simpler but delays data by one cycle."
    }
  ],
  "multiSelect": false
}
```

**Depends on:** State any prior decisions this builds on in the `question` text, or note "No dependencies" if standalone.

### Batched questions example

```json
{
  "questions": [
    {
      "question": "What is the primary deployment target?",
      "header": "Deploy",
      "options": [
        {
          "label": "Docker + ECS (Recommended)",
          "description": "Matches existing infra. Deployment pipeline already exists."
        },
        {
          "label": "Kubernetes",
          "description": "More flexible but requires new infra setup."
        },
        {
          "label": "Serverless",
          "description": "Lower ops burden but cold start latency concerns."
        }
      ],
      "multiSelect": false
    },
    {
      "question": "Which monitoring approaches should we include?",
      "header": "Monitoring",
      "options": [
        {
          "label": "Structured logging (Recommended)",
          "description": "JSON logs to CloudWatch. Searchable and alertable."
        },
        {
          "label": "APM traces",
          "description": "Distributed tracing for request flow visibility."
        },
        {
          "label": "Custom metrics",
          "description": "Business-specific counters and gauges in Datadog."
        }
      ],
      "multiSelect": true
    }
  ]
}
```

### Using previews

Use the `preview` field on options when the user needs to visually compare concrete artifacts — code snippets, architecture diagrams, schema shapes, or configuration examples. Preview content renders as markdown in a monospace box with side-by-side comparison.

**When to use previews:**

- Comparing two code patterns or implementations
- Showing different schema shapes or data structures
- Presenting architecture alternatives with ASCII diagrams

**Constraint:** Previews are single-select only (`multiSelect: false`). If you need multi-select, omit previews and use descriptions instead.

Example with previews:

```json
{
  "question": "Which pattern should we use for the data pipeline?",
  "header": "Pipeline",
  "options": [
    {
      "label": "Generator pipeline (Recommended)",
      "description": "Lazy evaluation, memory-efficient for large datasets.",
      "preview": "def pipeline(source):\n    for record in source:\n        cleaned = clean(record)\n        validated = validate(cleaned)\n        yield validated"
    },
    {
      "label": "Batch pipeline",
      "description": "Processes all records at once. Simpler but higher memory usage.",
      "preview": "def pipeline(source):\n    records = list(source)\n    cleaned = [clean(r) for r in records]\n    validated = [validate(r) for r in cleaned]\n    return validated"
    }
  ],
  "multiSelect": false
}
```

## Rules for Asking Questions

- **Use AskUserQuestion for every question.** Period.
- **First option = recommendation.** The first option always has `(Recommended)` in the label.
- **Batch related questions.** Group up to 4 related questions from the same domain into one AskUserQuestion call. Cross-domain questions must be separate calls.
- **Respect tool constraints.** 2-4 options per question. Headers max 12 characters. Use `multiSelect: true` when options are not mutually exclusive (e.g., 'Which testing approaches should we use?' or 'Which domains need coverage?').
- **Filter options.** When more than 4 valid choices exist, present the 3 most relevant based on codebase context. Users select "Other" for anything not listed.
- **Be specific.** "How should we handle errors?" is too vague. "When the Oura API returns a 429, should we retry with backoff or queue for the next run?" is specific.
- **Show your work.** If your recommendation is based on something you found in the codebase, reference the file and line.
- **Accept the answer.** When the user decides, record it and move on. Don't re-litigate unless a later decision creates a conflict with a prior one.

## Fallback (no AskUserQuestion available)

If AskUserQuestion is not available in the runtime environment, fall back to this text format:

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
