"""Tests for evals._harness.calibration — the admission rule and its hashes."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import jsonschema
import pytest

from evals._harness.calibration import (
    compute_calibration_record,
    compute_input_hash,
    compute_no_skill_arm,
    fixture_fingerprint,
    write_calibration_records,
)
from evals._harness.fingerprint import builder_output_fingerprint

_SCHEMA = json.loads(
    (Path(__file__).resolve().parent.parent / "schemas" / "calibration-record.schema.json").read_text(
        encoding="utf-8"
    )
)


def _audit_entry(credited_item: str, audited_item: str | None, raw: str = "raw-1", finding: int = 0) -> dict:
    return {"raw": raw, "finding": finding, "credited_item": credited_item, "audited_item": audited_item}


# ---------------------------------------------------------------------------
# Gate-candidate admission clauses
# ---------------------------------------------------------------------------


def test_gate_candidate_skill_arm_below_threshold_is_not_admitted():
    record = compute_calibration_record(
        item_id="item-a",
        kind="gate-candidate",
        skill_hits=4,
        skill_n=6,
        no_skill_attempts=[{"contaminated": False, "hit": False}] * 3,
        audited_hits=4,
        audit=[],
        input_hash="a" * 64,
    )

    assert record["gate_or_trend_status"] == "trend"


def test_gate_candidate_no_skill_arm_above_threshold_is_not_admitted():
    no_skill_attempts = [
        {"contaminated": False, "hit": True},
        {"contaminated": False, "hit": True},
        {"contaminated": False, "hit": False},
    ]

    record = compute_calibration_record(
        item_id="item-a",
        kind="gate-candidate",
        skill_hits=5,
        skill_n=6,
        no_skill_attempts=no_skill_attempts,
        audited_hits=5,
        audit=[],
        input_hash="a" * 64,
    )

    assert record["gate_or_trend_status"] == "trend"
    assert record["no_skill_arm_result"] == {"n": 3, "hits": 2, "replacements": 0}


def test_gate_candidate_audited_rate_mismatch_is_not_admitted():
    no_skill_attempts = [{"contaminated": False, "hit": False}] * 3

    record = compute_calibration_record(
        item_id="item-a",
        kind="gate-candidate",
        skill_hits=5,
        skill_n=6,
        no_skill_attempts=no_skill_attempts,
        audited_hits=4,
        audit=[],
        input_hash="a" * 64,
    )

    assert record["gate_or_trend_status"] == "trend"


def test_gate_candidate_cross_match_credit_is_not_admitted():
    no_skill_attempts = [{"contaminated": False, "hit": False}] * 3
    audit = [_audit_entry("item-a", "item-b")]

    record = compute_calibration_record(
        item_id="item-a",
        kind="gate-candidate",
        skill_hits=5,
        skill_n=6,
        no_skill_attempts=no_skill_attempts,
        audited_hits=5,
        audit=audit,
        input_hash="a" * 64,
    )

    assert record["cross_match_result"] == "fail"
    assert record["gate_or_trend_status"] == "trend"
    assert record["audit"] == audit


def test_gate_candidate_null_audited_item_credited_to_scored_item_is_a_cross_match():
    """A credited finding the auditor matched to no item is a cross-match too.

    Per the conductor's ruling: any entry credited to the scored item whose
    ``audited_item`` differs from it — including ``None`` — fails the item.
    Kills a mutant that special-cases ``None`` as passing.
    """
    no_skill_attempts = [{"contaminated": False, "hit": False}] * 3
    audit = [_audit_entry("item-a", None)]

    record = compute_calibration_record(
        item_id="item-a",
        kind="gate-candidate",
        skill_hits=5,
        skill_n=6,
        no_skill_attempts=no_skill_attempts,
        audited_hits=5,
        audit=audit,
        input_hash="a" * 64,
    )

    assert record["cross_match_result"] == "fail"
    assert record["gate_or_trend_status"] == "trend"


def test_gate_candidate_entry_crediting_a_sibling_item_is_ignored_for_the_scored_item():
    """An audit entry credited to a different item never counts toward X.

    Kills a mutant that drops the ``credited_item == item_id`` filter, which
    would make a sibling's own correctly-matched entry read as a cross-match
    for this item.
    """
    no_skill_attempts = [{"contaminated": False, "hit": False}] * 3
    audit = [_audit_entry("item-b", "item-b")]

    record = compute_calibration_record(
        item_id="item-a",
        kind="gate-candidate",
        skill_hits=5,
        skill_n=6,
        no_skill_attempts=no_skill_attempts,
        audited_hits=5,
        audit=audit,
        input_hash="a" * 64,
    )

    assert record["cross_match_result"] == "pass"
    assert record["gate_or_trend_status"] == "gate"


def test_gate_candidate_cross_match_in_the_second_audit_entry_is_caught():
    """Every entry credited to X is checked, not only the first.

    Kills a mutant that stops scanning after the first audit entry.
    """
    no_skill_attempts = [{"contaminated": False, "hit": False}] * 3
    audit = [
        _audit_entry("item-a", "item-a", raw="raw-1", finding=0),
        _audit_entry("item-a", "item-b", raw="raw-2", finding=0),
    ]

    record = compute_calibration_record(
        item_id="item-a",
        kind="gate-candidate",
        skill_hits=5,
        skill_n=6,
        no_skill_attempts=no_skill_attempts,
        audited_hits=5,
        audit=audit,
        input_hash="a" * 64,
    )

    assert record["cross_match_result"] == "fail"
    assert record["gate_or_trend_status"] == "trend"


def test_gate_candidate_third_contamination_is_baseline_void_and_not_admitted():
    no_skill_attempts = [
        {"contaminated": True, "hit": False},
        {"contaminated": True, "hit": False},
        {"contaminated": True, "hit": False},
    ]

    record = compute_calibration_record(
        item_id="item-a",
        kind="gate-candidate",
        skill_hits=5,
        skill_n=6,
        no_skill_attempts=no_skill_attempts,
        audited_hits=5,
        audit=[],
        input_hash="a" * 64,
    )

    assert record["no_skill_arm_result"] == "baseline-void"
    assert record["gate_or_trend_status"] == "trend"


def test_gate_candidate_with_no_no_skill_arm_is_not_admitted():
    record = compute_calibration_record(
        item_id="item-a",
        kind="gate-candidate",
        skill_hits=6,
        skill_n=6,
        no_skill_attempts=None,
        audited_hits=6,
        audit=[],
        input_hash="a" * 64,
    )

    assert record["no_skill_arm_result"] is None
    assert record["gate_or_trend_status"] == "trend"


def test_gate_candidate_admitted_when_every_clause_passes():
    no_skill_attempts = [{"contaminated": False, "hit": False}] * 3

    record = compute_calibration_record(
        item_id="item-a",
        kind="gate-candidate",
        skill_hits=5,
        skill_n=6,
        no_skill_attempts=no_skill_attempts,
        audited_hits=5,
        audit=[],
        input_hash="a" * 64,
    )

    assert record["gate_or_trend_status"] == "gate"


def test_single_indeterminate_no_skill_attempt_replaced_by_a_miss_counts_only_the_replacement():
    attempts = [
        {"contaminated": True, "hit": True},
        {"contaminated": False, "hit": False},
        {"contaminated": False, "hit": False},
        {"contaminated": False, "hit": False},
    ]

    result = compute_no_skill_arm(attempts)

    assert result == {"n": 3, "hits": 0, "replacements": 1}


def test_gate_candidate_no_skill_arm_exactly_one_third_is_admitted():
    """The no-skill bar is *at most* 1 of 3 hits, so exactly 1/3 still passes.

    Kills a mutant that lowers the no-skill threshold from ``<= 1`` to
    ``<= 0``.
    """
    no_skill_attempts = [
        {"contaminated": False, "hit": True},
        {"contaminated": False, "hit": False},
        {"contaminated": False, "hit": False},
    ]

    record = compute_calibration_record(
        item_id="item-a",
        kind="gate-candidate",
        skill_hits=5,
        skill_n=6,
        no_skill_attempts=no_skill_attempts,
        audited_hits=5,
        audit=[],
        input_hash="a" * 64,
    )

    assert record["no_skill_arm_result"] == {"n": 3, "hits": 1, "replacements": 0}
    assert record["gate_or_trend_status"] == "gate"


def test_gate_candidate_two_contaminated_no_skill_attempts_then_three_clean_misses_is_admitted():
    """Two replacements are allowed; the arm still resolves to n=3, hits=0.

    Kills a mutant that lowers the contamination cap from 2 replacements to
    1 (which would call this ``baseline-void`` instead of admitting it).
    """
    no_skill_attempts = [
        {"contaminated": True, "hit": True},
        {"contaminated": True, "hit": True},
        {"contaminated": False, "hit": False},
        {"contaminated": False, "hit": False},
        {"contaminated": False, "hit": False},
    ]

    record = compute_calibration_record(
        item_id="item-a",
        kind="gate-candidate",
        skill_hits=5,
        skill_n=6,
        no_skill_attempts=no_skill_attempts,
        audited_hits=5,
        audit=[],
        input_hash="a" * 64,
    )

    assert record["no_skill_arm_result"] == {"n": 3, "hits": 0, "replacements": 2}
    assert record["gate_or_trend_status"] == "gate"


def test_gate_candidate_no_skill_arm_with_only_two_attempts_is_not_admitted():
    """The no-skill arm must land exactly 3 counted attempts, not fewer.

    Kills a mutant that drops the ``no_skill_arm_result["n"] == 3`` clause
    (which would admit on hit-rate alone, regardless of how many attempts
    were actually drawn).
    """
    no_skill_attempts = [
        {"contaminated": False, "hit": False},
        {"contaminated": False, "hit": False},
    ]

    record = compute_calibration_record(
        item_id="item-a",
        kind="gate-candidate",
        skill_hits=5,
        skill_n=6,
        no_skill_attempts=no_skill_attempts,
        audited_hits=5,
        audit=[],
        input_hash="a" * 64,
    )

    assert record["no_skill_arm_result"] == {"n": 2, "hits": 0, "replacements": 0}
    assert record["gate_or_trend_status"] == "trend"


def test_gate_candidate_skill_arm_with_five_of_five_is_not_admitted():
    """The skill arm must run exactly 6 executions, not merely hit 5.

    Kills a mutant that drops the ``skill_n == 6`` clause (which would admit
    on hit-rate alone at any n).
    """
    no_skill_attempts = [{"contaminated": False, "hit": False}] * 3

    record = compute_calibration_record(
        item_id="item-a",
        kind="gate-candidate",
        skill_hits=5,
        skill_n=5,
        no_skill_attempts=no_skill_attempts,
        audited_hits=5,
        audit=[],
        input_hash="a" * 64,
    )

    assert record["gate_or_trend_status"] == "trend"


# ---------------------------------------------------------------------------
# Triggering branch
# ---------------------------------------------------------------------------


def test_triggering_item_below_threshold_is_not_admitted():
    record = compute_calibration_record(
        item_id="item-a",
        kind="triggering",
        skill_hits=4,
        skill_n=6,
        no_skill_attempts=None,
        audited_hits=4,
        audit=[],
        input_hash="a" * 64,
    )

    assert record["gate_or_trend_status"] == "trend"
    assert record["no_skill_arm_result"] is None


def test_triggering_item_with_audited_rate_mismatch_is_not_admitted():
    record = compute_calibration_record(
        item_id="item-a",
        kind="triggering",
        skill_hits=5,
        skill_n=6,
        no_skill_attempts=None,
        audited_hits=4,
        audit=[],
        input_hash="a" * 64,
    )

    assert record["gate_or_trend_status"] == "trend"


@pytest.mark.parametrize("skill_hits", [5, 6])
def test_triggering_item_admitted_with_matching_audit_and_no_cross_match(skill_hits):
    record = compute_calibration_record(
        item_id="item-a",
        kind="triggering",
        skill_hits=skill_hits,
        skill_n=6,
        no_skill_attempts=None,
        audited_hits=skill_hits,
        audit=[],
        input_hash="a" * 64,
    )

    assert record["gate_or_trend_status"] == "gate"
    assert record["no_skill_arm_result"] is None


def test_non_triggering_item_with_no_no_skill_arm_is_not_admitted():
    record = compute_calibration_record(
        item_id="item-a",
        kind="gate-candidate",
        skill_hits=6,
        skill_n=6,
        no_skill_attempts=None,
        audited_hits=6,
        audit=[],
        input_hash="a" * 64,
    )

    assert record["gate_or_trend_status"] == "trend"


# ---------------------------------------------------------------------------
# Trend items
# ---------------------------------------------------------------------------


def test_trend_item_is_never_admitted_even_when_every_clause_would_pass():
    no_skill_attempts = [{"contaminated": False, "hit": False}] * 3

    record = compute_calibration_record(
        item_id="item-a",
        kind="trend",
        skill_hits=6,
        skill_n=6,
        no_skill_attempts=no_skill_attempts,
        audited_hits=6,
        audit=[],
        input_hash="a" * 64,
    )

    assert record["gate_or_trend_status"] == "trend"


# ---------------------------------------------------------------------------
# Record shape / schema validation
# ---------------------------------------------------------------------------


def test_record_validates_against_the_calibration_record_schema():
    record = compute_calibration_record(
        item_id="item-a",
        kind="gate-candidate",
        skill_hits=5,
        skill_n=6,
        no_skill_attempts=[{"contaminated": False, "hit": False}] * 3,
        audited_hits=5,
        audit=[],
        input_hash="a" * 64,
    )

    jsonschema.validate(record, _SCHEMA)


def test_triggering_record_validates_against_the_calibration_record_schema():
    record = compute_calibration_record(
        item_id="item-a",
        kind="triggering",
        skill_hits=6,
        skill_n=6,
        no_skill_attempts=None,
        audited_hits=6,
        audit=[],
        input_hash="a" * 64,
    )

    jsonschema.validate(record, _SCHEMA)


def test_unknown_kind_raises():
    with pytest.raises(ValueError):
        compute_calibration_record(
            item_id="item-a",
            kind="not-a-real-kind",
            skill_hits=6,
            skill_n=6,
            no_skill_attempts=None,
            audited_hits=6,
            audit=[],
            input_hash="a" * 64,
        )


# ---------------------------------------------------------------------------
# write_calibration_records: output scope
# ---------------------------------------------------------------------------


def test_write_calibration_records_writes_only_calibration_json_under_case_dir(tmp_path):
    case_dir = tmp_path / "evals" / "example-skill" / "case-a"
    case_dir.mkdir(parents=True)
    records = {
        "item-a": compute_calibration_record(
            item_id="item-a",
            kind="gate-candidate",
            skill_hits=5,
            skill_n=6,
            no_skill_attempts=[{"contaminated": False, "hit": False}] * 3,
            audited_hits=5,
            audit=[],
            input_hash="a" * 64,
        )
    }

    dest = write_calibration_records(case_dir, records)

    assert dest == case_dir / "calibration.json"
    written_files = [path for path in case_dir.rglob("*") if path.is_file()]
    assert written_files == [dest]
    for path in written_files:
        assert path.name != "tests.md"


def test_write_calibration_records_output_round_trips_and_validates(tmp_path):
    case_dir = tmp_path / "evals" / "example-skill" / "case-a"
    case_dir.mkdir(parents=True)
    record = compute_calibration_record(
        item_id="item-a",
        kind="gate-candidate",
        skill_hits=5,
        skill_n=6,
        no_skill_attempts=[{"contaminated": False, "hit": False}] * 3,
        audited_hits=5,
        audit=[],
        input_hash="a" * 64,
    )

    dest = write_calibration_records(case_dir, {"item-a": record})

    written = json.loads(dest.read_text(encoding="utf-8"))
    assert written == {"item-a": record}
    jsonschema.validate(written["item-a"], _SCHEMA)


def test_write_calibration_records_round_trips_a_non_empty_audit_list(tmp_path):
    """AC8: a written record's ``audit`` equals the input list verbatim."""
    case_dir = tmp_path / "evals" / "example-skill" / "case-a"
    case_dir.mkdir(parents=True)
    audit = [
        _audit_entry("item-a", "item-a", raw="raw-1", finding=0),
        _audit_entry("item-a", "item-b", raw="raw-2", finding=1),
    ]
    record = compute_calibration_record(
        item_id="item-a",
        kind="gate-candidate",
        skill_hits=5,
        skill_n=6,
        no_skill_attempts=[{"contaminated": False, "hit": False}] * 3,
        audited_hits=5,
        audit=audit,
        input_hash="a" * 64,
    )

    dest = write_calibration_records(case_dir, {"item-a": record})

    written = json.loads(dest.read_text(encoding="utf-8"))
    assert written["item-a"]["audit"] == audit


