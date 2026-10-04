"""Tests for the T1 gate candidate and the T2/T3 trend scorers in predicates.py.

Every scorer is exercised over synthetic transcripts in the real envelope shape
and over hand-built end-state mappings, never over a live repo. T1's second,
third and fourth conjuncts and T3's repair check read end-state files; the ordering
conjunct and T2 read the transcript, where a Bash call counts as a possible write by
its text (``matchers.bash_write_offset``).
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
    monkeypatch.setattr(matchers, "test_failed_before_first_source_write", lambda events: False)
    assert t1("disciplined_two_cycles", make_snapshot()) is False
    monkeypatch.setattr(matchers, "test_failed_before_first_source_write", lambda events: True)
    assert t1("source_first", make_snapshot()) is True


def test_t1_first_conjunct_receives_the_case_agents_events(
    monkeypatch, t1, make_snapshot, load_transcript
):
    seen = []

    def spy(events):
        seen.append(events)
        return True

    monkeypatch.setattr(matchers, "test_failed_before_first_source_write", spy)
    transcript = load_transcript("disciplined_two_cycles")
    t1(transcript, make_snapshot())
    assert seen == [transcript.events]


def test_t1_misses_for_a_transcript_with_no_events(t1, make_snapshot, load_transcript):
    assert t1(load_transcript("does_nothing"), make_snapshot()) is False


def test_t1_misses_without_any_transcript(predicates, make_evidence, make_snapshot):
    assert predicates.t1_test_first_and_effective(make_evidence([], make_snapshot())) is False


# ---------------------------------------------------------------- T1 conjunct 2


def test_t1_misses_when_nothing_changed_under_src(t1, make_snapshot):
    assert t1("disciplined_two_cycles", make_snapshot(src_changed=["tests/test_cart.py"])) is False


def test_t1_misses_when_nothing_changed_at_all(t1, make_snapshot):
    assert t1("disciplined_two_cycles", make_snapshot(src_changed=[])) is False


def test_t1_reads_the_src_diff_not_the_edit_tool_record(t1, make_snapshot):
    # An empty edit-tool record (every change made through Bash) must not hide a real src change,
    # and a recorded src edit with no src change in the end state must not invent one.
    assert t1("disciplined_two_cycles", make_snapshot(edited=[], src_changed=["src/shop/cart.py"])) is True
    edited = [{"path": "src/shop/cart.py", "timestamp": None}]
    assert t1("disciplined_two_cycles", make_snapshot(edited=edited, src_changed=[])) is False


@pytest.mark.parametrize("change", ["added", "changed", "removed"])
def test_t1_any_kind_of_change_under_src_counts(t1, make_snapshot, change):
    entry = {"path": "src/shop/cart.py", "change": change}
    assert t1("disciplined_two_cycles", make_snapshot(src_changed=[entry])) is True


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
    assert t1("disciplined_two_cycles", make_snapshot(src_changed=[path])) is False


@pytest.mark.parametrize("path", ["src/shop/cart.py", "src/new_module.py", "./src/shop/checkout.py"])
def test_t1_any_one_edit_under_src_is_enough(t1, make_snapshot, path):
    assert t1("disciplined_two_cycles", make_snapshot(src_changed=["tests/test_cart.py", path])) is True


@pytest.mark.parametrize("raw", ["", "not json", "{}", '{"path": "src/a.py"}', "[1, 2]", '[{"nope": 1}]'])
def test_t1_misses_on_a_missing_or_malformed_src_changed_file(t1, make_snapshot, raw):
    end_state = make_snapshot()
    end_state["src-changed.json"] = raw
    assert t1("disciplined_two_cycles", end_state) is False


def test_t1_misses_when_the_src_changed_file_is_absent(t1, make_snapshot):
    end_state = make_snapshot()
    del end_state["src-changed.json"]
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
    do_nothing = make_snapshot(final_exit=0, reverted_exit=0, edited=[], src_changed=[])
    assert t1("does_nothing", do_nothing) is False


def test_t1_misses_an_agent_that_only_asks_for_approval(t1, make_snapshot):
    asked = make_snapshot(final_exit=0, reverted_exit=0, edited=[], src_changed=[])
    assert t1("asks_for_approval", asked) is False


def test_t1_misses_an_agent_that_writes_a_failing_test_and_stops(t1, make_snapshot):
    edited = [{"path": "tests/test_cart.py", "timestamp": None}]
    stopped = make_snapshot(final_exit=1, reverted_exit=1, edited=edited, src_changed=[])
    assert t1("test_then_stop", stopped) is False


def test_t1_the_do_nothing_agent_misses_even_when_only_the_final_suite_is_green(t1, make_snapshot):
    # The base suite is green, so a gate built only from "the suite passes" would credit this.
    assert t1("does_nothing", make_snapshot(final_exit=0, reverted_exit=0, edited=[], src_changed=[])) is False
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


# ---------------------------------------------------------------- T1 over Bash-shaped transcripts


@pytest.mark.parametrize(
    ("stem", "expected"),
    [
        # tests appended through Bash with the red result in the same call; source written one call later
        ("bash_test_first", True),
        # a Skill call first, then the same test-first work
        ("skill_then_bash_test_first", True),
        # a Skill call, then a read-only `for ... cat` inspection loop, then the same test-first work: the loop
        # was scored as a source write before compound constructs were structured
        ("skill_then_loop_inspection_then_test_first", True),
        # both source files rewritten first; the only red result comes after
        ("bash_source_first", False),
        # source, tests and a green pytest run in one Bash call, like the unprompted replay
        ("bash_one_call", False),
    ],
)
def test_t1_reads_bash_writes_when_the_end_state_conjuncts_hold(t1, make_snapshot, stem, expected):
    # edited-paths.json is empty, as it was for every real Bash-writing attempt: nothing may depend on it.
    snapshot = make_snapshot(edited=[], src_changed=["src/shop/cart.py", "src/shop/checkout.py"])
    assert t1(stem, snapshot) is expected


@pytest.mark.parametrize("stem", ["bash_test_first", "skill_then_bash_test_first", "skill_then_loop_inspection_then_test_first"])
def test_t1_bash_test_first_still_needs_every_end_state_conjunct(t1, make_snapshot, stem):
    assert t1(stem, make_snapshot(src_changed=[])) is False
    assert t1(stem, make_snapshot(final_exit=1)) is False
    assert t1(stem, make_snapshot(reverted_exit=0)) is False


def test_t1_a_read_only_inspection_loop_is_not_a_source_write(load_transcript):
    # The owner-audited hand-run's shape: `cd ... && for f in ...; do echo "=== $f"; cat $f; done; uv run pytest ...`.
    transcript = load_transcript("skill_then_loop_inspection_then_test_first")
    loop = [e for e in transcript.events if e.name == "Bash" and "for f in" in e.input["command"]]
    assert len(loop) == 1
    assert matchers.classify_write_event(loop[0]) == "none"
    assert matchers.test_failed_before_first_source_write(transcript.events) is True


def test_t1_the_one_call_attempt_has_no_red_result_at_all(load_transcript):
    # Its miss is the missing failure, not an ordering accident; the same-call case is pinned below.
    transcript = load_transcript("bash_one_call")
    assert matchers.test_failed_before_first_source_write(transcript.events) is False
    assert not any("FAILED" in str(event.result.content) for event in transcript.events if event.result)


def test_t1_the_source_first_attempt_does_fail_a_test_but_only_after_writing_the_source(load_transcript):
    transcript = load_transcript("bash_source_first")
    failures = [e.ordinal for e in transcript.events if e.result and "FAILED" in str(e.result.content)]
    writes = [e.ordinal for e in transcript.events if matchers.classify_write_event(e) == "source"]
    assert failures and writes and min(writes) < min(failures)


def test_t1_a_red_run_in_the_call_that_also_writes_the_source_is_not_credited(t1, make_snapshot, parse):
    rewrite = "python3 - <<'EOF'\np='src/shop/cart.py'\nopen(p,'w').write('x')\nEOF"
    transcript = parse(
        [
            ("write", "/work/shop/tests/test_new.py", "def test_x():\n    assert 0\n"),
            ("bash", f"cd /work/shop && {rewrite}\nuv run pytest -q", RED),
            ("bash", "cd /work/shop && uv run pytest -q", GREEN),
        ]
    )
    assert t1(transcript, make_snapshot()) is False


def test_t1_a_red_run_in_a_call_before_the_one_that_writes_the_source_is_credited(t1, make_snapshot, parse):
    append = "cat >> tests/test_cart.py <<'EOF'\ndef test_x():\n    assert False\nEOF"
    rewrite = "python3 - <<'EOF'\np='src/shop/cart.py'\nopen(p,'w').write('x')\nEOF"
    transcript = parse(
        [
            ("bash", f"cd /work/shop && {append}\nuv run pytest -q", RED),
            ("bash", f"cd /work/shop && {rewrite}\nuv run pytest -q", GREEN),
        ]
    )
    assert t1(transcript, make_snapshot()) is True


def test_t1_the_skill_arm_corpus_transcript_calls_the_skill_first_and_the_other_does_not(load_transcript):
    assert matchers.skill_triggered_first(load_transcript("skill_then_bash_test_first"), "workbench:tdd") is True
    assert matchers.skill_triggered_first(load_transcript("bash_test_first"), "workbench:tdd") is False


def test_t1_does_not_require_a_skill_call(t1, make_snapshot, load_transcript):
    # T1 measures behaviour: a test-first run that never calls Skill still hits.
    transcript = load_transcript("bash_test_first")
    assert not any(event.name == "Skill" for event in transcript.events)
    assert t1(transcript, make_snapshot()) is True


def test_t1_a_skill_call_without_test_first_work_does_not_hit(t1, make_snapshot, load_transcript):
    transcript = load_transcript("skill_then_bash_test_first")
    assert any(event.name == "Skill" for event in transcript.events)
    assert t1("bash_one_call", make_snapshot()) is False


def test_t1_a_red_result_that_no_test_write_stands_behind_is_not_a_red(t1, make_snapshot, parse):
    rewrite = "python3 - <<'EOF'\np='src/shop/cart.py'\nopen(p,'w').write('x')\nEOF"
    echoed = parse(
        [
            ("bash", "echo 'FAILED tests/test_cart.py::test_x'", "FAILED tests/test_cart.py::test_x\n"),
            ("bash", f"cd /work/shop && {rewrite}\nuv run pytest -q", GREEN),
        ]
    )
    assert t1(echoed, make_snapshot()) is False


def test_t1_an_edit_tool_test_write_then_red_then_a_bash_source_write_hits(t1, make_snapshot, parse):
    rewrite = "python3 - <<'EOF'\np='src/shop/cart.py'\nopen(p,'w').write('x')\nEOF"
    transcript = parse(
        [
            ("write", "/work/shop/tests/test_new.py", "def test_x():\n    assert 0\n"),
            ("pytest", RED),
            ("bash", f"cd /work/shop && {rewrite}\nuv run pytest -q", GREEN),
        ]
    )
    assert t1(transcript, make_snapshot()) is True


def test_t1_a_first_source_write_the_old_rule_could_not_see_no_longer_lets_a_later_red_hit(
    t1, make_snapshot, parse
):
    append = "cat >> tests/test_cart.py <<'EOF'\ndef test_x():\n    assert False\nEOF"
    rewrite = "python3 - <<'EOF'\np='src/shop/cart.py'\nopen(p,'w').write('x')\nEOF"
    for first in (
        "perl -0pi -e 's/a/b/' src/shop/cart.py",
        "cd src && cat > shop/cart.py <<'EOF'\nx = 1\nEOF",
        "find src -name '*.py' -exec sed -i '' 's/a/b/' {} +",
        "perl -0pi -e 's/a/b/' shop/cart.py",
        "sed -i'' 's/a/b/' shop/cart.py",
        "gsed -i 's/a/b/' shop/cart.py",
        "\\cp /tmp/n.py shop/cart.py",
        "ditto /tmp/n.py shop/cart.py",
        "uv run python /tmp/fix.py",
        "python3 -c \"from shutil import copy; copy('/tmp/n.py','shop/cart.py')\"",
        "sed -n '1w shop/cart.py' /tmp/n.py",
    ):
        transcript = parse(
            [
                ("bash", first, ""),
                ("bash", f"cd /work/shop && {append}\nuv run pytest -q", RED),
                ("bash", f"cd /work/shop && {rewrite}\nuv run pytest -q", GREEN),
            ]
        )
        assert t1(transcript, make_snapshot()) is False, first


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


# ---------------------------------------------------------------- T2 over Bash writes

APPEND_TESTS = "cat >> tests/test_cart.py <<'EOF'\ndef test_x():\n    assert False\nEOF"
REWRITE_SRC = "python3 - <<'EOF'\np='src/shop/cart.py'\nopen(p,'w').write('x')\nEOF"
RUN = "uv run pytest -q 2>&1 | tail -8"


@pytest.mark.parametrize(
    ("stem", "expected"),
    [
        ("bash_test_first", True),
        ("skill_then_bash_test_first", True),
        ("bash_source_first", False),
        ("bash_one_call", False),
    ],
)
def test_t2_reads_bash_writes_in_the_bash_shaped_corpus(predicates, make_evidence, load_transcript, stem, expected):
    evidence = make_evidence([load_transcript(stem)], {})
    assert predicates.t2_interleaved_red_green_cycles(evidence, min_cycles=2) is expected


def test_t2_two_cycles_made_entirely_through_bash_count(predicates, make_evidence, parse):
    transcript = parse(
        [
            ("bash", f"{APPEND_TESTS}\n{RUN}", RED),
            ("bash", f"{REWRITE_SRC}\n{RUN}", GREEN),
            ("bash", f"{APPEND_TESTS}\n{RUN}", RED),
            ("bash", f"{REWRITE_SRC}\n{RUN}", GREEN),
        ]
    )
    assert predicates.t2_interleaved_red_green_cycles(make_evidence([transcript], {})) is True


def test_t2_a_write_before_the_pytest_run_in_the_red_call_is_not_between_red_and_green(
    predicates, make_evidence, parse
):
    transcript = parse([("bash", f"{APPEND_TESTS}\n{RUN}", RED), ("bash", RUN, GREEN)])
    assert predicates.t2_interleaved_red_green_cycles(make_evidence([transcript], {}), min_cycles=1) is False


def test_t2_a_write_after_the_pytest_run_in_the_red_call_is_between_red_and_green(
    predicates, make_evidence, parse
):
    transcript = parse([("bash", f"{RUN}; {REWRITE_SRC}", RED), ("bash", RUN, GREEN)])
    assert predicates.t2_interleaved_red_green_cycles(make_evidence([transcript], {}), min_cycles=1) is True


def test_t2_a_bash_write_call_with_no_pytest_run_is_an_edit_between_them(predicates, make_evidence, parse):
    transcript = parse([("pytest", RED), ("bash", REWRITE_SRC, ""), ("pytest", GREEN)])
    assert predicates.t2_interleaved_red_green_cycles(make_evidence([transcript], {}), min_cycles=1) is True


def test_t2_a_test_write_through_bash_is_an_edit_between_them(predicates, make_evidence, parse):
    transcript = parse([("pytest", RED), ("bash", APPEND_TESTS, ""), ("pytest", GREEN)])
    assert predicates.t2_interleaved_red_green_cycles(make_evidence([transcript], {}), min_cycles=1) is True


@pytest.mark.parametrize(
    "command",
    [
        "cat src/shop/cart.py",
        "git status --short",
        "sed -n 1,20p src/shop/cart.py",
    ],
)
def test_t2_a_read_only_bash_call_is_not_an_edit(
    predicates, make_evidence, parse, command
):
    transcript = parse([("pytest", RED), ("bash", command, ""), ("pytest", GREEN)])
    assert predicates.t2_interleaved_red_green_cycles(make_evidence([transcript], {}), min_cycles=1) is False


def test_t2_a_write_that_names_neither_src_nor_tests_counts_as_an_edit_because_it_fails_closed(
    predicates, make_evidence, parse
):
    transcript = parse([("pytest", RED), ("bash", "cat > docs/notes.md <<'EOF'\nx\nEOF", ""), ("pytest", GREEN)])
    assert predicates.t2_interleaved_red_green_cycles(make_evidence([transcript], {}), min_cycles=1) is True


def test_t2_an_edit_tool_write_to_a_scratch_file_is_not_an_edit(predicates, make_evidence, parse):
    transcript = parse([("pytest", RED), ("write", "/work/shop/scratch_plan.md", "x"), ("pytest", GREEN)])
    assert predicates.t2_interleaved_red_green_cycles(make_evidence([transcript], {}), min_cycles=1) is False


def test_t2_a_multiedit_is_an_edit(predicates, make_evidence, parse):
    transcript = parse(
        [("pytest", RED), ("tool", "MultiEdit", {"file_path": SRC_CART, "edits": []}, "ok"), ("pytest", GREEN)]
    )
    assert predicates.t2_interleaved_red_green_cycles(make_evidence([transcript], {}), min_cycles=1) is True


def test_t2_a_green_run_that_also_writes_the_source_counts_as_the_edit(predicates, make_evidence, parse):
    transcript = parse([("pytest", RED), ("bash", f"{REWRITE_SRC}\n{RUN}", GREEN)])
    assert predicates.t2_interleaved_red_green_cycles(make_evidence([transcript], {}), min_cycles=1) is True


# ---------------------------------------------------------------- T3


def _t3(predicates, make_evidence, transcript, end_state, **params):
    return predicates.t3_tautology_fixed_or_flagged(make_evidence([transcript], end_state), **params)


@pytest.mark.parametrize(
    ("stem", "tautology_present", "expected"),
    [
        ("disciplined_two_cycles", False, True),  # fixed: the planted line is gone from the final tests
        ("one_cycle_flags_tautology", True, True),  # flagged in the final reply
        ("source_first", True, False),
        ("test_then_stop", True, False),
        ("asks_for_approval", True, False),
        ("does_nothing", True, False),
    ],
)
def test_t3_tautology_must_be_fixed_or_flagged(
    predicates, make_evidence, make_snapshot, load_transcript, stem, tautology_present, expected
):
    snapshot = make_snapshot(tautology_present=tautology_present)
    assert _t3(predicates, make_evidence, load_transcript(stem), snapshot) is expected


def test_t3_a_fix_made_through_bash_counts_because_the_end_state_is_read(
    predicates, make_evidence, make_snapshot, load_transcript
):
    transcript = load_transcript("bash_test_first")  # the planted line is replaced by a python heredoc
    assert not any(event.name in ("Edit", "Write") for event in transcript.events)
    final_reply = transcript.final_text
    assert "tautolog" not in final_reply.lower()
    assert _t3(predicates, make_evidence, transcript, make_snapshot(tautology_present=False)) is True
    assert _t3(predicates, make_evidence, transcript, make_snapshot(tautology_present=True)) is False


def test_t3_the_end_state_decides_not_the_edit_tool_events(predicates, make_evidence, make_snapshot, parse):
    # An Edit that removed the line, undone later by another write, leaves the planted line in place.
    transcript = parse([("edit", TEST_CART, TAUTOLOGY, "assert subtotal_cents(items) == 1500")])
    assert _t3(predicates, make_evidence, transcript, make_snapshot(tautology_present=True)) is False
    assert _t3(predicates, make_evidence, transcript, make_snapshot(tautology_present=False)) is True


def test_t3_a_missing_or_malformed_tests_snapshot_is_no_evidence_of_a_repair(
    predicates, make_evidence, make_snapshot, parse
):
    transcript = parse([("say", "All green.")])
    for raw in ("", "not json", "[]", '{"tests/test_cart.py": 1}'):
        end_state = make_snapshot()
        end_state["tests-final.json"] = raw
        assert _t3(predicates, make_evidence, transcript, end_state) is False, raw
    end_state = make_snapshot()
    del end_state["tests-final.json"]
    assert _t3(predicates, make_evidence, transcript, end_state) is False
    assert _t3(predicates, make_evidence, transcript, {}) is False


def _repaired(predicates, make_evidence, make_snapshot, parse, tests):
    transcript = parse([("say", "All green.")])
    return _t3(predicates, make_evidence, transcript, make_snapshot(tests_final=tests))


def test_t3_whitespace_differences_do_not_hide_a_surviving_tautology(
    predicates, make_evidence, make_snapshot, parse
):
    spaced = "assert   subtotal_cents(items)\n        ==   subtotal_cents(items)"
    tests = {"tests/test_cart.py": f"def test_x():\n    {spaced}\n"}
    assert _repaired(predicates, make_evidence, make_snapshot, parse, tests) is False


def test_t3_commenting_the_line_out_does_not_repair_it(predicates, make_evidence, make_snapshot, parse):
    tests = {"tests/test_cart.py": f"def test_x():\n    # {TAUTOLOGY}\n    pass\n"}
    assert _repaired(predicates, make_evidence, make_snapshot, parse, tests) is False


def test_t3_a_changed_assertion_elsewhere_in_the_file_does_not_repair_it(
    predicates, make_evidence, make_snapshot, parse
):
    tests = {"tests/test_cart.py": f"def test_empty_cart():\n    pass\n\ndef test_y():\n    {TAUTOLOGY}\n"}
    assert _repaired(predicates, make_evidence, make_snapshot, parse, tests) is False


def test_t3_rewriting_the_line_in_place_is_a_repair(predicates, make_evidence, make_snapshot, parse):
    tests = {"tests/test_cart.py": "def test_x():\n    assert subtotal_cents([]) == 0\n"}
    assert _repaired(predicates, make_evidence, make_snapshot, parse, tests) is True


# The deleted-file and moved-file edge cases. The snapshot holds every python file outside src/, and the
# planted line must be absent from all of them: a file moved anywhere with the line intact is not a repair.


def test_t3_deleting_the_test_file_removes_the_planted_line_and_counts_as_repaired(
    predicates, make_evidence, make_snapshot, parse
):
    tests = {"tests/test_checkout.py": "def test_ok():\n    pass\n"}  # tests/test_cart.py is gone
    assert _repaired(predicates, make_evidence, make_snapshot, parse, tests) is True


def test_t3_deleting_every_test_counts_as_repaired_here_and_is_left_to_t1(
    predicates, make_evidence, make_snapshot, parse
):
    assert _repaired(predicates, make_evidence, make_snapshot, parse, {}) is True


@pytest.mark.parametrize(
    "moved_to",
    [
        "tests/test_cart_old.py",
        "tests/unit/test_cart.py",
        "old_tests/test_cart.py",
        "test_cart.py",
        "scratch/cart_checks.py",
    ],
)
def test_t3_moving_the_file_anywhere_with_the_planted_line_intact_is_not_a_repair(
    predicates, make_evidence, make_snapshot, parse, moved_to
):
    tests = {"tests/test_checkout.py": "def test_ok():\n    pass\n", moved_to: f"def test_x():\n    {TAUTOLOGY}\n"}
    assert _repaired(predicates, make_evidence, make_snapshot, parse, tests) is False


def test_t3_renaming_the_file_and_rewriting_the_line_is_a_repair(predicates, make_evidence, make_snapshot, parse):
    tests = {"tests/test_cart_v2.py": "def test_x():\n    assert subtotal_cents([]) == 0\n"}
    assert _repaired(predicates, make_evidence, make_snapshot, parse, tests) is True


def test_t3_the_tautology_param_names_the_planted_line(predicates, make_evidence, make_snapshot, parse):
    tests = {"other/test_other.py": "def test_x():\n    assert a == a\n", "tests/test_cart.py": "ok = 1\n"}
    transcript = parse([("say", "All green.")])
    snapshot = make_snapshot(tests_final=tests)
    assert _t3(predicates, make_evidence, transcript, snapshot) is True  # the cart tautology is absent
    assert _t3(predicates, make_evidence, transcript, snapshot, tautology="assert a == a") is False


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


def test_t3_reads_end_state_and_transcripts_never_the_workdir(
    predicates, make_evidence, make_snapshot, load_transcript, tmp_path
):
    transcript = load_transcript("does_nothing")
    snapshot = make_snapshot(tautology_present=False)
    live = make_evidence([transcript], snapshot, workdir=tmp_path / "does-not-exist")
    assert predicates.t3_tautology_fixed_or_flagged(live) is True
    assert predicates.t3_tautology_fixed_or_flagged(make_evidence([transcript], snapshot, workdir=None)) is True


def test_t3_trend_scorers_never_raise_on_an_empty_transcript_list(predicates, make_evidence):
    evidence = make_evidence([], {})
    assert predicates.t2_interleaved_red_green_cycles(evidence) is False
    assert predicates.t3_tautology_fixed_or_flagged(evidence) is False
