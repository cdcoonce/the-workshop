#!/usr/bin/env python3
"""SubagentStart hook: record a git baseline for the evidence check at stop.

Pairs with verify-subagent-evidence.py (SubagentStop). Side-effect only —
SubagentStart supports no blocking/decision control — so this always exits 0.
Fails open: outside a git repo, or on any git error, there's simply nothing
to snapshot and the paired stop hook will no-op too.
"""

import json
import sys
from pathlib import Path

try:
    data = json.load(sys.stdin)
except json.JSONDecodeError:
    sys.exit(0)

if not isinstance(data, dict):
    # Fail open: a payload that isn't a JSON object isn't ours to act on.
    sys.exit(0)

cwd = Path(data.get("cwd") or ".").resolve()
agent_id = data.get("agent_id")
if not agent_id:
    sys.exit(0)

try:
    from _git_baseline import git_dir, head_sha, working_tree_signature
except ImportError:
    # Fail open: the helper module ships alongside every hook, but a stale or
    # partial install must no-op rather than crash the user's tool path.
    sys.exit(0)


repo_git_dir = git_dir(cwd)
if repo_git_dir is None:
    sys.exit(0)

state_file = repo_git_dir / "the-workshop-subagent-gate" / f"{agent_id}.txt"
try:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    # Normalize None to "" at the boundary. The paired stop hook reads these
    # back as strings and compares them, so writing the literal "None" would
    # never match and would silently disable the evidence check.
    state_file.write_text(
        f"{head_sha(cwd) or ''}\n{working_tree_signature(cwd) or ''}\n"
    )
except OSError:
    pass

sys.exit(0)
