"""A3's triggering item: the rostered skill's Skill call comes before any other work.

The predicate is #992's ``matchers.skill_triggered_first``; these tests import it
from there and drive it, and A3's scorer, with synthetic transcripts in the real
envelope shape. Each negative embeds the exact violation it names.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals._harness import matchers
from evals._harness.matchers import skill_triggered_first

SKILL = Path(__file__).resolve().parents[2].name
OTHER_SKILL = "using-workflow"
ENVELOPE_TYPES = {"user", "assistant", "attachment"}
PROMPT = "Check this branch over before I merge it."
FINAL = "Done: here is what I found."
READ = ("tool", "Read", {"file_path": "src/settlement/rounding.py"})
BASH = ("tool", "Bash", {"command": "git log --oneline"})
EDIT = ("tool", "Edit", {"file_path": "src/settlement/rounding.py", "old_string": "a", "new_string": "b"})
SEARCH = ("tool", "ToolSearch", {"query": "select:Read"})

POSITIVE = {
    "skill_then_work_then_final_text": [
        ("prompt", PROMPT),
        ("attachment",),
        ("say", "I'll start by loading the right skill."),
        ("skill", SKILL),
        READ,
        BASH,
        ("say", FINAL),
    ],
    "skill_is_the_only_tool_call": [("prompt", PROMPT), ("skill", SKILL), ("say", FINAL)],
    "skill_called_twice_the_first_call_counts": [
        ("prompt", PROMPT),
        ("skill", SKILL),
        READ,
        ("skill", SKILL),
        ("say", FINAL),
    ],
    "toolsearch_and_another_skill_may_come_first": [
        ("prompt", PROMPT),
        SEARCH,
        ("skill", OTHER_SKILL),
        SEARCH,
        ("skill", SKILL),
        READ,
        ("say", FINAL),
    ],
}

NEGATIVE = {
    "bash_runs_before_the_skill_call": [("prompt", PROMPT), BASH, ("skill", SKILL), ("say", FINAL)],
    "read_runs_before_the_skill_call": [("prompt", PROMPT), READ, ("skill", SKILL), READ, ("say", FINAL)],
    "edit_runs_before_the_skill_call": [("prompt", PROMPT), EDIT, ("skill", SKILL), ("say", FINAL)],
    "skill_call_is_the_last_tool_call_of_many": [
        ("prompt", PROMPT),
        READ,
        BASH,
        EDIT,
        ("skill", SKILL),
        ("say", FINAL),
    ],
    "no_skill_call_at_all": [("prompt", PROMPT), READ, BASH, ("say", FINAL)],
    "toolsearch_only": [("prompt", PROMPT), SEARCH, ("say", FINAL)],
    "no_tool_calls_just_a_reply": [("prompt", PROMPT), ("say", FINAL)],
    "nothing_but_the_prompt": [("prompt", PROMPT)],
    "skill_call_for_a_different_skill_only": [
        ("prompt", PROMPT),
        ("skill", OTHER_SKILL),
        READ,
        ("say", FINAL),
    ],
    "different_skill_first_then_work_never_the_rostered_one": [
        ("prompt", PROMPT),
        ("skill", OTHER_SKILL),
        BASH,
        ("skill", f"{SKILL}-lite"),
        ("say", FINAL),
    ],
    "skill_call_named_differently_suffix": [("prompt", PROMPT), ("skill", f"{SKILL}-lite"), ("say", FINAL)],
    "skill_call_named_differently_case": [("prompt", PROMPT), ("skill", SKILL.upper()), ("say", FINAL)],
    "skill_call_named_differently_prefix": [("prompt", PROMPT), ("skill", f"my-{SKILL}"), ("say", FINAL)],
    "skill_call_arrives_after_the_final_text": [("prompt", PROMPT), ("say", FINAL), ("skill", SKILL)],
    "skill_call_after_text_with_no_tools_before_it": [
        ("prompt", PROMPT),
        ("say", "Looks fine to me, ready to merge."),
        ("skill", SKILL),
    ],
}


def _scorer_result(predicates, case_toml, evidence_for, transcript) -> bool:
    item = case_toml["items"][0]
    return getattr(predicates, item["scorer"])(evidence_for(transcript), **item.get("params", {}))


def test_the_predicate_the_scorer_uses_is_the_harness_predicate_not_a_copy(predicates):
    assert predicates.skill_triggered_first is matchers.skill_triggered_first
    assert skill_triggered_first is matchers.skill_triggered_first


@pytest.mark.parametrize("name", sorted(POSITIVE))
def test_predicate_is_true_when_the_skill_call_precedes_every_other_tool_call_and_the_final_text(parse, name):
    assert skill_triggered_first(parse(POSITIVE[name]), SKILL) is True


@pytest.mark.parametrize("name", sorted(NEGATIVE))
def test_predicate_is_false_on_a_transcript_that_violates_the_order(parse, name):
    assert skill_triggered_first(parse(NEGATIVE[name]), SKILL) is False


@pytest.mark.parametrize("name", sorted(POSITIVE))
def test_scorer_credits_a_transcript_where_the_skill_triggered_first(
    parse, predicates, case_toml, evidence_for, name
):
    assert _scorer_result(predicates, case_toml, evidence_for, parse(POSITIVE[name])) is True


@pytest.mark.parametrize("name", sorted(NEGATIVE))
def test_scorer_never_credits_a_transcript_that_violates_the_order(
    parse, predicates, case_toml, evidence_for, name
):
    assert _scorer_result(predicates, case_toml, evidence_for, parse(NEGATIVE[name])) is False


def test_scorer_does_not_credit_an_attempt_with_no_transcript(predicates, case_toml, evidence_for):
    item = case_toml["items"][0]
    assert getattr(predicates, item["scorer"])(evidence_for(), **item.get("params", {})) is False


def test_scorer_does_not_credit_a_second_transcript_that_rides_along(
    parse, predicates, case_toml, evidence_for
):
    """A subagent case has exactly one transcript; a stray extra one must not rescue a miss."""
    item = case_toml["items"][0]
    hit = parse(POSITIVE["skill_is_the_only_tool_call"])
    miss = parse(NEGATIVE["no_skill_call_at_all"])
    scorer = getattr(predicates, item["scorer"])
    assert scorer(evidence_for(miss, hit), **item.get("params", {})) is False
    assert scorer(evidence_for(hit, miss), **item.get("params", {})) is False


def test_scorer_returns_a_plain_bool(parse, predicates, case_toml, evidence_for):
    result = _scorer_result(predicates, case_toml, evidence_for, parse(POSITIVE["skill_is_the_only_tool_call"]))
    assert type(result) is bool


@pytest.mark.parametrize("name", sorted({**POSITIVE, **NEGATIVE}))
def test_synthetic_transcripts_are_in_the_real_envelope_shape(write_transcript, name):
    steps = {**POSITIVE, **NEGATIVE}[name]
    lines = [json.loads(line) for line in write_transcript(steps).read_text(encoding="utf-8").splitlines()]
    assert lines, name
    for line in lines:
        assert line["type"] in ENVELOPE_TYPES
        if line["type"] == "attachment":
            continue
        assert isinstance(line["message"]["content"], (list, str))
    calls = {}
    for line in lines:
        content = line["message"]["content"] if line["type"] != "attachment" else []
        if line["type"] == "assistant":
            for block in content:
                assert block["type"] in {"tool_use", "text"}
                if block["type"] == "tool_use":
                    assert set(block) == {"type", "id", "name", "input"}
                    calls[block["id"]] = line
        elif line["type"] == "user" and isinstance(content, list):
            for block in content:
                if block["type"] == "tool_result":
                    assert set(block) == {"type", "tool_use_id", "is_error", "content"}
                    assert block["tool_use_id"] in calls, "a result must follow its call"
