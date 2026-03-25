# Claude Workflow Template System

This file is auto-loaded every conversation. It defines how Claude should work in this repo.

## What This Repo Is

A template system for Claude Code plugin configurations. It builds self-contained plugin directories (with `.claude-plugin/plugin.json`, skills, agents, hooks, and settings) for new projects.

See [.claude/docs/project.md](.claude/docs/project.md) for detailed project context (tech stack, data flow, architecture patterns).

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

## Methodology

### TDD — Test-Driven Development

Write the test first. Watch it fail. Write minimal code to pass.
Full process: [core/docs/tdd.md](core/docs/tdd.md)

### Root Cause Tracing

Never fix at the symptom. Trace backward to the original trigger.
Full process: [core/docs/root-cause-tracing.md](core/docs/root-cause-tracing.md)

### Subagent-Driven Development

Dispatch a fresh subagent per task with code review between each.
Full process: [core/docs/subagent-development.md](core/docs/subagent-development.md)

### Parallel Agent Dispatch

When 3+ unrelated failures need investigation, dispatch one agent per problem domain.
Full process: [core/docs/parallel-agents.md](core/docs/parallel-agents.md)

## Code Style

- Descriptive variable names (`private_key_bytes` not `pkb`)
- SOLID, DRY, YAGNI — simplicity over complexity
- Type hints on all function signatures
- Numpy-style docstrings for public functions

## Planning

Write plans to `docs/plans/{file_name}.md`. Archive completed plans to `docs/archive/`.

## Skills

Skills are provided by the `claude-tooling` plugin (enabled in `.claude/settings.json`).
Source templates live in `core/skills/` (universal) and `presets/*/skills/` (preset-specific).
See core CLAUDE.md for skill trigger conditions.

## Agents

Agents are specialized role definitions (`AGENT.md` with YAML frontmatter) that give subagents domain expertise. Each agent is self-contained -- skills are declared directly in the agent's frontmatter via `skills.add`/`skills.remove`.

- `core/agents/` — Universal agents: `tdd-implementer` (implementer), `code-reviewer` (reviewer)
- `presets/*/agents/` — Preset-specific agents (e.g., `api-builder`, `security-reviewer`)

### Agent file format

```yaml
---
name: agent-name # Must match directory name
description: one-liner # Used for convention-based matching
role: implementer # implementer or reviewer
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
