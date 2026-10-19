"""Shared git-baseline helpers for hook scripts.

Not a hook. The leading underscore keeps it out of hook discovery — `scripts/stamp.py`
scans `hooks/scripts/*.py` and treats a file without a `WORKSHOP_HOOK` declaration
as a library module rather than a hook, which is exactly what this file is.

`run-hook.sh` invokes hooks as `python3 <hooks/scripts/name.py>`, so `sys.path[0]`
is that directory and a sibling import resolves at runtime. The stamper ships
this module alongside `run-hook.sh`, so it is always next to the hooks that need it.

Every helper returns None on any failure — missing git, not a repo, timeout, a
non-zero exit. Hooks run on the user's prompt and tool path, so they fail open;
callers that serialize these values normalize None themselves rather than
writing the string "None" into a state file.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

_HASH_CHUNK_BYTES = 1024 * 1024


def _run_git(args: list[str], cwd: Path, timeout: int = 10) -> str | None:
    """Run `git -C <cwd> <args>` and return stripped stdout, or None on any failure.

    Parameters
    ----------
    args
        Arguments after `git -C <cwd>`.
    cwd
        Directory git runs in.
    timeout
        Seconds before the call is abandoned.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def state_key(raw: str) -> str:
    """A single safe path component naming `raw`, distinct for distinct `raw`.

    Hook payload ids are untrusted: the sanitized text keeps the name readable
    and free of separators, and the short hash of the *raw* id keeps ids that
    sanitize alike ("a/b" and "a_b") from sharing one state file.
    """
    text = str(raw)
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in text)
    digest = hashlib.sha1(text.encode("utf-8", "surrogatepass")).hexdigest()[:8]
    return f"{safe}-{digest}"


def git_dir(project_dir: Path) -> Path | None:
    """Absolute .git directory for `project_dir`, or None outside a repo."""
    out = _run_git(["rev-parse", "--absolute-git-dir"], project_dir)
    return None if out is None else Path(out)


def git_common_dir(project_dir: Path) -> Path | None:
    """Absolute shared .git directory for `project_dir`, or None outside a repo.

    In a linked worktree `git_dir` points at `.git/worktrees/<name>`, which git
    deletes with the worktree; this resolves to the repository's own `.git`.
    """
    out = _run_git(["rev-parse", "--git-common-dir"], project_dir)
    if out is None:
        return None
    # Git reports this relative to `project_dir` in the plain-repo case.
    return (Path(project_dir) / out).resolve()


def head_sha(project_dir: Path) -> str | None:
    """Current HEAD sha, or None when there is no resolvable HEAD."""
    return _run_git(["rev-parse", "HEAD"], project_dir)


def working_tree_signature(project_dir: Path) -> str | None:
    """A content-aware fingerprint of what's changed.

    `git status --porcelain` alone only reports per-path status flags (M/A/??),
    not content — editing an already-modified file's content again produces the
    identical porcelain line, which would wrongly look "unchanged." So this
    hashes the status output plus the current bytes of every listed path.
    """
    try:
        status = subprocess.run(
            ["git", "-C", str(project_dir), "status", "--porcelain", "-z", "--untracked-files=all"],
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if status.returncode != 0:
        return None

    # `-z` output is NUL-delimited and never C-quoted, so non-ASCII, tab, quote
    # and backslash paths arrive as raw bytes. Each entry is `XY <path>`; a
    # rename/copy entry (X or Y is R/C) is followed by one extra field, the
    # original path, which is not a file to hash.
    hasher = hashlib.sha256()
    hasher.update(status.stdout)
    fields = status.stdout.split(b"\0")
    index = 0
    while index < len(fields):
        entry = fields[index]
        index += 1
        if len(entry) < 4:
            continue
        if b"R" in entry[:2] or b"C" in entry[:2]:
            index += 1  # skip the original-path field
        path_part = os.fsdecode(entry[3:])
        try:
            with (project_dir / path_part).open("rb") as handle:
                # Chunked so a large changed file cannot balloon the hook's memory.
                for chunk in iter(lambda: handle.read(_HASH_CHUNK_BYTES), b""):
                    hasher.update(chunk)
        except OSError:
            pass
    return hasher.hexdigest()
