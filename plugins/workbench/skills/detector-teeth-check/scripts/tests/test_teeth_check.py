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

import hashlib
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


def test_a_missing_target_file_is_not_applied_and_the_run_continues(
    target: Path, tmp_path: Path
) -> None:
    """A deleted or renamed target is a spec error on that row, like a stale anchor.

    Crashing mid-run threw away the verdicts of every row after it; scoring
    it as a survivor would send someone hunting for a missing test.
    """
    gone = tmp_path / "deleted.py"

    report = run_teeth_check(
        _spec(
            target,
            Mutation("gone", gone, "LIMIT = 25", "LIMIT = 999"),
            Mutation("cap", target, "LIMIT = 25", "LIMIT = 999"),
        ),
        runner=_killing_runner(),
    )

    assert [(m.label, m.status) for m in report.mutants] == [
        ("gone", "not-applied"),
        ("cap", "killed"),
    ]
    assert report.mutants[0].detail == f"file not found: {gone}"
    assert _exit_code(report) == 1


def test_a_target_file_that_is_not_utf8_is_not_applied_and_the_run_continues(
    target: Path, tmp_path: Path
) -> None:
    """A target that reads but will not decode is as unmutable as a missing one.

    The decode error escaped as a traceback, throwing away the verdict of
    every row after it. It must name the path, not a byte offset in an
    unnamed file, and leave the file exactly as it was.
    """
    latin1 = tmp_path / "latin1.py"
    original = "LIMIT = 25  # café\n".encode("latin-1")
    latin1.write_bytes(original)

    report = run_teeth_check(
        _spec(
            target,
            Mutation("latin1", latin1, "LIMIT = 25", "LIMIT = 999"),
            Mutation("cap", target, "LIMIT = 25", "LIMIT = 999"),
        ),
        runner=_killing_runner(),
    )

    assert [(m.label, m.status) for m in report.mutants] == [
        ("latin1", "not-applied"),
        ("cap", "killed"),
    ]
    assert report.mutants[0].detail == f"not UTF-8: {latin1}"
    assert _exit_code(report) == 1
    assert latin1.read_bytes() == original


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
# Line endings
#
# ``read_text`` translates ``\r\n`` to ``\n``. A restore written from its
# result rewrote every line of a Windows-authored file, leaving a whole-file
# diff on a file the run claims to leave byte-identical. Found on a 990-line
# CRLF source that had to stay verbatim.
# ---------------------------------------------------------------------------


@pytest.fixture
def crlf_target(tmp_path: Path) -> Path:
    src = tmp_path / "mod.py"
    src.write_bytes(b"LIMIT = 25\r\nGUARD = True\r\n")
    return src


def test_restores_a_crlf_file_byte_for_byte(crlf_target: Path) -> None:
    before = hashlib.sha256(crlf_target.read_bytes()).hexdigest()

    run_teeth_check(
        _spec(crlf_target, Mutation("cap", crlf_target, "LIMIT = 25", "LIMIT = 1")),
        runner=_killing_runner(),
    )

    assert hashlib.sha256(crlf_target.read_bytes()).hexdigest() == before


def test_a_newline_anchor_mutates_a_crlf_file_in_its_own_line_endings(
    crlf_target: Path,
) -> None:
    """Reading the source verbatim must not strand every spec written with ``\\n``.

    The anchor still resolves, and the mutant on disk keeps the file's CRLF,
    so it differs from the source only where the spec said.
    """
    on_disk: list[bytes] = []
    killing = _killing_runner()

    def runner(cmd: list[str]) -> tuple[int, str]:
        on_disk.append(crlf_target.read_bytes())
        return killing(cmd)

    report = run_teeth_check(
        _spec(
            crlf_target,
            Mutation(
                "cap",
                crlf_target,
                "LIMIT = 25\nGUARD = True",
                "LIMIT = 1\nGUARD = True",
            ),
        ),
        runner=runner,
    )

    assert [m.status for m in report.mutants] == ["killed"]
    assert on_disk[-1] == b"LIMIT = 1\r\nGUARD = True\r\n"


def test_apply_mutation_leaves_mixed_line_endings_alone_outside_the_anchor() -> None:
    """A CRLF file with LF lines added elsewhere must not be re-encoded wholesale."""
    text = "LIMIT = 25\r\nGUARD = True\r\nTAIL = 0\n"

    out = apply_mutation(text, "LIMIT = 25\nGUARD = True", "LIMIT = 1\nGUARD = True")

    assert out == "LIMIT = 1\r\nGUARD = True\r\nTAIL = 0\n"


@pytest.mark.parametrize("source_eol", ["\n", "\r\n"], ids=["lf-source", "crlf-source"])
@pytest.mark.parametrize("anchor_eol", ["\n", "\r\n"], ids=["lf-anchor", "crlf-anchor"])
def test_apply_mutation_ignores_the_anchors_line_endings(
    source_eol: str, anchor_eol: str
) -> None:
    """A spec resolves whichever platform saved the file or wrote the spec."""
    text = f"LIMIT = 25{source_eol}GUARD = True{source_eol}"

    out = apply_mutation(
        text, f"LIMIT = 25{anchor_eol}GUARD", f"LIMIT = 1{anchor_eol}GUARD"
    )

    assert out == f"LIMIT = 1{source_eol}GUARD = True{source_eol}"


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


