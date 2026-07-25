#!/usr/bin/env python3
"""Vault Query — cross-platform note querying by frontmatter fields.

Replaces Obsidian Bases functionality on Windows (VS Code).
Can be run standalone or imported by other scripts.

Usage:
    python vault_query.py active-work
    python vault_query.py decisions
    python vault_query.py people
    python vault_query.py competencies
    python vault_query.py brag
    python vault_query.py learning
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add parent scripts dir to path for shared imports
SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

from frontmatter_engine import _parse_frontmatter as _parse_fm_full
from vault_utils import find_vault_root


def _parse_frontmatter(path: Path) -> dict | None:
    """Parse YAML frontmatter from a markdown file."""
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    fm, _, error = _parse_fm_full(content)
    return fm


def _scan_notes(vault: Path, dirs: list[str]) -> list[tuple[Path, dict]]:
    """Scan directories for notes with valid frontmatter."""
    results = []
    seen: set[Path] = set()
    for d in dirs:
        dir_path = vault / d
        if not dir_path.exists():
            continue
        for md in dir_path.rglob("*.md"):
            if md in seen:
                continue
            seen.add(md)
            fm = _parse_frontmatter(md)
            if fm:
                results.append((md, fm))
    return results


def _has_tag(fm: dict, tag: str) -> bool:
    """Check if frontmatter has a specific tag."""
    tags = fm.get("tags", [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",")]
    return tag in tags


def _format_table(headers: list[str], rows: list[list[str]]) -> str:
    """Format data as a markdown table."""
    if not rows:
        return "(no results)\n"

    def _escape(value: object) -> str:
        # Escape pipes so a cell value containing `|` doesn't break the table.
        return str(value).replace("|", "\\|")

    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(widths):
                widths[i] = max(widths[i], len(_escape(cell)))

    header_line = "| " + " | ".join(h.ljust(widths[i]) for i, h in enumerate(headers)) + " |"
    sep_line = "| " + " | ".join("-" * widths[i] for i in range(len(headers))) + " |"
    data_lines = []
    for row in rows:
        cells = []
        for i, cell in enumerate(row):
            escaped = _escape(cell)
            w = widths[i] if i < len(widths) else len(escaped)
            cells.append(escaped.ljust(w))
        data_lines.append("| " + " | ".join(cells) + " |")

    return "\n".join([header_line, sep_line, *data_lines]) + "\n"


# ---------------------------------------------------------------------------
# Query functions
# ---------------------------------------------------------------------------

def query_active_work(vault: Path) -> str:
    """List all active work notes."""
    notes = _scan_notes(vault, ["work/active", "work/incidents"])
    rows = []
    for path, fm in sorted(notes, key=lambda x: x[1].get("date", ""), reverse=True):
        rows.append([
            path.stem,
            str(fm.get("status", "")),
            str(fm.get("project", "")),
            str(fm.get("date", "")),
        ])
    return _format_table(["Note", "Status", "Project", "Date"], rows)


def query_decisions(vault: Path) -> str:
    """List all decision records."""
    notes = _scan_notes(vault, ["work/active", "work/archive", "brain"])
    rows = []
    for path, fm in notes:
        if _has_tag(fm, "decision"):
            rows.append([
                path.stem,
                str(fm.get("status", "")),
                str(fm.get("date", "")),
                str(fm.get("description", ""))[:60],
            ])
    rows.sort(key=lambda r: r[2], reverse=True)
    return _format_table(["Decision", "Status", "Date", "Description"], rows)


def query_people(vault: Path) -> str:
    """List all person profiles."""
    notes = _scan_notes(vault, ["org/people"])
    rows = []
    for path, fm in sorted(notes, key=lambda x: x[0].stem):
        rows.append([
            path.stem,
            str(fm.get("role", "")),
            str(fm.get("team", "")),
        ])
    return _format_table(["Name", "Role", "Team"], rows)


def query_competencies(vault: Path) -> str:
    """List all competency notes with levels."""
    notes = _scan_notes(vault, ["perf/competencies"])
    rows = []
    for path, fm in sorted(notes, key=lambda x: x[0].stem):
        rows.append([
            path.stem,
            str(fm.get("current_level", "")),
            str(fm.get("target_level", "")),
        ])
    return _format_table(["Competency", "Current", "Target"], rows)


def query_brag(vault: Path) -> str:
    """List all brag/evidence notes."""
    notes = _scan_notes(vault, ["perf/evidence", "perf"])
    rows = []
    for path, fm in notes:
        if _has_tag(fm, "brag-doc") or _has_tag(fm, "evidence"):
            rows.append([
                path.stem,
                str(fm.get("date", "")),
                str(fm.get("description", ""))[:60],
            ])
    rows.sort(key=lambda r: r[1], reverse=True)
    return _format_table(["Entry", "Date", "Description"], rows)


def query_learning(vault: Path) -> str:
    """List all learning notes."""
    notes = _scan_notes(vault, ["personal/learning"])
    rows = []
    for path, fm in sorted(notes, key=lambda x: x[1].get("date", ""), reverse=True):
        rows.append([
            path.stem,
            str(fm.get("status", "")),
            str(fm.get("source", "")),
            str(fm.get("date", "")),
        ])
    return _format_table(["Topic", "Status", "Source", "Date"], rows)


QUERIES = {
    "active-work": ("Active Work Notes", query_active_work),
    "decisions": ("Decision Records", query_decisions),
    "people": ("People Directory", query_people),
    "competencies": ("Competency Map", query_competencies),
    "brag": ("Brag Doc Entries", query_brag),
    "learning": ("Learning Notes", query_learning),
}


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in QUERIES:
        print("Usage: python vault_query.py <query>")
        print(f"Available queries: {', '.join(QUERIES)}")
        return 1

    query_name = sys.argv[1]
    title, query_fn = QUERIES[query_name]
    vault = find_vault_root()
    if vault is None:
        print("Error: not in a vault directory (no CLAUDE.md found)")
        return 1

    print(f"## {title}\n")
    print(query_fn(vault))
    return 0


if __name__ == "__main__":
    sys.exit(main())
