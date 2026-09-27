"""Tests for the evals._harness.guards runner: discovery, reporting, exit code."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import evals._harness.guards as guards_package
from evals._harness.guards import GuardContext, Result
from evals._harness.guards.__main__ import discover_checks, main, report, run_checks

# The repo root two levels above this file's containing package
# (evals/_harness/tests/test_guards.py -> tests -> _harness -> evals -> repo
# root), used both to assert `repo_root` is wired correctly and to give a
# subprocess the PYTHONPATH it needs to import `evals` bare.
_REPO_ROOT = Path(__file__).resolve().parents[3]

_PLANTED_FAIL_GUARD_SOURCE = (
    "from evals._harness.guards import Result\n\n\n"
    "def check(ctx):\n"
    "    return [Result(level='fail', guard='planted_fail_guard', message='boom')]\n"
)


def test_report_prints_every_result(capsys):
    results = [
        Result(level="warn", guard="demo", message="a warning"),
        Result(level="fail", guard="demo", message="a failure"),
    ]
    report(results)
    captured = capsys.readouterr()
    assert "a warning" in captured.out
    assert "a failure" in captured.out


def test_report_exits_zero_when_no_result_is_a_failure():
    exit_code = report([Result(level="warn", guard="demo", message="just a warning")])
    assert exit_code == 0


def test_report_exits_one_when_any_result_is_a_failure():
    exit_code = report(
        [
            Result(level="warn", guard="demo", message="a warning"),
            Result(level="fail", guard="demo", message="a failure"),
        ]
    )
    assert exit_code == 1


def test_report_exits_zero_and_prints_nothing_for_no_results(capsys):
    exit_code = report([])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == ""


def test_run_checks_passes_the_context_to_every_discovered_check(monkeypatch):
    captured_ctx = []

    def fake_check(ctx):
        captured_ctx.append(ctx)
        return [Result(level="warn", guard="fake", message="saw it")]

    monkeypatch.setattr(
        "evals._harness.guards.__main__.discover_checks",
        lambda: [("fake", fake_check)],
    )
    ctx = GuardContext(base="origin/main", repo_root=Path("/tmp"))
    results = run_checks(ctx)
    assert captured_ctx == [ctx]
    assert results == [Result(level="warn", guard="fake", message="saw it")]


def test_discover_checks_finds_a_planted_module_exposing_check(tmp_path, monkeypatch):
    (tmp_path / "planted_guard.py").write_text(
        "from evals._harness.guards import Result\n\n\n"
        "def check(ctx):\n"
        "    return [Result(level='warn', guard='planted', message='hi')]\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(guards_package, "__path__", [str(tmp_path), *guards_package.__path__])
    try:
        names = [name for name, _ in discover_checks()]
        assert "planted_guard" in names
    finally:
        sys.modules.pop("evals._harness.guards.planted_guard", None)


def test_main_with_zero_guard_modules_exits_zero_and_prints_nothing(tmp_path, monkeypatch, capsys):
    # Isolated to an empty guard directory: sibling issues will add real
    # guard modules under this package, and this test must not start
    # discovering and running them (nor rely on "origin/main" resolving in
    # whatever repo it happens to run in).
    monkeypatch.setattr(guards_package, "__path__", [str(tmp_path)])
    exit_code = main(["--base", "does-not-need-to-resolve"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == ""


def test_main_wires_base_and_repo_root_into_the_guard_context(tmp_path, monkeypatch):
    """CLI wiring: main() must pass its --base value and cwd through untouched.

    A planted fail guard records what it was actually handed, isolated from
    every other guard module via the patched package __path__ (same pattern
    as test_discover_checks_finds_a_planted_module_exposing_check above).
    """
    seen_path = tmp_path / "seen.txt"
    (tmp_path / "planted_fail_guard.py").write_text(
        "from pathlib import Path\n"
        "from evals._harness.guards import Result\n\n\n"
        "def check(ctx):\n"
        f"    Path({str(seen_path)!r}).write_text(\n"
        "        f'{ctx.base}|{ctx.repo_root}', encoding='utf-8'\n"
        "    )\n"
        "    return [Result(level='fail', guard='planted_fail_guard', message='boom')]\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(guards_package, "__path__", [str(tmp_path)])
    expected_repo_root = str(Path.cwd())
    try:
        exit_code = main(["--base", "SENTINEL"])
    finally:
        sys.modules.pop("evals._harness.guards.planted_fail_guard", None)

    assert exit_code == 1
    base_seen, repo_root_seen = seen_path.read_text(encoding="utf-8").split("|", 1)
    assert base_seen == "SENTINEL"
    assert repo_root_seen == expected_repo_root


def test_module_execution_exits_1_on_a_failing_guard_and_0_when_the_guard_dir_is_empty(tmp_path):
    """Exercises the real ``if __name__ == "__main__": sys.exit(main())`` line.

    A direct ``main()`` call (as above) never runs that module-level guard,
    so a mutation collapsing it to a bare ``main()`` call would still leave
    every in-process test green. Running the module itself in a subprocess,
    the same way ``python -m evals._harness.guards`` does, is the only way to
    pin the exit-code wiring.
    """
    fail_dir = tmp_path / "fail_guards"
    fail_dir.mkdir()
    (fail_dir / "planted_fail_guard.py").write_text(_PLANTED_FAIL_GUARD_SOURCE, encoding="utf-8")
    empty_dir = tmp_path / "empty_guards"
    empty_dir.mkdir()

    env = {**os.environ, "PYTHONPATH": str(_REPO_ROOT)}

    # A plain `runpy.run_module("evals._harness.guards", run_name="__main__")`
    # would re-resolve the "__main__" submodule through the package's
    # (already-patched) __path__ and fail to find it, since the planted
    # directory holds no __main__.py of its own. Reading __main__.py's real
    # source before patching __path__, then running it via the private
    # runpy._run_module_code with mod_name="__main__" (so the module's own
    # `if __name__ == "__main__":` guard fires) and pkg_name set to the real
    # dotted package name (so `sys.modules[__package__]` inside it resolves)
    # reproduces exactly what `python -m evals._harness.guards` does, fully
    # isolated from every real guard module.
    script = (
        "import runpy, sys\n"
        "import evals._harness.guards as guards_package\n"
        "main_path = guards_package.__path__[0] + '/__main__.py'\n"
        "source = open(main_path, encoding='utf-8').read()\n"
        "code = compile(source, main_path, 'exec')\n"
        "guards_package.__path__ = [sys.argv[1]]\n"
        "sys.argv = ['prog', '--base', 'origin/main']\n"
        "runpy._run_module_code(\n"
        "    code, mod_name='__main__', pkg_name='evals._harness.guards', script_name=main_path\n"
        ")\n"
    )

    def run_with_guard_dir(guard_dir: Path) -> int:
        result = subprocess.run(
            [sys.executable, "-c", script, str(guard_dir)],
            cwd=_REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
        )
        return result.returncode

    assert run_with_guard_dir(fail_dir) == 1
    assert run_with_guard_dir(empty_dir) == 0
