#!/usr/bin/env python3
"""ConfigChange hook: audit-log and surface mid-session config file changes.

`ConfigChange` fires whenever a project/local settings file or a skill/command
file changes during a session, from any source — the user's editor, Claude's
own Edit tool (e.g. via the update-config skill), or an external process a
task happened to run. The event gives no content diff, only the file path and
source type, so it can't distinguish a legitimate edit from a malicious one.

That ambiguity is why this doesn't block: a hard block here would fight the
repo's own update-config skill, which legitimately rewrites .claude/settings.json
on the user's behalf. Instead this logs every change (for after-the-fact
review, e.g. during a review-contributor-pr session where an untrusted PR's
code ran) and surfaces a visible warning so a silent, unattended rewrite of
hooks/permissions never goes unnoticed in the transcript.

Fails open: any git/filesystem error still lets the session proceed, logging
best-effort.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    data = json.load(sys.stdin)
except json.JSONDecodeError:
    sys.exit(0)

if not isinstance(data, dict):
    # Fail open: a payload that isn't a JSON object isn't ours to act on.
    sys.exit(0)

config_source = data.get("config_source", "unknown")
file_path = data.get("file_path", "")
cwd = Path(data.get("cwd") or ".").resolve()

if not file_path:
    sys.exit(0)

try:
    from _git_baseline import git_dir
except ImportError:
    # Fail open: the helper module ships alongside every hook, but a stale or
    # partial install must no-op rather than crash the user's tool path.
    sys.exit(0)


repo_git_dir = git_dir(cwd)
log_path = (
    repo_git_dir / "the-workshop-config-audit.log"
    if repo_git_dir is not None
    else None
)

entry = {
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "source": config_source,
    "file_path": file_path,
    "session_id": data.get("session_id"),
}

if log_path is not None:
    try:
        with log_path.open("a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass

print(
    json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "ConfigChange",
            },
            "systemMessage": (
                f"Config file changed mid-session: {file_path} ({config_source}). "
                "If you didn't request this, investigate before continuing."
            ),
        }
    )
)
sys.exit(0)
