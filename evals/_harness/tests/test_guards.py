"""Tests for the evals._harness.guards runner: discovery, reporting, exit code."""

from __future__ import annotations

import sys
from pathlib import Path

import evals._harness.guards as guards_package
from evals._harness.guards import GuardContext, Result
from evals._harness.guards.__main__ import discover_checks, main, report, run_checks


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


def test_main_with_zero_guard_modules_exits_zero_and_prints_nothing(capsys):
    exit_code = main(["--base", "origin/main"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == ""
