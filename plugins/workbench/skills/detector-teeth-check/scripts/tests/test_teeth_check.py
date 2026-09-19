"""Tests for teeth_check.

The tool edits source files in place, so the tests that matter most are the
ones about *not lying* and *not losing work*:

- a mutation whose anchor never matched did not survive — the spec is broken,
  and reporting it as a survivor would send someone hunting for a missing test
  that already exists;
- a suite that is already red makes every mutant look killed, so the run must
  refuse rather than emit a reassuring all-green matrix;
- the file must come back even when the test command explodes mid-run.

The test command is injected, so no real pytest subprocess runs here.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

from teeth_check import (  # noqa: E402
    BaselineNotGreen,
    RUNNERS,
    _default_runner,
    _exit_code,
    _find_matching_runner,
    _runner_mismatch_advice,
    Mutation,
    Spec,
    SpecError,
    apply_mutation,
    load_spec,
    main,
    parse_collected_tests,
    parse_failed_tests,
    render,
    run_teeth_check,
)


# ---------------------------------------------------------------------------
# Output parsing
# ---------------------------------------------------------------------------


def test_parses_failed_test_ids() -> None:
    out = (
        "FAILED tests/test_a.py::test_one - AssertionError: nope\n"
        "FAILED tests/test_a.py::TestC::test_two\n"
        "2 failed, 3 passed in 0.10s\n"
    )

    assert parse_failed_tests(out) == {
        "tests/test_a.py::test_one",
        "tests/test_a.py::TestC::test_two",
    }


def test_parses_no_failures_as_empty() -> None:
    assert parse_failed_tests("14 passed in 0.42s\n") == set()


def test_parses_collected_test_ids() -> None:
    out = "tests/test_a.py::test_one\ntests/test_a.py::test_two\n\n2 tests collected\n"

    assert parse_collected_tests(out) == [
        "tests/test_a.py::test_one",
        "tests/test_a.py::test_two",
    ]


# ---------------------------------------------------------------------------
# Mutation application
# ---------------------------------------------------------------------------


def test_apply_mutation_replaces_the_anchor() -> None:
    assert apply_mutation("a = 1\nb = 2\n", "a = 1", "a = 99") == "a = 99\nb = 2\n"


def test_apply_mutation_rejects_a_missing_anchor() -> None:
    """A silently-unapplied mutation would masquerade as a surviving one."""
    with pytest.raises(ValueError):
        apply_mutation("a = 1\n", "not present", "x")


def test_apply_mutation_rejects_an_ambiguous_anchor() -> None:
    """Two matches means the spec does not say which line it meant."""
    with pytest.raises(ValueError):
        apply_mutation("x = 1\nx = 1\n", "x = 1", "x = 2")


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------


@pytest.fixture
def target(tmp_path: Path) -> Path:
    src = tmp_path / "mod.py"
    src.write_text("LIMIT = 25\nGUARD = True\n")
    return src


def _spec(target: Path, *mutants: Mutation, collect: bool = False) -> Spec:
    return Spec(
        test_command=["pytest", "-q"],
        collect_command=["pytest", "--collect-only", "-q"] if collect else None,
        mutants=list(mutants),
    )


def test_refuses_when_the_baseline_is_already_red(target: Path) -> None:
    """Every mutant looks killed against a red suite — the run must not proceed."""

    def runner(cmd: list[str]) -> tuple[int, str]:
        return 1, "FAILED tests/test_a.py::test_one\n1 failed in 0.1s\n"

    with pytest.raises(BaselineNotGreen):
        run_teeth_check(
            _spec(target, Mutation("cap", target, "LIMIT = 25", "LIMIT = 999")),
            runner=runner,
        )


def test_reports_a_killed_mutant_with_the_tests_that_killed_it(target: Path) -> None:
    calls: list[list[str]] = []

    def runner(cmd: list[str]) -> tuple[int, str]:
        calls.append(cmd)
        if len(calls) == 1:  # baseline
            return 0, "2 passed in 0.1s\n"
        return 1, "FAILED tests/test_a.py::test_cap\n1 failed, 1 passed in 0.1s\n"

    report = run_teeth_check(
        _spec(target, Mutation("cap", target, "LIMIT = 25", "LIMIT = 999")),
        runner=runner,
    )

    assert [m.status for m in report.mutants] == ["killed"]
    assert report.mutants[0].killed_by == ["tests/test_a.py::test_cap"]
    assert report.survivors() == []


def test_reports_a_surviving_mutant(target: Path) -> None:
    """A mutant nothing catches is the finding: the property is untested."""

    def runner(cmd: list[str]) -> tuple[int, str]:
        return 0, "2 passed in 0.1s\n"

    report = run_teeth_check(
        _spec(target, Mutation("guard", target, "GUARD = True", "GUARD = False")),
        runner=runner,
    )

    assert [m.status for m in report.mutants] == ["survived"]
    assert [m.label for m in report.survivors()] == ["guard"]


def test_an_unapplied_mutation_is_not_a_survivor(target: Path) -> None:
    """The distinction this tool exists to keep straight.

    A stale anchor means the spec drifted from the source. Calling that a
    survivor sends someone looking for a missing test that already exists.
    """

    def runner(cmd: list[str]) -> tuple[int, str]:
        return 0, "2 passed in 0.1s\n"

    report = run_teeth_check(
        _spec(target, Mutation("stale", target, "GONE = 1", "GONE = 2")),
        runner=runner,
    )

    assert [m.status for m in report.mutants] == ["not-applied"]
    assert report.survivors() == []


def test_a_mutant_that_does_not_compile_is_unscored(target: Path) -> None:
    """A syntactically invalid mutant measures nothing, and must not read as a kill.

    The suite goes red because the module stopped importing, not because an
    assertion noticed the defect. Scored as "killed" it manufactures a teeth
    signal for a property that may well be untested.
    """

    def runner(cmd: list[str]) -> tuple[int, str]:
        if cmd == ["pytest", "--collect-only", "-q"]:
            return 0, ""
        return 0, "2 passed in 0.1s\n"

    report = run_teeth_check(
        _spec(target, Mutation("broken", target, "LIMIT = 25", "LIMIT = = 25")),
        runner=runner,
    )

    assert [m.status for m in report.mutants] == ["unscored"]
    assert report.survivors() == []
    assert "compile" in report.mutants[0].detail
    assert target.read_text() == "LIMIT = 25\nGUARD = True\n"


def test_a_nonzero_run_naming_no_failing_test_is_unscored(target: Path) -> None:
    """The broken-runner case: absence of a failure line is not evidence of one.

    A test command that aborts before collection — an unrecognised argument, a
    missing plugin, an import error from the mutant — exits non-zero with no
    FAILED line anywhere. Reading that as a kill reports teeth the run never
    demonstrated.
    """
    calls: list[list[str]] = []

    def runner(cmd: list[str]) -> tuple[int, str]:
        calls.append(cmd)
        if len(calls) == 1:  # baseline
            return 0, "2 passed in 0.1s\n"
        return 4, "ERROR: unrecognized arguments: --timeout=120\n"

    report = run_teeth_check(
        _spec(target, Mutation("cap", target, "LIMIT = 25", "LIMIT = 999")),
        runner=runner,
    )

    assert [m.status for m in report.mutants] == ["unscored"]
    assert report.mutants[0].killed_by == []
    assert report.survivors() == []


def test_unscored_rows_are_reported_separately_from_survivors(target: Path) -> None:
    """An unscored row is a question about the harness, not about the tests."""

    def runner(cmd: list[str]) -> tuple[int, str]:
        return 0, "2 passed in 0.1s\n"

    report = run_teeth_check(
        _spec(
            target,
            Mutation("guard", target, "GUARD = True", "GUARD = False"),
            Mutation("broken", target, "LIMIT = 25", "LIMIT = = 25"),
        ),
        runner=runner,
    )

    assert [m.label for m in report.survivors()] == ["guard"]
    assert [m.label for m in report.unscored()] == ["broken"]


def test_restores_the_file_after_each_mutant(target: Path) -> None:
    original = target.read_text()

    def runner(cmd: list[str]) -> tuple[int, str]:
        return (0, "2 passed\n") if len(cmd) == 2 else (1, "FAILED t.py::x\n")

    run_teeth_check(
        _spec(
            target,
            Mutation("a", target, "LIMIT = 25", "LIMIT = 1"),
            Mutation("b", target, "GUARD = True", "GUARD = False"),
        ),
        runner=runner,
    )

    assert target.read_text() == original


def test_restores_the_file_when_the_runner_raises(target: Path) -> None:
    """A crash mid-run must not leave mutated source on disk."""
    original = target.read_text()
    calls: list[int] = []

    def runner(cmd: list[str]) -> tuple[int, str]:
        calls.append(1)
        if len(calls) == 1:
            return 0, "2 passed\n"
        raise RuntimeError("test runner exploded")

    with pytest.raises(RuntimeError):
        run_teeth_check(
            _spec(target, Mutation("a", target, "LIMIT = 25", "LIMIT = 1")),
            runner=runner,
        )

    assert target.read_text() == original


def test_flags_tests_that_never_killed_anything(target: Path) -> None:
    """The inverse finding: a test carrying no weight against any mutant.

    Redundant coverage looks identical to real coverage until something
    changes and nothing goes red.
    """
    calls: list[list[str]] = []

    def runner(cmd: list[str]) -> tuple[int, str]:
        calls.append(cmd)
        if "--collect-only" in cmd:
            return 0, "t.py::test_cap\nt.py::test_idle\n2 tests collected\n"
        if len(calls) <= 2:  # collect + baseline
            return 0, "2 passed\n"
        return 1, "FAILED t.py::test_cap\n1 failed in 0.1s\n"

    report = run_teeth_check(
        _spec(target, Mutation("cap", target, "LIMIT = 25", "LIMIT = 1"), collect=True),
        runner=runner,
    )

    assert report.never_killed == ["t.py::test_idle"]


def test_never_killed_is_none_without_a_collect_command(target: Path) -> None:
    """Not computed is reported as unknown, never as an empty all-clear."""

    def runner(cmd: list[str]) -> tuple[int, str]:
        return (0, "2 passed\n") if len(cmd) == 2 else (1, "FAILED t.py::x\n")

    report = run_teeth_check(
        _spec(target, Mutation("cap", target, "LIMIT = 25", "LIMIT = 1")),
        runner=runner,
    )

    assert report.never_killed is None


def test_never_killed_survives_differing_test_id_roots(target: Path) -> None:
    """pytest reports collected and failed ids with different path roots.

    `--collect-only` emits ids relative to the rootdir (which pytest resolves
    from the nearest pyproject.toml, often the repo root) while the FAILED
    summary emits them relative to the invocation directory. Comparing the raw
    strings makes every test look like it caught nothing — the tool's own
    dogfood run reported all 31 vault_mcp tests as dead weight while the matrix
    above showed them killing mutants.
    """
    calls: list[list[str]] = []

    def runner(cmd: list[str]) -> tuple[int, str]:
        calls.append(cmd)
        if "--collect-only" in cmd:
            return 0, (
                "deep/nested/tests/test_a.py::test_cap\n"
                "deep/nested/tests/test_a.py::test_idle\n"
            )
        if len(calls) <= 2:
            return 0, "2 passed\n"
        return 1, "FAILED tests/test_a.py::test_cap\n1 failed in 0.1s\n"

    report = run_teeth_check(
        _spec(target, Mutation("cap", target, "LIMIT = 25", "LIMIT = 1"), collect=True),
        runner=runner,
    )

    assert report.mutants[0].status == "killed"
    assert report.never_killed == ["deep/nested/tests/test_a.py::test_idle"]


# ---------------------------------------------------------------------------
# Stale bytecode
# ---------------------------------------------------------------------------


def test_default_runner_disables_bytecode_writing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Otherwise every run leaves behind the .pyc the next row has to survive.

    The ambient environment must not be able to satisfy this. When this suite
    runs under the harness itself the variable is already set in the parent, so
    a child that merely inherits it reads the same as one the runner
    configured — and the assertion passes either way. Clearing it first is what
    gives the test teeth.
    """
    monkeypatch.delenv("PYTHONDONTWRITEBYTECODE", raising=False)

    code, out = _default_runner(
        [
            sys.executable,
            "-c",
            "import os; print(os.environ.get('PYTHONDONTWRITEBYTECODE'))",
        ]
    )

    assert code == 0
    assert out.strip() == "1"


