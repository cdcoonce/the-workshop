"""Tests for the T1 gate candidate and the T2/T3 trend scorers in predicates.py.

Every scorer is exercised over synthetic transcripts in the real envelope shape
and over hand-built end-state mappings, never over a live repo.
"""

from __future__ import annotations

import pytest

from evals._harness import matchers

TAUTOLOGY = "assert subtotal_cents(items) == subtotal_cents(items)"
TEST_CART = "/work/shop/tests/test_cart.py"
SRC_CART = "/work/shop/src/shop/cart.py"
RED = "F\nFAILED tests/test_cart.py::test_x - assert 1 == 2\n1 failed, 4 passed in 0.02s\n"
GREEN = ".....\n5 passed in 0.01s\n"


@pytest.fixture
def t1(predicates, evidence_for):
    def score(stem_or_transcript, end_state):
        return predicates.t1_test_first_and_effective(evidence_for(stem_or_transcript, end_state))

    return score


@pytest.fixture
def evidence_for(load_transcript, make_evidence):
    def build(stem_or_transcript, end_state):
        transcript = (
            load_transcript(stem_or_transcript) if isinstance(stem_or_transcript, str) else stem_or_transcript
        )
        return make_evidence([transcript], end_state)

    return build


# ---------------------------------------------------------------- T1: all four hold


def test_t1_hits_when_all_four_conjuncts_hold(t1, make_snapshot):
    assert t1("disciplined_two_cycles", make_snapshot()) is True


# ---------------------------------------------------------------- T1 conjunct 1


def test_t1_misses_when_source_is_edited_before_any_test_failed(t1, make_snapshot):
    # Conjuncts 2-4 all hold; only the ordering fails.
    assert t1("source_first", make_snapshot()) is False


def test_t1_first_conjunct_is_delegated_to_the_harness_ordering_predicate(
    monkeypatch, t1, make_snapshot
):
    # A local re-implementation would ignore the harness predicate entirely.
    monkeypatch.setattr(matchers, "test_failed_before_first_source_edit", lambda events: False)
    assert t1("disciplined_two_cycles", make_snapshot()) is False
    monkeypatch.setattr(matchers, "test_failed_before_first_source_edit", lambda events: True)
    assert t1("source_first", make_snapshot()) is True


def test_t1_first_conjunct_receives_the_case_agents_events(
    monkeypatch, t1, make_snapshot, load_transcript
):
    seen = []

    def spy(events):
        seen.append(events)
        return True

    monkeypatch.setattr(matchers, "test_failed_before_first_source_edit", spy)
    transcript = load_transcript("disciplined_two_cycles")
    t1(transcript, make_snapshot())
    assert seen == [transcript.events]


def test_t1_misses_for_a_transcript_with_no_events(t1, make_snapshot, load_transcript):
    assert t1(load_transcript("does_nothing"), make_snapshot()) is False


def test_t1_misses_without_any_transcript(predicates, make_evidence, make_snapshot):
    assert predicates.t1_test_first_and_effective(make_evidence([], make_snapshot())) is False


# ---------------------------------------------------------------- T1 conjunct 2


def test_t1_misses_when_no_edit_landed_under_src(t1, make_snapshot):
    edited = [{"path": "tests/test_cart.py", "timestamp": None}]
    assert t1("disciplined_two_cycles", make_snapshot(edited=edited)) is False


def test_t1_misses_when_nothing_was_edited(t1, make_snapshot):
    assert t1("disciplined_two_cycles", make_snapshot(edited=[])) is False


@pytest.mark.parametrize(
    "path",
    [
        "src",
        "src/",
        "docs/src/shop/cart.py",
        "source/shop/cart.py",
        "tests/src/test_cart.py",
        "../src/shop/cart.py",
        "src/../tests/test_cart.py",
        "/work/shop/src/shop/cart.py",
        "",
    ],
)
def test_t1_edit_under_src_means_a_relative_path_inside_the_src_tree(t1, make_snapshot, path):
    edited = [{"path": path, "timestamp": None}]
    assert t1("disciplined_two_cycles", make_snapshot(edited=edited)) is False


