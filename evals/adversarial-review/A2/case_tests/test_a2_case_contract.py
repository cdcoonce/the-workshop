"""A2's case-directory contract, and that its matchers keep the experiment's ground truth.

``fixture/defects.json`` is the experiment's own ground truth. A2 repairs the
experiment's scoring (``score_arm.py:65``, ``return in_window or
bool(regex.search(desc))``) without rewriting that data: D1, D2, D3 and D4 keep
their file suffix, window and regex; D4 and D5 are file-level; D5's regex is
tightened.
"""

from __future__ import annotations

import re

import pytest

from evals._harness import dispatch
from evals._harness.calibration import fixture_fingerprint
from evals._harness.deps import tree_hash

_FIXTURE = "evals/adversarial-review/A2/fixture"


def test_case_runs_inline_with_the_findings_envelope(case_toml):
    assert case_toml["mode"] == "inline"
    assert case_toml["envelope"] == "findings"
    assert case_toml["prompt"] == "prompt.md"


def test_case_has_a_static_fixture_and_no_builder_of_its_own(case_toml, case_dir):
    assert "builder" not in case_toml
    assert not (case_dir / "build_fixture.py").exists()
    assert (case_dir / "fixture").is_dir()


def test_case_directory_holds_the_contract_files(case_dir):
    for name in ("case.toml", "prompt.md", "acceptance.md", "predicates.py", "provenance.toml"):
        assert (case_dir / name).is_file(), name


def test_every_item_carries_id_kind_and_scorer(items):
    for item_id, item in items.items():
        assert item["kind"] in {"gate-candidate", "trend"}, item_id
        assert item["scorer"], item_id


def test_the_harness_accepts_the_case(case_dir):
    assert dispatch.find_invalid_modes([case_dir]) == []
    assert dispatch.find_duplicate_item_ids(case_dir.parent) == set()
    dispatch._case_toml(case_dir)


@pytest.mark.parametrize("defect", ["D1", "D2", "D3", "D4"])
def test_matchers_keep_the_experiments_suffix_and_regex(items, defects, defect):
    params = items[f"A2-{defect}"]["params"]
    assert params["file_suffix"] == defects[defect]["file_suffix"]
    assert params["regex"] == defects[defect]["regex"]


@pytest.mark.parametrize("defect", ["D1", "D2", "D3"])
def test_windowed_matchers_keep_the_experiments_line_window(items, defects, defect):
    assert items[f"A2-{defect}"]["params"]["line_window"] == defects[defect]["line_window"]


@pytest.mark.parametrize("defect", ["D4", "D5"])
def test_d4_and_d5_are_file_level_exactly_as_defects_json_records(items, defects, defect):
    assert defects[defect]["line_window"] is None
    assert "line_window" not in items[f"A2-{defect}"]["params"]
    assert items[f"A2-{defect}"]["params"]["file_suffix"] == defects[defect]["file_suffix"]


def test_d5_keeps_the_experiments_file_suffix_but_not_its_regex(items, defects):
    params = items["A2-D5"]["params"]
    assert params["file_suffix"] == defects["D5"]["file_suffix"]
    assert params["regex"] != defects["D5"]["regex"]
    # The experiment's regex was a bare alternation of three words; the tightened one is
    # not satisfied by a word alone.
    assert re.search(defects["D5"]["regex"], "staged", re.IGNORECASE)
    assert not re.search(params["regex"], "staged", re.IGNORECASE)
    assert not re.search(params["regex"], "--cached", re.IGNORECASE)
    assert not re.search(params["regex"], "uncommitted", re.IGNORECASE)


def test_the_fixture_fingerprint_is_the_tree_hash_of_the_committed_fixture(case_dir):
    assert fixture_fingerprint(case_dir) == tree_hash([_FIXTURE])
    assert fixture_fingerprint(case_dir) == fixture_fingerprint(case_dir)


def test_the_fixture_tree_hash_is_pinned_to_committed_blobs_not_the_work_tree(case_dir):
    """``tree_hash`` reads HEAD blobs, so the fixture must be committed before it is fingerprinted."""
    committed = {path.name for path in (case_dir / "fixture").iterdir()}
    assert committed == {"defects.json", "diff.patch", "spec.md"}
    assert re.fullmatch(r"[0-9a-f]{64}", fixture_fingerprint(case_dir))


def test_the_ab_raws_are_never_read_as_calibration_input(case_dir, case_toml):
    """Matcher development and the cross-match audit only: nothing scored or fingerprinted reads them."""
    predicates_source = (case_dir / "predicates.py").read_text(encoding="utf-8")
    assert "ab_raws" not in predicates_source
    assert not any("ab_raws" in str(value) for item in case_toml["items"] for value in item.get("params", {}).values())
    assert "ab_raws" not in case_toml["prompt"]
    raws_note = (case_dir / "case.toml").read_text(encoding="utf-8")
    assert "never calibration input" in raws_note
    assert not (case_dir / "fixture" / "ab_raws").exists()
