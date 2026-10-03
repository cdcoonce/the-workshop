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
    "no-issue-here": "No issue here: the function checks staged changes correctly.",
    "nothing-wrong": "Nothing wrong with the staged-changes guard.",
    "never-fails-to": "It never fails to check for staged changes.",
    "not-only": "Not only does it check for staged files, it also resets cleanly.",
    "not-a-defect": "Not a defect: `git diff --cached` guard is present.",
    "but-staged-is-guarded": "squash() does not handle a detached HEAD but staged changes are guarded.",
    "comma-between-negator-and-guard": "There is no doubt, checks for staged changes exist in the function.",
    "not-uncommitted": "This is not uncommitted work, so there is nothing to guard.",
    "un-staged": "There is no check for un-staged files in this helper.",
    "not-only-checks": "Not only checks staged files but also resets cleanly.",
    "comma-before-the-guard-word": "Reviewer says no, check for staged changes before anything else.",
    "word-ending-in-no": "A piano check for staged files.",
    "identifier-starting-with-staged": "There is no check for staged_files.",
    "unstaged-guard-is-missing": "The unstaged-files guard is missing.",
    "un-staged-guard-is-absent": "The un-staged changes guard is absent.",
    "no-op": "The no-op path leaves staged files alone.",
    "guard-is-present": "The staged-changes guard is present.",
    "r2-no-issue-here-as": "No issue here as staged changes are handled.",
    "r2-no-problem-since": "No problem since staged files are checked first.",
    "r2-no-defect-in-how": "There is no defect in how staged changes are checked.",
    "r2-no-regression": "No regression for staged files handling.",
    "r2-does-not-mention": "The docstring does not mention that staged files are checked first.",
    "r2-no-guard-is-needed": "No guard is needed for staged files since reset --soft preserves them.",
    "r2-unlike-the-staged-guard": "squash() does not check the reflog either, unlike the staged guard above it.",
    "r2-before-the-staged-guard-runs": "never checks remote reachability before the staged guard runs",
    "r2-without-checking-whether": "_is_ancestor is called without checking whether the staged base exists.",
    "r2-not-handled-the-way": "The ls-remote failure is not handled the way the staged check is.",
    "r2-without-the-staged-check": "Without the staged check the test still passes, so the test is weak.",
    "r2-no-other-guard-is-needed": "No other guard is needed besides the staged check.",
    "r2-if-there-were-no-guard": "If there were no staged-changes guard, the test would fail.",
    "r2-no-staged-check-is-needed": "No staged check is needed here.",
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
    "guard-is-missing": "The staged-changes guard is missing.",
    "guard-for-staged-is-missing": "The guard for staged changes is missing from squash().",
    "guard-is-absent": "The staged-changes guard is absent.",
    "guard-is-not-implemented": "The staged-changes guard is not implemented.",
    "no-check-comma-anywhere": "There is no check, anywhere in squash(), for staged changes.",
    "never-inspects-the-index": "squash() never inspects the index.",
    "never-looks-at": "squash() never looks at staged changes.",
    "missing-as-negator": "squash() is missing a check for staged changes.",
    "real-b-r1-spec-line-168": "squash() goes directly from the merge-commit check to gathering rev_list here without ever inspecting the index; no such check exists anywhere in the 295-line file.",
    "spec-wording-guard-for": "The guard for staged-but-uncommitted changes is missing.",
    "spec-wording-check-for": "The check for staged-but-uncommitted changes is absent.",
    "was-never-implemented": "The guard for staged changes was never implemented.",
    "does-not-exist": "The check for staged changes does not exist.",
    "was-omitted": "The guard for staged changes was omitted.",
    "forgets-to-check": "squash() forgets to check for staged changes.",
    "backtick-before-the-marker": "There is no `staged` guard.",
    "does-not-run-git-diff-cached": "squash() does not run `git diff --cached`.",
    "never-calls-git-diff-cached-quiet": "squash() never calls `git diff --cached --quiet`.",
    "newline-inside-one-sentence": "squash() has no check\nfor staged changes before the reset.",
    "the-checks-are-missing": "The checks for staged changes are missing.",
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


# --- one sentence per negator word: each must be the only thing that makes its sentence credit ----

NEGATOR_SENTENCES = {
    "no": "There is no check for staged changes.",
    "never": "squash() never checks for staged changes.",
    "not": "squash() is not checking for staged changes.",
    "did-not": "squash() did not check for staged changes.",
    "does-not": "squash() does not check for staged changes.",
    "nowhere": "Nowhere is there any check for staged changes.",
    "without": "Without a check for staged files the reset sweeps them in.",
    "missing": "squash() is missing a check for staged changes.",
    "lacks": "squash() lacks a check for staged changes.",
    "lacking": "squash() is lacking a check for staged changes.",
    "absent": "Absent a check for staged changes, the reset sweeps them in.",
    "omits": "squash() omits the check for staged changes.",
    "omitted": "squash() omitted any check for staged changes.",
    "doesnt": "squash() doesn't check for staged changes.",
    "fails-to": "squash() fails to check for staged changes.",
    "forgets-to": "squash() forgets to check for staged changes.",
}


@pytest.mark.parametrize("text", NEGATOR_SENTENCES.values(), ids=NEGATOR_SENTENCES.keys())
def test_each_negator_word_credits_its_own_sentence(items, predicates, text):
    assert _credits_d5(items, predicates, text) is True


@pytest.mark.parametrize("verb", ["inspects", "looks at", "examines", "consults", "reads"])
def test_each_inspect_verb_credits_never_reading_the_index(items, predicates, verb):
    assert _credits_d5(items, predicates, f"squash() never {verb} the index.") is True


@pytest.mark.parametrize("copula", ["is", "was", "are", "were"])
def test_each_copula_credits_a_guard_that_is_missing(items, predicates, copula):
    text = f"The checks for staged changes {copula} missing."
    assert _credits_d5(items, predicates, text) is True


# --- the bounds: a credit at N, none at N+1 -------------------------------------------------


def _at_bound(items, predicates, template: str, filler: str, bound: int) -> tuple[bool, bool]:
    at = _credits_d5(items, predicates, template.format(filler * bound))
    over = _credits_d5(items, predicates, template.format(filler * (bound + 1)))
    return at, over


def test_shape_one_allows_five_words_between_the_guard_word_and_for(items, predicates):
    assert _at_bound(items, predicates, "There is no check{} for staged changes.", " anywhere", 5) == (True, False)


def test_shape_two_allows_four_qualifiers_between_the_negator_and_the_marker(items, predicates):
    assert _at_bound(items, predicates, "There is no{} staged guard.", " dedicated", 4) == (True, False)


def test_the_negator_to_guard_word_gap_allows_three_words(items, predicates):
    assert _at_bound(items, predicates, "squash() never{} checks for staged changes.", " actually", 3) == (True, False)


def test_shape_one_allows_two_filler_words_after_for(items, predicates):
    assert _at_bound(items, predicates, "There is no check for{} staged changes.", " any", 2) == (True, False)


def test_shape_five_allows_three_words_after_the_marker_phrase(items, predicates):
    assert _at_bound(items, predicates, "The guard for staged changes{} is missing.", " in", 3) == (True, False)
