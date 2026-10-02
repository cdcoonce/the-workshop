"""Tests for evals._harness.guards.schema_validate.

Every repo here is a synthetic git repo built under ``tmp_path``; the synthetic
run files and calibration records are checked against the real schemas under
``evals/_harness/schemas/``.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from evals._harness.guards import GuardContext
from evals._harness.guards.schema_validate import check

_RUN = "evals/example-skill/runs/20260101T000000Z-aaaaaaaa.json"
_CALIBRATION = "evals/example-skill/case-a/calibration.json"
_HEX = "a" * 64


def _valid_run() -> dict:
    return {
        "skill": "example-skill",
        "verdict": "green",
        "fingerprint": {
            "direct_tier_hash": "d",
            "injection_tier_hash": "i",
            "plugin_version": "1.0.0",
            "claude_code_version": "2.0.0",
            "run_date": "2026-01-01",
        },
        "tokens": 10,
        "wall_time_s": 1.5,
        "cases": [
            {
                "case": "case-a",
                "fixture_fingerprint": _HEX,
                "gated_items": ["item-a"],
                "model_ids": ["claude-test"],
                "attempts": [
                    {
                        "attempt": 1,
                        "classification": "counted",
                        "items": {"item-a": "hit"},
                        "parse_error": False,
                        "unmatched_findings": 0,
                        "reserve_used": 0,
                        "raw": "20260101T000000Z-aaaaaaaa/case-a/attempt-1/",
                    }
                ],
            }
        ],
    }


def _valid_record() -> dict:
    return {
        "n": 6,
        "hits": 6,
        "audited_hits": 6,
        "cross_match_result": "pass",
        "no_skill_arm_result": {"n": 3, "hits": 0, "replacements": 0},
        "gate_or_trend_status": "gate",
        "input_hash": _HEX,
        "audit": [{"raw": "r", "finding": 0, "credited_item": "item-a", "audited_item": "item-a"}],
    }


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def _write_json(repo: Path, rel_path: str, value) -> None:
    path = repo / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _write_text(repo: Path, rel_path: str, text: str) -> None:
    path = repo / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _base_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _write_text(repo, "evals/example-skill/checks.manifest", "")
    return repo, _commit(repo, "base")


def _run(repo: Path, base: str):
    return check(GuardContext(base=base, repo_root=repo))


# ---------------------------------------------------------------------------
# run files
# ---------------------------------------------------------------------------


def test_passes_a_well_formed_added_run_file_and_calibration_file(tmp_path):
    repo, base = _base_repo(tmp_path)
    _write_json(repo, _RUN, _valid_run())
    _write_json(repo, _CALIBRATION, {"item-a": _valid_record(), "item-b": _valid_record()})
    _commit(repo, "a run and a calibration")

    assert _run(repo, base) == []


def test_fails_a_run_file_missing_a_required_field(tmp_path):
    repo, base = _base_repo(tmp_path)
    run = _valid_run()
    del run["verdict"]
    _write_json(repo, _RUN, run)
    _commit(repo, "add an incomplete run")

    results = _run(repo, base)

    assert len(results) == 1
    assert results[0].level == "fail"
    assert results[0].guard == "schema_validate"
    assert _RUN in results[0].message
    assert "verdict" in results[0].message


def test_fails_a_run_file_with_a_wrong_type(tmp_path):
    repo, base = _base_repo(tmp_path)
    run = _valid_run()
    run["tokens"] = "many"
    _write_json(repo, _RUN, run)
    _commit(repo, "add a mistyped run")

    results = _run(repo, base)

    assert len(results) == 1
    assert _RUN in results[0].message


def test_fails_a_run_file_nested_deep_inside_with_a_bad_enum(tmp_path):
    repo, base = _base_repo(tmp_path)
    run = _valid_run()
    run["cases"][0]["attempts"][0]["items"]["item-a"] = "maybe"
    _write_json(repo, _RUN, run)
    _commit(repo, "add a run with a bad outcome")

    results = _run(repo, base)

    assert len(results) == 1


def test_fails_a_run_file_carrying_an_unknown_field(tmp_path):
    """The run-file schema is closed: a commit SHA (or any other stray field)
    must not ride along in a run file.
    """
    repo, base = _base_repo(tmp_path)
    run = _valid_run()
    run["commit"] = "deadbeef"
    _write_json(repo, _RUN, run)
    _commit(repo, "add a run with a commit field")

    assert len(_run(repo, base)) == 1


def test_fails_a_run_file_that_is_not_json(tmp_path):
    repo, base = _base_repo(tmp_path)
    _write_text(repo, _RUN, "{not json")
    _commit(repo, "add a garbled run")

    results = _run(repo, base)

    assert len(results) == 1
    assert _RUN in results[0].message


def test_fails_a_run_file_that_existed_at_base_and_is_modified_into_an_invalid_one(tmp_path):
    repo, _ = _base_repo(tmp_path)
    _write_json(repo, _RUN, _valid_run())
    base = _commit(repo, "a valid run already at base")
    broken = _valid_run()
    del broken["cases"]
    _write_json(repo, _RUN, broken)
    _commit(repo, "break it")

    results = _run(repo, base)

    assert len(results) == 1
    assert _RUN in results[0].message


def test_does_not_validate_a_raw_under_the_stem_directory_as_a_run_file(tmp_path):
    repo, base = _base_repo(tmp_path)
    _write_json(repo, _RUN, _valid_run())
    # A raw JSON file that is certainly not a run file: it would fail the schema.
    _write_json(
        repo,
        "evals/example-skill/runs/20260101T000000Z-aaaaaaaa/case-a/attempt-1/end_state/state.json",
        {"not": "a run file"},
    )
    _commit(repo, "a run with a raw json file")

    assert _run(repo, base) == []


def test_does_not_validate_a_non_json_file_directly_under_runs(tmp_path):
    repo, base = _base_repo(tmp_path)
    _write_text(repo, "evals/example-skill/runs/notes.txt", "{not json")
    _commit(repo, "a stray text file")

    assert _run(repo, base) == []


def test_does_not_validate_an_unchanged_run_file(tmp_path):
    repo, _ = _base_repo(tmp_path)
    _write_json(repo, _RUN, {"already": "invalid at base"})
    base = _commit(repo, "an invalid run file already at base")
    _write_text(repo, "evals/example-skill/checks.manifest", "item-a described\n")
    _commit(repo, "an unrelated change")

    assert _run(repo, base) == []


def test_does_not_validate_a_deleted_run_file(tmp_path):
    repo, _ = _base_repo(tmp_path)
    _write_json(repo, _RUN, _valid_run())
    base = _commit(repo, "a run at base")
    (repo / _RUN).unlink()
    _commit(repo, "delete it")

    assert _run(repo, base) == []


def test_validates_every_skills_run_files(tmp_path):
    repo, base = _base_repo(tmp_path)
    other = "evals/other-skill/runs/20260101T000000Z-bbbbbbbb.json"
    _write_json(repo, other, {"skill": "other-skill"})
    _commit(repo, "another skill's incomplete run")

    results = _run(repo, base)

    assert len(results) == 1
    assert other in results[0].message


def test_reports_every_invalid_file_in_the_diff(tmp_path):
    repo, base = _base_repo(tmp_path)
    other = "evals/other-skill/runs/20260101T000000Z-bbbbbbbb.json"
    _write_json(repo, _RUN, {"skill": "example-skill"})
    _write_json(repo, other, {"skill": "other-skill"})
    _commit(repo, "two incomplete runs")

    assert len(_run(repo, base)) == 2


def test_passes_an_empty_diff(tmp_path):
    repo, base = _base_repo(tmp_path)

    assert _run(repo, base) == []


# ---------------------------------------------------------------------------
# calibration records
# ---------------------------------------------------------------------------


def test_fails_a_calibration_file_with_a_malformed_record(tmp_path):
    repo, base = _base_repo(tmp_path)
    record = _valid_record()
    del record["input_hash"]
    _write_json(repo, _CALIBRATION, {"item-a": record})
    _commit(repo, "a calibration with an incomplete record")

    results = _run(repo, base)

    assert len(results) == 1
    assert results[0].level == "fail"
    assert _CALIBRATION in results[0].message
    assert "item-a" in results[0].message


def test_fails_when_the_malformed_record_is_the_second_of_two(tmp_path):
    repo, base = _base_repo(tmp_path)
    broken = _valid_record()
    broken["gate_or_trend_status"] = "maybe"
    _write_json(repo, _CALIBRATION, {"item-a": _valid_record(), "item-b": broken})
    _commit(repo, "the second record is malformed")

    results = _run(repo, base)

    assert len(results) == 1
    assert "item-b" in results[0].message
    assert "item-a" not in results[0].message


def test_reports_every_malformed_record_in_one_file(tmp_path):
    repo, base = _base_repo(tmp_path)
    first, second = _valid_record(), _valid_record()
    first["n"] = "six"
    second["hits"] = -1
    _write_json(repo, _CALIBRATION, {"item-a": first, "item-b": second})
    _commit(repo, "both records are malformed")

    assert len(_run(repo, base)) == 2


def test_fails_a_calibration_record_with_a_bad_input_hash(tmp_path):
    repo, base = _base_repo(tmp_path)
    record = _valid_record()
    record["input_hash"] = "not-a-sha256"
    _write_json(repo, _CALIBRATION, {"item-a": record})
    _commit(repo, "a calibration with a malformed hash")

    assert len(_run(repo, base)) == 1


@pytest.mark.parametrize("content", ["{not json", "[1, 2]", '"text"', '{"item-a": 5}'])
def test_fails_a_calibration_file_that_is_not_a_map_of_records(tmp_path, content):
    repo, base = _base_repo(tmp_path)
    _write_text(repo, _CALIBRATION, content)
    _commit(repo, "a calibration that is not a map of records")

    results = _run(repo, base)

    assert len(results) == 1
    assert _CALIBRATION in results[0].message


def test_fails_a_calibration_file_modified_into_an_invalid_one(tmp_path):
    repo, _ = _base_repo(tmp_path)
    _write_json(repo, _CALIBRATION, {"item-a": _valid_record()})
    base = _commit(repo, "a valid calibration at base")
    record = _valid_record()
    del record["audit"]
    _write_json(repo, _CALIBRATION, {"item-a": record})
    _commit(repo, "break it")

    assert len(_run(repo, base)) == 1


def test_passes_an_empty_calibration_map(tmp_path):
    repo, base = _base_repo(tmp_path)
    _write_json(repo, _CALIBRATION, {})
    _commit(repo, "an empty calibration")

    assert _run(repo, base) == []


def test_does_not_validate_a_calibration_json_that_is_not_directly_in_a_case_directory(tmp_path):
    repo, base = _base_repo(tmp_path)
    _write_json(repo, "evals/example-skill/case-a/fixture/calibration.json", {"item-a": {}})
    _write_json(repo, "evals/example-skill/calibration.json", {"item-a": {}})
    _commit(repo, "calibration-named files that are not a case's calibration")

    assert _run(repo, base) == []


def test_does_not_validate_an_unchanged_calibration_file(tmp_path):
    repo, _ = _base_repo(tmp_path)
    _write_json(repo, _CALIBRATION, {"item-a": {"stale": True}})
    base = _commit(repo, "an invalid calibration already at base")
    _write_text(repo, "evals/example-skill/case-a/prompt.md", "changed\n")
    _commit(repo, "an unrelated change")

    assert _run(repo, base) == []


def test_validates_each_artifact_against_its_own_schema(tmp_path):
    """A valid run file is not a valid calibration map, and vice versa."""
    repo, base = _base_repo(tmp_path)
    _write_json(repo, _RUN, _valid_record())
    _write_json(repo, _CALIBRATION, {"item-a": _valid_run()})
    _commit(repo, "each file holds the other's shape")

    assert len(_run(repo, base)) == 2


def test_ignores_a_base_only_change_via_the_three_dot_range(tmp_path):
    """The diff is base...HEAD (merge-base relative): an invalid run file the BASE
    branch added after this branch forked is not this branch's change.
    """
    repo, fork = _base_repo(tmp_path)
    branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    _git(repo, "branch", "base-line", fork)
    _git(repo, "checkout", "-q", "base-line")
    _write_json(repo, _RUN, {"skill": "incomplete"})
    base_head = _commit(repo, "base adds an incomplete run file")
    _git(repo, "checkout", "-q", branch)
    _write_text(repo, "unrelated.txt", "hello\n")
    _commit(repo, "this branch touches something else")

    assert _run(repo, base_head) == []