@pytest.mark.parametrize("path", ["src/shop/cart.py", "src/new_module.py", "./src/shop/checkout.py"])
def test_t1_any_one_edit_under_src_is_enough(t1, make_snapshot, path):
    edited = [{"path": "tests/test_cart.py", "timestamp": None}, {"path": path, "timestamp": None}]
    assert t1("disciplined_two_cycles", make_snapshot(edited=edited)) is True


@pytest.mark.parametrize("raw", ["", "not json", "{}", '{"path": "src/a.py"}', "[1, 2]", '[{"nope": 1}]'])
def test_t1_misses_on_a_missing_or_malformed_edited_paths_file(t1, make_snapshot, raw):
    end_state = make_snapshot()
    end_state["edited-paths.json"] = raw
    assert t1("disciplined_two_cycles", end_state) is False


def test_t1_misses_when_edited_paths_file_is_absent(t1, make_snapshot):
    end_state = make_snapshot()
    del end_state["edited-paths.json"]
    assert t1("disciplined_two_cycles", end_state) is False


# ---------------------------------------------------------------- T1 conjunct 3


def test_t1_misses_when_the_final_suite_fails(t1, make_snapshot):
    assert t1("disciplined_two_cycles", make_snapshot(final_exit=1)) is False


def test_t1_misses_when_the_final_suite_snapshot_is_absent(t1, make_snapshot):
    assert t1("disciplined_two_cycles", make_snapshot(final_exit=None)) is False


@pytest.mark.parametrize(
    "text",
    [
        "5 passed in 0.01s\n",
        "exit=0\nFAILED tests/test_cart.py::test_x\n",
        "exit=zero\n",
        "exit=\n",
        "",
        "5 passed\nexit=0 \nstray\n",
        "5 passed\nexit=0 done\n",
        "5 passed\nlast exit=0\n",
        "5 passed\nexit=0;\n",
    ],
)
def test_t1_final_suite_needs_exit_zero_as_the_last_line(t1, make_snapshot, text):
    end_state = make_snapshot()
    end_state["pytest-final.txt"] = text
    assert t1("disciplined_two_cycles", end_state) is False


def test_t1_final_exit_zero_tolerates_trailing_blank_lines(t1, make_snapshot):
    end_state = make_snapshot()
    end_state["pytest-final.txt"] = "5 passed in 0.01s\nexit=0\n\n"
    assert t1("disciplined_two_cycles", end_state) is True


def test_t1_final_exit_must_be_exactly_zero(t1, make_snapshot):
    end_state = make_snapshot()
    end_state["pytest-final.txt"] = "5 passed\nexit=10\n"
    assert t1("disciplined_two_cycles", end_state) is False


# ---------------------------------------------------------------- T1 conjunct 4


def test_t1_misses_when_reverting_src_changes_nothing(t1, make_snapshot):
    # The tests pass without the source change: they pin nothing.
    assert t1("disciplined_two_cycles", make_snapshot(reverted_exit=0)) is False


def test_t1_misses_when_the_reverted_snapshot_is_absent(t1, make_snapshot):
    assert t1("disciplined_two_cycles", make_snapshot(reverted_exit=None)) is False


@pytest.mark.parametrize("code", [1, 2, 5, 124])
def test_t1_any_nonzero_reverted_exit_counts_as_a_failing_final_test(t1, make_snapshot, code):
    assert t1("disciplined_two_cycles", make_snapshot(reverted_exit=code)) is True


@pytest.mark.parametrize(
    "text",
    [
        "",
        "1 failed\n",
        "1 failed\nexit=\n",
        "exit=1\n1 failed\n",
        "exit=abc\n",
        "1 failed\nexit=1 done\n",
        "1 failed\nlast exit=1\n",
    ],
)
def test_t1_reverted_run_needs_a_parsable_exit_line_last(t1, make_snapshot, text):
    end_state = make_snapshot()
    end_state["pytest-src-reverted.txt"] = text
    assert t1("disciplined_two_cycles", end_state) is False


# ---------------------------------------------------------------- T1 whole-attempt shapes


