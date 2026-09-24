"""Search the head tree for every surviving reference to a renamed identifier."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from rename_detector import Rename


@dataclass(frozen=True)
class Hit:
    """One surviving reference to a renamed identifier."""

    path: str
    line: int
    rename: Rename


def sweep(repo: Path, head: str, renames: list[Rename]) -> list[Hit]:
    """Return every word-boundary occurrence of each renamed token at ``head``.

    Parameters
    ----------
    repo
        Repository root to search.
    head
        Commit-ish whose tree is searched, so uncommitted edits never count.
    renames
        Tokens to chase, from ``rename_detector.detect_renames``.

    Returns
    -------
    list[Hit]
        Hits in path, then line order, per rename.
    """
    hits: list[Hit] = []
    for rename in renames:
        result = subprocess.run(
            ["git", "grep", "-n", "-w", "-F", "-e", rename.old, head, "--"],
            cwd=repo,
            capture_output=True,
            text=True,
        )
        # git grep exits 1 for "no match", which is the clean answer here.
        if result.returncode not in (0, 1):
            raise RuntimeError(result.stderr.strip() or f"git grep failed for {rename.old}")
        prefix = f"{head}:"
        for row in result.stdout.splitlines():
            if row.startswith(prefix):
                row = row[len(prefix):]
            path, line, _ = row.split(":", 2)
            hits.append(Hit(path=path, line=int(line), rename=rename))
    return hits
