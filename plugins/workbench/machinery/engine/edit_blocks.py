"""Split one file's diff into blocks a wrap-up can stage independently.

Concurrent vault sessions share one checkout, and /wrap-up sends every one of
them to the same anchors (``## Recent`` in Key Decisions, ``## Current
Status``, the handoff's open threads). When two sessions insert at the same
anchor, a line diff reports one hunk holding both insertions, so a hunk is
too coarse to tell one session's edit from another's. This module splits a
diff more finely:

- a pure insertion splits at markdown headings when it contains any, else at
  paragraph starts (a non-blank line after a blank one) and at top-level list
  items, so each Key Decisions entry, status paragraph or handoff bullet is
  its own block;
- an equal-length replacement splits line by line;
- anything else (a deletion, an unequal replacement) stays one block.

Block ids hash the block's content and position anchor, not its ordinal, so an
id a session listed still names the same block after another session edits
elsewhere in the file. ``apply_blocks`` rebuilds the file from the old lines
with only the selected blocks applied: all ids give the new file, none give
the old one.

The file ships twice, byte-identical: in the vault-wrap-up skill's
``scripts/`` (used by ``stage_session_edits.py``) and in the machinery
``engine/`` (used by ``wrap_up_audit.py``'s ``claimed_hunks`` check), so the
ids the audit lists are the ids the staging script accepts. A machinery test
fails if the two copies diverge.
"""

from __future__ import annotations

import difflib
import hashlib
import re
from dataclasses import dataclass, field

_HEADING_RE = re.compile(r"^#{1,6} ")
_LIST_ITEM_RE = re.compile(r"^(?:[-*+]|\d+[.)]) ")


@dataclass
class Block:
    """One independently stageable change.

    ``old_start``/``old_end`` index the old lines this block replaces (equal
    for a pure insertion); ``new_lines`` is what replaces them.
    """

    id: str
    kind: str  # "add" | "delete" | "replace"
    old_start: int
    old_end: int
    new_start: int
    new_lines: list[str] = field(default_factory=list)
    old_lines: list[str] = field(default_factory=list)

    @property
    def first_line(self) -> str:
        """First non-blank changed line, newline stripped — what a session reads to claim it."""
        for line in (self.new_lines or self.old_lines):
            if line.strip():
                return line.rstrip("\r\n")
        return ""


def _is_blank(line: str) -> bool:
    return line.strip() == ""


def _split_insert(lines: list[str]) -> list[list[str]]:
    """Split inserted lines into runs, each starting at a boundary line."""
    has_heading = any(_HEADING_RE.match(line) for line in lines)

    def starts_block(i: int) -> bool:
        line = lines[i]
        if _is_blank(line):
            return False
        if has_heading:
            return bool(_HEADING_RE.match(line))
        after_blank = i > 0 and _is_blank(lines[i - 1])
        return after_blank or bool(_LIST_ITEM_RE.match(line))

    runs: list[list[str]] = []
    for i, line in enumerate(lines):
        if runs and starts_block(i):
            # A run holding only blank lines so far is leading whitespace: keep
            # it with the first real block instead of making it its own.
            if all(_is_blank(x) for x in runs[-1]):
                runs[-1].append(line)
            else:
                runs.append([line])
        elif runs:
            runs[-1].append(line)
        else:
            runs.append([line])
    return runs


