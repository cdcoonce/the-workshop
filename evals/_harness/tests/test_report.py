"""Tests for evals._harness.report — the red-run report writer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals._harness.ledger import write_run
from evals._harness.report import write_report

_COUNTED_MISS = "miss"
_HIT = "hit"


def _fingerprint(run_date: str, direct: str = "a" * 64, injection: str = "b" * 64) -> dict:
    return {
        "direct_tier_hash": direct,
        "injection_tier_hash": injection,
        "plugin_version": "1.0.0",
        "claude_code_version": "2.0.0",
        "run_date": run_date,
    }


def _attempt(n: int, item_outcomes: dict, raw: str) -> dict:
    return {
        "attempt": n,
        "classification": "counted",
        "items": item_outcomes,
        "parse_error": False,
        "unmatched_findings": 0,
        "reserve_used": 0,
        "raw": raw,
    }


def _write_run(runs_dir: Path, filename: str, run: dict) -> Path:
    runs_dir.mkdir(parents=True, exist_ok=True)
    path = runs_dir / filename
    path.write_text(json.dumps(run), encoding="utf-8")
    return path


def test_write_report_returns_none_for_a_non_red_run(tmp_path):
    runs_dir = tmp_path / "runs"
    run = {
        "skill": "example-skill",
        "verdict": "green",
        "fingerprint": _fingerprint("2026-01-02"),
        "tokens": 100,
        "wall_time_s": 1.0,
        "cases": [
            {
                "case": "case-a",
                "fixture_fingerprint": "c" * 64,
                "gated_items": ["item-a"],
                "model_ids": ["m1"],
                "attempts": [_attempt(1, {"item-a": "hit"}, "case-a/attempt-1/")],
            }
        ],
    }
    run_file = _write_run(runs_dir, "20260102T000000Z-bbbbbbbb.json", run)

    assert write_report(run_file) is None
    assert not (runs_dir / "20260102T000000Z-bbbbbbbb.report.md").exists()


def test_write_report_lists_failing_items_raws_and_fingerprint_diff(tmp_path):
    runs_dir = tmp_path / "runs"

    stale_green_run = {
        "skill": "example-skill",
        "verdict": "green",
        "fingerprint": _fingerprint("2025-12-31", direct="a" * 64, injection="0" * 64),
        "tokens": 50,
        "wall_time_s": 0.5,
        "cases": [
            {
                "case": "case-a",
                "fixture_fingerprint": "c" * 64,
                "gated_items": ["item-a"],
                "model_ids": ["m1"],
                "attempts": [_attempt(1, {"item-a": "hit"}, "case-a/attempt-1/")],
            }
        ],
    }
    _write_run(runs_dir, "20251231T000000Z-99999999.json", stale_green_run)

    green_run = {
        "skill": "example-skill",
        "verdict": "green",
        "fingerprint": _fingerprint("2026-01-01", direct="a" * 64, injection="b" * 64),
        "tokens": 100,
        "wall_time_s": 1.0,
        "cases": [
            {
                "case": "case-a",
                "fixture_fingerprint": "c" * 64,
                "gated_items": ["item-a"],
                "model_ids": ["m1"],
                "attempts": [_attempt(1, {"item-a": "hit"}, "case-a/attempt-1/")],
            }
        ],
    }
    _write_run(runs_dir, "20260101T000000Z-aaaaaaaa.json", green_run)

    red_run = {
        "skill": "example-skill",
        "verdict": "red",
        "fingerprint": _fingerprint("2026-01-02", direct="a" * 64, injection="9" * 64),
        "tokens": 200,
        "wall_time_s": 2.0,
        "cases": [
            {
                "case": "case-a",
                "fixture_fingerprint": "c" * 64,
                "gated_items": ["item-a", "item-ok"],
                "model_ids": ["m1"],
                "attempts": [
                    _attempt(1, {"item-a": "miss", "item-ok": "hit"}, "case-a/attempt-1/"),
                    _attempt(2, {"item-a": "miss", "item-ok": "hit"}, "case-a/attempt-2/"),
                    _attempt(3, {"item-a": "miss", "item-ok": "hit"}, "case-a/attempt-3/"),
                ],
            }
        ],
    }
    red_run_file = _write_run(runs_dir, "20260102T000000Z-bbbbbbbb.json", red_run)

    report_path = write_report(red_run_file)

    assert report_path == runs_dir / "20260102T000000Z-bbbbbbbb.report.md"
    text = report_path.read_text(encoding="utf-8")

    failing_idx = text.index("## Failing items")
    raws_idx = text.index("## Raws")
    diff_idx = text.index("## Fingerprint diff")
    assert failing_idx < raws_idx < diff_idx

    failing_section = text[failing_idx:raws_idx]
    assert "case-a" in failing_section
    assert "item-a" in failing_section
    assert "red" in failing_section
    # A gated item that hit every attempt must not be reported as failing.
    assert "item-ok" not in failing_section

    raws_section = text[raws_idx:diff_idx]
    assert "case-a/attempt-1/" in raws_section
    assert "case-a/attempt-2/" in raws_section
    assert "case-a/attempt-3/" in raws_section

    diff_section = text[diff_idx:]
    assert "injection_tier_hash" in diff_section
    # Must diff against the newest green run (hash "b"*64), not the older,
    # stale green run (hash "0"*64).
    assert "b" * 64 in diff_section
    assert "9" * 64 in diff_section
    assert "0" * 64 not in diff_section
    # The unchanged direct_tier_hash should be reported too.
    assert "a" * 64 in diff_section


def test_write_report_lists_a_void_item_alongside_a_red_item(tmp_path):
    runs_dir = tmp_path / "runs"

    red_run = {
        "skill": "example-skill",
        "verdict": "red",
        "fingerprint": _fingerprint("2026-01-01"),
        "tokens": 100,
        "wall_time_s": 1.0,
        "cases": [
            {
                "case": "case-a",
                "fixture_fingerprint": "c" * 64,
                "gated_items": ["item-red", "item-void"],
                "model_ids": ["m1"],
                "attempts": [
                    _attempt(
                        1,
                        {"item-red": "miss", "item-void": "indeterminate"},
                        "case-a/attempt-1/",
                    ),
                    _attempt(
                        2,
                        {"item-red": "miss", "item-void": "indeterminate"},
                        "case-a/attempt-2/",
                    ),
                    _attempt(
                        3,
                        {"item-red": "miss", "item-void": "indeterminate"},
                        "case-a/attempt-3/",
                    ),
                ],
            }
        ],
    }
    red_run_file = _write_run(runs_dir, "20260101T000000Z-aaaaaaaa.json", red_run)

    report_path = write_report(red_run_file)
    text = report_path.read_text(encoding="utf-8")

    failing_idx = text.index("## Failing items")
    raws_idx = text.index("## Raws")
    failing_section = text[failing_idx:raws_idx]

    assert "item-red" in failing_section
    assert "red" in failing_section
    assert "item-void" in failing_section
    assert "void" in failing_section

    raws_section = text[raws_idx:]
    assert "case-a/attempt-1/" in raws_section


def test_write_report_fails_on_an_existing_report_path(tmp_path):
    runs_dir = tmp_path / "runs"
    red_run = {
        "skill": "example-skill",
        "verdict": "red",
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
                    _attempt(1, {"item-a": "miss"}, "case-a/attempt-1/"),
                    _attempt(2, {"item-a": "miss"}, "case-a/attempt-2/"),
                    _attempt(3, {"item-a": "miss"}, "case-a/attempt-3/"),
                ],
            }
        ],
    }
    red_run_file = _write_run(runs_dir, "20260101T000000Z-aaaaaaaa.json", red_run)

    write_report(red_run_file)
    with pytest.raises(FileExistsError):
        write_report(red_run_file)


def test_write_report_scrubs_a_home_path_from_the_report(tmp_path):
    home = str(Path.home())
    runs_dir = tmp_path / "runs"
    red_run = {
        "skill": "example-skill",
        "verdict": "red",
        "fingerprint": _fingerprint("2026-01-01"),
        "tokens": 100,
        "wall_time_s": 1.0,
        "cases": [
            {
                "case": f"case-a-{home}",
                "fixture_fingerprint": "c" * 64,
                "gated_items": ["item-a"],
                "model_ids": ["m1"],
                "attempts": [
                    _attempt(1, {"item-a": "miss"}, f"{home}/case-a/attempt-1/"),
                    _attempt(2, {"item-a": "miss"}, "case-a/attempt-2/"),
                    _attempt(3, {"item-a": "miss"}, "case-a/attempt-3/"),
                ],
            }
        ],
    }
    red_run_file = _write_run(runs_dir, "20260101T000000Z-aaaaaaaa.json", red_run)

    report_path = write_report(red_run_file)
    text = report_path.read_text(encoding="utf-8")

    assert home not in text


def test_write_report_writes_only_beside_the_run_file_and_never_tests_md(tmp_path):
    runs_dir = tmp_path / "evals" / "example-skill" / "runs"
    red_run = {
        "skill": "example-skill",
        "verdict": "red",
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
                    _attempt(1, {"item-a": "miss"}, "case-a/attempt-1/"),
                    _attempt(2, {"item-a": "miss"}, "case-a/attempt-2/"),
                    _attempt(3, {"item-a": "miss"}, "case-a/attempt-3/"),
                ],
            }
        ],
    }
    red_run_file = _write_run(runs_dir, "20260101T000000Z-aaaaaaaa.json", red_run)
    before = {p for p in runs_dir.parent.rglob("*") if p.is_file()}

    write_report(red_run_file)

    after = {p for p in runs_dir.parent.rglob("*") if p.is_file()}
    new_files = after - before
    assert len(new_files) == 1
    new_file = new_files.pop()
    assert new_file.parent == runs_dir
    assert new_file.name != "tests.md"


def _write_transcript(path: Path, model: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "type": "assistant",
                "message": {"model": model, "content": [{"type": "text", "text": "done"}]},
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_write_report_omits_a_home_path_planted_in_a_raw_end_to_end(tmp_path):
    """A home path planted in a raw's content must not reach the run file,
    the written raw copy, or the report — going through the real
    ``write_run`` -> ``write_report`` pipeline, not a hand-written run file.
    """
    home = str(Path.home())
    runs_dir = tmp_path / "evals" / "example-skill" / "runs"

    source = tmp_path / "sources" / "attempt-1"
    _write_transcript(source / "transcript.jsonl", "claude-sonnet-5")
    (source / "final-reply.txt").write_text(f"see {home}/secret.txt", encoding="utf-8")

    run = {
        "skill": "example-skill",
        "verdict": "red",
        "fingerprint": _fingerprint("2026-01-01"),
        "tokens": 100,
        "wall_time_s": 1.0,
        "cases": [
            {
                "case": "case-a",
                "fixture_fingerprint": "c" * 64,
                "gated_items": ["item-a"],
                "model_ids": ["placeholder-should-be-overwritten"],
                "attempts": [
                    {
                        "attempt": 1,
                        "classification": "counted",
                        "items": {"item-a": "miss"},
                        "parse_error": False,
                        "unmatched_findings": 0,
                        "reserve_used": 0,
                        "raw": "case-a/attempt-1/",
                    },
                    {
                        "attempt": 2,
                        "classification": "counted",
                        "items": {"item-a": "miss"},
                        "parse_error": False,
                        "unmatched_findings": 0,
                        "reserve_used": 0,
                        "raw": "case-a/attempt-2/",
                    },
                    {
                        "attempt": 3,
                        "classification": "counted",
                        "items": {"item-a": "miss"},
                        "parse_error": False,
                        "unmatched_findings": 0,
                        "reserve_used": 0,
                        "raw": "case-a/attempt-3/",
                    },
                ],
            }
        ],
    }

    run_file = write_run(
        runs_dir,
        run,
        {
            "case-a/attempt-1/": source,
            "case-a/attempt-2/": source,
            "case-a/attempt-3/": source,
        },
    )

    report_path = write_report(run_file)

    run_text = run_file.read_text(encoding="utf-8")
    raw_copy_text = (
        runs_dir / run_file.stem / "case-a" / "attempt-1" / "final-reply.txt"
    ).read_text(encoding="utf-8")
    report_text = report_path.read_text(encoding="utf-8")

    assert home not in run_text
    assert home not in raw_copy_text
    assert home not in report_text
