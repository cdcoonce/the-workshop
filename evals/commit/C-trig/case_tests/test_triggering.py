"""C-trig's triggering item: the rostered skill's Skill call comes before any other work.

The predicate is #992's ``matchers.skill_triggered_first``; these tests import it
from there and drive it, and C-trig's scorer, with synthetic transcripts in the real
envelope shape. Each negative embeds the exact violation it names.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals._harness import matchers
from evals._harness.matchers import skill_triggered_first
from evals._harness.transcript import parse_transcript

SKILL = Path(__file__).resolve().parents[2].name
# In real Claude Code transcripts the Skill call's ``input.skill`` is always plugin-qualified
# (``workbench:<name>``), never the bare name, and ``skill_triggered_first`` compares exactly,
# so the item's param and every positive transcript here use the qualified spelling. A bare
# name or another plugin's copy (``workshop-maintainer:<name>``) is a different string and must
# miss.
QUALIFIED = f"workbench:{SKILL}"
OTHER_SKILL = "workbench:using-workflow"
ANOTHER_SKILL = "workbench:brainstorm"
ENVELOPE_TYPES = {"user", "assistant", "attachment"}
PROMPT = "Check in the changes in my working tree and write a good message."
FINAL = "Done: the changes are saved."
READ = ("tool", "Read", {"file_path": "src/greeter/format.py"})
BASH = ("tool", "Bash", {"command": "git status"})
EDIT = ("tool", "Edit", {"file_path": "src/greeter/format.py", "old_string": "a", "new_string": "b"})
SEARCH = ("tool", "ToolSearch", {"query": "select:Read"})

POSITIVE = {
    "skill_then_work_then_final_text": [
        ("prompt", PROMPT),
        ("attachment",),
        ("say", "I'll start by loading the right skill."),
        ("skill", QUALIFIED),
        READ,
        BASH,
        ("say", FINAL),
    ],
    "skill_is_the_only_tool_call": [("prompt", PROMPT), ("skill", QUALIFIED), ("say", FINAL)],
    "skill_called_twice_the_first_call_counts": [
        ("prompt", PROMPT),
        ("skill", QUALIFIED),
        READ,
        ("skill", QUALIFIED),
        ("say", FINAL),
    ],
    "toolsearch_and_another_skill_may_come_first": [
        ("prompt", PROMPT),
        SEARCH,
        ("skill", OTHER_SKILL),
        SEARCH,
        ("skill", QUALIFIED),
        READ,
        ("say", FINAL),
    ],
}

NEGATIVE = {
    "bash_runs_before_the_skill_call": [("prompt", PROMPT), BASH, ("skill", QUALIFIED), ("say", FINAL)],
    "read_runs_before_the_skill_call": [("prompt", PROMPT), READ, ("skill", QUALIFIED), READ, ("say", FINAL)],
    "edit_runs_before_the_skill_call": [("prompt", PROMPT), EDIT, ("skill", QUALIFIED), ("say", FINAL)],
    "skill_call_is_the_last_tool_call_of_many": [
        ("prompt", PROMPT),
        READ,
        BASH,
        EDIT,
        ("skill", QUALIFIED),
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
    "only_a_different_qualified_skill_is_called_first": [
        ("prompt", PROMPT),
        ("skill", ANOTHER_SKILL),
        ("say", FINAL),
    ],
    "only_the_bare_name_is_called": [("prompt", PROMPT), ("skill", SKILL), ("say", FINAL)],
    "only_the_other_plugins_copy_is_called": [
        ("prompt", PROMPT),
        ("skill", f"workshop-maintainer:{SKILL}"),
        ("say", FINAL),
    ],
    "skill_call_named_differently_suffix": [("prompt", PROMPT), ("skill", f"workbench:{SKILL}-lite"), ("say", FINAL)],
    "skill_call_named_differently_case": [("prompt", PROMPT), ("skill", f"workbench:{SKILL.upper()}"), ("say", FINAL)],
    "skill_call_named_differently_prefix": [("prompt", PROMPT), ("skill", f"workbench:my-{SKILL}"), ("say", FINAL)],
    "skill_call_arrives_after_the_final_text": [("prompt", PROMPT), ("say", FINAL), ("skill", QUALIFIED)],
    "skill_call_after_text_with_no_tools_before_it": [
        ("prompt", PROMPT),
        ("say", "All done, nothing left to do here."),
        ("skill", QUALIFIED),
    ],
}


# Negatives whose only defect is the Skill call's name: flipping that name to the rostered
# qualified one must make the very same transcript hit, or the negative proves nothing about names.
NAME_ONLY_NEGATIVES = {
    "only_a_different_qualified_skill_is_called_first": ANOTHER_SKILL,
    "only_the_bare_name_is_called": SKILL,
    "only_the_other_plugins_copy_is_called": f"workshop-maintainer:{SKILL}",
    "skill_call_for_a_different_skill_only": OTHER_SKILL,
    "skill_call_named_differently_suffix": f"workbench:{SKILL}-lite",
    "skill_call_named_differently_case": f"workbench:{SKILL.upper()}",
    "skill_call_named_differently_prefix": f"workbench:my-{SKILL}",
}


def _real_shape_transcript(tmp_path, skill_name: str) -> Path:
    """A minimal subagent transcript copied from the shape of real Claude Code lines.

    The Skill ``tool_use`` block carries ``input.skill`` (plus ``args``) and a ``caller``
    key, inside an ``assistant`` line that also carries the envelope fields real lines have.
    """
    envelope = {"isSidechain": True, "userType": "external", "sessionId": "s-1", "agentId": "a-1"}
    lines = [
        {
            **envelope,
            "parentUuid": None,
            "type": "user",
            "message": {"role": "user", "content": "Check in the changes in my working tree and write a good message."},
            "uuid": "u-1",
            "timestamp": "2026-10-01T10:00:01.000Z",
        },
        {
            **envelope,
            "parentUuid": "u-1",
            "type": "assistant",
            "message": {
                "model": "claude-sonnet-5-5",
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_skill",
                        "name": "Skill",
                        "input": {"skill": skill_name, "args": ""},
                        "caller": {"type": "direct"},
                    }
                ],
                "stop_reason": "tool_use",
            },
            "uuid": "u-2",
            "timestamp": "2026-10-01T10:00:02.000Z",
        },
        {
            **envelope,
            "parentUuid": "u-2",
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_skill",
                        "content": f"Launching skill: {skill_name}",
                        "is_error": False,
                    }
                ],
            },
            "uuid": "u-3",
            "timestamp": "2026-10-01T10:00:03.000Z",
        },
        {
            **envelope,
            "parentUuid": "u-3",
            "type": "assistant",
            "message": {
                "model": "claude-sonnet-5-5",
                "id": "msg_2",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "text", "text": "Done: the changes are saved."}],
                "stop_reason": "end_turn",
            },
            "uuid": "u-4",
            "timestamp": "2026-10-01T10:00:04.000Z",
        },
    ]
    path = tmp_path / "real-shape.jsonl"
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")
    return path


def _scorer_result(predicates, case_toml, evidence_for, transcript) -> bool:
    item = case_toml["items"][0]
    return getattr(predicates, item["scorer"])(evidence_for(transcript), **item.get("params", {}))


def test_the_predicate_the_scorer_uses_is_the_harness_predicate_not_a_copy(predicates):
    assert predicates.skill_triggered_first is matchers.skill_triggered_first
    assert skill_triggered_first is matchers.skill_triggered_first


@pytest.mark.parametrize("name", sorted(POSITIVE))
def test_predicate_is_true_when_the_skill_call_precedes_every_other_tool_call_and_the_final_text(parse, name):
    assert skill_triggered_first(parse(POSITIVE[name]), QUALIFIED) is True


@pytest.mark.parametrize("name", sorted(NEGATIVE))
def test_predicate_is_false_on_a_transcript_that_violates_the_order(parse, name):
    assert skill_triggered_first(parse(NEGATIVE[name]), QUALIFIED) is False


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


def test_item_param_is_the_plugin_qualified_name_real_transcripts_carry(case_toml):
    assert case_toml["items"][0]["params"] == {"skill": QUALIFIED}


@pytest.mark.parametrize("name", sorted(NAME_ONLY_NEGATIVES))
def test_a_name_only_negative_hits_once_the_name_is_flipped_to_the_rostered_skill(parse, name):
    flipped = [
        (step[0], QUALIFIED) if step[0] == "skill" and step[1] == NAME_ONLY_NEGATIVES[name] else step
        for step in NEGATIVE[name]
    ]
    assert flipped != NEGATIVE[name]
    assert skill_triggered_first(parse(flipped), QUALIFIED) is True


def test_a_real_shape_qualified_skill_line_is_scored_a_hit(tmp_path, predicates, case_toml, evidence_for):
    transcript = parse_transcript(_real_shape_transcript(tmp_path, QUALIFIED))
    assert transcript.status == "complete"
    assert [event.name for event in transcript.events] == ["Skill"]
    assert _scorer_result(predicates, case_toml, evidence_for, transcript) is True


@pytest.mark.parametrize("name", [SKILL, f"workshop-maintainer:{SKILL}"])
def test_a_real_shape_line_with_the_bare_or_other_plugins_name_is_scored_a_miss(
    tmp_path, predicates, case_toml, evidence_for, name
):
    transcript = parse_transcript(_real_shape_transcript(tmp_path, name))
    assert _scorer_result(predicates, case_toml, evidence_for, transcript) is False
