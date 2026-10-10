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
3. Ledger rule: the session's change is read per anchor block as *whole
   entries* -- new dated entries, and existing entries edited in place (an
   in-place correction like the vault's ``2455bf8c``, even one that changes
   the entry's own heading line). Each entry the session edited must be
   byte-identical, exactly once, in origin's block; origin's entries the
   session did not touch simply win, corrections included. New entries are
   added unless origin already holds them, and every entry under the anchor is
   re-sorted newest-first by date -- the deterministic re-linearization that
   keeps #871's ordering guarantee under concurrency (#871's ordering-drift
   detector stays on as the tooth). An anchor is a block's innermost non-entry
   heading (``### Wins`` under ``## Q3 2026``, ``## Technical``). An entry
   heading ends in ``(YYYY-MM-DD)`` or ``(YYYY-MM-DD, qualifier)``, or starts
   with a date; a dated ``- **YYYY-MM-DD`` bullet inside a heading entry is
   body text, not an entry. Deleting an entry, editing a block preamble, or
   changing any text outside the anchor blocks refuses.
4. Handoff rule: origin's file wins wholesale; inside each ``##`` section this
   session touched (the ``handoff_sections`` collector's section model) the
   replay is item-level -- an item is a top-level ``- `` bullet with its
   continuation, or a blank-separated paragraph. Every item the session
   replaced must occur in origin's section byte-identically exactly once; an
   inserted item lands right after its (unique) base predecessor. The
   ``_Updated`` stamp resolves three-way instead of counting as a preamble
   divergence, and the frontmatter ``description:`` is merged additively at
   clause granularity rather than restored as the session's whole paragraph.
5. Assertions, fail-closed: before every replacement, origin's corresponding
   span must be byte-identical to the session-base version, with spans drawn
   per *replaced* entry / per *replaced* item -- exactly the spans the replay
   replaces, never wider and never skipped, which is spec, not preference.
   Any assertion failure, any entry deletion, or any conflict outside the
   allowlist refuses and leaves the repository exactly as it found it. Every
   conflicting file is evaluated first, so the report's ``refusals`` names
   each one. The escalation path is unchanged.
6. ``ci/vault_health.py`` runs on the replayed tree before anything is
   pushed; a failure restores the original state.

Where the #892 squash boundary fails *open* (every guard degrades to
today's behavior), this fallback fails *closed*: it rewrites shared ledger
content, so every uncertainty stops it. Exit codes: 0 for ``replayed`` and
``none`` (sync proceeds -- after ``replayed`` the push is a fast-forward),
1 for ``refused`` (stop and alert; the repository has been restored), 2 for
usage errors.

Two read-only companions share the module's grammar. ``--lint [PATH ...]``
checks that every ledger block and handoff parses under the replay grammar
(needs no git or network), so a shape defect is fixed at write time rather
than discovered as a refusal at sync. ``--verify --base B --tip T --origin O
--result R`` checks a hand-built merge against both sides by multiset of
non-blank lines -- run it after any user-approved hand rebuild that follows a
refusal, and do not push on a failure. ``scripts/entry_replay_backtest.py`` in
the workshop repository measures all of this against real vault history.
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
# A rolling digest is `handoff-<context>.md`; a dotted stem (`handoff-personal.prev.md`)
# is a backup or variant, never a digest the replay or lint should touch.
_HANDOFF_NAME_RE = re.compile(r"^handoff-[A-Za-z0-9_-]+\.md$")
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
# A Gotchas heading ends in ``(YYYY-MM-DD)`` or ``(YYYY-MM-DD<sep>qualifier)``
# where sep is a comma or space and the qualifier holds no parentheses -- the
# live vault carries ``(2026-10-10, [[apipulse]])`` and ``(2026-09-14 onward, [[x]])``
# alongside the bare form. The entry's date is always the first one.
_TRAIL_DATE_RE = re.compile(r"\((\d{4}-\d{2}-\d{2})(?:[ ,][^()]*)?\)$")
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
    # Every refusal found, not just the first: [{"path": ..., "reason": ...}].
    # ``reason`` stays the first one, so a reader of the old shape still works.
    refusals: list[dict[str, str]] = field(default_factory=list)
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
    return path.startswith(HANDOFF_PREFIX) and bool(
        _HANDOFF_NAME_RE.match(path[len(".brain/"):])
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

    Refuses on mixed entry heading levels, and -- for heading-kind blocks --
    on any undated heading at or below the entries' level, which would make
    entry boundaries ambiguous. A block with any dated heading is a
    heading-entry block: dated bullets inside it are body text.
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

    # Entry-kind precedence: a block holding any dated heading is a
    # heading-entry block, so a ``- **YYYY-MM-DD`` line inside it is body text
    # (a Gotchas entry quoting a dated bullet), never an entry start. Blocks
    # without a dated heading keep bullet entries (the Brag Doc shape).
    if any(started[0] == "heading" for _idx, started in starts):
        starts = [(idx, started) for idx, started in starts if started[0] == "heading"]

    kind = starts[0][1][0]  # one kind by construction: all heading, or all bullet
    levels = {started[1] for _idx, started in starts}
    if len(levels) > 1:
        raise RefusalError(
            f"{path}: {context} mixes entry heading levels {sorted(levels)}; "
            "refusing to re-linearize it"
        )
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


@dataclass
class _Span:
    """One anchor block's extent in a document: heading line to next boundary."""

    anchor_idx: int
    end_idx: int  # exclusive
    path: tuple[str, ...]
    line: str


@dataclass
class _Doc:
    """A ledger parsed just far enough to locate its anchor blocks."""

    lines: list[str]
    flags: list[bool]
    headings: list[tuple[int, int, str]]
    spans: list[_Span]

    def interior(self, span: _Span) -> list[str]:
        return self.lines[span.anchor_idx + 1 : span.end_idx]

    def by_path(self) -> dict[tuple[str, ...], list[_Span]]:
        out: dict[tuple[str, ...], list[_Span]] = {}
        for span in self.spans:
            out.setdefault(span.path, []).append(span)
        return out

    def outside(self) -> list[str]:
        """Every line that is not inside an anchor block's interior."""
        keep = [True] * len(self.lines)
        for span in self.spans:
            for idx in range(span.anchor_idx + 1, span.end_idx):
                keep[idx] = False
        return [line for line, kept in zip(self.lines, keep, strict=True) if kept]


def _anchor_spans(
    lines: list[str], flags: list[bool], headings: list[tuple[int, int, str]]
) -> list[_Span]:
    """The anchor blocks of a ledger: its innermost non-entry headings.

    An anchor is a non-entry heading of level 2 or deeper whose next heading
    is an entry heading, a heading no deeper than itself, or nothing -- so
    ``## Technical`` (Gotchas, Key Decisions) and ``### Wins`` (Brag Doc, under
    ``## Q3 2026``) are anchors while ``## Q3 2026`` is not. A block runs to the
    next heading no deeper than its own, so Wins and Growth sort separately.
    """
    spans: list[_Span] = []
    for pos, (idx, lvl, raw) in enumerate(headings):
        if lvl < 2 or parse_entry_start(raw) is not None:
            continue
        if pos + 1 < len(headings):
            _nidx, nlvl, nraw = headings[pos + 1]
            if nlvl > lvl and parse_entry_start(nraw) is None:
                continue  # a deeper non-entry heading follows: not innermost
        spans.append(
            _Span(
                anchor_idx=idx,
                end_idx=_block_end(headings, idx, lvl, len(lines)),
                path=_heading_path(headings, lines, idx),
                line=raw,
            )
        )
    return spans


def _load_doc(text: str) -> _Doc:
    lines = _lines(text)
    flags = _fence_flags(lines)
    headings = _headings(lines, flags)
    return _Doc(lines, flags, headings, _anchor_spans(lines, flags, headings))


def _unique_spans(doc: _Doc, side: str, path: str) -> dict[tuple[str, ...], _Span]:
    out: dict[tuple[str, ...], _Span] = {}
    for span_path, spans in doc.by_path().items():
        if len(spans) != 1:
            raise RefusalError(
                f"{path}: anchor {spans[0].line!r} appears {len(spans)} times in the "
                f"{side}; anchors are ambiguous"
            )
        out[span_path] = spans[0]
    return out


def ledger_merge(
    base_text: str, tip_text: str, origin_text: str, path: str
) -> tuple[str, dict[str, Any]]:
    """Replay the session's entry-level ledger changes onto origin's copy.

    The session's change is read per anchor block as a set of *entries*
    (workshop #893): inserted entries, and whole entries edited in place. A
    deletion, a change outside the anchor blocks, or a change to a block
    preamble refuses. Origin's block is the starting point: each entry the
    session edited must be byte-identical, exactly once, in origin's block
    (the narrow per-replaced-entry assertion -- origin's copies of entries the
    session did not touch simply win, including their corrections); the
    session's new entries are added unless origin already holds them, and the
    block is re-sorted newest-first by date.

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
        fragment (rule, anchors, inserted, replaced, duplicates_skipped,
        unchanged).

    Raises
    ------
    RefusalError
        On any session change outside the anchor blocks or in a block
        preamble, any entry deletion, any anchor missing or ambiguous on
        origin, an origin-side preamble edit, an edited entry origin no longer
        holds byte-identically exactly once, or mixed entry shapes.
    """
    base = _load_doc(base_text)
    tip = _load_doc(tip_text)
    origin = _load_doc(origin_text)
    base_spans = _unique_spans(base, "session base", path)
    tip_spans = _unique_spans(tip, "session tip", path)

    if base.outside() != tip.outside() or set(base_spans) != set(tip_spans):
        raise RefusalError(
            f"{path}: the session changed text outside the anchor blocks "
            "(or added/removed an anchor heading); escalating"
        )
    origin_by_path = origin.by_path()

    detail: dict[str, Any] = {
        "rule": "ledger",
        "anchors": [],
        "inserted": 0,
        "replaced": 0,
        "duplicates_skipped": 0,
        "unchanged": False,
    }
    replacements: list[tuple[_Block, list[str]]] = []
    for apath, base_span in base_spans.items():
        tip_span = tip_spans[apath]
        if base.interior(base_span) == tip.interior(tip_span):
            continue  # this block was not touched
        anchor_line = base_span.line
        base_block = _parse_block(base.lines, base.flags, base.headings, base_span.anchor_idx, path)
        tip_block = _parse_block(tip.lines, tip.flags, tip.headings, tip_span.anchor_idx, path)
        if _strip_trailing_blanks(base_block.preamble) != _strip_trailing_blanks(tip_block.preamble):
            raise RefusalError(
                f"{path}: the session edited the preamble under {anchor_line!r}; "
                "only dated entries may change; escalating"
            )

        candidates = origin_by_path.get(apath, [])
        if len(candidates) != 1:
            raise RefusalError(
                f"{path}: anchor {anchor_line!r} was not found exactly once on origin "
                f"(found {len(candidates)}); the replay never guesses a new anchor"
            )
        origin_block = _parse_block(
            origin.lines, origin.flags, origin.headings, candidates[0].anchor_idx, path
        )
        if _strip_trailing_blanks(base_block.preamble) != _strip_trailing_blanks(
            origin_block.preamble
        ):
            raise RefusalError(
                f"{path}: origin's preamble under {anchor_line!r} is not byte-identical "
                "to the session base; escalating"
            )

        new_entries, replaced = _diff_entries(base_block, tip_block, anchor_line, path)

        origin_keys = Counter(chunk.key for chunk in origin_block.entries)
        swaps: dict[tuple[str, ...], _Chunk] = {}
        for old, edited in replaced:
            if origin_keys[old.key] != 1:
                raise RefusalError(
                    f"{path}: origin's copy of entry {old.label!r} the session edited is "
                    "not byte-identical exactly once (edited or removed on origin); escalating"
                )
            swaps[old.key] = edited

        present = Counter(origin_keys)
        kept: list[_Chunk] = []
        for chunk in new_entries:
            if present[chunk.key] > 0:
                present[chunk.key] -= 1
                detail["duplicates_skipped"] += 1
                continue
            kept.append(chunk)

        merged_entries = kept + [swaps.get(chunk.key, chunk) for chunk in origin_block.entries]
        kinds = {chunk.kind for chunk in merged_entries}
        levels = {chunk.level for chunk in merged_entries}
        if len(kinds) > 1 or len(levels) > 1:
            raise RefusalError(
                f"{path}: entries under {anchor_line!r} mix shapes across the two sides; "
                "refusing to re-linearize"
            )
        merged_entries.sort(key=lambda chunk: chunk.day, reverse=True)

        at_eof = origin_block.end_idx == len(origin.lines)
        interior = _emit_interior(origin_block.preamble, merged_entries, at_eof)
        replacements.append((origin_block, interior))
        detail["anchors"].append(anchor_line)
        detail["inserted"] += len(kept)
        detail["replaced"] += len(swaps)

    out = list(origin.lines)
    for origin_block, interior in sorted(replacements, key=lambda item: -item[0].anchor_idx):
        out[origin_block.anchor_idx + 1 : origin_block.end_idx] = interior
    merged_text = _join(out)
    detail["unchanged"] = merged_text == origin_text
    return merged_text, detail


def _diff_entries(
    base_block: _Block, tip_block: _Block, anchor_line: str, path: str
) -> tuple[list[_Chunk], list[tuple[_Chunk, _Chunk]]]:
    """Classify the session's entry changes: ``(inserted, [(base, edited)])``.

    A ``replace`` opcode pairs each base entry with the tip entry that has the
    identical start line (an in-place edit with one or more neighbouring
    insertions lands in one opcode); when exactly one base and one tip entry
    remain unpaired they are an in-place edit that also changed the start
    line. Remaining tip entries are insertions. Any base entry left without a
    partner -- and any ``delete`` -- is a deletion and refuses.
    """
    base_keys = [chunk.key for chunk in base_block.entries]
    tip_keys = [chunk.key for chunk in tip_block.entries]
    inserted: list[_Chunk] = []
    replaced: list[tuple[_Chunk, _Chunk]] = []
    matcher = difflib.SequenceMatcher(None, base_keys, tip_keys, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag == "insert":
            inserted.extend(tip_block.entries[j1:j2])
            continue
        lost: list[_Chunk] = []
        if tag == "delete":
            lost = base_block.entries[i1:i2]
            unpaired_tip: list[_Chunk] = []
        else:
            unpaired_tip = list(tip_block.entries[j1:j2])
            for old in base_block.entries[i1:i2]:
                partner = next(
                    (chunk for chunk in unpaired_tip if chunk.lines[0] == old.lines[0]), None
                )
                if partner is None:
                    lost.append(old)
                else:
                    unpaired_tip.remove(partner)
                    replaced.append((old, partner))
            if len(lost) == 1 and len(unpaired_tip) == 1:
                replaced.append((lost.pop(), unpaired_tip.pop()))
        if lost:
            raise RefusalError(
                f"{path}: the session deleted entry {lost[0].label!r} under {anchor_line!r}; "
                "entry deletions escalate to a human"
            )
        inserted.extend(unpaired_tip)
    return inserted, replaced


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


_STAMP_PREFIX = "_Updated "


def _stamp_lines(preamble: list[str]) -> list[str]:
    return [line for line in preamble if line.startswith(_STAMP_PREFIX)]


def _unstamped(preamble: list[str]) -> list[str]:
    return [line for line in preamble if not line.startswith(_STAMP_PREFIX)]


def _items(body: list[str]) -> list[tuple[str, ...]]:
    """Split a section body into items: the replay's unit inside a section.

    An item is a top-level ``- `` bullet plus its continuation (the indented
    lines and blank lines that follow it), or a non-bullet unindented line that
    follows a blank line, which opens a new paragraph item. Whatever precedes
    the first item (typically the blank line under the heading) is its own
    item, and so are the blank lines that end the section: two wrap-ups that
    both append a bullet to a section's end would otherwise each rewrite the
    last bullet's trailing blank and collide. Concatenating the items
    reproduces the body exactly.
    """
    end = len(body)
    while end > 0 and body[end - 1] == "":
        end -= 1
    items: list[tuple[str, ...]] = []
    current: list[str] = []
    for line in body[:end]:
        opens = bool(line) and not line[0].isspace() and (
            line.startswith("- ") or (bool(current) and current[-1] == "")
        )
        if opens and current:
            items.append(tuple(current))
            current = []
        current.append(line)
    if current:
        items.append(tuple(current))
    if end < len(body):
        items.append(tuple(body[end:]))
    return items


def _find_runs(
    haystack: list[tuple[str, ...]], run: list[tuple[str, ...]]
) -> list[int]:
    """Start indices where ``run`` occurs as a contiguous byte-identical run."""
    width = len(run)
    return [
        at for at in range(len(haystack) - width + 1) if haystack[at : at + width] == run
    ]


def _merge_section_items(
    base_body: list[str],
    tip_body: list[str],
    origin_body: list[str],
    path: str,
    name: str,
    counts: dict[str, int],
) -> list[str]:
    """Re-apply the session's item-level edits of one section onto origin's body.

    Every item the session replaced or deleted must occur in origin's body as
    a contiguous, byte-identical run exactly once; an insertion anchors on the
    base item before it, which must occur exactly once on origin (an insertion
    at the very top goes to the section top). Placements that overlap refuse.
    """
    base_items = _items(base_body)
    tip_items = _items(tip_body)
    origin_items = _items(origin_body)
    placements: list[tuple[int, int, list[tuple[str, ...]]]] = []
    matcher = difflib.SequenceMatcher(None, base_items, tip_items, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag == "insert":
            if i1 == 0:
                placements.append((0, 0, tip_items[j1:j2]))
            else:
                hits = _find_runs(origin_items, [base_items[i1 - 1]])
                if len(hits) != 1:
                    raise RefusalError(
                        f"{path}: in '## {name}', the item before the session's insertion "
                        f"({base_items[i1 - 1][0][:60]!r}) is not byte-identical exactly once on "
                        f"origin ({len(hits)} matches); escalating"
                    )
                placements.append((hits[0] + 1, hits[0] + 1, tip_items[j1:j2]))
            counts["items_inserted"] += j2 - j1
            continue
        run = base_items[i1:i2]
        hits = _find_runs(origin_items, run)
        if len(hits) != 1:
            raise RefusalError(
                f"{path}: in '## {name}', the session's changed item "
                f"{run[0][0][:60]!r} is not byte-identical exactly once on origin "
                f"({len(hits)} matches; edited or removed there); escalating"
            )
        placements.append((hits[0], hits[0] + len(run), tip_items[j1:j2]))
        counts["items_replaced"] += len(run)
    placements.sort(key=lambda placement: (placement[0], placement[1]))
    for (_s1, end1, _r1), (start2, _e2, _r2) in zip(placements, placements[1:], strict=False):
        if start2 < end1:
            raise RefusalError(
                f"{path}: the session's item edits in '## {name}' overlap on origin; escalating"
            )
    merged = list(origin_items)
    for start, end, replacement in reversed(placements):
        merged[start:end] = replacement
    return [line for item in merged for line in item]


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
        "items_replaced": 0,
        "items_inserted": 0,
        "description": "unchanged",
        "unchanged": False,
    }

    # The non-section preamble (frontmatter rest + body preamble) is one span,
    # except the ``_Updated`` stamp: every wrap-up rewrites it, so it is
    # resolved three-way below instead of counting as a divergence.
    b_rest = (b_fm_rest, _unstamped(b_pre))
    t_rest = (t_fm_rest, _unstamped(t_pre))
    o_rest = (o_fm_rest, _unstamped(o_pre))
    if o_rest == b_rest:
        fm_rest, pre, desc_at = t_fm_rest, t_pre, t_desc_idx
    elif t_rest == b_rest or t_rest == o_rest:
        fm_rest, pre, desc_at = o_fm_rest, o_pre, o_desc_idx
    else:
        raise RefusalError(
            f"{path}: the handoff preamble (frontmatter/date line) diverged on both "
            "sides beyond the _Updated stamp and is not byte-identical to the session "
            "base; escalating"
        )
    winning_stamp = (
        _stamp_lines(t_pre)
        if _stamp_lines(t_pre) != _stamp_lines(b_pre)
        else _stamp_lines(o_pre)
    )
    if _stamp_lines(pre) != winning_stamp:
        if len(_stamp_lines(pre)) != 1 or len(winning_stamp) != 1:
            raise RefusalError(
                f"{path}: the handoff _Updated stamp is not a single line on every side; "
                "escalating"
            )
        pre = [winning_stamp[0] if line.startswith(_STAMP_PREFIX) else line for line in pre]

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
        out_body.append(raw)
        if name in touched:
            out_body.extend(
                _merge_section_items(b_map[name], t_map[name], body, path, name, detail)
            )
            detail["sections_replaced"].append(name)
        else:
            out_body.extend(body)

    fm = fm_rest[:desc_at] + [f'description: "{desc}"'] + fm_rest[desc_at:]
    merged_text = _join(["---", *fm, "---", *out_body])
    detail["unchanged"] = merged_text == origin_text
    return merged_text, detail


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------


def _detail_summary(detail: dict[str, Any]) -> str:
    """One-line human summary of a per-file merge detail."""
    if detail["rule"] == "ledger":
        return f"+{detail['inserted']} inserted, {detail['replaced']} replaced"
    return (
        f"{len(detail['sections_replaced'])} section(s), "
        f"{detail['items_replaced']} replaced / {detail['items_inserted']} inserted items"
    )


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

    # Evaluate every conflicting file before refusing: the merges are pure
    # functions of three blobs (nothing in the repository moves until all of
    # them succeed), so one run can name every file that needs a human.
    refusals: list[dict[str, str]] = []
    outside = sorted(path for path in conflicts if not is_allowlisted(path))
    report.outside_allowlist = outside
    for path in outside:
        refusals.append(
            {"path": path, "reason": f"conflicting file outside the allowlist: {path}"}
        )

    merged: dict[str, str | None] = {}
    for path in sorted(conflicts):
        if path in outside:
            continue
        s_status, o_status = conflicts[path]
        if s_status != "M" or o_status != "M":
            refusals.append(
                {
                    "path": path,
                    "reason": (
                        f"{path}: conflict is not a plain modification on both sides "
                        f"(session {s_status}, origin {o_status}); escalating"
                    ),
                }
            )
            continue
        base_text = _blob_text(base, path)
        tip_text = _blob_text(head, path)
        origin_text = _blob_text(origin_head, path)
        try:
            if path in LEDGER_FILES:
                merged_text, detail = ledger_merge(base_text, tip_text, origin_text, path)
            else:
                merged_text, detail = handoff_merge(base_text, tip_text, origin_text, path)
        except RefusalError as exc:
            refusals.append({"path": path, "reason": str(exc)})
            continue
        report.files[path] = detail
        merged[path] = None if detail["unchanged"] else merged_text

    if refusals:
        report.refusals = refusals
        raise RefusalError(refusals[0]["reason"])

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
                f"{path} ({_detail_summary(detail)})"
                for path, detail in sorted(report.files.items())
            )
            message = (
                f"vault sync: entry-replay of session {head[:12]} onto {remote}/{target}\n"
                "\n"
                f"Conflicted hub files replayed onto origin's copies: {summary or 'none'}.\n"
                f"Session-only paths carried: {sum(len(v) for v in report.carried.values())}.\n"
                "Every replaced span was asserted byte-identical to the session base\n"
                "(per replaced entry / per replaced handoff item) before replacement;\n"
                "ledger anchors were re-sorted newest-first (the-workshop#893).\n"
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
        replaced = sum(detail.get("replaced", 0) for detail in report.files.values())
        items = sum(
            detail.get("items_replaced", 0) + detail.get("items_inserted", 0)
            for detail in report.files.values()
        )
        report.reason = (
            f"replayed {len(conflicts)} conflicted hub file(s) onto {remote}/{target}: "
            f"{inserted} entries inserted, {replaced} replaced, {items} handoff item(s) "
            "re-applied; push is now a fast-forward"
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


# ---------------------------------------------------------------------------
# --lint: does every hub file parse under the replay grammar?
# ---------------------------------------------------------------------------


def _is_handoff_path(path: str) -> bool:
    return bool(_HANDOFF_NAME_RE.match(Path(path).name))


def _lint_ledger(text: str, path: str) -> list[str]:
    """Findings for one ledger: every anchor block must parse, no orphan entries."""
    doc = _load_doc(text)
    findings: list[str] = []
    covered = [False] * len(doc.lines)
    for span in doc.spans:
        for idx in range(span.anchor_idx + 1, span.end_idx):
            covered[idx] = True
        try:
            _parse_block(doc.lines, doc.flags, doc.headings, span.anchor_idx, path)
        except RefusalError as exc:
            findings.append(str(exc))
    for idx, line in enumerate(doc.lines):
        if doc.flags[idx] or covered[idx]:
            continue
        if parse_entry_start(line) is not None:
            findings.append(
                f"{path}: dated entry {line!r} sits outside every anchor block "
                f"(line {idx + 1}); the replay could not place it"
            )
    return findings


def _lint_handoff(text: str, path: str) -> list[str]:
    """Findings for one handoff: frontmatter/description parse, unique sections."""
    try:
        _fm, _desc_idx, _desc, body = _split_handoff(text, path)
        _split_sections(body, path)
    except RefusalError as exc:
        return [str(exc)]
    return []


def _default_lint_paths() -> list[str]:
    paths = sorted(LEDGER_FILES)
    brain = Path(".brain")
    if brain.is_dir():
        paths.extend(
            sorted(str(p) for p in brain.glob("handoff-*.md") if _HANDOFF_NAME_RE.match(p.name))
        )
    return paths


def lint(paths: list[str]) -> dict[str, Any]:
    """Run the replay grammar over hub files without touching git or the network.

    Parameters
    ----------
    paths:
        Files to check; ``handoff-*.md`` basenames are handoffs, everything
        else is a ledger. Missing files are skipped.

    Returns
    -------
    dict
        ``{"ok": bool, "checked": [path...], "findings": [{"path", "message"}]}``.
    """
    checked: list[str] = []
    findings: list[dict[str, str]] = []
    for path in paths:
        file = Path(path)
        if not file.is_file():
            continue
        checked.append(path)
        try:
            text = file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            findings.append({"path": path, "message": f"{path}: unreadable ({exc})"})
            continue
        found = _lint_handoff(text, path) if _is_handoff_path(path) else _lint_ledger(text, path)
        findings.extend({"path": path, "message": message} for message in found)
    return {"ok": not findings, "checked": checked, "findings": findings}


# ---------------------------------------------------------------------------
# --verify: did a hand rebuild keep both sides' additions and invent nothing?
# ---------------------------------------------------------------------------


def _blob_or_empty(rev: str, path: str) -> str:
    if _blob_sha(rev, path) is None:
        return ""
    proc = subprocess.run(
        ["git", "cat-file", "blob", f"{rev}:{path}"], capture_output=True, check=False
    )
    if proc.returncode != 0:
        raise GitError(f"git cat-file blob {rev}:{path}: {proc.stderr.decode(errors='replace')}")
    return proc.stdout.decode("utf-8", errors="replace")


def _nonblank_lines(text: str) -> Counter[str]:
    return Counter(line for line in text.splitlines() if line.strip())


def compare_texts(base: str, tip: str, origin: str, result: str) -> dict[str, list[str]]:
    """Compare one file's merge result to both sides by non-blank-line multisets.

    Returns ``{"missing", "extra", "ambiguous"}``: ``missing`` is any line
    either side added that the result lacks, ``extra`` any line the result
    holds beyond ``base - deletions + additions``, and ``ambiguous`` the lines
    both sides added (one copy or two are both legitimate, so they never fail).
    Counter semantics throughout.
    """
    b, t, o, r = (_nonblank_lines(text) for text in (base, tip, origin, result))
    s_add, o_add = t - b, o - b
    s_del, o_del = b - t, b - o
    ambiguous = set(s_add) & set(o_add)
    missing = [line for line in ((s_add - r) + (o_add - r)) if line not in ambiguous]
    expected = (b - (s_del | o_del)) + s_add + o_add
    extra = [line for line in (r - expected) if line not in ambiguous]
    return {"missing": sorted(missing), "extra": sorted(extra), "ambiguous": sorted(ambiguous)}


def verify_merge(base: str, tip: str, origin: str, result: str) -> dict[str, Any]:
    """Check a merge result against both sides, file by file.

    Covers every path changed base->tip or base->origin; see
    ``compare_texts`` for the per-file rule. A line-level check cannot see
    reordering; it catches the losses and inventions (a dropped addition, a
    duplicated sentence).

    Parameters
    ----------
    base, tip, origin, result:
        Git revisions, resolved by the caller.

    Returns
    -------
    dict
        ``{"ok": bool, "files": {path: {"missing", "extra", "ambiguous"}}}``.
    """
    paths = sorted(set(_name_status(base, tip)) | set(_name_status(base, origin)))
    files: dict[str, dict[str, list[str]]] = {}
    for path in paths:
        files[path] = compare_texts(
            *(_blob_or_empty(rev, path) for rev in (base, tip, origin, result))
        )
    ok = all(not entry["missing"] and not entry["extra"] for entry in files.values())
    return {"ok": ok, "files": files}


def _clip(line: str, width: int = 100) -> str:
    return line if len(line) <= width else line[: width - 3] + "..."


def _resolve_rev(rev: str) -> str | None:
    proc = _run_git("rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}")
    return proc.stdout.strip() if proc.returncode == 0 else None


def _main_lint(args: argparse.Namespace) -> int:
    paths = args.paths or _default_lint_paths()
    outcome = lint(paths)
    if args.as_json:
        print(json.dumps(outcome, indent=2))
    else:
        for finding in outcome["findings"]:
            print(finding["message"])
        print(
            f"lint: {'clean' if outcome['ok'] else 'FINDINGS'} "
            f"({len(outcome['checked'])} file(s) checked)"
        )
    return 0 if outcome["ok"] else 1


def _main_verify(args: argparse.Namespace) -> int:
    revs: dict[str, str] = {}
    for label in ("base", "tip", "origin", "result"):
        value = getattr(args, label)
        if value is None:
            print(f"error: --verify needs --{label}", file=sys.stderr)
            return 2
        resolved = _resolve_rev(value)
        if resolved is None:
            print(f"error: --{label} {value!r} is not a commit in this repository", file=sys.stderr)
            return 2
        revs[label] = resolved
    try:
        outcome = verify_merge(revs["base"], revs["tip"], revs["origin"], revs["result"])
    except GitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.as_json:
        print(json.dumps(outcome, indent=2))
    else:
        for path, entry in outcome["files"].items():
            if not entry["missing"] and not entry["extra"]:
                continue
            print(f"FAIL {path}")
            for kind in ("missing", "extra"):
                for line in entry[kind]:
                    print(f"  {kind}: {_clip(line)}")
        for path, entry in outcome["files"].items():
            for line in entry["ambiguous"]:
                print(f"  ambiguous (both sides added) {path}: {_clip(line)}")
        print(f"verify: {'ok' if outcome['ok'] else 'FAIL'} ({len(outcome['files'])} file(s))")
    return 0 if outcome["ok"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Scoped, fail-closed entry-replay of this session's hub-file changes onto "
            "origin, for /sync conflicts confined to the vault's allowlisted "
            "accumulating files. --lint and --verify are read-only companions."
        )
    )
    parser.add_argument(
        "--base",
        help=(
            "commit before this session's first commit (the wrap-up audit base); "
            "with --verify, the merge base of the rebuild"
        ),
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
    parser.add_argument(
        "--lint",
        action="store_true",
        help=(
            "check that every ledger block and handoff parses under the replay grammar "
            "(default PATHs: the three ledgers plus .brain/handoff-*.md); needs no git"
        ),
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="check a hand-built merge result against both sides (needs --base/--tip/--origin/--result)",
    )
    parser.add_argument("--tip", help="--verify: the session tip revision")
    parser.add_argument("--origin", help="--verify: origin's head revision")
    parser.add_argument("--result", help="--verify: the hand-built merge result revision")
    parser.add_argument("paths", nargs="*", metavar="PATH", help="--lint: files to check")
    args = parser.parse_args(argv)

    if args.lint and args.verify:
        print("error: --lint and --verify are separate modes", file=sys.stderr)
        return 2
    if args.lint:
        return _main_lint(args)
    if _run_git("rev-parse", "--git-dir").returncode != 0:
        print("error: not inside a git repository", file=sys.stderr)
        return 2
    if args.verify:
        if args.base is None:
            print("error: --verify needs --base", file=sys.stderr)
            return 2
        return _main_verify(args)
    if args.paths:
        print("error: PATH arguments only apply to --lint", file=sys.stderr)
        return 2
    if args.base is None:
        print("error: --base is required", file=sys.stderr)
        return 2
    base_sha = _resolve_rev(args.base)
    if base_sha is None:
        print(f"error: --base {args.base!r} is not a commit in this repository", file=sys.stderr)
        return 2

    report = replay(base_sha, args.remote, args.health_cmd)

    if args.as_json:
        print(json.dumps(asdict(report), indent=2))
    else:
        print(f"{report.action}: {report.reason}")
        for refusal in report.refusals:
            print(f"  refused: {refusal['reason']}")
    return 1 if report.action == "refused" else 0


if __name__ == "__main__":
    raise SystemExit(main())
