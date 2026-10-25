"""Quarterly ledger rollover -- move old Key Decisions and Brag Doc text into archives.

``brain/Key Decisions.md`` and ``perf/Brag Doc.md`` grow without bound. Once per
calendar quarter, this module moves everything dated before the first day of the
current quarter out of the live file and into a quarterly archive file, verbatim:

- Key Decisions: ``### YYYY-MM-DD`` entries under ``## Recent`` move to
  ``brain/archive/key-decisions/YYYY-QN.md``, newest first.
- Brag Doc: whole ``## QN YYYY`` sections other than the current (or a later)
  quarter move to ``perf/archive/brag-YYYY-QN.md``.

Entry boundaries follow ``vault_utils.entry_runs`` / ``entry_start``, so an entry
inside a code fence is never moved. Nothing is rewritten: the moved text is the
same bytes it was. The live file keeps its headings and gains one ``## Archive``
list linking every archive file; each archive file links back to the live one, so
neither side is an orphan.

The core, ``plan_rollover``, is a pure function over file text with an injectable
``today``. ``rollover_ledgers`` is the thin filesystem wrapper (dry by default),
and ``main`` is the CLI::

    python ledger_rollover.py rollover [--vault-root PATH] [--apply]

Public API:
    quarter_start(day) -> date
    quarter_label(day) -> str
    archive_path_key_decisions(label) -> str
    archive_path_brag(label) -> str
    plan_rollover(files, today) -> Rollover
    rollover_ledgers(vault_root, today?, apply?) -> dict
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Mapping

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from vault_utils import _HEADING_RE, entry_runs, fence_flags, find_vault_root  # noqa: E402

KEY_DECISIONS = "brain/Key Decisions.md"
BRAG_DOC = "perf/Brag Doc.md"
KD_ARCHIVE_DIR = "brain/archive/key-decisions/"
BRAG_ARCHIVE_DIR = "perf/archive/"
BRAG_ARCHIVE_PREFIX = "perf/archive/brag-"

_RECENT_RE = re.compile(r"^##\s+Recent\s*$")
_ARCHIVE_RE = re.compile(r"^##\s+Archive\s*$")
_QUARTER_H2_RE = re.compile(r"^##\s+Q([1-4])\s+(\d{4})\s*$")
_KD_ARCHIVE_RE = re.compile(r"^brain/archive/key-decisions/(\d{4})-Q([1-4])\.md$")
_BRAG_ARCHIVE_RE = re.compile(r"^perf/archive/brag-(\d{4})-Q([1-4])\.md$")


# ---------------------------------------------------------------------------
# Quarter arithmetic and paths
# ---------------------------------------------------------------------------


def quarter_start(day: date) -> date:
    """First day of the calendar quarter holding ``day`` (Q1 = Jan to Mar)."""
    return date(day.year, 3 * ((day.month - 1) // 3) + 1, 1)


def quarter_label(day: date) -> str:
    """``YYYY-QN`` for the calendar quarter holding ``day``."""
    return f"{day.year}-Q{(day.month - 1) // 3 + 1}"


def archive_path_key_decisions(label: str) -> str:
    """Vault-relative Key Decisions archive path for a ``YYYY-QN`` label."""
    return f"{KD_ARCHIVE_DIR}{label}.md"


def archive_path_brag(label: str) -> str:
    """Vault-relative Brag Doc archive path for a ``YYYY-QN`` label."""
    return f"{BRAG_ARCHIVE_PREFIX}{label}.md"


def _wikilink_target(path: str) -> str:
    return path[: -len(".md")]


# ---------------------------------------------------------------------------
# Text helpers (byte-preserving: line endings are never normalised)
# ---------------------------------------------------------------------------


def split_keepends(text: str) -> list[str]:
    """Split on ``\\n`` only, keeping each terminator, so joining returns the text."""
    return re.findall(r"[^\n]*\n|[^\n]+", text)


def _plain(lines: list[str]) -> list[str]:
    return [line.rstrip("\r\n") for line in lines]


def _newline_of(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _ensure_terminated(chunk: str, newline: str) -> str:
    return chunk if chunk.endswith("\n") or not chunk else chunk + newline


def _heading_level(line: str) -> int | None:
    m = _HEADING_RE.match(line)
    return len(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------


@dataclass
class Rollover:
    """What a rollover would change.

    Attributes
    ----------
    files : dict of str to str
        Vault-relative path to its new full text; only files that change.
    moved : dict of str to int
        Archive path to the number of entries (Key Decisions) or sections
        (Brag Doc) moved into it this run.
    skipped : list of str
        Archive paths whose section was left in the live file because the
        archive already holds a different section for that quarter.
    """

    files: dict[str, str] = field(default_factory=dict)
    moved: dict[str, int] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)


def _frontmatter(today: date, description: str, tag: str) -> str:
    return (
        "---\n"
        f"date: {today.isoformat()}\n"
        f'description: "{description}"\n'
        "tags:\n"
        f"  - {tag}\n"
        "---\n"
    )


def _archive_section(live_lines: list[str], links: list[str], newline: str, insert_at: int | None) -> list[str]:
    """Return ``live_lines`` with the ``## Archive`` list rebuilt from ``links``.

    An existing ``## Archive`` section has its body replaced; otherwise the
    section is inserted at ``insert_at`` (or appended when None).
    """
    plain = _plain(live_lines)
    flags = fence_flags(plain)
    block = [f"## Archive{newline}", newline]
    block += [f"- [[{_wikilink_target(p)}]]{newline}" for p in links]
    block.append(newline)
    for idx, line in enumerate(plain):
        if not flags[idx] and _ARCHIVE_RE.match(line):
            end = next(
                (j for j in range(idx + 1, len(plain)) if not flags[j] and _heading_level(plain[j]) in (1, 2)),
                len(plain),
            )
            return live_lines[:idx] + block + live_lines[end:]
    if insert_at is None:
        tail = live_lines[-1:] if live_lines else []
        sep = [] if not tail or tail[0].strip() == "" else [newline]
        return live_lines + sep + block
    return live_lines[:insert_at] + block + live_lines[insert_at:]


def _archive_links(known: Mapping[str, str], created: list[str], pattern: re.Pattern[str]) -> list[str]:
    paths = {p for p in known if pattern.match(p)} | set(created)
    return sorted(paths, key=lambda p: (pattern.match(p).group(1), pattern.match(p).group(2)), reverse=True)  # type: ignore[union-attr]


# --- Key Decisions ---------------------------------------------------------


def _kd_chunks(lines: list[str]) -> list[tuple[int, int, date]]:
    """``(start, end, day)`` per entry under ``## Recent`` (line indices, end exclusive)."""
    plain = _plain(lines)
    flags = fence_flags(plain)
    out: list[tuple[int, int, date]] = []
    for anchor, entries in entry_runs(plain):
        if anchor is None or not _RECENT_RE.match(plain[anchor]):
            continue
        level = _heading_level(plain[anchor]) or 2
        run_end = next(
            (j for j in range(anchor + 1, len(plain)) if not flags[j] and (_heading_level(plain[j]) or 99) <= level),
            len(plain),
        )
        for k, (start, day) in enumerate(entries):
            end = entries[k + 1][0] if k + 1 < len(entries) else run_end
            out.append((start, end, date.fromisoformat(day)))
    return out


