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

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

from teeth_check import (  # noqa: E402
    BaselineNotGreen,
    Mutation,
    Spec,
    apply_mutation,
    parse_collected_tests,
    parse_failed_tests,
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
