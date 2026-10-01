"""Tests for evals._harness.guards.flaky_item_warn."""

from __future__ import annotations

import json
from pathlib import Path

from evals._harness.guards import GuardContext
from evals._harness.guards.flaky_item_warn import check

_ITEM = "gated.flaky"


def _fingerprint(run_date: str) -> dict:
    return {
        "direct_tier_hash": "a" * 64,
        "injection_tier_hash": "b" * 64,
        "plugin_version": "1.0.0",
        "claude_code_version": "2.0.0",
        "run_date": run_date,
    }


def _run(run_date: str, items: dict[str, list[str]]) -> dict:
    """Build a run file whose one case gates every key of *items*.

    ``items`` maps a gated item id to its per-attempt hit/miss outcomes, in
    attempt order (e.g. ``["miss", "hit"]`` needs 2 attempts; ``["miss"]``
    never hits within the attempts recorded).
    """
    attempts: list[dict] = []
    max_attempts = max((len(outcomes) for outcomes in items.values()), default=0)
    for attempt_num in range(1, max_attempts + 1):
        attempt_items = {
            item_id: outcomes[attempt_num - 1]
            for item_id, outcomes in items.items()
            if attempt_num <= len(outcomes)
        }
        attempts.append(
            {
                "attempt": attempt_num,
                "classification": "counted",
                "items": attempt_items,
                "parse_error": False,
                "unmatched_findings": 0,
                "reserve_used": 0,
                "raw": f"case-a/attempt-{attempt_num}/",
            }
        )
    return {
        "skill": "commit",
        "verdict": "green",
        "fingerprint": _fingerprint(run_date),
        "tokens": 100,
        "wall_time_s": 1.0,
        "cases": [
            {
                "case": "case-a",
                "fixture_fingerprint": "c" * 64,
                "gated_items": list(items.keys()),
                "model_ids": ["m1"],
                "attempts": attempts,
            }
        ],
    }


def _gate(repo: Path, *item_ids: str) -> None:
    """List *item_ids* as the commit skill's gated set in its checks.manifest."""
    manifest = repo / "evals" / "commit" / "checks.manifest"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text("".join(f"{item_id} A description\n" for item_id in item_ids), encoding="utf-8")


def _write_run(runs_dir: Path, filename: str, run: dict) -> None:
    runs_dir.mkdir(parents=True, exist_ok=True)
    (runs_dir / filename).write_text(json.dumps(run), encoding="utf-8")


def test_warns_when_an_item_is_flaky_in_two_of_the_last_three_runs(tmp_path):
    _gate(tmp_path, _ITEM)
    runs_dir = tmp_path / "evals" / "commit" / "runs"
    _write_run(runs_dir, "20260101T000000Z-aaa.json", _run("2026-01-01", {_ITEM: ["miss", "hit"]}))
    _write_run(runs_dir, "20260102T000000Z-bbb.json", _run("2026-01-02", {_ITEM: ["hit"]}))
    _write_run(runs_dir, "20260103T000000Z-ccc.json", _run("2026-01-03", {_ITEM: ["miss"]}))

    results = check(GuardContext(base="unused", repo_root=tmp_path))

    assert len(results) == 1
    assert results[0].level == "warn"
    assert results[0].guard == "flaky_item_warn"
    assert "commit" in results[0].message
    assert _ITEM in results[0].message


def test_no_result_when_flaky_in_only_one_of_the_last_three_runs(tmp_path):
    _gate(tmp_path, _ITEM)
    runs_dir = tmp_path / "evals" / "commit" / "runs"
    _write_run(runs_dir, "20260101T000000Z-aaa.json", _run("2026-01-01", {_ITEM: ["miss", "hit"]}))
    _write_run(runs_dir, "20260102T000000Z-bbb.json", _run("2026-01-02", {_ITEM: ["hit"]}))
    _write_run(runs_dir, "20260103T000000Z-ccc.json", _run("2026-01-03", {_ITEM: ["hit"]}))

    results = check(GuardContext(base="unused", repo_root=tmp_path))

    assert results == []


def test_warns_with_fewer_than_three_runs_when_both_are_flaky(tmp_path):
    _gate(tmp_path, _ITEM)
    runs_dir = tmp_path / "evals" / "commit" / "runs"
    _write_run(runs_dir, "20260101T000000Z-aaa.json", _run("2026-01-01", {_ITEM: ["miss"]}))
    _write_run(runs_dir, "20260102T000000Z-bbb.json", _run("2026-01-02", {_ITEM: ["miss", "hit"]}))

    results = check(GuardContext(base="unused", repo_root=tmp_path))

    assert len(results) == 1
    assert results[0].level == "warn"


def test_no_result_with_a_single_flaky_run_only(tmp_path):
    _gate(tmp_path, _ITEM)
    runs_dir = tmp_path / "evals" / "commit" / "runs"
    _write_run(runs_dir, "20260101T000000Z-aaa.json", _run("2026-01-01", {_ITEM: ["miss"]}))

    results = check(GuardContext(base="unused", repo_root=tmp_path))

    assert results == []


