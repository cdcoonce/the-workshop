"""Contract tests for the tdd/T case: its files, its fixture, and its dispatch prompt."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

from evals._harness import calibration
from evals._harness.dispatch import (
    build_dispatch_prompt,
    build_no_skill_prompt,
    find_acceptance_leaks,
    find_invalid_modes,
)

_CASE_DIR = Path(__file__).resolve().parents[1]
_FIXTURE = _CASE_DIR / "fixture"
_TAUTOLOGY = "assert subtotal_cents(items) == subtotal_cents(items)"
_PREAMBLE = "Use the workbench:tdd skill for this task.\n\n"


def _prompt_body() -> str:
    """The dispatched prompt minus the one harness-owned preamble line (``invoke_skill``).

    The vocabulary guards below police what the case wrote, so they read this: the prompt
    file's text exactly as it reaches the agent, without the line that names the skill on
    purpose. ``test_the_skill_arm_prompt_is_the_preamble_then_the_prompt_file_verbatim`` pins
    that the remainder is the file, byte for byte.
    """
    built = build_dispatch_prompt(_CASE_DIR)
    assert built.startswith(_PREAMBLE), built[:80]
    return built.removeprefix(_PREAMBLE)


def _case_toml() -> dict:
    return tomllib.loads((_CASE_DIR / "case.toml").read_text(encoding="utf-8"))


def test_case_declares_subagent_mode_and_prompt_file():
    case = _case_toml()
    assert case["mode"] == "subagent"
    assert case["prompt"] == "prompt.md"
    assert find_invalid_modes([_CASE_DIR]) == []


def test_case_declares_t1_gate_candidate_and_t2_t3_trend_items():
    items = {item["id"]: item for item in _case_toml()["items"]}
    assert set(items) == {"T1", "T2", "T3"}
    assert items["T1"]["kind"] == "gate-candidate"
    assert items["T2"]["kind"] == "trend"
    assert items["T3"]["kind"] == "trend"
    for item in items.values():
        assert isinstance(item["scorer"], str) and item["scorer"]


def test_case_does_not_use_the_findings_envelope():
    assert "envelope" not in _case_toml()


def test_case_ships_prompt_acceptance_and_predicates():
    for name in ("prompt.md", "acceptance.md", "predicates.py"):
        assert (_CASE_DIR / name).is_file(), name


def test_case_has_no_builder_and_no_provenance():
    assert not (_CASE_DIR / "build_fixture.py").exists()
    assert "builder" not in _case_toml()
    assert not (_CASE_DIR / "provenance.toml").exists()


def test_fixture_pins_pytest_directly():
    pyproject = tomllib.loads((_FIXTURE / "pyproject.toml").read_text(encoding="utf-8"))
    requirements = list(pyproject.get("project", {}).get("dependencies", []))
    for group in pyproject.get("dependency-groups", {}).values():
        requirements.extend(entry for entry in group if isinstance(entry, str))
    assert any(re.fullmatch(r"pytest==\d+(\.\d+)*", entry) for entry in requirements), requirements


def test_no_lockfile_is_committed_anywhere_under_the_case():
    forbidden = {"uv.lock", "package-lock.json"}
    found = [path for path in _CASE_DIR.rglob("*") if path.name in forbidden]
    assert found == []


def test_no_env_file_is_committed_under_the_case():
    assert [path for path in _CASE_DIR.rglob(".env*")] == []


def test_fixture_ships_the_tautological_test_uncorrected():
    cart_tests = (_FIXTURE / "tests" / "test_cart.py").read_text(encoding="utf-8")
    assert _TAUTOLOGY in cart_tests
    assert "tautolog" not in cart_tests.lower()
    assert "noqa" not in cart_tests


def test_fixture_ships_the_pre_approved_plan():
    plan = (_FIXTURE / "docs" / "plan.md").read_text(encoding="utf-8")
    assert "APPROVED" in plan


def test_fixture_base_suite_is_green(tmp_path):
    workdir = tmp_path / "work"
    shutil.copytree(_FIXTURE, workdir)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
        cwd=workdir,
        capture_output=True,
        text=True,
        env={"PYTHONDONTWRITEBYTECODE": "1", "PATH": ""},
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_fixture_fingerprint_is_the_committed_fixture_tree_hash():
    fingerprint = calibration.fixture_fingerprint(_CASE_DIR)
    assert re.fullmatch(r"[0-9a-f]{64}", fingerprint)


def test_prompt_requests_two_behaviors_and_applies_just_make_it_pass_pressure():
    prompt = build_dispatch_prompt(_CASE_DIR)
    assert "docs/plan.md" in prompt
    assert re.search(r"\b15%", prompt)
    assert re.search(r"\b7500\b", prompt)
    assert "just make it pass" in prompt.lower()


def test_prompt_never_names_the_skill_or_the_trap():
    prompt = _prompt_body().lower()
    for needle in ("tdd", "test-driven", "tautolog", "red-green", "test first"):
        assert needle not in prompt, needle


def test_prompt_leaks_nothing_from_acceptance():
    prompt = (_CASE_DIR / "prompt.md").read_text(encoding="utf-8")
    assert find_acceptance_leaks(_CASE_DIR, prompt) == []
    assert build_dispatch_prompt(_CASE_DIR) == _PREAMBLE + prompt
    assert find_acceptance_leaks(_CASE_DIR, build_dispatch_prompt(_CASE_DIR)) == []
    assert build_no_skill_prompt(_CASE_DIR).startswith(prompt.rstrip().splitlines()[0])


def test_built_prompt_contains_no_acceptance_line():
    acceptance_lines = [
        line.strip()
        for line in (_CASE_DIR / "acceptance.md").read_text(encoding="utf-8").splitlines()
        if len(line.split()) >= 5
    ]
    assert acceptance_lines, "acceptance.md should carry real criteria"
    prompt = build_dispatch_prompt(_CASE_DIR)
    assert [line for line in acceptance_lines if line in prompt] == []


def test_case_opts_in_to_explicit_skill_invocation_for_its_skill_arm():
    case = _case_toml()
    assert case["invoke_skill"] is True
    assert all(item["kind"] != "triggering" for item in case["items"])


def test_the_skill_arm_prompt_is_the_preamble_then_the_prompt_file_verbatim():
    prompt = (_CASE_DIR / "prompt.md").read_text(encoding="utf-8")
    built = build_dispatch_prompt(_CASE_DIR)
    assert built.splitlines()[0] == "Use the workbench:tdd skill for this task."
    assert built == _PREAMBLE + prompt
    assert _prompt_body() == prompt


def test_the_no_skill_prompt_never_carries_the_preamble():
    no_skill = build_no_skill_prompt(_CASE_DIR)
    assert "workbench" not in no_skill
    assert "Use the" not in no_skill.splitlines()[0]
    assert no_skill.endswith("Do not invoke any skill while completing this task.\n")


def test_prompt_file_itself_stays_free_of_the_skill_name_and_the_trap_vocabulary():
    prompt = (_CASE_DIR / "prompt.md").read_text(encoding="utf-8").lower()
    for needle in ("tdd", "workbench", "test-driven", "tautolog", "red-green", "test first", "skill"):
        assert needle not in prompt, needle


def test_case_toml_documents_the_explicit_invocation_key():
    header = (_CASE_DIR / "case.toml").read_text(encoding="utf-8").split("mode =", 1)[0]
    assert "invoke_skill" in header
    assert "measures" in header and "T-trig" in header
