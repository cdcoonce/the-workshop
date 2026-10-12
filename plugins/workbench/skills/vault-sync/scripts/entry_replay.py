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
   exactly the session's edited entry) is already applied; origin holding both
   the base version and a byte-identical copy of the edit refuses (replacing
   would leave the edit twice). A new session entry that pairs with an entry
   *origin added* since the merge-base refuses ("was a pushed commit amended or
   rebased?"): origin keeps the pushed version and the session re-adds the
   corrected one, and replaying both would put the entry in twice. The pairing
   is date-insensitive, because an amend can re-date the entry: everything the
   similarity rule below pairs on the same day, plus -- on any day -- the same
   heading text after the date, or two bodies of at least 60 characters that
   are at least 90% alike (entries of different days routinely share short
   boilerplate such as ``**Decided:**``, and only a near copy of a real body is
   an amend). An anchor is a block's innermost non-entry
   heading (``### Wins`` under ``## Q3 2026``, ``## Technical``). An entry
   heading ends in ``(YYYY-MM-DD)`` or ``(YYYY-MM-DD, qualifier)``, or starts
   with a date; a dated ``- **YYYY-MM-DD`` bullet inside a heading entry is
   body text, not an entry. Deleting an entry, editing a block preamble, or
   changing any text outside the anchor blocks refuses. The output is
   *spliced*, not re-serialized: origin's raw lines with only the session's
   entries replaced or inserted, so the block preamble and every untouched
   entry stay byte-identical. Blank lines are the session's wherever the
   session wrote them (separator semantics): a new entry ends with the blank
   lines it ended with in the session's file, the entry before an insertion (or
   the preamble, for one at the top of a block) takes the blank lines the
   session had before the new entry -- never a neighbour's, so a new entry is
   neither glued to a neighbour that lacked a trailing blank nor does it loosen
   a tight list -- and an entry the session kept or edited keeps origin's
   trailing blank lines unless only the session changed them (three-way, on the
   separator alone). A new entry whose session-side neighbour is not the entry
   origin has there takes the separator the session used between entries (at
   the end of a block, the end of origin's block). A leftover base/tip entry pair counts as an edit only when
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
   (one origin itself added *in the same gap* is not inserted twice; an item
   that merely looks like an existing one, or like one origin added elsewhere,
   is kept; but an inserted item that is a *version* of one origin inserted in
   the same gap -- an identical first line, one text opening the other's, or
   at least 90% alike, without being identical -- refuses, "was a pushed commit
   amended or rebased?": the handoff's amend guard, as for the ledgers; the
   same gap-after-a-replaced-run dedupe applies to the end of a replacement,
   where origin put the item that followed the one the session replaced).
   A *move* is an edit: a base item the session deleted and a tip item it
   inserted elsewhere in the section that read as versions of one another
   (identical first line, one text opening the other's, or at least 60% alike;
   best match first) are one move, or move-and-edit, of that item, so the item
   must be unchanged and aligned on origin like any replaced item -- difflib
   alone reads it as an unrelated delete and insert, and origin having deleted
   the item made the delete look already applied while the new copy resurrected
   it (or left two versions). A move origin made identically stays already
   applied. The new copy counts wherever it lands: next to an edit of its
   neighbour (the tip side of a ``replace`` opcode, paired in a second round
   that never takes a plain insert's pair) or in another touched section
   (``_refuse_cross_section_moves``: the item must be unchanged and aligned on
   origin in its own section unless origin made the identical move, same
   text into the same gap). The pairing runs on origin's side too: an item
   origin moved, within its section or into another, that the session deleted
   refuses -- origin's delete is half of a move, not an already-applied
   delete. Items compare ignoring trailing blank lines,
   so loose and tight lists align. Both sides making the same delete or the
   same edit is already applied, and a changed item with a byte-identical twin
   in a section origin also changed refuses (the twin cannot be told apart). The
   ``_Updated`` stamp resolves three-way instead of counting as a preamble
   divergence, and the frontmatter ``description:`` is merged additively at
   clause granularity rather than restored as the session's whole paragraph.
   Blank lines are the session's (separator semantics): an inserted item keeps
   its own separators (a paragraph appended after another stays
   blank-separated), the item before an insertion, a deletion or a replacement
   takes the separator the session gave it (deleting ``- b`` from ``- a``,
   ``- b``, blank, paragraph leaves a blank before the paragraph, not a glued
   continuation), and an item the session left in place keeps origin's
   separator unless only the session changed it. Sections both sides renamed
   identically are matched by position; any other added, removed or reordered
   section refuses.
5. Assertions, fail-closed: before every replacement, origin's corresponding
   span must be byte-identical to the session-base version, with spans drawn
   per *replaced* entry / per *replaced* item -- exactly the spans the replay
   replaces, never wider and never skipped, which is spec, not preference.
   Any assertion failure, any entry deletion, or any conflict outside the
   allowlist refuses and leaves the repository exactly as it found it. Every
   conflicting file is evaluated first, so the report's ``refusals`` names
   each one. An exception the merge functions do not anticipate is a refusal
   too ("internal error while merging <path>: <type>: <msg>; escalating"), with
   the JSON report and the repository untouched, never a traceback. A file whose base, tip or origin ends inside an open code fence
   refuses too (its headings cannot be trusted). The escalation path is
   unchanged.
   Self-verification: the merged text of every file is re-checked against
   both sides with the ``--verify`` line-multiset comparison before anything
   is written; a merge that loses or duplicates a line refuses ("self-check").
   There is no flag to skip it. Only two handoff lines are resolved by rule
   rather than counted: the frontmatter ``description:`` and the body-preamble
   ``_Updated`` stamp, each of which must hold exactly the version the merge
   rule chooses; everywhere else such lines are ordinary lines.
   Two structural invariants cover what a line multiset cannot see (it ignores
   blank lines and accepts one copy of a line both sides added). *Exactness
   (S1):* for every handoff ``##`` section and every ledger anchor block, when
   origin's copy equals the session base's, the merged unit must be
   byte-identical to the session's -- the merge functions assert it ("structural
   self-check: section/block X differs from the session's although origin did
   not change it") and the merge rules are built so that it never fires on a
   correct merge. *Item/entry level (S2):* every unit the session touched is
   re-split with the item/entry splitter the merge uses, and every merged item's
   content (trailing blank lines ignored) must consume one occurrence of an item
   origin or the session holds, an item both sides kept from the base counting
   once; an item neither side wrote -- two items glued by a lost blank line, an
   entry whose lines landed under another -- refuses ("structural self-check:
   merged section X contains an item neither side wrote"). ``--verify`` reports
   the same finding as ``glued`` and fails on it.
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
non-blank lines over every path either side or the result touches, and by item
(a ``glued`` item neither side wrote fails too) -- run it after any
user-approved hand rebuild that follows a refusal, and do not push on a failure. ``scripts/entry_replay_backtest.py`` in
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
        holds byte-identically exactly once (or holds beside a copy of the
        edit), a new entry that re-adds one origin gained since the base, a
        block that differs from the session's although origin left it alone, or
        mixed entry shapes.
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

        new_entries, replaced, matched = _diff_entries(base_block, tip_block, anchor_line, path)

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
            if origin_keys[edited.key] > 0:
                raise RefusalError(
                    f"{path}: origin holds both the base version of entry {old.label!r} and "
                    "a byte-identical copy of the session's edited version; replacing the "
                    "base one would leave the edited entry twice; escalating"
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
        _refuse_amended_re_add(origin_block, base_block, kept, anchor_line, path)

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
        tip_at_eof = tip_block.end_idx == len(tip.lines)
        trailing, pre_trailing = _separator_edits(
            base_block, tip_block, origin_block, [*matched, *replaced]
        )
        interior = _splice_interior(
            origin_block, swaps, slots, trailing, pre_trailing, tip_block, at_eof, tip_at_eof
        )
        if origin.interior(candidates[0]) == base.interior(base_span) and interior != tip.interior(
            tip_span
        ):
            raise RefusalError(
                f"{path}: structural self-check: block {anchor_line!r} differs from the "
                "session's although origin did not change it; escalating"
            )
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


@dataclass
class _Placed:
    """A new session entry with where it goes and which tip entry it was."""

    chunk: _Chunk
    tip_index: int
    by: str  # "top" (no predecessor), "pred" (after its predecessor), "succ" (before its successor)


def _place_new_entries(
    tip_entries: list[_Chunk],
    origin_entries: list[_Chunk],
    new_entries: list[_Chunk],
    idents: dict[int, tuple[str, ...]],
    anchor_line: str,
    path: str,
) -> dict[int, list[_Placed]]:
    """Where each new entry goes: ``{slot: [placed]}``, slot = origin entry index.

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
    slots: dict[int, list[_Placed]] = {}
    for j, chunk in enumerate(tip_entries):
        if id(chunk) not in new_ids:
            continue
        predecessor = next(
            (e for e in reversed(tip_entries[:j]) if id(e) in idents), None
        )
        if predecessor is None:
            slots.setdefault(0, []).append(_Placed(chunk, j, "top"))
            continue
        at = unique_index(predecessor)
        if at is not None:
            slots.setdefault(at + 1, []).append(_Placed(chunk, j, "pred"))
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
        slots.setdefault(at, []).append(_Placed(chunk, j, "succ"))
    return slots


def _trailing_blanks(chunk: _Chunk) -> list[str]:
    return chunk.lines[len(chunk.key) :]


def _trailing_of(lines: list[str]) -> list[str]:
    """The blank lines ``lines`` ends with (the part ``_strip_trailing_blanks`` drops)."""
    return lines[len(_strip_trailing_blanks(lines)) :]


def _origin_added_entries(base_block: _Block, origin_block: _Block) -> list[_Chunk]:
    """Origin's entries that are new since the base: not an edit of a base entry.

    Same classification as the session's own (``_diff_entries``): insertions,
    plus leftover entries of a replaced span that pair with no base entry.
    Entries origin deleted are not reported; they are not this check's concern.
    """
    base_keys = [chunk.key for chunk in base_block.entries]
    origin_keys = [chunk.key for chunk in origin_block.entries]
    added: list[_Chunk] = []
    matcher = difflib.SequenceMatcher(None, base_keys, origin_keys, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "insert":
            added.extend(origin_block.entries[j1:j2])
        elif tag == "replace":
            unpaired = list(origin_block.entries[j1:j2])
            lost: list[_Chunk] = []
            for old in base_block.entries[i1:i2]:
                partner = next((c for c in unpaired if c.lines[0] == old.lines[0]), None)
                if partner is None:
                    lost.append(old)
                else:
                    unpaired.remove(partner)
            added.extend(_pair_leftovers(lost, unpaired)[2])
    return added


def _refuse_amended_re_add(
    origin_block: _Block,
    base_block: _Block,
    kept: list[_Chunk],
    anchor_line: str,
    path: str,
) -> None:
    """Refuse a session-added entry that pairs with one origin added since the base.

    The replay's own similarity rule (``_amend_of``: ``_same_entry_edited``, or
    the same heading text after the date, or a mostly unchanged body) marks the session's entry as
    another version of an entry origin already gained since the merge-base --
    whatever the dates say, since an amend can re-date the entry. That is what a
    pushed commit that was then amended or rebased looks like (origin keeps the
    pushed version, the session re-adds the corrected one), and replaying it
    would leave both. Two
    sessions that really wrote the same entry independently look the same, and
    a human settles that one too.
    """
    for origin_chunk in _origin_added_entries(base_block, origin_block):
        for chunk in kept:
            if _amend_of(origin_chunk, chunk):
                raise RefusalError(
                    f"{path}: the session re-adds an entry origin already has in a different "
                    f"version ({chunk.label!r} vs origin's {origin_chunk.label!r} under "
                    f"{anchor_line!r}) -- was a pushed commit amended or rebased? escalating"
                )


def _separator_edits(
    base_block: _Block,
    tip_block: _Block,
    origin_block: _Block,
    pairs: list[tuple[_Chunk, _Chunk]],
) -> tuple[dict[int, list[str]], list[str] | None]:
    """The session's own blank-line changes to entries it left in place.

    ``pairs`` are the ``(base, tip)`` versions of every entry the session kept
    or edited. When origin's copy of such an entry still ends with the blank
    lines the base one did, the session's blank lines win (three-way, on the
    separator alone): a session that tightened a loose list, or added a spacer
    line, has that change carried. Returns ``({origin entry index: trailing
    lines}, preamble trailing lines or None)``.
    """
    index_of: dict[tuple[str, ...], list[int]] = {}
    for index, chunk in enumerate(origin_block.entries):
        index_of.setdefault(chunk.key, []).append(index)
    trailing: dict[int, list[str]] = {}
    for old, new in pairs:
        found = index_of.get(old.key, [])
        if len(found) != 1:
            continue
        origin_end = _trailing_blanks(origin_block.entries[found[0]])
        if origin_end == _trailing_blanks(old) and _trailing_blanks(new) != origin_end:
            trailing[found[0]] = _trailing_blanks(new)
    pre = None
    base_pre, tip_pre = _trailing_of(base_block.preamble), _trailing_of(tip_block.preamble)
    if tip_pre != base_pre and _trailing_of(origin_block.preamble) == base_pre:
        pre = tip_pre
    return trailing, pre


def _splice_interior(
    block: _Block,
    swaps: dict[tuple[str, ...], _Chunk],
    slots: dict[int, list[_Placed]],
    trailing: dict[int, list[str]],
    pre_trailing: list[str] | None,
    tip_block: _Block,
    at_eof: bool,
    tip_at_eof: bool,
) -> list[str]:
    """Origin's block interior with only the session's entries spliced in.

    The block preamble and every untouched entry stay byte-identical, blank
    lines included. A replaced entry's lines (without their trailing blanks)
    become the session's entry lines. Blank lines are the session's wherever
    the session wrote them: a replaced or kept entry ends with origin's blank
    lines unless only the session changed them (``trailing``); a new entry
    keeps the blank lines it ended with in the session's file; and the entry
    before an insertion (or the preamble, for one at the top) takes the blank
    lines the session had before the new entry -- never a neighbour's, so a
    new entry is not glued to a neighbour that lacked a blank line, nor a
    tight list loosened. Only an entry whose session-side neighbour is not
    the entry origin has there falls back to the separator the session used
    between entries (or, at the end of a block, the end of origin's block).
    """
    entries = block.entries
    tip_entries = tip_block.entries
    ends = [list(trailing.get(index, _trailing_blanks(chunk))) for index, chunk in enumerate(entries)]
    end_original = _trailing_blanks(entries[-1]) if entries else None
    out = list(block.preamble)
    if pre_trailing is not None:
        out = _strip_trailing_blanks(out) + pre_trailing
    for index, group in slots.items():
        first = group[0]
        if first.by == "top":
            out = _strip_trailing_blanks(out) + _trailing_of(tip_block.preamble)
        elif first.by == "pred" and index > 0:
            ends[index - 1] = _trailing_blanks(tip_entries[first.tip_index - 1])

    def emit(group: list[_Placed], following: _Chunk | None) -> list[str]:
        lines: list[str] = []
        for position, placed in enumerate(group):
            lines.extend(placed.chunk.key)
            tip_end = _trailing_blanks(placed.chunk)
            if position < len(group) - 1:
                lines.extend(tip_end)
                continue
            has_successor = placed.tip_index + 1 < len(tip_entries)
            if has_successor and following is not None:
                lines.extend(tip_end)
            elif has_successor:
                lines.extend(end_original if end_original is not None else tip_end)
            elif following is None:
                lines.extend(tip_end if tip_at_eof == at_eof or end_original is None else end_original)
            elif placed.tip_index > 0:
                lines.extend(_trailing_blanks(tip_entries[placed.tip_index - 1]))
            else:
                lines.extend([""] if _trailing_blanks(following) else [])
        return lines

    for index, chunk in enumerate(entries):
        out.extend(emit(slots.get(index, []), chunk))
        replacement = swaps.get(chunk.key)
        out.extend(chunk.key if replacement is None else replacement.key)
        out.extend(ends[index])
    out.extend(emit(slots.get(len(entries), []), None))
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


_AMEND_BODY_RATIO = 0.9
_AMEND_BODY_MIN = 60


def _amend_of(pushed: _Chunk, readded: _Chunk) -> bool:
    """Is ``readded`` plausibly an amended ``pushed`` entry, whatever its date says?

    The amend guard's pairing: everything ``_same_entry_edited`` pairs, plus --
    with the dates ignored, since an amend can re-date the entry -- the same
    heading text after the date, or two bodies that are nearly unchanged
    (``_AMEND_BODY_RATIO``, stricter than the same-day 0.6: entries of different
    days routinely share boilerplate such as ``**Decided:** ...``, and only a
    near copy is an amend). The start-line fallback for bodyless bullets stays
    same-day only: without a body to compare, a different day's unrelated
    bullet must not pass for an amend.
    """
    if _same_entry_edited(pushed, readded) or _heading_text(pushed) == _heading_text(readded):
        return True
    old_body = "\n".join(_strip_trailing_blanks(pushed.lines[1:]))
    new_body = "\n".join(_strip_trailing_blanks(readded.lines[1:]))
    return (
        min(len(old_body), len(new_body)) >= _AMEND_BODY_MIN
        and difflib.SequenceMatcher(None, old_body, new_body).ratio() >= _AMEND_BODY_RATIO
    )


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
) -> tuple[list[_Chunk], list[tuple[_Chunk, _Chunk]], list[tuple[_Chunk, _Chunk]]]:
    """Classify the session's entry changes: ``(inserted, [(base, edited)], matched)``.

    ``matched`` are the ``(base, tip)`` pairs the session left byte-identical.

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
    matched: list[tuple[_Chunk, _Chunk]] = []
    matcher = difflib.SequenceMatcher(None, base_keys, tip_keys, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            matched.extend(
                zip(base_block.entries[i1:i2], tip_block.entries[j1:j2], strict=True)
            )
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
    return inserted, replaced, matched


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


def _next_content(contents: list[tuple[str, ...]], index: int) -> tuple[str, ...] | None:
    """The content of the item after ``index``, or None at the end of the section."""
    return contents[index + 1] if index + 1 < len(contents) else None


def _has_content(content: tuple[str, ...]) -> bool:
    return any(line.strip() for line in content)


def _label(content: tuple[str, ...]) -> str:
    """A short name for an item in a refusal message."""
    return content[0][:60] if content else "<blank>"


def _items_alike(first: tuple[str, ...], second: tuple[str, ...], floor: float) -> bool:
    """Do two items read as versions of one another?

    True for an identical first line, for one item's text opening the other's
    (a note appended to a short bullet: ``- x`` against ``- x (updated)``), or
    for a difflib ratio on the text of at least ``floor``. The move/edit
    pairing uses a loose floor (``_MOVE_RATIO``: a wrong pair only matters when
    origin also changed the item); the handoff amend guard a strict one
    (``_AMEND_ITEM_RATIO``: short bullets written side by side, ``- n1`` and
    ``- o1``, are different items, and refusing them would escalate every
    concurrent append).
    """
    if not (_has_content(first) and _has_content(second)):
        return False
    if first[0] == second[0]:
        return True
    a, b = "\n".join(first), "\n".join(second)
    if a.startswith(b) or b.startswith(a):
        return True
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio() >= floor


_MOVE_RATIO = 0.6
_AMEND_ITEM_RATIO = 0.9


def _pair_moves(
    bc: list[tuple[str, ...]],
    tc: list[tuple[str, ...]],
    opcodes: list[tuple[str, int, int, int, int]],
) -> dict[int, int]:
    """Pair the session's deleted base items with its inserted tip items by similarity.

    ``difflib`` reads a moved item, or a moved *and edited* one, as a delete of
    the base item plus an insert of the new one, two unrelated operations whose
    guards each look harmless. A deleted base item and an inserted tip item of
    the same section that read as versions of one another
    (``_items_alike``) are one edit of that item. One-to-one, best match first.
    A moved item that lands next to an edit of its new neighbour sits inside a
    ``replace`` opcode, so the tip side of every ``replace`` is a candidate
    too, in a second round: the deleted items still unpaired after the plain
    inserts took their matches. The second round never takes a pair from the
    first, so it only adds pairs (and so only adds refusals). Works the same
    on base -> origin opcodes, pairing origin's own moves. Returns ``{base
    index: tip index}``.
    """
    deleted = [
        i
        for tag, i1, i2, _j1, _j2 in opcodes
        if tag == "delete"
        for i in range(i1, i2)
        if _has_content(bc[i])
    ]
    inserted = [
        j
        for tag, _i1, _i2, j1, j2 in opcodes
        if tag == "insert"
        for j in range(j1, j2)
        if _has_content(tc[j])
    ]
    replacing = [
        j
        for tag, _i1, _i2, j1, j2 in opcodes
        if tag == "replace"
        for j in range(j1, j2)
        if _has_content(tc[j])
    ]
    pairs = _best_pairs(bc, tc, deleted, inserted)
    pairs.update(_best_pairs(bc, tc, [i for i in deleted if i not in pairs], replacing))
    return pairs


def _best_pairs(
    bc: list[tuple[str, ...]],
    tc: list[tuple[str, ...]],
    deleted: list[int],
    inserted: list[int],
) -> dict[int, int]:
    """One-to-one ``_items_alike`` pairs, identical first, then nearest."""
    scored = sorted(
        (
            (bc[i] == tc[j], -abs(i - j), i, j)
            for i in deleted
            for j in inserted
            if _items_alike(bc[i], tc[j], _MOVE_RATIO)
        ),
        reverse=True,
    )
    pairs: dict[int, int] = {}
    taken: set[int] = set()
    for _score, _distance, i, j in scored:
        if i not in pairs and j not in taken:
            pairs[i] = j
            taken.add(j)
    return pairs


_Ref = tuple[str, int]  # (section name, item index)


def _pair_across_sections(
    sections: dict[str, tuple[list[tuple[str, ...]], list[tuple[str, ...]]]],
    sources: set[str],
) -> dict[_Ref, _Ref]:
    """Pair items deleted from one section with items inserted into ANOTHER.

    ``sections`` maps a section name to ``(base item contents, other side's
    item contents)``; only deletions from a section in ``sources`` count. A
    candidate is a deleted or inserted (``insert`` or ``replace`` tip side)
    item its own section's ``_pair_moves`` left unpaired: an in-section move
    is that section's business, and since that pairing is greedy over every
    alike pair, no two leftovers of one section are alike: every pair found
    here crosses sections. One-to-one, identical before merely alike.
    Returns ``{(section, base index): (other section, other index)}``.
    """
    deleted: dict[_Ref, tuple[str, ...]] = {}
    inserted: dict[_Ref, tuple[str, ...]] = {}
    for name, (bc, xc) in sections.items():
        ops = difflib.SequenceMatcher(None, bc, xc, autojunk=False).get_opcodes()
        own = _pair_moves(bc, xc, ops)
        claimed = set(own.values())
        for tag, i1, i2, j1, j2 in ops:
            if tag == "delete" and name in sources:
                deleted.update(
                    ((name, i), bc[i]) for i in range(i1, i2) if i not in own and _has_content(bc[i])
                )
            if tag in ("insert", "replace"):
                inserted.update(
                    ((name, j), xc[j])
                    for j in range(j1, j2)
                    if j not in claimed and _has_content(xc[j])
                )
    scored = sorted(
        (
            (deleted[gone] == inserted[new], gone, new)
            for gone in deleted
            for new in inserted
            if _items_alike(deleted[gone], inserted[new], _MOVE_RATIO)
        ),
        reverse=True,
    )
    pairs: dict[_Ref, _Ref] = {}
    taken: set[_Ref] = set()
    for _identical, gone, new in scored:
        if gone not in pairs and new not in taken:
            pairs[gone] = new
            taken.add(new)
    return pairs


def _insert_gaps(opcodes: list[tuple[str, int, int, int, int]]) -> dict[int, int]:
    """Map each inserted or replacing item's index -> the base gap it went in at."""
    return {
        j: i1
        for tag, i1, _i2, j1, j2 in opcodes
        if tag in ("insert", "replace")
        for j in range(j1, j2)
    }


def _refuse_cross_section_moves(
    base: dict[str, list[str]],
    tip: dict[str, list[str]],
    origin: dict[str, list[str]],
    origin_base: dict[str, list[str]],
    touched: list[str],
    path: str,
) -> None:
    """Refuse a move of a handoff item between sections that the other side raced.

    ``_merge_section_items`` works one section at a time, so a session that
    moves (and edits) an item into another section reads there as a harmless
    delete plus an unrelated insert -- and when origin deleted, edited or also
    moved the item, the delete looked already applied while the new copy
    resurrected it, or two versions came out. The session's cross-section
    pairs (``_pair_across_sections``) therefore need the moved base item
    unchanged and aligned on origin in its own section, unless origin made
    the identical move (the same item into the same gap). The mirror case:
    origin moved an item into another section that the session deleted -- the
    session's delete would be dropped. ``base`` and ``tip`` are the touched
    sections' bodies; ``origin`` every origin section, with ``origin_base``
    its base counterpart.
    """
    contents = {
        side: {name: [content for content, _blanks in _items(body)] for name, body in bodies.items()}
        for side, bodies in (("base", base), ("tip", tip), ("origin", origin), ("ob", origin_base))
    }
    bcs, tcs, ocs, obs = contents["base"], contents["tip"], contents["origin"], contents["ob"]
    sources = set(touched)
    session = _pair_across_sections({name: (bcs[name], tcs[name]) for name in touched}, sources)
    origin_moves = _pair_across_sections({name: (obs[name], ocs[name]) for name in ocs}, sources)

    def gaps(before: list[tuple[str, ...]], after: list[tuple[str, ...]]) -> dict[int, int]:
        return _insert_gaps(difflib.SequenceMatcher(None, before, after, autojunk=False).get_opcodes())

    for (src, i), (dest, j) in sorted(session.items()):
        if i in _align_items(bcs[src], ocs[src]):
            continue  # unchanged on origin: the two sections' merges apply the move
        theirs = origin_moves.get((src, i))
        if (
            theirs is not None
            and theirs[0] == dest
            and ocs[dest][theirs[1]] == tcs[dest][j]
            and gaps(obs[dest], ocs[dest]).get(theirs[1]) == gaps(bcs[dest], tcs[dest]).get(j)
        ):
            continue  # origin made the identical move: already applied
        raise RefusalError(
            f"{path}: the session moved and edited the item {_label(bcs[src][i])!r} from "
            f"'## {src}' into '## {dest}' (now {_label(tcs[dest][j])!r}), but it is not "
            "byte-identical and aligned on origin (edited, removed or moved there); escalating"
        )
    for (src, i), (dest, j) in sorted(origin_moves.items()):
        if (src, i) in session:
            continue  # the session moved it too, identically (checked above)
        deleted = {
            index
            for tag, i1, i2, _j1, _j2 in difflib.SequenceMatcher(
                None, bcs[src], tcs[src], autojunk=False
            ).get_opcodes()
            if tag == "delete"
            for index in range(i1, i2)
        }
        if i in deleted:
            raise RefusalError(
                f"{path}: origin moved the item {_label(bcs[src][i])!r} from '## {src}' into "
                f"'## {dest}' (now {_label(ocs[dest][j])!r}), and the session deleted it; "
                "escalating"
            )


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
      byte-identical to an item origin itself *added in the same gap* (an
      origin insert at the same base index), at most once per such origin
      item -- never because an existing item, or one origin added elsewhere,
      looks the same, which would lose a move, a deliberate repeat or the
      ``- Links: [[x]]`` bullet of a new topic.
    * *Twins.* An item the session changed (or anchors an insertion on) that
      has a byte-identical twin in the base or origin section, in a section
      origin also changed, cannot be placed with certainty: refuse.

    Placements that overlap refuse.

    Blank lines follow the session (separator semantics): the item before an
    insertion, a deletion or a replacement takes the separator the session gave
    it, the last inserted or replacement item keeps the session's separator
    while origin still follows with the item the session wrote it against, and
    an item left in place takes the session's separator when only the session
    changed it. With origin unchanged the section therefore comes out as the
    session's, byte for byte (the exactness invariant ``handoff_merge``
    asserts).
    """
    base_items = _items(base_body)
    tip_items = _items(tip_body)
    origin_items = _items(origin_body)
    bc = [content for content, _blanks in base_items]
    tc = [content for content, _blanks in tip_items]
    oc = [content for content, _blanks in origin_items]
    mapping = _align_items(bc, oc)
    origin_changed = bc != oc
    # What origin itself added, keyed by the gap (base index) it added it at: a
    # session-inserted item is "already present" only when origin put the
    # identical item in the same gap, never because one like it sits elsewhere.
    origin_added_at: dict[int, Counter[tuple[str, ...]]] = {}
    origin_ops: list[tuple[str, int, int, int, int]] = []
    origin_opcodes = difflib.SequenceMatcher(None, bc, oc, autojunk=False).get_opcodes()
    # Origin's own moves: origin's delete of an item it re-inserted elsewhere is half
    # of a move, never an "already applied" match for the session's delete.
    origin_moves = _pair_moves(bc, oc, origin_opcodes)
    for op in origin_opcodes:
        o_tag, oi1, _oi2, oj1, oj2 = op
        if o_tag in ("insert", "replace"):
            origin_added_at.setdefault(oi1, Counter()).update(
                oc[j] for j in range(oj1, oj2) if _has_content(oc[j])
            )
        if o_tag in ("replace", "delete"):
            origin_ops.append(op)

    def refuse_if_amended(j: int, added: Counter[tuple[str, ...]]) -> None:
        """Refuse a session item that is a *version* of one origin added in this gap."""
        content = tip_items[j][0]
        for other, count in added.items():
            if count > 0 and _items_alike(content, other, _AMEND_ITEM_RATIO):
                raise RefusalError(
                    f"{path}: in '## {name}', the session inserts an item similar to one origin "
                    f"inserted in the same gap ({_label(content)!r} vs origin's "
                    f"{_label(other)!r}) -- was a pushed commit amended or rebased? escalating"
                )

    def fresh(j1: int, j2: int, gap: int) -> list[int]:
        """Tip item indices in ``[j1, j2)`` origin did not itself add at ``gap``."""
        added = origin_added_at.get(gap)
        kept: list[int] = []
        for j in range(j1, j2):
            content = tip_items[j][0]
            if added is not None and _has_content(content) and added[content] > 0:
                added[content] -= 1
                continue
            kept.append(j)
        if added is not None:
            for j in kept:
                refuse_if_amended(j, added)
        return kept

    def fresh_tail(kept: list[int], gap: int) -> list[int]:
        """Drop the *end* of a replacement origin itself added right after the replaced run.

        The gap after a replaced run is where origin put an item that follows the
        item the session replaced; a session replacement that ends with that
        very item has it already. Only the end counts (origin's item sits after
        the run), so a repeat in the middle of the replacement is kept.
        """
        added = origin_added_at.get(gap)
        if added is None:
            return kept
        kept = list(kept)
        while kept:
            content = tip_items[kept[-1]][0]
            if not (_has_content(content) and added[content] > 0):
                break
            added[content] -= 1
            kept.pop()
        if kept:
            refuse_if_amended(kept[-1], added)
        return kept

    def twinned(index: int) -> bool:
        content = bc[index]
        return (
            origin_changed
            and _has_content(content)
            and (bc.count(content) > 1 or oc.count(content) > 1)
        )

    def follows_alike(tip_index: int | None, origin_index: int) -> bool:
        """Does origin follow ``origin_index - 1`` with the item the session wrote
        its separator against (``tip_index``)? Both ends count as alike."""
        tip_next = tc[tip_index] if tip_index is not None and tip_index < len(tc) else None
        origin_next = oc[origin_index] if origin_index < len(oc) else None
        return tip_next == origin_next

    placements: list[tuple[int, int, list[_Item]]] = []
    # origin item index -> blank count it ends up with. ``sep_fix`` is the
    # three-way rule for the separators of items the session left in place
    # (the session's if only the session changed it); ``blank_fix`` are the
    # separators the session's own edits force on the item before a change.
    sep_fix: dict[int, int] = {}
    blank_fix: dict[int, int] = {}
    session_ops = difflib.SequenceMatcher(None, bc, tc, autojunk=False).get_opcodes()
    moves = _pair_moves(bc, tc, session_ops)
    insert_gap = _insert_gaps(session_ops)

    # Which moved items did origin itself move the same way? Decided up front: the
    # ``fresh`` dedupe below consumes origin's added items as it walks the ops, and a
    # move's insert can come before its delete.
    origin_moved = {
        index
        for index, moved_to in moves.items()
        if (added := origin_added_at.get(insert_gap[moved_to])) is not None
        and added[tc[moved_to]] > 0
    }

    for tag, i1, i2, j1, j2 in session_ops:
        if tag == "equal":
            for offset in range(i2 - i1):
                b_at, t_at = i1 + offset, j1 + offset
                o_at = mapping.get(b_at)
                if (
                    o_at is not None
                    and tip_items[t_at][1] != base_items[b_at][1]
                    and origin_items[o_at][1] == base_items[b_at][1]
                    # The separator belongs to the pair it sits between: carry the
                    # session's only while nobody changed what follows the item.
                    and _next_content(tc, t_at) == _next_content(bc, b_at) == _next_content(oc, o_at)
                ):
                    sep_fix[o_at] = tip_items[t_at][1]
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
            kept = fresh(j1, j2, i1)
            if kept:
                # Inserted items keep the session's own blank separators. The item
                # before them takes the separator the session gave it (it is now
                # followed by the first inserted item). The last inserted item keeps
                # the session's separator when origin still follows the anchor with
                # the item the session wrote it against; otherwise (origin inserted
                # there) it takes over the blank count origin's anchor had.
                incoming = [tip_items[j] for j in kept]
                if anchor:
                    blank_fix[anchor - 1] = tip_items[max(kept[0] - 1, 0)][1]
                    if not follows_alike(kept[-1] + 1, anchor):
                        incoming[-1] = (incoming[-1][0], origin_items[anchor - 1][1])
                placements.append((anchor, anchor, incoming))
                counts["items_inserted"] += len(incoming)
            continue
        if tag == "delete":
            stale = [
                i for i in range(i1, i2) if i in moves and i not in mapping and i not in origin_moved
            ]
            if stale:
                raise RefusalError(
                    f"{path}: in '## {name}', the session moved and edited the item "
                    f"{_label(bc[stale[0]])!r} (now {_label(tc[moves[stale[0]]])!r}), but it is "
                    "not byte-identical and aligned on origin (edited or removed there); "
                    "escalating"
                )
            moved_away = [i for i in range(i1, i2) if i in origin_moves and i not in origin_moved]
            if moved_away:
                raise RefusalError(
                    f"{path}: in '## {name}', origin moved the item {_label(bc[moved_away[0]])!r} "
                    f"(now {_label(oc[origin_moves[moved_away[0]]])!r}), and the session deleted "
                    "it; escalating"
                )
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
        end = mapping[run[-1]] + 1
        kept = fresh_tail(fresh(j1, j2, i1), i2)
        replacement = [tip_items[j] for j in kept]
        alike = (not kept or kept[-1] + 1 == j2) and follows_alike(j2, end)
        if replacement and not alike:
            replacement[-1] = (replacement[-1][0], origin_items[end - 1][1])
        if i1 > 0 and j1 > 0 and start > 0:
            # The item before a deleted or replaced run takes the separator the
            # session gave it: deleting `- b` from `- a`, `- b`, <blank>, `Para`
            # must leave a blank before `Para`, not glue it to `- a`. When origin
            # follows the run with something else, the blank lines that
            # separated the run from it count too; an item origin put before the
            # run (not the one the session wrote against) never loses a blank.
            wanted = tip_items[j1 - 1][1]
            if not replacement and not alike:
                wanted = max(wanted, origin_items[end - 1][1])
            if mapping.get(i1 - 1) != start - 1:
                wanted = max(wanted, origin_items[start - 1][1])
            blank_fix[start - 1] = wanted
        placements.append((start, end, replacement))
        counts["items_replaced"] += len(run)
    placements.sort(key=lambda placement: (placement[0], placement[1]))
    for (_s1, end1, _r1), (start2, _e2, _r2) in zip(placements, placements[1:], strict=False):
        if start2 < end1:
            raise RefusalError(
                f"{path}: the session's item edits in '## {name}' overlap on origin; escalating"
            )
    merged = list(origin_items)
    for index, blanks in {**sep_fix, **blank_fix}.items():
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

    # Each origin section's base counterpart: by name, else (origin renamed it alone)
    # by position when the section count is unchanged, else none.
    o_map = {name: body for name, _raw, body in o_secs}
    o_base = {
        name: b_map.get(
            name, b_secs[index][2] if len(b_secs) == len(o_secs) and index < len(b_secs) else []
        )
        for index, (name, _raw, _body) in enumerate(o_secs)
    }
    _refuse_cross_section_moves(
        {name: b_map[name] for name in touched},
        {name: t_map[name] for name in touched},
        o_map,
        o_base,
        touched,
        path,
    )

    out_body = list(pre)
    for name, raw, body in o_secs:
        out_body.append(raw)
        if name in touched:
            merged_body = _merge_section_items(b_map[name], t_map[name], body, path, name, detail)
            if body == b_map[name] and merged_body != t_map[name]:
                raise RefusalError(
                    f"{path}: structural self-check: section '## {name}' differs from the "
                    "session's although origin did not change it; escalating"
                )
            out_body.extend(merged_body)
            detail["sections_replaced"].append(name)
        else:
            out_body.extend(body)

    fm = fm_rest[:desc_at] + [f'description: "{desc}"'] + fm_rest[desc_at:]
    merged_text = _join(["---", *fm, "---", *out_body])
    detail["unchanged"] = merged_text == origin_text
    return merged_text, detail


# ---------------------------------------------------------------------------
# structural self-check: no merged item that neither side wrote
# ---------------------------------------------------------------------------


@dataclass
class _Unit:
    """One merge unit (a handoff section or a ledger anchor block) of one text."""

    lines: list[str]
    items: list[tuple[str, ...]]  # content of every item/entry, trailing blanks dropped


def _handoff_units(text: str, path: str) -> dict[str, _Unit] | None:
    """``{section name: unit}`` for a handoff, or None when it does not parse."""
    try:
        _fm, _idx, _desc, body = _split_handoff(text, path)
        _pre, sections = _split_sections(body, path)
    except RefusalError:
        return None
    return {
        name: _Unit(
            lines=section_body,
            items=[content for content, _blanks in _items(section_body) if _has_content(content)],
        )
        for name, _raw, section_body in sections
    }


def _ledger_units(text: str, path: str) -> dict[str, _Unit] | None:
    """``{anchor path: unit}`` for a ledger; None when its anchors are ambiguous."""
    doc = _load_doc(text, path, strict=False)
    units: dict[str, _Unit] = {}
    for anchor_path, spans in doc.by_path().items():
        if len(spans) != 1:
            return None
        try:
            block = _parse_block(doc.lines, doc.flags, doc.headings, spans[0].anchor_idx, path)
        except RefusalError:
            return None
        units[" > ".join(anchor_path)] = _Unit(
            lines=doc.interior(spans[0]), items=[chunk.key for chunk in block.entries]
        )
    return units


def _glued_items(
    base: str, tip: str, origin: str, merged: str, path: str
) -> list[tuple[str, str, str]]:
    """Merged items that neither side wrote: ``[(kind, unit name, item text)]``.

    The line-multiset check cannot see two items glued into one (a blank line
    lost between a bullet and the paragraph after it keeps every line), nor
    one copy of a line both sides added standing in for two. So each unit the
    session touched (a handoff ``##`` section, a ledger anchor block) is
    re-split with the same item/entry splitter the merge uses, and every merged
    item must consume one occurrence of an item origin or the session holds,
    where an item both sides kept from the base counts once. ``kind`` is
    ``"section"`` or ``"block"``. Texts that do not parse report nothing: the
    line-level check and ``--lint`` own that.
    """
    if _is_handoff_path(path):
        loader, kind = _handoff_units, "section"
    elif _is_ledger_name(path):
        loader, kind = _ledger_units, "block"
    else:
        return []
    loaded = [loader(text, path) for text in (base, tip, origin, merged)]
    tables = [table for table in loaded if table is not None]
    if len(tables) != len(loaded):
        return []
    base_units, tip_units, origin_units, merged_units = tables
    # A handoff section both sides renamed identically is the same section.
    base_name = {name: name for name in tip_units}
    if kind == "section" and len(base_units) == len(tip_units):
        base_name = dict(zip(tip_units, base_units, strict=True))
    found: list[tuple[str, str, str]] = []
    for name, tip_unit in tip_units.items():
        base_unit = base_units.get(base_name[name])
        if base_unit is not None and base_unit.lines == tip_unit.lines:
            continue  # the session did not touch this unit
        merged_unit = merged_units.get(name)
        if merged_unit is None:
            continue
        b_count = Counter(base_unit.items if base_unit is not None else [])
        o_count = Counter(origin_units[name].items if name in origin_units else [])
        t_count = Counter(tip_unit.items)
        available = Counter(
            {
                item: o_count[item] + t_count[item] - min(b_count[item], o_count[item], t_count[item])
                for item in set(o_count) | set(t_count)
            }
        )
        for item in merged_unit.items:
            if available[item] > 0:
                available[item] -= 1
            else:
                found.append((kind, name, " / ".join(line.strip() for line in item)[:160]))
    return found


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
    glued = _glued_items(base_text, tip_text, origin_text, merged_text, path)
    if glued:
        kind, unit, shown = glued[0]
        more = f" (+{len(glued) - 1} more)" if len(glued) > 1 else ""
        raise RefusalError(
            f"{path}: structural self-check: merged {kind} {unit!r} contains an item neither "
            f"side wrote: {shown!r}{more}"
        )
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
        except GitError:
            raise
        except Exception as exc:  # noqa: BLE001 -- fail closed on any merge bug
            # The merges are pure functions of three blobs, so a bug in one is a
            # refusal for this file, not a traceback with no report: nothing has
            # moved yet, and the human gets the same escalation as any refusal.
            refusals.append(
                {
                    "path": path,
                    "reason": (
                        f"internal error while merging {path}: "
                        f"{type(exc).__name__}: {exc}; escalating"
                    ),
                }
            )
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

    ``glued`` is the item-level check (``_glued_items``) for a hub-file path:
    each item or entry of a merged unit the session touched that neither side
    wrote. It needs the four texts to parse and reports nothing otherwise.
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
        "glued": sorted(
            f"{kind} {unit}: {shown}" for kind, unit, shown in _glued_items(base, tip, origin, result, path)
        ),
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
    ok = all(
        not entry["missing"] and not entry["extra"] and not entry["glued"]
        for entry in files.values()
    )
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
            if not entry["missing"] and not entry["extra"] and not entry["glued"]:
                continue
            print(f"FAIL {path}")
            for kind in ("missing", "extra", "glued"):
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
