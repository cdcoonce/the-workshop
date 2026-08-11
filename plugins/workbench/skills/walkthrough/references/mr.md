# Merge Request Walkthrough

## What to Explain

An MR walkthrough builds understanding of what changed, why, and what impact it has on the broader system.

## Overview Phase

Generate a visual showing:
- **Files changed** — grouped by module/directory, sized by change magnitude
- **Change type distribution** — new code vs modifications vs deletions
- **Dependency impact** — which parts of the system are touched and what depends on them

Best diagram type: **D3 treemap** with files sized by lines changed, colored by change type (green=add, yellow=modify, red=delete). Alternatively, a **Mermaid flowchart** showing the logical flow of the change.

## Drill-Down Sections

1. **Intent & motivation** — what problem does this solve, what's the ticket/context
2. **Architecture impact** — does this change boundaries, introduce new patterns, or shift responsibilities
3. **Specific file changes** — walk through key hunks explaining the logic
4. **Risk areas** — what could break, what assumptions are made, edge cases
5. **Test coverage** — what's tested, what isn't, are the tests meaningful
6. **Migration/rollback** — is this reversible, does it require data migration

## Exploration Strategy

- Use `git diff` or `gh/glab` CLI to get the full diff.
- Read the MR description and any linked issues.
- Identify the "spine" of the change — the core modification that everything else supports.
- Check if tests were added/modified proportionally to the change.
- Look at what the changed code connects to (callers, dependents).

## Visual Updates on Drill-Down

- **Architecture impact** → before/after module diagram showing boundary shifts
- **File changes** → annotated diff with inline commentary
- **Risk areas** → dependency graph highlighting affected paths
- **Test coverage** → coverage overlay on the change treemap
