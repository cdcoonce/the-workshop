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


def sweep(repo: Path, head: str, renames: list[Rename], exclude: tuple[str, ...] = ()) -> list[Hit]:
    """Return every word-boundary occurrence of each renamed token at ``head``.

    Parameters
    ----------
    repo
        Repository root to search.
    head
        Commit-ish whose tree is searched, so uncommitted edits never count.
    renames
        Tokens to chase, from ``rename_detector.detect_renames``.
    exclude
        Pathspecs never searched, such as the repo's own ignore list.

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
            ["git", "grep", "-z", "-I", "-n", "-w", "-F", "-e", rename.old, head, "--", ".", *exclude],
            cwd=repo,
            capture_output=True,
        )
        # git grep exits 1 for "no match", which is the clean answer here.
        if result.returncode not in (0, 1):
            stderr = result.stderr.decode("utf-8", "replace").strip()
            raise RuntimeError(stderr or f"git grep failed for {rename.old}")
        prefix = f"{head}:"
        # Bytes decoded by hand, then rows split on `\n` only. `text=True`
        # (universal newlines) or `splitlines` would also break a row at a
        # `\r` or form feed inside the matched line and strand its NULs.
        stdout = result.stdout.decode("utf-8", "replace")
        for row in filter(None, stdout.split("\n")):
            name, line, _ = row.split("\0", 2)
            path = name[len(prefix):] if name.startswith(prefix) else name
            hits.append(Hit(path=path, line=int(line), rename=rename))
    return hits
