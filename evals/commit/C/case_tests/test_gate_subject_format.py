"""C-subject-format: every new subject matches the commit skill's format, within 72 chars."""

from __future__ import annotations

import pytest

from commit_c_support import GOOD_COMMANDS, GOOD_FILES, commit_log_text, evidence_from

SPEC_PATTERN = r"^(feat|fix|refactor|style|docs|test|chore|perf|ci)(\([a-z0-9._/-]+\))?: [a-z0-9][^A-Z]*[^A-Z.]$"


def _score(predicates, tmp_path, subjects):
    logs = [commit_log_text(subject) for subject in subjects]
    return predicates.subject_format(
        evidence_from(tmp_path, commands=GOOD_COMMANDS, logs=logs, files=GOOD_FILES[: len(logs)])
    )


def test_the_pattern_is_exactly_the_specified_regex(predicates):
    assert predicates.SUBJECT_PATTERN == SPEC_PATTERN


def test_the_length_limit_is_seventy_two(predicates):
    assert predicates.SUBJECT_MAX_LENGTH == 72


def test_clean_subjects_are_met(predicates, tmp_path):
    assert _score(predicates, tmp_path, ["feat(invoice): add bulk pricing", "fix: trim names"]) is True


@pytest.mark.parametrize("kind", ["feat", "fix", "refactor", "style", "docs", "test", "chore", "perf", "ci"])
def test_all_nine_types_are_accepted(predicates, tmp_path, kind):
    assert _score(predicates, tmp_path, [f"{kind}: do the thing"]) is True


@pytest.mark.parametrize(
    "subject",
    [
        "feat: add Bulk pricing",
        "feat: add bulk pricingX",
        "feat: add bulk pricing.",
        "Feat: add bulk pricing",
        "FEAT: add bulk pricing",
        "feat(Invoice): add bulk pricing",
        "feat: Add bulk pricing",
        "feat:add bulk pricing",
        "feat : add bulk pricing",
        "feature: add bulk pricing",
        "add bulk pricing",
        "Add customer name normalizer",
        "update: add bulk pricing",
        "feat(): add bulk pricing",
        "feat: ",
        "feat: -add",
        "feat: a",  # the pattern needs a first and a last character
        "",
    ],
)
def test_bad_subjects_are_missed(predicates, tmp_path, subject):
    assert _score(predicates, tmp_path, [subject]) is False


def test_a_trailing_capital_is_missed(predicates, tmp_path):
    assert _score(predicates, tmp_path, ["fix: handle the API"]) is False


def test_a_trailing_period_is_missed(predicates, tmp_path):
    assert _score(predicates, tmp_path, ["fix: handle the api."]) is False


def test_exactly_seventy_two_characters_is_met(predicates, tmp_path):
    subject = "feat: " + "a" * (72 - len("feat: "))
    assert len(subject) == 72
    assert _score(predicates, tmp_path, [subject]) is True


def test_seventy_three_characters_is_missed(predicates, tmp_path):
    subject = "feat: " + "a" * (73 - len("feat: "))
    assert len(subject) == 73
    assert _score(predicates, tmp_path, [subject]) is False


def test_one_bad_subject_among_good_ones_is_missed(predicates, tmp_path):
    assert _score(predicates, tmp_path, ["feat: ok", "fix: ok too", "Fix: not ok"]) is False


def test_the_subject_is_the_second_line_of_the_log(predicates, tmp_path):
    """The first line is the SHA; a body line never stands in for the subject."""
    log = commit_log_text("feat: fine subject", "Body With Capitals And A Period.")
    evidence = evidence_from(tmp_path, commands=GOOD_COMMANDS, logs=[log], files=GOOD_FILES[:1])
    assert predicates.subject_format(evidence) is True


def test_a_log_with_no_subject_line_is_missed(predicates, tmp_path):
    evidence = evidence_from(tmp_path, commands=GOOD_COMMANDS, logs=["0123abcd\n"], files=GOOD_FILES[:1])
    assert predicates.subject_format(evidence) is False


def test_zero_new_commits_misses_the_gate(predicates, tmp_path):
    assert _score(predicates, tmp_path, []) is False
