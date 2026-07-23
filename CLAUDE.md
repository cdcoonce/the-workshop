# The Workshop

This file is auto-loaded every conversation. It defines how coding agents should work in this repo.

## What This Repo Is

A template system for coding-agent plugin configurations, targeting Claude Code, Codex, and Cortex Code (CoCo) as first-class outputs. It builds self-contained plugin directories (manifests, skills, agents, hooks, and settings) for new projects.

See [ROADMAP.md](ROADMAP.md) for the multi-platform goal and design principle, [COMPATIBILITY.md](COMPATIBILITY.md) for per-platform requirements, and [.claude/docs/project.md](.claude/docs/project.md) for detailed project context (tech stack, data flow, architecture patterns).

## Architecture

- `core/` — The shared source every package builds from: universal skills, methodology docs, safety hooks, and agents
- `presets/` — Package manifests: `workbench` (the everything package — all core skills/agents/docs/hooks plus the general preset skills and agents), `vault-ops` (domain-specific), and five `persona-*` output-style layers
- `scripts/` — Python build/smoke-test/marketplace tooling
- `dist/` — Build output (gitignored)

## Commands

- Build a preset: `uv run python -m scripts.build_preset <preset_name>`
- Build marketplace index: `uv run python -m scripts.build_marketplace`
- Smoke test: `uv run python -m scripts.smoke_test <preset_name>`
- Run tests: `uv run pytest`
- Run with coverage: `uv run pytest --cov=scripts --cov-report=term-missing`

## Syncing Shared Files Across core/ and Preset Copies

Some source files are duplicated between `core/` and one or more `presets/*/` directories (e.g. a skill or agent that every preset bundles a copy of). If you edit one of these shared/duplicated files, you must apply the same change to every copy — core and every preset that carries it — not just the copy you happened to open.

Before considering such a change done:

1. Edit the file identically in `core/` and in each preset copy.
2. Rebuild every preset: `uv run python -m scripts.build_preset <preset_name>` for each preset under `presets/`.
3. Run the smoke test on each rebuilt preset: `uv run python -m scripts.smoke_test <preset_name>`.
4. Confirm the rebuilt `dist/` output is byte-identical across preset copies of the shared file (e.g. via `diff`) — a change applied to only one copy will show up here as a divergence.

This convention exists because PR #142 fixed a bug in a shared file and had to keep all five `dist/` preset copies in sync with `core/`, verifying "every preset rebuilds byte-identically" before the fix was accepted. Skipping this step ships a fix to one copy while leaving the others silently stale.

## Avoiding Capability-Blocked Bash Calls During Unattended Execution

The `afk` executor runs slices unattended under `permission_mode = "acceptEdits"` (see `.afk/config.toml`): Edit and Write calls auto-approve, but Bash calls the harness flags as needing interactive approval — `gh`/network commands, and piped or chained (`|`, `&&`, `;`) commands — do not auto-approve, and fail immediately with no human present to grant them. A slice whose plan depends on the output of one of these calls cannot proceed once the call is rejected.

Before shelling out to `gh` (issue/PR lookup, comments, status checks) or chaining Bash commands with `|`/`&&`/`;`/`2>&1`:

1. Check whether the needed information is already in context — the issue title, body, and labels are already included in the task prompt; do not re-fetch them with `gh issue view`.
2. Prefer a single, unpiped command (`git log`, `grep`, `find`) over a chained one; run separate commands instead of combining them with a pipe.
3. If a task genuinely requires `gh`/network access or command chaining that no single unpiped Bash call can express, stop and record the gap in `.afk/question.md` rather than issuing the call and letting the slice fail.

This convention exists because issue #259 found the executor had quarantined 7 slices as `capability` — agents repeatedly issued `gh`/piped Bash calls that require interactive approval unattended execution cannot grant, instead of working from the context already provided or a simpler command.

## Escalating to .afk/question.md Only After Exhausting Available Context

This file's conventions sometimes instruct the agent to stop and write to `.afk/question.md` when it hits a specific blocker — for example, the capability-blocked Bash rule above, when a task genuinely needs `gh`/network access or command chaining no single unpiped call can express. Each such instruction is a legitimate escape hatch — but only once the blocking fact is genuinely absent from the repository, not merely absent from what the agent has read so far.

Before writing to `.afk/question.md` for any blocker:

1. Grep this file for a section that already addresses the specific blocker in front of you — do not assume a precedent exists without checking, and do not assume one is missing just because it isn't the first thing you recall.
2. Re-read the issue title, body, and labels already supplied in the task prompt; do not treat a detail restated there as missing.
3. Check `git log`/`git show` on recent `AFK: implement issue #N` commits for a directly analogous prior change this issue is extending or correcting.

Escalate only when, after this check, the blocking fact truly cannot be found anywhere in the repository — a credential, a URL not present in the issue or codebase, or a decision that trades off two valid approaches with no existing precedent to follow.

This convention exists because issue #260 found the executor had quarantined 3 slices as `question` — recurrence at this level suggested agents were treating ambiguity as a hard blocker before checking whether it was already resolved by an existing CLAUDE.md convention or by the issue text already in context.

## Code Style

- Descriptive variable names (`private_key_bytes` not `pkb`)
- SOLID, DRY, YAGNI — simplicity over complexity
- Type hints on all function signatures
- Numpy-style docstrings for public functions

## Planning

Write plans to `docs/plans/{file_name}.md`. Archive completed plans to `docs/archive/`.

## Output and Metadata Locations

Skills produce two kinds of output, and they go to two different places. Choosing
wrong either buries a repo artifact in a home directory or litters a target repo
with machine-local files.

1. **Repo-scoped artifacts** — output that describes, plans, or configures the
   target repository and is meant to be committed and reviewed alongside its code.
   These stay **inside the target repo** at their conventional paths:
   `docs/plans/` (plans), `docs/dev-cycle/*.state.md` and `docs/archive/`
   (dev-cycle state), `.claude/docs/project.md` (project context). Never relocate
   these to a home directory — a plan belongs to the repo it plans.

2. **Machine-local outputs and metadata** — output that belongs to the user or the
   machine rather than to any one repository: study documents, ingested notes,
   caches, personal indexes, and skill run-state that no target repo should carry.
   These default to **`~/.workshop/`** unless the invoking skill was given an
   explicit destination (a setting, env var, or argument). A skill in this
   category writes under a named subdirectory, e.g. `~/.workshop/transcript-notes/`,
   and treats a configured destination as authoritative when one is provided.

When adding a skill that writes output, classify it against these two categories
first. If the output is not a repo artifact, it defaults to `~/.workshop/<skill>/`;
do not invent a new home-directory location per skill.

This convention exists because an audit ahead of the first machine-local skill
(`transcript-notes`) found every existing output-writing skill correctly wrote
repo-scoped artifacts into the target repo, and no skill wrote scattered
machine-local output — so the rule codifies the split that was already implicit
before a second category of skill could diverge from it.

## Branch and Promotion Policy

- **GitHub `dev` first.** Merge completed work into `dev`; GitHub CI validates
  it and mirrors `dev` to GitLab.
- **Never push directly to `main`.** `main` is promoted only through the
  approved GitLab merge-request and CI/CD path.
- Before any push or pull request, confirm the target branch from these project
  instructions and `.github/workflows/`; do not infer it from the repository's
  default branch.

## Skills

Skills live in `core/skills/` (universal) and `presets/*/skills/` (preset-specific).
See core CLAUDE.md for skill trigger conditions.

## Agents

Agents are specialized role definitions (`AGENT.md` with YAML frontmatter) that give subagents domain expertise. Each agent is self-contained -- skills are declared directly in the agent's frontmatter via `skills.add`/`skills.remove`.

- `core/agents/` — Universal agents: `tdd-implementer` (implementer), `code-reviewer` (reviewer), `skill-analyst` (analyst), `qa-tester` (qa-tester), `skill-writer` (skill-writer), `strategy` (strategy)
- `presets/*/agents/` — Preset-specific agents (e.g., `api-builder`, `security-reviewer`)

### Agent file format

```yaml
---
name: agent-name # Must match directory name
description: one-liner # Used for convention-based matching
role: implementer # implementer | reviewer | analyst | qa-tester | skill-writer | strategy
skills:
  add: [tdd, commit]
  remove: []
---
```

### Manifest fields

- `core.agents` — `"all"` (default) or list of agent names to include
- `preset_agents` — List of preset-specific agent names (default `[]`)
- Exclusion format: `agents/<name>`
- Preset agent with same name as core agent replaces it (override semantics)
