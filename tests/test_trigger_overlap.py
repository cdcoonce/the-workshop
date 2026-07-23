"""Unit tests for cross-skill trigger-phrase overlap detection in smoke_test."""

from scripts.smoke_test import _lint_trigger_overlaps


def test_flags_shared_quoted_trigger_phrase() -> None:
    """Two skills quoting the same multi-word trigger collide and are flagged."""
    descriptions = {
        "readme-generator": 'Use when the user says "write docs for this repo".',
        "repo-reference-docs": 'Use when the user says "write docs for this repo" for depth.',
    }
    findings = _lint_trigger_overlaps(descriptions)
    assert len(findings) == 1
    joined = findings[0].lower()
    assert "write docs for this repo" in joined
    assert "readme-generator" in joined
    assert "repo-reference-docs" in joined


def test_no_finding_for_distinct_triggers() -> None:
    """Skills with different quoted triggers do not collide."""
    descriptions = {
        "a": 'Use when the user says "generate a changelog".',
        "b": 'Use when the user says "review a pull request".',
    }
    assert _lint_trigger_overlaps(descriptions) == []


def test_ignores_short_common_phrases() -> None:
    """Short (<3-word) quoted tokens are too generic to be collisions."""
    descriptions = {
        "a": 'Use for a "README" file.',
        "b": 'Use for a "README" update.',
    }
    assert _lint_trigger_overlaps(descriptions) == []


def test_overlap_ignores_case_and_whitespace() -> None:
    """Phrase matching is normalized so trivial differences still collide."""
    descriptions = {
        "a": 'Use when asked to "Document This Project".',
        "b": 'Use when asked to "document this   project".',
    }
    assert len(_lint_trigger_overlaps(descriptions)) == 1