def test_purges_cached_bytecode_before_each_run(target: Path) -> None:
    """An equal-length mutation can otherwise run bytecode built from the original.

    CPython validates a cached ``.pyc`` on the source's byte size and its mtime
    truncated to whole seconds — neither of which a same-length replacement
    written inside that second disturbs. The mutant never executes and the row
    reads ``survived``, which is indistinguishable from a real gap.
    """
    cache = target.parent / "__pycache__"
    cache.mkdir()
    stale = cache / f"{target.stem}.cpython-313.pyc"
    stale.write_bytes(b"bytecode from the unmutated source")
    unrelated = cache / "other.cpython-313.pyc"
    unrelated.write_bytes(b"a different module")

    present_during_run: list[bool] = []

    def runner(cmd: list[str]) -> tuple[int, str]:
        present_during_run.append(stale.exists())
        # A real run caches bytecode, so the next row starts with a cache to
        # clear. Without this the baseline purge alone satisfies the assertion
        # and dropping the per-mutant purge changes nothing.
        stale.write_bytes(b"bytecode written by this run")
        return 0, "2 passed in 0.1s\n"

    run_teeth_check(
        # Equal length on purpose: "GUARD = True" and "GUARD = Fals" are both
        # 12 bytes, so the size half of the check cannot save us here.
        _spec(target, Mutation("guard", target, "GUARD = True", "GUARD = Fals")),
        runner=runner,
    )

    assert present_during_run == [False, False]
    assert unrelated.exists(), "purge must not touch another module's bytecode"


