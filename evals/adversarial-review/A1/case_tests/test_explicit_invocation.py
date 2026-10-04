"""A1's skill arm is told to use the skill: ``invoke_skill = true`` and what it changes.

The ``coverage_bound`` gate candidate needs the report slot the ``adversarial-review``
skill adds, and at the first calibration the skill arm never called the skill. So
A1 opts in to explicit invocation: the skill arm's dispatched prompt is the harness's
one fixed line, a blank line, then ``prompt.md`` verbatim. ``prompt.md`` itself stays
name-free, and the no-skill arm is built from the prompt file alone and never carries
the line. The key also moves ``compute_input_hash``.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from evals._harness.calibration import compute_input_hash
from evals._harness.dispatch import (
    INVOKE_SKILL_PREAMBLE,
    _case_toml,
    build_dispatch_prompt,
    build_no_skill_prompt,
    find_acceptance_leaks,
)

_SKILL = "adversarial-review"
_BUILDER = "plugins/workbench/skills/adversarial-review/scripts/build_fixture.py"
_TESTS_MD = "plugins/workbench/skills/adversarial-review/tests.md"
_NO_SKILL_INSTRUCTION = "Do not invoke any skill while completing this task."
_KEY_LINE = "invoke_skill = true\n"


def _preamble() -> str:
    return INVOKE_SKILL_PREAMBLE.format(skill=_SKILL)


def _prompt_md(case_dir: Path) -> str:
    return (case_dir / "prompt.md").read_text(encoding="utf-8")


def _scenario_1_cell(repo_root: Path) -> str:
    text = (repo_root / _TESTS_MD).read_text(encoding="utf-8")
    section = text.split("## Kept scenarios", 1)[1]
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if line.startswith("|") and cells[0] == "1":
            return cells[1]
    raise AssertionError("no scenario ID 1 row in the Kept scenarios table")


# ---------------------------------------------------------------------------
# the key
# ---------------------------------------------------------------------------


def test_case_toml_sets_invoke_skill_true_as_a_top_level_key_before_the_first_item(case_dir, case_toml):
    assert case_toml["invoke_skill"] is True
    text = (case_dir / "case.toml").read_text(encoding="utf-8")
    first_items_header = text.index("[[items]]")
    key_at = re.search(r"^invoke_skill = true$", text, re.MULTILINE)
    assert key_at is not None and key_at.start() < first_items_header
    assert all("invoke_skill" not in item for item in case_toml["items"])


def test_the_harnesss_own_loader_reads_the_key_as_true(case_dir):
    assert _case_toml(case_dir)["invoke_skill"] is True


def test_a1_declares_no_triggering_item_so_the_key_is_allowed(case_dir):
    # The harness refuses the key on a case with a triggering item; A3 measures firing, not A1.
    assert all(item["kind"] != "triggering" for item in _case_toml(case_dir)["items"])


def test_case_toml_header_documents_the_key_and_what_the_gate_now_measures(case_dir):
    header = (case_dir / "case.toml").read_text(encoding="utf-8").split("mode =", 1)[0]
    assert "invoke_skill" in header
    assert "A3" in header and "measures" in header


# ---------------------------------------------------------------------------
# the skill arm's prompt
# ---------------------------------------------------------------------------


def test_the_skill_arm_prompt_contains_the_preamble_exactly_once_and_as_the_first_line(case_dir):
    built = build_dispatch_prompt(case_dir)
    assert built.count(_preamble()) == 1
    assert built.splitlines()[0] == _preamble()
    assert built.startswith(_preamble() + "\n\n")
    assert built.removeprefix(_preamble() + "\n\n") == _prompt_md(case_dir)


def test_the_preamble_sentence_passes_the_acceptance_leak_check(case_dir):
    # build_dispatch_prompt runs the leak check over the preamble and the prompt; it must not raise.
    built = build_dispatch_prompt(case_dir)
    assert find_acceptance_leaks(case_dir, built) == []
    assert find_acceptance_leaks(case_dir, _preamble()) == []


# ---------------------------------------------------------------------------
# prompt.md stays the scenario-1 cell and name-free
# ---------------------------------------------------------------------------


def test_prompt_md_is_the_scenario_1_cell_byte_for_byte(case_dir, repo_root):
    assert (case_dir / "prompt.md").read_bytes() == (_scenario_1_cell(repo_root) + "\n").encode("utf-8")


def test_prompt_md_names_no_skill_and_carries_no_preamble_sentence(case_dir):
    prompt = _prompt_md(case_dir)
    lowered = prompt.lower()
    for needle in ("adversarial-review", "adversarial review", "workbench", "skill", "for this task"):
        assert needle not in lowered, needle
    assert _preamble() not in prompt
    assert "Use the" not in prompt


# ---------------------------------------------------------------------------
# the no-skill arm
# ---------------------------------------------------------------------------


def test_the_no_skill_prompt_never_carries_the_preamble_and_is_built_from_the_prompt_file_alone(case_dir):
    no_skill = build_no_skill_prompt(case_dir)
    assert no_skill == f"{_prompt_md(case_dir).strip()}\n\n{_NO_SKILL_INSTRUCTION}\n"
    assert _preamble() not in no_skill
    assert "workbench" not in no_skill
    assert "for this task" not in no_skill
    assert no_skill.splitlines()[0] == _prompt_md(case_dir).strip()


# ---------------------------------------------------------------------------
# compute_input_hash
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


@pytest.fixture
def hashable_copy(case_dir: Path, repo_root: Path, tmp_path: Path) -> Path:
    """A copy of the case directory and its builder in a throwaway git repository."""
    repo = tmp_path / "repo"
    copy = repo / "evals" / _SKILL / case_dir.name
    shutil.copytree(case_dir, copy, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "case_tests"))
    builder = repo / _BUILDER
    builder.parent.mkdir(parents=True)
    shutil.copy2(repo_root / _BUILDER, builder)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "case")
    return copy


def test_toggling_the_key_changes_the_input_hash(hashable_copy):
    on = compute_input_hash(hashable_copy)
    toml_path = hashable_copy / "case.toml"
    text = toml_path.read_text(encoding="utf-8")
    assert _KEY_LINE in text
    toml_path.write_text(text.replace(_KEY_LINE, ""), encoding="utf-8")
    off = compute_input_hash(hashable_copy)
    assert on != off
    toml_path.write_text(text.replace(_KEY_LINE, "invoke_skill = false\n"), encoding="utf-8")
    assert compute_input_hash(hashable_copy) == off
