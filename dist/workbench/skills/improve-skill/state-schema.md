# State File Schema — improve-skill (v1)

## Location

`docs/skill-improve/{slug}.state.md`

## Template

```markdown
---
schema_version: 1
slug: { slug }
skill_path: { resolved path, e.g. core/skills/tdd/SKILL.md }
status: in_progress
current_phase: grill
target_pass_rate:
max_iterations:
current_iteration: 0
best_score:
best_iteration: 0
prd_issue:
baseline_score:
new_test_ids:
stall_count: 0
created: { YYYY-MM-DD }
updated: { YYYY-MM-DD }
---

## Scores

| Iteration | Score | Notes |
| --------- | ----- | ----- |

## Log
```

## Field Definitions

- **schema_version:** `1` (integer). Increment on breaking format changes.
- **slug:** Kebab-case skill name. Must match filename. On collision, suffix with `-2`, `-3`, etc.
- **skill_path:** Relative path to the resolved `SKILL.md` (e.g., `core/skills/tdd/SKILL.md`).
- **status:** `in_progress` | `completed` | `abandoned`
- **current_phase:** `grill` | `baseline` | `iterate` | `finalize`
- **target_pass_rate:** Integer percentage (e.g., `90`). Set during Phase 2 (Grill).
- **max_iterations:** Integer. Set during Phase 2 (Grill).
- **current_iteration:** Incremented after each full Skill Writer + QA Tester cycle.
- **best_score:** Highest pass percentage achieved so far (integer). Blank until Phase 4 initializes it to `baseline_score`.
- **best_iteration:** Iteration number that produced `best_score`.
- **prd_issue:** Optional issue number that this improvement run is associated with. Omit if no issue is tracked. Populated during Phase 1 if the user provides an issue number.
- **baseline_score:** Score from Phase 3 before any iteration. Set once; never updated.
- **new_test_ids:** Comma-separated list of test IDs added during the current Grill session (Phase 2 Step 3). Consumed by Phase 3's no-skill RED baseline step to scope which rows need a fresh no-skill run; cleared once consumed.
- **stall_count:** Number of consecutive iterations without improvement. Incremented on no-change, reset to `0` on improvement or after strategy dispatch. Read at loop start for resume support.
- **created / updated:** ISO date (YYYY-MM-DD). `updated` refreshed on every state write.

## Scores Table

Appended after each QA Tester run (baseline gets iteration `0`). Scores are percentages.

## Log

Append-only event log. Each entry: `{YYYY-MM-DD} — {event description}`.

Examples:

```
2026-04-01 — State file created. Skill path: core/skills/tdd/SKILL.md
2026-04-01 — Baseline score: 60%. 9/15 tests passed.
2026-04-01 — Iteration 1 complete. Score: 73%. New best.
2026-04-01 — Iteration 2 complete. Score: 67%. Regression — reverted to iteration 1.
```

## Status Transitions

```
in_progress → completed   (Phase 5 finalize, PR merged)
in_progress → abandoned   (user cancels)
```

Terminal state files are archived to `docs/archive/skill-improve/`.
