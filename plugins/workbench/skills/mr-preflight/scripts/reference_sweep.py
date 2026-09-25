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
        # `-z` separates name, line and content with NUL, so a `:` inside a
        # path cannot split it; `-I` skips binary files, which have no line
        # to fix and would otherwise print a line-less "Binary file" row.
        result = subprocess.run(
            ["git", "grep", "-z", "-I", "-n", "-w", "-F", "-e", rename.old, head, "--"],
            cwd=repo,
            capture_output=True,
            text=True,
        )
        # git grep exits 1 for "no match", which is the clean answer here.
        if result.returncode not in (0, 1):
            raise RuntimeError(result.stderr.strip() or f"git grep failed for {rename.old}")
        prefix = f"{head}:"
        # Rows end at `\n` only: `splitlines` would also break on a form feed
        # or `\r` inside a matched line's content and strand its NULs.
        for row in filter(None, result.stdout.split("\n")):
            name, line, _ = row.split("\0", 2)
            path = name[len(prefix):] if name.startswith(prefix) else name
            hits.append(Hit(path=path, line=int(line), rename=rename))
    return hits
