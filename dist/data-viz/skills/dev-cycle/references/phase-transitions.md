# Phase Transitions

Each transition follows: validate artifact → update state → prepare context → invoke next phase.

See the 7-Phase Pipeline table in SKILL.md for delegation targets. This document specifies validation, handoff, and recovery details only.

---

## Brainstorm → Plan

- **Validate:** GitHub issue URL (PRD) is present and accessible via `gh issue view`
- **Handoff:** Pass issue URL to `prd-to-plan`, which reads the PRD and breaks it into vertical slices
- **Record:** Plan file path in artifacts table
- **Failure:** If `gh` is not authenticated or issue is 404, set phase to `blocked`, suggest resolution

## Plan → CEO Review

- **Validate:** Plan file exists at recorded path and is non-empty
- **Handoff:** Pass plan file path to `plan-ceo-review`, recommend HOLD SCOPE mode
- **Record:** Review outcome in log. Plan file on disk reflects revisions (skill edits it in place)
- **Failure:** If plan file is missing, set phase to `blocked`

## CEO Review → Issues

- **Validate:** Plan has been reviewed and user approved. Plan file on disk reflects all revisions.
- **Handoff:** Orchestrator reads the plan's vertical slices and creates one GitHub issue per slice using `gh issue create`. Each issue:
  - References the PRD issue number
  - Includes acceptance criteria from the plan
  - Is created in dependency order so blockers can be referenced by number
- **Record:** Each issue URL is recorded individually in the Issues table as it's created (not batched)
- **Partial completion:** On retry, skip slices that already have a recorded issue URL in the Issues table
- **Failure:** If `gh issue create` fails mid-batch, the Issues table reflects which were created. Retry resumes from next uncreated slice.

## Issues → Implement

- **Validate:** All GitHub issues created and URLs recorded in Issues table
- **Branch creation:**
  - Create `feat/{feature-slug}` from current HEAD
  - If branch already exists and belongs to this feature (per state file): check it out
  - If branch exists but is unrecognized: error, ask user to resolve
- **Handoff:** Load plan file. Dispatch one subagent per issue following `subagent-development` methodology, each invoking `tdd`. Code review between each dispatch.
- **Model (required):** Every dispatch — implementer and reviewer — must set `model` explicitly per the rubric in `.claude/docs/agent-matching.md#model-selection`. An omitted model silently inherits the orchestrator's own model. Implementer dispatches default to `mid`; reviewer dispatches never go below `mid`.
- **State updates:** After each subagent completes:
  - Log dispatch and result: `"Subagent completed for issue #N: pass/fail"`
  - Log code review result: `"Code review after issue #N: clean/blocking"`
  - Update Issues table status
- **Failure:** Context window exhaustion mid-dispatch is recoverable — Issues table shows which issues are complete. Resume dispatches remaining issues.

## Implement → Code Review

- **Validate:** All implementation issues resolved, tests passing (`uv run pytest` or project test command)
- **Handoff:** Invoke `daa-code-review` against all changed files on the feature branch
- **Gate:** If blocking issues → fix, re-run review. Loop until clean.
- **Failure:** If code review finds architectural issues requiring plan rework, trigger backwards transition to `plan` (see Backwards Transitions below)

## Code Review → PR

- **Validate:** Code review passed with no blocking issues
- **Conflict check:** Before PR creation:
  - Check for conflicts with default branch (via `gh repo view --json defaultBranchRef`)
  - If conflicts exist: rebase or merge default branch, resolve conflicts
  - If a PR already exists for this branch: update it instead of creating duplicate
- **Handoff:** Invoke `commit` for conventional commit, then `github-cli` to open PR
- **Record:** PR URL in artifacts table, set feature `status: completed`
- **Archive:** Run archival step — `mkdir -p docs/archive/dev-cycle docs/archive/plans`, then `git mv` the state file to `docs/archive/dev-cycle/` and the plan file (read path from artifacts table) to `docs/archive/plans/`. Commit with `chore(dev-cycle): archive {slug}`.
- **Failure:** If PR creation fails (no remote, auth error), set phase to `blocked`

---

## Backwards Transitions

Valid: `implement → plan`, `code_review → plan`

When triggered:

1. Log the reason
2. **Code handling:** Warn user that existing code may conflict. Present options:
   - (a) Keep all existing code on the branch
   - (b) Revert specific commits
   - (c) Create a new branch from the default branch
3. Log the user's choice
4. Reset phases from `plan` onward to `pending`
5. Re-enter Phase 2

---

## Phase Retry

If any phase fails:

1. Log failure reason in state file
2. Set phase status to `blocked` with blocker description
3. Present error and suggest resolution
4. On next invocation, retry from the beginning of the blocked phase

---

## Feature Abandonment

1. Set `status: abandoned`
2. Log reason and timestamp
3. Archive the state file and plan file: `mkdir -p docs/archive/dev-cycle docs/archive/plans`, then `git mv` both to their archive locations. Commit with `chore(dev-cycle): archive {slug} (abandoned)`.
4. Feature branch (if any) is not auto-deleted
5. Cannot be resumed — start a new feature to restart
