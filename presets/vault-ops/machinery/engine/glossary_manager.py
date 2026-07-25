"""Glossary Manager — CRUD for brain/Glossary.md and brain/Quick-Reference.md.

Public interface:
    ensure_glossary(vault_root) -> Path
    ensure_quick_reference(vault_root) -> Path
    parse_glossary(file_path) -> list[GlossaryEntry]
    add_glossary_entry(vault_root, term, meaning, category) -> None
    remove_glossary_entry(vault_root, term) -> bool
    lookup_term(vault_root, term) -> GlossaryEntry | None
    parse_quick_reference(file_path) -> list[QuickRefEntry]
    add_quick_ref_entry(vault_root, section, name, col2, col3) -> None
    remove_quick_ref_entry(vault_root, section, name) -> bool
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from frontmatter_engine import generate


TABLE_ROW_RE = re.compile(r"^\|\s*\*\*(?P<key>[^*]+)\*\*\s*\|(?P<rest>.+)\|$")


@dataclass
class GlossaryEntry:
    term: str
    meaning: str
    category: str


@dataclass
class QuickRefEntry:
    section: str  # People, Terms, or Projects
    name: str
    col2: str  # Role/Meaning/Full Name
    col3: str  # Context/blank/Status


def ensure_glossary(vault_root: Path) -> Path:
    """Create brain/Glossary.md with frontmatter if it does not exist."""
    brain = vault_root / "brain"
    brain.mkdir(parents=True, exist_ok=True)
    path = brain / "Glossary.md"
    if path.exists():
        return path

    frontmatter = generate("reference", {
        "date": date.today().isoformat(),
        "description": "Complete decoder ring for workplace shorthand",
        "tags": ["reference", "glossary"],
    })
    content = (
        f"{frontmatter}\n# Glossary\n\n"
        "| Term | Meaning | Category |\n"
        "|------|---------|----------|\n"
    )
    path.write_text(content, encoding="utf-8")
    return path


def ensure_quick_reference(vault_root: Path) -> Path:
    """Create brain/Quick-Reference.md with frontmatter if it does not exist."""
    brain = vault_root / "brain"
    brain.mkdir(parents=True, exist_ok=True)
    path = brain / "Quick-Reference.md"
    if path.exists():
        return path

    frontmatter = generate("reference", {
        "date": date.today().isoformat(),
        "description": "Hot cache of frequently referenced people, terms, and projects",
        "tags": ["reference", "memory"],
    })
    content = (
        f"{frontmatter}\n# Quick Reference\n\n"
        "## People\n\n"
        "| Name | Role | Context |\n"
        "|------|------|--------|\n\n"
        "## Terms\n\n"
        "| Term | Meaning |\n"
        "|------|---------|\n\n"
        "## Projects\n\n"
        "| Alias | Full Name | Status |\n"
        "|-------|-----------|--------|\n"
    )
    path.write_text(content, encoding="utf-8")
    return path


def parse_glossary(file_path: Path) -> list[GlossaryEntry]:
    """Parse the Glossary.md table into a list of GlossaryEntry."""
    if not file_path.exists():
        return []

    content = file_path.read_text(encoding="utf-8")
    entries: list[GlossaryEntry] = []

    for line in content.splitlines():
        match = TABLE_ROW_RE.match(line.strip())
        if not match:
            continue
        term = match.group("key").strip()
        rest_cols = [c.strip() for c in match.group("rest").split("|")]
        meaning = rest_cols[0] if len(rest_cols) > 0 else ""
        category = rest_cols[1] if len(rest_cols) > 1 else ""
        entries.append(GlossaryEntry(term=term, meaning=meaning, category=category))

    return entries


def add_glossary_entry(vault_root: Path, term: str, meaning: str, category: str) -> None:
    """Add a term to the glossary. Skips if term already exists (case-insensitive)."""
    path = ensure_glossary(vault_root)
    existing = parse_glossary(path)
    if any(e.term.lower() == term.lower() for e in existing):
        return

    content = path.read_text(encoding="utf-8")
    row = f"| **{term}** | {meaning} | {category} |"
    lines = content.splitlines()

    # Locate the glossary table and insert at the end of its contiguous block of
    # `|`-prefixed lines, rather than at the end of the file. Appending blindly
    # corrupts the table if any trailing content follows it.
    header = "| Term | Meaning | Category |"
    insert_idx = len(lines)
    in_table = False

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == header:
            in_table = True
            insert_idx = i + 1  # default: right after the header
            continue
        if in_table:
            if stripped.startswith("|"):
                # Table row or separator — insert after it
                insert_idx = i + 1
            else:
                # First non-table line ends the block
                break

    lines.insert(insert_idx, row)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def remove_glossary_entry(vault_root: Path, term: str) -> bool:
    """Remove a term from the glossary by case-insensitive match. Returns True if found."""
    path = vault_root / "brain" / "Glossary.md"
    if not path.exists():
        return False

    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()
    new_lines = []
    found = False

    for line in lines:
        match = TABLE_ROW_RE.match(line.strip())
        if match and match.group("key").strip().lower() == term.lower():
            found = True
            continue
        new_lines.append(line)

    if found:
        path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    return found


def lookup_term(vault_root: Path, term: str) -> GlossaryEntry | None:
    """Search the glossary for a term (case-insensitive). Returns first match or None."""
    glossary_path = vault_root / "brain" / "Glossary.md"
    if glossary_path.exists():
        for entry in parse_glossary(glossary_path):
            if entry.term.lower() == term.lower():
                return entry
    return None


def parse_quick_reference(file_path: Path) -> list[QuickRefEntry]:
    """Parse Quick-Reference.md into a list of QuickRefEntry grouped by section."""
    if not file_path.exists():
        return []

    content = file_path.read_text(encoding="utf-8")
    entries: list[QuickRefEntry] = []
    current_section = ""

    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("## ") and stripped[3:] in ("People", "Terms", "Projects"):
            current_section = stripped[3:]
            continue
        if not current_section:
            continue

        match = TABLE_ROW_RE.match(stripped)
        if not match:
            continue

        name = match.group("key").strip()
        rest_cols = [c.strip() for c in match.group("rest").split("|")]
        col2 = rest_cols[0] if len(rest_cols) > 0 else ""
        col3 = rest_cols[1] if len(rest_cols) > 1 else ""

        entries.append(QuickRefEntry(
            section=current_section, name=name, col2=col2, col3=col3,
        ))

    return entries


def add_quick_ref_entry(vault_root: Path, section: str, name: str, col2: str, col3: str) -> None:
    """Add an entry to a Quick-Reference section. Skips if name exists (case-insensitive)."""
    path = ensure_quick_reference(vault_root)
    existing = parse_quick_reference(path)
    if any(e.section == section and e.name.lower() == name.lower() for e in existing):
        return

    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()

    # Terms section is 2-column; People and Projects are 3-column
    if section == "Terms":
        row = f"| **{name}** | {col2} |"
    else:
        row = f"| **{name}** | {col2} | {col3} |"

    # Find end of section's table: last table row (|...) before a blank line or next ##
    in_section = False
    seen_table = False
    insert_idx = len(lines)

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == f"## {section}":
            in_section = True
            insert_idx = i + 1  # default: right after header
            continue
        if in_section:
            if stripped.startswith("## "):
                # Hit next section — insert before it
                insert_idx = i
                break
            if stripped.startswith("|"):
                # Table row or separator — insert after it
                seen_table = True
                insert_idx = i + 1
            elif stripped == "" and seen_table:
                # Blank line after the table — insert before the blank
                break
            # Blank lines BEFORE the table (between header and table) are skipped,
            # so the new row lands inside the table, not above its header.

    lines.insert(insert_idx, row)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def remove_quick_ref_entry(vault_root: Path, section: str, name: str) -> bool:
    """Remove an entry from a Quick-Reference section by section+name. Returns True if found."""
    path = vault_root / "brain" / "Quick-Reference.md"
    if not path.exists():
        return False

    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()
    new_lines = []
    found = False
    current_section = ""

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## ") and stripped[3:] in ("People", "Terms", "Projects"):
            current_section = stripped[3:]

        match = TABLE_ROW_RE.match(stripped)
        if (
            current_section == section
            and match
            and match.group("key").strip().lower() == name.lower()
        ):
            found = True
            continue
        new_lines.append(line)

    if found:
        path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    return found