@pytest.mark.parametrize(
    "relative_case_dir",
    [
        "not_evals/example-skill/case-a",
        "evals/example-skill",
        "evals/example-skill/case-a/sub",
    ],
)
def test_write_calibration_records_refuses_a_case_dir_not_under_evals(tmp_path, relative_case_dir):
    """AC: writes only under ``evals/<skill>/<case>``; a test asserts both.

    Covers a wrong root, a directory one level too shallow, and one level too deep.
    """
    case_dir = tmp_path / relative_case_dir
    case_dir.mkdir(parents=True)
    record = compute_calibration_record(
        item_id="item-a",
        kind="gate-candidate",
        skill_hits=5,
        skill_n=6,
        no_skill_attempts=[{"contaminated": False, "hit": False}] * 3,
        audited_hits=5,
        audit=[],
        input_hash="a" * 64,
    )

    with pytest.raises(ValueError):
        write_calibration_records(case_dir, {"item-a": record})

    assert not (case_dir / "calibration.json").exists()


def test_write_calibration_records_refuses_a_symlinked_destination(tmp_path):
    """A pre-existing ``calibration.json`` symlink must not let the write escape ``evals/``."""
    case_dir = tmp_path / "evals" / "example-skill" / "case-a"
    case_dir.mkdir(parents=True)
    outside = tmp_path / "outside.json"
    outside.write_text("untouched\n", encoding="utf-8")
    (case_dir / "calibration.json").symlink_to(outside)
    record = compute_calibration_record(
        item_id="item-a",
        kind="gate-candidate",
        skill_hits=5,
        skill_n=6,
        no_skill_attempts=[{"contaminated": False, "hit": False}] * 3,
        audited_hits=5,
        audit=[],
        input_hash="a" * 64,
    )

    with pytest.raises(ValueError):
        write_calibration_records(case_dir, {"item-a": record})

    assert outside.read_text(encoding="utf-8") == "untouched\n"