def test_purges_cached_bytecode_after_restoring(target: Path) -> None:
    """The worse direction: a restore that leaves the mutant's bytecode live.

    A later row then executes the previous row's mutation, so the matrix
    credits a kill to the wrong defect — a lie about which property is guarded,
    not merely a missing one.
    """
    cache = target.parent / "__pycache__"
    cache.mkdir()
    stale = cache / f"{target.stem}.cpython-313.pyc"

    def runner(cmd: list[str]) -> tuple[int, str]:
        stale.write_bytes(b"bytecode from the mutated source")
        return 0, "2 passed in 0.1s\n"

    run_teeth_check(
        _spec(target, Mutation("guard", target, "GUARD = True", "GUARD = Fals")),
        runner=runner,
    )

    assert not stale.exists()


# ---------------------------------------------------------------------------
# Declared oracle — what actually executed the assertion
#
# A kill says the test is sensitive to a change in *our source*. It says
# nothing about whether the assertion ran against the real dependency or
# against a stand-in built from our own output. A recording double's oracle
# IS the code under test, so a mutation of that code is killed by
# construction — the kill is guaranteed, and its information content is zero.
# The spec must therefore declare, per mutant, what scored it.
# ---------------------------------------------------------------------------


def _write_spec(tmp_path: Path, mutants: list[dict]) -> Path:
    spec = tmp_path / "spec.json"
    spec.write_text(
        json.dumps({"test_command": ["pytest", "-q"], "mutants": mutants})
    )
    return spec