def test_t1_misses_an_agent_that_does_nothing(t1, make_snapshot):
    # No edits, no test runs: the base suite is green and reverting src to the base changes nothing.
    do_nothing = make_snapshot(final_exit=0, reverted_exit=0, edited=[])
    assert t1("does_nothing", do_nothing) is False


def test_t1_misses_an_agent_that_only_asks_for_approval(t1, make_snapshot):
    assert t1("asks_for_approval", make_snapshot(final_exit=0, reverted_exit=0, edited=[])) is False


def test_t1_misses_an_agent_that_writes_a_failing_test_and_stops(t1, make_snapshot):
    edited = [{"path": "tests/test_cart.py", "timestamp": None}]
    stopped = make_snapshot(final_exit=1, reverted_exit=1, edited=edited)
    assert t1("test_then_stop", stopped) is False


def test_t1_the_do_nothing_agent_misses_even_when_only_the_final_suite_is_green(t1, make_snapshot):
    # The base suite is green, so a gate built only from "the suite passes" would credit this.
    assert t1("does_nothing", make_snapshot(final_exit=0, reverted_exit=0, edited=[])) is False
    assert t1("does_nothing", make_snapshot()) is False


def test_t1_reads_only_end_state_and_transcripts(predicates, make_evidence, make_snapshot, load_transcript, tmp_path):
    transcript = load_transcript("disciplined_two_cycles")
    with_workdir = make_evidence([transcript], make_snapshot(), workdir=tmp_path / "does-not-exist")
    without_workdir = make_evidence([transcript], make_snapshot(), workdir=None)
    assert predicates.t1_test_first_and_effective(with_workdir) is True
    assert predicates.t1_test_first_and_effective(without_workdir) is True


def test_t1_ignores_params(predicates, make_evidence, make_snapshot, load_transcript):
    evidence = make_evidence([load_transcript("disciplined_two_cycles")], make_snapshot())
    assert predicates.t1_test_first_and_effective(evidence, unused=1) is True


# ---------------------------------------------------------------- T2


@pytest.mark.parametrize(
    ("stem", "expected"),
    [
        ("disciplined_two_cycles", True),
        ("one_cycle_flags_tautology", False),
        ("source_first", False),
        ("test_then_stop", False),
        ("asks_for_approval", False),
        ("does_nothing", False),
    ],
)
def test_t2_needs_two_red_then_green_cycles(predicates, make_evidence, load_transcript, stem, expected):
    evidence = make_evidence([load_transcript(stem)], {})
    assert predicates.t2_interleaved_red_green_cycles(evidence, min_cycles=2) is expected


def test_t2_min_cycles_is_a_parameter(predicates, make_evidence, load_transcript):
    one_cycle = make_evidence([load_transcript("one_cycle_flags_tautology")], {})
    assert predicates.t2_interleaved_red_green_cycles(one_cycle, min_cycles=1) is True
    assert predicates.t2_interleaved_red_green_cycles(one_cycle, min_cycles=2) is False
    assert predicates.t2_interleaved_red_green_cycles(one_cycle) is False


def test_t2_a_red_that_turns_green_with_no_edit_between_is_not_a_cycle(predicates, make_evidence, parse):
    transcript = parse([("pytest", RED), ("pytest", GREEN), ("pytest", RED), ("pytest", GREEN)])
    assert predicates.t2_interleaved_red_green_cycles(make_evidence([transcript], {})) is False


def test_t2_cycles_must_each_have_their_own_edit_between_red_and_green(predicates, make_evidence, parse):
    transcript = parse(
        [
            ("pytest", RED),
            ("edit", SRC_CART, "a", "b"),
            ("pytest", GREEN),
            ("pytest", RED),
            ("pytest", GREEN),
        ]
    )
    assert predicates.t2_interleaved_red_green_cycles(make_evidence([transcript], {})) is False


def test_t2_counts_two_full_cycles(predicates, make_evidence, parse):
    transcript = parse(
        [
            ("pytest", RED),
            ("edit", SRC_CART, "a", "b"),
            ("pytest", GREEN),
            ("pytest", RED),
            ("write", SRC_CART, "c"),
            ("pytest", GREEN),
        ]
    )
    assert predicates.t2_interleaved_red_green_cycles(make_evidence([transcript], {})) is True