def test_write_calibration_records_touches_no_file_besides_calibration_json(tmp_path):
    """Snapshot every file under tmp_path before/after: only calibration.json

    changes, and no ``tests.md`` appears anywhere — not only under case_dir.
    Kills a mutant that also writes a ``tests.md`` beside the case directory.
    """
    case_dir = tmp_path / "evals" / "example-skill" / "case-a"
    case_dir.mkdir(parents=True)
    record = compute_calibration_record(
        item_id="item-a",
        kind="gate-candidate",
        skill_hits=5,
        skill_n=6,
        no_skill_attempts=[{"contaminated": False, "hit": False}] * 3,
        audited_hits=5,
        audit=[],
        input_hash="a" * 64,
    )

    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}

    dest = write_calibration_records(case_dir, {"item-a": record})

    after = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}

    changed_or_new = {path for path in after if path not in before or after[path] != before[path]}
    assert changed_or_new == {dest}
    assert not any(path.name == "tests.md" for path in tmp_path.rglob("*"))


def test_write_calibration_records_raises_and_writes_nothing_for_a_record_failing_schema(tmp_path):
    """Kills a mutant that skips schema validation in the writer."""
    case_dir = tmp_path / "evals" / "example-skill" / "case-a"
    case_dir.mkdir(parents=True)
    bad_record = {"n": 6, "hits": 5}  # missing every other required field

    with pytest.raises(jsonschema.ValidationError):
        write_calibration_records(case_dir, {"item-a": bad_record})

    assert not (case_dir / "calibration.json").exists()


