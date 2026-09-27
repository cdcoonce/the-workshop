"""Tests for evals._harness.scorer — classification, retry, and verdict rules."""

from __future__ import annotations

import pytest

from evals._harness.scorer import Attempt, classify_attempt, compute_verdict, should_retry


def test_classify_attempt_scores_hits_and_misses_on_a_complete_parsed_transcript():
    attempt = classify_attempt(
        transcript_status="complete",
        envelope_parsed=True,
        item_hits={"item-a": True, "item-b": False},
    )
    assert attempt == Attempt(
        classification="counted",
        item_hits={"item-a": "hit", "item-b": "miss"},
        parse_error=False,
    )


@pytest.mark.parametrize(
    "transcript_status", ["dispatch_error", "missing", "truncated", "api_error"]
)
def test_classify_attempt_harness_breakage_is_indeterminate_for_every_item(transcript_status):
    attempt = classify_attempt(
        transcript_status=transcript_status,
        envelope_parsed=True,
        item_hits={"item-a": True, "item-b": False},
    )
    assert attempt == Attempt(
        classification="indeterminate",
        item_hits={"item-a": "indeterminate", "item-b": "indeterminate"},
        parse_error=False,
    )


def test_classify_attempt_complete_but_unparsed_envelope_is_a_miss_with_parse_error():
    attempt = classify_attempt(
        transcript_status="complete",
        envelope_parsed=False,
        item_hits={"item-a": True, "item-b": False},
    )
    assert attempt == Attempt(
        classification="counted",
        item_hits={"item-a": "miss", "item-b": "miss"},
        parse_error=True,
    )


def test_should_retry_true_while_an_item_is_unmet_and_under_both_caps():
    assert should_retry(
        item_states={"item-a": True, "item-b": False},
        counted_attempts=1,
        reserve_used=0,
    ) is True


def test_should_retry_false_once_every_item_is_met():
    assert should_retry(
        item_states={"item-a": True, "item-b": True},
        counted_attempts=1,
        reserve_used=0,
    ) is False


def test_should_retry_false_at_three_counted_attempts_even_with_reserve_left():
    assert should_retry(
        item_states={"item-a": False},
        counted_attempts=3,
        reserve_used=0,
    ) is False


def test_should_retry_false_at_the_five_execution_total_cap():
    assert should_retry(
        item_states={"item-a": False},
        counted_attempts=2,
        reserve_used=3,
    ) is False


def test_should_retry_true_below_both_caps_with_reserve_already_drawn():
    assert should_retry(
        item_states={"item-a": False},
        counted_attempts=2,
        reserve_used=2,
    ) is True


def test_compute_verdict_green_when_every_gated_item_is_hit():
    verdict = compute_verdict(
        {
            "item-a": (True, ["miss", "hit"]),
            "item-b": (True, ["hit"]),
        }
    )
    assert verdict == "green"


def test_compute_verdict_red_when_a_gated_item_missed_all_three_counted_attempts():
    verdict = compute_verdict(
        {
            "item-a": (True, ["miss", "miss", "miss"]),
            "item-b": (True, ["hit"]),
        }
    )
    assert verdict == "red"


def test_compute_verdict_void_when_a_gated_item_is_indeterminate_after_the_reserve_is_exhausted():
    verdict = compute_verdict(
        {
            "item-a": (True, ["miss", "indeterminate", "indeterminate"]),
            "item-b": (True, ["hit"]),
        }
    )
    assert verdict == "void"


def test_compute_verdict_trend_item_ending_indeterminate_does_not_void_the_run():
    verdict = compute_verdict(
        {
            "item-a": (True, ["hit"]),
            "item-b": (False, ["miss", "indeterminate", "indeterminate"]),
        }
    )
    assert verdict == "green"


def test_compute_verdict_red_takes_precedence_over_void():
    verdict = compute_verdict(
        {
            "item-a": (True, ["miss", "miss", "miss"]),
            "item-b": (True, ["miss", "indeterminate", "indeterminate"]),
        }
    )
    assert verdict == "red"