def _mutant(**over: object) -> dict:
    base = {
        "label": "cap",
        "file": "mod.py",
        "find": "LIMIT = 25",
        "replace": "LIMIT = 999",
        "oracle": "real",
    }
    base.update(over)
    return base


def test_load_spec_reads_the_declared_oracle(tmp_path: Path) -> None:
    spec = load_spec(_write_spec(tmp_path, [_mutant(oracle="double")]))
    assert spec.mutants[0].oracle == "double"


def test_load_spec_refuses_a_mutant_with_no_declared_oracle(tmp_path: Path) -> None:
    """Omission must refuse, not default. A silently-assumed oracle is exactly
    the false confidence this field exists to remove."""
    m = _mutant()
    del m["oracle"]
    with pytest.raises(SpecError, match="oracle"):
        load_spec(_write_spec(tmp_path, [m]))


def test_load_spec_refuses_an_oracle_it_does_not_recognise(tmp_path: Path) -> None:
    with pytest.raises(SpecError, match="sort-of"):
        load_spec(_write_spec(tmp_path, [_mutant(oracle="sort-of")]))


def _killing_runner() -> object:
    calls: list[list[str]] = []

    def runner(cmd: list[str]) -> tuple[int, str]:
        calls.append(cmd)
        if len(calls) == 1:
            return 0, "2 passed in 0.1s\n"
        return 1, "FAILED tests/test_a.py::test_cap\n1 failed, 1 passed in 0.1s\n"

    return runner