# ---------------------------------------------------------------------------
# compute_input_hash / fixture_fingerprint
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    )
    return result.stdout


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")


def _write_case_toml(case_dir: Path, *, items: list[dict], builder: str | None = None) -> None:
    lines = ['prompt = "prompt.md"']
    if builder is not None:
        lines.append(f'builder = "{builder}"')
    for item in items:
        lines.append("")
        lines.append("[[items]]")
        lines.append(f'id = "{item["id"]}"')
        lines.append(f'kind = "{item["kind"]}"')
        lines.append(f'scorer = "{item["scorer"]}"')
        lines.append("[items.params]")
        for key, value in item["params"].items():
            lines.append(f'{key} = "{value}"')
    (case_dir / "case.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _base_item(regex: str = "foo") -> dict:
    return {"id": "item-a", "kind": "gate-candidate", "scorer": "review_match", "params": {"regex": regex}}


def _commit_all(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)


def test_compute_input_hash_requires_a_fixture_or_a_builder(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    case_dir = repo / "evals" / "example-skill" / "case-a"
    case_dir.mkdir(parents=True)
    (case_dir / "prompt.md").write_text("do the thing\n", encoding="utf-8")
    _write_case_toml(case_dir, items=[_base_item()])
    _commit_all(repo, "case with no fixture or builder")

    with pytest.raises(ValueError):
        compute_input_hash(case_dir)

    with pytest.raises(ValueError):
        fixture_fingerprint(case_dir)


def test_compute_input_hash_changes_when_item_params_change(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    case_dir = repo / "evals" / "example-skill" / "case-a"
    fixture_dir = case_dir / "fixture"
    fixture_dir.mkdir(parents=True)
    (fixture_dir / "input.txt").write_text("fixture\n", encoding="utf-8")
    (case_dir / "prompt.md").write_text("do the thing\n", encoding="utf-8")
    _write_case_toml(case_dir, items=[_base_item("foo")])
    _commit_all(repo, "first")

    first_hash = compute_input_hash(case_dir)

    _write_case_toml(case_dir, items=[_base_item("bar")])
    _commit_all(repo, "second")

    second_hash = compute_input_hash(case_dir)

    assert first_hash != second_hash


def test_compute_input_hash_changes_when_predicates_change(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    case_dir = repo / "evals" / "example-skill" / "case-a"
    fixture_dir = case_dir / "fixture"
    fixture_dir.mkdir(parents=True)
    (fixture_dir / "input.txt").write_text("fixture\n", encoding="utf-8")
    (case_dir / "prompt.md").write_text("do the thing\n", encoding="utf-8")
    _write_case_toml(case_dir, items=[_base_item()])
    _commit_all(repo, "first")

    no_predicates_hash = compute_input_hash(case_dir)

    (case_dir / "predicates.py").write_text("def f():\n    return True\n", encoding="utf-8")
    _commit_all(repo, "add predicates")

    with_predicates_hash = compute_input_hash(case_dir)

    assert no_predicates_hash != with_predicates_hash


def test_compute_input_hash_changes_when_an_existing_predicates_body_changes(tmp_path):
    """``predicates_hash`` is a content hash, not an existence flag.

    Kills a mutant that replaces the sha256 of ``predicates.py``'s bytes with
    a bare existence boolean, which would be blind to an edit of an already-
    present file.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    case_dir = repo / "evals" / "example-skill" / "case-a"
    fixture_dir = case_dir / "fixture"
    fixture_dir.mkdir(parents=True)
    (fixture_dir / "input.txt").write_text("fixture\n", encoding="utf-8")
    (case_dir / "prompt.md").write_text("do the thing\n", encoding="utf-8")
    (case_dir / "predicates.py").write_text("def f():\n    return True\n", encoding="utf-8")
    _write_case_toml(case_dir, items=[_base_item()])
    _commit_all(repo, "first")

    first_hash = compute_input_hash(case_dir)

    (case_dir / "predicates.py").write_text("def f():\n    return False\n", encoding="utf-8")
    _commit_all(repo, "edit predicates body")

    second_hash = compute_input_hash(case_dir)

    assert first_hash != second_hash


def test_compute_input_hash_changes_when_prompt_text_changes(tmp_path):
    """Kills a mutant that drops ``prompt_text`` from the hashed payload."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    case_dir = repo / "evals" / "example-skill" / "case-a"
    fixture_dir = case_dir / "fixture"
    fixture_dir.mkdir(parents=True)
    (fixture_dir / "input.txt").write_text("fixture\n", encoding="utf-8")
    (case_dir / "prompt.md").write_text("do the thing\n", encoding="utf-8")
    _write_case_toml(case_dir, items=[_base_item()])
    _commit_all(repo, "first")

    first_hash = compute_input_hash(case_dir)

    (case_dir / "prompt.md").write_text("do the other thing\n", encoding="utf-8")
    _commit_all(repo, "change prompt text")

    second_hash = compute_input_hash(case_dir)

    assert first_hash != second_hash


def test_compute_input_hash_and_fixture_fingerprint_change_when_a_committed_fixture_file_changes(
    tmp_path,
):
    repo = tmp_path / "repo"
    _init_repo(repo)
    case_dir = repo / "evals" / "example-skill" / "case-a"
    fixture_dir = case_dir / "fixture"
    fixture_dir.mkdir(parents=True)
    (fixture_dir / "input.txt").write_text("v1\n", encoding="utf-8")
    (case_dir / "prompt.md").write_text("do the thing\n", encoding="utf-8")
    _write_case_toml(case_dir, items=[_base_item()])
    _commit_all(repo, "first")

    first_input_hash = compute_input_hash(case_dir)
    first_fingerprint = fixture_fingerprint(case_dir)

    (fixture_dir / "input.txt").write_text("v2\n", encoding="utf-8")
    _commit_all(repo, "change fixture")

    second_input_hash = compute_input_hash(case_dir)
    second_fingerprint = fixture_fingerprint(case_dir)

    assert first_input_hash != second_input_hash
    assert first_fingerprint != second_fingerprint


# A builder that pins every git identity/date so its output is reproducible
# across separate invocations: no test may depend on wall-clock time to
# distinguish "same" from "changed". It reads a committed ``seed.txt`` next
# to itself (in whichever directory it actually lives — the case dir, or a
# repo-root-relative directory named by ``case.toml``'s ``builder`` key) and
# writes that seed's content into an UNTRACKED output file, so a test can
# change only the seed (a committed input) without touching the builder's
# own script bytes.
_BUILDER_TEMPLATE = """\
import os
import subprocess
import sys
from pathlib import Path

dest = Path(sys.argv[1])
dest.mkdir(parents=True, exist_ok=True)
seed_path = Path(__file__).resolve().parent / "seed.txt"
seed_text = seed_path.read_text(encoding="utf-8") if seed_path.exists() else "no-seed"

subprocess.run(["git", "-C", str(dest), "init", "-q"], check=True)
subprocess.run(["git", "-C", str(dest), "config", "user.email", "t@example.com"], check=True)
subprocess.run(["git", "-C", str(dest), "config", "user.name", "T"], check=True)
(dest / "tracked.txt").write_text("tracked\\n", encoding="utf-8")
subprocess.run(["git", "-C", str(dest), "add", "-A"], check=True)

_commit_env = dict(os.environ)
_commit_env.update({
    "GIT_AUTHOR_NAME": "T",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "T",
    "GIT_COMMITTER_EMAIL": "t@example.com",
    "GIT_AUTHOR_DATE": "2020-01-01T00:00:00+00:00",
    "GIT_COMMITTER_DATE": "2020-01-01T00:00:00+00:00",
})
subprocess.run(
    ["git", "-C", str(dest), "commit", "-q", "-m", "built"],
    check=True,
    env=_commit_env,
)
(dest / "untracked.txt").write_text(seed_text, encoding="utf-8")
"""


def _write_builder_case(case_dir: Path, *, seed: str = "seed-v1", builder_text: str | None = None) -> None:
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "prompt.md").write_text("do the thing\n", encoding="utf-8")
    (case_dir / "seed.txt").write_text(seed, encoding="utf-8")
    (case_dir / "build_fixture.py").write_text(
        builder_text if builder_text is not None else _BUILDER_TEMPLATE, encoding="utf-8"
    )
    _write_case_toml(case_dir, items=[_base_item()])


def test_fixture_fingerprint_and_input_hash_stable_across_seconds_for_an_unchanged_builder_case(
    tmp_path,
):
    """A rebuild of the *same* builder case must fingerprint identically.

    Before the builder's git commit pinned its author/committer dates, two
    calls separated by real time produced different commit SHAs inside the
    built repo and therefore different fingerprints, even though nothing
    about the case changed — several other tests were passing only by
    timestamp drift. This is the direct regression test for that fix.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    case_dir = repo / "evals" / "example-skill" / "case-a"
    _write_builder_case(case_dir, seed="seed-v1")
    _commit_all(repo, "first")

    first_fingerprint = fixture_fingerprint(case_dir)
    first_hash = compute_input_hash(case_dir)

    time.sleep(1.1)

    second_fingerprint = fixture_fingerprint(case_dir)
    second_hash = compute_input_hash(case_dir)

    assert first_fingerprint == second_fingerprint
    assert first_hash == second_hash


def test_fixture_fingerprint_equals_a_manual_build_of_the_same_builder(tmp_path):
    """``fixture_fingerprint`` is exactly ``builder_output_fingerprint`` of a

    fresh build of the case's own builder — verified by building it a second
    time by hand, into a separate temp dir, and comparing.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    case_dir = repo / "evals" / "example-skill" / "case-a"
    _write_builder_case(case_dir, seed="seed-v1")
    _commit_all(repo, "first")

    result = fixture_fingerprint(case_dir)

    manual_dest = tmp_path / "manual-build"
    subprocess.run(
        [sys.executable, str(case_dir / "build_fixture.py"), str(manual_dest)],
        check=True,
        cwd=str(repo),
    )
    expected = builder_output_fingerprint(manual_dest)

    assert result == expected


def test_seed_input_change_changes_fixture_fingerprint_and_input_hash(tmp_path):
    """Changing only a committed input the builder reads (not its own script)

    must change both the fixture fingerprint and the input hash — the
    builder's UNTRACKED output differs, which is exactly what
    ``builder_output_fingerprint`` is for.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    case_dir = repo / "evals" / "example-skill" / "case-a"
    _write_builder_case(case_dir, seed="seed-v1")
    _commit_all(repo, "first")

    first_fingerprint = fixture_fingerprint(case_dir)
    first_hash = compute_input_hash(case_dir)

    (case_dir / "seed.txt").write_text("seed-v2", encoding="utf-8")
    _commit_all(repo, "change committed seed input only")

    second_fingerprint = fixture_fingerprint(case_dir)
    second_hash = compute_input_hash(case_dir)

    assert first_fingerprint != second_fingerprint
    assert first_hash != second_hash


def test_compute_input_hash_changes_when_builder_script_content_changes_even_if_output_is_same(
    tmp_path,
):
    repo = tmp_path / "repo"
    _init_repo(repo)
    case_dir = repo / "evals" / "example-skill" / "case-a"
    _write_builder_case(case_dir, seed="seed-v1")
    _commit_all(repo, "first")

    first_hash = compute_input_hash(case_dir)

    # Append a no-op comment: the builder's own script content changes, but
    # (with dates pinned and the seed unchanged) its built output is
    # genuinely byte-identical, so only builder_hash can be what moves this.
    builder_path = case_dir / "build_fixture.py"
    builder_path.write_text(
        builder_path.read_text(encoding="utf-8") + "\n# a harmless comment\n", encoding="utf-8"
    )
    _commit_all(repo, "no-op comment change")

    second_hash = compute_input_hash(case_dir)

    assert first_hash != second_hash


def test_compute_input_hash_hashes_both_when_a_case_supplies_a_fixture_and_a_builder(tmp_path):
    """A case with both a committed fixture and a builder hashes both

    independently: changing only the fixture moves the hash, and — from
    that same starting point reverted — changing only the builder script
    moves it too.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    case_dir = repo / "evals" / "example-skill" / "case-a"
    fixture_dir = case_dir / "fixture"
    fixture_dir.mkdir(parents=True)
    (fixture_dir / "input.txt").write_text("v1\n", encoding="utf-8")
    _write_builder_case(case_dir, seed="seed-v1")
    _commit_all(repo, "first")

    base_hash = compute_input_hash(case_dir)

    (fixture_dir / "input.txt").write_text("v2\n", encoding="utf-8")
    _commit_all(repo, "change committed fixture that the builder also reads")

    fixture_changed_hash = compute_input_hash(case_dir)
    assert fixture_changed_hash != base_hash

    (fixture_dir / "input.txt").write_text("v1\n", encoding="utf-8")
    builder_path = case_dir / "build_fixture.py"
    builder_path.write_text(
        builder_path.read_text(encoding="utf-8") + "\n# a harmless comment\n", encoding="utf-8"
    )
    _commit_all(repo, "revert fixture, change builder only")

    builder_changed_hash = compute_input_hash(case_dir)
    assert builder_changed_hash != base_hash


def test_compute_input_hash_resolves_builder_key_against_repo_root(tmp_path):
    """A ``case.toml`` ``builder`` key is repo-root-relative, not case-dir-

    relative: the builder lives outside the case directory, and a content
    change to it still moves the hash.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    builders_dir = repo / "builders"
    builders_dir.mkdir()
    (builders_dir / "b.py").write_text(_BUILDER_TEMPLATE, encoding="utf-8")
    case_dir = repo / "evals" / "example-skill" / "case-a"
    case_dir.mkdir(parents=True)
    (case_dir / "prompt.md").write_text("do the thing\n", encoding="utf-8")
    _write_case_toml(case_dir, items=[_base_item()], builder="builders/b.py")
    _commit_all(repo, "first")

    first_hash = compute_input_hash(case_dir)

    builder_path = builders_dir / "b.py"
    builder_path.write_text(
        builder_path.read_text(encoding="utf-8") + "\n# a harmless comment\n", encoding="utf-8"
    )
    _commit_all(repo, "change out-of-case-dir builder content")

    second_hash = compute_input_hash(case_dir)

    assert first_hash != second_hash
