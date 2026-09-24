"""Scoped, fail-closed entry-replay fallback for /sync's hub-file conflicts.

The vault's four accumulating hub files -- ``brain/Gotchas.md``,
``brain/Key Decisions.md``, ``perf/Brag Doc.md``, and the rolling
``.brain/handoff-*.md`` digests -- are written by every same-day session at
the same anchored bytes (workshop #871), so ``git pull --rebase`` conflicts
on them structurally, not incidentally. When such a rebase has been aborted,
/sync may run this script (issue #893): it rebuilds the session's
contribution on top of origin's copy instead of asking git to line-merge it.

The procedure codifies the 2026-09-19 hand-built union merge (the vault's
``3164dec0``):

1. Fresh branch from freshly fetched ``origin/<target>``; origin's copy of
   every file is the starting point. ``<target>`` is the sync target
   (``sync_target.py``), not the current branch's namesake: a desktop-app
   worktree session sits on an unpublished ``claude/*`` branch whose work
   integrates into origin's default branch. Only that local branch is moved
   to the result; local ``main`` belongs to the primary checkout. A Codex
   session on a detached HEAD moves no branch: HEAD is left detached at the
   result, and a refusal returns it to the original detached commit.
2. The session's per-file diff (``--base`` -> HEAD) is computed
   content-level; after the #892 squash that is one hunk set.
3. Ledger rule: hunks must be *pure insertions* of dated entries under a
   recognized anchor heading. They are re-inserted under that anchor in
   origin's copy, then every entry under the anchor is re-sorted
   newest-first by date -- the deterministic re-linearization that keeps
   #871's ordering guarantee under concurrency (#871's ordering-drift
   detector stays on as the tooth).
4. Handoff rule: origin's file wins wholesale; only the ``##`` sections this
   session touched (the ``handoff_sections`` collector's section model) are
   re-applied, and the frontmatter ``description:`` is merged additively at
   clause granularity rather than restored as the session's whole paragraph.
5. Assertions, fail-closed: before every replacement, origin's corresponding
   span must be byte-identical to the session-base version, with spans drawn
   per entry / per section -- as narrow as possible, which is spec, not
   preference. Any assertion failure, any non-insertion change in a ledger
   (an in-place correction like the vault's ``2455bf8c``), or any conflict
   outside the allowlist refuses, lists the files, and leaves the repository
   exactly as it found it. The escalation path is unchanged.
6. ``ci/vault_health.py`` runs on the replayed tree before anything is
   pushed; a failure restores the original state.

Where the #892 squash boundary fails *open* (every guard degrades to
today's behavior), this fallback fails *closed*: it rewrites shared ledger
content, so every uncertainty stops it. Exit codes: 0 for ``replayed`` and
``none`` (sync proceeds -- after ``replayed`` the push is a fast-forward),
1 for ``refused`` (stop and alert; the repository has been restored), 2 for
usage errors.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import shlex
import subprocess
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from sync_target import UnresolvedTarget
from sync_target import resolve as resolve_sync_target

LEDGER_FILES = frozenset(
    {
        "brain/Gotchas.md",
        "brain/Key Decisions.md",
        "perf/Brag Doc.md",
    }
)
HANDOFF_PREFIX = ".brain/handoff-"
HEALTH_SCRIPT = "ci/vault_health.py"
HEALTH_CMD_DEFAULT = "uv run --script ci/vault_health.py"
HEALTH_TIMEOUT_SECONDS = 300
REPLAY_BRANCH_PREFIX = "sync-entry-replay/"

_FENCE_RE = re.compile(r"^(```|~~~)")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
# Mirrors the wrap-up collector's handoff section model: level-2 headings only.
_SECTION_RE = re.compile(r"^## (.+?)\s*$")
_BULLET_ENTRY_RE = re.compile(r"^-\s+\*\*(\d{4}-\d{2}-\d{2})\b")
_LEAD_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\b")
_TRAIL_DATE_RE = re.compile(r"\((\d{4}-\d{2}-\d{2})\)$")
_DESCRIPTION_RE = re.compile(r'^description:\s*"((?:[^"\\]|\\.)*)"\s*$')


class GitError(RuntimeError):
    """A git invocation failed in a way the replay cannot interpret."""


class RefusalError(RuntimeError):
    """A fail-closed guard fired; the replay must stop and escalate."""


@dataclass
class Report:
    """What the replay did, machine-readable via ``--json``."""

    action: str  # "replayed" | "none" | "refused"
    reason: str
    branch: str | None = None
    target: str | None = None
    target_source: str | None = None
    remote: str = "origin"
    base: str | None = None
    old_head: str | None = None
    origin_head: str | None = None
    new_head: str | None = None
    replay_branch: str | None = None
    conflicts: list[str] = field(default_factory=list)
    outside_allowlist: list[str] = field(default_factory=list)
    files: dict[str, dict[str, Any]] = field(default_factory=dict)
    carried: dict[str, list[str]] = field(
        default_factory=lambda: {"added": [], "modified": [], "deleted": []}
    )
    health: str | None = None  # "passed" | "failed" | "absent" | None (not reached)
    restored: bool | None = None


# ---------------------------------------------------------------------------
# git plumbing
# ---------------------------------------------------------------------------


def _run_git(*args: str) -> subprocess.CompletedProcess[str]:
    """Run git in the current directory, capturing output, never raising."""
    return subprocess.run(["git", *args], capture_output=True, text=True, check=False)


def _git_out(*args: str) -> str:
    """Run git and return stripped stdout, raising GitError on failure."""
    proc = _run_git(*args)
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or "no output"
        raise GitError(f"git {' '.join(args)}: {detail}")
    return proc.stdout.strip()


def _is_ancestor(ancestor: str, descendant: str) -> bool:
    proc = _run_git("merge-base", "--is-ancestor", ancestor, descendant)
    if proc.returncode not in (0, 1):
        raise GitError(f"merge-base --is-ancestor failed: {proc.stderr.strip()}")
    return proc.returncode == 0


def _blob_sha(rev: str, path: str) -> str | None:
    proc = _run_git("rev-parse", "--verify", "--quiet", f"{rev}:{path}")
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def _blob_text(rev: str, path: str) -> str:
    """Exact blob content at ``rev:path`` -- bytes-faithful, no stripping."""
    proc = subprocess.run(
        ["git", "cat-file", "blob", f"{rev}:{path}"],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        detail = proc.stderr.decode(errors="replace").strip()
        raise GitError(f"git cat-file blob {rev}:{path}: {detail}")
    try:
        return proc.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RefusalError(f"{path}: not valid UTF-8 text at {rev[:12]}; refusing to merge it") from exc


def _name_status(old: str, new: str) -> dict[str, str]:
    """``{path: status}`` for ``old`` -> ``new``, statuses A/M/D/T only."""
    proc = _run_git("diff", "--name-status", "--no-renames", "-z", old, new)
    if proc.returncode != 0:
        raise GitError(f"git diff --name-status failed: {proc.stderr.strip()}")
    fields = proc.stdout.split("\0")
    out: dict[str, str] = {}
    it = iter(fields)
    for status in it:
        if status == "":
            continue
        path = next(it, None)
        if path is None:
            raise GitError("git diff --name-status returned an odd field count")
        out[path] = status[:1]
    return out


def _operation_in_progress() -> str | None:
    """Name of any in-flight git operation that makes replaying unsafe.

    ``BISECT_LOG`` matters because a bisect detaches HEAD, and a detached
    HEAD is otherwise a legitimate session state (a Codex worktree).
    """
    git_dir = Path(_git_out("rev-parse", "--absolute-git-dir"))
    for marker in (
        "rebase-merge",
        "rebase-apply",
        "MERGE_HEAD",
        "CHERRY_PICK_HEAD",
        "REVERT_HEAD",
        "BISECT_LOG",
    ):
        if (git_dir / marker).exists():
            return marker
    return None


# ---------------------------------------------------------------------------
# text model shared by both rules
# ---------------------------------------------------------------------------


def _lines(text: str) -> list[str]:
    parts = text.split("\n")
    if parts and parts[-1] == "":
        parts.pop()
    return parts


def _join(lines: list[str]) -> str:
    return "\n".join(lines) + "\n"


def _fence_flags(lines: list[str]) -> list[bool]:
    """Per-line "inside (or delimiting) a code fence" flags."""
    flags: list[bool] = []
    in_fence = False
    marker = ""
    for line in lines:
        stripped = line.strip()
        m = _FENCE_RE.match(stripped)
        if m:
            if not in_fence:
                in_fence = True
                marker = m.group(1)
            elif stripped.startswith(marker):
                in_fence = False
                marker = ""
            flags.append(True)
            continue
        flags.append(in_fence)
    return flags


def _valid_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def parse_entry_start(line: str) -> tuple[str, int, str] | None:
    """Classify a line as a dated entry start, or None.

    Recognizes the vault's accumulating-entry shapes (workshop #871's
    detector grammar plus the Gotchas variant): a level-3+ heading with a
    leading ``YYYY-MM-DD`` (Key Decisions), a level-3+ heading with a
    trailing ``(YYYY-MM-DD)`` (Gotchas), and a top-level ``- **YYYY-MM-DD``
    bullet (Brag Doc). Level-2 headings are anchors, never entries.

    Parameters
    ----------
    line:
        One line of markdown, outside any code fence.

    Returns
    -------
    tuple or None
        ``(kind, heading_level, iso_date)`` where kind is ``"heading"`` or
        ``"bullet"`` (level 0), or None when the line starts no entry.
    """
    bm = _BULLET_ENTRY_RE.match(line)
    if bm and _valid_date(bm.group(1)):
        return ("bullet", 0, bm.group(1))
    hm = _HEADING_RE.match(line)
    if hm is None or len(hm.group(1)) < 3:
        return None
    text = hm.group(2)
    lead = _LEAD_DATE_RE.match(text)
    if lead and _valid_date(lead.group(1)):
        return ("heading", len(hm.group(1)), lead.group(1))
    trail = _TRAIL_DATE_RE.search(text)
    if trail and _valid_date(trail.group(1)):
        return ("heading", len(hm.group(1)), trail.group(1))
    return None


def is_allowlisted(path: str) -> bool:
    """True when ``path`` is one of the replayable hub files (issue #893)."""
    if path in LEDGER_FILES:
        return True
    return (
        path.startswith(HANDOFF_PREFIX)
        and path.endswith(".md")
        and "/" not in path[len(".brain/"):]
    )


def _strip_trailing_blanks(lines: list[str]) -> list[str]:
    end = len(lines)
    while end > 0 and lines[end - 1].strip() == "":
        end -= 1
    return lines[:end]


@dataclass
class _Chunk:
    """One entry under an anchor: its raw lines, identity key, and date."""

    lines: list[str]
    kind: str
    level: int
    day: str

    @property
    def key(self) -> tuple[str, ...]:
        return tuple(_strip_trailing_blanks(self.lines))

    @property
    def label(self) -> str:
        return self.lines[0] if self.lines else "<empty>"


def _headings(lines: list[str], flags: list[bool]) -> list[tuple[int, int, str]]:
    """``(index, level, raw_line)`` for every heading outside code fences."""
    out: list[tuple[int, int, str]] = []
    for idx, line in enumerate(lines):
        if flags[idx]:
            continue
        m = _HEADING_RE.match(line)
        if m:
            out.append((idx, len(m.group(1)), line))
    return out


def _heading_path(
    headings: list[tuple[int, int, str]], lines: list[str], anchor_idx: int
) -> tuple[str, ...]:
    """The anchor's outline path: enclosing non-entry headings, outermost first.

    ``### Wins`` repeats once per quarter in the Brag Doc, so an anchor is
    identified by its full path (``# Brag Doc`` > ``## Q3 2026`` >
    ``### Wins``), never by its own heading line alone.
    """
    path: list[str] = []
    level: int | None = None
    for idx, lvl, raw in reversed(headings):
        if idx > anchor_idx:
            continue
        if idx == anchor_idx:
            path.append(raw)
            level = lvl
            continue
        if parse_entry_start(lines[idx]) is not None:
            continue
        if level is not None and lvl < level:
            path.append(raw)
            level = lvl
    return tuple(reversed(path))


@dataclass
class _Block:
    """An anchor's interior: preamble lines then parsed entry chunks."""

    anchor_idx: int
    anchor_level: int
    end_idx: int
    preamble: list[str]
    entries: list[_Chunk]


def _block_end(
    headings: list[tuple[int, int, str]], anchor_idx: int, anchor_level: int, total: int
) -> int:
    for idx, lvl, _raw in headings:
        if idx > anchor_idx and lvl <= anchor_level:
            return idx
    return total


def _parse_chunks(
    lines: list[str], flags: list[bool], path: str, context: str
) -> tuple[list[str], list[_Chunk]]:
    """Split ``lines`` into (preamble, dated entry chunks), fail-closed.

    Refuses on mixed entry kinds or heading levels, and -- for heading-kind
    blocks -- on any undated heading at or below the entries' level, which
    would make entry boundaries ambiguous.
    """
    starts: list[tuple[int, tuple[str, int, str]]] = []
    for idx, line in enumerate(lines):
        if flags[idx]:
            continue
        started = parse_entry_start(line)
        if started is not None:
            starts.append((idx, started))

    if not starts:
        return list(lines), []

    kinds = {started[0] for _idx, started in starts}
    if len(kinds) > 1:
        raise RefusalError(
            f"{path}: {context} mixes bullet and heading entries; refusing to re-linearize it"
        )
    levels = {started[1] for _idx, started in starts}
    if len(levels) > 1:
        raise RefusalError(
            f"{path}: {context} mixes entry heading levels {sorted(levels)}; "
            "refusing to re-linearize it"
        )
    kind = kinds.pop()
    level = levels.pop()
    if kind == "heading":
        start_indices = {idx for idx, _started in starts}
        for idx, line in enumerate(lines):
            if flags[idx] or idx in start_indices:
                continue
            m = _HEADING_RE.match(line)
            if m and len(m.group(1)) <= level:
                raise RefusalError(
                    f"{path}: {context} holds an undated heading {line!r} at the entries' "
                    "level; entry boundaries are ambiguous"
                )

    preamble = lines[: starts[0][0]]
    chunks: list[_Chunk] = []
    for pos, (idx, started) in enumerate(starts):
        end = starts[pos + 1][0] if pos + 1 < len(starts) else len(lines)
        chunks.append(
            _Chunk(lines=lines[idx:end], kind=started[0], level=started[1], day=started[2])
        )
    return preamble, chunks


def _parse_block(
    lines: list[str],
    flags: list[bool],
    headings: list[tuple[int, int, str]],
    anchor_idx: int,
    path: str,
) -> _Block:
    match = _HEADING_RE.match(lines[anchor_idx])
    if match is None:
        raise GitError(f"{path}: internal error, anchor index {anchor_idx} is not a heading")
    anchor_level = len(match.group(1))
    end = _block_end(headings, anchor_idx, anchor_level, len(lines))
    interior = lines[anchor_idx + 1 : end]
    interior_flags = flags[anchor_idx + 1 : end]
    context = f"the block under {lines[anchor_idx]!r}"
    preamble, entries = _parse_chunks(interior, interior_flags, path, context)
    return _Block(
        anchor_idx=anchor_idx,
        anchor_level=anchor_level,
        end_idx=end,
        preamble=preamble,
        entries=entries,
    )


def _emit_interior(preamble: list[str], chunks: list[_Chunk], at_eof: bool) -> list[str]:
    """Reassemble a block interior: chunks verbatim, single-blank separated."""
    segments: list[list[str]] = []
    pre = _strip_trailing_blanks(preamble)
    if pre:
        segments.append(pre)
    segments.extend(list(chunk.key) for chunk in chunks)
    out: list[str] = []
    for segment in segments:
        out.append("")
        out.extend(segment)
    if not at_eof:
        out.append("")
    return out


# ---------------------------------------------------------------------------
# ledger rule
# ---------------------------------------------------------------------------


def ledger_merge(
    base_text: str, tip_text: str, origin_text: str, path: str
) -> tuple[str, dict[str, Any]]:
    """Replay the session's pure entry insertions onto origin's ledger copy.

    Parameters
    ----------
    base_text, tip_text, origin_text:
        The file at the session base, the session tip, and origin's head.
    path:
        Repository-relative path, used in refusal messages.

    Returns
    -------
    tuple
        ``(merged_text, detail)`` -- the merged file content and a report
        fragment (rule, anchors, inserted, duplicates_skipped, unchanged).

    Raises
    ------
    RefusalError
        On any non-insertion session change, any insertion not under a
        recognized anchor, any origin-side entry or block-preamble edit
        (the per-entry base assertion), or any structural ambiguity.
    """
    base_lines = _lines(base_text)
    tip_lines = _lines(tip_text)
    origin_lines = _lines(origin_text)

    matcher = difflib.SequenceMatcher(None, base_lines, tip_lines, autojunk=False)
    insertions: list[tuple[int, list[str]]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag != "insert":
            raise RefusalError(
                f"{path}: non-insertion session change ({tag} touching base lines "
                f"{i1 + 1}-{max(i2, i1 + 1)}); in-place ledger corrections escalate to a human"
            )
        insertions.append((i1, tip_lines[j1:j2]))

    base_flags = _fence_flags(base_lines)
    base_headings = _headings(base_lines, base_flags)

    per_anchor: dict[int, list[_Chunk]] = {}
    for at, inserted in insertions:
        anchor_idx: int | None = None
        for idx, _lvl, _raw in reversed(base_headings):
            if idx >= at:
                continue
            if parse_entry_start(base_lines[idx]) is not None:
                continue
            anchor_idx = idx
            break
        if anchor_idx is None:
            raise RefusalError(
                f"{path}: insertion before line {at + 1} is not under any anchor heading"
            )
        anchor_match = _HEADING_RE.match(base_lines[anchor_idx])
        if anchor_match is None or len(anchor_match.group(1)) < 2:
            raise RefusalError(
                f"{path}: insertion before line {at + 1} sits under the document title, "
                "not a recognized anchor heading"
            )
        ins_flags = _fence_flags(inserted)
        ins_preamble, ins_chunks = _parse_chunks(
            inserted, ins_flags, path, f"the insertion under {base_lines[anchor_idx]!r}"
        )
        if not ins_chunks or _strip_trailing_blanks(ins_preamble):
            raise RefusalError(
                f"{path}: insertion under {base_lines[anchor_idx]!r} is not a pure "
                "dated-entry insertion; in-place edits escalate to a human"
            )
        per_anchor.setdefault(anchor_idx, []).extend(ins_chunks)

    origin_flags = _fence_flags(origin_lines)
    origin_headings = _headings(origin_lines, origin_flags)

    detail: dict[str, Any] = {
        "rule": "ledger",
        "anchors": [],
        "inserted": 0,
        "duplicates_skipped": 0,
        "unchanged": False,
    }
    replacements: list[tuple[_Block, list[str]]] = []
    for anchor_idx in sorted(per_anchor):
        anchor_line = base_lines[anchor_idx]
        apath = _heading_path(base_headings, base_lines, anchor_idx)
        base_block = _parse_block(base_lines, base_flags, base_headings, anchor_idx, path)

        candidates = [
            idx
            for idx, _lvl, raw in origin_headings
            if raw == anchor_line
            and parse_entry_start(origin_lines[idx]) is None
            and _heading_path(origin_headings, origin_lines, idx) == apath
        ]
        if len(candidates) != 1:
            raise RefusalError(
                f"{path}: anchor {anchor_line!r} was not found exactly once on origin "
                f"(found {len(candidates)}); the replay never guesses a new anchor"
            )
        origin_block = _parse_block(
            origin_lines, origin_flags, origin_headings, candidates[0], path
        )

        if _strip_trailing_blanks(base_block.preamble) != _strip_trailing_blanks(
            origin_block.preamble
        ):
            raise RefusalError(
                f"{path}: origin's preamble under {anchor_line!r} is not byte-identical "
                "to the session base; escalating"
            )
        origin_keys = Counter(chunk.key for chunk in origin_block.entries)
        for chunk in base_block.entries:
            if origin_keys[chunk.key] < 1:
                raise RefusalError(
                    f"{path}: origin's copy of entry {chunk.label!r} is not byte-identical "
                    "to the session base (edited or removed); escalating"
                )
            origin_keys[chunk.key] -= 1

        new_chunks = per_anchor[anchor_idx]
        present = Counter(chunk.key for chunk in origin_block.entries)
        kept: list[_Chunk] = []
        for chunk in new_chunks:
            if present[chunk.key] > 0:
                present[chunk.key] -= 1
                detail["duplicates_skipped"] += 1
                continue
            kept.append(chunk)

        merged_entries = kept + origin_block.entries
        kinds = {chunk.kind for chunk in merged_entries}
        levels = {chunk.level for chunk in merged_entries}
        if len(kinds) > 1 or len(levels) > 1:
            raise RefusalError(
                f"{path}: entries under {anchor_line!r} mix shapes across the two sides; "
                "refusing to re-linearize"
            )
        merged_entries.sort(key=lambda chunk: chunk.day, reverse=True)

        at_eof = origin_block.end_idx == len(origin_lines)
        interior = _emit_interior(origin_block.preamble, merged_entries, at_eof)
        replacements.append((origin_block, interior))
        detail["anchors"].append(anchor_line)
        detail["inserted"] += len(kept)

    out = list(origin_lines)
    for origin_block, interior in sorted(replacements, key=lambda item: -item[0].anchor_idx):
        out[origin_block.anchor_idx + 1 : origin_block.end_idx] = interior
    merged_text = _join(out)
    detail["unchanged"] = merged_text == origin_text
    return merged_text, detail


# ---------------------------------------------------------------------------
# handoff rule
# ---------------------------------------------------------------------------


def merge_descriptions(base: str, tip: str, origin: str) -> str:
    """Merge the handoff ``description:`` additively at clause granularity.

    The description is a single quoted paragraph of ``"; "``-separated
    clauses that *every* wrap-up rewrites -- a 100%-collision span by
    construction -- so refusing here would make the whole replay useless.
    Instead: origin's paragraph stands; clauses the session removed are
    dropped when origin still carries them byte-identically; clauses the
    session added are appended. Nothing is ever lost -- an origin-side
    rewording of a clause the session also touched survives alongside the
    session's version, and the next wrap-up rewrites the paragraph anyway.

    Parameters
    ----------
    base, tip, origin:
        The raw quoted-scalar interiors of the three ``description:`` values.

    Returns
    -------
    str
        The merged description interior.
    """
    base_clauses = base.split("; ")
    tip_clauses = tip.split("; ")
    origin_clauses = origin.split("; ")

    unmatched_base = Counter(base_clauses)
    added: list[str] = []
    for clause in tip_clauses:
        if unmatched_base[clause] > 0:
            unmatched_base[clause] -= 1
        else:
            added.append(clause)
    removed = unmatched_base  # base clauses the session dropped or reworded

    out: list[str] = []
    for clause in origin_clauses:
        if removed[clause] > 0:
            removed[clause] -= 1
            continue
        out.append(clause)
    out.extend(added)
    if not out:
        raise RefusalError("description merge produced an empty value; escalating")
    return "; ".join(out)


def _split_handoff(text: str, path: str) -> tuple[list[str], int, str, list[str]]:
    """``(fm_rest, description_index, description, body_lines)`` or refuse."""
    lines = _lines(text)
    if not lines or lines[0] != "---":
        raise RefusalError(f"{path}: missing frontmatter; refusing to merge the handoff")
    try:
        close = lines[1:].index("---") + 1
    except ValueError:
        raise RefusalError(
            f"{path}: unterminated frontmatter; refusing to merge the handoff"
        ) from None
    fm = lines[1:close]
    body = lines[close + 1 :]
    desc_indices = [idx for idx, line in enumerate(fm) if line.startswith("description:")]
    if len(desc_indices) != 1:
        raise RefusalError(
            f"{path}: expected exactly one description: line, found {len(desc_indices)}"
        )
    m = _DESCRIPTION_RE.match(fm[desc_indices[0]])
    if m is None:
        raise RefusalError(
            f"{path}: description: is not a single-line double-quoted scalar; "
            "refusing to merge it"
        )
    fm_rest = fm[: desc_indices[0]] + fm[desc_indices[0] + 1 :]
    return fm_rest, desc_indices[0], m.group(1), body


def _split_sections(
    body: list[str], path: str
) -> tuple[list[str], list[tuple[str, str, list[str]]]]:
    """``(preamble, [(name, heading_line, body_lines)])`` -- level-2 model."""
    flags = _fence_flags(body)
    marks: list[tuple[int, str, str]] = []
    for idx, line in enumerate(body):
        if flags[idx]:
            continue
        m = _SECTION_RE.match(line)
        if m:
            marks.append((idx, m.group(1), line))
    names = [name for _idx, name, _raw in marks]
    duplicates = [name for name, count in Counter(names).items() if count > 1]
    if duplicates:
        raise RefusalError(
            f"{path}: duplicate handoff section heading(s) {duplicates}; sections are ambiguous"
        )
    if not marks:
        return list(body), []
    preamble = body[: marks[0][0]]
    sections: list[tuple[str, str, list[str]]] = []
    for pos, (idx, name, raw) in enumerate(marks):
        end = marks[pos + 1][0] if pos + 1 < len(marks) else len(body)
        sections.append((name, raw, body[idx + 1 : end]))
    return preamble, sections


def handoff_merge(
    base_text: str, tip_text: str, origin_text: str, path: str
) -> tuple[str, dict[str, Any]]:
    """Origin wins wholesale; re-apply only the session's touched sections.

    Section identification follows the ``handoff_sections`` collector's
    model (``## `` headings, fence-aware). Every replaced section carries the
    per-section base assertion: origin's copy must be byte-identical to the
    session base, or the replay refuses. The frontmatter ``description:``
    merges additively via ``merge_descriptions``; the remaining preamble
    (frontmatter rest plus everything above the first section) is one span
    that must agree on at least one side.

    Parameters
    ----------
    base_text, tip_text, origin_text:
        The file at the session base, the session tip, and origin's head.
    path:
        Repository-relative path, used in refusal messages.

    Returns
    -------
    tuple
        ``(merged_text, detail)`` -- the merged file content and a report
        fragment (rule, sections_replaced, description, unchanged).
    """
    b_fm_rest, _b_desc_idx, b_desc, b_body = _split_handoff(base_text, path)
    t_fm_rest, t_desc_idx, t_desc, t_body = _split_handoff(tip_text, path)
    o_fm_rest, o_desc_idx, o_desc, o_body = _split_handoff(origin_text, path)

    b_pre, b_secs = _split_sections(b_body, path)
    t_pre, t_secs = _split_sections(t_body, path)
    o_pre, o_secs = _split_sections(o_body, path)

    if [name for name, _raw, _body in t_secs] != [name for name, _raw, _body in b_secs]:
        raise RefusalError(
            f"{path}: the session added, removed, or reordered handoff sections; "
            "the replay only re-applies existing sections"
        )

    detail: dict[str, Any] = {
        "rule": "handoff",
        "sections_replaced": [],
        "description": "unchanged",
        "unchanged": False,
    }

    # The non-section preamble (frontmatter rest + body preamble) is one span.
    b_rest = (b_fm_rest, b_pre)
    t_rest = (t_fm_rest, t_pre)
    o_rest = (o_fm_rest, o_pre)
    if o_rest == b_rest:
        fm_rest, pre, desc_at = t_fm_rest, t_pre, t_desc_idx
    elif t_rest == b_rest or t_rest == o_rest:
        fm_rest, pre, desc_at = o_fm_rest, o_pre, o_desc_idx
    else:
        raise RefusalError(
            f"{path}: the handoff preamble (frontmatter/date/updated line) diverged on "
            "both sides and is not byte-identical to the session base; escalating"
        )

    if o_desc == b_desc:
        detail["description"] = "session" if t_desc != b_desc else "unchanged"
        desc = t_desc
    elif t_desc == b_desc or t_desc == o_desc:
        detail["description"] = "origin"
        desc = o_desc
    else:
        desc = merge_descriptions(b_desc, t_desc, o_desc)
        detail["description"] = "merged"

    b_map = {name: body for name, _raw, body in b_secs}
    t_map = {name: body for name, _raw, body in t_secs}
    touched = [name for name, _raw, body in b_secs if t_map[name] != body]
    o_names = {name for name, _raw, _body in o_secs}
    for name in touched:
        if name not in o_names:
            raise RefusalError(
                f"{path}: section '## {name}' this session touched was not found on "
                "origin; the replay never guesses"
            )

    out_body = list(pre)
    for name, raw, body in o_secs:
        if name in touched:
            if body != b_map[name]:
                raise RefusalError(
                    f"{path}: origin's copy of section '## {name}' is not byte-identical "
                    "to the session base; escalating"
                )
            out_body.append(raw)
            out_body.extend(t_map[name])
            detail["sections_replaced"].append(name)
        else:
            out_body.append(raw)
            out_body.extend(body)

    fm = fm_rest[:desc_at] + [f'description: "{desc}"'] + fm_rest[desc_at:]
    merged_text = _join(["---", *fm, "---", *out_body])
    detail["unchanged"] = merged_text == origin_text
    return merged_text, detail


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------


def _chunked(items: list[str], size: int = 100) -> list[list[str]]:
    return [items[k : k + size] for k in range(0, len(items), size)]


def _run_health(health_cmd: str | None, report: Report) -> None:
    """Run the vault health gate on the replayed tree, fail-closed."""
    if health_cmd is None:
        if not Path(HEALTH_SCRIPT).exists():
            report.health = "absent"
            return
        cmd = shlex.split(HEALTH_CMD_DEFAULT)
    else:
        cmd = shlex.split(health_cmd)
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, check=False, timeout=HEALTH_TIMEOUT_SECONDS
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        report.health = "failed"
        raise RefusalError(f"vault health could not run on the replayed tree ({exc})") from exc
    if proc.returncode != 0:
        report.health = "failed"
        tail = (proc.stderr.strip() or proc.stdout.strip()).splitlines()[-3:]
        raise RefusalError(
            "vault health failed on the replayed tree; nothing was pushed"
            + (f" ({' | '.join(tail)})" if tail else "")
        )
    report.health = "passed"


def _replay(base: str, remote: str, health_cmd: str | None, report: Report) -> None:
    marker = _operation_in_progress()
    if marker is not None:
        raise RefusalError(f"git operation in progress ({marker}); abort it first")

    # None on a detached HEAD (a Codex worktree): the result is then checked
    # out detached, since no local branch owns this session's commits.
    branch_proc = _run_git("symbolic-ref", "--short", "-q", "HEAD")
    branch = branch_proc.stdout.strip() if branch_proc.returncode == 0 else None
    report.branch = branch

    for scope, args in (
        ("unstaged", ["diff", "--quiet"]),
        ("staged", ["diff", "--cached", "--quiet"]),
    ):
        proc = _run_git(*args)
        if proc.returncode == 1:
            raise RefusalError(
                f"uncommitted changes present ({scope}); the replay switches branches, "
                "so the tree must be clean"
            )
        if proc.returncode != 0:
            raise GitError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")

    head = _git_out("rev-parse", "HEAD")
    report.old_head = head
    if not _is_ancestor(base, head):
        raise RefusalError(f"base {base[:12]} is not an ancestor of HEAD")

    try:
        sync_target = resolve_sync_target(remote)
    except UnresolvedTarget as exc:
        raise RefusalError(
            f"cannot resolve the sync target ({exc}); cannot verify origin, "
            "so the replay fails closed"
        ) from exc
    target = sync_target.target
    report.target = target
    report.target_source = sync_target.source

    fetch = _run_git("fetch", "--quiet", "--", remote, target)
    if fetch.returncode != 0:
        raise RefusalError(
            f"git fetch {remote} {target} failed ({fetch.stderr.strip() or 'no output'}); "
            "cannot verify origin, so the replay fails closed"
        )
    origin_head = _git_out("rev-parse", "FETCH_HEAD^{commit}")
    report.origin_head = origin_head

    if origin_head == head or _is_ancestor(head, origin_head):
        report.action = "none"
        report.reason = "origin already contains this session's head; nothing to replay"
        return
    if _is_ancestor(origin_head, head):
        report.action = "none"
        report.reason = "origin has not diverged; a plain push or rebase applies"
        return
    if not _is_ancestor(base, origin_head):
        raise RefusalError(
            f"base {base[:12]} is not an ancestor of {remote}/{target}; unpushed history "
            "predates this session, so attribution is ambiguous"
        )

    session_changes = _name_status(base, head)
    origin_changes = _name_status(base, origin_head)

    conflicts: dict[str, tuple[str, str]] = {}
    for path in sorted(set(session_changes) & set(origin_changes)):
        if _blob_sha(head, path) == _blob_sha(origin_head, path):
            continue  # both sides made the identical change
        conflicts[path] = (session_changes[path], origin_changes[path])
    report.conflicts = sorted(conflicts)

    if not conflicts:
        report.action = "none"
        report.reason = (
            "no path-level conflicts between the session and origin; a plain rebase applies"
        )
        return

    outside = sorted(path for path in conflicts if not is_allowlisted(path))
    if outside:
        report.outside_allowlist = outside
        raise RefusalError("conflicting files outside the allowlist: " + ", ".join(outside))

    merged: dict[str, str | None] = {}
    for path in sorted(conflicts):
        s_status, o_status = conflicts[path]
        if s_status != "M" or o_status != "M":
            raise RefusalError(
                f"{path}: conflict is not a plain modification on both sides "
                f"(session {s_status}, origin {o_status}); escalating"
            )
        base_text = _blob_text(base, path)
        tip_text = _blob_text(head, path)
        origin_text = _blob_text(origin_head, path)
        if path in LEDGER_FILES:
            merged_text, detail = ledger_merge(base_text, tip_text, origin_text, path)
        else:
            merged_text, detail = handoff_merge(base_text, tip_text, origin_text, path)
        report.files[path] = detail
        merged[path] = None if detail["unchanged"] else merged_text

    carried_add: list[str] = []
    carried_mod: list[str] = []
    carried_del: list[str] = []
    for path, status in session_changes.items():
        if path in origin_changes:
            continue
        if status == "D":
            carried_del.append(path)
        elif status == "A":
            carried_add.append(path)
        else:  # M or T
            carried_mod.append(path)
    report.carried = {
        "added": sorted(carried_add),
        "modified": sorted(carried_mod),
        "deleted": sorted(carried_del),
    }

    replay_branch = REPLAY_BRANCH_PREFIX + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if _run_git("rev-parse", "--verify", "--quiet", f"refs/heads/{replay_branch}").returncode == 0:
        raise RefusalError(f"replay branch {replay_branch} already exists; refusing to reuse it")
    report.replay_branch = replay_branch

    switch = _run_git("switch", "--quiet", "-c", replay_branch, origin_head)
    if switch.returncode != 0:
        raise RefusalError(
            f"could not branch from {remote}/{target} ({switch.stderr.strip() or 'no output'})"
        )

    try:
        for group in _chunked(sorted(carried_add) + sorted(carried_mod)):
            _git_out("checkout", "--quiet", head, "--", *group)
        for group in _chunked(sorted(carried_del)):
            _git_out("rm", "--quiet", "--", *group)
        to_write = {path: text for path, text in merged.items() if text is not None}
        for path, text in to_write.items():
            Path(path).write_text(text, encoding="utf-8")
        for group in _chunked(sorted(to_write)):
            _git_out("add", "--", *group)

        expected = set(carried_add) | set(carried_mod) | set(carried_del) | set(to_write)
        staged_raw = _run_git("diff", "--cached", "--name-only", "-z", origin_head)
        if staged_raw.returncode != 0:
            raise GitError(f"git diff --cached failed: {staged_raw.stderr.strip()}")
        staged = {p for p in staged_raw.stdout.split("\0") if p}
        if staged != expected:
            raise RefusalError(
                "replay staging mismatch: "
                f"unexpected {sorted(staged - expected)}, missing {sorted(expected - staged)}"
            )

        if not expected:
            new_head = origin_head
        else:
            summary = ", ".join(
                f"{path} (+{detail.get('inserted', len(detail.get('sections_replaced', [])))})"
                for path, detail in sorted(report.files.items())
            )
            message = (
                f"vault sync: entry-replay of session {head[:12]} onto {remote}/{target}\n"
                "\n"
                f"Conflicted hub files replayed onto origin's copies: {summary or 'none'}.\n"
                f"Session-only paths carried: {sum(len(v) for v in report.carried.values())}.\n"
                "Every replaced span was asserted byte-identical to the session base\n"
                "(per entry / per section) before replacement; ledger anchors were\n"
                "re-sorted newest-first (the-workshop#893).\n"
            )
            _git_out("commit", "--quiet", "-m", message)
            new_head = _git_out("rev-parse", "HEAD")
            if _git_out("rev-parse", f"{new_head}^") != origin_head:
                raise RefusalError("replay commit verification failed (unexpected parent)")

        _run_health(health_cmd, report)

        if branch is None:
            _git_out("switch", "--quiet", "--detach", new_head)
        else:
            _git_out("branch", "-f", branch, new_head)
            _git_out("switch", "--quiet", branch)
        _run_git("branch", "--quiet", "-D", replay_branch)
        report.new_head = new_head
        report.action = "replayed"
        inserted = sum(detail.get("inserted", 0) for detail in report.files.values())
        sections = sum(
            len(detail.get("sections_replaced", [])) for detail in report.files.values()
        )
        report.reason = (
            f"replayed {len(conflicts)} conflicted hub file(s) onto {remote}/{target}: "
            f"{inserted} entries inserted, {sections} handoff section(s) re-applied; "
            "push is now a fast-forward"
        )
    except BaseException:
        restore_ok = True
        back = (
            ("switch", "--quiet", "--detach", head)
            if branch is None
            else ("switch", "--quiet", branch)
        )
        for step in (
            ("reset", "--hard", "--quiet", origin_head),
            back,
            ("branch", "--quiet", "-D", replay_branch),
        ):
            if _run_git(*step).returncode != 0:
                restore_ok = False
        report.restored = restore_ok
        raise


def replay(base: str, remote: str, health_cmd: str | None) -> Report:
    """Run the fallback and always come back with a Report, never an exception.

    Parameters
    ----------
    base:
        Resolved SHA of the commit before this session's first commit -- the
        same session base the wrap-up audit and the #892 squash use.
    remote:
        Remote name to fetch and replay onto.
    health_cmd:
        Override for the health gate command; None runs the default
        ``uv run --script ci/vault_health.py`` when that script exists.

    Returns
    -------
    Report
        ``replayed`` on success, ``none`` when there is nothing for the
        fallback to do, ``refused`` when any fail-closed guard fired.
    """
    report = Report(action="refused", reason="", remote=remote, base=base)
    try:
        _replay(base, remote, health_cmd, report)
    except RefusalError as exc:
        report.action = "refused"
        report.reason = str(exc)
    except (GitError, OSError) as exc:
        report.action = "refused"
        report.reason = f"git failure: {exc}"
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Scoped, fail-closed entry-replay of this session's hub-file changes onto "
            "origin, for /sync conflicts confined to the vault's allowlisted "
            "accumulating files."
        )
    )
    parser.add_argument(
        "--base",
        required=True,
        help="commit before this session's first commit (the wrap-up audit base)",
    )
    parser.add_argument("--remote", default="origin", help="remote to fetch and replay onto")
    parser.add_argument(
        "--health-cmd",
        default=None,
        help=(
            "override the vault health command (default: 'uv run --script "
            "ci/vault_health.py' when that file exists on the replayed tree)"
        ),
    )
    parser.add_argument("--json", action="store_true", dest="as_json", help="emit a JSON report")
    args = parser.parse_args(argv)

    if _run_git("rev-parse", "--git-dir").returncode != 0:
        print("error: not inside a git repository", file=sys.stderr)
        return 2
    base_proc = _run_git("rev-parse", "--verify", "--quiet", f"{args.base}^{{commit}}")
    if base_proc.returncode != 0:
        print(f"error: --base {args.base!r} is not a commit in this repository", file=sys.stderr)
        return 2

    report = replay(base_proc.stdout.strip(), args.remote, args.health_cmd)

    if args.as_json:
        print(json.dumps(asdict(report), indent=2))
    else:
        print(f"{report.action}: {report.reason}")
        for path in report.outside_allowlist:
            print(f"  outside allowlist: {path}")
    return 1 if report.action == "refused" else 0


if __name__ == "__main__":
    raise SystemExit(main())
