# Hook Conventions

## stdin Format

Hook scripts receive a JSON object on stdin with the tool call details:

```json
{
  "tool_name": "Edit",
  "tool_input": {
    "file_path": "/absolute/path/to/file.py",
    "old_string": "...",
    "new_string": "..."
  }
}
```

Fields vary by tool. Common fields:

- `Edit` / `Write` — `file_path`, `old_string`, `new_string` (Edit) or `content` (Write)
- `Bash` — `command`, `description`

## Exit Codes

| Code  | Meaning | Effect                                                                        |
| ----- | ------- | ----------------------------------------------------------------------------- |
| 0     | Pass    | Hook passes, tool execution continues                                         |
| 2     | Block   | **PreToolUse only.** Tool call is blocked. Message on stderr shown to Claude. |
| Other | Error   | Hook failure is reported but does not block                                   |

- **PreToolUse** hooks use exit code 2 to block. Print the reason to stderr.
- **PostToolUse** hooks cannot block (tool already ran). Print diagnostics to stderr.

## Matcher Syntax

Matchers specify which tool(s) trigger the hook:

| Pattern       | Matches         |
| ------------- | --------------- |
| `Edit`        | Only Edit tool  |
| `Write`       | Only Write tool |
| `Edit\|Write` | Edit or Write   |
| `Bash`        | Only Bash tool  |
| `*`           | All tools       |

## Python Script Template

### PreToolUse (blocking)

```python
#!/usr/bin/env python3
"""Pre-tool hook: <describe what it checks>."""

import json
import sys

data = json.load(sys.stdin)
tool_input = data.get("tool_input", {})
file_path = tool_input.get("file_path", "")

# --- Your logic here ---
# To block: print reason to stderr, exit 2
# To allow: exit 0

if should_block:
    print(f"Blocked: {reason}", file=sys.stderr)
    sys.exit(2)
```

### PostToolUse (non-blocking)

```python
#!/usr/bin/env python3
"""Post-tool hook: <describe what it does>."""

import json
import subprocess
import sys

data = json.load(sys.stdin)
tool_input = data.get("tool_input", {})
file_path = tool_input.get("file_path", "")

# --- Your logic here ---
# Run formatters, linters, notifications, etc.
# Print actions taken to stderr for visibility.

if actions:
    print(f"Hook ran: {', '.join(actions)}", file=sys.stderr)
```

## Example Hooks

### Block edits to .env files (PreToolUse)

```python
#!/usr/bin/env python3
import json, sys
data = json.load(sys.stdin)
path = data.get("tool_input", {}).get("file_path", "")
if ".env" in path:
    print(f"Blocked: {path} is a protected file", file=sys.stderr)
    sys.exit(2)
```

### Auto-format Python with Ruff (PostToolUse)

```python
#!/usr/bin/env python3
import json, shutil, subprocess, sys
data = json.load(sys.stdin)
path = data.get("tool_input", {}).get("file_path", "")
if path.endswith(".py") and shutil.which("ruff"):
    subprocess.run(["ruff", "check", "--fix", path], capture_output=True)
    subprocess.run(["ruff", "format", path], capture_output=True)
    print(f"Hook ran: ruff on {path}", file=sys.stderr)
```