def _raw_changes(old: list[str], new: list[str]) -> list[tuple[str, int, int, int, int]]:
    """difflib opcodes minus ``equal``, with insertions slid past leading blanks.

    difflib may align an anchor's blank separator with the end of an inserted
    run instead of its start, leaving the insertion beginning with a blank
    line. Sliding it down (the content is identical either way) makes each
    insertion start at real content, so its trailing blank travels with it.
    """
    matcher = difflib.SequenceMatcher(None, old, new, autojunk=False)
    changes: list[tuple[str, int, int, int, int]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag == "insert":
            while j1 < j2 and _is_blank(new[j1]) and i1 < len(old) and j2 < len(new) and old[i1] == new[j1] == new[j2]:
                i1 += 1
                i2 += 1
                j1 += 1
                j2 += 1
        changes.append((tag, i1, i2, j1, j2))
    return changes


def _block_id(kind: str, anchor: str, old_lines: list[str], new_lines: list[str], seen: dict[str, int]) -> str:
    digest = hashlib.sha1()
    for part in (kind, anchor, *old_lines, "\0", *new_lines):
        digest.update(part.encode("utf-8", "surrogatepass"))
        digest.update(b"\0")
    base = digest.hexdigest()[:8]
    count = seen.get(base, 0)
    seen[base] = count + 1
    return base if count == 0 else f"{base}-{count + 1}"


def split_blocks(old: list[str], new: list[str]) -> list[Block]:
    """Blocks turning *old* into *new*, in file order. Lines keep their endings."""
    blocks: list[Block] = []
    seen: dict[str, int] = {}

    def add(kind: str, i1: int, i2: int, j1: int, new_lines: list[str]) -> None:
        old_lines = old[i1:i2]
        anchor = old[i1 - 1] if i1 > 0 else ""
        blocks.append(
            Block(
                id=_block_id(kind, anchor, old_lines, new_lines, seen),
                kind=kind,
                old_start=i1,
                old_end=i2,
                new_start=j1,
                new_lines=list(new_lines),
                old_lines=list(old_lines),
            )
        )

    for tag, i1, i2, j1, j2 in _raw_changes(old, new):
        if tag == "insert":
            offset = j1
            for run in _split_insert(new[j1:j2]):
                add("add", i1, i1, offset, run)
                offset += len(run)
        elif tag == "delete":
            add("delete", i1, i2, j1, [])
        elif i2 - i1 == j2 - j1:
            for k in range(i2 - i1):
                add("replace", i1 + k, i1 + k + 1, j1 + k, [new[j1 + k]])
        else:
            add("replace", i1, i2, j1, new[j1:j2])
    return blocks


_SECTION_RE = re.compile(r"^## (.+?)\s*$")
_FENCE_RE = re.compile(r"^(```|~~~)")


def section_of(lines: list[str], index: int) -> str | None:
    """The ``## `` heading at or before 0-based line *index*, skipping fenced code."""
    section: str | None = None
    fence = ""
    for line in lines[: index + 1]:
        stripped = line.strip()
        fm = _FENCE_RE.match(stripped)
        if fm:
            if not fence:
                fence = fm.group(1)
            elif stripped.startswith(fence):
                fence = ""
            continue
        if fence:
            continue
        hm = _SECTION_RE.match(line.rstrip("\r\n"))
        if hm:
            section = hm.group(1)
    return section


def block_section(block: Block, old: list[str], new: list[str]) -> str | None:
    """The ``## `` section a block sits in: new side for an add/replace, old side for a delete."""
    if block.kind == "delete":
        return section_of(old, block.old_start)
    return section_of(new, block.new_start)


def apply_blocks(old: list[str], blocks: list[Block], selected: list[str]) -> list[str]:
    """*old* with only the *selected* block ids applied.

    Raises ValueError naming any id that is not one of *blocks*.
    """
    known = {b.id for b in blocks}
    unknown = [s for s in selected if s not in known]
    if unknown:
        raise ValueError(f"unknown block id(s): {', '.join(unknown)}")
    chosen = set(selected)
    out: list[str] = []
    pos = 0
    for block in sorted(blocks, key=lambda b: (b.old_start, b.new_start)):
        out.extend(old[pos:block.old_start])
        pos = max(pos, block.old_start)
        if block.id in chosen:
            out.extend(block.new_lines)
        else:
            out.extend(old[block.old_start:block.old_end])
        pos = max(pos, block.old_end)
    out.extend(old[pos:])
    return out
