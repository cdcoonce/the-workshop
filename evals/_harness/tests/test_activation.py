"""Tests for evals._harness.activation — manifest/retired parsing and is_active."""

from __future__ import annotations

from evals._harness.activation import (
    ROSTERED_SKILLS,
    is_active,
    parse_checks_manifest,
    parse_retired_entries,
)


def test_rostered_skills_is_the_three_epic_skills():
    assert ROSTERED_SKILLS == ("adversarial-review", "tdd", "commit")


def test_parse_checks_manifest_ignores_comments_and_blank_lines():
    text = """
    # a leading comment
    foo.bar Some description here

    baz-1 Another one
    """
    assert parse_checks_manifest(text) == ["foo.bar", "baz-1"]


def test_parse_checks_manifest_empty_text_returns_no_ids():
    assert parse_checks_manifest("") == []
    assert parse_checks_manifest("# only a comment\n\n") == []


def test_parse_checks_manifest_skips_a_line_whose_id_fails_the_grammar():
    text = "-bad-start A description\nok.id Another description\n"
    assert parse_checks_manifest(text) == ["ok.id"]


def test_parse_retired_entries_parses_every_field_of_two_entries():
    text = """
## a.first
- date: 2026-01-02
- reason: noise
- evidence: flaked twice in a row

## a.second
- date: 2026-02-03
- reason: superseded-by:a.first
- evidence: replaced by a.first
"""
    entries = parse_retired_entries(text)
    assert entries == [
        {
            "id": "a.first",
            "date": "2026-01-02",
            "reason": "noise",
            "evidence": "flaked twice in a row",
        },
        {
            "id": "a.second",
            "date": "2026-02-03",
            "reason": "superseded-by:a.first",
            "evidence": "replaced by a.first",
        },
    ]


def test_parse_retired_entries_empty_text_returns_no_entries():
    assert parse_retired_entries("") == []


def test_is_active_false_when_manifest_and_retired_are_both_empty(tmp_path):
    skill_dir = tmp_path / "commit"
    skill_dir.mkdir()
    (skill_dir / "checks.manifest").write_text("", encoding="utf-8")
    (skill_dir / "retired.md").write_text("", encoding="utf-8")
    assert is_active(skill_dir) is False


def test_is_active_false_when_retired_is_absent(tmp_path):
    skill_dir = tmp_path / "commit"
    skill_dir.mkdir()
    (skill_dir / "checks.manifest").write_text("# nothing yet\n", encoding="utf-8")
    assert is_active(skill_dir) is False


def test_is_active_true_with_one_gated_id_in_manifest(tmp_path):
    skill_dir = tmp_path / "commit"
    skill_dir.mkdir()
    (skill_dir / "checks.manifest").write_text("foo.bar A description\n", encoding="utf-8")
    (skill_dir / "retired.md").write_text("", encoding="utf-8")
    assert is_active(skill_dir) is True


def test_is_active_true_with_only_a_retired_entry_and_empty_manifest(tmp_path):
    skill_dir = tmp_path / "commit"
    skill_dir.mkdir()
    (skill_dir / "checks.manifest").write_text("", encoding="utf-8")
    (skill_dir / "retired.md").write_text(
        "## old.id\n- date: 2026-01-01\n- reason: noise\n- evidence: flaky\n",
        encoding="utf-8",
    )
    assert is_active(skill_dir) is True
