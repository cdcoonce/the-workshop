"""Contract tests for the adversarial-review/A3 case: its files, wiring, fixture and prompt."""

from __future__ import annotations

import os
import re
import subprocess
import sys

from evals._harness import calibration
from evals._harness.dispatch import build_dispatch_prompt, find_acceptance_leaks, find_invalid_modes

# Words that belong to the review lens itself. A prompt carrying them would hand the
# case-agent the discipline, and triggering would stop measuring whether the skill fires.
_LENS_VOCABULARY = (
    "adversar",
    "attack",
    "hostile",
    "disprove",
    "falsif",
    "try to break",
    "could not verify",
    "evidence",
    "defect",
    "edge case",
)
_CASE_KEYS = {"mode", "prompt", "builder", "items"}
_ITEM_KEYS = {"id", "kind", "scorer", "params"}


def test_case_declares_subagent_mode_and_a_prompt_file(case_toml, case_dir):
    assert case_toml["mode"] == "subagent"
    assert case_toml["prompt"] == "prompt.md"
    assert find_invalid_modes([case_dir]) == []


def test_case_has_exactly_one_item_and_it_is_a_triggering_item(case_toml):
    assert len(case_toml["items"]) == 1
    item = case_toml["items"][0]
    assert item["kind"] == "triggering"
    assert item["id"] == "A3"


def test_the_item_names_the_rostered_skill_and_a_scorer_that_exists(case_toml, predicates, rostered_skill):
    item = case_toml["items"][0]
    # Real transcripts carry the plugin-qualified name in the Skill call's input.skill, and
    # skill_triggered_first compares exactly, so the param must be "workbench:<name>".
    assert item["params"] == {"skill": f"workbench:{rostered_skill}"}
    assert callable(getattr(predicates, item["scorer"]))


def test_case_carries_no_calibration_key(case_toml):
    assert set(case_toml) <= _CASE_KEYS
    assert set(case_toml["items"][0]) <= _ITEM_KEYS
    assert "envelope" not in case_toml


def test_triggering_kind_selects_the_skill_arm_only_admission_branch(case_toml):
    kind = case_toml["items"][0]["kind"]
    common = {"item_id": "A3", "kind": kind, "skill_n": 6, "audited_hits": 5, "audit": [], "input_hash": "0" * 64}
    admitted = calibration.compute_calibration_record(skill_hits=5, no_skill_attempts=None, **common)
    assert admitted["gate_or_trend_status"] == "gate"
    assert admitted["n"] == 6
    assert admitted["no_skill_arm_result"] is None
    short = calibration.compute_calibration_record(
        skill_hits=4, no_skill_attempts=None, **{**common, "audited_hits": 4}
    )
    assert short["gate_or_trend_status"] == "trend"


def test_case_ships_prompt_acceptance_and_predicates(case_dir):
    for name in ("prompt.md", "acceptance.md", "predicates.py"):
        assert (case_dir / name).is_file(), name


def test_case_uses_the_skills_own_builder_so_no_agent_runs_in_the_workshop_checkout(
    case_toml, case_dir, repo_root
):
    assert case_toml["builder"] == "plugins/workbench/skills/adversarial-review/scripts/build_fixture.py"
    assert (repo_root / case_toml["builder"]).is_file()
    assert not (case_dir / "fixture").exists()
    assert not (case_dir / "provenance.toml").exists()


def test_built_fixture_is_a_repo_with_a_branch_checked_out_and_no_remote(case_toml, repo_root, tmp_path):
    dest = tmp_path / "built"
    subprocess.run(
        [sys.executable, str(repo_root / case_toml["builder"]), str(dest)],
        check=True,
        capture_output=True,
        cwd=repo_root,
    )

    def git(*args: str) -> str:
        # No inherited GIT_* (a hook environment sets GIT_DIR): the repo under test is `dest`.
        env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        return subprocess.run(
            ["git", "-C", str(dest), *args], check=True, capture_output=True, text=True, env=env
        ).stdout.strip()

    assert git("branch", "--show-current") not in ("", "main")
    assert git("rev-parse", "--verify", "main")
    assert git("remote") == ""
    assert git("status", "--porcelain") == ""


def test_fixture_fingerprint_is_the_builder_output_fingerprint(case_dir):
    assert re.fullmatch(r"[0-9a-f]{64}", calibration.fixture_fingerprint(case_dir))


def test_prompt_is_a_pre_merge_check_request_with_no_user_turns(case_dir):
    prompt = build_dispatch_prompt(case_dir)
    assert prompt.strip()
    assert re.search(r"\bmerge\b", prompt, re.IGNORECASE)
    assert re.search(r"\b(?:check|look)\b", prompt, re.IGNORECASE)
    assert not re.search(r"^\s*(?:human|user|assistant)\s*:", prompt, re.IGNORECASE | re.MULTILINE)
    assert "\n---" not in prompt


def test_prompt_does_not_smuggle_the_review_lens(case_dir):
    prompt = build_dispatch_prompt(case_dir).lower()
    for needle in _LENS_VOCABULARY:
        assert needle not in prompt, needle


def test_prompt_leaks_nothing_from_acceptance(case_dir):
    prompt = (case_dir / "prompt.md").read_text(encoding="utf-8")
    assert find_acceptance_leaks(case_dir, prompt) == []
    assert build_dispatch_prompt(case_dir) == prompt


def test_acceptance_records_real_criteria(case_dir):
    acceptance = (case_dir / "acceptance.md").read_text(encoding="utf-8")
    assert "A3" in acceptance
    assert "Skill" in acceptance


def test_acceptance_notes_that_real_runs_carry_the_plugin_qualified_skill_name(case_dir, rostered_skill):
    acceptance = (case_dir / "acceptance.md").read_text(encoding="utf-8")
    assert f"workbench:{rostered_skill}" in acceptance
    assert "investigated" in acceptance
