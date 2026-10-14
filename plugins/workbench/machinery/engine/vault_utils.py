"""Shared vault utilities used across hook scripts and tools.

Centralizes common operations to avoid DRY violations.
"""

from __future__ import annotations

import os
import re
from datetime import date
from pathlib import Path

# Wikilink patterns — shared across frontmatter_engine, task_manager, etc.
WIKILINK_RE = re.compile(r"\[\[.+?\]\]")
WIKILINK_CAPTURE_RE = re.compile(r"\[\[(.+?)\]\]")
_INLINE_CODE_RE = re.compile(r"`+[^`]*`+")


def code_spans(text: str) -> list[tuple[int, int]]:
    """Char ranges covered by Markdown code: fenced blocks and inline spans.

    Wikilinks inside these are documentation or examples, not real links, so
    resolvers skip any match that starts inside a returned range. Fenced blocks
    are delimited by lines starting with three backticks or three tildes (the
    fence lines included); inline spans are backtick runs.

    Parameters
    ----------
    text : str
        Markdown source.

    Returns
    -------
    list of tuple of int
        ``(start, end)`` character offsets, end exclusive.
    """
    spans: list[tuple[int, int]] = []
    pos = 0
    in_fence = False
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        is_fence = stripped.startswith("```") or stripped.startswith("~~~")
        if in_fence:
            spans.append((pos, pos + len(line)))
            if is_fence:
                in_fence = False
        elif is_fence:
            in_fence = True
            spans.append((pos, pos + len(line)))
        else:
            for m in _INLINE_CODE_RE.finditer(line):
                spans.append((pos + m.start(), pos + m.end()))
        pos += len(line)
    return spans

# Fallback used only when the scaffold-owned config predates ``BATCH_MODEL``
# (a vault rendered before #431 has no such attribute); see read_batch_model.
# Dated entries in the accumulating hub files, read with the vault-sync entry
# replay's grammar (skills/vault-sync/scripts/entry_replay.py: _fence_scan,
# parse_entry_start, _anchor_spans and _parse_chunks). The engine is vendored
# into the vault and runs standalone there, so it carries its own copy; the
# vault-sync suite's test_entry_grammar_parity.py holds the two to the same
# entries.
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
_BULLET_ENTRY_RE = re.compile(r"^-\s+\*\*(\d{4}-\d{2}-\d{2})\b")
_LEAD_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\b")
# ``(YYYY-MM-DD)`` or ``(YYYY-MM-DD<comma or space>qualifier)`` ending a
# Gotchas heading; the entry's date is the first one.
_TRAIL_DATE_RE = re.compile(r"\((\d{4}-\d{2}-\d{2})(?:[ ,][^()]*)?\)$")


