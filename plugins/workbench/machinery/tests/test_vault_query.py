"""Tests for vault_query — markdown table formatting and note scanning.

Covers two fixes:
- #53: _format_table must escape pipe characters in cell values so a cell
  containing `|` does not break the markdown table.
- #41: _scan_notes must dedupe overlapping directory scans so each note
  appears exactly once.
"""

from __future__ import annotations

import sys
from pathlib import Path

# vault_query lives under .claude/scripts/queries/ and imports sibling modules
# (frontmatter_engine, vault_utils) from .claude/scripts/ assuming that dir is
# on sys.path. Neither dir is a package (no __init__.py), so put BOTH on the
# path and import the module directly.
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(SCRIPTS_DIR / "queries"))

import vault_query
from vault_query import _format_table, _scan_notes


# ---------------------------------------------------------------------------
# #53 — _format_table escapes pipe characters in cells
# ---------------------------------------------------------------------------

def test_format_table_escapes_pipe_in_cell() -> None:
    """A cell value containing `|` must not emit an unescaped pipe inside the
    cell (it would otherwise be read as a column separator)."""
    out = _format_table(["Note"], [["a|b"]])
    data_line = out.splitlines()[2]  # header, separator, then first data row

    # The literal sequence "a|b" must not survive — the pipe is escaped.
    assert "a|b" not in data_line
    # And the escaped form is present.
    assert "a\\|b" in data_line


def test_format_table_escaped_cell_has_correct_column_count() -> None:
    """With the pipe escaped, the data row has the same number of real column
    separators as the header row (a stray `|` would add a phantom column)."""
    out = _format_table(["Note"], [["a|b"]])
    lines = out.splitlines()
    header_line, data_line = lines[0], lines[2]

    def real_separators(line: str) -> int:
        # Count unescaped pipes (column separators), ignoring escaped \| .
        return line.replace("\\|", "").count("|")

    assert real_separators(data_line) == real_separators(header_line)


# ---------------------------------------------------------------------------
# #41 — _scan_notes dedupes overlapping directory scans
# ---------------------------------------------------------------------------

def _write_note(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        "date: 2026-06-28\n"
        'description: "test note"\n'
        "tags:\n  - test\n"
        "---\n\n"
        "# Note\n",
        encoding="utf-8",
    )


def test_scan_notes_dedupes_overlapping_dirs(tmp_path: Path) -> None:
    """When a directory and its parent are both scanned, a note inside the
    child must appear exactly once, not twice."""
    note = tmp_path / "work" / "active" / "task.md"
    _write_note(note)

    # "work" (parent) and "work/active" (child) overlap — rglob from each would
    # surface task.md twice without deduping.
    results = _scan_notes(tmp_path, ["work", "work/active"])

    paths = [p for p, _ in results]
    assert paths.count(note) == 1
    assert len(paths) == len(set(paths))


def test_scan_notes_returns_all_distinct_notes(tmp_path: Path) -> None:
    """Deduping must not drop distinct notes."""
    n1 = tmp_path / "work" / "active" / "a.md"
    n2 = tmp_path / "work" / "incidents" / "b.md"
    _write_note(n1)
    _write_note(n2)

    # "work" overlaps both children; b.md is only under work/incidents.
    results = _scan_notes(tmp_path, ["work", "work/active"])
    paths = {p for p, _ in results}

    assert n1 in paths
    assert n2 in paths
    assert len(paths) == 2


# ---------------------------------------------------------------------------
# Helpers for the broader coverage below
# ---------------------------------------------------------------------------