def test_check_anchors_reports_a_missing_target_file_and_checks_the_rest(
    target: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A deleted or renamed target is a spec error on that mutant, not a crash.

    A traceback printed no verdict at all: the mutant that broke went
    unnamed, and every other mutant in the spec went unchecked.
    """
    gone = (tmp_path / "deleted.py").resolve()
    spec_path = _write_spec(
        tmp_path, [_mutant(label="gone", file="deleted.py"), _mutant()]
    )

    code = main(["--check-anchors", "--json", str(spec_path)])

    assert code == 1
    outcomes = {o["label"]: o["error"] for o in json.loads(capsys.readouterr().out)}
    assert outcomes["cap"] is None
    assert outcomes["gone"] == f"file not found: {gone}"


def test_check_anchors_reports_a_target_that_is_not_a_readable_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Any failure to read the target is the same spec error as a missing one.

    A directory where the file was expected can no more be mutated than a
    deleted file can, so it is reported on its row rather than as a crash.
    """
    (tmp_path / "pkg").mkdir()
    spec_path = _write_spec(tmp_path, [_mutant(label="dir", file="pkg")])

    code = main(["--check-anchors", "--json", str(spec_path)])

    assert code == 1
    [outcome] = json.loads(capsys.readouterr().out)
    assert outcome["label"] == "dir"
    assert outcome["error"].startswith(f"cannot read {(tmp_path / 'pkg').resolve()}: ")


def test_check_anchors_reports_a_target_that_is_not_utf8_and_checks_the_rest(
    target: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A binary or non-UTF-8 target is that row's error, not a crash.

    The ``make check-teeth-anchors`` gate runs this path with ``--json``; a
    traceback there named no mutant and left every other one unchecked.
    """
    (tmp_path / "blob.bin").write_bytes(b"\x89PNG\r\n\x1a\n\xff\xfe")
    blob = (tmp_path / "blob.bin").resolve()
    spec_path = _write_spec(
        tmp_path, [_mutant(label="blob", file="blob.bin"), _mutant()]
    )

    code = main(["--check-anchors", "--json", str(spec_path)])

    assert code == 1
    outcomes = {o["label"]: o["error"] for o in json.loads(capsys.readouterr().out)}
    assert outcomes["cap"] is None
    assert outcomes["blob"] == f"not UTF-8: {blob}"


@pytest.mark.parametrize(
    ("source", "find"),
    [
        (b"LIMIT = 25\r\nGUARD = True\r\n", "LIMIT = 25\nGUARD"),
        (b"LIMIT = 25\r\nGUARD = True\r\n", "LIMIT = 25\r\nGUARD"),
        (b"LIMIT = 25\rGUARD = True\r", "LIMIT = 25\nGUARD"),
    ],
    ids=["crlf-source-lf-anchor", "crlf-source-crlf-anchor", "cr-source-lf-anchor"],
)
def test_check_anchors_agrees_with_the_run(
    tmp_path: Path, source: bytes, find: str
) -> None:
    """An anchor the fast check passes must apply in the run, and vice versa.

    Reading the file differently from the run would let a gate go green on a
    spec whose every row then scores ``not-applied``.
    """
    (tmp_path / "mod.py").write_bytes(source)
    spec_path = _write_spec(tmp_path, [_mutant(find=find, replace=find)])

    anchors_resolve = main(["--check-anchors", str(spec_path)]) == 0
    report = run_teeth_check(load_spec(spec_path), runner=_killing_runner())

    assert anchors_resolve == (report.mutants[0].status != "not-applied")


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


# ---------------------------------------------------------------------------
# Anchor preflight on a full run
#
# A full run costs one test-suite run per row; resolving every anchor costs
# milliseconds. Scoring a stale row `not-applied` only when the loop reaches
# it spent a whole run (6.6 minutes on the 60-row mr-preflight spec) to learn
# what `--check-anchors` knew up front, and a run with any unapplied row can
# never be the recorded tally. So the CLI resolves every anchor before the
# baseline and refuses outright.
# ---------------------------------------------------------------------------


def _poison_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    def _poisoned(cmd: list[str]) -> tuple[int, str]:
        raise AssertionError(f"ran a command it should have refused: {cmd}")

    monkeypatch.setattr("teeth_check._default_runner", _poisoned)


def test_a_full_run_refuses_a_stale_anchor_before_running_anything(
    target: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Every stale row is named, not just the first, so one repair pass fixes all."""
    spec_path = _write_spec(
        tmp_path,
        [
            _mutant(label="first stale", find="GONE = 1", replace="GONE = 2"),
            _mutant(),
            _mutant(label="second stale", file="deleted.py"),
        ],
    )
    _poison_runner(monkeypatch)

    code = main([str(spec_path)])

    assert code == 2
    err = capsys.readouterr().err
    assert "first stale: anchor not found" in err
    assert f"second stale: file not found: {(tmp_path / 'deleted.py').resolve()}" in err
    assert "cap:" not in err


# ---------------------------------------------------------------------------
# --changed-since: the inner loop of a fix round
#
# A review-fix round touches a handful of rows (the fix's new tooth, the rows
# it re-anchored) and a full run re-scores all of them. `--changed-since REV`
# runs only rows added or edited in the spec since REV, plus every declared
# control, so the round is verified in seconds. It is never the tally: the
# count a pull request carries comes from one full run at the end.
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> None:
    import subprocess

    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


_HELD_CONTROL = _mutant(
    label="[control] rewrite GUARD in place",
    find="GUARD = True",
    replace="GUARD = True",
    expect="survived",
    why="Identical text; nothing changes.",
)


@pytest.fixture
def committed_spec(target: Path, tmp_path: Path) -> Path:
    """A spec committed at HEAD with two rows and a control."""
    spec_path = _write_spec(
        tmp_path,
        [
            _mutant(),
            _mutant(label="guard", find="GUARD = True", replace="GUARD = False"),
            _HELD_CONTROL,
        ],
    )
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "spec")
    return spec_path


def _labels_run(capsys: pytest.CaptureFixture[str]) -> list[str]:
    return [m["label"] for m in json.loads(capsys.readouterr().out)["mutants"]]


def test_changed_since_runs_only_edited_and_added_rows_plus_controls(
    committed_spec: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`cap` is byte-identical to HEAD, so it must not run."""
    _write_spec(
        tmp_path,
        [
            _mutant(),
            _mutant(label="guard", find="GUARD = True", replace="GUARD = None"),
            _HELD_CONTROL,
            _mutant(label="zero cap", replace="LIMIT = 0"),
        ],
    )
    monkeypatch.setattr("teeth_check._default_runner", _killing_runner())

    main(["--changed-since", "HEAD", "--json", str(committed_spec)])

    assert _labels_run(capsys) == ["guard", "[control] rewrite GUARD in place", "zero cap"]


def test_a_partial_run_says_it_is_not_the_tally(
    committed_spec: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A partial matrix pasted into a pull request would read as the full count."""
    _write_spec(
        tmp_path,
        [
            _mutant(),
            _mutant(label="guard", find="GUARD = True", replace="GUARD = None"),
            _HELD_CONTROL,
        ],
    )
    monkeypatch.setattr("teeth_check._default_runner", _killing_runner())

    main(["--changed-since", "HEAD", str(committed_spec)])
    text = capsys.readouterr().out
    monkeypatch.setattr("teeth_check._default_runner", _killing_runner())
    main(["--changed-since", "HEAD", "--json", str(committed_spec)])
    data = json.loads(capsys.readouterr().out)

    assert text.startswith("PARTIAL: 2 of 3 rows (changed since HEAD, plus controls)")
    assert "not the tally" in text.splitlines()[0]
    assert data["partial"] == {"ran": 2, "of": 3, "changed_since": "HEAD"}


def test_changed_since_still_refuses_a_stale_anchor_on_a_row_it_would_skip(
    committed_spec: Path,
    target: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The case a fix round produces: the code moved, the row did not.

    `cap` is unchanged since HEAD, so it would not run, but the fix rewrote
    the line it anchors on. The fix round is where that gets found.
    """
    target.write_text("LIMIT = 30\nGUARD = True\n")
    _write_spec(
        tmp_path,
        [
            _mutant(),
            _mutant(label="guard", find="GUARD = True", replace="GUARD = None"),
            _HELD_CONTROL,
        ],
    )
    _poison_runner(monkeypatch)

    code = main(["--changed-since", "HEAD", str(committed_spec)])

    assert code == 2
    assert "cap: anchor not found" in capsys.readouterr().err


def test_changed_since_refuses_when_no_row_changed(
    committed_spec: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Controls alone verify nothing; a clean exit here would read as a pass."""
    _poison_runner(monkeypatch)

    code = main(["--changed-since", "HEAD", str(committed_spec)])

    assert code == 2
    assert "no rows added or edited since HEAD" in capsys.readouterr().err


def test_a_spec_absent_at_the_revision_runs_every_row_as_new(
    committed_spec: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A spec first written on this branch is all new rows: a full run, not partial."""
    fresh = tmp_path / "fresh.teeth.json"
    fresh.write_text(committed_spec.read_text())
    monkeypatch.setattr("teeth_check._default_runner", _killing_runner())

    main(["--changed-since", "HEAD", "--json", str(fresh)])
    data = json.loads(capsys.readouterr().out)

    assert [m["label"] for m in data["mutants"]] == [
        "cap",
        "guard",
        "[control] rewrite GUARD in place",
    ]
    assert "partial" not in data


def test_changed_since_refuses_a_revision_that_does_not_exist(
    committed_spec: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A typo must not read as 'the spec is new here' and quietly run every row."""
    _poison_runner(monkeypatch)

    code = main(["--changed-since", "no-such-rev", str(committed_spec)])

    assert code == 2
    assert "no-such-rev" in capsys.readouterr().err


def test_changed_since_refuses_a_spec_outside_a_git_repository(
    target: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    spec_path = _write_spec(tmp_path, [_mutant()])
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    _poison_runner(monkeypatch)

    code = main(["--changed-since", "HEAD", str(spec_path)])

    assert code == 2
    assert "HEAD" in capsys.readouterr().err


def test_a_partial_run_does_not_compute_never_killed_tests(
    target: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A test that kills only a skipped row would be named as killing nothing.

    `test_cap` kills `cap`, which is unchanged and does not run, so against
    the selected rows alone it looks like dead weight.
    """
    rows = [_mutant(), _mutant(label="guard", find="GUARD = True", replace="GUARD = False")]
    spec_path = tmp_path / "spec.json"

    def write(rows: list[dict]) -> None:
        spec_path.write_text(
            json.dumps(
                {
                    "test_command": ["pytest", "-q"],
                    "collect_command": ["pytest", "--collect-only", "-q"],
                    "mutants": rows,
                }
            )
        )

    write(rows)
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "spec")
    write([rows[0], _mutant(label="guard", find="GUARD = True", replace="GUARD = None")])

    def runner() -> object:
        test_runs = 0

        def run(cmd: list[str]) -> tuple[int, str]:
            nonlocal test_runs
            if "--collect-only" in cmd:
                return 0, "tests/test_a.py::test_cap\ntests/test_a.py::test_guard\n"
            test_runs += 1
            if test_runs == 1:  # baseline
                return 0, "2 passed in 0.1s\n"
            return 1, "FAILED tests/test_a.py::test_guard\n1 failed, 1 passed in 0.1s\n"

        return run

    monkeypatch.setattr("teeth_check._default_runner", runner())
    main(["--changed-since", "HEAD", str(spec_path)])
    text = capsys.readouterr().out
    monkeypatch.setattr("teeth_check._default_runner", runner())
    main(["--changed-since", "HEAD", "--json", str(spec_path)])
    data = json.loads(capsys.readouterr().out)

    assert data["never_killed"] is None
    assert "never-killed tests: not computed (partial run)" in text


@pytest.mark.parametrize(
    "committed",
    [
        "not json",
        '{"test_command": ["x"]}',
        '{"test_command": ["x"], "mutants": {}}',
        '{"test_command": ["x"], "mutants": "legacy"}',
        '{"test_command": ["x"], "mutants": ["a row that is not an object"]}',
        '["a spec that is not an object"]',
    ],
    ids=["invalid-json", "no-mutants", "mutants-object", "mutants-string", "row-string", "top-level-list"],
)
def test_changed_since_refuses_a_spec_it_cannot_read_at_the_revision(
    target: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    committed: str,
) -> None:
    """A traceback exits 1, the code for 'lacks teeth'; a refusal must exit 2."""
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(committed)
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "broken spec")
    _write_spec(tmp_path, [_mutant()])
    _poison_runner(monkeypatch)

    code = main(["--changed-since", "HEAD", str(spec_path)])

    assert code == 2
    assert "HEAD" in capsys.readouterr().err


def test_changed_since_follows_a_committed_symlink_to_the_spec(
    committed_spec: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Through a symlink git shows the link's own text, not the spec."""
    link = tmp_path / "link.json"
    link.symlink_to("spec.json")
    _git(tmp_path, "add", "link.json")
    _git(tmp_path, "commit", "-q", "-m", "link")
    _write_spec(
        tmp_path,
        [
            _mutant(),
            _mutant(label="guard", find="GUARD = True", replace="GUARD = None"),
            _HELD_CONTROL,
        ],
    )
    monkeypatch.setattr("teeth_check._default_runner", _killing_runner())

    main(["--changed-since", "HEAD", "--json", str(link)])

    assert _labels_run(capsys) == ["guard", "[control] rewrite GUARD in place"]


def test_a_changed_test_command_since_the_revision_runs_every_row(
    committed_spec: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A new test command can flip any row's verdict, edited or not."""
    spec = json.loads(committed_spec.read_text())
    spec["test_command"] = ["pytest", "-q", "-k", "cap"]
    committed_spec.write_text(json.dumps(spec))
    monkeypatch.setattr("teeth_check._default_runner", _killing_runner())

    main(["--changed-since", "HEAD", "--json", str(committed_spec)])
    data = json.loads(capsys.readouterr().out)

    assert [m["label"] for m in data["mutants"]] == [
        "cap",
        "guard",
        "[control] rewrite GUARD in place",
    ]
    assert "partial" not in data


def test_a_row_copied_verbatim_since_the_revision_counts_as_added(
    committed_spec: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Each committed row matches one current row, not every copy of it."""
    spec = json.loads(committed_spec.read_text())
    spec["mutants"].append(spec["mutants"][0])
    committed_spec.write_text(json.dumps(spec))
    monkeypatch.setattr("teeth_check._default_runner", _killing_runner())

    main(["--changed-since", "HEAD", "--json", str(committed_spec)])

    assert _labels_run(capsys) == ["[control] rewrite GUARD in place", "cap"]


def test_check_anchors_with_changed_since_is_a_usage_error(
    committed_spec: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Checking anchors ignored the revision, so a bogus one exited 0 unread."""
    with pytest.raises(SystemExit) as exc:
        main(["--check-anchors", "--changed-since", "no-such-rev", str(committed_spec)])

    assert exc.value.code == 2
    assert "--changed-since" in capsys.readouterr().err


@pytest.mark.parametrize("key", ["label", "file", "find", "replace"])
def test_load_spec_refuses_a_mutant_missing_a_required_key(
    tmp_path: Path, key: str
) -> None:
    m = _mutant()
    del m[key]
    with pytest.raises(SpecError, match=f"required key '{key}'"):
        load_spec(_write_spec(tmp_path, [m]))


@pytest.mark.parametrize("key", ["label", "file", "find", "replace"])
def test_main_refuses_a_mutant_missing_a_required_key(
    tmp_path: Path, key: str, capsys: pytest.CaptureFixture[str]
) -> None:
    m = _mutant()
    del m[key]
    code = main([str(_write_spec(tmp_path, [m]))])
    assert code == 2
    err = capsys.readouterr().err
    assert err.startswith("refusing to run: ")
    assert f"required key '{key}'" in err


@pytest.mark.parametrize("key", ["file", "find", "replace"])
def test_missing_key_refusal_names_the_offending_mutant_label(
    tmp_path: Path, key: str
) -> None:
    m = _mutant(label="the-offending-row")
    del m[key]
    with pytest.raises(SpecError, match="the-offending-row"):
        load_spec(_write_spec(tmp_path, [m]))


def test_load_spec_accepts_an_empty_replace(tmp_path: Path) -> None:
    spec = load_spec(_write_spec(tmp_path, [_mutant(replace="")]))
    assert spec.mutants[0].replace == ""


def test_load_spec_passes_a_null_replace_through_unrefused(tmp_path: Path) -> None:
    # Issue #1073 is silent on null; this pins current behavior (key present
    # means accepted), it does not endorse it.
    spec = load_spec(_write_spec(tmp_path, [_mutant(replace=None)]))
    assert spec.mutants[0].replace is None


# ---------------------------------------------------------------------------
# Signal-safe restore, one run per target, recovery of a killed run (#1195)
#
# The restore used to live in a `finally`, which CPython's default SIGTERM
# disposition skips: `pkill` left the mutant on disk and the test command
# running, and a second run then read that mutant as its "original" and made
# it permanent. Nothing here may touch the real ~/.workshop, so every test in
# this module gets a throwaway state directory.
# ---------------------------------------------------------------------------

import base64  # noqa: E402
import fcntl  # noqa: E402
import os  # noqa: E402
import signal  # noqa: E402
import subprocess  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

import teeth_check as tc  # noqa: E402

ORIGINAL = "LIMIT = 25\nGUARD = True\n"
MUTANT_TEXT = "LIMIT = 999\nGUARD = True\n"


@pytest.fixture(autouse=True)
def _state_dir(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Path:
    state = tmp_path_factory.mktemp("teeth-state")
    monkeypatch.setenv("TEETH_CHECK_STATE_DIR", str(state))
    return state


def _state() -> Path:
    return Path(os.environ["TEETH_CHECK_STATE_DIR"])


def _lock_path(target: Path) -> Path:
    digest = hashlib.sha256(str(target.resolve()).encode()).hexdigest()
    return _state() / "locks" / f"{digest}.lock"


def _record(target: Path) -> dict:
    return json.loads(_lock_path(target).read_text())


def _write_journal(
    target: Path, *, original: bytes, mutant: bytes, pid: int = 2_000_000
) -> None:
    """Leave the lock file a hard-killed run would have left behind."""
    lock = _lock_path(target)
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(
        json.dumps(
            {
                "pid": pid,
                "path": str(target.resolve()),
                "original_b64": base64.b64encode(original).decode(),
                "original_sha256": hashlib.sha256(original).hexdigest(),
                "mutant_sha256": hashlib.sha256(mutant).hexdigest(),
            }
        )
    )


def _hold_lock(target: Path, record: dict | None) -> int:
    """Take the lock as another live run would; return the fd to release."""
    lock = _lock_path(target)
    lock.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if record is not None:
        os.write(fd, json.dumps(record).encode())
    return fd


def _green(cmd: list[str]) -> tuple[int, str]:
    return 0, "2 passed in 0.1s\n"


def _mutation(target: Path) -> Mutation:
    return Mutation("cap", target, "LIMIT = 25", "LIMIT = 999")


def _cli_spec(tmp_path: Path, target: Path, test_command: list[str]) -> Path:
    spec = tmp_path / "cli-spec.json"
    spec.write_text(
        json.dumps(
            {
                "test_command": test_command,
                "mutants": [
                    {
                        "label": "cap",
                        "file": target.name,
                        "find": "LIMIT = 25",
                        "replace": "LIMIT = 999",
                        "oracle": "real",
                    }
                ],
            }
        )
    )
    return spec


# --- B1: SIGTERM and SIGHUP restore; library callers get no handlers -------


def test_main_installs_term_and_hup_handlers_and_puts_them_back(
    target: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sentinel = lambda signum, frame: None  # noqa: E731
    prior_term = signal.signal(signal.SIGTERM, sentinel)
    prior_hup = signal.signal(signal.SIGHUP, sentinel)
    seen: list[object] = []

    def runner(cmd: list[str]) -> tuple[int, str]:
        seen.append((signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGHUP)))
        return 0, "ok\n"

    monkeypatch.setattr("teeth_check._default_runner", runner)
    try:
        main([str(_cli_spec(tmp_path, target, ["pytest"]))])
        after = (signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGHUP))
    finally:
        signal.signal(signal.SIGTERM, prior_term)
        signal.signal(signal.SIGHUP, prior_hup)

    assert seen, "the runner never ran"
    assert all(s[0] is not sentinel and s[1] is not sentinel for s in seen)
    assert after == (sentinel, sentinel)


def test_library_callers_get_no_handlers(target: Path) -> None:
    seen: list[object] = []
    before = (signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGHUP))

    def runner(cmd: list[str]) -> tuple[int, str]:
        seen.append((signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGHUP)))
        return 0, "ok\n"

    run_teeth_check(_spec(target, _mutation(target)), runner=runner)

    assert seen and all(s == before for s in seen)


@pytest.mark.parametrize("signum", [signal.SIGTERM, signal.SIGHUP])
def test_a_signal_mid_mutant_restores_and_exits_128_plus_signum(
    target: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    signum: signal.Signals,
) -> None:
    calls: list[int] = []

    def runner(cmd: list[str]) -> tuple[int, str]:
        calls.append(1)
        if len(calls) == 2:  # the mutant is on disk
            assert target.read_text() == MUTANT_TEXT
            os.kill(os.getpid(), signum)
            time.sleep(5)  # main's handler raises long before this returns
        return 0, "ok\n"

    monkeypatch.setattr("teeth_check._default_runner", runner)
    # Without main's handler this signal would kill the pytest process itself;
    # a swallowing placeholder keeps a failing run a failure, not a vanished one.
    prior = signal.signal(signum, lambda s, f: None)
    try:
        code = main([str(_cli_spec(tmp_path, target, ["pytest"]))])
    finally:
        signal.signal(signum, prior)

    assert code == 128 + signum
    assert target.read_text() == ORIGINAL
    assert (
        f"interrupted by {signal.Signals(signum).name}; mutated files were restored"
        in capsys.readouterr().err
    )


def test_ctrl_c_mid_mutant_restores_and_exits_130(
    target: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[int] = []

    def runner(cmd: list[str]) -> tuple[int, str]:
        calls.append(1)
        if len(calls) == 2:
            raise KeyboardInterrupt
        return 0, "ok\n"

    monkeypatch.setattr("teeth_check._default_runner", runner)

    try:
        code = main([str(_cli_spec(tmp_path, target, ["pytest"]))])
    except KeyboardInterrupt:  # would abort the whole pytest session
        pytest.fail("KeyboardInterrupt escaped main")

    assert code == 130
    assert target.read_text() == ORIGINAL
    assert "interrupted by SIGINT; mutated files were restored" in capsys.readouterr().err


# --- subprocess harness: the real CLI against a test command that sleeps ---

_SLEEPER = """\
import os, subprocess, sys, time
from pathlib import Path

target, pidfile = Path(sys.argv[1]), Path(sys.argv[2])
if "LIMIT = 999" in target.read_text():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"])
    pidfile.write_text(f"{os.getpid()} {child.pid}")
    time.sleep(300)
"""


def _wait_until(predicate: object, what: str, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():  # type: ignore[operator]
            return
        time.sleep(0.05)
    raise AssertionError(f"timed out after {timeout}s waiting for {what}")


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


class _LiveRun:
    """The CLI running against a test command that sleeps once mutated."""

    def __init__(self, tmp_path: Path, target: Path, cleanup: list[int]) -> None:
        self.tmp_path = tmp_path
        self.target = target
        self.pidfile = tmp_path / "pids.txt"
        script = tmp_path / "sleeper.py"
        script.write_text(_SLEEPER)
        self.spec = _cli_spec(
            tmp_path, target, [sys.executable, str(script), str(target), str(self.pidfile)]
        )
        self.env = {**os.environ, "TEETH_CHECK_STATE_DIR": str(_state())}
        self.out = (tmp_path / "live.out").open("w+")
        self.cleanup = cleanup
        self.proc = subprocess.Popen(
            [sys.executable, str(SCRIPTS_DIR / "teeth_check.py"), str(self.spec)],
            stdout=self.out,
            stderr=subprocess.STDOUT,
            env=self.env,
        )
        cleanup.append(self.proc.pid)

    def wait_mutated(self) -> tuple[int, int]:
        """Block until the mutant is on disk and the test command is running."""

        def ready() -> bool:
            try:
                runner_pid, child = self.pidfile.read_text().split()
                int(runner_pid), int(child)
            except (OSError, ValueError):
                return False
            return self.target.read_text() == MUTANT_TEXT

        _wait_until(ready, "the mutant to reach disk")
        test_pid, grandchild = (int(p) for p in self.pidfile.read_text().split())
        self.cleanup += [test_pid, grandchild]
        return test_pid, grandchild

    def finish(self) -> tuple[int, str]:
        code = self.proc.wait(timeout=180)
        self.out.seek(0)
        return code, self.out.read()


@pytest.fixture
def live(tmp_path: Path, target: Path):  # type: ignore[no-untyped-def]
    cleanup: list[int] = []
    run = _LiveRun(tmp_path, target, cleanup)
    yield run
    for pid in cleanup:
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    run.proc.wait(timeout=60)
    run.out.close()


@pytest.mark.parametrize("signum", [signal.SIGTERM, signal.SIGHUP])
def test_cli_signal_restores_the_target_and_kills_the_test_commands_group(
    live: _LiveRun, signum: signal.Signals
) -> None:
    """B1 and B2 against the real CLI: no mutant left, no orphaned child."""
    test_pid, grandchild = live.wait_mutated()

    live.proc.send_signal(signum)
    code, out = live.finish()

    assert live.target.read_text() == ORIGINAL
    assert code == 128 + signum, out
    assert (
        f"interrupted by {signal.Signals(signum).name}; mutated files were restored"
        in out
    )
    _wait_until(lambda: not _alive(test_pid), "the test command to die")
    _wait_until(lambda: not _alive(grandchild), "the test command's child to die")


# --- B2: the whole process group dies with the run -------------------------

_LEADER = """\
import os, signal, subprocess, sys, time
from pathlib import Path

pidfile, marker = Path(sys.argv[1]), Path(sys.argv[2])
signal.signal(signal.SIGTERM, signal.SIG_IGN)  # inherited across exec
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"])
def on_term(signum, frame):
    marker.write_text("got SIGTERM")
    os._exit(0)
signal.signal(signal.SIGTERM, on_term)
pidfile.write_text(f"{os.getpid()} {child.pid}")
time.sleep(300)
"""


def test_default_runner_terminates_then_kills_the_whole_group_on_an_interrupt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SIGTERM reaches the group first; what ignores it is SIGKILLed after the grace."""
    monkeypatch.setattr(tc, "_KILL_GRACE_SECONDS", 1, raising=False)
    script = tmp_path / "leader.py"
    script.write_text(_LEADER)
    pidfile, marker = tmp_path / "pids.txt", tmp_path / "marker.txt"
    pids: list[int] = []

    class Boom(BaseException):
        pass

    def raise_boom(signum: int, frame: object) -> None:
        raise Boom

    prior = signal.signal(signal.SIGUSR1, raise_boom)
    main_ident = threading.main_thread().ident

    def poke() -> None:
        def ready() -> bool:
            try:
                pids[:] = [int(p) for p in pidfile.read_text().split()]
            except (OSError, ValueError):
                return False
            return len(pids) == 2

        try:
            _wait_until(ready, "the leader to start")
        finally:
            signal.pthread_kill(main_ident, signal.SIGUSR1)

    thread = threading.Thread(target=poke)
    thread.start()
    try:
        with pytest.raises(Boom):
            _default_runner([sys.executable, str(script), str(pidfile), str(marker)])
    finally:
        signal.signal(signal.SIGUSR1, prior)
        thread.join()
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    assert len(pids) == 2
    assert marker.read_text() == "got SIGTERM"
    _wait_until(lambda: not _alive(pids[1]), "the signal-ignoring child to die")


# --- B3: one run per target, enforced by an OS lock ------------------------


def test_a_second_run_on_a_locked_target_refuses_before_running_anything(
    target: Path,
) -> None:
    fd = _hold_lock(target, {"pid": 4242, "path": str(target.resolve())})
    try:
        with pytest.raises(tc.TargetLocked):
            run_teeth_check(
                _spec(target, _mutation(target), collect=True),
                runner=lambda cmd: pytest.fail(f"ran {cmd} on a locked target"),
            )
    finally:
        os.close(fd)

    assert target.read_text() == ORIGINAL


def test_main_names_the_holder_and_exits_2(
    target: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _poison_runner(monkeypatch)
    fd = _hold_lock(target, {"pid": 4242, "path": str(target.resolve())})
    try:
        code = main([str(_cli_spec(tmp_path, target, ["pytest"]))])
    finally:
        os.close(fd)

    assert code == 2
    assert (
        f"refusing to run: another teeth_check run (pid 4242) holds {target.resolve()}"
        in capsys.readouterr().err
    )


def test_main_says_pid_unknown_when_the_holder_left_no_record(
    target: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _poison_runner(monkeypatch)
    fd = _hold_lock(target, None)
    try:
        code = main([str(_cli_spec(tmp_path, target, ["pytest"]))])
    finally:
        os.close(fd)

    assert code == 2
    assert "(pid unknown)" in capsys.readouterr().err


def test_the_lock_is_released_when_the_run_returns_and_when_it_raises(
    target: Path,
) -> None:
    run_teeth_check(_spec(target, _mutation(target)), runner=_green)
    fd = _hold_lock(target, None)  # would raise BlockingIOError if still held
    os.close(fd)

    def boom(cmd: list[str]) -> tuple[int, str]:
        raise RuntimeError("test command exploded")

    with pytest.raises(RuntimeError):
        run_teeth_check(_spec(target, _mutation(target)), runner=boom)
    os.close(_hold_lock(target, None))


def test_each_distinct_target_is_locked_and_a_duplicate_is_locked_once(
    target: Path, tmp_path: Path
) -> None:
    other = tmp_path / "other.py"
    other.write_text("LIMIT = 25\n")
    held = _hold_lock(other, None)
    try:
        with pytest.raises(tc.TargetLocked):
            run_teeth_check(
                _spec(
                    target,
                    _mutation(target),
                    Mutation("again", target, "GUARD = True", "GUARD = False"),
                    _mutation(other),
                ),
                runner=_green,
            )
    finally:
        os.close(held)

    # `target` was free, so refusing on `other` must not leave it locked.
    os.close(_hold_lock(target, None))
    run_teeth_check(
        _spec(
            target,
            _mutation(target),
            Mutation("again", target, "GUARD = True", "GUARD = False"),
        ),
        runner=_green,
    )


def test_check_anchors_takes_no_lock(target: Path, tmp_path: Path) -> None:
    fd = _hold_lock(target, {"pid": 4242, "path": str(target.resolve())})
    try:
        assert main(["--check-anchors", str(_cli_spec(tmp_path, target, ["x"]))]) == 0
    finally:
        os.close(fd)


# --- B4: the lock file is a journal ---------------------------------------


def test_the_lock_file_journals_the_original_around_each_mutant(target: Path) -> None:
    states: list[dict] = []

    def runner(cmd: list[str]) -> tuple[int, str]:
        states.append(_record(target))
        return 0, "ok\n"

    run_teeth_check(_spec(target, _mutation(target), collect=True), runner=runner)

    resolved = str(target.resolve())
    original = ORIGINAL.encode()
    plain = {"pid": os.getpid(), "path": resolved}
    # collect, baseline: acquired, nothing mutated yet. Then the mutant run.
    assert states[0] == plain and states[1] == plain
    assert states[2] == {
        **plain,
        "original_b64": base64.b64encode(original).decode(),
        "original_sha256": hashlib.sha256(original).hexdigest(),
        "mutant_sha256": hashlib.sha256(MUTANT_TEXT.encode()).hexdigest(),
    }
    assert _record(target) == plain  # cleared after the restore


def test_the_journal_is_cleared_even_when_the_run_raises(target: Path) -> None:
    calls: list[int] = []

    def runner(cmd: list[str]) -> tuple[int, str]:
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("boom")
        return 0, "ok\n"

    with pytest.raises(RuntimeError):
        run_teeth_check(_spec(target, _mutation(target)), runner=runner)

    assert target.read_text() == ORIGINAL
    assert _record(target) == {"pid": os.getpid(), "path": str(target.resolve())}


# --- B5: recovery of a hard-killed run ------------------------------------


def test_a_run_restores_the_mutant_a_killed_run_left_and_says_so(
    target: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target.write_text(MUTANT_TEXT)
    _write_journal(target, original=ORIGINAL.encode(), mutant=MUTANT_TEXT.encode())
    cache = target.parent / "__pycache__"
    cache.mkdir()
    stale = cache / "mod.cpython-313.pyc"
    stale.write_bytes(b"mutant bytecode")
    seen: list[str] = []

    def runner(cmd: list[str]) -> tuple[int, str]:
        seen.append(target.read_text())
        return 0, "ok\n"

    run_teeth_check(_spec(target, _mutation(target)), runner=runner)

    assert seen[0] == ORIGINAL  # the baseline saw the recovered file
    assert target.read_text() == ORIGINAL
    assert not stale.exists()
    assert (
        f"recovered {target.resolve()}: restored the original a killed run "
        "(pid 2000000) left mutated" in capsys.readouterr().err
    )


def test_a_record_whose_file_already_holds_the_original_clears_silently(
    target: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_journal(target, original=ORIGINAL.encode(), mutant=MUTANT_TEXT.encode())

    run_teeth_check(_spec(target, _mutation(target)), runner=_green)

    assert target.read_text() == ORIGINAL
    assert "recovered" not in capsys.readouterr().err
    assert "mutant_sha256" not in _lock_path(target).read_text()


@pytest.mark.parametrize("missing", [False, True])
def test_a_file_edited_after_the_kill_is_never_written_and_the_original_is_saved(
    target: Path, missing: bool
) -> None:
    _write_journal(target, original=ORIGINAL.encode(), mutant=MUTANT_TEXT.encode())
    if missing:
        target.unlink()
    else:
        target.write_text("LIMIT = 25\nGUARD = True\n# edited by hand after the kill\n")
    before = None if missing else target.read_bytes()

    with pytest.raises(tc.RecoveryRefused):
        run_teeth_check(
            _spec(target, _mutation(target), collect=True),
            runner=lambda cmd: pytest.fail(f"ran {cmd} after a refusal"),
        )

    assert (target.read_bytes() if target.exists() else None) == before
    digest = hashlib.sha256(ORIGINAL.encode()).hexdigest()[:12]
    saved = _state() / "recovered" / f"mod.py.{digest}.orig"
    assert saved.read_bytes() == ORIGINAL.encode()
    assert "mutant_sha256" not in _lock_path(target).read_text()


def test_main_recovers_before_the_stale_anchor_preflight(
    target: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A mutant on disk makes its own anchor stale; recovery has to come first."""
    target.write_text(MUTANT_TEXT)
    _write_journal(target, original=ORIGINAL.encode(), mutant=MUTANT_TEXT.encode())
    monkeypatch.setattr("teeth_check._default_runner", _killing_runner())

    code = main([str(_cli_spec(tmp_path, target, ["pytest"]))])

    err = capsys.readouterr().err
    assert "anchor(s) no longer resolve" not in err
    assert "recovered" in err
    assert code == 0
    assert target.read_text() == ORIGINAL


def test_main_refuses_with_the_saved_path_and_exits_2(
    target: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _poison_runner(monkeypatch)
    _write_journal(target, original=ORIGINAL.encode(), mutant=MUTANT_TEXT.encode())
    target.write_text("LIMIT = 25\n# hand edit\n")

    code = main([str(_cli_spec(tmp_path, target, ["pytest"]))])

    digest = hashlib.sha256(ORIGINAL.encode()).hexdigest()[:12]
    saved = _state() / "recovered" / f"mod.py.{digest}.orig"
    assert code == 2
    assert (
        f"refusing to run: {target.resolve()} changed after a killed run left a "
        f"mutant in it; the original is saved at {saved}"
    ) in capsys.readouterr().err


def test_a_sigkilled_run_leaves_a_mutant_and_the_next_run_recovers_it(
    live: _LiveRun, tmp_path: Path
) -> None:
    test_pid, grandchild = live.wait_mutated()
    live.proc.kill()
    live.proc.wait(timeout=180)
    os.kill(grandchild, signal.SIGKILL)
    os.kill(test_pid, signal.SIGKILL)

    # Positive control: SIGKILL really did strand the mutant. Without this the
    # recovery assertions below could pass on a rig that never left one.
    assert live.target.read_text() == MUTANT_TEXT

    quick = _cli_spec(tmp_path, live.target, [sys.executable, "-c", "pass"])
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "teeth_check.py"), str(quick)],
        capture_output=True,
        text=True,
        env=live.env,
        timeout=180,
    )

    assert "recovered" in result.stderr
    assert live.target.read_text() == ORIGINAL
    assert result.returncode == 1  # the surviving mutant, not a refusal


# --- B6: a restore never clobbers a concurrent edit -----------------------


def test_a_restore_does_not_overwrite_an_edit_made_while_the_mutant_was_on_disk(
    target: Path,
) -> None:
    calls: list[int] = []
    edited = "LIMIT = 25\n# somebody's new work\n"

    def runner(cmd: list[str]) -> tuple[int, str]:
        calls.append(1)
        if len(calls) == 2:
            target.write_text(edited)
        return 0, "ok\n"

    with pytest.raises(tc.ConcurrentEdit):
        run_teeth_check(_spec(target, _mutation(target)), runner=runner)

    assert target.read_text() == edited
    digest = hashlib.sha256(ORIGINAL.encode()).hexdigest()[:12]
    assert (
        _state() / "recovered" / f"mod.py.{digest}.orig"
    ).read_bytes() == ORIGINAL.encode()
    assert _record(target) == {"pid": os.getpid(), "path": str(target.resolve())}


def test_a_target_deleted_mid_run_is_not_recreated(target: Path) -> None:
    calls: list[int] = []

    def runner(cmd: list[str]) -> tuple[int, str]:
        calls.append(1)
        if len(calls) == 2:
            target.unlink()
        return 0, "ok\n"

    with pytest.raises(tc.ConcurrentEdit):
        run_teeth_check(_spec(target, _mutation(target)), runner=runner)

    assert not target.exists()
    digest = hashlib.sha256(ORIGINAL.encode()).hexdigest()[:12]
    assert (_state() / "recovered" / f"mod.py.{digest}.orig").exists()


def test_main_reports_a_concurrent_edit_and_exits_2(
    target: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[int] = []

    def runner(cmd: list[str]) -> tuple[int, str]:
        calls.append(1)
        if len(calls) == 2:
            target.write_text("LIMIT = 25\n# new work\n")
        return 0, "ok\n"

    monkeypatch.setattr("teeth_check._default_runner", runner)

    code = main([str(_cli_spec(tmp_path, target, ["pytest"]))])

    digest = hashlib.sha256(ORIGINAL.encode()).hexdigest()[:12]
    saved = _state() / "recovered" / f"mod.py.{digest}.orig"
    assert code == 2
    assert (
        f"refusing to run: {target.resolve()} was edited while a mutant was on "
        f"disk; left as found, the original is saved at {saved}"
    ) in capsys.readouterr().err


# --- B7: --recover ---------------------------------------------------------


def test_recover_reports_clean_and_runs_nothing(
    target: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _poison_runner(monkeypatch)

    code = main(["--recover", str(_cli_spec(tmp_path, target, ["pytest"]))])

    assert code == 0
    assert capsys.readouterr().out.splitlines() == [f"{target.resolve()}: clean"]
    assert target.read_text() == ORIGINAL


def test_recover_restores_a_stranded_mutant(
    target: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _poison_runner(monkeypatch)
    target.write_text(MUTANT_TEXT)
    _write_journal(target, original=ORIGINAL.encode(), mutant=MUTANT_TEXT.encode())

    code = main(["--recover", str(_cli_spec(tmp_path, target, ["pytest"]))])

    assert code == 0
    assert capsys.readouterr().out.splitlines() == [f"{target.resolve()}: recovered"]
    assert target.read_text() == ORIGINAL


def test_recover_reports_every_target_and_exits_2_on_any_refusal(
    target: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _poison_runner(monkeypatch)
    locked = tmp_path / "locked.py"
    locked.write_text("LIMIT = 25\n")
    edited = tmp_path / "edited.py"
    edited.write_text("LIMIT = 25\n# hand edit\n")
    _write_journal(edited, original=b"LIMIT = 25\n", mutant=b"LIMIT = 999\n")
    target.write_text(MUTANT_TEXT)
    _write_journal(target, original=ORIGINAL.encode(), mutant=MUTANT_TEXT.encode())
    spec = tmp_path / "multi.json"
    spec.write_text(
        json.dumps(
            {
                "test_command": ["pytest"],
                "mutants": [
                    {
                        "label": name,
                        "file": f,
                        "find": "LIMIT = 25",
                        "replace": "LIMIT = 999",
                        "oracle": "real",
                    }
                    for name, f in [
                        ("a", "locked.py"),
                        ("b", "edited.py"),
                        ("c", "mod.py"),
                        ("d", "mod.py"),
                    ]
                ],
            }
        )
    )
    fd = _hold_lock(locked, {"pid": 31337, "path": str(locked.resolve())})
    try:
        code = main(["--recover", str(spec)])
    finally:
        os.close(fd)

    lines = capsys.readouterr().out.splitlines()
    assert code == 2
    assert len(lines) == 3  # one per distinct target
    assert any("pid 31337" in line and str(locked.resolve()) in line for line in lines)
    assert any("changed after a killed run" in line for line in lines)
    assert f"{target.resolve()}: recovered" in lines
    assert target.read_text() == ORIGINAL


def test_recover_is_exclusive_with_the_other_modes(
    target: Path, tmp_path: Path
) -> None:
    spec = str(_cli_spec(tmp_path, target, ["pytest"]))
    with pytest.raises(SystemExit) as exc:
        main(["--recover", "--check-anchors", spec])
    assert exc.value.code == 2


# ---------------------------------------------------------------------------
# Budgeted, resumable runs (--budget / --report)
#
# A 168-row spec at ~40 s a row takes hours and a worker may run for ten
# minutes. Hand-cut slice specs print a false never-killed list and mix
# verdicts from different trees. `--budget SECONDS` runs pending rows until the
# next would overrun and exits 3; a ledger keyed by the working-tree
# fingerprint (plus the settings) holds each row's verdict, so the tally comes
# from one tree and is only ever printed when every row is recorded.
# ---------------------------------------------------------------------------

import re  # noqa: E402

_FAKE_SUITE = '''\
import pathlib
import sys
import time

args = sys.argv[1:]


def opt(name):
    return args[args.index(name) + 1] if name in args else None


if "--collect" in args:
    print("t.py::test_cap\\nt.py::test_guard\\nt.py::test_extra")
    sys.exit(0)
if opt("--marker"):
    pathlib.Path(opt("--marker")).write_text("ran")
if opt("--log"):
    with open(opt("--log"), "a") as log:
        log.write("run\\n")
src = pathlib.Path("mod.py").read_text()
mutant = "LIMIT = 25" not in src or "GUARD = True" not in src
if mutant and "--sleep" in args:
    time.sleep(1.0)
if "GUARD = True" not in src and opt("--touch-on-guard"):
    pathlib.Path(opt("--touch-on-guard")).write_text("x")
if mutant and opt("--touch-many"):
    for i in range(int(opt("--touch-many"))):
        pathlib.Path(f"side_{i:02d}.txt").write_text("x")
failed = []
if "LIMIT = 25" not in src:
    failed.append("t.py::test_cap")
if "GUARD = True" not in src:
    failed.append("t.py::test_guard")
for name in failed:
    print("FAILED", name)
sys.exit(1 if failed else 0)
'''

_LEDGER_ROWS = {
    "cap": ("LIMIT = 25", "LIMIT = 999"),
    "guard": ("GUARD = True", "GUARD = False"),
    "survivor": ("OTHER = 1", "OTHER = 2"),
}


def _ledger_row(name: str, *, replace: str | None = None) -> dict:
    find, default_replace = _LEDGER_ROWS[name]
    return {
        "label": name,
        "file": "mod.py",
        "oracle": "real",
        "find": find,
        "replace": default_replace if replace is None else replace,
    }


def _write_ledger_spec(
    repo: Path, names: tuple[str, ...] = ("cap", "guard"), *flags: str, **over: object
) -> Path:
    spec = {
        "test_command": [sys.executable, "fake_suite.py", *flags],
        "collect_command": [sys.executable, "fake_suite.py", "--collect"],
        "mutants": [_ledger_row(n) for n in names],
        **over,
    }
    path = repo / "spec.json"
    path.write_text(json.dumps(spec))
    return path


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A committed git repo under tmp_path, cwd inside it, nothing inherited."""
    for var in ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE"):
        monkeypatch.delenv(var, raising=False)
    root = tmp_path / "repo"
    root.mkdir()
    (root / "mod.py").write_text("LIMIT = 25\nGUARD = True\nOTHER = 1\n")
    (root / "fake_suite.py").write_text(_FAKE_SUITE)
    (root / ".gitignore").write_text("__pycache__/\n")
    _write_ledger_spec(root)
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    monkeypatch.chdir(root)
    return root


def _cli(
    capsys: pytest.CaptureFixture[str], *args: object
) -> tuple[int, str, str]:
    rc = main([str(a) for a in args])
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


def _report_json(capsys: pytest.CaptureFixture[str], spec: Path) -> dict:
    rc, out, _ = _cli(capsys, "--report", "--json", spec)
    return json.loads(out)


def _ledger_lines(path: str | Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text().splitlines()]


def test_budget_runs_exactly_one_row_per_invocation_until_complete(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A tiny budget still runs one row, and each re-run picks up the next."""
    spec = _write_ledger_spec(repo, ("cap", "guard", "survivor"), "--sleep")

    rc, out, _ = _cli(capsys, "--budget", 0.001, spec)
    assert rc == 3
    assert out.splitlines()[0].startswith("INCOMPLETE: 1 of 3 rows recorded for tree ")
    assert out.splitlines()[0].endswith(" — re-run the same command; not the tally")

    rc, out, _ = _cli(capsys, "--budget", 0.001, spec)
    assert rc == 3
    assert out.splitlines()[0].startswith("INCOMPLETE: 2 of 3 rows recorded for tree ")

    rc, out, _ = _cli(capsys, "--budget", 0.001, spec)
    first = out.splitlines()[0]
    assert re.fullmatch(r"LEDGER: 3 of 3 rows for tree [0-9a-f]{12} \(.+\.jsonl\)", first)
    assert rc == 1  # the survivor is a finding, as in a single run


def test_an_incomplete_ledger_exits_3_whatever_the_recorded_rows_say(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = _write_ledger_spec(repo, ("cap", "guard"), "--sleep")

    rc, out, _ = _cli(capsys, "--budget", 0.001, spec)

    assert rc == 3  # the one recorded row was a clean kill
    assert "never-killed tests: not computed (incomplete ledger)" in out
    assert "cap" in out and "guard" not in out.split("\n", 1)[1]


def test_a_complete_clean_ledger_exits_0_and_a_rerun_runs_nothing(
    repo: Path, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    marker = tmp_path / "marker"
    spec = _write_ledger_spec(repo, ("cap", "guard"), "--marker", str(marker))

    rc, out, _ = _cli(capsys, "--budget", 1000, spec)
    assert rc == 0
    assert out.splitlines()[0].startswith("LEDGER: 2 of 2 rows for tree ")
    assert marker.exists()

    marker.unlink()
    rc, out, _ = _cli(capsys, "--budget", 1000, spec)
    assert rc == 0
    assert out.splitlines()[0].startswith("LEDGER: 2 of 2 rows for tree ")
    assert not marker.exists(), "nothing pending: no baseline, no collect, no row"


def test_json_carries_the_ledger_block_and_a_null_never_killed_when_incomplete(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = _write_ledger_spec(repo, ("cap", "guard"), "--sleep")

    rc, out, _ = _cli(capsys, "--json", "--budget", 0.001, spec)
    payload = json.loads(out)
    assert rc == 3
    assert payload["never_killed"] is None
    assert [m["label"] for m in payload["mutants"]] == ["cap"]
    assert payload["ledger"]["recorded"] == 1 and payload["ledger"]["of"] == 2
    assert re.fullmatch(r"[0-9a-f]{40}", payload["ledger"]["tree"])

    rc, out, _ = _cli(capsys, "--json", "--budget", 0.001, spec)
    payload = json.loads(out)
    assert rc == 0
    assert payload["never_killed"] == ["t.py::test_extra"]
    assert payload["ledger"]["recorded"] == 2 and payload["ledger"]["of"] == 2


def test_never_killed_after_several_invocations_equals_a_single_full_run(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = _write_ledger_spec(repo, ("cap", "guard", "survivor"), "--sleep")
    for _ in range(3):
        rc, out, _ = _cli(capsys, "--json", "--budget", 0.001, spec)
    ledgered = json.loads(out)

    rc, out, _ = _cli(capsys, "--json", spec)  # no ledger: one whole run
    single = json.loads(out)

    assert single["never_killed"] == ["t.py::test_extra"]
    assert ledgered["never_killed"] == single["never_killed"]
    assert [m["status"] for m in ledgered["mutants"]] == [
        m["status"] for m in single["mutants"]
    ]


def test_the_ledger_lives_under_the_state_dir_keyed_by_tree_and_settings(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = _write_ledger_spec(repo)
    payload = _report_json(capsys, spec)
    path = Path(payload["ledger"]["path"])

    settings = hashlib.sha256(
        json.dumps(
            {
                "schema": 1,
                "test_command": [sys.executable, "fake_suite.py"],
                "collect_command": [sys.executable, "fake_suite.py", "--collect"],
                "runner": "pytest",
                "cwd": ".",
                "spec": "spec.json",
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    assert path.parent == _state() / "ledgers"
    assert path.name == f"{payload['ledger']['tree']}-{settings[:16]}.jsonl"


def test_an_untracked_file_change_starts_a_fresh_ledger(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = _write_ledger_spec(repo)
    assert _cli(capsys, "--budget", 1000, spec)[0] == 0
    before = _report_json(capsys, spec)
    assert before["ledger"]["recorded"] == 2

    (repo / "notes.txt").write_text("new, untracked\n")
    after = _report_json(capsys, spec)

    assert after["ledger"]["recorded"] == 0
    assert after["ledger"]["tree"] != before["ledger"]["tree"]
    assert after["ledger"]["path"] != before["ledger"]["path"]


def test_an_ignored_file_does_not_change_the_fingerprint(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = _write_ledger_spec(repo)
    before = _report_json(capsys, spec)

    (repo / "__pycache__").mkdir()
    (repo / "__pycache__" / "x.pyc").write_bytes(b"junk")

    assert _report_json(capsys, spec)["ledger"]["tree"] == before["ledger"]["tree"]


def test_editing_one_spec_row_reruns_only_that_row(
    repo: Path, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    log = tmp_path / "runs.log"
    spec = _write_ledger_spec(repo, ("cap", "guard", "survivor"), "--log", str(log))
    assert _cli(capsys, "--budget", 1000, spec)[0] == 1
    assert len(log.read_text().splitlines()) == 1 + 3  # baseline + three rows

    log.unlink()
    text = json.loads(spec.read_text())
    text["mutants"][1] = _ledger_row("guard", replace="GUARD = None")
    spec.write_text(json.dumps(text))
    rc, out, _ = _cli(capsys, "--budget", 1000, spec)

    assert out.splitlines()[0].startswith("LEDGER: 3 of 3 rows")
    assert len(log.read_text().splitlines()) == 1 + 1  # baseline + the edited row


def test_identical_rows_are_keyed_apart_by_their_position(
    repo: Path, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    log = tmp_path / "runs.log"
    spec = _write_ledger_spec(repo, ("cap", "cap"), "--log", str(log))

    rc, out, _ = _cli(capsys, "--budget", 1000, spec)

    assert out.splitlines()[0].startswith("LEDGER: 2 of 2 rows")
    assert len(log.read_text().splitlines()) == 1 + 2


def test_a_changed_test_command_starts_a_fresh_ledger(
    repo: Path, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    spec = _write_ledger_spec(repo)
    assert _cli(capsys, "--budget", 1000, spec)[0] == 0
    before = _report_json(capsys, spec)

    _write_ledger_spec(repo, ("cap", "guard"), "--log", str(tmp_path / "other.log"))
    after = _report_json(capsys, spec)

    assert before["ledger"]["recorded"] == 2
    assert after["ledger"]["recorded"] == 0
    assert after["ledger"]["path"] != before["ledger"]["path"]


def test_committing_does_not_void_a_ledger(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = _write_ledger_spec(repo)
    (repo / "new.txt").write_text("untracked until committed\n")
    assert _cli(capsys, "--budget", 1000, spec)[0] == 0
    before = _report_json(capsys, spec)

    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "commit the new file")
    after = _report_json(capsys, spec)

    assert after["ledger"] == before["ledger"]
    assert after["ledger"]["recorded"] == 2


def test_a_separate_worktree_at_the_same_content_shares_the_ledger(
    repo: Path, capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch
) -> None:
    spec = _write_ledger_spec(repo)  # identical to the committed spec
    assert _cli(capsys, "--budget", 1000, spec)[0] == 0
    before = _report_json(capsys, spec)

    other = tmp_path / "other-worktree"
    _git(repo, "worktree", "add", "-q", "--detach", str(other))
    monkeypatch.chdir(other)
    after = _report_json(capsys, other / "spec.json")

    assert after["ledger"] == before["ledger"]


def test_a_tree_edit_during_a_row_refuses_and_records_nothing_for_that_row(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = _write_ledger_spec(
        repo, ("cap", "guard", "survivor"), "--touch-on-guard", "side.txt"
    )
    old = _report_json(capsys, spec)["ledger"]

    rc, out, err = _cli(capsys, "--budget", 1000, spec)

    assert rc == 2
    assert err.startswith("refusing to continue: the tree changed during the run (was ")
    assert "side.txt" in err
    assert "1 rows stay recorded under " in err
    assert "this row was not recorded" in err
    lines = _ledger_lines(old["path"])
    assert [(e["kind"], e.get("label")) for e in lines] == [
        ("collect", None),
        ("row", "cap"),
    ]
    assert (repo / "mod.py").read_text() == "LIMIT = 25\nGUARD = True\nOTHER = 1\n"


def test_an_interrupt_mid_row_records_nothing_for_that_row(
    repo: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _write_ledger_spec(repo, ("cap", "guard"))
    old = _report_json(capsys, spec)["ledger"]

    def runner(cmd: list[str]) -> tuple[int, str]:
        if "LIMIT = 25" not in (repo / "mod.py").read_text():
            raise KeyboardInterrupt
        return 0, ""

    monkeypatch.setattr(tc, "_default_runner", runner)
    rc, _, err = _cli(capsys, "--budget", 1000, spec)

    assert rc == 130
    assert "interrupted by SIGINT" in err
    assert [e["kind"] for e in _ledger_lines(old["path"])] == ["collect"]
    assert (repo / "mod.py").read_text() == "LIMIT = 25\nGUARD = True\nOTHER = 1\n"


def test_report_runs_no_command_and_reads_zero_rows_on_a_fresh_tree(
    repo: Path, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    marker = tmp_path / "marker"
    spec = _write_ledger_spec(repo, ("cap", "guard"), "--marker", str(marker))

    rc, out, _ = _cli(capsys, "--report", spec)

    assert rc == 3
    assert out.splitlines()[0].startswith("INCOMPLETE: 0 of 2 rows recorded for tree ")
    assert not marker.exists()
    assert not (_state() / "ledgers").exists() or not list(
        (_state() / "ledgers").glob("*.jsonl")
    )


def test_report_takes_no_lock(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = _write_ledger_spec(repo)
    held = tc._TargetLock((repo / "mod.py").resolve())
    held.acquire()
    try:
        rc, out, _ = _cli(capsys, "--report", spec)
    finally:
        held.release()

    assert rc == 3
    assert out.startswith("INCOMPLETE: 0 of 2")


def test_report_of_a_complete_ledger_is_the_tally(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = _write_ledger_spec(repo, ("cap", "guard", "survivor"))
    assert _cli(capsys, "--budget", 1000, spec)[0] == 1

    rc, out, _ = _cli(capsys, "--report", spec)

    assert rc == 1
    assert out.splitlines()[0].startswith("LEDGER: 3 of 3 rows for tree ")
    assert "SURVIVORS" in out and "t.py::test_extra" in out


def test_a_second_run_on_a_held_ledger_refuses_before_running_anything(
    repo: Path, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    marker = tmp_path / "marker"
    spec = _write_ledger_spec(repo, ("cap", "guard"), "--marker", str(marker))
    path = Path(_report_json(capsys, spec)["ledger"]["path"])
    held = tc._LedgerLock(path)
    held.acquire()
    try:
        rc, out, err = _cli(capsys, "--budget", 1000, spec)
    finally:
        held.release()

    assert rc == 2
    assert f"another teeth_check run holds ledger {path}" in err
    assert not marker.exists()
    assert (repo / "mod.py").read_text() == "LIMIT = 25\nGUARD = True\nOTHER = 1\n"


def test_fingerprinting_never_writes_the_real_index(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = _write_ledger_spec(repo)
    (repo / "untracked.txt").write_text("a plain `git add -A` would stage this\n")
    index = repo / ".git" / "index"
    before = index.read_bytes()

    _cli(capsys, "--report", spec)
    _cli(capsys, "--budget", 1000, spec)

    assert index.read_bytes() == before
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"], cwd=repo, capture_output=True, text=True
    ).stdout
    assert staged == ""


def test_a_truncated_last_ledger_line_is_ignored_and_the_next_row_still_lands(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = _write_ledger_spec(repo, ("cap", "guard"))
    assert _cli(capsys, "--budget", 1000, spec)[0] == 0
    path = Path(_report_json(capsys, spec)["ledger"]["path"])
    text = path.read_text()
    last = text.rstrip("\n").rsplit("\n", 1)[1]
    path.write_text(text[: text.rindex(last)] + last[: len(last) // 2])  # crash mid-write

    assert _report_json(capsys, spec)["ledger"]["recorded"] == 1

    rc, out, _ = _cli(capsys, "--budget", 1000, spec)
    assert rc == 0
    assert out.splitlines()[0].startswith("LEDGER: 2 of 2 rows")
    # Re-read the file: the row just appended must not have been glued onto the
    # partial line, or it is lost on disk while the run above still reports it.
    assert _report_json(capsys, spec)["ledger"]["recorded"] == 2


def test_unknown_kinds_and_rows_no_longer_in_the_spec_are_ignored(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = _write_ledger_spec(repo)
    assert _cli(capsys, "--budget", 1000, spec)[0] == 0
    path = Path(_report_json(capsys, spec)["ledger"]["path"])
    with path.open("a") as handle:
        handle.write(json.dumps({"kind": "from-the-future", "x": 1}) + "\n")
        handle.write(
            json.dumps(
                {"kind": "row", "key": "0" * 64 + ":0", "label": "gone", "result": {}, "seconds": 1}
            )
            + "\n"
        )

    payload = _report_json(capsys, spec)

    assert payload["ledger"]["recorded"] == 2
    assert [m["label"] for m in payload["mutants"]] == ["cap", "guard"]


def test_ledger_lines_are_collect_then_rows_with_seconds(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = _write_ledger_spec(repo)
    assert _cli(capsys, "--budget", 1000, spec)[0] == 0
    lines = _ledger_lines(_report_json(capsys, spec)["ledger"]["path"])

    assert lines[0] == {
        "kind": "collect",
        "collected": ["t.py::test_cap", "t.py::test_guard", "t.py::test_extra"],
    }
    assert [e["kind"] for e in lines[1:]] == ["row", "row"]
    assert all(re.fullmatch(r"[0-9a-f]{64}:0", e["key"]) for e in lines[1:])
    assert lines[1]["result"]["status"] == "killed"
    assert isinstance(lines[1]["seconds"], float)


@pytest.mark.parametrize("value", ["0", "-3", "soon", "nan"])
def test_budget_must_be_a_positive_number(
    repo: Path, capsys: pytest.CaptureFixture[str], value: str
) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--budget", value, str(repo / "spec.json")])

    assert exc.value.code == 2
    assert "greater than 0" in capsys.readouterr().err


@pytest.mark.parametrize(
    "other", [["--report"], ["--check-anchors"], ["--recover"], ["--changed-since", "HEAD"]]
)
def test_budget_is_exclusive_with_the_other_modes(
    repo: Path, capsys: pytest.CaptureFixture[str], other: list[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--budget", "5", *other, str(repo / "spec.json")])

    assert exc.value.code == 2
    assert "not allowed with" in capsys.readouterr().err


def test_report_is_exclusive_with_the_other_modes(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--report", "--check-anchors", str(repo / "spec.json")])

    assert exc.value.code == 2
    assert "not allowed with" in capsys.readouterr().err


@pytest.mark.parametrize("mode", ["--budget", "--report"])
def test_ledger_mode_refuses_a_spec_outside_a_git_worktree(
    target: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], mode: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for var in ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE"):
        monkeypatch.delenv(var, raising=False)
    spec = _cli_spec(tmp_path, target, ["pytest"])
    monkeypatch.chdir(tmp_path)
    argv = [mode, "5", str(spec)] if mode == "--budget" else [mode, str(spec)]

    rc = main(argv)

    assert rc == 2
    assert "refusing to run:" in capsys.readouterr().err
    assert target.read_text() == ORIGINAL


def test_ledger_mode_refuses_a_target_outside_the_worktree(
    repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    outside = tmp_path / "outside.py"
    outside.write_text("LIMIT = 25\n")
    spec = _write_ledger_spec(repo)
    data = json.loads(spec.read_text())
    data["mutants"][0]["file"] = "../outside.py"
    spec.write_text(json.dumps(data))

    for argv in (["--report", str(spec)], ["--budget", "5", str(spec)]):
        rc = main(argv)
        assert rc == 2
        assert "refusing to run:" in capsys.readouterr().err
    assert outside.read_text() == "LIMIT = 25\n"


def test_ledger_mode_refuses_a_working_directory_outside_the_worktree(
    repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = _write_ledger_spec(repo)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    for argv in (["--report", str(spec)], ["--budget", "5", str(spec)]):
        assert main(argv) == 2
        assert "refusing to run:" in capsys.readouterr().err


def test_a_run_without_ledger_flags_does_not_touch_the_ledger_dir(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = _write_ledger_spec(repo)

    rc, out, _ = _cli(capsys, spec)

    assert rc == 0
    assert out.startswith("mutant ")
    assert not (_state() / "ledgers").exists()


# ---------------------------------------------------------------------------
# Review fixes for the ledger: the budget's clock, the estimate, the key of an
# identical row, one collect per ledger, the changed-paths list, fsync, and the
# two git environment hardenings.
# ---------------------------------------------------------------------------


class _FakeClock:
    """A ``time`` stand-in whose ``monotonic`` moves only when a command ends."""

    def __init__(self) -> None:
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now

    def __getattr__(self, name: str) -> object:
        return getattr(time, name)


def _drive_clock(
    monkeypatch: pytest.MonkeyPatch, repo: Path, cost: object
) -> _FakeClock:
    """Make every test-command call take ``cost(mod_py_text)`` fake seconds.

    The runner is wrapped, not replaced: the real fake suite still runs, and the
    mutant is still on disk when ``cost`` reads ``mod.py`` after the call.
    """
    clock = _FakeClock()
    monkeypatch.setattr(tc, "time", clock)
    real = tc._default_runner

    def run(cmd: list[str]) -> tuple[int, str]:
        result = real(cmd)
        clock.now += cost((repo / "mod.py").read_text())  # type: ignore[operator]
        return result

    monkeypatch.setattr(tc, "_default_runner", run)
    return clock


_PRISTINE = "LIMIT = 25\nGUARD = True\nOTHER = 1\n"


def _four_rows(repo: Path) -> Path:
    spec = _write_ledger_spec(repo, ("cap", "guard", "survivor"))
    doc = json.loads(spec.read_text())
    doc["mutants"].append(_ledger_row("survivor", replace="OTHER = 3"))
    spec.write_text(json.dumps(doc))
    return spec


@pytest.mark.parametrize(
    ("rows", "cost", "budget", "recorded"),
    [
        pytest.param(
            4,
            lambda src: 1 if src == _PRISTINE else 10,
            25,
            2,
            id="uniform-rows",
        ),
        pytest.param(
            3,
            lambda src: 30 if "LIMIT = 999" in src else 1,
            35,
            1,
            id="one-slow-row",
        ),
    ],
)
def test_budget_counts_elapsed_time_across_rows(
    repo: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    rows: int,
    cost: object,
    budget: int,
    recorded: int,
) -> None:
    """The next row waits when the time already spent plus the slowest row seen overruns."""
    spec = _four_rows(repo) if rows == 4 else _write_ledger_spec(
        repo, ("cap", "guard", "survivor")
    )
    _drive_clock(monkeypatch, repo, cost)

    rc, out, _ = _cli(capsys, "--json", "--budget", budget, spec)

    assert json.loads(out)["ledger"]["recorded"] == recorded
    assert rc == 3


def test_the_estimate_uses_the_slowest_recorded_row(
    repo: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A later invocation knows an earlier one's slow row, though its baseline is fast."""
    spec = _write_ledger_spec(repo, ("cap", "guard", "survivor"))

    def cost(src: str) -> int:
        if "LIMIT = 999" in src:
            return 30
        if "GUARD = False" in src or "OTHER = 2" in src:
            return 10
        return 1

    _drive_clock(monkeypatch, repo, cost)
    assert _cli(capsys, "--budget", 0.001, spec)[0] == 3  # the 30 s row, alone

    rc, out, _ = _cli(capsys, "--json", "--budget", 35, spec)

    assert json.loads(out)["ledger"]["recorded"] == 2  # not 3: 11 s + 30 s > 35 s
    assert rc == 3


def test_identical_rows_each_run_when_the_budget_splits_them(
    repo: Path, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    log = tmp_path / "runs.log"
    spec = _write_ledger_spec(repo, ("cap", "cap"), "--log", str(log))

    assert _cli(capsys, "--budget", 0.001, spec)[0] == 3
    rc, out, _ = _cli(capsys, "--budget", 0.001, spec)

    assert rc == 0
    assert out.splitlines()[0].startswith("LEDGER: 2 of 2 rows")
    assert len(log.read_text().splitlines()) == 2 + 2  # a baseline and a row, twice


def test_collect_runs_once_per_ledger(
    repo: Path, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    counter = tmp_path / "collects"
    script = (
        "import pathlib, sys\n"
        "pathlib.Path(sys.argv[1]).open('a').write('c\\n')\n"
        "print('t.py::test_cap')\n"
    )
    spec = _write_ledger_spec(
        repo,
        ("cap", "guard", "survivor"),
        collect_command=[sys.executable, "-c", script, str(counter)],
    )

    for _ in range(3):
        _cli(capsys, "--budget", 0.001, spec)

    assert counter.read_text().splitlines() == ["c"]


def _changed_paths(err: str) -> list[str]:
    match = re.search(r"changed: ([^)]*)\)", err)
    assert match, err
    return match.group(1).split(", ")


def test_tree_change_message_names_at_most_ten_paths_with_no_empty_entry(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = _write_ledger_spec(repo, ("cap", "guard"), "--touch-many", "12")
    rc, _, err = _cli(capsys, "--budget", 1000, spec)
    assert rc == 2
    assert _changed_paths(err) == [f"side_{i:02d}.txt" for i in range(10)]

    for stale in repo.glob("side_*.txt"):
        stale.unlink()
    spec = _write_ledger_spec(repo, ("cap", "guard"), "--touch-many", "1")
    rc, _, err = _cli(capsys, "--budget", 1000, spec)
    assert rc == 2
    assert _changed_paths(err) == ["side_00.txt"]
    assert ", )" not in err


def test_every_ledger_line_is_fsynced(
    repo: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    synced: list[int] = []
    real = os.fsync

    def spy(fd: int) -> None:
        synced.append(os.fstat(fd).st_ino)
        real(fd)

    monkeypatch.setattr(os, "fsync", spy)
    spec = _write_ledger_spec(repo, ("cap", "guard"))

    assert _cli(capsys, "--budget", 1000, spec)[0] == 0

    path = Path(_report_json(capsys, spec)["ledger"]["path"])
    assert len(_ledger_lines(path)) == 3  # collect + two rows
    assert synced.count(path.stat().st_ino) == 3


def test_a_stray_git_index_file_in_the_environment_does_not_change_the_fingerprint(
    repo: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _write_ledger_spec(repo)
    (repo / "__pycache__").mkdir()
    (repo / "__pycache__" / "x.pyc").write_bytes(b"ignored, yet staged in the decoy")
    decoy = repo.parent / "decoy-index"
    decoy.write_bytes((repo / ".git" / "index").read_bytes())
    subprocess.run(  # the decoy, and only the decoy, tracks a file .gitignore hides
        ["git", "add", "-f", "__pycache__/x.pyc"],
        cwd=repo,
        check=True,
        capture_output=True,
        env={**os.environ, "GIT_INDEX_FILE": str(decoy)},
    )
    unset = _report_json(capsys, spec)["ledger"]["tree"]
    before = decoy.read_bytes()

    monkeypatch.setenv("GIT_INDEX_FILE", str(decoy))
    set_ = _report_json(capsys, spec)["ledger"]["tree"]

    assert set_ == unset
    assert decoy.read_bytes() == before


def test_a_spec_named_with_glob_characters_is_still_excluded(
    repo: Path, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    log = tmp_path / "runs.log"
    spec = repo / "spec[1].json"
    spec.write_text(
        _write_ledger_spec(repo, ("cap", "guard", "survivor"), "--log", str(log)).read_text()
    )
    assert _cli(capsys, "--budget", 1000, spec)[0] == 1
    log.unlink()

    doc = json.loads(spec.read_text())
    doc["mutants"][1] = _ledger_row("guard", replace="GUARD = None")
    spec.write_text(json.dumps(doc))
    rc, out, _ = _cli(capsys, "--budget", 1000, spec)

    assert out.splitlines()[0].startswith("LEDGER: 3 of 3 rows")
    assert len(log.read_text().splitlines()) == 1 + 1  # baseline + the edited row
