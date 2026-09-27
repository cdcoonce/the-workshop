"""Field-set tests for the run-file and calibration-record JSON Schemas."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import jsonschema
import pytest

_SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"
_RUN_FILE_SCHEMA = json.loads((_SCHEMAS_DIR / "run-file.schema.json").read_text(encoding="utf-8"))
_CALIBRATION_SCHEMA = json.loads(
    (_SCHEMAS_DIR / "calibration-record.schema.json").read_text(encoding="utf-8")
)


def _valid_run() -> dict:
    return {
        "skill": "example-skill",
        "verdict": "green",
        "fingerprint": {
            "direct_tier_hash": "a" * 64,
            "injection_tier_hash": "b" * 64,
            "plugin_version": "1.2.3",
            "claude_code_version": "2.1.0",
            "run_date": "2026-09-27",
        },
        "tokens": 1000,
        "wall_time_s": 12.5,
        "cases": [
            {
                "case": "case-a",
                "fixture_fingerprint": "c" * 64,
                "gated_items": ["item-a"],
                "model_ids": ["claude-sonnet-5"],
                "attempts": [
                    {
                        "attempt": 1,
                        "classification": "counted",
                        "items": {"item-a": "hit"},
                        "parse_error": False,
                        "unmatched_findings": 0,
                        "reserve_used": 0,
                        "raw": "case-a/attempt-1/",
                    }
                ],
            }
        ],
    }


def _valid_calibration_record() -> dict:
    return {
        "n": 5,
        "hits": 4,
        "audited_hits": 4,
        "cross_match_result": "pass",
        "no_skill_arm_result": {"n": 5, "hits": 1, "replacements": 0},
        "gate_or_trend_status": "gate",
        "input_hash": "d" * 64,
        "audit": [
            {
                "raw": "case-a/calibration/attempt-1",
                "finding": 0,
                "credited_item": "item-a",
                "audited_item": "item-a",
            }
        ],
    }


def _delete_path(data: dict, path: tuple) -> dict:
    mutated = copy.deepcopy(data)
    target = mutated
    for key in path[:-1]:
        target = target[key]
    del target[path[-1]]
    return mutated


RUN_FILE_REQUIRED_PATHS = [
    ("skill",),
    ("verdict",),
    ("fingerprint",),
    ("tokens",),
    ("wall_time_s",),
    ("cases",),
    ("fingerprint", "direct_tier_hash"),
    ("fingerprint", "injection_tier_hash"),
    ("fingerprint", "plugin_version"),
    ("fingerprint", "claude_code_version"),
    ("fingerprint", "run_date"),
    ("cases", 0, "case"),
    ("cases", 0, "fixture_fingerprint"),
    ("cases", 0, "gated_items"),
    ("cases", 0, "model_ids"),
    ("cases", 0, "attempts"),
    ("cases", 0, "attempts", 0, "attempt"),
    ("cases", 0, "attempts", 0, "classification"),
    ("cases", 0, "attempts", 0, "items"),
    ("cases", 0, "attempts", 0, "parse_error"),
    ("cases", 0, "attempts", 0, "unmatched_findings"),
    ("cases", 0, "attempts", 0, "reserve_used"),
    ("cases", 0, "attempts", 0, "raw"),
]


def test_run_file_well_formed_example_passes():
    jsonschema.validate(_valid_run(), _RUN_FILE_SCHEMA)


@pytest.mark.parametrize("path", RUN_FILE_REQUIRED_PATHS, ids=lambda p: ".".join(map(str, p)))
def test_run_file_missing_required_field_fails(path):
    mutated = _delete_path(_valid_run(), path)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(mutated, _RUN_FILE_SCHEMA)


def test_run_file_unknown_top_level_field_fails():
    mutated = _valid_run()
    mutated["bogus"] = "nope"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(mutated, _RUN_FILE_SCHEMA)


def test_run_file_unknown_case_level_field_fails():
    mutated = _valid_run()
    mutated["cases"][0]["bogus"] = "nope"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(mutated, _RUN_FILE_SCHEMA)


def test_run_file_unknown_attempt_level_field_fails():
    mutated = _valid_run()
    mutated["cases"][0]["attempts"][0]["bogus"] = "nope"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(mutated, _RUN_FILE_SCHEMA)


CALIBRATION_REQUIRED_PATHS = [
    ("n",),
    ("hits",),
    ("audited_hits",),
    ("cross_match_result",),
    ("no_skill_arm_result",),
    ("gate_or_trend_status",),
    ("input_hash",),
    ("audit",),
    ("audit", 0, "raw"),
    ("audit", 0, "finding"),
    ("audit", 0, "credited_item"),
    ("audit", 0, "audited_item"),
]


def test_calibration_record_well_formed_example_passes():
    jsonschema.validate(_valid_calibration_record(), _CALIBRATION_SCHEMA)


@pytest.mark.parametrize(
    "path", CALIBRATION_REQUIRED_PATHS, ids=lambda p: ".".join(map(str, p))
)
def test_calibration_record_missing_required_field_fails(path):
    mutated = _delete_path(_valid_calibration_record(), path)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(mutated, _CALIBRATION_SCHEMA)


def test_calibration_record_unknown_top_level_field_fails():
    mutated = _valid_calibration_record()
    mutated["bogus"] = "nope"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(mutated, _CALIBRATION_SCHEMA)


def test_calibration_record_unknown_audit_entry_field_fails():
    mutated = _valid_calibration_record()
    mutated["audit"][0]["bogus"] = "nope"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(mutated, _CALIBRATION_SCHEMA)


@pytest.mark.parametrize(
    "no_skill_arm_result",
    [None, "baseline-void", {"n": 3, "hits": 0, "replacements": 1}],
    ids=["null", "baseline-void", "object"],
)
def test_calibration_record_no_skill_arm_result_variants_pass(no_skill_arm_result):
    record = _valid_calibration_record()
    record["no_skill_arm_result"] = no_skill_arm_result
    jsonschema.validate(record, _CALIBRATION_SCHEMA)


def test_calibration_record_no_skill_arm_result_invalid_string_fails():
    record = _valid_calibration_record()
    record["no_skill_arm_result"] = "not-a-valid-value"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(record, _CALIBRATION_SCHEMA)
