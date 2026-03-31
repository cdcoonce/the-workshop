---
name: setup-hooks
description: >
  Set up Claude Code hooks for the current project. Use when user wants to add
  custom hooks, create PreToolUse or PostToolUse handlers, automate tool-triggered
  actions, or mentions "hooks", "hook setup", or /setup-hooks.
---

# Setup Claude Code Hooks

Scaffold a Claude Code hook through a guided interview. Collects event type, tool matcher, and desired behavior, then hands off to script generation.

Read [hook-protocol.md](references/hook-protocol.md) before proceeding. It defines the stdin JSON schema, exit code semantics, matcher syntax, and annotated examples you will need to generate correct hooks.

## Prerequisites

Before proceeding, verify:

1. **`.claude/` directory exists** — check for a `.claude/` directory in the project root. If not found, inform the user and stop.
2. **Python available** — run `python3 --version` (or `python --version` on Windows) to confirm Python is installed. Hooks are Python scripts.

If prerequisites fail, inform the user what is missing and how to fix it.

## Step 1: Event Type

Use `AskUserQuestion` to ask which hook event type the user needs. Provide these options:

- **PreToolUse (Recommended)** — Runs BEFORE a tool executes. Can BLOCK the operation by exiting non-zero. Use for: file protection, input validation, policy enforcement, preventing edits to specific files or patterns.
- **PostToolUse** — Runs AFTER a tool executes. Cannot block. Use for: auto-formatting, linting, logging, notifications, running fixers on modified files.

If the user is unsure, recommend PreToolUse — it covers the most common use case (protecting files from unwanted changes).

Record the selection for use in later phases.

## Step 2: Matcher Pattern

Use `AskUserQuestion` to ask which tools should trigger this hook. Offer these preset options:

- **Edit|Write (Recommended)** — Triggers on file modification tools. Most common choice for both protection and formatting hooks.
- **Bash** — Triggers on shell command execution. Use for command validation or post-command cleanup.
- **Read** — Triggers on file reading. Use for access logging or sensitive file detection.
- **Other** — Custom matcher pattern. Ask the user to type a pipe-separated tool list (e.g., `Edit|Write|Read`).

If the user selects "Other", follow up with a free-text `AskUserQuestion` asking them to provide their custom matcher pattern.

Record the matcher pattern for use in later phases.

## Step 3: Behavior Description

Use `AskUserQuestion` to ask the user to describe what the hook should do. This is a free-text question — do not offer multiple choice options.

Prompt: "Describe the behavior you want this hook to perform. Be specific about what conditions should trigger action and what the action should be. For example: 'Block edits to any file in the migrations/ directory' or 'Run black formatter on Python files after they are edited'."

Record the behavior description for use in later phases.

## Summary

After collecting all three answers, present a summary to the user:

- **Event type**: PreToolUse or PostToolUse
- **Matcher**: the selected tool pattern
- **Behavior**: the user's description

Confirm the user is satisfied before proceeding to script generation.

## Step 4: Generate Hook Script

Create the `.claude/hooks/` directory if it does not exist. Run `mkdir -p .claude/hooks/` via Bash.

Choose a descriptive script name based on the user's behavior description (e.g., `block-migration-edits.py`, `auto-format-python.py`).

**Name collision check**: Before writing the script, check if a file with the chosen name already exists in `.claude/hooks/`. If it does, use `AskUserQuestion` to ask the user to:

- **Overwrite** the existing file
- **Rename** — provide a different name
- **Cancel** — stop without creating anything

If the user cancels, stop and inform them that no files were created.

Generate a Python script using this canonical template:

```python
#!/usr/bin/env python3
"""{DOCSTRING} — describes what the hook does"""

import json
import sys

data = json.load(sys.stdin)
file_path = data.get("tool_input", {}).get("file_path", "")

if not file_path:
    sys.exit(0)

# {BEHAVIOR_LOGIC} — the user's described behavior translated to Python
```

**For Bash-triggered hooks**: The template above extracts `file_path`, which is not present in Bash tool input. Instead, extract `data.get("tool_input", {}).get("command", "")` and adapt the early-exit guard to check `command` instead of `file_path`.

Follow these rules when generating the script:

- **PreToolUse hooks**: Call `sys.exit(2)` (or another non-zero code) to block the tool. Call `sys.exit(0)` to allow it.
- **PostToolUse hooks**: Run side effects after the tool completes. The exit code is ignored. If the hook calls external tools, use `shutil.which()` to check availability first and `subprocess.run()` for execution.
- **All status messages go to stderr**: Use `print("...", file=sys.stderr)` for any output.
- **stdlib only**: The script MUST use only Python standard library modules — no pip dependencies.

Write the generated script to `.claude/hooks/{SCRIPT_NAME}` using the Write tool.

## Step 5: Wire Hook into Settings

Read `.claude/settings.json`. Handle these cases:

1. **File does not exist** — create it with this skeleton:

   ```json
   {
     "hooks": {
       "PreToolUse": [],
       "PostToolUse": []
     }
   }
   ```

2. **File exists but has no `hooks` key** — add the `hooks` key with both event arrays.

3. **File exists with `hooks` key but is missing the relevant event array** (PreToolUse or PostToolUse) — add the missing array.

Append a new entry to the appropriate event array. Do NOT replace existing entries — use append/extend semantics to preserve all existing hook configurations.

The new entry shape:

```json
{
  "matcher": "{MATCHER_PATTERN}",
  "hooks": [
    {
      "type": "command",
      "command": "python3 .claude/hooks/{SCRIPT_NAME}"
    }
  ]
}
```

Write the updated JSON back to `.claude/settings.json` with 2-space indent formatting.

## Step 6: Confirm

Display a summary of what was created:

- **Hook script path**: `.claude/hooks/{SCRIPT_NAME}`
- **Event type**: PreToolUse or PostToolUse
- **Matcher pattern**: the tool matcher wired in settings.json
- **Config entry**: the entry appended to `.claude/settings.json`

Tell the user how to test: "The hook will run automatically on your next matching tool call. To test, try using the matched tool and verify the hook behavior."
