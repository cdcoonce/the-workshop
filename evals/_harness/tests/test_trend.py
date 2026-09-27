"""Tests for evals._harness.trend — summarize and history over run files."""

from __future__ import annotations

import json
from pathlib import Path

from evals._harness.trend import history, summarize


def _fingerprint(run_date: str) -> dict:
    return {
        "direct_tier_hash": "a" * 64,
        "injection_tier_hash": "b" * 64,
        "plugin_version": "1.0.0",
        "claude_code_version": "2.0.0",
        "run_date": run_date,
    }


def _write_run_file(runs_dir: Path, filename: str, run: dict) -> None:
    runs_dir.mkdir(parents=True, exist_ok=True)
    (runs_dir / filename).write_text(json.dumps(run), encoding="utf-8")


def _run_a() -> dict:
    return {
        "skill": "example-skill",
        "verdict": "green",
        "fingerprint": _fingerprint("2026-01-01"),
        "tokens": 1000,
        "wall_time_s": 10.0,
        "cases": [
            {
                "case": "case-a",
                "fixture_fingerprint": "c" * 64,
                "gated_items": ["item-a", "item-b"],
                "model_ids": ["m1"],
                "attempts": [
                    {
                        "attempt": 1,
                        "classification": "counted",
                        "items": {"item-a": "miss", "item-b": "hit"},
                        "parse_error": False,
                        "unmatched_findings": 1,
                        "reserve_used": 0,
                        "raw": "case-a/attempt-1/",
                    },
                    {
                        "attempt": 2,
                        "classification": "counted",
                        "items": {"item-a": "hit", "item-b": "hit", "item-trend": "hit"},
                        "parse_error": False,
                        "unmatched_findings": 0,
                        "reserve_used": 0,
                        "raw": "case-a/attempt-2/",
                    },
                ],
            }
        ],
    }


def _run_b() -> dict:
    return {
        "skill": "example-skill",
        "verdict": "red",
        "fingerprint": _fingerprint("2026-01-02"),
        "tokens": 500,
        "wall_time_s": 5.0,
        "cases": [
            {
                "case": "case-a",
                "fixture_fingerprint": "c" * 64,
                "gated_items": ["item-a", "item-b"],
                "model_ids": ["m1"],
                "attempts": [
                    {
                        "attempt": 1,
                        "classification": "counted",
                        "items": {"item-a": "miss", "item-b": "miss"},
                        "parse_error": False,
                        "unmatched_findings": 2,
                        "reserve_used": 0,
                        "raw": "case-a/attempt-1/",
                    },
                ],
            }
        ],
    }


def test_summarize_computes_totals_and_attempts_per_gated_item_by_hand(tmp_path):
    runs_dir = tmp_path / "runs"
    _write_run_file(runs_dir, "20260101T000000Z-aaaaaaaa.json", _run_a())
    _write_run_file(runs_dir, "20260102T000000Z-bbbbbbbb.json", _run_b())

    result = summarize(runs_dir)

    assert result["tokens"] == 1000 + 500
    assert result["wall_time_s"] == 10.0 + 5.0
    assert result["unmatched_findings"] == (1 + 0) + 2
    # Per case: "attempts needed" is the 1-based attempt index of the item's
    # first hit, or the total attempts recorded for it if it never hit — not
    # a count of every attempt that recorded an outcome for it.
    # run_a/case-a: item-a hits first on attempt 2, item-b hits first on
    # attempt 1. run_b/case-a: neither item ever hits, across 1 attempt each.
    assert result["attempts_per_item"] == {"item-a": 2 + 1, "item-b": 1 + 1}


def test_summarize_attempts_per_item_counts_the_first_hit_not_every_recorded_attempt(
    tmp_path,
):
    runs_dir = tmp_path / "runs"
    run = {
        "skill": "example-skill",
        "verdict": "green",
        "fingerprint": _fingerprint("2026-01-01"),
        "tokens": 100,
        "wall_time_s": 1.0,
        "cases": [
            {
                "case": "case-a",
                "fixture_fingerprint": "c" * 64,
                "gated_items": ["item-early", "item-late"],
                "model_ids": ["m1"],
                "attempts": [
                    {
                        "attempt": 1,
                        "classification": "counted",
                        "items": {"item-early": "hit", "item-late": "miss"},
                        "parse_error": False,
                        "unmatched_findings": 0,
                        "reserve_used": 0,
                        "raw": "case-a/attempt-1/",
                    },
                    {
                        "attempt": 2,
                        "classification": "counted",
                        # The retry loop keeps running because item-late is
                        # still missing; item-early is still recorded even
                        # though it already hit on attempt 1.
                        "items": {"item-early": "hit", "item-late": "miss"},
                        "parse_error": False,
                        "unmatched_findings": 0,
                        "reserve_used": 0,
                        "raw": "case-a/attempt-2/",
                    },
                    {
                        "attempt": 3,
                        "classification": "counted",
                        "items": {"item-late": "hit"},
                        "parse_error": False,
                        "unmatched_findings": 0,
                        "reserve_used": 0,
                        "raw": "case-a/attempt-3/",
                    },
                ],
            }
        ],
    }
    _write_run_file(runs_dir, "20260101T000000Z-aaaaaaaa.json", run)

    result = summarize(runs_dir)

    assert result["attempts_per_item"] == {"item-early": 1, "item-late": 3}


