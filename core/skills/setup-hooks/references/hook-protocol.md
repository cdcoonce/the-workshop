# Claude Code Hook Protocol Reference

Hooks are Python scripts that Claude Code runs at specific points in the tool execution lifecycle. They receive context via stdin and communicate results through exit codes and stderr.

## Hook Types

| Type | When it runs | Can block? | Exit code meaning |
|------|-------------|------------|-------------------|
| **PreToolUse** | Before a tool executes | Yes | 0 = allow, non-zero = block |
| **PostToolUse** | After a tool executes | No | Ignored by Claude Code |

## Stdin JSON Schema

Claude Code pipes a JSON object to the hook's stdin. The structure varies slightly by hook type, but the core fields are consistent.

### Common Fields

```json
{
  "tool_name": "Edit",
  "tool_input": {
    "file_path": "/path/to/file.py",
    "command": "...",
    "content": "..."
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `tool_name` | string | Name of the tool being invoked (e.g., `Edit`, `Write`, `Bash`, `Read`) |
| `tool_input` | object | Tool-specific input parameters |

### Tool Input Fields by Tool

| Tool | `tool_input` fields |
|------|-------------------|
| **Edit** | `file_path`, `old_string`, `new_string` |
| **Write** | `file_path`, `content` |
| **Bash** | `command` |
| **Read** | `file_path` |

### Reading Stdin

Every hook must read the JSON from stdin using `json.load(sys.stdin)`:

```python
import json
import sys

data = json.load(sys.stdin)
file_path = data.get("tool_input", {}).get("file_path", "")
```

## Exit Code Meanings

### PreToolUse Hooks

| Exit code | Effect |
|-----------|--------|
| **0** | Allow the tool to proceed |
| **Non-zero** (e.g., 2) | Block the tool from executing |

When a PreToolUse hook exits non-zero, Claude Code cancels the tool invocation. The message printed to stderr is shown to Claude as the reason for the block.

### PostToolUse Hooks

| Exit code | Effect |
|-----------|--------|
| **Any** | Ignored — PostToolUse hooks cannot block |

PostToolUse hooks run side effects (formatting, linting, logging). Their exit codes do not affect Claude Code's behavior.

## Matcher Syntax

Matchers define which tools trigger a hook. They use pipe-separated tool names in the hook configuration:

| Matcher | Tools matched |
|---------|--------------|
| `Edit\|Write` | File modification tools |
| `Bash` | Shell command execution |
| `Read` | File reading |
| `Edit\|Write\|Read` | Multiple tools combined |

Matchers appear in the `.claude/settings.json` configuration file:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "python3 .claude/hooks/protect-files.py"
          }
        ]
      }
    ]
  }
}
```

## Stderr Messaging

Hooks communicate status messages to Claude via stderr. Use `print("...", file=sys.stderr)`:

```python
print(f"Blocked: {file_path} matches protected pattern '{pattern}'", file=sys.stderr)
```

- **PreToolUse**: stderr messages explain why a tool was blocked (or allowed).
- **PostToolUse**: stderr messages report what side effects were performed.

Do not use stdout for messages — Claude Code reads stdout for structured data in some contexts.

## Environment Variables

| Variable | Value | Usage |
|----------|-------|-------|
| `$CLAUDE_PLUGIN_ROOT` | Absolute path to the plugin's root directory | Reference hook scripts packaged inside a plugin |

**Note:** `$CLAUDE_PLUGIN_ROOT` is used by plugin-packaged hooks (hooks shipped inside a `.claude-plugin/` distribution). For user-created hooks in `.claude/hooks/`, use project-relative paths instead:

```
python3 .claude/hooks/my-hook.py
```

## Annotated Examples

### Example 1: PreToolUse — File Protection (protect-files.py)

This hook blocks edits to sensitive or generated files. It runs before `Edit` or `Write` tools execute.

```python
#!/usr/bin/env python3
"""Pre-edit hook: block edits to sensitive/generated files."""

import json
import sys

# 1. Read the JSON payload from stdin
data = json.load(sys.stdin)

# 2. Extract the file path from tool_input
file_path = data.get("tool_input", {}).get("file_path", "")

# 3. If no file path, allow (nothing to protect)
if not file_path:
    sys.exit(0)

# 4. Define patterns to protect
PROTECTED_PATTERNS = [".env", "package-lock.json", "uv.lock", "node_modules/", ".git/"]

# 5. Check each pattern — block on match
for pattern in PROTECTED_PATTERNS:
    if pattern in file_path:
        # Print block reason to stderr (shown to Claude)
        print(f"Blocked: {file_path} matches protected pattern '{pattern}'", file=sys.stderr)
        # Exit non-zero to block the tool
        sys.exit(2)

# 6. Implicit exit 0 — allow the tool to proceed
```

**Key points:**
- Exit 0 = allow, exit non-zero = block
- Block messages go to stderr
- Check `tool_input.file_path` for file-targeting tools

### Example 2: PostToolUse — Auto-Format and Lint (post-edit-lint.py)

This hook auto-formats Python files with Ruff after edits. It runs after `Edit` or `Write` tools complete.

```python
#!/usr/bin/env python3
"""Post-edit hook: auto-format and lint Python files with Ruff."""

import json
import os
import shutil
import subprocess
import sys

# 1. Read the JSON payload from stdin (same pattern as PreToolUse)
data = json.load(sys.stdin)
file_path = data.get("tool_input", {}).get("file_path", "")

if not file_path:
    sys.exit(0)

actions = []


def run(cmd, label):
    """Run a command silently, ignoring failures."""
    try:
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode == 0:
            actions.append(label)
    except FileNotFoundError:
        pass


# 2. Run formatters on Python files (only if tool is available)
if file_path.endswith(".py") and shutil.which("ruff"):
    run(["ruff", "check", "--fix", file_path], "ruff-check")
    run(["ruff", "format", file_path], "ruff-format")

# 3. Report what ran to stderr
if actions:
    print(f"Hook ran: {', '.join(actions)} on {os.path.basename(file_path)}", file=sys.stderr)

# 4. Exit code is ignored for PostToolUse — no need to explicitly set it
```

**Key points:**
- Exit code is ignored (PostToolUse cannot block)
- Use `subprocess.run` for side effects
- Check tool availability with `shutil.which` before calling
- Report actions to stderr for visibility

## Hook Script Template

Use this as a starting point for new hooks:

```python
#!/usr/bin/env python3
"""<Hook type> hook: <what it does>."""

import json
import sys

data = json.load(sys.stdin)
file_path = data.get("tool_input", {}).get("file_path", "")

if not file_path:
    sys.exit(0)

# --- Your logic here ---

# For PreToolUse: sys.exit(0) to allow, sys.exit(2) to block
# For PostToolUse: exit code is ignored
```