def _split_archive(text: str) -> tuple[list[str], list[tuple[date, str]]]:
    """An existing archive file as ``(preamble lines, [(day, chunk text), ...])``."""
    lines = split_keepends(text)
    plain = _plain(lines)
    starts: list[tuple[int, date]] = []
    for _anchor, entries in entry_runs(plain):
        starts.extend((i, date.fromisoformat(d)) for i, d in entries)
    starts.sort()
    if not starts:
        return lines, []
    chunks = []
    for k, (idx, day) in enumerate(starts):
        end = starts[k + 1][0] if k + 1 < len(starts) else len(lines)
        chunks.append((day, "".join(lines[idx:end])))
    return lines[: starts[0][0]], chunks


def _kd_archive_text(
    label: str, today: date, existing: str | None, new: list[tuple[date, str]], newline: str
) -> str:
    if existing is None:
        year, q = label.split("-")
        preamble = (
            _frontmatter(
                today,
                f"Key Decisions entries dated {year} {q}, archived verbatim from Key Decisions by the quarterly rollover.",
                "key-decisions-archive",
            )
            + f"# Key Decisions {year} {q} (archive){newline}{newline}"
            + f"Archived verbatim from [[Key Decisions]] by the quarterly rollover. Newest first.{newline}{newline}"
        )
        pre_lines: list[str] = split_keepends(preamble)
        chunks: list[tuple[date, str]] = []
    else:
        pre_lines, chunks = _split_archive(existing)
    for day, text in new:
        if any(text == have for _d, have in chunks):
            continue  # already archived (a half-finished earlier run)
        at = next((i for i, (d, _t) in enumerate(chunks) if d < day), len(chunks))
        chunks.insert(at, (day, text))
    out: list[str] = list(pre_lines)
    for k, (_d, text) in enumerate(chunks):
        out.append(text if k == len(chunks) - 1 else _ensure_terminated(text, newline))
    return "".join(out)