def test_history_returns_chronological_order_with_hand_computed_fields(tmp_path):
    runs_dir = tmp_path / "runs"
    # Written out of order — 03 first, then 01, then 02 — to prove `history`
    # sorts by filename rather than write order.
    run_03 = {
        "skill": "example-skill",
        "verdict": "green",
        "fingerprint": _fingerprint("2026-01-03"),
        "tokens": 300,
        "wall_time_s": 3.0,
        "cases": [
            {
                "case": "case-a",
                "fixture_fingerprint": "c" * 64,
                "gated_items": ["item-a"],
                "model_ids": ["m1"],
                "attempts": [
                    {
                        "attempt": 1,
                        "classification": "counted",
                        "items": {"item-a": "hit"},
                        "parse_error": False,
                        "unmatched_findings": 0,
                        "reserve_used": 0,
                        "raw": "case-a/attempt-1/",
                    },
                ],
            }
        ],
    }
    run_01 = {
        "skill": "example-skill",
        "verdict": "green",
        "fingerprint": _fingerprint("2026-01-01"),
        "tokens": 100,
        "wall_time_s": 1.0,
        "cases": [
            {
                "case": "case-a",
                "fixture_fingerprint": "c" * 64,
                "gated_items": ["item-a"],
                "model_ids": ["m1"],
                "attempts": [
                    {
                        "attempt": 1,
                        "classification": "counted",
                        "items": {"item-a": "miss"},
                        "parse_error": False,
                        "unmatched_findings": 1,
                        "reserve_used": 0,
                        "raw": "case-a/attempt-1/",
                    },
                    {
                        "attempt": 2,
                        "classification": "counted",
                        "items": {"item-a": "hit"},
                        "parse_error": False,
                        "unmatched_findings": 0,
                        "reserve_used": 0,
                        "raw": "case-a/attempt-2/",
                    },
                ],
            }
        ],
    }
    run_02 = {
        "skill": "example-skill",
        "verdict": "void",
        "fingerprint": _fingerprint("2026-01-02"),
        "tokens": 200,
        "wall_time_s": 2.0,
        "cases": [
            {
                "case": "case-a",
                "fixture_fingerprint": "c" * 64,
                "gated_items": ["item-a"],
                "model_ids": ["m1"],
                "attempts": [
                    {
                        "attempt": 1,
                        "classification": "indeterminate",
                        "items": {"item-a": "indeterminate"},
                        "parse_error": False,
                        "unmatched_findings": 0,
                        "reserve_used": 1,
                        "raw": "case-a/attempt-1/",
                    },
                ],
            }
        ],
    }

    _write_run_file(runs_dir, "20260103T000000Z-cccccccc.json", run_03)
    _write_run_file(runs_dir, "20260101T000000Z-aaaaaaaa.json", run_01)
    _write_run_file(runs_dir, "20260102T000000Z-bbbbbbbb.json", run_02)

    entries = history(runs_dir)

    assert [entry["run_file"] for entry in entries] == [
        "20260101T000000Z-aaaaaaaa.json",
        "20260102T000000Z-bbbbbbbb.json",
        "20260103T000000Z-cccccccc.json",
    ]

    assert entries[0]["run_date"] == "2026-01-01"
    assert entries[0]["tokens"] == 100
    assert entries[0]["wall_time_s"] == 1.0
    assert entries[0]["unmatched_findings"] == 1
    assert entries[0]["items"] == {
        "item-a": {"hit": True, "first_hit_attempt": 2, "attempts_used": 2}
    }

    assert entries[1]["run_date"] == "2026-01-02"
    assert entries[1]["tokens"] == 200
    assert entries[1]["wall_time_s"] == 2.0
    assert entries[1]["unmatched_findings"] == 0
    assert entries[1]["items"] == {
        "item-a": {"hit": False, "first_hit_attempt": None, "attempts_used": 1}
    }

    assert entries[2]["run_date"] == "2026-01-03"
    assert entries[2]["tokens"] == 300
    assert entries[2]["wall_time_s"] == 3.0
    assert entries[2]["unmatched_findings"] == 0
    assert entries[2]["items"] == {
        "item-a": {"hit": True, "first_hit_attempt": 1, "attempts_used": 1}
    }
