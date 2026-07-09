#!/usr/bin/env python3
"""SubagentStart hook: record a git baseline for the evidence check at stop.

Pairs with verify-subagent-evidence.py (SubagentStop). Side-effect only —
SubagentStart supports no blocking/decision control — so this always exits 0.
Fails open: outside a git repo, or on any git error, there's simply nothing
to snapshot and the paired stop hook will no-op too.
"""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

try:
    data = json.load(sys.stdin)
except json.JSONDecodeError:
    sys.exit(0)

cwd = Path(data.get("cwd") or ".").resolve()
agent_id = data.get("agent_id")
if not agent_id:
    sys.exit(0)


def git_dir(project_dir: Path):
    try:
        result = subprocess.run(
            ["git", "-C", str(project_dir), "rev-parse", "--absolute-git-dir"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip())


def head_sha(project_dir: Path):
    try:
        result = subprocess.run(
            ["git", "-C", str(project_dir), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def working_tree_signature(project_dir: Path):
    try:
        status = subprocess.run(
            ["git", "-C", str(project_dir), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if status.returncode != 0:
        return ""
    hasher = hashlib.sha256()
    hasher.update(status.stdout.encode("utf-8", "surrogateescape"))
    for line in status.stdout.splitlines():
        path_part = line[3:]
        if " -> " in path_part:
            path_part = path_part.split(" -> ")[-1]
        path_part = path_part.strip('"')
        try:
            hasher.update((project_dir / path_part).read_bytes())
        except OSError:
            pass
    return hasher.hexdigest()


repo_git_dir = git_dir(cwd)
if repo_git_dir is None:
    sys.exit(0)

state_file = repo_git_dir / "claude-workflow-subagent-gate" / f"{agent_id}.txt"
try:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(f"{head_sha(cwd)}\n{working_tree_signature(cwd)}\n")
except OSError:
    pass

sys.exit(0)
