"""Tests for evals._harness.matchers — review matching and ordering predicates."""

from __future__ import annotations

import json

import pytest

from evals._harness import matchers
from evals._harness.matchers import (
    count_unmatched,
    extract_findings,
    precedes,
    review_match,
    skill_triggered_first,
    test_failed_before_first_source_write as _failed_before_first_source_write,
)
from evals._harness.transcript import ToolCallEvent, ToolResult, parse_transcript


def _event(name: str, input_: dict, ordinal: int, *, content: str | None = None, is_error: bool = False) -> ToolCallEvent:
    result = None if content is None else ToolResult(content=content, is_error=is_error)
    return ToolCallEvent(name=name, input=input_, result=result, ordinal=ordinal, timestamp=None)


# --- review_match (conjunctive matcher) --------------------------------


def test_review_match_location_only_does_not_credit_the_item():
    finding = {"file": "src/foo.py", "line": 12, "description": "unrelated text"}
    assert (
        review_match(finding, file_suffix="foo.py", regex="race condition", line_window=[10, 15])
        is False
    )


def test_review_match_regex_only_does_not_credit_the_item():
    finding = {"file": "src/other.py", "line": 12, "description": "a race condition here"}
    assert (
        review_match(finding, file_suffix="foo.py", regex="race condition", line_window=[10, 15])
        is False
    )


def test_review_match_both_location_and_regex_credit_the_item():
    finding = {"file": "src/foo.py", "line": 12, "description": "a race condition here"}
    assert (
        review_match(finding, file_suffix="foo.py", regex="race condition", line_window=[10, 15])
        is True
    )


def test_review_match_file_suffix_only_variant_requires_regex_too():
    finding = {"file": "src/foo.py", "line": 999, "description": "unrelated text"}
    assert review_match(finding, file_suffix="foo.py", regex="race condition", line_window=None) is False


def test_review_match_file_suffix_only_variant_credits_when_regex_also_hits():
    finding = {"file": "src/foo.py", "line": 999, "description": "a race condition here"}
    assert review_match(finding, file_suffix="foo.py", regex="race condition", line_window=None) is True


def test_review_match_file_suffix_only_variant_requires_the_suffix_too():
    finding = {"file": "src/other.py", "line": 999, "description": "a race condition here"}
    assert review_match(finding, file_suffix="foo.py", regex="race condition", line_window=None) is False


# --- extract_findings ----------------------------------------------------


def test_extract_findings_returns_empty_and_false_when_unparseable():
    findings, ok = extract_findings("no json here at all")
    assert findings == []
    assert ok is False


def test_extract_findings_parses_fenced_json_block():
    text = 'prose\n```json\n{"findings": [{"file": "a.py", "line": 1, "description": "d"}]}\n```\n'
    findings, ok = extract_findings(text)
    assert ok is True
    assert findings == [{"file": "a.py", "line": 1, "description": "d"}]


def test_extract_findings_parses_bare_brace_span():
    text = 'prose before {"findings": [{"file": "a.py"}]} prose after'
    findings, ok = extract_findings(text)
    assert ok is True
    assert findings == [{"file": "a.py"}]


# --- count_unmatched -------------------------------------------------------


def test_count_unmatched_counts_findings_crediting_no_item():
    items = [{"file_suffix": "foo.py", "regex": "race condition", "line_window": [10, 15]}]
    findings = [
        {"file": "src/foo.py", "line": 12, "description": "a race condition here"},
        {"file": "src/foo.py", "line": 13, "description": "a race condition here too"},
        {"file": "src/bar.py", "line": 1, "description": "unrelated"},
    ]
    assert count_unmatched(findings, items) == 1


# --- precedes ---------------------------------------------------------------


def _is_make_test(event: ToolCallEvent) -> bool:
    return event.name == "Bash" and "make test" in event.input.get("command", "")


def _is_git_add(event: ToolCallEvent) -> bool:
    return event.name == "Bash" and "git add" in event.input.get("command", "")


def test_precedes_true_when_first_event_comes_first():
    events = [
        _event("Bash", {"command": "make test"}, 0),
        _event("Bash", {"command": "git add ."}, 1),
    ]
    assert precedes(events, _is_make_test, _is_git_add) is True


def test_precedes_false_when_then_event_comes_first():
    events = [
        _event("Bash", {"command": "git add ."}, 0),
        _event("Bash", {"command": "make test"}, 1),
    ]
    assert precedes(events, _is_make_test, _is_git_add) is False


def test_precedes_false_when_either_event_never_occurs():
    events = [_event("Bash", {"command": "make test"}, 0)]
    assert precedes(events, _is_make_test, _is_git_add) is False
    events2 = [_event("Bash", {"command": "git add ."}, 0)]
    assert precedes(events2, _is_make_test, _is_git_add) is False


