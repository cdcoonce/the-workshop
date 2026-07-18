---
name: create-hook
description: >
  Create and register Claude Code hooks (PreToolUse, PostToolUse) as Python
  scripts. Use when user wants to create a hook, add a pre-edit check,
  post-edit formatter, block file edits, or automate responses to tool use.
---

# Create Hook

Create a Claude Code hook through an interview, generate the Python script, and register it in `.claude/settings.json`.

## Interview

Use `AskUserQuestion` to gather requirements. Batch into 2-3 calls.

### Call 1 — Hook Type & Trigger

Ask these together:

1. **Hook type**: PreToolUse (block/validate before tool runs) or PostToolUse (act after tool runs)?
2. **Matcher pattern**: Which tools should trigger this hook? Common patterns: `Edit|Write`, `Bash`, `*` (all tools). See [hook-conventions.md](references/hook-conventions.md) for full syntax.

### Call 2 — Behavior

1. **What should the hook do?** Describe the core logic — what to check, block, format, or log.
2. **For PreToolUse**: What conditions should block the tool call? What message should the user see?
3. **For PostToolUse**: What commands or actions should run? Should it report what it did?

### Call 3 — Naming (if not obvious)

1. **Hook name**: Suggest a descriptive kebab-case name based on the behavior (e.g., `protect-migrations`, `auto-format-python`). Confirm with user.

## Implementation

After the interview, generate the hook script and register it.

### Step 1 — Write the hook script

- Create `.claude/hooks/<hook-name>.py`
- Follow the Python template from [hook-conventions.md](references/hook-conventions.md)
- Read JSON from stdin, extract `tool_input` fields relevant to the matcher
- PreToolUse: use `sys.exit(2)` to block, print reason to stderr
- PostToolUse: run actions, print summary to stderr
- Keep scripts focused — one concern per hook

### Step 2 — Register in settings.json

Read `.claude/settings.json` and update the hooks configuration:

1. Parse the existing JSON
2. Navigate to `hooks.<HookType>` (e.g., `hooks.PreToolUse`)
3. Look for an existing entry with the same `matcher` value
   - **If found**: append the new hook command to that entry's `hooks` array
   - **If not found**: add a new entry to the hook type array:
     ```json
     {
       "matcher": "<pattern>",
       "hooks": [
         {
           "type": "command",
           "command": "python3 .claude/hooks/<hook-name>.py"
         }
       ]
     }
     ```
4. Write the updated JSON back with 2-space indent

### Step 3 — Inform the user

Tell the user:

- The hook script location
- What it does and when it triggers
- They need to **restart Claude Code** for the hook to take effect

### Step 4 — Keep generated docs in sync

If the repo generates docs from its components (a `make docs` target, a
`scripts/build_docs.py`, or a `docs/reference/` tree), regenerate and commit
that output with the new hook so the reference doesn't drift. Give the hook a
module docstring whose first line names its event (e.g. `"Stop hook: ..."`) —
generators read it. In the claude-workflow repo, run `make docs && make build
&& make test`; the last step gates on staleness.