def test_ignores_runs_older_than_the_last_three(tmp_path):
    # The OLDEST runs are flaky and the latest three are clean, so slicing the
    # wrong end of the history (the oldest three) flips the outcome to a warn.
    _gate(tmp_path, _ITEM)
    runs_dir = tmp_path / "evals" / "commit" / "runs"
    _write_run(runs_dir, "20251229T000000Z-xxx.json", _run("2025-12-29", {_ITEM: ["miss"]}))
    _write_run(runs_dir, "20251230T000000Z-yyy.json", _run("2025-12-30", {_ITEM: ["miss"]}))
    _write_run(runs_dir, "20251231T000000Z-zzz.json", _run("2025-12-31", {_ITEM: ["miss"]}))
    _write_run(runs_dir, "20260101T000000Z-aaa.json", _run("2026-01-01", {_ITEM: ["hit"]}))
    _write_run(runs_dir, "20260102T000000Z-bbb.json", _run("2026-01-02", {_ITEM: ["hit"]}))
    _write_run(runs_dir, "20260103T000000Z-ccc.json", _run("2026-01-03", {_ITEM: ["hit"]}))

    results = check(GuardContext(base="unused", repo_root=tmp_path))

    assert results == []


def test_warns_on_the_most_recent_three_runs_when_the_oldest_are_clean(tmp_path):
    # Mirror of the case above: clean oldest runs, flaky latest three.
    _gate(tmp_path, _ITEM)
    runs_dir = tmp_path / "evals" / "commit" / "runs"
    _write_run(runs_dir, "20251229T000000Z-xxx.json", _run("2025-12-29", {_ITEM: ["hit"]}))
    _write_run(runs_dir, "20251230T000000Z-yyy.json", _run("2025-12-30", {_ITEM: ["hit"]}))
    _write_run(runs_dir, "20251231T000000Z-zzz.json", _run("2025-12-31", {_ITEM: ["hit"]}))
    _write_run(runs_dir, "20260101T000000Z-aaa.json", _run("2026-01-01", {_ITEM: ["miss"]}))
    _write_run(runs_dir, "20260102T000000Z-bbb.json", _run("2026-01-02", {_ITEM: ["miss", "hit"]}))
    _write_run(runs_dir, "20260103T000000Z-ccc.json", _run("2026-01-03", {_ITEM: ["hit"]}))

    results = check(GuardContext(base="unused", repo_root=tmp_path))

    assert len(results) == 1
    assert results[0].level == "warn"
    assert "2 of its last 3 runs" in results[0].message


def test_only_counts_runs_where_the_item_is_present(tmp_path):
    _gate(tmp_path, _ITEM)
    runs_dir = tmp_path / "evals" / "commit" / "runs"
    _write_run(runs_dir, "20260101T000000Z-aaa.json", _run("2026-01-01", {}))
    _write_run(runs_dir, "20260102T000000Z-bbb.json", _run("2026-01-02", {_ITEM: ["miss"]}))
    _write_run(runs_dir, "20260103T000000Z-ccc.json", _run("2026-01-03", {_ITEM: ["miss"]}))

    results = check(GuardContext(base="unused", repo_root=tmp_path))

    assert len(results) == 1
    assert results[0].level == "warn"


def test_no_result_with_no_runs_dir(tmp_path):
    results = check(GuardContext(base="unused", repo_root=tmp_path))

    assert results == []


def test_only_warns_for_items_in_the_skills_current_gated_set(tmp_path):
    # `gone` was retired (it is in retired.md, not checks.manifest) but still
    # appears in the last three run files; the spec is "for each gated item",
    # so only `other` -- the one gated item -- may be reported.
    (tmp_path / "evals" / "commit").mkdir(parents=True)
    (tmp_path / "evals" / "commit" / "checks.manifest").write_text(
        "other An item still gated\n", encoding="utf-8"
    )
    (tmp_path / "evals" / "commit" / "retired.md").write_text(
        "## gone\n- date: 2026-01-01\n- reason: noise\n- evidence: flaked repeatedly\n",
        encoding="utf-8",
    )
    runs_dir = tmp_path / "evals" / "commit" / "runs"
    flaky = {"gone": ["miss", "hit"], "other": ["miss", "hit"]}
    _write_run(runs_dir, "20260101T000000Z-aaa.json", _run("2026-01-01", flaky))
    _write_run(runs_dir, "20260102T000000Z-bbb.json", _run("2026-01-02", flaky))
    _write_run(runs_dir, "20260103T000000Z-ccc.json", _run("2026-01-03", flaky))

    results = check(GuardContext(base="unused", repo_root=tmp_path))

    assert [result.level for result in results] == ["warn"]
    assert "'other'" in results[0].message
    assert not any("gone" in result.message for result in results)
