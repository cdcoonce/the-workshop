#!/usr/bin/env python3
"""SubagentStop hook: catch a subagent claiming a change it never made.

Pairs with snapshot-subagent-start.py (SubagentStart), which records the git
HEAD sha + working-tree content signature when the subagent begins. If the
subagent's final message claims it implemented/fixed/committed something but
neither the HEAD sha nor the working tree changed at all since the snapshot,
block it and ask for the actual evidence instead of trusting the claim — the
exact failure mode "never trust a subagent's done without reading the diff"
exists to catch (a tool call that silently no-oped, a hallucinated edit).

Only blocks on a real contradiction; anything ambiguous (no snapshot, not a
git repo, no completion-sounding claim in the message) fails open.
"""

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

try:
    data = json.load(sys.stdin)
except json.JSONDecodeError:
    sys.exit(0)

message = data.get("last_assistant_message") or ""
agent_id = data.get("agent_id")
cwd = Path(data.get("cwd") or ".").resolve()

if not agent_id or not message:
    sys.exit(0)

# Conservative on purpose: only fire on a strong first-person completion
# claim, not any mention of these words in passing (e.g. "no fix needed").
COMPLETION_CLAIM = re.compile(
    r"\bI(?:'ve| have)\s+(?:implemented|fixed|added|updated|created|removed|"
    r"deleted|refactored|committed|resolved|written|wrote|applied)\b"
    r"|\b(?:changes? (?:are|is) complete|fix is (?:in place|complete|done)|"
    r"implementation is complete|committed the (?:fix|change)|"
    r"done\.?\s*$)",
    re.IGNORECASE,
)

if not COMPLETION_CLAIM.search(message):
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

state_file = repo_git_dir / "the-workshop-subagent-gate" / f"{agent_id}.txt"
if not state_file.exists():
    sys.exit(0)  # no baseline to compare against — nothing we can prove

try:
    lines = state_file.read_text().splitlines()
except OSError:
    sys.exit(0)
lines += [""] * (2 - len(lines))
baseline_sha, baseline_signature = lines[0], lines[1]

try:
    state_file.unlink()
except OSError:
    pass

current_sha = head_sha(cwd)
current_signature = working_tree_signature(cwd)

if current_sha != baseline_sha or current_signature != baseline_signature:
    sys.exit(0)  # something actually changed — claim is consistent

print(
    json.dumps(
        {
            "decision": "block",
            "reason": (
                "This message claims a change was made, but neither the git "
                "HEAD commit nor the working tree changed at all since this "
                "subagent started. Verify the edit/commit actually happened — "
                "re-check the tool result, don't just report success."
            ),
        }
    )
)
sys.exit(0)
