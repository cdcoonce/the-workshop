"""Tests for evals._harness.calibration — the admission rule and its hashes."""

from __future__ import annotations

import json
import subprocess
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


_BUILDER_TEMPLATE = """\
import sys
from pathlib import Path
import subprocess

dest = Path(sys.argv[1])
dest.mkdir(parents=True, exist_ok=True)
subprocess.run(["git", "-C", str(dest), "init", "-q"], check=True)
subprocess.run(["git", "-C", str(dest), "config", "user.email", "t@example.com"], check=True)
subprocess.run(["git", "-C", str(dest), "config", "user.name", "T"], check=True)
(dest / "tracked.txt").write_text("tracked\\n", encoding="utf-8")
subprocess.run(["git", "-C", str(dest), "add", "-A"], check=True)
subprocess.run(["git", "-C", str(dest), "commit", "-q", "-m", "built"], check=True)
(dest / "untracked.txt").write_text({untracked!r}, encoding="utf-8")
"""


def test_fixture_fingerprint_uses_builder_output_for_a_builder_case(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    case_dir = repo / "evals" / "example-skill" / "case-a"
    case_dir.mkdir(parents=True)
    (case_dir / "prompt.md").write_text("do the thing\n", encoding="utf-8")
    (case_dir / "build_fixture.py").write_text(
        _BUILDER_TEMPLATE.format(untracked="one"), encoding="utf-8"
    )
    _write_case_toml(case_dir, items=[_base_item()])
    _commit_all(repo, "first")

    first_fingerprint = fixture_fingerprint(case_dir)

    (case_dir / "build_fixture.py").write_text(
        _BUILDER_TEMPLATE.format(untracked="two"), encoding="utf-8"
    )
    _commit_all(repo, "change untracked output only")

    second_fingerprint = fixture_fingerprint(case_dir)

    assert first_fingerprint != second_fingerprint


def test_compute_input_hash_changes_when_builder_script_content_changes_even_if_output_is_same(
    tmp_path,
):
    repo = tmp_path / "repo"
    _init_repo(repo)
    case_dir = repo / "evals" / "example-skill" / "case-a"
    case_dir.mkdir(parents=True)
    (case_dir / "prompt.md").write_text("do the thing\n", encoding="utf-8")
    (case_dir / "build_fixture.py").write_text(
        _BUILDER_TEMPLATE.format(untracked="same"), encoding="utf-8"
    )
    _write_case_toml(case_dir, items=[_base_item()])
    _commit_all(repo, "first")

    first_hash = compute_input_hash(case_dir)

    # Append a no-op comment: the builder's own script content changes, but
    # its built output (still writing "same") does not.
    builder_path = case_dir / "build_fixture.py"
    builder_path.write_text(
        builder_path.read_text(encoding="utf-8") + "\n# a harmless comment\n", encoding="utf-8"
    )
    _commit_all(repo, "no-op comment change")

    second_hash = compute_input_hash(case_dir)

    assert first_hash != second_hash


def test_compute_input_hash_hashes_both_when_a_case_supplies_a_fixture_and_a_builder(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    case_dir = repo / "evals" / "example-skill" / "case-a"
    fixture_dir = case_dir / "fixture"
    fixture_dir.mkdir(parents=True)
    (fixture_dir / "input.txt").write_text("v1\n", encoding="utf-8")
    (case_dir / "prompt.md").write_text("do the thing\n", encoding="utf-8")
    (case_dir / "build_fixture.py").write_text(
        _BUILDER_TEMPLATE.format(untracked="one"), encoding="utf-8"
    )
    _write_case_toml(case_dir, items=[_base_item()])
    _commit_all(repo, "first")

    first_hash = compute_input_hash(case_dir)

    (fixture_dir / "input.txt").write_text("v2\n", encoding="utf-8")
    _commit_all(repo, "change committed fixture that the builder also reads")

    second_hash = compute_input_hash(case_dir)

    assert first_hash != second_hash
