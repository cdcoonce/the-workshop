---
name: dev-cycle
description: >
  Use when user says "dev cycle", "development workflow", "full development
  pipeline", or invokes /dev-cycle to take a GitHub-issues-driven feature from
  brainstorm through a merged PR. This is the interactive lane — for
  greenfield work, skill-building, or changes too coupled to delegate.
---

# Dev Cycle Orchestrator

Orchestrate the full development lifecycle: brainstorm → plan → review → issues → implement → code review → PR.

**Disambiguation:** If the user only wants a PRD, route to `/write-a-prd`. If they only want a plan, route to `/prd-to-plan`. This skill is for the full end-to-end lifecycle.

**Lane boundary:** dev-cycle is the _interactive_ lane — greenfield features, work the user wants to build hands-on, or changes too coupled to hand off. Localized single-concern correctness work with clear acceptance criteria belongs in an autonomous pipeline instead when one is available: file it as an executor-ready issue (see `triage-issue` / `prd-to-issues` issue shapes) rather than running it through this ceremony.

## The 7-Phase Pipeline

Every phase is mandatory. No phase can be skipped. **Before treating any phase as optional**, read the Excuse → Reality table in [references/phase-transitions.md](references/phase-transitions.md#excuse-reality-skipping-a-phase) — every rationalization for skipping a phase is addressed there.

| #   | Phase           | Delegates To                                           | Gate Condition                    |
| --- | --------------- | ------------------------------------------------------ | --------------------------------- |
| 1   | **Brainstorm**  | `write-a-prd`                                          | Issue URL recorded                |
| 2   | **Plan**        | `prd-to-plan`                                          | Plan file exists at `docs/plans/` |
| 3   | **CEO Review**  | `plan-ceo-review` (recommend HOLD SCOPE)               | Review complete, user approves    |
| 4   | **Issues**      | Orchestrator (plan slices → GitHub issues)             | All issue URLs recorded           |
| 5   | **Implement**   | Orchestrator (`tdd` per issue, `subagent-development`) | All issues resolved, tests pass   |
| 6   | **Code Review** | `daa-code-review`                                      | Clean review                      |
| 7   | **PR**          | `commit` + `finish-branch`                             | PR URL recorded                   |

## Re-entry Logic

### No arguments (`/dev-cycle`)

Scan `docs/dev-cycle/` for `*.state.md` with `status: in_progress`. One match → ask "Resume **{feature}** (`{branch}`)? Currently at **{phase}**." Multiple → list with branch names, ask which. None → ask what feature, start Phase 1.

### With argument (`/dev-cycle {slug}`)

Look for `docs/dev-cycle/{slug}.state.md`. Found → resume at `current_phase`. Not found → create state file, start Phase 1.

### Slug Collision

When creating a new state file, check `docs/dev-cycle/` for existing slugs. If the slug already exists (abandoned or completed), suffix with `-2`, `-3`, etc.

### Context Loading on Resume

Before continuing, load all referenced artifacts: PRD issue (`gh issue view`), plan file (from disk, includes CEO Review revisions), implementation issues (`gh issue view` each), and git status on the feature branch. Present: "Resuming **{feature}** at **{phase}**. Here's where we left off: ..."

## Phase Execution

Phases 1–3 delegate directly per the table above; record each artifact (issue URL, plan path, review completion) in the state file as soon as it's produced. Full validate/handoff/record/failure detail for every transition lives in [references/phase-transitions.md](references/phase-transitions.md).

### Phase 4: Issues

**Owned by the orchestrator.** For each of the plan's vertical slices, create a GitHub issue via `gh issue create` that references the PRD, includes acceptance criteria from the plan, and is created in dependency order. Record each issue URL immediately after creation. See [references/phase-transitions.md](references/phase-transitions.md) for partial-completion recovery.

### Phase 5: Implement

**Owned by the orchestrator.** Create feature branch `feat/{feature-slug}`, then dispatch one subagent per GitHub issue following `subagent-development` methodology (each invokes `tdd`; code review runs between dispatches; state file updates after each subagent, not batched). See [references/phase-transitions.md](references/phase-transitions.md) for branch handling, per-subagent logging, and model-selection requirements.

**Escalation threshold:** After 3 failed fix attempts on the same issue, stop retrying. A 4th attempt at the same fix is not more diligence, it's a sign the architecture is wrong for the problem. Question the approach, then ask the human before continuing.

### Phase 6: Code Review

Invoke `daa-code-review` against all changed files on the feature branch. If blocking issues found → fix, re-run. Loop until clean. Architectural issues requiring plan rework → trigger backwards transition to Phase 2.

### Phase 7: PR

Invoke `commit` for a conventional commit, then hand off to `finish-branch`, which presents its four-option menu (merge locally, push + open PR, keep as-is, discard) and owns its own test-gate around any rebase or merge it performs. See [references/phase-transitions.md](references/phase-transitions.md) for recording rules per option and the required post-rebase/merge re-test.

## State File

Each feature tracked at `docs/dev-cycle/{feature-slug}.state.md`. See [references/state-file-schema.md](references/state-file-schema.md) for full format, field definitions, and transition rules.

## Failure & Recovery

See [references/phase-transitions.md](references/phase-transitions.md) for phase retry logic, backwards transitions (implement/code_review → plan), and feature abandonment. Archived files are moved to `docs/archive/`.

## Branch Management

- **Phases 1–4:** Run on current branch (documentation only)
- **Phase 5:** Creates `feat/{feature-slug}` branch
- **Phase 7:** PRs to the default branch (detected via `gh repo view --json defaultBranchRef`)
- **Resume at Phase 5+:** Check out feature branch if not already on it

## Archival

Runs automatically at the end of Phase 7 (after PR URL is recorded and status is set to `completed`) and on feature abandonment (after status is set to `abandoned`). See [references/phase-transitions.md](references/phase-transitions.md) for the exact archive steps (directory creation, `git mv`, commit message).
