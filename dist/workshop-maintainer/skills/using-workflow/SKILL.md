---
name: using-workflow
description: >
  Use when starting any conversation or task in this project — establishes
  precedence between instructions and skills, requires invoking any skill
  that might apply, and sets the order skills run in before any response
  or action.
---

<SUBAGENT-STOP>
If you were dispatched as a subagent to execute a specific task, ignore this skill.
</SUBAGENT-STOP>

# Using Workflow

Router skill for this project. Read this before any other skill, response, or action.

## Precedence

CLAUDE.md and other user instructions outrank skills. Skills outrank default
behavior. If a skill's guidance conflicts with CLAUDE.md or a direct user
request, follow CLAUDE.md or the user.

## Resolve repository policy

Resolve repository policy before selecting an integration workflow. Read the
nearest project instructions and relevant CI/CD configuration for branch
promotion, review, test, deployment, and unattended-execution constraints.
Never infer an integration target from a hosting provider's default branch.

## Resolve development branch naming

Resolve development branch naming separately from the integration target.
Use this precedence: explicit user policy, then the nearest explicit repository
policy, then the fallback `<type>/<kebab-case-slug>`.
Use Conventional Commit type vocabulary for the fallback: `feat/`, `fix/`,
`docs/`, `refactor/`, `test/`, `chore/`, `ci/`, `perf/`, and `style/`.
Branch history may inform slug formatting only when it is consistent with the
explicit policy. Historical vendor- or agent-prefixed branches do not count as
policy. Branch history must never authorize vendor or agent prefixes.

## Choose execution mode

- **Interactive:** Use the repository's normal workflow and request approval
  only when the action needs it.
- **AFK / unattended:** Treat local AFK configuration and project instructions
  as an execution contract. Prefer available context, read-only inspection,
  and single unpiped commands. Do not make progress depend on network,
  approval-gated, or chained shell calls that the unattended executor cannot
  approve. After exhausting repository context and safe alternatives, record a
  genuine capability gap using the repository's AFK escalation mechanism.

Apply the same repository policy in both modes; AFK changes *how* work is
executed, not its integration target, quality gate, or authorization boundary.

## Trigger Floor

If there is even a small chance a listed skill applies to what you're doing,
invoke it. Invoking a skill and discarding it because it doesn't fit costs
almost nothing. Skipping a skill that did apply is the expensive mistake —
don't rationalize your way past a skill because the task "feels simple" or
you "already know" what it says.

## Ordering

When multiple skills apply, process skills run first and implementation
skills run after:

- Process skills set the approach — e.g. `grill-me`, `write-a-prd`,
  `plan-ceo-review`.
- Implementation skills carry it out — e.g. `tdd`, `commit`, `github-cli`.

Example: "write a PRD for X" → `write-a-prd` first, then `commit` once the
PRD is filed.

## Announce Convention

Before following a skill, announce it: "Using [skill] to [purpose]." If the
skill defines a checklist, create one todo per checklist item before starting
work, and track them as you go.

## Subagent Opt-Out

<SUBAGENT-STOP>
Workers dispatched to execute one specific task skip this router entirely —
no announcement, no checklist, no precedence check. Do the task.
</SUBAGENT-STOP>
