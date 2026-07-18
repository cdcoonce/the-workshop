---
name: project-context
description: >
  Generate or update the `.claude/docs/project.md` file that gives Claude project-specific
  context. Use this skill when the user asks to create, update, regenerate, or refresh
  project context, or says things like "update project.md", "generate project context",
  "this repo needs a project.md", or "Claude doesn't know about this project". Also trigger
  when onboarding Claude to a new repository for the first time.
---

# Project Context Generator

Create or update `.claude/docs/project.md` — the concise project reference `CLAUDE.md` auto-loads every conversation. Unlike a README (written for humans), project.md is written for Claude: dense, factual, no marketing prose. When it's missing or stale, Claude wastes turns re-discovering the tech stack, test commands, and architecture — this skill automates that discovery.

## Workflow

### Step 1: Analyze the codebase

Run a structured three-phase analysis to gather project facts. Tag every fact with a confidence level: `[confirmed]` (read from source), `[inferred-high]` (strong evidence), `[inferred-low]` (partial evidence), or `[unknown]`.

See [references/analysis-methodology.md](references/analysis-methodology.md) for detailed tool actions, glob/grep patterns, and record templates.

**Phase 1 — Project Metadata:** Glob for package manager files, env templates, CI configs, and toolchain files. Extract: project name, language, Python version, dependencies (with purposes), scripts/commands, environment variables, CI stages, test markers.

**Phase 2 — Architecture Scan:** Glob for all source files. Identify entry points, build the import graph, classify modules (core/leaf/orchestrator), and identify the architecture pattern. Read config files referenced by source code.

**Phase 3 — Data Sources & Infrastructure:** Identify external data sources (databases, APIs, files), output targets (files, uploads, APIs), test structure, and custom exception hierarchy.

### Step 2: Ask clarifying questions

After analysis, ask the user about `[inferred-low]` and `[unknown]` items. Keep it focused — don't ask about things you already know. Common gaps: project purpose (if not obvious from code), data sources (what feeds in, what receives output), deployment (local, scheduled, cloud). A straightforward codebase may need only 1-2 questions, or none.

### Step 3: Generate project.md

Write the file following the structure in [references/analysis-methodology.md](references/analysis-methodology.md#output-structure) — scale depth to match the project; small projects may skip sections, complex projects may add subsections. If `.claude/docs/project.md` already exists, confirm with the user before overwriting.

## Writing Guidelines

- **Dense over verbose.** Every line should earn its place — no motivation or context-setting, just facts.
- **Specific over generic.** "Run `uv run pytest -m 'not snowflake'`" beats "Run the tests excluding external dependencies."
- **One sentence per pattern.** Architecture patterns should be one line each — name, file, explanation.
- **Real commands.** Copy test commands from `pyproject.toml` or CI configs, not paraphrased versions.
- **Annotate dependencies.** Don't just list `polars` — say `polars — high-performance DataFrames`.
- **Data sources are critical.** List every database, API, and file source Claude needs to know about.
- **Keep it under 100 lines.** If project.md exceeds ~100 lines, it's too detailed — move specifics to dedicated docs and link to them.

## Output

Save as `.claude/docs/project.md` (create the directory if needed). If the file already exists, show the user a diff summary before overwriting.

After generating, check if `CLAUDE.md` references it. If not, suggest adding:

```markdown
See [.claude/docs/project.md](.claude/docs/project.md) for project-specific details (tech stack, architecture, test markers).
```
