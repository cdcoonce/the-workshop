---
name: dev-cycle
description: >
  Orchestrate the full GitLab-issues-driven development lifecycle.
  7-phase pipeline from brainstorm through MR with state tracking
  and cross-conversation resume. Use when user says "dev cycle",
  "development workflow", "full development pipeline", or invokes /dev-cycle.
---

# Dev Cycle Orchestrator

Orchestrate the full development lifecycle: brainstorm → plan → review → issues → implement → code review → MR.

**Disambiguation:** If the user only wants a PRD, route to `/write-a-prd`. If they only want a plan, route to `/prd-to-plan`. This skill is for the full end-to-end lifecycle.

## The 7-Phase Pipeline

Every phase is mandatory. No phase can be skipped.

| #   | Phase           | Delegates To                                           | Gate Condition                    |
| --- | --------------- | ------------------------------------------------------ | --------------------------------- |
| 1   | **Brainstorm**  | `write-a-prd`                                          | Issue URL recorded                |
| 2   | **Plan**        | `prd-to-plan`                                          | Plan file exists at `docs/plans/` |
| 3   | **CEO Review**  | `plan-ceo-review` (recommend HOLD SCOPE)               | Review complete, user approves    |
| 4   | **Issues**      | Orchestrator (plan slices → GitLab issues)             | All issue URLs recorded           |
| 5   | **Implement**   | Orchestrator (`tdd` per issue, `subagent-development`) | All issues resolved, tests pass   |
| 6   | **Code Review** | `daa-code-review`                                      | Clean review                      |
| 7   | **MR**          | `commit` + `gitlab-cli`                                | MR URL recorded                   |

## Re-entry Logic

On every invocation:

### No arguments (`/dev-cycle`)

1. Scan `docs/dev-cycle/` for `*.state.md` files with `status: in_progress`
2. If one → ask: "Resume **{feature}** (`{branch}`)? Currently at **{phase}**."
3. If multiple → list with branch names, ask which to resume
4. If none → ask: "What feature are you working on?" → start Phase 1

### With argument (`/dev-cycle {slug}`)

1. Look for `docs/dev-cycle/{slug}.state.md`
2. Found → resume at `current_phase`
3. Not found → create state file, start Phase 1

### Slug Collision

When creating a new state file, check `docs/dev-cycle/` for existing slugs. If the slug already exists (abandoned or completed), suffix with `-2`, `-3`, etc.

### Context Loading on Resume

Before continuing, load ALL referenced artifacts:

- **Brainstorm:** `glab issue view` the PRD issue
- **Plan:** Read plan file from disk
- **CEO Review:** Read the plan file (includes review revisions)
- **Issues:** `glab issue view` each implementation issue
- **Implement:** Check git status on feature branch, review closed issues

Present summary: "Resuming **{feature}** at **{phase}**. Here's where we left off: ..."

## Phase Execution

### Phase 1: Brainstorm

Invoke `write-a-prd`. Trust the skill's internal flow (interview → PRD → GitLab issue). Record the issue URL in the state file. **Do not commit** the state file — it stays as a working change on main.

### Phase 2: Plan

Pass the PRD issue URL to `prd-to-plan`. Record the plan file path (at `docs/plans/{feature}.md`). **Do not commit** the plan file or state file — both stay as working changes.

### Phase 3: CEO Review

Pass plan file path to `plan-ceo-review`. Recommend HOLD SCOPE mode but let the skill's own mode selection (Step 0F) run. Record when review is complete and user approves. **Do not commit** — plan revisions remain working changes.

### Phase 4: Issues

**Owned by the orchestrator.** Read the plan's vertical slices. For each slice, create a GitLab issue using `glab issue create` that:

- References the PRD issue
- Includes acceptance criteria from the plan
- Is created in dependency order

Record each issue URL in the Issues table immediately after creation. See [references/phase-transitions.md](references/phase-transitions.md) for partial-completion recovery.

### Phase 5: Implement

**Owned by the orchestrator.** Before dispatching any implementation work, commit and push all planning artifacts so they land on main — not the feature branch:

