"""D5's regex is tightened: a passing mention of staged / --cached / uncommitted credits nothing.

The experiment's D5 regex was the bare alternation ``staged|--cached|uncommitted``,
matched disjunctively, so a finding that merely listed the spec's guards, named a
test, or described a clean state credited the missing-guard defect. Every
passing-mention text below carries one of those words, and every one of them is
matched by the experiment's own regex (the tests are red against the disjunctive
rule); under the repaired item none credits D5. D5 needs a negator, a guard word
and the marker word in ONE clause.
"""

from __future__ import annotations

import re

import pytest

from evals._harness.dispatch import Evidence

SYNC_SCRIPT = "plugins/workbench/skills/vault-wrap-up/scripts/sync_boundary_squash.py"

PASSING_MENTIONS = {
    "docstring-staged": "The module docstring says it runs from the vault root after the wrap-up commit, with staged files left in place.",
    "test-name-and-cached": "test_staged_uncommitted_changes_skip_squash exercises this function and reads `git diff --cached` output.",
    "clean-state-list": "every SPEC-listed condition is satisfied (no merge commit, clean pushed/unpushed prefix, no staged changes, reachable remote, attached HEAD, ancestor base, non-empty diff)",
    "spec-guard-list": "that SPEC's Guards section never lists: the spec enumerates exactly seven ambiguity conditions (merge commit in range, interleaved classification, staged-but-uncommitted changes, an unreachable remote) and this is not one of them",
    "negator-in-another-sentence": "There is no rebase guard here. Staged files are mentioned in the docstring.",
    "negator-on-the-previous-line": "There is no check for the remote head\nand staged files are fine.",
    "negator-in-another-clause": "There is no guard against concurrent pushes, and staged files are untouched.",
    "nobody-is-not-a-negator": "Nobody checks the staged index in the happy path.",
    "unstaged-is-not-staged": "There is no check for unstaged files in this helper.",
    "no-longer-is-not-a-negator": "The test no longer skips the squash when staged files exist.",
    "negator-too-far-from-the-word": "squash() does not verify that the remote head is reachable before the squash proceeds and the staged index is then read once.",
    "word-alone": "staged",
    "cached-alone": "--cached",
    "uncommitted-alone": "uncommitted",
}

GENUINE_ABSENCES = {
    "no-check-for": "squash() contains no check for staged-but-uncommitted changes before the reset.",
    "never-checks": "squash() never checks for staged-but-uncommitted changes before rewriting history",
    "no-cached-guard": "There is no `git diff --cached` guard anywhere in the function.",
    "no-staged-index-check": "squash() has no staged/index check anywhere in the file.",
    "lacks": "squash() lacks any check for uncommitted changes.",
    "does-not-guard": "The function does not guard against staged changes.",
    "without": "Without a check for staged files the reset sweeps them into the commit.",
    "shouting": "NEVER CHECKS FOR STAGED CHANGES before it resets.",
}


def _credits_d5(items, predicates, text: str, *, file: str = SYNC_SCRIPT) -> bool:
    item = items["A2-D5"]
    finding = {"file": file, "line": 168, "description": text}
    evidence = Evidence(transcripts=[], findings=[finding], workdir=None, end_state={})
    return getattr(predicates, item["scorer"])(evidence, **item["params"])


@pytest.mark.parametrize("text", PASSING_MENTIONS.values(), ids=PASSING_MENTIONS.keys())
def test_a_passing_mention_does_not_credit_d5(items, predicates, text):
    assert _credits_d5(items, predicates, text) is False


@pytest.mark.parametrize("text", PASSING_MENTIONS.values(), ids=PASSING_MENTIONS.keys())
def test_the_experiments_disjunctive_regex_would_have_credited_that_passing_mention(defects, text):
    """Why the passing-mention test is red against the experiment's rule."""
    assert re.search(defects["D5"]["regex"], text, re.IGNORECASE)


@pytest.mark.parametrize("text", GENUINE_ABSENCES.values(), ids=GENUINE_ABSENCES.keys())
def test_a_finding_that_says_the_guard_is_missing_credits_d5(items, predicates, text):
    assert _credits_d5(items, predicates, text) is True


@pytest.mark.parametrize("text", GENUINE_ABSENCES.values(), ids=GENUINE_ABSENCES.keys())
def test_a_genuine_absence_in_the_wrong_file_does_not_credit_d5(items, predicates, text):
    wrong = "plugins/workbench/skills/vault-wrap-up/scripts/tests/test_sync_boundary_squash.py"
    assert _credits_d5(items, predicates, text, file=wrong) is False


def test_the_regex_alone_never_credits_a_passing_mention_in_the_right_file(items):
    regex = items["A2-D5"]["params"]["regex"]
    for text in PASSING_MENTIONS.values():
        assert not re.search(regex, text, re.IGNORECASE), text
