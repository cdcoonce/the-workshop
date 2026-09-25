"""Find the identifiers a diff renamed, from its unified diff text alone.

Pure: no git, no filesystem. The input is `git diff -U0` output and the
output is what the sweep should go looking for, so every rule here is testable
against a pasted diff.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")
INTERNAL_CAPITAL = re.compile(r"[a-z0-9][A-Z]")
DUNDER = re.compile(r"^__\w+__$")
MIN_LENGTH = 6
# `@@ -start[,count] +start[,count] @@`; an omitted count means one line.
HUNK_HEADER = re.compile(r"^@@ -\d+(?:,(?P<removed>\d+))? \+\d+(?:,(?P<added>\d+))? @@")


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
        old_tokens = _tokens(old_line)
        new_tokens = _tokens(new_line)
        if not new_tokens:
            continue
        # Align the two token sequences so each replaced name is credited to
        # the name that took its place, not to the first new name on the line.
        replacement: dict[str, str] = {}
        matcher = SequenceMatcher(a=old_tokens, b=new_tokens, autojunk=False)
        for op, i1, i2, j1, j2 in matcher.get_opcodes():
            if op == "replace":
                for offset, token in enumerate(old_tokens[i1:i2]):
                    new = new_tokens[j1 + offset] if j1 + offset < j2 else ""
                    replacement.setdefault(token, new)
        for token in old_tokens:
            if token not in new_tokens and is_distinctive(token):
                renames.append(Rename(old=token, new=replacement.get(token, ""), path=path))
    return renames


def detect_renames(diff_text: str, exclude_paths: frozenset[str] = frozenset()) -> list[Rename]:
    """Return every token a paired ``-``/``+`` line replaced.

    Parameters
    ----------
    diff_text
        Output of ``git diff -U0`` between the base and the head.
    exclude_paths
        Files whose lines are neither renames nor uses, on either side of the
        diff. They are skipped here, after git has paired moved files: a
        pathspec would unpair a moved file and turn its lines into additions.

    Returns
    -------
    list[Rename]
        One entry per renamed token, first occurrence wins.
    """
    candidates: list[Rename] = []
    added_anywhere: set[str] = set()
    path = old_path = ""
    removed: list[str] = []
    added: list[str] = []

    def flush() -> None:
        candidates.extend(_pair_renames(removed, added, path))
        removed.clear()
        added.clear()

    # Header lines are only headers outside a hunk. Inside one, the hunk
    # header's counts say exactly how many removed and added lines follow, so
    # a removed SQL comment `-- x` (diffed as `--- x`) or an added `++ x`
    # (diffed as `+++ x`) stays content instead of reading as a file header.
    removed_left = added_left = 0
    # `\n` only: `splitlines` would also break a diffed line at a `\r`.
    for line in diff_text.split("\n"):
        if removed_left or added_left:
            if path in exclude_paths or old_path in exclude_paths:
                if line.startswith("-") and removed_left:
                    removed_left -= 1
                elif line.startswith("+") and added_left:
                    added_left -= 1
                continue
            if line.startswith("-") and removed_left:
                removed_left -= 1
                if added:
                    flush()
                removed.append(line[1:])
            elif line.startswith("+") and added_left:
                added_left -= 1
                added.append(line[1:])
                added_anywhere.update(_tokens(line[1:]))
            continue
        hunk = HUNK_HEADER.match(line)
        if hunk:
            flush()
            removed_left = int(hunk.group("removed") or 1)
            added_left = int(hunk.group("added") or 1)
        elif line.startswith("+++ "):
            flush()
            path = line[6:] if line.startswith("+++ b/") else line[4:]
        elif line.startswith("--- "):
            flush()
            old_path = line[6:] if line.startswith("--- a/") else line[4:]
        elif line.startswith("diff --git"):
            flush()
            path = old_path = ""
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
