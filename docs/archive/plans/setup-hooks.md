# Plan: setup-hooks skill

> Source PRD: https://gitlab.com/Charles.Coonce/claude-workflow/-/work_items/20

## Architectural decisions

Durable decisions that apply across all phases:

- **Skill location**: `core/skills/setup-hooks/` (core skill, included in all presets via `core.skills: "all"`)
- **Skill files**: `SKILL.md` (main definition) + `references/hook-protocol.md` (protocol reference)
- **Generated hook path**: `.claude/hooks/{descriptive-name}.py` in the user's project
- **Config target**: `.claude/settings.json` under `hooks.PreToolUse[]` or `hooks.PostToolUse[]`
- **Hook entry shape**: `{ "matcher": "<Tool|Tool>", "hooks": [{ "type": "command", "command": "python3 .claude/hooks/{name}.py" }] }`
- **Script contract**: `#!/usr/bin/env python3`, reads `json.load(sys.stdin)`, stdlib only, messages on stderr, exit codes for control flow (PreToolUse: non-zero blocks; PostToolUse: exit code ignored)
- **Interview tool**: AskUserQuestion for all user-facing questions
- **Canonical examples**: `core/hooks/protect-files.py` (PreToolUse pattern), `presets/*/hooks/post-edit-lint.py` (PostToolUse pattern)
- **Settings skeleton** (when settings.json is absent): `{ "hooks": { "PreToolUse": [], "PostToolUse": [] } }`
- **Name collision handling**: If generated script name already exists in `.claude/hooks/`, ask the user (overwrite, rename, or cancel)
- **Matcher presets**: Interview offers common matchers as AskUserQuestion options (`Edit|Write`, `Bash`, `Read`) plus free-text via "Other"

---

## Phase 1: Hook protocol reference and skill interview flow

**User stories**: 1, 2, 3, 13, 14

### What to build

Create the `core/skills/setup-hooks/` directory with two files:

1. **`references/hook-protocol.md`** — Complete reference documenting the Claude Code hook protocol:
   - Stdin JSON schema for PreToolUse and PostToolUse events (the `tool_input` structure)
   - Exit code meanings (0 = allow, non-zero = block for PreToolUse; ignored for PostToolUse)
   - Matcher syntax (pipe-separated tool names: `Edit|Write`, `Bash`, etc.)
   - Stderr messaging conventions
   - The `$CLAUDE_PLUGIN_ROOT` environment variable
   - Annotated examples from the two canonical hook scripts

2. **`SKILL.md`** — Skill definition with YAML frontmatter and the interview section:
   - Frontmatter: name, description, trigger conditions
   - Prerequisites check (`.claude/` directory exists)
   - Interview flow using AskUserQuestion:
     - Question 1: Event type (PreToolUse vs PostToolUse) with guidance on when to use each
     - Question 2: Matcher pattern — offer common presets (`Edit|Write`, `Bash`, `Read`) as AskUserQuestion options, plus "Other" for custom input
     - Question 3: Natural language description of desired behavior

### Acceptance criteria

- [ ] `core/skills/setup-hooks/SKILL.md` exists with valid YAML frontmatter (name, description)
- [ ] `core/skills/setup-hooks/references/hook-protocol.md` exists and documents stdin JSON schema, exit codes, and matcher syntax
- [ ] Reference doc includes annotated examples from both canonical hook scripts
- [ ] SKILL.md interview section uses AskUserQuestion with 2-4 options per question
- [ ] `uv run python -m scripts.smoke_test data-pipeline` passes (skill included in build)

---

## Phase 2: Script generation and config wiring

**User stories**: 4, 5, 6, 7, 8, 9, 10, 11, 12

### What to build

Extend `SKILL.md` with the generation and wiring sections that follow the interview:

1. **Script generation instructions** — After the interview, the skill directs Claude to:
   - Create `.claude/hooks/` directory if it doesn't exist
   - Check if a script with the generated name already exists; if so, ask the user to overwrite, rename, or cancel
   - Generate a Python script using a canonical template with placeholders:
     ```
     #!/usr/bin/env python3
     """{DOCSTRING}"""

     import json
     import sys

     data = json.load(sys.stdin)
     file_path = data.get("tool_input", {}).get("file_path", "")

     if not file_path:
         sys.exit(0)

     {BEHAVIOR_LOGIC}
     ```
     - PreToolUse scripts exit non-zero to block, zero to allow
     - PostToolUse scripts run side effects and exit zero
     - Status messages go to stderr: `print("...", file=sys.stderr)`
   - Name the script descriptively based on the behavior (e.g., `block-migration-edits.py`)

2. **Config wiring instructions** — The skill directs Claude to:
   - Read existing `.claude/settings.json` (or create `{ "hooks": { "PreToolUse": [], "PostToolUse": [] } }` if absent)
   - Append a new hook entry to the appropriate event array (PreToolUse or PostToolUse)
   - Preserve all existing hook entries (extend, not replace)
   - Write the updated config back

3. **Summary output** — After generation, display what was created:
   - Hook script path
   - Config entry added
   - How to test the hook

### Acceptance criteria

- [ ] SKILL.md contains complete script generation instructions referencing the hook protocol
- [ ] SKILL.md contains config wiring instructions that append (not replace) hook entries
- [ ] SKILL.md includes a summary/confirmation section showing what was created
- [ ] Generated scripts follow the canonical patterns (stdin parsing, exit codes, stderr messaging)
- [ ] Config wiring preserves existing hooks in settings.json
- [ ] End-to-end: invoking `/setup-hooks` in a test project produces a working hook script and valid settings.json entry

---

## CEO Review Findings (HOLD SCOPE)

Review date: 2026-03-31. Mode: HOLD SCOPE. 4 issues found and resolved:

| # | Issue | Decision | Applied To |
|---|-------|----------|------------|
| 1 | No settings.json skeleton when file absent | Specify exact JSON: `{ "hooks": { "PreToolUse": [], "PostToolUse": [] } }` | Arch decisions + Phase 2 |
| 2 | Hook script name collision unhandled | Ask user: overwrite, rename, or cancel | Arch decisions + Phase 2 |
| 3 | Matcher patterns need guided input | Offer common presets (`Edit\|Write`, `Bash`, `Read`) + "Other" via AskUserQuestion | Arch decisions + Phase 1 |
| 4 | Generation instructions underspecified | Added canonical script template with placeholders | Phase 2 |
