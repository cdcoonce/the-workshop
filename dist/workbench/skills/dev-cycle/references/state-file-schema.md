# State File Schema (v1)

## Location

`docs/dev-cycle/{feature-slug}.state.md`

## Template

```markdown
---
schema_version: 1
feature: { feature-slug }
status: not_started
current_phase: brainstorm
created: { YYYY-MM-DD }
updated: { YYYY-MM-DD }
branch:
---

## Artifacts

| Phase       | Status  | Artifact |
| ----------- | ------- | -------- |
| brainstorm  | pending | —        |
| plan        | pending | —        |
| ceo_review  | pending | —        |
| issues      | pending | —        |
| implement   | pending | —        |
| code_review | pending | —        |
| pr          | pending | —        |

## Issues

| Plan Slice | GitHub Issue | Status |
| ---------- | ------------ | ------ |

## Log
```

## Field Definitions

- **schema_version:** `1` (integer). Increment on breaking format changes.
- **feature:** Kebab-case slug. Must match filename. On collision with existing slug, suffix with `-2`, `-3`, etc.
- **status:** `not_started` | `in_progress` | `completed` | `abandoned`
- **current_phase:** `brainstorm` | `plan` | `ceo_review` | `issues` | `implement` | `code_review` | `pr`
- **created/updated:** ISO date (YYYY-MM-DD).
- **branch:** Git branch name. Empty until Phase 5. Format: `feat/{feature-slug}`.

## Artifact Status Values

`pending` | `in_progress` | `completed` | `blocked`

Completed phases MUST have a non-empty artifact (not `—`).

## Issues Table

Populated incrementally during Phase 4. Each row maps a plan slice to a GitHub issue URL. On retry, the orchestrator skips slices that already have a recorded issue URL.

## Phase Transition Rules

Forward only, in strict order:

```text
brainstorm → plan → ceo_review → issues → implement → code_review → pr
```

### Backwards Transitions (exceptions)

- `implement → plan` — approach is wrong, plan needs rework
- `code_review → plan` — architectural issues found

When a backwards transition occurs:

1. Log the reason
2. Present code handling options to user (keep/revert/new branch)
3. Reset phases from `plan` onward to `pending`
4. Re-enter Phase 2

All other backwards transitions are not supported.

## Validation

Run `uv run python -m scripts.dev_cycle_validate docs/dev-cycle/` to validate all `*.state.md` files.

## Archive

When a feature reaches terminal state (`completed` or `abandoned`), files move to:

- State file: `docs/archive/dev-cycle/{slug}.state.md`
- Plan file: `docs/archive/plans/{feature}.md`

The plan path is read from the artifacts table (plan phase row). Use `git mv` to preserve history.

Active state files live in `docs/dev-cycle/`. The re-entry logic only scans this directory — archived files are not considered for resume.
