# Agent-Matching Algorithm

This document is the canonical specification for how orchestrators select agents when dispatching subagents. All orchestrators — dev-cycle, subagent-development, parallel-agents — follow this algorithm.

The build pipeline copies this file into every preset at `docs/agent-matching.md` so it is always available to orchestrators at `.claude/docs/agent-matching.md` in any project using a preset plugin.

## Overview

Agent matching happens in four steps: **scan → filter → score → select**.

## Step 1: Scan

Read all `AGENT.md` files from `.claude/agents/`. Extract from each:

- `name` — the agent identifier
- `description` — the matching signal
- `role` — either `implementer` or `reviewer`
- `skills.add` / `skills.remove` — used later for prompt construction

If `.claude/agents/` does not exist, skip directly to [Fallback](#fallback).

## Step 2: Filter by Role

Keep only agents whose `role` matches the task type:

- Implementation tasks → `implementer` agents only
- Review tasks → `reviewer` agents only

If no agents survive the filter, skip to [Fallback](#fallback).

## Step 3: Score by Description Relevance

For each remaining agent, score how well its `description` matches the current task. This is Claude's reasoning judgment, not keyword matching.

### Scoring Rubric

Evaluate each agent description on these four dimensions:

| Dimension       | Strong signal                                                                       | Weak signal                                     |
| --------------- | ----------------------------------------------------------------------------------- | ----------------------------------------------- |
| **Technology**  | Names the exact framework or library in the task (FastAPI, React, Dagster)          | Technology-agnostic ("builds backend services") |
| **Domain**      | Names the specific artifact or concern (REST endpoints, ETL pipelines, skill files) | Domain-agnostic ("implements features")         |
| **Action verb** | Verb matches the task action (builds, validates, reviews, migrates)                 | Generic verb ("works on", "handles")            |
| **Scope**       | Scope matches task granularity (endpoint-level, pipeline-level, component-level)    | Too broad or too narrow                         |

### Score Levels

Assign one of four levels to each agent:

- **Strong match** — Description directly addresses both the technology and domain of the task. Reading the description and the task side-by-side, they are clearly about the same thing.
- **Moderate match** — Description partially matches. Same domain, different technology; or same technology, different domain.
- **Weak match** — Description is too generic to provide meaningful signal but is role-compatible (e.g., `tdd-implementer` for any implementation task).
- **No match** — Description is role-compatible but clearly addresses a different domain or technology.

## Step 4: Select

1. Collect all agents with the highest score.
2. If only one, select it.
3. **Tiebreaking when scores are equal:** Prefer the more specialized agent over a generic core agent. `api-builder` beats `tdd-implementer` for an API task; `security-reviewer` beats `code-reviewer` for a security review. A specialized agent is one whose description names a specific technology or domain; a generic agent is one whose description could apply to any task of that role.
4. If multiple agents are equally specialized and tied, select any one and note the ambiguity in the dispatch prompt so the subagent is aware.

## Fallback

Use the fallback (dispatch a generic subagent with no agent identity) when any of the following apply:

- `.claude/agents/` does not exist
- No agents exist for the required role
- No agent scores above "no match" (all descriptions are clearly about a different domain)
- The task is so general that no description provides meaningful signal over any other

**Never force a bad match.** An unspecialized subagent outperforms a wrongly-specialized one. The fallback is not a failure — it is the correct behavior for general-purpose tasks and for projects that have not configured specialized agents.

## Good vs. Bad Agent Descriptions

Matching quality is determined by description quality. Here is what separates them.

### Bad descriptions

```yaml
description: Implements features using test-driven development
```

**Problems:** No domain signal, no technology signal. Matches any implementation task equally. Only useful as a generic fallback, not as a specialist match.

```yaml
description: Builds backend services
```

**Problems:** "Backend" is too broad. Does it mean API endpoints, database queries, ETL pipelines, message consumers? An orchestrator cannot distinguish this from any other backend task.

```yaml
description: Reviews code for quality
```

**Problems:** Every reviewer reviews code for quality. This description does not help an orchestrator choose between a security reviewer, a UX reviewer, and a data quality reviewer.

### Good descriptions

```yaml
description: Builds Python API endpoints with FastAPI, Flask, or Lambda
```

**Why it works:** Names the exact frameworks. When a task involves adding a FastAPI route or a Lambda handler, this description signals a clear match.

```yaml
description: Builds Claude Code skills, hooks, and MCP server integrations
```

**Why it works:** Names the specific artifacts. When a task involves creating a skill file or configuring a hook, this matches precisely.

```yaml
description: Builds data pipelines with ETL/ELT patterns and orchestration
```

**Why it works:** Names the architectural pattern (ETL/ELT) and the concern (orchestration). A task about adding a Dagster asset or dbt model clearly maps here.

```yaml
description: Reviews auth patterns, input validation, and OWASP top 10
```

**Why it works:** Names specific review concerns. An orchestrator can immediately distinguish this from a general code reviewer when the task involves authentication or input handling.

### The pattern

Good descriptions answer: **"What specific things do I build or review, and with what tools or patterns?"** Name the output artifacts and the technology stack, not just the abstract activity.

## Reusable Prompt Fragment

Include this block verbatim in orchestrator prompts when agent selection is required. Replace `{role}` with `implementer` or `reviewer`.

---

**Selecting an agent:** Before dispatching, scan `.claude/agents/` for `AGENT.md` files. Filter to agents with `role: {role}`. Score each by how well its `description` matches the task's domain and technology — strong, moderate, weak, or no match. Select the highest-scoring agent. On ties, prefer the more specialized agent over a generic core agent (e.g., `api-builder` over `tdd-implementer`). If no agent scores above "no match", or if `.claude/agents/` does not exist, dispatch a generic subagent with no agent identity. See `.claude/docs/agent-matching.md` for the full scoring rubric, tiebreaking rules, and description examples.

---
