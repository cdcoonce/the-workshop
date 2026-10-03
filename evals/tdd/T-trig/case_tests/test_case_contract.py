"""Contract tests for the tdd/T-trig case: its files, wiring, fixture and prompt."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tomllib

from evals._harness import calibration
from evals._harness.deps import tree_hash
from evals._harness.dispatch import build_dispatch_prompt, find_acceptance_leaks, find_invalid_modes

# Words that belong to the discipline itself. A prompt carrying them would hand the
# case-agent the method, and triggering would stop measuring whether the skill fires.
_DISCIPLINE_VOCABULARY = (
    "tdd",
    "test-driven",
    "red-green",
    "refactor",
    "failing test",
    "iron law",
    "one test at a time",
    "vertical slice",
)
_DISCIPLINE_WORDS = (r"\bred\b", r"\bgreen\b")
_CASE_KEYS = {"mode", "prompt", "items"}
_ITEM_KEYS = {"id", "kind", "scorer", "params"}


def test_case_declares_subagent_mode_and_a_prompt_file(case_toml, case_dir):
    assert case_toml["mode"] == "subagent"
    assert case_toml["prompt"] == "prompt.md"
    assert find_invalid_modes([case_dir]) == []


def test_case_has_exactly_one_item_and_it_is_a_triggering_item(case_toml):
    assert len(case_toml["items"]) == 1
    item = case_toml["items"][0]
    assert item["kind"] == "triggering"
    assert item["id"] == "T-trig"


def test_the_item_names_the_rostered_skill_and_a_scorer_that_exists(case_toml, predicates, rostered_skill):
    item = case_toml["items"][0]
    # Real transcripts carry the plugin-qualified name in the Skill call's input.skill, and
    # skill_triggered_first compares exactly, so the param must be "workbench:<name>".
    assert item["params"] == {"skill": f"workbench:{rostered_skill}"}
    assert callable(getattr(predicates, item["scorer"]))


def test_case_carries_no_calibration_key_and_no_calibration_record(case_toml, case_dir):
    assert set(case_toml) <= _CASE_KEYS
    assert set(case_toml["items"][0]) <= _ITEM_KEYS
    assert "envelope" not in case_toml
    assert not (case_dir / "calibration.json").exists()


def test_triggering_kind_selects_the_skill_arm_only_admission_branch(case_toml):
    kind = case_toml["items"][0]["kind"]
    common = {"item_id": "T-trig", "kind": kind, "skill_n": 6, "audited_hits": 5, "audit": [], "input_hash": "0" * 64}
    admitted = calibration.compute_calibration_record(skill_hits=5, no_skill_attempts=None, **common)
    assert admitted["gate_or_trend_status"] == "gate"
    assert admitted["n"] == 6
    assert admitted["no_skill_arm_result"] is None
    short = calibration.compute_calibration_record(
        skill_hits=4, no_skill_attempts=None, **{**common, "audited_hits": 4}
    )
    assert short["gate_or_trend_status"] == "trend"


def test_case_ships_prompt_acceptance_predicates_and_a_committed_fixture(case_dir):
    for name in ("prompt.md", "acceptance.md", "predicates.py"):
        assert (case_dir / name).is_file(), name
    assert (case_dir / "fixture").is_dir()


def test_case_has_no_builder_and_no_provenance(case_toml, case_dir):
    assert not (case_dir / "build_fixture.py").exists()
    assert "builder" not in case_toml
    assert not (case_dir / "provenance.toml").exists()


def test_fixture_pins_pytest_directly(case_dir):
    pyproject = tomllib.loads((case_dir / "fixture" / "pyproject.toml").read_text(encoding="utf-8"))
    requirements = list(pyproject.get("project", {}).get("dependencies", []))
    for group in pyproject.get("dependency-groups", {}).values():
        requirements.extend(entry for entry in group if isinstance(entry, str))
    assert any(re.fullmatch(r"pytest==\d+(\.\d+)*", entry) for entry in requirements), requirements


def test_no_lockfile_or_env_file_is_committed_anywhere_under_the_case(case_dir):
    forbidden = {"uv.lock", "package-lock.json"}
    assert [path for path in case_dir.rglob("*") if path.name in forbidden] == []
    assert [path for path in case_dir.rglob(".env*")] == []


def test_fixture_base_suite_is_green(case_dir, tmp_path):
    workdir = tmp_path / "work"
    shutil.copytree(case_dir / "fixture", workdir)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
        cwd=workdir,
        capture_output=True,
        text=True,
        env={"PYTHONDONTWRITEBYTECODE": "1", "PATH": ""},
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_fixture_does_not_already_ship_the_requested_function(case_dir):
    fixture = case_dir / "fixture"
    assert not (fixture / "src" / "textkit" / "truncate.py").exists()
    assert not any("truncate_words" in path.read_text(encoding="utf-8") for path in fixture.rglob("*.py"))


def test_fixture_fingerprint_is_the_committed_fixture_tree_hash(case_dir, repo_root):
    """The fingerprint equals #995's tier hash of the committed fixture, computed independently."""
    fixture_path = case_dir.relative_to(repo_root).as_posix() + "/fixture"
    expected = tree_hash([fixture_path], repo=repo_root)
    assert re.fullmatch(r"[0-9a-f]{64}", expected)
    assert calibration.fixture_fingerprint(case_dir) == expected
    # It hashes this fixture and nothing else: another tree gives another digest.
    assert expected != tree_hash([case_dir.relative_to(repo_root).as_posix() + "/case_tests"], repo=repo_root)
    # It reads committed blobs, so every fixture file must be tracked.
    tracked = subprocess.run(
        ["git", "ls-files", "--", fixture_path], cwd=repo_root, capture_output=True, text=True, check=True
    ).stdout.split()
    on_disk = sorted(
        path.relative_to(repo_root).as_posix() for path in (case_dir / "fixture").rglob("*") if path.is_file()
    )
    assert sorted(tracked) == on_disk


def test_prompt_is_a_natural_test_first_request_with_no_user_turns(case_dir):
    prompt = build_dispatch_prompt(case_dir)
    assert "truncate_words" in prompt
    assert "test-first" in prompt.lower()
    assert not re.search(r"^\s*(?:human|user|assistant)\s*:", prompt, re.IGNORECASE | re.MULTILINE)
    assert "\n---" not in prompt


def test_prompt_does_not_smuggle_the_discipline(case_dir):
    prompt = build_dispatch_prompt(case_dir).lower()
    for needle in _DISCIPLINE_VOCABULARY:
        assert needle not in prompt, needle
    for pattern in _DISCIPLINE_WORDS:
        assert not re.search(pattern, prompt), pattern


def test_prompt_leaks_nothing_from_acceptance(case_dir):
    prompt = (case_dir / "prompt.md").read_text(encoding="utf-8")
    assert find_acceptance_leaks(case_dir, prompt) == []
    assert build_dispatch_prompt(case_dir) == prompt


def test_acceptance_records_real_criteria(case_dir):
    acceptance = (case_dir / "acceptance.md").read_text(encoding="utf-8")
    assert "T-trig" in acceptance
    assert "Skill" in acceptance


def test_acceptance_notes_that_real_runs_carry_the_plugin_qualified_skill_name(case_dir, rostered_skill):
    acceptance = (case_dir / "acceptance.md").read_text(encoding="utf-8")
    assert f"workbench:{rostered_skill}" in acceptance
    assert "investigated" in acceptance
