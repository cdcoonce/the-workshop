---
name: improve-skill
description: >
  Benchmark-driven skill improvement pipeline. Interviews the user to build
  a test suite, scores the original skill, iterates with a Skill Writer and
  QA Tester loop until the target pass rate is reached, then files a PR.
  Use when user says "improve skill", "benchmark skill", "make skill better",
  or invokes /improve-skill.
---

# Improve-Skill Orchestrator

Run a benchmark-driven improvement loop on any skill: interview → baseline → iterate → PR.

**Self-check:** Before executing any phase, count the lines in this SKILL.md file. If it exceeds 100 lines, report the violation and halt execution immediately.

**Reference path rule:** All `references/` paths in this skill are relative to this skill's own directory (`core/skills/improve-skill/`). Always resolve them as `core/skills/improve-skill/references/<file>` regardless of current working directory.

**Sidecar path rule:** The `.best_skill.md` sidecar file is always written to the same directory as the resolved `skill_path` (i.e., the directory containing the target skill's SKILL.md), not hardcoded to `core/skills/`. This applies to Phase 4 Step G and Phase 5 Step 1.

## Phase 1: Orchestrator

**Step 1 — Parse and validate slug:** Usage: `/improve-skill <slug>`. If no slug given, reply with usage and stop. Reject the slug if it contains path separators (`/`, `\`), traversal sequences (`..`), spaces, or git-unsafe characters (`~`, `^`, `:`). On rejection, reply: `Error: invalid slug "{slug}". Slugs must be alphanumeric with hyphens only.` and stop.

**Step 2 — Resolve skill path:** Check `core/skills/{slug}/SKILL.md`, then `presets/*/skills/{slug}/SKILL.md`. If not found, abort: `Error: no skill found for slug "{slug}".` Record resolved path as `skill_path`. Derive `tests_path` as the directory of `skill_path` plus `/tests.md`.

**Step 3 — Check state file:** Look for `docs/skill-improve/{slug}.state.md`.

- **`status: in_progress`:** Read `skill_path`, `current_phase`, `best_score`. Verify `skill_path` exists on disk. Report: "Resuming **{slug}** at phase **{current_phase}** (best score: {best_score}%)." Jump to that phase.
- **`status: completed` or `status: abandoned`:** Notify user, start new run (suffix slug with `-2`, `-3` etc.).
- **Not found:** Proceed to Step 4.

**Step 4 — Create state file:** Write `docs/skill-improve/{slug}.state.md`. Set `status: in_progress`, `current_phase: grill`. Log: `{YYYY-MM-DD} — State file created. Skill path: {skill_path}`. Proceed to Phase 2.

---

## Phase 2: Grill

Read `core/skills/improve-skill/references/phase-2-grill.md` using the Read tool, then follow its instructions exactly. **Input validation override:** When asking for target pass rate, validate the input is an integer between 1 and 100. If invalid (non-numeric, out of range), explain the valid range and re-prompt. The target will be further validated against baseline in Phase 3.

After completion: test suite is written to `{tests_path}`; config (target pass rate, max iterations) is recorded in the state file; `current_phase` is advanced to `baseline`.

---

## Phase 3: Baseline

Read `core/skills/improve-skill/references/phase-3-baseline.md` using the Read tool, then follow its instructions exactly.

After completion: `baseline_score` is recorded in state; iteration 0 is added to the Scores table; `best_score` is initialized to `baseline_score`.

---

## Phase 4: Iterate

Read `core/skills/improve-skill/references/phase-4-iterate.md` using the Read tool, then follow its instructions with these overrides:

**Sidecar override:** Wherever the reference doc says `core/skills/{slug}/.best_skill.md`, use the directory of `{skill_path}` instead. The sidecar lives next to the target skill, not hardcoded to core.

**Regression/stall override (this takes precedence over the reference doc):** After each iteration compare `new_score` to `best_score`:

- **Improvement** (`new_score > best_score`): Update `best_score` and `best_iteration`; copy skill to sidecar; reset `stall_count` to 0.
- **Regression** (`new_score < best_score`): Increment `stall_count` by 1; log the regression; revert `{skill_path}` to the sidecar content; preserve `best_score` and `best_iteration`.
- **No change** (`new_score == best_score`): Increment `stall_count` by 1.

When `stall_count` >= 2, invoke the strategy agent, then reset `stall_count` to 0. Loop continues until target pass rate is met or max iterations is reached.

---

## Phase 5: Finalize

Read `core/skills/improve-skill/references/phase-5-finalize.md` using the Read tool, then follow its instructions with these overrides:

**Sidecar override:** Read sidecar from the directory of `{skill_path}`, not hardcoded `core/skills/`.

**Data preservation override:** Before clearing Result/Reason columns (Step 2), read and store the full annotated test table in memory so Step 3 can accurately report "Tests fixed" and "Tests still failing."

**Merge conflict check:** Before opening the PR (Step 5), check for merge conflicts with the default branch. If conflicts exist, warn the user that manual resolution is needed and do not silently open an unmergeable PR.

After completion: PR is filed using best iteration content; state archived to `docs/archive/skill-improve/`.

---

## Phase 6: Agent Definitions

Agents live in `core/agents/`: `skill-analyst`, `qa-tester`, `skill-writer`, `strategy`.