# --- the red-result marker read by test_failed_before_first_source_write -------


def _red_then_source(content: str, *, tool: str = "Bash") -> list[ToolCallEvent]:
    # A test write (ordinal 0), the candidate red result (1), then a source write (2).
    return [
        _event("Edit", {"file_path": "tests/test_new.py"}, 0),
        _event(tool, {"command": "pytest"} if tool == "Bash" else {"file_path": "log.txt"}, 1, content=content),
        _event("Edit", {"file_path": "src/foo.py"}, 2),
    ]


def test_a_failed_line_is_a_red_result():
    assert _failed_before_first_source_write(_red_then_source("FAILED tests/test_new.py::test_x - boom")) is True


def test_an_error_line_is_a_red_result():
    assert _failed_before_first_source_write(_red_then_source("ERROR collecting tests/test_new.py")) is True


def test_an_error_during_collection_substring_is_a_red_result():
    assert _failed_before_first_source_write(_red_then_source("noise\nerror during collection\nmore noise")) is True


def test_a_passing_run_is_not_a_red_result():
    assert _failed_before_first_source_write(_red_then_source("1 passed")) is False


def test_failure_text_in_a_non_bash_tool_result_is_not_a_red_result():
    events = _red_then_source("FAILED tests/test_foo.py::test_x", tool="Read")
    assert _failed_before_first_source_write(events) is False


def test_a_malformed_transcript_is_truncated_not_a_verdict(tmp_path):
    path = tmp_path / "agent-transcript.jsonl"
    path.write_text(
        json.dumps({"type": "assistant", "message": {"model": "m1", "content": []}})
        + "\n"
        + "not valid json\n"
    )
    transcript = parse_transcript(path)
    assert transcript.status == "truncated"


# --- one rule for write paths ------------------------------------------------


@pytest.mark.parametrize("name", ["_is_test_path", "_is_source_edit", "test_failed_before_first_source_edit"])
def test_the_legacy_path_classifier_chain_is_retired(name):
    # #1131: a second path classifier disagreed with ``classify_write_event`` on absolute paths
    # with a ``tests`` directory above ``src``. ``classify_write_event`` is the only rule.
    assert not hasattr(matchers, name)


# --- skill_triggered_first ---------------------------------------------------


def _transcript_with_events(events: list[ToolCallEvent], final_text_ordinal: int | None):
    from evals._harness.transcript import Transcript

    return Transcript(
        status="complete",
        events=events,
        model_ids=[],
        final_text="done",
        final_text_ordinal=final_text_ordinal,
    )


def test_skill_triggered_first_met_when_earliest_and_precedes_everything():
    events = [
        _event("Skill", {"skill": "tdd"}, 0),
        _event("Bash", {"command": "ls"}, 1),
    ]
    transcript = _transcript_with_events(events, final_text_ordinal=2)
    assert skill_triggered_first(transcript, "tdd") is True


def test_skill_triggered_first_unmet_when_skill_never_called():
    events = [_event("Bash", {"command": "ls"}, 0)]
    transcript = _transcript_with_events(events, final_text_ordinal=1)
    assert skill_triggered_first(transcript, "tdd") is False


def test_skill_triggered_first_unmet_when_a_non_skill_tool_call_precedes_it():
    events = [
        _event("Bash", {"command": "ls"}, 0),
        _event("Skill", {"skill": "tdd"}, 1),
    ]
    transcript = _transcript_with_events(events, final_text_ordinal=2)
    assert skill_triggered_first(transcript, "tdd") is False


def test_skill_triggered_first_exemption_not_narrowed_to_rostered_skill_only():
    events = [
        _event("Skill", {"skill": "using-workflow"}, 0),
        _event("ToolSearch", {"query": "select:Read"}, 1),
        _event("Skill", {"skill": "tdd"}, 2),
        _event("Bash", {"command": "ls"}, 3),
    ]
    transcript = _transcript_with_events(events, final_text_ordinal=4)
    assert skill_triggered_first(transcript, "tdd") is True


def test_skill_triggered_first_unmet_when_final_text_precedes_the_skill_call():
    events = [_event("Skill", {"skill": "tdd"}, 5)]
    transcript = _transcript_with_events(events, final_text_ordinal=0)
    assert skill_triggered_first(transcript, "tdd") is False


def test_skill_triggered_first_unmet_when_trigger_ordinal_equals_final_text_ordinal():
    events = [_event("Skill", {"skill": "tdd"}, 3)]
    transcript = _transcript_with_events(events, final_text_ordinal=3)
    assert skill_triggered_first(transcript, "tdd") is False