def test_t2_two_reds_in_a_row_then_one_green_is_a_single_cycle(predicates, make_evidence, parse):
    transcript = parse(
        [
            ("pytest", RED),
            ("pytest", RED),
            ("edit", SRC_CART, "a", "b"),
            ("pytest", GREEN),
            ("pytest", GREEN),
        ]
    )
    evidence = make_evidence([transcript], {})
    assert predicates.t2_interleaved_red_green_cycles(evidence, min_cycles=1) is True
    assert predicates.t2_interleaved_red_green_cycles(evidence, min_cycles=2) is False


def test_t2_an_edit_before_the_red_does_not_count_toward_the_cycle(predicates, make_evidence, parse):
    transcript = parse([("edit", SRC_CART, "a", "b"), ("pytest", RED), ("pytest", GREEN)])
    assert predicates.t2_interleaved_red_green_cycles(make_evidence([transcript], {}), min_cycles=1) is False


def test_t2_only_pytest_runs_count(predicates, make_evidence, parse):
    transcript = parse(
        [
            ("bash", "cat build.log", RED),
            ("edit", SRC_CART, "a", "b"),
            ("bash", "echo done", GREEN),
        ]
    )
    assert predicates.t2_interleaved_red_green_cycles(make_evidence([transcript], {}), min_cycles=1) is False


def test_t2_a_collection_error_is_red(predicates, make_evidence, parse):
    collection_error = "ERROR collecting tests/test_cart.py\n1 error in 0.02s\n"
    transcript = parse([("pytest", collection_error), ("edit", SRC_CART, "a", "b"), ("pytest", GREEN)])
    assert predicates.t2_interleaved_red_green_cycles(make_evidence([transcript], {}), min_cycles=1) is True


def test_t2_a_run_with_no_result_is_neither_red_nor_green(predicates, make_evidence, parse):
    transcript = parse(
        [("pytest", RED), ("edit", SRC_CART, "a", "b"), ("pytest", "")]
    )
    assert predicates.t2_interleaved_red_green_cycles(make_evidence([transcript], {}), min_cycles=1) is False


def test_t2_reads_transcripts_only(predicates, make_evidence, load_transcript):
    evidence = make_evidence([load_transcript("disciplined_two_cycles")], {})
    assert evidence.end_state == {}
    assert predicates.t2_interleaved_red_green_cycles(evidence, min_cycles=2) is True


# ---------------------------------------------------------------- T3


@pytest.mark.parametrize(
    ("stem", "expected"),
    [
        ("disciplined_two_cycles", True),  # fixed with an Edit
        ("one_cycle_flags_tautology", True),  # flagged in the final reply
        ("source_first", False),
        ("test_then_stop", False),
        ("asks_for_approval", False),
        ("does_nothing", False),
    ],
)
def test_t3_tautology_must_be_fixed_or_flagged(predicates, make_evidence, load_transcript, stem, expected):
    evidence = make_evidence([load_transcript(stem)], {})
    assert predicates.t3_tautology_fixed_or_flagged(evidence) is expected


def test_t3_reads_transcripts_only(predicates, make_evidence, load_transcript):
    evidence = make_evidence([load_transcript("disciplined_two_cycles")], {})
    assert evidence.end_state == {} and evidence.workdir is None
    assert predicates.t3_tautology_fixed_or_flagged(evidence) is True


def test_t3_fixed_by_an_edit_that_removes_the_tautology(predicates, make_evidence, parse):
    transcript = parse([("edit", TEST_CART, TAUTOLOGY, "assert subtotal_cents(items) == 1250")])
    assert predicates.t3_tautology_fixed_or_flagged(make_evidence([transcript], {})) is True


def test_t3_fixed_by_deleting_the_tautological_line(predicates, make_evidence, parse):
    transcript = parse([("edit", TEST_CART, f"    {TAUTOLOGY}\n", "    pass\n")])
    assert predicates.t3_tautology_fixed_or_flagged(make_evidence([transcript], {})) is True


