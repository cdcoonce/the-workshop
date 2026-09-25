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
        )
        # git grep exits 1 for "no match", which is the clean answer here.
        if result.returncode not in (0, 1):
            stderr = result.stderr.decode("utf-8", "replace").strip()
            raise RuntimeError(stderr or f"git grep failed for {rename.old}")
        prefix = f"{head}:"
        # Each row is `name NUL line NUL content \n`, read field by field.
        # git prints a newline inside a path raw under `-z`, so only the NULs
        # can find the name; a row ends at the first `\n` after its line
        # field. Bytes are decoded by hand because `text=True` (universal
        # newlines) would also break a row at a `\r` in the matched line.
        stdout = result.stdout.decode("utf-8", "replace")
        start = 0
        while start < len(stdout):
            name_end = stdout.index("\0", start)
            line_end = stdout.index("\0", name_end + 1)
            row_end = stdout.find("\n", line_end + 1)
            if row_end == -1:
                row_end = len(stdout)
            name = stdout[start:name_end]
            path = name[len(prefix):] if name.startswith(prefix) else name
            hits.append(Hit(path=path, line=int(stdout[name_end + 1 : line_end]), rename=rename))
            start = row_end + 1
    return hits
