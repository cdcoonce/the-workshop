"""Find the identifiers a diff renamed, from its unified diff text alone.

Pure: no git, no filesystem. The input is `git diff -U0` output and the
output is what the sweep should go looking for, so every rule here is testable
against a pasted diff.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")
INTERNAL_CAPITAL = re.compile(r"[a-z0-9][A-Z]")
DUNDER = re.compile(r"^__\w+__$")
MIN_LENGTH = 6


def is_distinctive(token: str) -> bool:
    """Whether a token is specific enough to chase across a whole repo.

    A plain word (``rows``) or a short name (``a_b``) matches too much
    unrelated text for a hit to mean anything; ``LEGACY_SCHEMA``,
    ``load_curves``, ``LoadCurves`` and ``pkg.module`` do not.
    """
    if len(token) < MIN_LENGTH or DUNDER.match(token):
        return False
    return "_" in token or "." in token or bool(INTERNAL_CAPITAL.search(token))


@dataclass(frozen=True)
class Rename:
    """An identifier that left the diff, what replaced it, and where."""

    old: str
    new: str
    path: str


def _tokens(line: str) -> list[str]:
    """Split a line into comparable names.

    A qualified name contributes its parts, so a diff that only rewrites
    ``LEGACY_SCHEMA.prices`` still chases the bare ``LEGACY_SCHEMA`` into a
    ``USE SCHEMA`` line elsewhere. The whole dotted name is kept only when no
    part is distinctive on its own (``pkg.module``), since it is then the
    only specific thing to chase.
    """
    tokens: list[str] = []
    for match in TOKEN.findall(line):
        parts = match.split(".")
        tokens.extend(parts)
        if len(parts) > 1 and not any(is_distinctive(part) for part in parts):
            tokens.append(match)
    return tokens


def _pair_renames(removed: list[str], added: list[str], path: str) -> list[Rename]:
    renames = []
    for old_line, new_line in zip(removed, added):
        new_tokens = _tokens(new_line)
        if not new_tokens:
            continue
        gone = [t for t in _tokens(old_line) if t not in new_tokens and is_distinctive(t)]
        arrived = [t for t in new_tokens if t not in _tokens(old_line)]
        for token in gone:
            renames.append(Rename(old=token, new=arrived[0] if arrived else "", path=path))
    return renames


def detect_renames(diff_text: str) -> list[Rename]:
    """Return every token a paired ``-``/``+`` line replaced.

    Parameters
    ----------
    diff_text
        Output of ``git diff -U0`` between the base and the head.

    Returns
    -------
    list[Rename]
        One entry per renamed token, first occurrence wins.
    """
    candidates: list[Rename] = []
    added_anywhere: set[str] = set()
    path = ""
    removed: list[str] = []
    added: list[str] = []

    def flush() -> None:
        candidates.extend(_pair_renames(removed, added, path))
        removed.clear()
        added.clear()

    for line in diff_text.splitlines():
        if line.startswith("+++ "):
            flush()
            path = line[6:] if line.startswith("+++ b/") else line[4:]
        elif line.startswith("--- ") or line.startswith("diff --git"):
            flush()
        elif line.startswith("@@"):
            flush()
        elif line.startswith("-"):
            if added:
                flush()
            removed.append(line[1:])
        elif line.startswith("+"):
            added.append(line[1:])
            added_anywhere.update(_tokens(line[1:]))
    flush()

    # A token the diff also adds somewhere moved rather than disappeared, so
    # its surviving references are still correct.
    seen: set[str] = set()
    renames = []
    for rename in candidates:
        if rename.old not in seen and rename.old not in added_anywhere:
            seen.add(rename.old)
            renames.append(rename)
    return renames