def _roll_key_decisions(
    files: Mapping[str, str], today: date, cutoff: date, plan: Rollover
) -> None:
    text = files.get(KEY_DECISIONS)
    if text is None:
        return
    lines = split_keepends(text)
    newline = _newline_of(text)
    moving = [(s, e, d) for s, e, d in _kd_chunks(lines) if d < cutoff]
    if not moving:
        return
    by_label: dict[str, list[tuple[date, str]]] = {}
    for s, e, d in moving:
        by_label.setdefault(quarter_label(d), []).append((d, "".join(lines[s:e])))
    created: list[str] = []
    for label, new in by_label.items():
        path = archive_path_key_decisions(label)
        plan.files[path] = _kd_archive_text(label, today, files.get(path), new, newline)
        plan.moved[path] = len(new)
        created.append(path)
    drop = {i for s, e, _d in moving for i in range(s, e)}
    kept = [line for i, line in enumerate(lines) if i not in drop]
    plain = _plain(kept)
    flags = fence_flags(plain)
    recent = next((i for i, l in enumerate(plain) if not flags[i] and _RECENT_RE.match(l)), None)
    links = _archive_links(files, created, _KD_ARCHIVE_RE)
    plan.files[KEY_DECISIONS] = "".join(_archive_section(kept, links, newline, recent))


# --- Brag Doc --------------------------------------------------------------


def _brag_sections(lines: list[str]) -> list[tuple[int, int, int, int]]:
    """``(start, end, year, quarter)`` per ``## QN YYYY`` section (end exclusive)."""
    plain = _plain(lines)
    flags = fence_flags(plain)
    h1h2 = [i for i, l in enumerate(plain) if not flags[i] and _heading_level(l) in (1, 2)]
    out = []
    for idx in h1h2:
        m = _QUARTER_H2_RE.match(plain[idx])
        if not m:
            continue
        end = next((j for j in h1h2 if j > idx), len(plain))
        out.append((idx, end, int(m.group(2)), int(m.group(1))))
    return out


def _brag_archive_text(label: str, today: date, section: str, newline: str) -> str:
    year, q = label.split("-")
    preamble = (
        _frontmatter(
            today,
            f"Brag Doc wins, impact and growth for {year} {q}, archived verbatim from the Brag Doc by the quarterly rollover.",
            "brag-doc-archive",
        )
        + f"# Brag Doc {year} {q} (archive){newline}{newline}"
        + f"Archived verbatim from [[Brag Doc]] by the quarterly rollover.{newline}{newline}"
    )
    return preamble + section


