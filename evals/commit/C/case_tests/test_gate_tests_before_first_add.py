"""C-tests-before-first-add: `make test` ran before the first `git add` (and a commit exists).

The ordering itself is #992's generic ``matchers.precedes``; these tests drive
it through the case's predicate.
"""

from __future__ import annotations

import pytest

from commit_c_support import GOOD_COMMANDS, GOOD_FILES, GOOD_LOGS, evidence_from, write_transcript

from evals._harness.dispatch import Evidence
from evals._harness.transcript import parse_transcript


def _score(predicates, tmp_path, commands, logs=GOOD_LOGS, files=GOOD_FILES):
    return predicates.tests_before_first_add(
        evidence_from(tmp_path, commands=commands, logs=logs, files=files)
    )


def test_tests_then_adds_is_met(predicates, tmp_path):
    assert _score(predicates, tmp_path, GOOD_COMMANDS) is True


def test_tests_after_the_first_add_is_missed(predicates, tmp_path):
    commands = [
        "git status",
        "git add invoice/pricing.py tests/test_pricing.py",
        "make test",
        'git commit -m "feat(invoice): add bulk pricing"',
        "git add names/normalize.py tests/test_names.py",
        'git commit -m "fix(names): collapse inner whitespace"',
    ]
    assert _score(predicates, tmp_path, commands) is False


def test_tests_run_only_after_all_the_adds_is_missed(predicates, tmp_path):
    commands = ["git add -u", 'git commit -m "feat: x"', "make test"]
    assert _score(predicates, tmp_path, commands) is False


def test_no_test_run_at_all_is_missed(predicates, tmp_path):
    commands = [c for c in GOOD_COMMANDS if c != "make test"]
    assert _score(predicates, tmp_path, commands) is False


def test_no_add_at_all_is_missed(predicates, tmp_path):
    assert _score(predicates, tmp_path, ["make test", 'git commit -am "feat: x"']) is False


@pytest.mark.parametrize(
    "tests",
    [
        "make test",
        "make -s test",
        "make test VERBOSE=1",
        "make -C . test",
        "cd repo && make test",
        "make test 2>&1 | tail -20",
        "make test; echo done",
        "FOO=1 make test",
    ],
)
def test_the_ways_of_running_make_test_all_count(predicates, tmp_path, tests):
    commands = [tests, "git add invoice/pricing.py", 'git commit -m "feat: x"']
    assert _score(predicates, tmp_path, commands) is True


@pytest.mark.parametrize(
    "not_tests",
    [
        "make",
        "make build",
        "make test-evals",
        "make lint",
        "python3 -m unittest discover",
        "echo make test",
        "make -n lint # make test",
        'git commit -m "make test passes"',
        "cat Makefile",
        "make -C test build",
    ],
)
def test_other_commands_do_not_count_as_running_the_tests(predicates, tmp_path, not_tests):
    commands = [not_tests, "git add invoice/pricing.py", 'git commit -m "feat: x"']
    assert _score(predicates, tmp_path, commands) is False


def test_tests_and_add_chained_in_one_call_count_in_order(predicates, tmp_path):
    commands = ["make test && git add invoice/pricing.py && git commit -m 'feat: x'"]
    assert _score(predicates, tmp_path, commands) is True


def test_add_then_tests_chained_in_one_call_is_missed(predicates, tmp_path):
    commands = ["git add invoice/pricing.py && make test && git commit -m 'feat: x'"]
    assert _score(predicates, tmp_path, commands) is False


def test_only_the_first_add_matters(predicates, tmp_path):
    commands = ["make test", "git add a.py", "git commit -m 'feat: x'", "git add b.py"]
    assert _score(predicates, tmp_path, commands) is True
    commands = ["git add a.py", "make test", "git add b.py"]
    assert _score(predicates, tmp_path, commands) is False


def test_a_test_run_earlier_than_the_first_add_is_enough(predicates, tmp_path):
    commands = ["make test", "git add a.py", "make test", "git add b.py"]
    assert _score(predicates, tmp_path, commands) is True


def test_zero_new_commits_misses_the_gate(predicates, tmp_path):
    assert _score(predicates, tmp_path, GOOD_COMMANDS, logs=[], files=[]) is False


def test_the_ordering_is_decided_by_matchers_precedes(predicates, tmp_path, monkeypatch):
    """The conjunct delegates to #992's predicate: swap it and the verdict follows."""
    seen = []

    def always(events, first, then):
        seen.append(len(events))
        return True

    monkeypatch.setattr(predicates.matchers, "precedes", always)
    bad_order = ["git add a.py", "make test"]
    assert _score(predicates, tmp_path, bad_order) is True
    assert seen, "precedes was never called"


def test_the_ordering_holds_across_the_committed_transcripts(predicates, case_dir, tmp_path):
    transcripts = case_dir / "case_tests" / "transcripts"
    good = parse_transcript(transcripts / "good_run.jsonl")
    late = parse_transcript(transcripts / "tests_after_add.jsonl")
    end_state = {"commit-1.log": GOOD_LOGS[0], "commit-1.files": GOOD_FILES[0]}
    assert predicates.tests_before_first_add(Evidence([good], [], None, end_state)) is True
    assert predicates.tests_before_first_add(Evidence([late], [], None, end_state)) is False


def test_synthetic_transcripts_keep_the_real_envelope_shape(tmp_path):
    path = write_transcript(tmp_path / "t.jsonl", ["make test"])
    transcript = parse_transcript(path)
    assert transcript.status == "complete"
    assert [event.name for event in transcript.events] == ["Bash"]
    assert transcript.events[0].input["command"] == "make test"
    assert transcript.events[0].result is not None
