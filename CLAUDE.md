# Claude Workflow Template System

This file is auto-loaded every conversation. It defines how Claude should work in this repo.

## What This Repo Is

A template system for coding-agent plugin configurations, targeting Claude Code, Codex, and Cortex Code (CoCo) as first-class outputs. It builds self-contained plugin directories (manifests, skills, agents, hooks, and settings) for new projects.

See [ROADMAP.md](ROADMAP.md) for the multi-platform goal and design principle, [COMPATIBILITY.md](COMPATIBILITY.md) for per-platform requirements, and [.claude/docs/project.md](.claude/docs/project.md) for detailed project context (tech stack, data flow, architecture patterns).

## Architecture

- `core/` — Universal skills (17), methodology docs (4), file protection hook, agents (2)
- `presets/` — Named project type configurations (python-api, data-pipeline, full-stack, claude-tooling, analysis)
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

## Code Style

- Descriptive variable names (`private_key_bytes` not `pkb`)
- SOLID, DRY, YAGNI — simplicity over complexity
- Type hints on all function signatures
- Numpy-style docstrings for public functions

## Planning

Write plans to `docs/plans/{file_name}.md`. Archive completed plans to `docs/archive/`.

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
