"""Guard: a file that already exists under ``evals/<skill>/runs/`` never changes.

Run files are write-once (the ledger writer refuses to overwrite one) and a
run's verbatim raws live beside them under ``runs/<stem>/``, so every file
anywhere under a skill's ``runs/`` directory is protected once it exists at
the base. Diffs ``$(VERSION_BASE)...HEAD`` (the ``ctx.base`` ref the runner
passes) with ``--no-renames``, so a rename reads as a delete of the old path
plus an add of the new one, and fails if any protected file is modified,
deleted, or replaced. A path the diff adds is a new run (or a new raw) and is
always allowed.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from evals._harness.guards import GuardContext, Result

_GUARD_NAME = "runs_immutable"
_RUNS_PATH = re.compile(r"^evals/[^/]+/runs/")


def _changed_entries(repo_root: Path, base: str) -> list[tuple[str, str]]:
    """Return ``(status, path)`` for every path in ``base...HEAD``.

    ``-z`` keeps a path with unusual characters verbatim instead of quoted;
    ``--no-renames`` is what makes a rename out of ``runs/`` visible as a
    deletion of its protected old path.
    """
    output = subprocess.run(
        [
            "git", "-C", str(repo_root), "diff", "--no-renames", "--name-status", "-z",
            f"{base}...HEAD",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    fields = [field for field in output.split("\0") if field]
    return list(zip(fields[0::2], fields[1::2]))


def check(ctx: GuardContext) -> list[Result]:
    """Fail every file under a skill's ``runs/`` that existed at base and changed.

    Parameters
    ----------
    ctx : GuardContext
        ``ctx.base`` is the ref to diff against; ``ctx.repo_root`` is the
        work tree, checked out at HEAD.

    Returns
    -------
    list[Result]
        One ``fail`` per protected file the diff modifies, deletes or
        replaces. Empty when the diff only adds files there, or never touches
        a ``runs/`` directory.
    """
    results: list[Result] = []
    for status, path in _changed_entries(ctx.repo_root, ctx.base):
        if status.startswith("A"):
            continue
        if not _RUNS_PATH.match(path):
            continue
        results.append(
            Result(
                level="fail",
                guard=_GUARD_NAME,
                message=(
                    f"{path}: an existing file under a skill's runs/ directory was changed "
                    f"(git status {status}); run files and raws are write-once"
                ),
            )
        )
    return results
