---
name: generate-claude-md
description: >
  Generate or update the root `CLAUDE.md` file that Claude auto-loads every conversation.
  Use when the user asks to create, update, or regenerate CLAUDE.md, or says things like
  "generate CLAUDE.md", "create a CLAUDE.md", "set up CLAUDE.md", or "Claude needs a
  CLAUDE.md". Also triggered by the /init-project orchestrator after project context is
  collected.
---

# Generate CLAUDE.md

Create or update the root `CLAUDE.md` file — the concise project reference that Claude auto-loads every conversation. This skill supports two modes: **orchestrated** (pre-supplied context from `/init-project`) and **standalone** (reads project.md + interviews the user).

## Step 1: Detect available context

Check whether the current conversation already contains pre-supplied interview context (tech stack, code style, methodology, commands, guardrails). This happens when `/init-project` invokes this skill after collecting answers.

- **Context found** — Record it and skip to Step 3. Do not re-ask questions the user already answered.
- **No context found** — Continue to Step 2 (standalone mode).

## Step 2: Read project.md

Read `.claude/docs/project.md` if it exists. Extract:

- Project name and description
- Tech stack and dependencies
- Project layout / directory structure
- Build, run, and test commands
- Test markers and CI configuration
- Architecture patterns

**If project.md does not exist:**

Use `AskUserQuestion` to ask the user how to proceed:

- **(A) Run /project-context first (Recommended)** — Stop this skill and suggest the user run `/project-context` to generate project.md, then re-run `/generate-claude-md`.
- **(B) Proceed without project.md** — Continue in interview-only mode. All CLAUDE.md content will come from user answers.

If the user selects (A), stop and inform them to run `/project-context` first.

## Step 3: Ask clarifying questions (standalone mode only)

For each topic below, skip it if pre-supplied context or project.md already provides the answer. Ask only about gaps — do not re-ask questions that are already answered. If all topics are covered, skip this step entirely.

For information not found in project.md and not pre-supplied, use `AskUserQuestion` to fill gaps. Ask about each missing topic separately — do not batch unrelated questions.

**Code style** (if not known): "What code style conventions does this project follow?" Offer options like:
- Naming conventions (snake_case, camelCase, etc.)
- Formatter / linter (black, ruff, prettier, eslint, etc.)
- Type hints required? Docstring style?

**Methodology** (if not known): "What development methodology does this project use?" Offer options like:
- TDD / red-green-refactor
- Trunk-based development vs. feature branches
- PR/MR review workflow

**Commands** (if not extractable from project.md or pyproject.toml): "What are the key build/run/test commands for this project?"

If project.md provided sufficient detail for a topic, do not ask about it — use what was extracted.

## Step 4: Check for existing CLAUDE.md

Check whether `CLAUDE.md` exists at the project root.

If it exists, read it and present a brief summary of what sections will change. Use `AskUserQuestion` to confirm:

- **(A) Overwrite** — Replace the existing file with the new version.
- **(B) Merge (Recommended)** — Update the standard sections (Architecture, Commands, Code Style, Methodology) but preserve any custom sections the user added manually.
- **(C) Cancel** — Stop without modifying the file.

If the user selects (C), stop and inform them that no changes were made. If (B), identify sections in the existing file that are NOT in the standard template and preserve them at the end of the regenerated file.

## Step 5: Generate CLAUDE.md

Write `CLAUDE.md` at the project root using the template below. Populate each section from project.md content, pre-supplied context, and/or user answers. Omit any section that has no content — do not leave empty headings.

```markdown
# {Project Name}

{One-sentence description of what the project does.}

See [.claude/docs/project.md](.claude/docs/project.md) for detailed project context.

## Architecture

- `{directory}/` - {purpose}
- ...one bullet per top-level directory that matters

## Commands

- `{command}` - {what it does}
- ...extracted from pyproject.toml, Makefile, package.json, or user answers

## Code Style

- {Convention or tool} - {brief detail}
- ...naming, formatting, type hints, docstrings

## Methodology

- {Practice} - {brief detail}
- ...TDD, branching, review workflow, commit conventions
```

**Rules:**

- Keep it under 60 lines. CLAUDE.md is a summary — details belong in project.md.
- Use real commands copied from config files, not paraphrased versions.
- Bold nothing — use backticks for commands and paths, plain text for everything else.
- If `.claude/docs/project.md` exists, always include the "See project.md" reference line directly below the project description.
- If project.md does not exist, omit that reference line.

## Step 6: Verify reference

After writing the file, confirm that:

1. If `.claude/docs/project.md` exists, `CLAUDE.md` contains a link to it. If the link is missing, add it below the project description.
2. The generated file has no empty sections (headings with no content below them). Remove any that slipped through.

Report to the user what was created and where: "Generated `CLAUDE.md` at the project root with sections: {list of sections included}."

## Fallback (no AskUserQuestion available)

If `AskUserQuestion` is not available in the runtime environment, present choices as formatted text:

**[Header] — [Question]**

**Recommended:** [Your recommendation and why]

**Alternatives:**

- (A) [Option] — [trade-off]
- (B) [Option] — [trade-off]