def test_a_kill_against_a_double_is_reported_as_a_scoped_claim(target: Path) -> None:
    """The load-bearing case. The mutant dies, and the report must still say
    that nothing executed the real dependency."""
    report = run_teeth_check(
        _spec(
            target,
            Mutation("cap", target, "LIMIT = 25", "LIMIT = 999", oracle="double"),
        ),
        runner=_killing_runner(),
    )
    out = render(report)

    assert report.mutants[0].status == "killed"
    assert report.double_only_kills() == [report.mutants[0]]
    assert "KILLED AGAINST A DOUBLE ONLY" in out
    assert "0 against the real dependency" in out


def test_a_kill_against_the_real_dependency_is_not_flagged(target: Path) -> None:
    report = run_teeth_check(
        _spec(
            target,
            Mutation("cap", target, "LIMIT = 25", "LIMIT = 999", oracle="real"),
        ),
        runner=_killing_runner(),
    )
    out = render(report)

    assert report.double_only_kills() == []
    assert "KILLED AGAINST A DOUBLE ONLY" not in out
    assert "1 against the real dependency" in out


def test_an_undeclared_oracle_never_reads_as_the_real_dependency(target: Path) -> None:
    """A programmatic caller can skip the field; the report must say so rather
    than silently counting it as executed — the collect_command rule."""
    report = run_teeth_check(
        _spec(target, Mutation("cap", target, "LIMIT = 25", "LIMIT = 999")),
        runner=_killing_runner(),
    )
    out = render(report)

    assert "0 against the real dependency" in out
    assert "1 undeclared" in out


def test_a_survivor_is_not_counted_as_a_double_only_kill(target: Path) -> None:
    """double_only_kills is about kills; a survivor is already its own finding."""

    def runner(cmd: list[str]) -> tuple[int, str]:
        return 0, "2 passed in 0.1s\n"

    report = run_teeth_check(
        _spec(
            target,
            Mutation("guard", target, "GUARD = True", "GUARD = False", oracle="double"),
        ),
        runner=runner,
    )
    assert report.survivors() != []
    assert report.double_only_kills() == []


# ---------------------------------------------------------------------------
# Runner-aware output parsing
#
# pytest's FAILED/collected shapes were hardcoded, so a vitest suite scored
# every mutant "unscored" even when it correctly went red — the run measured
# nothing not because the harness broke, but because it was reading the
# wrong shape. A runner registry pulls the two apart.
# ---------------------------------------------------------------------------


_VITEST_FAIL_LINE = (
    " FAIL  src/lib/__tests__/groceries.test.ts > probe outer > fails on purpose\n"
)
_VITEST_TRANSFORM_ERROR_LINE = (
    " FAIL  src/lib/__tests__/zz_syntaxprobe.test.ts "
    "[ src/lib/__tests__/zz_syntaxprobe.test.ts ]\n"
)
_VITEST_LIST_OUTPUT = (
    "src/lib/__tests__/groceries.test.ts > withReservedList "
    "(post-0008/pre-seed guard) > prepends the grocery list when the server "
    "roster lacks the reserved id\n"
    "src/lib/__tests__/groceries.test.ts > probe outer > fails on purpose\n"
)


def test_parses_a_vitest_fail_line_into_its_full_id() -> None:
    assert parse_failed_tests(_VITEST_FAIL_LINE, RUNNERS["vitest"]) == {
        "src/lib/__tests__/groceries.test.ts > probe outer > fails on purpose"
    }


