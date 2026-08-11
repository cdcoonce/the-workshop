# Subagent-Driven Development

Execute a plan by dispatching a fresh subagent per task, with code review after each.

**Core principle:** Fresh subagent per task + review between tasks = high quality, fast iteration

## When to Use

- Staying in current session
- Tasks are mostly independent
- Want continuous progress with quality gates

## When NOT to Use

- Need to review plan first
- Tasks are tightly coupled (manual execution better)
- Plan needs revision

## The Process

### 1. Load Plan

Read plan file, create TodoWrite with all tasks.

### 2. Agent Discovery

Before dispatching each subagent, select the best-fit agent using the algorithm in `.claude/docs/agent-matching.md`. Summary:

1. **Scan** `.claude/agents/` — read all `AGENT.md` files
2. **Filter by role** — `implementer` for implementation tasks, `reviewer` for review tasks
3. **Score and select** — pick the agent whose description best matches the task domain and technology; prefer specialized over generic on ties
4. **Fallback** — if no `.claude/agents/` directory exists or no agent scores above "no match", dispatch a generic subagent with no agent identity

See `.claude/docs/agent-matching.md` for the full scoring rubric, tiebreaking rules, and good/bad description examples.

### 3. Execute Task with Subagent

For each task, dispatch fresh subagent with resolved agent identity. **Model is required** — an omitted model silently inherits the orchestrator's own model, typically the most capable and most expensive tier. Select a tier using the rubric in `.claude/docs/agent-matching.md#model-selection` (implementer tasks default to `mid`; reserve `cheapest` for purely mechanical work).

```
Task tool (general-purpose):
  description: "Implement Task N: [task name]"
  model: {tier}  # required — cheapest | mid | frontier, see agent-matching.md#model-selection
  prompt: |
    # Agent Identity (injected from agent discovery, omit if generic)
    You are [{agent.name}]: {agent.description}
    Your skills: {agent.resolved_skills}

    # Task
    You are implementing Task N from [plan-file].

    Read that task carefully. Your job is to:
    1. Implement exactly what the task specifies
    2. Write tests (following TDD)
    3. Verify implementation works: uv run pytest
    4. Commit your work
    5. Report back

    Report in 15 lines or less: what you implemented, what you tested, test
    results, files changed, any issues. Detail belongs in files or commit
    messages, not in this reply.

    Bad work is worse than no work; you will not be penalized for reporting
    BLOCKED.

    End your reply with exactly one line:
    STATUS: <one of DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT>
```

**Subagent reports back** with a ≤15-line summary of work, ending in the
required `STATUS:` line. See [Status Contract](#status-contract) below for
what each status means and how the controller must respond.

### 4. Review Subagent's Work

Dispatch code-reviewer subagent. **Model is required** — reviewer dispatches never go below `mid` tier (see `.claude/docs/agent-matching.md#model-selection`):

```
Task tool (code-reviewer):
  model: {tier}  # required — mid or frontier, never cheapest
  WHAT_WAS_IMPLEMENTED: [from subagent's report]
  PLAN_OR_REQUIREMENTS: Task N from [plan-file]
  BASE_SHA: [commit before task]
  HEAD_SHA: [current commit]
```

**Code reviewer returns:** Strengths, Issues (Critical/Important/Minor), Assessment

### 5. Apply Review Feedback

**If issues found:**

- Fix Critical issues immediately
- Fix Important issues before next task
- Note Minor issues

**Dispatch follow-up subagent if needed:**

```
"Fix issues from code review: [list issues]

End your reply with exactly one line:
STATUS: <one of DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT>"
```

### 6. Mark Complete, Next Task

- Mark task as completed in TodoWrite
- Move to next task
- Repeat steps 3-6

### 7. Final Review

After all tasks complete, dispatch final code-reviewer:

- Reviews entire implementation
- Checks all plan requirements met
- Validates overall architecture

### 8. Complete Development

After final review passes:

- Announce: "Subagent work complete!"

## Example Workflow

```
[Load plan, create TodoWrite]

Task 1: Add data validation module

[Dispatch implementation subagent]
Subagent: Implemented validation with tests, 5/5 passing

[Get git SHAs, dispatch code-reviewer]
Reviewer: Strengths: Good coverage. Issues: None. Ready.

[Mark Task 1 complete]

Task 2: Add error handling

[Dispatch implementation subagent]
Subagent: Added error handling, 8/8 tests passing

[Dispatch code-reviewer]
Reviewer: Issues (Important): Missing edge case for empty input

[Dispatch fix subagent]
Fix subagent: Added test and handling for empty input

[Verify fix, mark Task 2 complete]

...

[After all tasks]
[Dispatch final code-reviewer]
Final reviewer: All requirements met, ready to merge

Done!
```

## Status Contract

Every subagent dispatch prompt (implementation, fix, and review dispatches
alike) MUST end with the REQUIRED final line:

```
STATUS: <one of DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT>
```

Exactly one status, exactly once. Free-prose reports give the orchestrator no
reliable outcome signal — the status line is what phase-transition logic and
downstream tooling key off of (see `core/skills/dev-cycle/references/phase-transitions.md`).

Reply text (report or dispatch prompt) stays ≤15 lines — it stays resident in
the orchestrator's context for the rest of the session, so detail belongs in
files, commits, or issue comments, not in the reply itself.

**Bad work is worse than no work; the worker will not be penalized for
reporting BLOCKED.** Escalating a real blocker is success, not failure.

### Controller Playbook

| Status               | Controller move                                                                                                                           |
| -------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| `DONE`               | Verify the evidence (tests ran, files changed as claimed), then proceed.                                                                  |
| `DONE_WITH_CONCERNS` | Read the concerns before proceeding. Address each one or consciously accept it — do not silently proceed past a concern you haven't read. |
| `NEEDS_CONTEXT`      | Answer the worker's question, then re-dispatch the _same_ worker with the answer folded in.                                               |
| `BLOCKED`            | Work the escalation ladder below. Never ignore a `BLOCKED` report, and never re-dispatch the same prompt unchanged.                       |

### Escalation Ladder (for `BLOCKED`)

Work these in order — stop at the first rung that resolves the block:

1. **Supply missing context** — if the block is a missing fact, file, or decision the controller can provide, provide it and re-dispatch.
2. **Retry on a more capable model** — if the block looks like a capability gap, re-dispatch the same task on a stronger model.
3. **Split the task** — if the task is too large or coupled, break it into smaller, independent pieces and dispatch each separately.
4. **Escalate to the human** — if none of the above resolves it, stop and surface the blocker to the human rather than guessing.

## Red Flags

**Never:**

- Skip code review between tasks
- Proceed with unfixed Critical issues
- Dispatch multiple implementation subagents in parallel (conflicts)
- Implement without reading plan task
- Ignore a `BLOCKED` status or re-dispatch the same prompt unchanged
