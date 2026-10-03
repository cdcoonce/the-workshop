"""A1 holds a case directory that satisfies #995's case-directory contract."""

from __future__ import annotations

import ast
import re
import subprocess
import tomllib
from pathlib import Path

import pytest

from evals._harness.dispatch import (
    build_dispatch_prompt,
    find_acceptance_leaks,
    find_duplicate_item_ids,
    score_attempt,
)
from evals._harness.fingerprint import builder_output_fingerprint

_BUILDER = "plugins/workbench/skills/adversarial-review/scripts/build_fixture.py"
_TESTS_MD = "plugins/workbench/skills/adversarial-review/tests.md"
_GATE_ID = "A1-coverage-bound"
_TREND_IDS = {"A1-defect-decimal-from-float", "A1-defect-tests-no-teeth", "A1-defect-missed-call-site"}


def test_case_directory_holds_the_required_files_and_no_fixture_source_of_its_own(case_dir):
    for name in ("case.toml", "prompt.md", "acceptance.md", "provenance.toml", "predicates.py"):
        assert (case_dir / name).is_file(), name
    # The builder lives under plugins/ and is run in place: A1 never copies it.
    assert not (case_dir / "fixture").exists()
    assert not (case_dir / "build_fixture.py").exists()


def test_case_toml_declares_subagent_mode_prompt_and_the_plugin_builder(case_toml):
    assert case_toml["mode"] == "subagent"
    assert case_toml["prompt"] == "prompt.md"
    assert case_toml["builder"] == _BUILDER


def test_every_item_has_id_kind_and_a_scorer_that_predicates_defines(case_toml, predicates):
    items = case_toml["items"]
    assert items, "A1 declares no items"
    for item in items:
        assert item["id"] and item["kind"] in {"gate-candidate", "trend", "triggering"}
        assert callable(getattr(predicates, item["scorer"], None)), item["id"]


def test_one_gate_candidate_coverage_bound_and_three_trend_defects(case_toml):
    by_id = {item["id"]: item["kind"] for item in case_toml["items"]}
    assert by_id[_GATE_ID] == "gate-candidate"
    assert {i for i, kind in by_id.items() if kind == "trend"} == _TREND_IDS
    assert set(by_id) == {_GATE_ID} | _TREND_IDS


def test_planted_defects_are_never_gate_candidates_and_a1_is_not_in_checks_manifest(
    case_toml, case_dir
):
    for item in case_toml["items"]:
        if item["id"] in _TREND_IDS:
            assert item["kind"] == "trend"
    manifest = (case_dir.parent / "checks.manifest").read_text(encoding="utf-8")
    assert not any(item["id"] in manifest for item in case_toml["items"])


def test_envelope_is_set_if_and_only_if_a_scorer_reads_evidence_findings(case_toml, case_dir):
    tree = ast.parse((case_dir / "predicates.py").read_text(encoding="utf-8"))
    reads_findings = any(isinstance(n, ast.Attribute) and n.attr == "findings" for n in ast.walk(tree))
    assert ("envelope" in case_toml) == reads_findings


def test_item_ids_are_unique_within_the_skill(case_dir):
    assert find_duplicate_item_ids(case_dir.parent) == set()


def _scenario_1_cell(repo_root: Path) -> str:
    """The Scenario cell of ID 1 in tests.md's "Kept scenarios" table."""
    text = (repo_root / _TESTS_MD).read_text(encoding="utf-8")
    section = text.split("## Kept scenarios", 1)[1]
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if line.startswith("|") and cells[0] == "1":
            return cells[1]
    raise AssertionError("no scenario ID 1 row in the Kept scenarios table")


def test_prompt_is_the_scenario_1_cell_of_the_kept_scenarios_table_verbatim(case_dir, repo_root):
    assert (case_dir / "prompt.md").read_text(encoding="utf-8").strip() == _scenario_1_cell(repo_root)


def test_provenance_records_the_copied_prompts_source_path_and_its_blob_sha_at_the_resolved_ref(
    case_dir, repo_root
):
    provenance = tomllib.loads((case_dir / "provenance.toml").read_text(encoding="utf-8"))
    by_file = {entry["file"]: entry for entry in provenance["files"]}
    assert set(by_file) == {"prompt.md"}, "only prompt.md is copied; the builder is run in place"
    entry = by_file["prompt.md"]
    assert entry["source_path"] == _TESTS_MD
    assert re.fullmatch(r"[0-9a-f]{40}", entry["source_blob_sha"])
    # Pinned at the recorded ref, so a later edit to tests.md never turns this red.
    at_ref = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", f"{provenance['resolved_ref']}:{_TESTS_MD}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert entry["source_blob_sha"] == at_ref


def test_dispatch_prompt_is_prompt_md_and_carries_no_text_from_acceptance_md(case_dir):
    prompt = build_dispatch_prompt(case_dir)
    assert prompt == (case_dir / "prompt.md").read_text(encoding="utf-8")
    assert find_acceptance_leaks(case_dir, prompt) == []
    assert (case_dir / "acceptance.md").read_text(encoding="utf-8").strip()


def test_fixture_rebuilds_are_fingerprint_identical_across_two_builds(build_fixture, tmp_path):
    first = build_fixture(tmp_path / "one")
    second = build_fixture(tmp_path / "two")
    assert builder_output_fingerprint(first) == builder_output_fingerprint(second)


def test_built_fixture_has_main_and_the_claimed_fix_branch(build_fixture, tmp_path):
    repo = build_fixture(tmp_path / "fx")
    branches = subprocess.run(
        ["git", "-C", str(repo), "branch", "--format=%(refname:short)"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    assert set(branches) == {"main", "fix/settlement-rounding"}


def test_no_copy_of_the_builder_exists_under_evals(repo_root):
    # Only the plugin's own build_fixture.py exists; this case runs it in place.
    # Scoped to this skill's tree: a sibling skill's case (commit/C) ships its own
    # builder, and that is not a copy of this one.
    copies = [p for p in (repo_root / "evals" / "adversarial-review").rglob("build_fixture.py")]
    assert copies == []


@pytest.mark.parametrize(
    ("reply", "hit"),
    [
        ("## Could not verify\nI never executed `pytest.ini` handling.\n", True),
        ("## Findings\nrounding.py is wrong.\n", False),
    ],
)
def test_score_attempt_runs_the_gate_candidate_end_to_end(tmp_path, case_dir, reply, hit):
    import json

    transcript = tmp_path / "t.jsonl"
    transcript.write_text(
        json.dumps({"type": "assistant", "message": {"model": "claude-test", "content": [{"type": "text", "text": reply}]}})
        + "\n",
        encoding="utf-8",
    )
    attempt, unmatched = score_attempt(case_dir, [transcript], None, {_GATE_ID})
    assert attempt.item_hits[_GATE_ID] == ("hit" if hit else "miss")
    assert unmatched == 0