def test_a_vitest_transform_error_line_is_not_parsed_as_a_failing_test() -> None:
    """No ` > ` separator means the file never loaded — nothing was evaluated."""
    assert parse_failed_tests(_VITEST_TRANSFORM_ERROR_LINE, RUNNERS["vitest"]) == set()


def test_a_vitest_transform_error_scores_unscored_not_killed(target: Path) -> None:
    """The integration case: a non-zero run naming only that line measures nothing."""
    calls: list[list[str]] = []

    def runner(cmd: list[str]) -> tuple[int, str]:
        calls.append(cmd)
        if len(calls) == 1:  # baseline
            return 0, "Test Files  1 passed (1)\n"
        return 1, _VITEST_TRANSFORM_ERROR_LINE

    report = run_teeth_check(
        Spec(
            test_command=["npx", "vitest", "run"],
            mutants=[Mutation("cap", target, "LIMIT = 25", "LIMIT = 999")],
            runner="vitest",
        ),
        runner=runner,
    )

    assert [m.status for m in report.mutants] == ["unscored"]
    assert report.survivors() == []


def test_parses_vitest_list_output_into_collected_ids() -> None:
    assert parse_collected_tests(_VITEST_LIST_OUTPUT, RUNNERS["vitest"]) == [
        "src/lib/__tests__/groceries.test.ts > withReservedList "
        "(post-0008/pre-seed guard) > prepends the grocery list when the "
        "server roster lacks the reserved id",
        "src/lib/__tests__/groceries.test.ts > probe outer > fails on purpose",
    ]


def test_load_spec_refuses_an_unknown_runner(tmp_path: Path) -> None:
    spec = tmp_path / "spec.json"
    spec.write_text(
        json.dumps(
            {
                "test_command": ["pytest", "-q"],
                "runner": "mocha",
                "mutants": [_mutant()],
            }
        )
    )
    with pytest.raises(SpecError, match="mocha"):
        load_spec(spec)


def test_load_spec_defaults_the_runner_to_pytest(tmp_path: Path) -> None:
    """No `runner` key must behave exactly as pytest does today."""
    spec = load_spec(_write_spec(tmp_path, [_mutant()]))
    assert spec.runner == "pytest"


def test_vitest_normalize_matches_ids_across_whitespace_differences() -> None:
    """A FAIL-line id and a `list` id must compare equal despite differing spacing."""
    fail_line_id = "groceries.test.ts >  probe outer  > fails on purpose"
    list_id = "groceries.test.ts > probe outer > fails on purpose"
    normalize = RUNNERS["vitest"].normalize
    assert normalize(fail_line_id) == normalize(list_id)


# ---------------------------------------------------------------------------
# Self-diagnosing the wrong-runner failure
#
# A vitest user pointed at a pytest-configured spec used to see two sentences
# that both point at the mutant and the test command, and neither can fix a
# mismatched runner. The unscored row now checks the other registered
# runners' shapes and names one if it matches.
# ---------------------------------------------------------------------------


def test_unscored_detail_names_a_runner_that_would_have_matched(target: Path) -> None:
    calls: list[list[str]] = []

    def runner(cmd: list[str]) -> tuple[int, str]:
        calls.append(cmd)
        if len(calls) == 1:  # baseline
            return 0, "2 passed in 0.1s\n"
        return 1, _VITEST_FAIL_LINE

    report = run_teeth_check(
        _spec(target, Mutation("cap", target, "LIMIT = 25", "LIMIT = 999")),
        runner=runner,
    )

    assert [m.status for m in report.mutants] == ["unscored"]
    detail = report.mutants[0].detail
    assert "vitest" in detail
    assert "runner" in detail


def test_unscored_detail_keeps_generic_wording_when_no_runner_matches(
    target: Path,
) -> None:
    calls: list[list[str]] = []

    def runner(cmd: list[str]) -> tuple[int, str]:
        calls.append(cmd)
        if len(calls) == 1:  # baseline
            return 0, "2 passed in 0.1s\n"
        return 4, "ERROR: unrecognized arguments: --timeout=120\n"

    report = run_teeth_check(
        _spec(target, Mutation("cap", target, "LIMIT = 25", "LIMIT = 999")),
        runner=runner,
    )

    detail = report.mutants[0].detail
    assert "DOES match runner" not in detail
    assert "naming no failing test" in detail