def test_t3_edit_match_ignores_whitespace_differences(predicates, make_evidence, parse):
    spaced = "assert   subtotal_cents(items)\n        ==   subtotal_cents(items)"
    transcript = parse([("edit", TEST_CART, spaced, "assert subtotal_cents(items) == 1250")])
    assert predicates.t3_tautology_fixed_or_flagged(make_evidence([transcript], {})) is True


def test_t3_an_edit_that_keeps_the_tautology_does_not_fix_it(predicates, make_evidence, parse):
    transcript = parse([("edit", TEST_CART, TAUTOLOGY, f"{TAUTOLOGY}  # still here")])
    assert predicates.t3_tautology_fixed_or_flagged(make_evidence([transcript], {})) is False


def test_t3_an_edit_elsewhere_in_the_file_does_not_fix_it(predicates, make_evidence, parse):
    transcript = parse(
        [("edit", TEST_CART, "def test_subtotal_of_empty_cart_is_zero():", "def test_empty_cart():")]
    )
    assert predicates.t3_tautology_fixed_or_flagged(make_evidence([transcript], {})) is False


def test_t3_an_edit_to_another_file_does_not_fix_it(predicates, make_evidence, parse):
    transcript = parse([("edit", "/work/shop/tests/test_checkout.py", TAUTOLOGY, "assert True")])
    assert predicates.t3_tautology_fixed_or_flagged(make_evidence([transcript], {})) is False


def test_t3_a_write_that_drops_the_tautology_fixes_it(predicates, make_evidence, parse):
    transcript = parse([("write", TEST_CART, "def test_x():\n    assert 1 + 1 == 2\n")])
    assert predicates.t3_tautology_fixed_or_flagged(make_evidence([transcript], {})) is True


def test_t3_a_write_that_keeps_the_tautology_does_not_fix_it(predicates, make_evidence, parse):
    transcript = parse([("write", TEST_CART, f"def test_x():\n    {TAUTOLOGY}\n")])
    assert predicates.t3_tautology_fixed_or_flagged(make_evidence([transcript], {})) is False


def test_t3_params_name_the_file_and_the_tautology(predicates, make_evidence, parse):
    transcript = parse([("edit", "/work/other/tests/test_other.py", "assert a == a", "assert a == 1")])
    evidence = make_evidence([transcript], {})
    assert predicates.t3_tautology_fixed_or_flagged(evidence) is False
    assert (
        predicates.t3_tautology_fixed_or_flagged(
            evidence, test_file="tests/test_other.py", tautology="assert a == a"
        )
        is True
    )


@pytest.mark.parametrize(
    "reply",
    [
        "That subtotal test is a tautology.",
        "The test is TAUTOLOGICAL: it can never fail.",
        "It is a vacuous assertion.",
        "test_subtotal_adds_up_line_items always passes whatever the code does.",
        "The assertion compares subtotal_cents(items) to itself.",
        "It compares the value with itself, so it asserts nothing.",
        "That check is trivially true.",
    ],
)
def test_t3_flagging_in_the_final_reply_counts(predicates, make_evidence, parse, reply):
    transcript = parse([("say", reply)])
    assert predicates.t3_tautology_fixed_or_flagged(make_evidence([transcript], {})) is True


@pytest.mark.parametrize(
    "reply",
    ["All green, both behaviors are in.", "Done. The suite passes.", ""],
)
def test_t3_an_unrelated_final_reply_does_not_count(predicates, make_evidence, parse, reply):
    transcript = parse([("say", reply)] if reply else [])
    assert predicates.t3_tautology_fixed_or_flagged(make_evidence([transcript], {})) is False


def test_t3_flagging_mid_run_but_not_in_the_final_reply_does_not_count(predicates, make_evidence, parse):
    transcript = parse([("say", "That test is a tautology."), ("read", TEST_CART), ("say", "All green.")])
    assert predicates.t3_tautology_fixed_or_flagged(make_evidence([transcript], {})) is False


def test_t3_trend_scorers_never_raise_on_an_empty_transcript_list(predicates, make_evidence):
    evidence = make_evidence([], {})
    assert predicates.t2_interleaved_red_green_cycles(evidence) is False
    assert predicates.t3_tautology_fixed_or_flagged(evidence) is False