def _roll_brag(files: Mapping[str, str], today: date, cutoff: date, plan: Rollover) -> None:
    text = files.get(BRAG_DOC)
    if text is None:
        return
    lines = split_keepends(text)
    newline = _newline_of(text)
    cut = (cutoff.year, (cutoff.month - 1) // 3 + 1)
    moving = [(s, e, y, q) for s, e, y, q in _brag_sections(lines) if (y, q) < cut]
    created: list[str] = []
    drop: set[int] = set()
    for s, e, y, q in moving:
        label = f"{y}-Q{q}"
        path = archive_path_brag(label)
        section = "".join(lines[s:e])
        have = files.get(path)
        if have is not None:
            if section in have:
                drop.update(range(s, e))  # already archived byte-for-byte
            else:
                plan.skipped.append(path)
            continue
        plan.files[path] = _brag_archive_text(label, today, section, newline)
        plan.moved[path] = 1
        created.append(path)
        drop.update(range(s, e))
    if not drop:
        return
    kept = [line for i, line in enumerate(lines) if i not in drop]
    sections_left = _brag_sections(kept)
    insert_at = sections_left[0][0] if sections_left else None
    links = _archive_links(files, created, _BRAG_ARCHIVE_RE)
    plan.files[BRAG_DOC] = "".join(_archive_section(kept, links, newline, insert_at))


def plan_rollover(files: Mapping[str, str], today: date) -> Rollover:
    """Plan the quarterly rollover over file text, with no filesystem access.

    Parameters
    ----------
    files : mapping of str to str
        Vault-relative path to file text: the live ``brain/Key Decisions.md`` and
        ``perf/Brag Doc.md`` (either may be absent) plus any existing archive
        files under ``brain/archive/key-decisions/`` and ``perf/archive/``.
    today : date
        The reference date; entries before the first day of its calendar quarter
        move.

    Returns
    -------
    Rollover
        The changed files only. When nothing is old enough to move, it is empty,
        so a second run in the same quarter is a no-op.
    """
    cutoff = quarter_start(today)
    plan = Rollover()
    _roll_key_decisions(files, today, cutoff, plan)
    _roll_brag(files, today, cutoff, plan)
    return plan


# ---------------------------------------------------------------------------
# Filesystem wrapper and CLI
# ---------------------------------------------------------------------------


def _read(path: Path) -> str:
    with path.open(encoding="utf-8", newline="") as stream:
        return stream.read()


def _gather(vault_root: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for rel in (KEY_DECISIONS, BRAG_DOC):
        path = vault_root / rel
        if path.is_file():
            files[rel] = _read(path)
    for directory, pattern in ((KD_ARCHIVE_DIR, _KD_ARCHIVE_RE), (BRAG_ARCHIVE_DIR, _BRAG_ARCHIVE_RE)):
        base = vault_root / directory
        if not base.is_dir():
            continue
        for path in sorted(base.glob("*.md")):
            rel = f"{directory}{path.name}"
            if pattern.match(rel):
                files[rel] = _read(path)
    return files


def rollover_ledgers(vault_root: Path, today: date | None = None, apply: bool = False) -> dict:
    """Run the quarterly rollover against a vault root; dry unless ``apply``.

    Archive files are written before the live files, so an interrupted run
    never has an entry that exists nowhere; a re-run finishes it (an entry
    already in its archive is dropped from the live file, not duplicated).

    Returns
    -------
    dict
        ``applied`` (bool), ``moved`` (archive path to count), ``skipped``
        (archive paths left alone), ``written`` (paths written; empty when dry).
    """
    today = today or date.today()
    vault_root = Path(vault_root)
    plan = plan_rollover(_gather(vault_root), today)
    written: list[str] = []
    if apply:
        ordered = [p for p in plan.files if p not in (KEY_DECISIONS, BRAG_DOC)] + [
            p for p in (KEY_DECISIONS, BRAG_DOC) if p in plan.files
        ]
        for rel in ordered:
            target = vault_root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("w", encoding="utf-8", newline="") as stream:
                stream.write(plan.files[rel])
            written.append(rel)
    return {
        "applied": apply,
        "moved": dict(plan.moved),
        "skipped": list(plan.skipped),
        "written": written,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Quarterly ledger rollover (Key Decisions, Brag Doc)")
    commands = parser.add_subparsers(dest="command", required=True)
    roll = commands.add_parser("rollover", help="move pre-quarter entries into archive files (dry by default)")
    roll.add_argument("--vault-root", type=Path, default=None, help="vault root (default: discovered from cwd)")
    roll.add_argument("--apply", action="store_true", help="write the changes (default is a dry run)")
    roll.add_argument("--today", type=date.fromisoformat, default=None, help="reference date, YYYY-MM-DD (tests)")
    args = parser.parse_args(argv)

    root = args.vault_root or find_vault_root()
    if root is None:
        print("ledger_rollover: no vault root found; pass --vault-root", file=sys.stderr)
        return 2
    if not Path(root).is_dir():
        print(f"ledger_rollover: vault root {root} is not a directory", file=sys.stderr)
        return 2
    result = rollover_ledgers(root, today=args.today, apply=args.apply)
    print(f"ledger rollover ({'applied' if result['applied'] else 'dry run'}) in {root}")
    if not result["moved"] and not result["skipped"]:
        print("nothing to move")
    for path, count in sorted(result["moved"].items()):
        print(f"{path}: {count}")
    for path in result["skipped"]:
        print(f"skipped (archive already holds a different section): {path}")
    if not result["applied"] and result["moved"]:
        print("re-run with --apply to write")
    return 0


if __name__ == "__main__":
    sys.exit(main())