1. **Stage planning artifacts only:**
   ```
   git add docs/dev-cycle/{slug}.state.md docs/plans/{feature}.md
   ```
2. **Single commit:** `docs(dev-cycle): plan and state for {feature-slug}`
3. **Push to origin:** `git push origin main` (or current default branch) so the planning commits are on remote before branching
4. **Create feature branch:** `feat/{feature-slug}` from the updated HEAD (see branch handling in [references/phase-transitions.md](references/phase-transitions.md))

Before dispatching, resolve agent identities from **both** sources:

1. **Plugin agents (primary):** Check the Agent tool's available `subagent_type` values listed in the system prompt (e.g., `data-pipeline:tdd-implementer:tdd-implementer`, `data-pipeline:code-reviewer:code-reviewer`). These are the authoritative source for plugin-provided agents.
2. **Local agents:** Scan `.claude/agents/` for any locally-defined agent directories (each containing an `AGENT.md`). Read the YAML frontmatter to determine role (`implementer` or `reviewer`).
3. **Match implementers:** For each implementation issue, prefer a `subagent_type` whose name contains `tdd-implementer` or similar implementer role. If none found, check local agents with `role: implementer`.
4. **Match reviewer:** Prefer a `subagent_type` whose name contains `code-reviewer`. If none found, check local agents with `role: reviewer`.
5. **Fall back:** When no matching agent exists in either source, use `general-purpose` as the subagent type.

Dispatch one subagent per GitLab issue following `subagent-development` methodology:

- Each subagent is dispatched with its matched `subagent_type` (not a generic agent with an injected prompt)
- Code review runs between each subagent dispatch, using the matched reviewer `subagent_type`
- State file is updated after each subagent completes (not batched)

Log per-subagent events:

- `"Subagent started for issue #N: {title}"`
- `"Subagent completed for issue #N: {pass/fail}"`
- `"Code review after issue #N: {clean/blocking issues found}"`

### Phase 6: Code Review

Invoke `daa-code-review` against all changed files on the feature branch. If blocking issues found → fix, re-run. Loop until clean.

If architectural issues requiring plan rework → trigger backwards transition to Phase 2.

### Phase 7: MR

Check for conflicts with default branch first. Invoke `commit` for conventional commit, then `gitlab-cli` to open MR. Include `Closes #N` for the PRD issue and all implementation issues in the MR description so GitLab auto-closes them on merge. Record MR URL, set `status: completed`. Then run the archival step (see Archival below).

## State File

Each feature tracked at `docs/dev-cycle/{feature-slug}.state.md`. See [references/state-file-schema.md](references/state-file-schema.md) for full format, field definitions, and transition rules.

## Failure & Recovery

See [references/phase-transitions.md](references/phase-transitions.md) for:

- Phase retry logic (blocked → retry on next invocation)
- Backwards transitions (implement/code_review → plan)
- Feature abandonment. Archived files are moved to `docs/archive/`.

## Branch Management

- **Phases 1–4:** Run on current branch (documentation only). **Do NOT commit** state files or plan docs during these phases — keep them as unstaged working changes. This prevents planning commits from polluting the feature branch history.
- **Phase 4 → 5 gate:** Before creating the feature branch, commit all planning artifacts in a single commit and push to origin (see Phase 5 for exact steps).
- **Phase 5:** Creates `feat/{feature-slug}` branch from the updated, pushed main
- **Phase 7:** MRs to the default branch (detected via `glab repo view --output json`)
- **Resume at Phase 5+:** Check out feature branch if not already on it

## Archival

When a feature reaches a terminal state (`completed` or `abandoned`), archive its artifacts:

1. Create archive directories: `mkdir -p docs/archive/dev-cycle docs/archive/plans`
2. Move the state file: `git mv docs/dev-cycle/{slug}.state.md docs/archive/dev-cycle/`
3. Move the plan file: read the plan path from the artifacts table, then `git mv {plan_path} docs/archive/plans/`
4. Commit the moves with message: `chore(dev-cycle): archive {slug}`

Archival runs automatically:

- At the end of Phase 7 (after MR URL is recorded and status is set to `completed`)
- On feature abandonment (after status is set to `abandoned`)
