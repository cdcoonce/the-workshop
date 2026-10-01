"""Shared base-side git reads for the PR-relative guards.

The spec diffs ``$(VERSION_BASE)...HEAD`` — three-dot, i.e. against the
merge-base of the base ref and HEAD, not against the base ref's tip. A base
branch that moved on after the PR forked would otherwise make a guard read
the PR as having removed or edited everything the base branch added since.
Guards that read base-side file content or tier hashes resolve the merge-base
once with `merge_base` and read from that commit.

This module has no ``check`` function, so the guard runner skips it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def merge_base(repo_root: Path, base: str) -> str:
    """Return the merge-base commit of *base* and ``HEAD``.

    Parameters
    ----------
    repo_root : Path
        The git work tree to resolve against.
    base : str
        The ``--base`` ref.

    Returns
    -------
    str
        The merge-base commit SHA.

    Raises
    ------
    subprocess.CalledProcessError
        If *base* does not resolve or shares no history with ``HEAD``. An
        unresolvable base must never read as "every file is absent at base",
        which would silently pass the guards that only look for losses.
    """
    result = subprocess.run(
        ["git", "-C", str(repo_root), "merge-base", base, "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def show_at(repo_root: Path, ref: str, rel_path: str) -> str:
    """Return *rel_path*'s text at *ref*, or "" if it does not exist there.

    *ref* must already be a resolved commit (see `merge_base`): a missing
    path at a good commit is a legitimate "absent at base", but an
    unresolvable ref is not and is not this function's concern.
    """
    result = subprocess.run(
        ["git", "-C", str(repo_root), "show", f"{ref}:{rel_path}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout if result.returncode == 0 else ""
