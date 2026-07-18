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
