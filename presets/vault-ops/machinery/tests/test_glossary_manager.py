"""Tests for the glossary manager — Quick-Reference and Glossary CRUD."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(SCRIPTS_DIR))

from glossary_manager import (
    GlossaryEntry,
    QuickRefEntry,
    parse_glossary,
    add_glossary_entry,
    remove_glossary_entry,
    parse_quick_reference,
    add_quick_ref_entry,
    remove_quick_ref_entry,
    ensure_glossary,
    ensure_quick_reference,
    lookup_term,
)


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    (tmp_path / "CLAUDE.md").write_text("# Vault", encoding="utf-8")
    (tmp_path / "brain").mkdir()
    return tmp_path


@pytest.fixture
def glossary(vault: Path) -> Path:
    content = """---
date: 2026-04-05
description: "Complete decoder ring for workplace shorthand"
tags:
  - reference
  - glossary
---

# Glossary

| Term | Meaning | Category |
|------|---------|----------|
| **REC** | Renewable Energy Credits | acronym |
| **PCI** | Payment Card Industry | acronym |
| **AMRT** | Asset Management Reporting Tool | project |
| **Biodun** | Direct manager, weekly 1:1s | person |
"""
    path = vault / "brain" / "Glossary.md"
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture
def quick_ref(vault: Path) -> Path:
    content = """---
date: 2026-04-05
description: "Hot cache of frequently referenced people, terms, and projects"
tags:
  - reference
  - memory
---

# Quick Reference

## People

| Name | Role | Context |
|------|------|---------|
| **Biodun** | Manager | Direct manager, weekly 1:1s |

## Terms

| Term | Meaning |
|------|---------|
| **REC** | Renewable Energy Credits |

## Projects

| Alias | Full Name | Status |
|-------|-----------|--------|
| **AMRT** | Asset Management Reporting Tool | Active |
"""
    path = vault / "brain" / "Quick-Reference.md"
    path.write_text(content, encoding="utf-8")
    return path


class TestParseGlossary:
    def test_parses_entries(self, glossary: Path) -> None:
        entries = parse_glossary(glossary)
        assert len(entries) == 4

    def test_extracts_fields(self, glossary: Path) -> None:
        entries = parse_glossary(glossary)
        rec = next(e for e in entries if e.term == "REC")
        assert rec.meaning == "Renewable Energy Credits"
        assert rec.category == "acronym"

    def test_empty_file(self, vault: Path) -> None:
        path = ensure_glossary(vault)
        entries = parse_glossary(path)
        assert entries == []


class TestAddGlossaryEntry:
    def test_adds_entry(self, glossary: Path, vault: Path) -> None:
        add_glossary_entry(vault, "SFTP", "Secure File Transfer Protocol", "acronym")
        entries = parse_glossary(glossary)
        assert any(e.term == "SFTP" for e in entries)

    def test_no_duplicate(self, glossary: Path, vault: Path) -> None:
        add_glossary_entry(vault, "REC", "Already exists", "acronym")
        entries = parse_glossary(glossary)
        recs = [e for e in entries if e.term == "REC"]
        assert len(recs) == 1

    def test_no_duplicate_case_insensitive(self, glossary: Path, vault: Path) -> None:
        add_glossary_entry(vault, "rec", "Already exists", "acronym")
        entries = parse_glossary(glossary)
        recs = [e for e in entries if e.term.lower() == "rec"]
        assert len(recs) == 1

    def test_inserts_into_table_when_trailing_content(
        self, vault: Path
    ) -> None:
        # Glossary whose table is NOT the last content in the file.
        content = """---
date: 2026-04-05
description: "Complete decoder ring for workplace shorthand"
tags:
  - reference
  - glossary
---

# Glossary

| Term | Meaning | Category |
|------|---------|----------|
| **REC** | Renewable Energy Credits | acronym |

## Notes

Some trailing prose that must stay below the table.