def _write_fm_note(path: Path, fm_lines: str, body: str = "# Note\n") -> None:
    """Write a markdown note with the given raw frontmatter block (no fences)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{fm_lines}---\n\n{body}", encoding="utf-8")


# ---------------------------------------------------------------------------
# _parse_frontmatter — valid / missing / malformed / unreadable
# ---------------------------------------------------------------------------

def test_parse_frontmatter_valid_returns_dict(tmp_path: Path) -> None:
    """A well-formed note returns the parsed frontmatter mapping."""
    note = tmp_path / "ok.md"
    _write_fm_note(note, 'date: 2026-06-28\ndescription: "x"\ntags:\n  - test\n')

    fm = vault_query._parse_frontmatter(note)

    assert fm is not None
    assert str(fm["date"]) == "2026-06-28"  # YAML coerces bare dates to date objects
    assert fm["tags"] == ["test"]


def test_parse_frontmatter_missing_returns_none(tmp_path: Path) -> None:
    """A file with no frontmatter (does not start with ---) yields None."""
    note = tmp_path / "plain.md"
    note.write_text("# Just a heading, no frontmatter\n", encoding="utf-8")

    assert vault_query._parse_frontmatter(note) is None


def test_parse_frontmatter_malformed_returns_none(tmp_path: Path) -> None:
    """Invalid YAML inside the fences yields None rather than raising."""
    note = tmp_path / "bad.md"
    # Unterminated/invalid YAML mapping triggers a YAMLError upstream.
    note.write_text("---\nkey: [unclosed\n---\n\nbody\n", encoding="utf-8")

    assert vault_query._parse_frontmatter(note) is None


def test_parse_frontmatter_unreadable_returns_none(tmp_path: Path) -> None:
    """A path that cannot be read (e.g. a directory) yields None, not an error."""
    d = tmp_path / "adir.md"
    d.mkdir()

    assert vault_query._parse_frontmatter(d) is None


# ---------------------------------------------------------------------------
# _has_tag — list tags, comma-string tags, absent tag
# ---------------------------------------------------------------------------

def test_has_tag_finds_tag_in_list() -> None:
    assert vault_query._has_tag({"tags": ["a", "decision", "b"]}, "decision") is True


def test_has_tag_absent_tag_returns_false() -> None:
    assert vault_query._has_tag({"tags": ["a", "b"]}, "decision") is False


def test_has_tag_handles_comma_string_tags() -> None:
    """When tags is a comma-separated string, it is split and matched."""
    assert vault_query._has_tag({"tags": "a, decision, b"}, "decision") is True


def test_has_tag_missing_tags_key_returns_false() -> None:
    assert vault_query._has_tag({}, "decision") is False


# ---------------------------------------------------------------------------
# _format_table — empty results and basic structure
# ---------------------------------------------------------------------------

def test_format_table_empty_rows_returns_no_results() -> None:
    assert _format_table(["Note"], []) == "(no results)\n"


def test_format_table_basic_structure() -> None:
    """Header, separator, and one data row are emitted in order."""
    out = _format_table(["Name", "Role"], [["Jane", "Eng"]])
    lines = out.splitlines()

    assert lines[0].startswith("| Name") and "Role" in lines[0]
    assert set(lines[1].replace("|", "").replace(" ", "")) == {"-"}
    assert "Jane" in lines[2] and "Eng" in lines[2]


# ---------------------------------------------------------------------------
# query_active_work — scope, projection, date-desc ordering
# ---------------------------------------------------------------------------

def test_query_active_work_includes_active_and_incidents(tmp_path: Path) -> None:
    _write_fm_note(
        tmp_path / "work" / "active" / "task.md",
        'date: 2026-06-01\ndescription: "d"\nstatus: active\nproject: Alpha\ntags:\n  - work\n',
    )
    _write_fm_note(
        tmp_path / "work" / "incidents" / "inc.md",
        'date: 2026-06-02\ndescription: "d"\nstatus: open\ntags:\n  - incident\n',
    )

    out = vault_query.query_active_work(tmp_path)

    assert "task" in out
    assert "inc" in out
    assert "Alpha" in out


def test_query_active_work_sorts_by_date_descending(tmp_path: Path) -> None:
    _write_fm_note(
        tmp_path / "work" / "active" / "older.md",
        'date: 2026-01-01\ndescription: "d"\nstatus: active\ntags:\n  - work\n',
    )
    _write_fm_note(
        tmp_path / "work" / "active" / "newer.md",
        'date: 2026-12-31\ndescription: "d"\nstatus: active\ntags:\n  - work\n',
    )

    out = vault_query.query_active_work(tmp_path)

    assert out.index("newer") < out.index("older")


def test_query_active_work_missing_dirs_returns_no_results(tmp_path: Path) -> None:
    """No work dirs at all -> graceful empty table, not an error."""
    assert vault_query.query_active_work(tmp_path) == "(no results)\n"


# ---------------------------------------------------------------------------
# query_decisions — tag filter + date-desc sort
# ---------------------------------------------------------------------------

def test_query_decisions_filters_to_decision_tag(tmp_path: Path) -> None:
    _write_fm_note(
        tmp_path / "brain" / "dec.md",
        'date: 2026-05-01\ndescription: "a decision"\nstatus: accepted\ntags:\n  - decision\n',
    )
    _write_fm_note(
        tmp_path / "brain" / "note.md",
        'date: 2026-05-02\ndescription: "not a decision"\ntags:\n  - misc\n',
    )

    out = vault_query.query_decisions(tmp_path)

    assert "dec" in out
    assert "note" not in out


def test_query_decisions_sorts_by_date_descending(tmp_path: Path) -> None:
    _write_fm_note(
        tmp_path / "brain" / "old.md",
        'date: 2026-01-01\ndescription: "d"\ntags:\n  - decision\n',
    )
    _write_fm_note(
        tmp_path / "brain" / "new.md",
        'date: 2026-09-09\ndescription: "d"\ntags:\n  - decision\n',
    )

    out = vault_query.query_decisions(tmp_path)

    assert out.index("new") < out.index("old")


# ---------------------------------------------------------------------------
# query_people — scope + role/team projection
# ---------------------------------------------------------------------------

def test_query_people_lists_org_people_with_role_and_team(tmp_path: Path) -> None:
    _write_fm_note(
        tmp_path / "org" / "people" / "Jane Smith.md",
        'date: 2026-06-01\ndescription: "person"\nrole: Engineer\nteam: Platform\ntags:\n  - person\n',
    )

    out = vault_query.query_people(tmp_path)

    assert "Jane Smith" in out
    assert "Engineer" in out
    assert "Platform" in out


# ---------------------------------------------------------------------------
# query_competencies — current/target level projection
# ---------------------------------------------------------------------------

def test_query_competencies_projects_levels(tmp_path: Path) -> None:
    _write_fm_note(
        tmp_path / "perf" / "competencies" / "Data Modeling.md",
        'date: 2026-06-01\ndescription: "c"\ncurrent_level: 2\ntarget_level: 4\ntags:\n  - competency\n',
    )

    out = vault_query.query_competencies(tmp_path)

    assert "Data Modeling" in out
    assert "2" in out
    assert "4" in out


# ---------------------------------------------------------------------------
# query_brag — tag filter (brag-doc OR evidence)
# ---------------------------------------------------------------------------

def test_query_brag_includes_brag_and_evidence_excludes_others(tmp_path: Path) -> None:
    _write_fm_note(
        tmp_path / "perf" / "brag.md",
        'date: 2026-06-01\ndescription: "a win"\ntags:\n  - brag-doc\n',
    )
    _write_fm_note(
        tmp_path / "perf" / "evidence" / "ev.md",
        'date: 2026-06-02\ndescription: "some evidence"\ntags:\n  - evidence\n',
    )
    _write_fm_note(
        tmp_path / "perf" / "other.md",
        'date: 2026-06-03\ndescription: "unrelated"\ntags:\n  - misc\n',
    )

    out = vault_query.query_brag(tmp_path)

    assert "brag" in out
    assert "ev" in out
    assert "other" not in out


# ---------------------------------------------------------------------------
# query_learning — scope + date-desc ordering
# ---------------------------------------------------------------------------

def test_query_learning_sorts_by_date_descending(tmp_path: Path) -> None:
    _write_fm_note(
        tmp_path / "personal" / "learning" / "old.md",
        'date: 2026-02-02\ndescription: "d"\nstatus: done\nsource: book\ntags:\n  - learning\n',
    )
    _write_fm_note(
        tmp_path / "personal" / "learning" / "new.md",
        'date: 2026-11-11\ndescription: "d"\nstatus: active\nsource: course\ntags:\n  - learning\n',
    )

    out = vault_query.query_learning(tmp_path)

    assert "course" in out
    assert out.index("new") < out.index("old")
