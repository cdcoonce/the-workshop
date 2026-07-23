"""Shared git-baseline helpers for hook scripts.

Not a hook. The leading underscore keeps it out of hook discovery — `build_docs`
globs `core/hooks/*.py` and requires every match to declare an event in its
docstring, which a library module has none of.

`run-hook.sh` invokes hooks as `python3 <hooks/scripts/name.py>`, so `sys.path[0]`
is that directory and a sibling import resolves at runtime. `build_preset` ships
this module unconditionally, like `run-hook.sh`, so it is always next to the
hooks that need it.

Every helper returns None on any failure — missing git, not a repo, timeout, a
non-zero exit. Hooks run on the user's prompt and tool path, so they fail open;
callers that serialize these values normalize None themselves rather than
writing the string "None" into a state file.
"""

import hashlib
import subprocess
from pathlib import Path


def git_dir(project_dir: Path):
    """Absolute .git directory for `project_dir`, or None outside a repo."""
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
    """Current HEAD sha, or None when there is no resolvable HEAD."""
    try:
        result = subprocess.run(
            ["git", "-C", str(project_dir), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def working_tree_signature(project_dir: Path):
    """A content-aware fingerprint of what's changed.

    `git status --porcelain` alone only reports per-path status flags (M/A/??),
    not content — editing an already-modified file's content again produces the
    identical porcelain line, which would wrongly look "unchanged." So this
    hashes the status output plus the current bytes of every listed path.
    """
    try:
        status = subprocess.run(
            ["git", "-C", str(project_dir), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if status.returncode != 0:
        return None

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