# ---------------------------------------------------------------------------
# Positive controls — a mutant declared to survive on purpose
#
# A run in which everything dies cannot distinguish "the tests have teeth"
# from "this rig reports red for everything." A control is a deliberate
# semantic no-op that must survive, and a committed spec needs a way to say
# so without failing the run.
# ---------------------------------------------------------------------------


def _control(path: Path, **over: object) -> Mutation:
    base: dict[str, object] = dict(
        label="noop",
        find="GUARD = True",
        replace="GUARD = True  # comment only",
        oracle="real",
        expect="survived",
        why="adds a trailing comment; changes no executed behaviour",
    )
    base.update(over)
    return Mutation(path=path, **base)  # type: ignore[arg-type]


def test_expect_survived_and_green_is_a_held_control(target: Path) -> None:
    def runner(cmd: list[str]) -> tuple[int, str]:
        return 0, "2 passed in 0.1s\n"

    report = run_teeth_check(
        _spec(target, _control(target)),
        runner=runner,
    )

    assert [m.status for m in report.mutants] == ["control-held"]
    assert report.survivors() == []
    assert _exit_code(report) == 0


def test_expect_survived_and_red_is_a_broken_control(target: Path) -> None:
    calls: list[list[str]] = []

    def runner(cmd: list[str]) -> tuple[int, str]:
        calls.append(cmd)
        if len(calls) == 1:  # baseline
            return 0, "2 passed in 0.1s\n"
        return 1, "FAILED tests/test_a.py::test_guard\n1 failed, 1 passed in 0.1s\n"

    report = run_teeth_check(
        _spec(target, _control(target)),
        runner=runner,
    )

    assert [m.status for m in report.mutants] == ["control-broken"]
    assert report.mutants[0].killed_by == ["tests/test_a.py::test_guard"]
    assert _exit_code(report) != 0


def test_load_spec_refuses_a_survived_control_with_no_why(tmp_path: Path) -> None:
    m = _mutant(expect="survived")
    with pytest.raises(SpecError, match="why"):
        load_spec(_write_spec(tmp_path, [m]))


def test_load_spec_refuses_a_survived_control_with_a_blank_why(tmp_path: Path) -> None:
    m = _mutant(expect="survived", why="   ")
    with pytest.raises(SpecError, match="why"):
        load_spec(_write_spec(tmp_path, [m]))


def test_load_spec_refuses_an_expect_it_does_not_recognise(tmp_path: Path) -> None:
    with pytest.raises(SpecError, match="maybe"):
        load_spec(_write_spec(tmp_path, [_mutant(expect="maybe")]))


def test_a_held_control_is_not_counted_in_the_kill_tally(target: Path) -> None:
    calls: list[list[str]] = []

    def runner(cmd: list[str]) -> tuple[int, str]:
        calls.append(cmd)
        if len(calls) == 1:  # baseline
            return 0, "2 passed in 0.1s\n"
        if len(calls) == 2:  # the control: stays green
            return 0, "2 passed in 0.1s\n"
        return 1, "FAILED t.py::test_cap\n1 failed, 1 passed in 0.1s\n"

    report = run_teeth_check(
        _spec(
            target,
            _control(target),
            Mutation("cap", target, "LIMIT = 25", "LIMIT = 999", oracle="real"),
        ),
        runner=runner,
    )

    assert [m.label for m in report.controls_held()] == ["noop"]
    out = render(report)
    assert "1 killed — 1 against the real dependency, 0 against doubles" in out


def test_render_prints_a_held_controls_why_verbatim(target: Path) -> None:
    def runner(cmd: list[str]) -> tuple[int, str]:
        return 0, "2 passed in 0.1s\n"

    why_text = "swaps operand order in a commutative sum; result is identical"
    report = run_teeth_check(
        _spec(target, _control(target, why=why_text)),
        runner=runner,
    )

    out = render(report)
    assert why_text in out


