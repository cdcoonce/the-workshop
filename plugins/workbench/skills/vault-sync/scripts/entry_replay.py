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
2. The session's per-file diff is computed content-level against the
   *merge-base* of HEAD and the fetched origin head -- not against ``--base``
   itself. ``--base`` is the commit before the session's first commit, but a
   session that already pushed some commits mid-session shares them with
   origin; reading those as additions on both sides would replay a pushed entry
   next to its own later correction. So ``--base`` only has to be an ancestor of
   (or equal to) the merge-base, else the replay refuses, and the merge-base is
   the three-way base for every merge, for the path-level conflict set and for
   the self-check (``--verify`` does the same). After the #892 squash the
   session is one hunk set.
3. Ledger rule: the session's change is read per anchor block as *whole
   entries* -- new dated entries, and existing entries edited in place (an
   in-place correction like the vault's ``2455bf8c``, even one that changes
   the entry's own heading line -- when the date is unchanged and the heading
   text or the body mostly is; overwriting an entry with a different one is a
   deletion). Each entry the session edited must be
   byte-identical, exactly once, in origin's block; origin's entries the
   session did not touch simply win, corrections included. New entries are
   added unless origin already holds them. Nothing is re-sorted: origin's
   entries keep their exact order (real blocks are not uniformly ordered, so a
   block-wide sort would rewrite entries the session never touched), an edited
   entry keeps its origin position, and each new entry is placed *positionally*,
   not by date: immediately after the session's predecessor entry (the nearest
   earlier entry of the tip block that origin also holds), which must appear on
   origin exactly once byte-identical -- else immediately before the session's
   successor entry under the same requirement, else the replay refuses. A new
   entry that opens the session's block goes to the top of origin's block,
   directly under the preamble. New entries sharing a position keep the
   session's order; the #874 ordering-drift detector, not the replay, is the
   order tooth. A correction both sides made identically (origin already holds
   exactly the session's edited entry) is already applied. An anchor is a block's innermost non-entry
   heading (``### Wins`` under ``## Q3 2026``, ``## Technical``). An entry
   heading ends in ``(YYYY-MM-DD)`` or ``(YYYY-MM-DD, qualifier)``, or starts
   with a date; a dated ``- **YYYY-MM-DD`` bullet inside a heading entry is
   body text, not an entry. Deleting an entry, editing a block preamble, or
   changing any text outside the anchor blocks refuses. The output is
   *spliced*, not re-serialized: origin's raw lines with only the session's
   entries replaced or inserted, so the block preamble and every untouched
   entry stay byte-identical, a replaced entry keeps origin's trailing blank
   lines, and a new entry copies the block's separator style (a tight list
   stays tight). A leftover base/tip entry pair counts as an edit only when
   it is the unique similar match (same date; same heading text, a mostly
   unchanged body, or -- for a bodyless one-line bullet -- a mostly unchanged
   start line).
4. Handoff rule: origin's file wins wholesale; inside each ``##`` section this
   session touched (the ``handoff_sections`` collector's section model) the
   replay is item-level -- an item is a top-level ``- `` bullet with its
   continuation, or a blank-separated paragraph (a code fence keeps its lines
   inside one item). Base items are aligned to origin's by position, not
   content: every item the session replaced must be unchanged and aligned on
   origin, and an inserted item lands right after its aligned base predecessor
   (one origin itself added is not inserted twice; an item that merely looks
   like an existing one is kept). Items compare ignoring trailing blank lines,
   so loose and tight lists align. Both sides making the same delete or the
   same edit is already applied, and a changed item with a byte-identical twin
   in a section origin also changed refuses (the twin cannot be told apart). The
   ``_Updated`` stamp resolves three-way instead of counting as a preamble
   divergence, and the frontmatter ``description:`` is merged additively at
   clause granularity rather than restored as the session's whole paragraph.
   An inserted item keeps the session's own blank-line separators (a paragraph
   appended after another stays blank-separated). Sections both sides renamed
   identically are matched by position; any other added, removed or reordered
   section refuses.
5. Assertions, fail-closed: before every replacement, origin's corresponding
   span must be byte-identical to the session-base version, with spans drawn
   per *replaced* entry / per *replaced* item -- exactly the spans the replay
   replaces, never wider and never skipped, which is spec, not preference.
   Any assertion failure, any entry deletion, or any conflict outside the
   allowlist refuses and leaves the repository exactly as it found it. Every
   conflicting file is evaluated first, so the report's ``refusals`` names
   each one. A file whose base, tip or origin ends inside an open code fence
   refuses too (its headings cannot be trusted). The escalation path is
   unchanged.
   Self-verification: the merged text of every file is re-checked against
   both sides with the ``--verify`` line-multiset comparison before anything
   is written; a merge that loses or duplicates a line refuses ("self-check").
   There is no flag to skip it. Only two handoff lines are resolved by rule
   rather than counted: the frontmatter ``description:`` and the body-preamble
   ``_Updated`` stamp, each of which must hold exactly the version the merge
   rule chooses; everywhere else such lines are ordinary lines.
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
(needs no git or network; it also flags a duplicated anchor path and an
unclosed code fence), so a shape defect is fixed at write time rather
than discovered as a refusal at sync. ``--verify --base B --tip T --origin O
--result R`` checks a hand-built merge against both sides by multiset of
non-blank lines over every path either side or the result touches -- run it after any user-approved hand rebuild that follows a
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

# CommonMark fence: up to three spaces of indent, then 3+ backticks or tildes.
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
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
    # ``git merge-base HEAD <origin head>``: the three-way base actually used.
    # It equals ``base`` unless the session already published commits.
    merge_base: str | None = None
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


def _fence_scan(lines: list[str]) -> tuple[list[bool], bool]:
    """``(flags, open_at_end)`` for ``lines`` under CommonMark fence rules.

    ``flags`` marks every line inside or delimiting a code fence. A fence
    opens on 3+ backticks or tildes (up to three spaces of indent; a backtick
    fence's info string holds no backtick) and closes only on a line of the
    *same* character at least as long as the opener with nothing but
    whitespace after it -- so a four-backtick fence is not ended by an inner
    three-backtick line. ``open_at_end`` is True when a fence is still open
    after the last line: either genuinely unclosed, or closed by something
    this recognizer does not accept (an over-indented opener, say, whose
    closer then reads as a new opener). Either way the file's heading
    structure cannot be trusted, so the replay refuses it.
    """
    flags: list[bool] = []
    fence_char = ""
    fence_len = 0
    for line in lines:
        m = _FENCE_RE.match(line)
        if fence_char:
            flags.append(True)
            if (
                m
                and m.group(1)[0] == fence_char
                and len(m.group(1)) >= fence_len
                and not m.group(2).strip()
            ):
                fence_char = ""
                fence_len = 0
            continue
        if m and not (m.group(1)[0] == "`" and "`" in m.group(2)):
            fence_char = m.group(1)[0]
            fence_len = len(m.group(1))
            flags.append(True)
            continue
        flags.append(False)
    return flags, bool(fence_char)


def _fence_flags(lines: list[str]) -> list[bool]:
    """Per-line "inside (or delimiting) a code fence" flags (see ``_fence_scan``)."""
    return _fence_scan(lines)[0]


def _require_closed_fences(lines: list[str], path: str, what: str) -> list[bool]:
    """Fence flags for ``lines``, refusing when a fence is still open at the end."""
    flags, open_at_end = _fence_scan(lines)
    if open_at_end:
        raise RefusalError(
            f"{path}: the {what} ends inside an unclosed or unrecognized code fence; "
            "its headings cannot be trusted, so the replay refuses it"
        )
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


def _load_doc(
    text: str, path: str = "<ledger>", what: str = "ledger", strict: bool = True
) -> _Doc:
    lines = _lines(text)
    flags = _require_closed_fences(lines, path, what) if strict else _fence_flags(lines)
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
    session's new entries are added unless origin already holds them. Origin's
    entry order is never rewritten: new entries are placed positionally, after
    the session's predecessor entry (see ``_place_new_entries``).

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
    base = _load_doc(base_text, path, "session base")
    tip = _load_doc(tip_text, path, "session tip")
    origin = _load_doc(origin_text, path, "origin copy")
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
            if origin_keys[old.key] == 0 and origin_keys[edited.key] == 1:
                # Origin already holds exactly the session's edited version and
                # no longer the base one: both sides made the same correction.
                detail["duplicates_skipped"] += 1
                continue
            if origin_keys[old.key] != 1:
                raise RefusalError(
                    f"{path}: origin's copy of entry {old.label!r} the session edited is "
                    "not byte-identical exactly once (edited or removed on origin); escalating"
                )
            swaps[old.key] = edited

        present = Counter(origin_keys)
        kept: list[_Chunk] = []
        already_on_origin: set[int] = set()
        for chunk in new_entries:
            if present[chunk.key] > 0:
                present[chunk.key] -= 1
                detail["duplicates_skipped"] += 1
                already_on_origin.add(id(chunk))
                continue
            kept.append(chunk)

        # Which tip entry is which origin entry: unchanged entries and entries
        # origin already holds by their own bytes; an entry the session edited by
        # the base version origin still carries (or the edited one when origin
        # already made the same edit).
        idents: dict[int, tuple[str, ...]] = {}
        edited_from = {id(edited): old for old, edited in replaced}
        new_ids = {id(chunk) for chunk in new_entries}
        for chunk in tip_block.entries:
            if id(chunk) in edited_from:
                old = edited_from[id(chunk)]
                idents[id(chunk)] = old.key if origin_keys[old.key] == 1 else chunk.key
            elif id(chunk) not in new_ids or id(chunk) in already_on_origin:
                idents[id(chunk)] = chunk.key
        slots = _place_new_entries(
            tip_block.entries, origin_block.entries, kept, idents, anchor_line, path
        )
        shape_check = [*origin_block.entries, *swaps.values(), *kept]
        kinds = {chunk.kind for chunk in shape_check}
        levels = {chunk.level for chunk in shape_check}
        if len(kinds) > 1 or len(levels) > 1:
            raise RefusalError(
                f"{path}: entries under {anchor_line!r} mix shapes across the two sides; "
                "refusing to merge them"
            )

        at_eof = origin_block.end_idx == len(origin.lines)
        interior = _splice_interior(origin_block, swaps, slots, at_eof)
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


def _place_new_entries(
    tip_entries: list[_Chunk],
    origin_entries: list[_Chunk],
    new_entries: list[_Chunk],
    idents: dict[int, tuple[str, ...]],
    anchor_line: str,
    path: str,
) -> dict[int, list[_Chunk]]:
    """Where each new entry goes: ``{slot: [entries]}``, slot = origin entry index.

    Placement is positional, never by date: blocks are not uniformly ordered
    (the Brag Doc's ``### Growth`` runs oldest-first), so a date rule would
    relocate entries the session placed elsewhere and invert ascending blocks.
    A new entry goes immediately after the session's *predecessor* -- the
    nearest earlier entry of the tip block that is also an origin entry
    (``idents`` maps it to the key origin holds) -- provided that entry appears
    on origin byte-identically exactly once. When it does not, the entry goes
    immediately before the session's *successor* (the nearest later such
    entry) under the same requirement; with neither, the replay refuses. A new
    entry with no predecessor at all sits at the top of the session's block, so
    it goes to the top of origin's block, directly under the preamble. New
    entries sharing a position keep their tip order.
    """
    positions: dict[tuple[str, ...], list[int]] = {}
    for index, chunk in enumerate(origin_entries):
        positions.setdefault(chunk.key, []).append(index)

    def unique_index(entry: _Chunk | None) -> int | None:
        if entry is None:
            return None
        found = positions.get(idents[id(entry)], [])
        return found[0] if len(found) == 1 else None

    new_ids = {id(chunk) for chunk in new_entries}
    slots: dict[int, list[_Chunk]] = {}
    for j, chunk in enumerate(tip_entries):
        if id(chunk) not in new_ids:
            continue
        predecessor = next(
            (e for e in reversed(tip_entries[:j]) if id(e) in idents), None
        )
        if predecessor is None:
            slots.setdefault(0, []).append(chunk)
            continue
        at = unique_index(predecessor)
        if at is not None:
            slots.setdefault(at + 1, []).append(chunk)
            continue
        successor = next((e for e in tip_entries[j + 1 :] if id(e) in idents), None)
        at = unique_index(successor)
        if at is None:
            raise RefusalError(
                f"{path}: the session's new entry {chunk.label!r} under {anchor_line!r} has no "
                "safe placement: neither its predecessor nor its successor entry is "
                "byte-identical exactly once on origin (edited, removed or duplicated there); "
                "escalating"
            )
        slots.setdefault(at, []).append(chunk)
    return slots


def _trailing_blanks(chunk: _Chunk) -> list[str]:
    return chunk.lines[len(chunk.key) :]


def _splice_interior(
    block: _Block,
    swaps: dict[tuple[str, ...], _Chunk],
    slots: dict[int, list[_Chunk]],
    at_eof: bool,
) -> list[str]:
    """Origin's block interior with only the session's entries spliced in.

    The block preamble and every untouched entry stay byte-identical, blank
    lines included. A replaced entry's lines (without their trailing blanks)
    become the session's entry lines, and origin keeps its own trailing blanks
    for that slot. A new entry is inserted at its slot with a separator that
    copies the block's style: when the origin entry next to the slot is
    followed by a blank line the new entry is too, otherwise (a tight list) it
    is not.
    """
    entries = block.entries
    out = list(block.preamble)
    if not entries:
        new = slots.get(0, [])
        if new:
            if not out:
                out.append("")
            elif out[-1].strip():
                out.append("")
            for position, chunk in enumerate(new):
                out.extend(chunk.key)
                if not (at_eof and position == len(new) - 1):
                    out.append("")
        return out
    for index, chunk in enumerate(entries):
        incoming = slots.get(index, [])
        if incoming:
            neighbour = entries[index - 1] if index else chunk
            separator = [""] if _trailing_blanks(neighbour) else []
            for new_chunk in incoming:
                out.extend(new_chunk.key)
                out.extend(separator)
        replacement = swaps.get(chunk.key)
        if replacement is None:
            out.extend(chunk.lines)
        else:
            out.extend(replacement.key)
            out.extend(_trailing_blanks(chunk))
    incoming = slots.get(len(entries), [])
    if incoming:
        last = entries[-1]
        if _trailing_blanks(last):
            for new_chunk in incoming:
                out.extend(new_chunk.key)
                out.append("")
        elif at_eof and any(_trailing_blanks(chunk) for chunk in entries):
            # A loose list whose last entry ends the file: blank line between
            # entries, none after the last.
            for new_chunk in incoming:
                out.append("")
                out.extend(new_chunk.key)
        else:
            for new_chunk in incoming:
                out.extend(new_chunk.key)
    return out


def _heading_text(chunk: _Chunk) -> str:
    """An entry's start line without its date: the part a rename would change."""
    line = chunk.lines[0]
    bullet = _BULLET_ENTRY_RE.match(line)
    if bullet:
        return line[bullet.end() :].strip()
    heading = _HEADING_RE.match(line)
    if heading is None:
        return line.strip()
    text = heading.group(2)
    lead = _LEAD_DATE_RE.match(text)
    if lead:
        return text[lead.end() :].strip()
    trail = _TRAIL_DATE_RE.search(text)
    return text[: trail.start()].strip() if trail else text.strip()


_DATE_TOKEN_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _same_entry_edited(old: _Chunk, edited: _Chunk) -> bool:
    """Is ``edited`` plausibly ``old`` with its start line changed?

    Required before a leftover entry of a ``replace`` is treated as an
    in-place edit: otherwise overwriting an entry with a brand-new one would
    read as an edit and silently lose the old entry. Same date, and either the
    same heading text or enough similarity: a body that is mostly unchanged,
    or -- when either side has no body at all (a one-line Brag bullet) -- a
    start line that is mostly unchanged once the date token is removed. With
    nothing but a start line to go on, an unrelated same-day entry must not
    pass for an edit.
    """
    if old.day != edited.day:
        return False
    if _heading_text(old) == _heading_text(edited):
        return True
    old_body = "\n".join(_strip_trailing_blanks(old.lines[1:]))
    new_body = "\n".join(_strip_trailing_blanks(edited.lines[1:]))
    if old_body and new_body:
        return difflib.SequenceMatcher(None, old_body, new_body).ratio() >= 0.6
    old_start = _DATE_TOKEN_RE.sub("", old.lines[0])
    new_start = _DATE_TOKEN_RE.sub("", edited.lines[0])
    return difflib.SequenceMatcher(None, old_start, new_start).ratio() >= 0.6


def _pair_leftovers(
    lost: list[_Chunk], unpaired_tip: list[_Chunk]
) -> tuple[list[tuple[_Chunk, _Chunk]], list[_Chunk], list[_Chunk]]:
    """Pair leftover base entries with leftover tip entries by unique similarity.

    A base entry pairs with a tip entry only when it is the base entry's one
    candidate (``_same_entry_edited``) and no other base entry also claims it.
    Returns ``(pairs, still_lost, still_unpaired_tip)``.
    """
    candidates = {
        id(old): [new for new in unpaired_tip if _same_entry_edited(old, new)] for old in lost
    }
    claims = Counter(id(options[0]) for options in candidates.values() if len(options) == 1)
    pairs: list[tuple[_Chunk, _Chunk]] = []
    still_lost: list[_Chunk] = []
    taken: set[int] = set()
    for old in lost:
        options = candidates[id(old)]
        if len(options) == 1 and claims[id(options[0])] == 1:
            pairs.append((old, options[0]))
            taken.add(id(options[0]))
        else:
            still_lost.append(old)
    return pairs, still_lost, [new for new in unpaired_tip if id(new) not in taken]


def _diff_entries(
    base_block: _Block, tip_block: _Block, anchor_line: str, path: str
) -> tuple[list[_Chunk], list[tuple[_Chunk, _Chunk]]]:
    """Classify the session's entry changes: ``(inserted, [(base, edited)])``.

    A ``replace`` opcode pairs each base entry with the tip entry that has the
    identical start line (an in-place edit with neighbouring insertions lands
    in one opcode); leftover base entries then pair with the leftover tip
    entry that is plausibly the same entry with its start line changed, when
    that match is unique (``_pair_leftovers``). Remaining tip entries are
    insertions. Any base entry left without a partner -- and any ``delete`` --
    is a deletion and refuses.
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
            pairs, lost, unpaired_tip = _pair_leftovers(lost, unpaired_tip)
            replaced.extend(pairs)
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
    # A clause origin already carries (both sides added it) is not appended again.
    out.extend(clause for clause in added if clause not in origin_clauses)
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
    flags = _require_closed_fences(body, path, "handoff body")
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


_Item = tuple[tuple[str, ...], int]  # (content lines, trailing blank-line count)


def _items(body: list[str]) -> list[_Item]:
    """Split a section body into items: the replay's unit inside a section.

    An item is a top-level ``- `` bullet plus its continuation (the indented
    lines that follow it), or a non-bullet unindented line that follows a
    blank line, which opens a new paragraph item. Each item is ``(content,
    blanks)``: its lines without trailing blank lines, and how many blank
    lines followed -- the separator is carried, not compared, so a tight list
    and a loose one (or a last bullet that gained a trailing blank on both
    sides) still align. Whatever precedes the first item (typically the blank
    line under the heading) is an item of empty content, and so are the blank
    lines that end the section. Lines inside a code fence never open an item,
    so a blank or ``- `` line in a fenced block stays with the item that
    holds the fence; the fence's own opening line can. ``_item_lines`` turns
    items back into the exact original lines.
    """
    end = len(body)
    while end > 0 and body[end - 1] == "":
        end -= 1
    flags = _fence_flags(body)
    raw: list[list[str]] = []
    current: list[str] = []
    for idx, line in enumerate(body[:end]):
        inside_fence = flags[idx] and not _is_fence_opener(flags, idx)
        opens = (
            bool(line)
            and not inside_fence
            and not line[0].isspace()
            and (line.startswith("- ") or (bool(current) and current[-1] == ""))
        )
        if opens and current:
            raw.append(current)
            current = []
        current.append(line)
    if current:
        raw.append(current)
    if end < len(body):
        raw.append(body[end:])
    items: list[_Item] = []
    for lines in raw:
        stop = len(lines)
        while stop > 0 and lines[stop - 1] == "":
            stop -= 1
        items.append((tuple(lines[:stop]), len(lines) - stop))
    return items


def _item_lines(items: list[_Item]) -> list[str]:
    return [line for content, blanks in items for line in (*content, *([""] * blanks))]


def _is_fence_opener(flags: list[bool], idx: int) -> bool:
    """Is line ``idx`` the opening line of a fence (flagged, previous line not)?"""
    return flags[idx] and (idx == 0 or not flags[idx - 1])


def _align_items(
    base: list[tuple[str, ...]], origin: list[tuple[str, ...]]
) -> dict[int, int]:
    """Map base item index -> origin item index for items unchanged on origin.

    Positional, not by content: two byte-identical items (``- Links: [[x]]``
    under different topics) are different items, and a content search would
    happily target the wrong one. Only items inside ``equal`` blocks of an
    ordered diff are mapped; everything else was changed or removed on origin.
    """
    mapping: dict[int, int] = {}
    matcher = difflib.SequenceMatcher(None, base, origin, autojunk=False)
    for tag, i1, i2, j1, _j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(i2 - i1):
                mapping[i1 + offset] = j1 + offset
    return mapping


def _has_content(content: tuple[str, ...]) -> bool:
    return any(line.strip() for line in content)


def _label(content: tuple[str, ...]) -> str:
    """A short name for an item in a refusal message."""
    return content[0][:60] if content else "<blank>"


def _merge_section_items(
    base_body: list[str],
    tip_body: list[str],
    origin_body: list[str],
    path: str,
    name: str,
    counts: dict[str, int],
) -> list[str]:
    """Re-apply the session's item-level edits of one section onto origin's body.

    Base items are aligned to origin's by position (``_align_items``) on their
    content, ignoring trailing blank lines. Every item the session replaced or
    deleted must be mapped -- unchanged and aligned on origin -- and the mapped
    run contiguous; an insertion anchors on the mapped origin position of the
    base item before it (an insertion at the very top goes to the section
    top). Further guards, each fail-closed:

    * *Already applied.* When origin made the identical change to the same
      base items (both deleted them, or both rewrote them to the same text),
      there is nothing left to apply.
    * *Already present.* A session-inserted item is dropped only when it is
      byte-identical to an item origin itself *added* (one the alignment does
      not map from base), at most once per such origin item -- never because
      an existing item looks the same, which would lose a move or a deliberate
      repeat.
    * *Twins.* An item the session changed (or anchors an insertion on) that
      has a byte-identical twin in the base or origin section, in a section
      origin also changed, cannot be placed with certainty: refuse.

    Placements that overlap refuse.
    """
    base_items = _items(base_body)
    tip_items = _items(tip_body)
    origin_items = _items(origin_body)
    bc = [content for content, _blanks in base_items]
    tc = [content for content, _blanks in tip_items]
    oc = [content for content, _blanks in origin_items]
    mapping = _align_items(bc, oc)
    origin_changed = bc != oc
    mapped_origin = set(mapping.values())
    origin_added = Counter(
        oc[j] for j in range(len(oc)) if j not in mapped_origin and _has_content(oc[j])
    )
    origin_ops = [
        op
        for op in difflib.SequenceMatcher(None, bc, oc, autojunk=False).get_opcodes()
        if op[0] in ("replace", "delete")
    ]

    def fresh(j1: int, j2: int) -> list[int]:
        """Tip item indices in ``[j1, j2)`` origin did not itself add."""
        kept: list[int] = []
        for j in range(j1, j2):
            content = tip_items[j][0]
            if _has_content(content) and origin_added[content] > 0:
                origin_added[content] -= 1
                continue
            kept.append(j)
        return kept

    def twinned(index: int) -> bool:
        content = bc[index]
        return (
            origin_changed
            and _has_content(content)
            and (bc.count(content) > 1 or oc.count(content) > 1)
        )

    placements: list[tuple[int, int, list[_Item]]] = []
    blank_fix: dict[int, int] = {}  # origin item index -> blank count it ends up with
    matcher = difflib.SequenceMatcher(None, bc, tc, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag == "insert":
            if i1 == 0:
                anchor = 0
            elif i1 - 1 in mapping:
                if twinned(i1 - 1):
                    raise RefusalError(
                        f"{path}: in '## {name}', the item before the session's insertion "
                        f"({_label(bc[i1 - 1])!r}) has a byte-identical twin and origin also "
                        "changed the section; the twin cannot be told apart; escalating"
                    )
                anchor = mapping[i1 - 1] + 1
            else:
                raise RefusalError(
                    f"{path}: in '## {name}', the item before the session's insertion "
                    f"({_label(bc[i1 - 1])!r}) is not unchanged on origin "
                    "(byte-identical and aligned); escalating"
                )
            kept = fresh(j1, j2)
            if kept:
                # Inserted items keep the session's own blank separators. Next to
                # a content item the separator after that item becomes the
                # session's (it is now followed by the first inserted item). The
                # last inserted item keeps the session's separator when origin
                # still follows the anchor with the item the session wrote it
                # against; otherwise (origin inserted there) it takes over the
                # blank count origin's anchor had.
                incoming = [tip_items[j] for j in kept]
                if anchor and _has_content(oc[anchor - 1]):
                    blank_fix[anchor - 1] = tip_items[max(kept[0] - 1, 0)][1]
                    tip_next = tc[kept[-1] + 1] if kept[-1] + 1 < len(tc) else None
                    origin_next = oc[anchor] if anchor < len(oc) else None
                    if tip_next is None or tip_next != origin_next:
                        incoming[-1] = (incoming[-1][0], origin_items[anchor - 1][1])
                placements.append((anchor, anchor, incoming))
                counts["items_inserted"] += len(incoming)
            continue
        if any(
            o_tag == tag and (oi1, oi2) == (i1, i2) and oc[oj1:oj2] == tc[j1:j2]
            for o_tag, oi1, oi2, oj1, oj2 in origin_ops
        ):
            continue  # origin already made this exact change
        run = list(range(i1, i2))
        if any(index not in mapping for index in run) or any(
            mapping[b] + 1 != mapping[a] for a, b in zip(run[1:], run, strict=False)
        ):
            raise RefusalError(
                f"{path}: in '## {name}', the session's changed item "
                f"{_label(bc[i1])!r} is not byte-identical, aligned, "
                "and contiguous on origin (edited or removed there); escalating"
            )
        if any(twinned(index) for index in run):
            raise RefusalError(
                f"{path}: in '## {name}', the session's changed item "
                f"{next(_label(bc[i]) for i in run if twinned(i))!r} has a byte-identical twin "
                "and origin also changed the section; the twin cannot be told apart; escalating"
            )
        start = mapping[i1]
        replacement = [tip_items[j] for j in fresh(j1, j2)]
        if replacement:
            last_blanks = origin_items[mapping[run[-1]]][1]
            replacement[-1] = (replacement[-1][0], last_blanks)
        placements.append((start, start + len(run), replacement))
        counts["items_replaced"] += len(run)
    placements.sort(key=lambda placement: (placement[0], placement[1]))
    for (_s1, end1, _r1), (start2, _e2, _r2) in zip(placements, placements[1:], strict=False):
        if start2 < end1:
            raise RefusalError(
                f"{path}: the session's item edits in '## {name}' overlap on origin; escalating"
            )
    merged = list(origin_items)
    for index, blanks in blank_fix.items():
        merged[index] = (merged[index][0], blanks)
    for start, end, replacement in reversed(placements):
        merged[start:end] = replacement
    return _item_lines(merged)


def _identical_renames(base: list[str], tip: list[str], origin: list[str]) -> bool:
    """True when tip and origin renamed the same sections the same way.

    The session's section-name list equals origin's and differs from the base
    only by renames at the same positions: same length, and every position
    that changed holds a name that exists on neither the other side's list (a
    swap or a move reuses names, so it is a reorder; a length change is an
    add or a remove). Anything else keeps the "added, removed, or reordered"
    refusal.
    """
    if tip != origin or len(tip) != len(base):
        return False
    base_set, tip_set = set(base), set(tip)
    return all(b == t or (b not in tip_set and t not in base_set) for b, t in zip(base, tip, strict=True))


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

    b_names = [name for name, _raw, _body in b_secs]
    t_names = [name for name, _raw, _body in t_secs]
    o_section_names = [name for name, _raw, _body in o_secs]
    if t_names != b_names and not _identical_renames(b_names, t_names, o_section_names):
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

    # Sections pair by position, so a section both sides renamed identically is
    # still the same section: the base body is keyed by the tip's (= origin's) name.
    b_map = {t_name: body for t_name, (_n, _raw, body) in zip(t_names, b_secs, strict=True)}
    t_map = {name: body for name, _raw, body in t_secs}
    touched = [name for name in t_names if t_map[name] != b_map[name]]
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


def _self_check_message(path: str, verdict: dict[str, list[str]]) -> str:
    parts = []
    for kind, verb in (("missing", "loses"), ("extra", "duplicates or invents")):
        lines = verdict[kind]
        if lines:
            shown = "; ".join(repr(line[:80]) for line in lines[:3])
            more = f" (+{len(lines) - 3} more)" if len(lines) > 3 else ""
            parts.append(f"{verb} {len(lines)} line(s): {shown}{more}")
    return f"{path}: self-check: merged output " + " and ".join(parts)


def _merge_hub_file(
    path: str, base_text: str, tip_text: str, origin_text: str
) -> tuple[str, dict[str, Any]]:
    """Merge one conflicted hub file and verify the result before it can be used.

    Every rule is narrow by construction, but a rule can still be wrong in a
    case nobody wrote a test for. So the merged text is re-checked against
    both sides with the same line-multiset comparison ``--verify`` applies to
    a hand rebuild (``compare_texts``): a merge that loses or duplicates any
    line refuses. There is no flag to skip this.
    """
    if path in LEDGER_FILES:
        merged_text, detail = ledger_merge(base_text, tip_text, origin_text, path)
    else:
        merged_text, detail = handoff_merge(base_text, tip_text, origin_text, path)
    verdict = compare_texts(base_text, tip_text, origin_text, merged_text, path)
    if verdict["missing"] or verdict["extra"]:
        raise RefusalError(_self_check_message(path, verdict))
    return merged_text, detail


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
    # The session base is "the commit before this session's first commit", but
    # a session that already pushed some commits mid-session shares them with
    # origin: treating those as additions on both sides would replay a pushed
    # entry next to its own later correction. The three-way base is therefore
    # the merge-base of HEAD and origin, and ``base`` only has to sit at or
    # before it (else unpushed history predates the session).
    merge_base = _git_out("merge-base", head, origin_head)
    report.merge_base = merge_base
    if not _is_ancestor(base, merge_base):
        raise RefusalError(
            f"base {base[:12]} is not an ancestor of the merge-base {merge_base[:12]} of HEAD "
            f"and {remote}/{target}; unpushed history predates this session, so attribution "
            "is ambiguous"
        )

    session_changes = _name_status(merge_base, head)
    origin_changes = _name_status(merge_base, origin_head)

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
        base_text = _blob_text(merge_base, path)
        tip_text = _blob_text(head, path)
        origin_text = _blob_text(origin_head, path)
        try:
            merged_text, detail = _merge_hub_file(path, base_text, tip_text, origin_text)
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
                "new ledger entries were placed after the session's predecessor entry, origin's\n"
                "order untouched (the-workshop#893).\n"
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
        same session base the wrap-up audit and the #892 squash use. It must
        sit at or before ``git merge-base HEAD <origin head>``, which is the
        actual three-way base (the session may already have pushed commits).
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


_OPEN_FENCE_FINDING = (
    "{path}: the {what} ends inside an unclosed or unrecognized code fence; "
    "its headings cannot be trusted, so the replay would refuse it"
)


def _lint_ledger(text: str, path: str) -> list[str]:
    """Findings for one ledger: closed fences, unique anchors, every block parses."""
    doc = _load_doc(text, path, strict=False)
    findings: list[str] = []
    if _fence_scan(doc.lines)[1]:
        findings.append(_OPEN_FENCE_FINDING.format(path=path, what="ledger"))
    try:
        _unique_spans(doc, "file", path)
    except RefusalError as exc:
        findings.append(str(exc))
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
    """Findings for one handoff: frontmatter, closed fences, unique sections."""
    try:
        _fm, _desc_idx, _desc, body = _split_handoff(text, path)
    except RefusalError as exc:
        return [str(exc)]
    if _fence_scan(body)[1]:
        # An open fence hides every later heading from the replay's section
        # model, so flag the fence and count the headings it hides naively.
        findings = [_OPEN_FENCE_FINDING.format(path=path, what="handoff body")]
        names = [m.group(1) for line in body if (m := _SECTION_RE.match(line))]
        duplicates = [name for name, count in Counter(names).items() if count > 1]
        if duplicates:
            findings.append(f"{path}: duplicate handoff section heading(s) {duplicates}")
        return findings
    try:
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


def _is_ledger_name(path: str) -> bool:
    return Path(path).name in {Path(ledger).name for ledger in LEDGER_FILES}


def lint(paths: list[str], explicit: bool = False) -> dict[str, Any]:
    """Run the replay grammar over hub files without touching git or the network.

    Parameters
    ----------
    paths:
        Files to check. A ``handoff-<context>.md`` basename is a handoff; a
        ledger basename (``Gotchas.md``, ``Key Decisions.md``, ``Brag Doc.md``)
        is a ledger; anything else is not a hub file.
    explicit:
        True when the caller named the paths: a missing one, or one that is
        not a hub file, is then a finding. Default-set files that are absent
        are simply skipped.

    Returns
    -------
    dict
        ``{"ok": bool, "checked": [path...], "findings": [{"path", "message"}]}``.
        Nothing checked and nothing found is itself a finding.
    """
    checked: list[str] = []
    findings: list[dict[str, str]] = []
    for path in paths:
        file = Path(path)
        if not file.is_file():
            if explicit:
                findings.append({"path": path, "message": f"{path}: file is missing"})
            continue
        handoff = _is_handoff_path(path)
        if not handoff and not _is_ledger_name(path):
            findings.append(
                {"path": path, "message": f"{path}: not a hub file (neither a ledger nor a handoff digest)"}
            )
            continue
        checked.append(path)
        try:
            text = file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            findings.append({"path": path, "message": f"{path}: unreadable ({exc})"})
            continue
        found = _lint_handoff(text, path) if handoff else _lint_ledger(text, path)
        findings.extend({"path": path, "message": message} for message in found)
    if not checked and not findings:
        findings.append({"path": "", "message": "no hub files found; nothing was checked"})
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


# Two handoff lines are resolved by rule rather than by line arithmetic: every
# wrap-up rewrites the frontmatter ``description:`` and the body-preamble
# ``_Updated`` stamp, so both sides "changing" them is expected. The exemption
# is deliberately narrow -- handoff files only, those two lines only, and the
# result must hold exactly the version the merge rule chooses -- so a fenced
# ``description:`` line in a ledger, or an ``_Updated`` line deep in a section,
# is counted like any other line.


def _resolved_split(text: str, handoff: bool) -> tuple[list[str], list[str], list[str]]:
    """``(description_lines, stamp_lines, other_lines)`` for one file's text.

    Only for a handoff: the frontmatter ``description:`` line(s) and the
    body-preamble (before the first ``## `` heading, fence-aware) lines
    starting ``_Updated `` are split out; every other line is "other".
    """
    lines = text.splitlines()
    if not handoff:
        return [], [], lines
    exempt: set[int] = set()
    desc: list[int] = []
    body_start = 0
    if lines and lines[0] == "---" and "---" in lines[1:]:
        close = lines.index("---", 1)
        desc = [i for i in range(1, close) if lines[i].startswith("description:")]
        body_start = close + 1
    body = lines[body_start:]
    flags = _fence_flags(body)
    first_section = next(
        (i for i, line in enumerate(body) if not flags[i] and _SECTION_RE.match(line)), len(body)
    )
    stamp = [
        body_start + i for i in range(first_section) if body[i].startswith(_STAMP_PREFIX)
    ]
    exempt.update(desc)
    exempt.update(stamp)
    other = [line for i, line in enumerate(lines) if i not in exempt]
    return [lines[i] for i in desc], [lines[i] for i in stamp], other


def _expected_descriptions(base: list[str], tip: list[str], origin: list[str]) -> list[list[str]]:
    """The ``description:`` line lists a correct merge may hold (``handoff_merge``'s rule).

    Origin's when the session left it alone, the session's when origin did,
    origin's when both made the same change, else the clause-merged one. When a
    side is not a single parseable quoted scalar the rule cannot be applied and
    either side's version is accepted.
    """
    if tip == base or tip == origin:
        return [origin]
    if origin == base:
        return [tip]
    parsed: list[str] = []
    for side in (base, tip, origin):
        match = _DESCRIPTION_RE.match(side[0]) if len(side) == 1 else None
        if match is None:
            return [tip, origin]
        parsed.append(match.group(1))
    try:
        merged = merge_descriptions(*parsed)
    except RefusalError:
        return [tip, origin]
    return [[f'description: "{merged}"']]


def compare_texts(
    base: str, tip: str, origin: str, result: str, path: str = ""
) -> dict[str, list[str]]:
    """Compare one file's merge result to both sides by non-blank-line multisets.

    The result must hold every non-blank line exactly ``base - deletions +
    additions`` times (deletions by either side win; additions from both sides
    count). ``missing`` lists lines the result holds too few times -- an
    addition lost, but also *untouched* content lost -- and ``extra`` lines it
    holds too many times (a duplicated sentence, an invented line). A line both
    sides added is ``ambiguous``: any count from one copy up to two is fine.

    For a handoff path (``path`` names a ``handoff-<context>.md``) two lines are
    resolved by rule, not arithmetic, and only those: the frontmatter
    ``description:`` line and the body-preamble ``_Updated `` line (before the
    first ``## `` heading). The result must hold exactly the version the merge
    rule chooses -- stamp: the session's if the session changed it, else
    origin's; description: origin's if the session left it alone, the session's
    if origin did, else the clause-merged one -- reported under ``resolved``;
    anything else is ``extra`` (and the chosen version ``missing``). In every
    other file, and anywhere else in a handoff, such lines are ordinary lines.
    """
    missing: set[str] = set()
    extra: set[str] = set()
    resolved: list[str] = []
    handoff = _is_handoff_path(path) if path else False
    split = [_resolved_split(text, handoff) for text in (base, tip, origin, result)]
    for slot, rule in ((0, "description"), (1, "stamp")):
        b, t, o, r = (part[slot] for part in split)
        if not (b or t or o or r):
            continue
        if rule == "description":
            candidates = _expected_descriptions(b, t, o)
        else:
            candidates = [t if t != b else o]
        if r in candidates:
            resolved.extend(r)
        else:
            extra.update(r)
            missing.update(candidates[0])

    def rest(lines: list[str]) -> Counter[str]:
        return Counter(line for line in lines if line.strip())

    b, t, o, r = (rest(part[2]) for part in split)
    s_add, o_add = t - b, o - b
    s_del, o_del = b - t, b - o
    # A line both sides added, or both sides deleted copies of, is ambiguous:
    # the two edits may or may not have touched the same copy.
    ambiguous = (set(s_add) & set(o_add)) | (set(s_del) & set(o_del))
    for line in set(b) | set(t) | set(o) | set(r):
        both_add = s_add[line] and o_add[line]
        both_del = s_del[line] and o_del[line]
        kept_high = b[line] - max(s_del[line], o_del[line])
        kept_low = max(0, b[line] - s_del[line] - o_del[line]) if both_del else kept_high
        add_low = max(s_add[line], o_add[line]) if both_add else s_add[line] + o_add[line]
        low = kept_low + add_low
        high = kept_high + s_add[line] + o_add[line]
        if r[line] < low:
            missing.add(line)
        if r[line] > high:
            extra.add(line)
    return {
        "missing": sorted(missing),
        "extra": sorted(extra),
        "ambiguous": sorted(ambiguous),
        "resolved": sorted(resolved),
    }


def _effective_base(base: str, tip: str, origin: str) -> str:
    """``merge-base(tip, origin)`` when ``base`` is a strict ancestor of it, else ``base``.

    A session that pushed some commits mid-session shares them with origin; the
    caller's ``base`` (before the session's first commit) would then count those
    commits' content as additions on both sides. A merge-base that is not a
    descendant of ``base`` is left alone: the caller's ``base`` stands.
    """
    proc = _run_git("merge-base", tip, origin)
    if proc.returncode != 0:
        return base
    merge_base = proc.stdout.strip()
    if merge_base != base and _is_ancestor(base, merge_base):
        return merge_base
    return base


def verify_merge(base: str, tip: str, origin: str, result: str) -> dict[str, Any]:
    """Check a merge result against both sides, file by file.

    Covers every path changed base->tip or base->origin; see
    ``compare_texts`` for the per-file rule. A line-level check cannot see
    reordering; it catches the losses and inventions (a dropped addition, a
    duplicated sentence).

    ``base`` is the session base the caller names ("the commit before this
    session's first commit"). When the session already published some commits,
    origin holds them too, so the three-way base is ``merge-base(tip, origin)``
    -- used whenever ``base`` is a strict ancestor of it (``effective_base``).

    Parameters
    ----------
    base, tip, origin, result:
        Git revisions, resolved by the caller.

    Returns
    -------
    dict
        ``{"ok": bool, "effective_base": sha, "files": {path: {"missing",
        "extra", "ambiguous", "resolved"}}}``.
    """
    base = _effective_base(base, tip, origin)
    paths = sorted(
        set(_name_status(base, tip))
        | set(_name_status(base, origin))
        | set(_name_status(base, result))
        | set(_name_status(origin, result))
    )
    files: dict[str, dict[str, list[str]]] = {}
    for path in paths:
        files[path] = compare_texts(
            *(_blob_or_empty(rev, path) for rev in (base, tip, origin, result)), path
        )
    ok = all(not entry["missing"] and not entry["extra"] for entry in files.values())
    return {"ok": ok, "effective_base": base, "files": files}


def _clip(line: str, width: int = 100) -> str:
    return line if len(line) <= width else line[: width - 3] + "..."


def _resolve_rev(rev: str) -> str | None:
    proc = _run_git("rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}")
    return proc.stdout.strip() if proc.returncode == 0 else None


def _main_lint(args: argparse.Namespace) -> int:
    paths = args.paths or _default_lint_paths()
    outcome = lint(paths, explicit=bool(args.paths))
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
        if outcome["effective_base"] != revs["base"]:
            print(
                f"note: origin holds later session commits; compared against merge-base "
                f"{outcome['effective_base'][:12]}, not --base {revs['base'][:12]}"
            )
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