def fence_flags(lines: list[str]) -> list[bool]:
    """Per-line "inside or delimiting a CommonMark code fence" flags.

    A fence closes only on the same character, at least as long as its
    opener, with nothing after it, so a four-backtick fence is not ended by
    an inner three-backtick line.
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
    return flags


def _valid_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def entry_start(line: str) -> tuple[str, str] | None:
    """``(kind, date)`` when ``line`` starts a dated entry, else None.

    A top-level ``- **YYYY-MM-DD`` bullet (Brag Doc), or a heading of level
    3 or deeper with a leading date (Key Decisions) or a trailing
    parenthesized one (Gotchas). Level-2 headings are anchors, never entries.
    """
    bm = _BULLET_ENTRY_RE.match(line)
    if bm and _valid_date(bm.group(1)):
        return ("bullet", bm.group(1))
    hm = _HEADING_RE.match(line)
    if hm is None or len(hm.group(1)) < 3:
        return None
    text = hm.group(2)
    lead = _LEAD_DATE_RE.match(text)
    if lead and _valid_date(lead.group(1)):
        return ("heading", lead.group(1))
    trail = _TRAIL_DATE_RE.search(text)
    if trail and _valid_date(trail.group(1)):
        return ("heading", trail.group(1))
    return None


def entry_runs(lines: list[str]) -> list[tuple[int | None, list[tuple[int, str]]]]:
    """Split a hub file into the runs of entries that each read newest-first.

    A run is one anchor block as the entry replay draws it -- an innermost
    non-entry heading of level 2 or deeper, running to the next heading no
    deeper than itself, so ``### Wins`` and ``### Growth`` are separate runs
    -- or, for lines in no anchor block, the stretch between two non-entry
    headings. Inside a run that holds any dated heading, a dated bullet is
    body text, not an entry.

    Parameters
    ----------
    lines : list of str
        The file's lines.

    Returns
    -------
    list of (int or None, list of (int, str))
        Per run, its anchor's line index (None outside any anchor block) and
        its entries as ``(line index, YYYY-MM-DD)``, both 0-based.
    """
    flags = fence_flags(lines)
    starts: dict[int, tuple[str, str]] = {}
    headings: list[tuple[int, int]] = []
    for idx, line in enumerate(lines):
        if flags[idx]:
            continue
        started = entry_start(line)
        if started is not None:
            starts[idx] = started
        m = _HEADING_RE.match(line)
        if m:
            headings.append((idx, len(m.group(1))))

    owner: list[int | None] = [None] * len(lines)
    runs: list[tuple[int | None, list[int]]] = []
    for pos, (idx, lvl) in enumerate(headings):
        if lvl < 2 or idx in starts or owner[idx] is not None:
            continue
        if pos + 1 < len(headings):
            nidx, nlvl = headings[pos + 1]
            if nlvl > lvl and nidx not in starts:
                continue  # a deeper non-entry heading follows: not innermost
        end = next((j for j, jlvl in headings if j > idx and jlvl <= lvl), len(lines))
        for j in range(idx + 1, end):
            owner[j] = len(runs)
        runs.append((idx, []))

    heading_lines = {idx for idx, _lvl in headings}
    current: int | None = None
    for idx in range(len(lines)):
        if owner[idx] is not None:
            current = None
            continue
        if current is None or (idx in heading_lines and idx not in starts):
            current = len(runs)
            runs.append((None, []))
        owner[idx] = current

    for idx in sorted(starts):
        runs[owner[idx]][1].append(idx)  # type: ignore[index]

    out: list[tuple[int | None, list[tuple[int, str]]]] = []
    for anchor, indices in runs:
        if any(starts[idx][0] == "heading" for idx in indices):
            indices = [idx for idx in indices if starts[idx][0] == "heading"]
        out.append((anchor, [(idx, starts[idx][1]) for idx in indices]))
    return out


DEFAULT_BATCH_MODEL = "claude-haiku-4-5"


def iso_week_string(d: date) -> str:
    """Format a date as an ISO week string (``YYYY-W##``).

    Uses ISO calendar semantics, so the year/week can straddle the Gregorian
    year boundary (e.g. 2025-12-29 → ``2026-W01``). The week is zero-padded to
    two digits. Shared by ``task_manager`` and ``work_task_manager``.
    """
    iso_year, iso_week, _ = d.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def find_vault_root(start: Path | None = None) -> Path | None:
    """Find the vault root by walking up from *start*.

    The vault is identified by ``.vault/vault.json`` — the same marker
    ``run-vault-hook.sh`` walks up for, so the bash guard and the Python engine
    agree on what counts as a vault.

    It used to be identified by ``CLAUDE.md`` alongside a ``brain/`` + ``perf/``
    signature. That check existed for a real reason and the reason still holds:
    many project repos carry their own ``CLAUDE.md``, and matching on that alone
    once let the session-stop auto-commit run inside whatever repo the shell had
    ``cd``'d into. But the signature hardcoded one vault's taxonomy into the tool
    whose whole premise is that the taxonomy is the owner's to choose, and it
    keyed on directories a freshly scaffolded vault does not have — init creates
    no note directories, so EVERY new vault reported "not in a vault directory"
    on its first session, whatever taxonomy its owner picked (#687).

    ``vault.json`` does the original job strictly better: no ordinary project
    repo has one, and it does not care what the note directories are called.

    Args:
        start: Starting directory. Defaults to cwd.

    Returns:
        Path to vault root, or None if not found.
    """
    if start is None:
        start = Path.cwd()
    for path in [start, *start.parents]:
        if (path / ".vault" / "vault.json").is_file():
            return path
    return None


def find_vault_root_from_env() -> Path | None:
    """Resolve the vault root from ``CLAUDE_PROJECT_DIR``, falling back to cwd.

    Centralizes the env+fallback idiom shared by the Stop/PreCompact hooks and
    the graph gardener: anchor to the project Claude Code launched in (the
    vault) when that env var is set, otherwise walk up from the current working
    directory. The ``find_vault_root`` signature check still applies, so a
    non-vault ``CLAUDE_PROJECT_DIR`` resolves to ``None``.

    Returns:
        Path to vault root, or None if not found.
    """
    proj = os.environ.get("CLAUDE_PROJECT_DIR")
    return find_vault_root(Path(proj)) if proj else find_vault_root()


def _linked_worktree_main_root(path: Path) -> Path | None:
    """Main worktree root when *path* is a linked worktree, else ``None``.

    A linked worktree's ``.git`` is a FILE holding ``gitdir: <dir>``, and that
    directory holds a ``commondir`` file pointing back at the main checkout's
    ``.git`` — whose parent is the main worktree root. Both indirections are
    resolved on the filesystem rather than by shelling out to ``git rev-parse
    --git-common-dir``: this runs inside ``session-start.py``, on the hot path of
    every single session, and two small reads beat a subprocess spawn. The same
    ``gitdir:`` parse already backs ``sync_manager._git_dir``.

    A submodule's ``.git`` is also a file, so the ``commondir`` step is what
    tells the two apart: a submodule's gitdir (``<super>/.git/modules/<name>``)
    has no such file, and this returns ``None`` rather than resolving to the
    superproject. The ``.git`` name check likewise rejects a worktree of a bare
    repository, where the common dir is the repo itself and has no work tree.

    Args:
        path: Directory to classify.

    Returns:
        Path to the main worktree root, or None when *path* is not a linked
        worktree (a normal checkout, a submodule, or not a repo at all).
    """
    dot_git = path / ".git"
    if not dot_git.is_file():
        return None
    try:
        text = dot_git.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text.startswith("gitdir:"):
        return None
    gitdir = Path(text.split(":", 1)[1].strip())
    if not gitdir.is_absolute():
        gitdir = path / gitdir
    try:
        common_text = (gitdir / "commondir").read_text(encoding="utf-8").strip()
    except OSError:
        return None  # no commondir → a submodule, not a linked worktree
    common = Path(common_text)
    if not common.is_absolute():
        common = gitdir / common
    try:
        common = common.resolve()
    except OSError:
        return None
    if common.name != ".git":
        return None  # bare repo: no main work tree to inherit from
    return common.parent


def _read_context_marker(ctx_file: Path) -> str | None:
    """Normalized ``.vault-context`` text, or ``None`` when the file is unreadable."""
    try:
        return ctx_file.read_text(encoding="utf-8").strip().lower()
    except OSError:
        return None


def read_vault_context(vault_root: Path, default: str = "unknown") -> str:
    """Read ``.vault-context`` (``work``|``personal``) from the vault root.

    Returns the lowercased value when it is exactly ``"work"`` or ``"personal"``;
    otherwise (file missing, empty, or any other value) returns *default*.

    The canonical single reader (#50): every hook/script that needs the machine
    context — session-start, graph_gardener, notebook-distill, context_loader,
    pulse, wrap_up_audit — reads through here, so the missing-file fallback is
    reconciled in ONE place. The default is ``"unknown"`` (a missing marker
    genuinely means the machine is unidentified). Callers that build
    per-context filenames stay mutually consistent precisely because they share
    this one default.

    When the marker is absent and *vault_root* is a LINKED WORKTREE, the main
    worktree's marker is read instead. This is not a convenience: the marker is
    gitignored and untracked, so it exists only in the main checkout, while
    Claude Code desktop sessions run inside ``<vault>/.claude/worktrees/<name>/``.
    Answering ``"unknown"`` there failed quietly in both directions — session
    start looked up a ``handoff-unknown.md`` that cannot exist and injected no
    handoff at all while logging that it had; the distiller and gardener wrote
    orphan ``notebook-unknown-*.md`` / ``gardener-unknown.md`` files no reader
    ever picks back up; and ``/wrap-up`` fails closed on ``"unknown"``, so it
    could never reach CLEAN from a worktree.

    A marker PRESENT in the worktree always wins, including when its value is
    invalid — present-but-invalid answers *default* rather than inheriting, so a
    typo resolves to nothing instead of silently to the other context. Only a
    missing or unreadable marker consults the main checkout. This function never
    writes the marker anywhere.
    """
    val = _read_context_marker(vault_root / ".vault-context")
    if val is None:
        main_root = _linked_worktree_main_root(vault_root)
        if main_root is not None:
            val = _read_context_marker(main_root / ".vault-context")
    if val is None:
        return default
    return val if val in ("work", "personal") else default


def read_batch_model(default: str = DEFAULT_BATCH_MODEL) -> str:
    """Read ``BATCH_MODEL`` from the scaffold-owned ``vault_scope`` config.

    The canonical single reader for the headless batch model: notebook-distill
    and graph_gardener Lane B both resolve their ``claude -p --model`` argument
    here, so a deprecation or tiering change is a scaffold edit rather than an
    engine release. ``vault_scope.py`` is scaffold-tier — init renders it once
    and upgrade never touches it — which is why the id lives there and not in
    the managed engine payload.

    A vault whose ``vault_scope.py`` was rendered before the value existed (or
    a context where the module is not importable) falls back to *default*, so
    an absent config preserves the previous behaviour exactly.
    """
    try:
        import vault_scope_resolved
    except ImportError:
        return default

    value = getattr(vault_scope_resolved, "BATCH_MODEL", None)
    return value if isinstance(value, str) and value else default