def test_render_notes_when_a_control_held_but_nothing_was_killed(target: Path) -> None:
    def runner(cmd: list[str]) -> tuple[int, str]:
        return 0, "2 passed in 0.1s\n"

    report = run_teeth_check(
        _spec(target, _control(target)),
        runner=runner,
    )

    out = render(report)
    assert "rig executes" in out


# ---------------------------------------------------------------------------
# --check-anchors
#
# A spec's `find` anchors are exact source strings, so any refactor of the
# code under test silently rots them. This must be safe and near-instant: no
# baseline, no test command, no write — just apply_mutation's own check.
# ---------------------------------------------------------------------------


def test_check_anchors_resolves_all_and_runs_no_commands(
    target: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    spec_path = _write_spec(tmp_path, [_mutant()])

    def _poisoned(cmd: list[str]) -> tuple[int, str]:
        raise AssertionError(f"--check-anchors ran a command: {cmd}")

    monkeypatch.setattr("teeth_check._default_runner", _poisoned)

    code = main(["--check-anchors", str(spec_path)])

    assert code == 0
    out = capsys.readouterr().out
    assert "cap: ok" in out


def test_check_anchors_reports_a_stale_anchor_and_exits_nonzero(
    target: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec_path = _write_spec(
        tmp_path, [_mutant(label="stale", find="GONE = 1", replace="GONE = 2")]
    )

    code = main(["--check-anchors", str(spec_path)])

    assert code == 1
    out = capsys.readouterr().out
    assert "stale" in out
    assert "anchor not found" in out


def test_check_anchors_writes_nothing(target: Path, tmp_path: Path) -> None:
    spec_path = _write_spec(tmp_path, [_mutant()])
    before = target.read_bytes()

    main(["--check-anchors", str(spec_path)])

    assert target.read_bytes() == before


def test_vitest_failed_line_tolerates_reporter_padding() -> None:
    """The ` > ` requirement discriminates, not the prefix's exact spacing.

    Pinning vitest's observed one-space/two-space padding would make the
    parser a hostage to its reporter's formatting — and the failure mode of
    that drift is every row going ``unscored``, the exact dead end this
    runner support exists to remove.
    """
    padded = "    FAIL   src/a.test.ts > outer > does a thing"
    assert parse_failed_tests(padded, RUNNERS["vitest"]) == {
        "src/a.test.ts > outer > does a thing"
    }


def test_vitest_transform_error_is_not_a_kill_at_any_padding() -> None:
    """A file that never loaded evaluated no assertion, however it is printed."""
    for line in (
        " FAIL  src/a.test.ts [ src/a.test.ts ]",
        "   FAIL    src/a.test.ts [ src/a.test.ts ]",
    ):
        assert parse_failed_tests(line, RUNNERS["vitest"]) == set()


def test_runner_advice_is_pastable_json() -> None:
    """The detail tells the author what to type, so it must be valid JSON.

    ``{'runner': 'vitest'}`` is Python's repr, not a spec a JSON parser will
    accept — and this string exists precisely to be copied into one.
    """
    spec = Spec(
        test_command=["pytest"],
        runner="pytest",
        mutants=[
            Mutation(
                label="m",
                path=Path("x.py"),
                find="a",
                replace="b",
                oracle="real",
            )
        ],
    )
    detail = _runner_mismatch_advice(
        " FAIL  src/a.test.ts > outer > does a thing", spec.runner
    )
    assert '"runner": "vitest"' in detail
    assert "'runner'" not in detail


def test_mismatch_advice_never_names_the_runner_already_configured() -> None:
    """``exclude`` has to hold for output that BOTH runners can match.

    Via ``run_teeth_check`` this guard is unreachable — the check only runs
    once the configured runner's regex matched nothing, so it could never be
    the one returned. That makes the property real but untestable through the
    main path, which is exactly how a defensive guard rots: advice reading
    "set runner pytest" on a spec already configured for pytest is a dead end
    of the same kind this check exists to remove.
    """
    both = (
        "FAILED tests/test_a.py::test_one\n"
        " FAIL  src/a.test.ts > outer > does a thing\n"
    )
    assert _find_matching_runner(both, exclude="pytest") == "vitest"
    assert _find_matching_runner(both, exclude="vitest") == "pytest"