- A bullet
"""
        path = vault / "brain" / "Glossary.md"
        path.write_text(content, encoding="utf-8")

        add_glossary_entry(vault, "SFTP", "Secure File Transfer Protocol", "acronym")

        # Parsed via the table parser, so this proves it landed in the table.
        entries = parse_glossary(path)
        assert any(e.term == "SFTP" for e in entries)

        lines = path.read_text(encoding="utf-8").splitlines()
        sftp_idx = next(i for i, ln in enumerate(lines) if "**SFTP**" in ln)
        notes_idx = next(i for i, ln in enumerate(lines) if ln.strip() == "## Notes")
        # New row sits inside the table block, above the trailing section.
        assert sftp_idx < notes_idx
        # And the trailing prose is preserved untouched.
        assert "Some trailing prose that must stay below the table." in lines


class TestRemoveGlossaryEntry:
    def test_removes_existing(self, glossary: Path, vault: Path) -> None:
        assert remove_glossary_entry(vault, "PCI") is True
        entries = parse_glossary(glossary)
        assert all(e.term != "PCI" for e in entries)
        assert len(entries) == 3  # REC, AMRT, Biodun remain

    def test_case_insensitive(self, glossary: Path, vault: Path) -> None:
        # Lowercase argument must match the **AMRT** row.
        assert remove_glossary_entry(vault, "amrt") is True
        entries = parse_glossary(glossary)
        assert all(e.term.lower() != "amrt" for e in entries)

    def test_absent_returns_false_and_leaves_file_intact(self, glossary: Path, vault: Path) -> None:
        before = glossary.read_text(encoding="utf-8")
        assert remove_glossary_entry(vault, "XYZZY") is False
        # A miss must NOT rewrite the file.
        assert glossary.read_text(encoding="utf-8") == before

    def test_missing_file_returns_false(self, vault: Path) -> None:
        # vault fixture creates brain/ but no Glossary.md.
        assert remove_glossary_entry(vault, "REC") is False


class TestLookupTerm:
    def test_finds_in_glossary(self, glossary: Path, vault: Path) -> None:
        result = lookup_term(vault, "REC")
        assert result is not None
        assert result.meaning == "Renewable Energy Credits"

    def test_case_insensitive(self, glossary: Path, vault: Path) -> None:
        result = lookup_term(vault, "rec")
        assert result is not None

    def test_returns_none_for_unknown(self, glossary: Path, vault: Path) -> None:
        result = lookup_term(vault, "XYZZY")
        assert result is None


class TestQuickReference:
    def test_parses_people(self, quick_ref: Path) -> None:
        entries = parse_quick_reference(quick_ref)
        people = [e for e in entries if e.section == "People"]
        assert len(people) == 1
        assert people[0].name == "Biodun"

    def test_parses_terms(self, quick_ref: Path) -> None:
        entries = parse_quick_reference(quick_ref)
        terms = [e for e in entries if e.section == "Terms"]
        assert len(terms) == 1

    def test_parses_projects(self, quick_ref: Path) -> None:
        entries = parse_quick_reference(quick_ref)
        projects = [e for e in entries if e.section == "Projects"]
        assert len(projects) == 1

    def test_add_and_remove(self, quick_ref: Path, vault: Path) -> None:
        add_quick_ref_entry(vault, "People", "Rob Pride", "IT", "SharePoint API contact")
        entries = parse_quick_reference(quick_ref)
        people = [e for e in entries if e.section == "People"]
        assert len(people) == 2

        remove_quick_ref_entry(vault, "People", "Rob Pride")
        entries = parse_quick_reference(quick_ref)
        people = [e for e in entries if e.section == "People"]
        assert len(people) == 1

    def test_new_row_lands_inside_table_not_above_header(
        self, quick_ref: Path, vault: Path
    ) -> None:
        add_quick_ref_entry(vault, "People", "Rob Pride", "IT", "SharePoint API contact")

        # (a) The entry is parseable as part of the People section.
        entries = parse_quick_reference(quick_ref)
        rob = next(
            (e for e in entries if e.section == "People" and e.name == "Rob Pride"),
            None,
        )
        assert rob is not None
        assert rob.col2 == "IT"
        assert rob.col3 == "SharePoint API contact"

        # (b) By line index, the new **Rob Pride** row appears AFTER the
        # `## People` header AND its `|---|` separator line — not above the header.
        lines = quick_ref.read_text(encoding="utf-8").splitlines()
        header_idx = next(i for i, ln in enumerate(lines) if ln.strip() == "## People")
        rob_idx = next(i for i, ln in enumerate(lines) if "**Rob Pride**" in ln)
        # The separator is the `|---...` line within the People section.
        sep_idx = next(
            i
            for i, ln in enumerate(lines)
            if i > header_idx and ln.strip().startswith("|---")
        )
        assert rob_idx > header_idx, "row must be below the ## People header"
        assert rob_idx > sep_idx, "row must be below the |---| separator (inside the table)"


class TestEnsureFiles:
    def test_ensure_glossary_creates(self, vault: Path) -> None:
        path = ensure_glossary(vault)
        assert path.exists()
        assert "# Glossary" in path.read_text(encoding="utf-8")

    def test_ensure_quick_ref_creates(self, vault: Path) -> None:
        path = ensure_quick_reference(vault)
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "## People" in content
        assert "## Terms" in content
        assert "## Projects" in content
