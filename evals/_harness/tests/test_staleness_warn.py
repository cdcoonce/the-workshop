"""Tests for evals._harness.guards.staleness_warn."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from evals._harness.guards import GuardContext
from evals._harness.guards.staleness_warn import check

_STALE_DATE = (date.today() - timedelta(days=40)).isoformat()
_FRESH_DATE = (date.today() - timedelta(days=5)).isoformat()


def _write(repo: Path, rel_path: str, content: str) -> None:
    path = repo / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _run_file(*, verdict: str, run_date: str) -> str:
    return json.dumps(
        {
            "skill": "commit",
            "verdict": verdict,
            "fingerprint": {
                "direct_tier_hash": "irrelevant",
                "injection_tier_hash": "irrelevant",
                "plugin_version": "0.1.0",
                "claude_code_version": "1.0.0",
                "run_date": run_date,
            },
            "tokens": 0,
            "wall_time_s": 0,
            "cases": [],
        }
    )


def _activate(repo: Path) -> None:
    _write(repo, "evals/commit/checks.manifest", "gated.one A description\n")
    _write(repo, "evals/commit/retired.md", "")


def test_warns_for_an_active_skill_with_a_stale_newest_green_run(tmp_path):
    _activate(tmp_path)
    _write(
        tmp_path,
        "evals/commit/runs/20260101T000000Z-aaa.json",
        _run_file(verdict="green", run_date=_STALE_DATE),
    )

    results = check(GuardContext(base="unused", repo_root=tmp_path))

    assert len(results) == 1
    assert results[0].level == "warn"
    assert results[0].guard == "staleness_warn"
    assert "commit" in results[0].message


def test_no_result_for_an_active_skill_with_a_recent_green_run(tmp_path):
    _activate(tmp_path)
    _write(
        tmp_path,
        "evals/commit/runs/20260101T000000Z-aaa.json",
        _run_file(verdict="green", run_date=_FRESH_DATE),
    )

    results = check(GuardContext(base="unused", repo_root=tmp_path))

    assert results == []


def test_no_result_for_an_inactive_skill_even_with_a_stale_green_run(tmp_path):
    _write(tmp_path, "evals/commit/checks.manifest", "")
    _write(tmp_path, "evals/commit/retired.md", "")
    _write(
        tmp_path,
        "evals/commit/runs/20260101T000000Z-aaa.json",
        _run_file(verdict="green", run_date=_STALE_DATE),
    )

    results = check(GuardContext(base="unused", repo_root=tmp_path))

    assert results == []


def test_a_newer_red_run_does_not_suppress_the_warning(tmp_path):
    _activate(tmp_path)
    _write(
        tmp_path,
        "evals/commit/runs/20260101T000000Z-aaa.json",
        _run_file(verdict="green", run_date=_STALE_DATE),
    )
    _write(
        tmp_path,
        "evals/commit/runs/20260601T000000Z-bbb.json",
        _run_file(verdict="red", run_date=_FRESH_DATE),
    )

    results = check(GuardContext(base="unused", repo_root=tmp_path))

    assert len(results) == 1
    assert results[0].level == "warn"


def test_no_result_when_no_green_run_exists(tmp_path):
    _activate(tmp_path)
    _write(
        tmp_path,
        "evals/commit/runs/20260101T000000Z-aaa.json",
        _run_file(verdict="red", run_date=_STALE_DATE),
    )

    results = check(GuardContext(base="unused", repo_root=tmp_path))

    assert results == []


def test_uses_the_newest_green_run_when_multiple_exist(tmp_path):
    _activate(tmp_path)
    _write(
        tmp_path,
        "evals/commit/runs/20260101T000000Z-aaa.json",
        _run_file(verdict="green", run_date=_STALE_DATE),
    )
    _write(
        tmp_path,
        "evals/commit/runs/20260601T000000Z-bbb.json",
        _run_file(verdict="green", run_date=_FRESH_DATE),
    )

    results = check(GuardContext(base="unused", repo_root=tmp_path))

    assert results == []


def test_no_result_when_no_runs_dir_exists(tmp_path):
    _activate(tmp_path)

    results = check(GuardContext(base="unused", repo_root=tmp_path))

    assert results == []
