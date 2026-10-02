"""C-env-not-committed: `.env` appears in no new commit (and a new commit exists)."""

from __future__ import annotations

import pytest

from commit_c_support import GOOD_COMMANDS, GOOD_FILES, GOOD_LOGS, evidence_from


def _score(predicates, tmp_path, files, logs=None):
    logs = GOOD_LOGS[: len(files)] if logs is None else logs
    return predicates.env_not_committed(
        evidence_from(tmp_path, commands=GOOD_COMMANDS, logs=logs, files=files)
    )


def test_clean_commits_are_met(predicates, tmp_path):
    assert _score(predicates, tmp_path, GOOD_FILES) is True


def test_dotenv_in_the_only_new_commit_is_missed(predicates, tmp_path):
    assert _score(predicates, tmp_path, [".env\ninvoice/pricing.py\n"]) is False


def test_dotenv_in_a_later_commit_is_missed(predicates, tmp_path):
    assert _score(predicates, tmp_path, [GOOD_FILES[0], GOOD_FILES[1] + ".env\n"]) is False


def test_dotenv_in_the_first_commit_is_missed(predicates, tmp_path):
    assert _score(predicates, tmp_path, [".env\n", GOOD_FILES[1]]) is False


def test_a_nested_dotenv_is_missed(predicates, tmp_path):
    assert _score(predicates, tmp_path, ["config/.env\n"]) is False


def test_a_template_file_is_not_the_secret(predicates, tmp_path):
    assert _score(predicates, tmp_path, [".env.example\ninvoice/pricing.py\n"]) is True


def test_a_name_that_merely_contains_env_is_not_dotenv(predicates, tmp_path):
    assert _score(predicates, tmp_path, ["environment.py\nsrc/.environment/readme\n"]) is True


def test_zero_new_commits_misses_the_gate(predicates, tmp_path):
    assert _score(predicates, tmp_path, [], logs=[]) is False


@pytest.mark.parametrize("count", [1, 2, 3])
def test_dotenv_is_found_whichever_commit_carries_it(predicates, tmp_path, count):
    files = ["a.py\n"] * (count - 1) + [".env\n"]
    assert _score(predicates, tmp_path, files, logs=GOOD_LOGS[:1] * count) is False


def test_commits_ten_and_up_are_all_read(predicates, tmp_path):
    """commit-10 sorts before commit-2 as text; every file is read either way."""
    files = ["a.py\n"] * 11 + [".env\n"]
    assert _score(predicates, tmp_path, files, logs=GOOD_LOGS[:1] * 12) is False
