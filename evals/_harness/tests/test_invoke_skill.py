"""Tests for the case-level ``invoke_skill`` opt-in of the dispatch harness.

A case may set ``invoke_skill = true`` in ``case.toml``. ``build_dispatch_prompt``
then begins the skill arm's prompt with one fixed line naming the skill, a blank
line, and the case prompt verbatim. Every other prompt the harness builds stays
exactly what it was: the key defaults off, the no-skill arm never carries the
line, a triggering item refuses the key, and ``compute_input_hash`` moves when
the key is toggled and only then.

Synthetic cases are built under ``tmp_path``. The committed-case scan at the
bottom pins every real case directory.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import tomllib
from pathlib import Path

import pytest

from evals._harness import dispatch
from evals._harness.calibration import compute_input_hash
from evals._harness.deps import tree_hash
from evals._harness.dispatch import (
    AcceptanceLeakError,
    CaseContractError,
    build_dispatch_prompt,
    build_no_skill_prompt,
    discover_case_dirs,
    score_attempt,
)

_EVALS_ROOT = Path(__file__).resolve().parents[2]
_NO_SKILL_INSTRUCTION = "Do not invoke any skill while completing this task."
_PROMPT = "Add the feature.\n\nKeep it small.\n"
# The committed cases allowed to carry the key. Anything else must dispatch its prompt untouched.
_OPT_IN_CASES = {"tdd/T"}


def _write_case(
    root: Path,
    *,
    skill: str = "skill-x",
    case: str = "case-a",
    prompt: str = _PROMPT,
    key_line: str = "",
    kind: str = "gate-candidate",
    acceptance: str = "private acceptance notes\n",
) -> Path:
    case_dir = root / skill / case
    case_dir.mkdir(parents=True)
    (case_dir / "prompt.md").write_text(prompt, encoding="utf-8")
    (case_dir / "acceptance.md").write_text(acceptance, encoding="utf-8")
    (case_dir / "case.toml").write_text(
        'mode = "subagent"\n'
        'prompt = "prompt.md"\n'
        f"{key_line}"
        "\n"
        "[[items]]\n"
        'id = "item-a"\n'
        f'kind = "{kind}"\n'
        'scorer = "never_called"\n',
        encoding="utf-8",
    )
    return case_dir


# ---------------------------------------------------------------------------
# the dispatched prompt
# ---------------------------------------------------------------------------


def test_the_preamble_is_the_documented_line():
    assert dispatch.INVOKE_SKILL_PREAMBLE == "Use the workbench:{skill} skill for this task."


def test_the_key_defaults_to_off_so_the_prompt_is_the_file_verbatim(tmp_path):
    case_dir = _write_case(tmp_path)
    assert build_dispatch_prompt(case_dir) == _PROMPT


def test_an_explicit_false_is_the_same_as_an_absent_key(tmp_path):
    case_dir = _write_case(tmp_path, key_line="invoke_skill = false\n")
    assert build_dispatch_prompt(case_dir) == _PROMPT


def test_the_key_on_adds_exactly_one_line_a_blank_line_and_the_prompt_verbatim(tmp_path):
    case_dir = _write_case(tmp_path, key_line="invoke_skill = true\n")
    assert build_dispatch_prompt(case_dir) == "Use the workbench:skill-x skill for this task.\n\n" + _PROMPT


def test_the_prompt_after_the_preamble_keeps_its_own_whitespace(tmp_path):
    prompt = "\n  Indented first line.\n\n\nLast line, no newline"
    case_dir = _write_case(tmp_path, prompt=prompt, key_line="invoke_skill = true\n")
    built = build_dispatch_prompt(case_dir)
    assert built.startswith("Use the workbench:skill-x skill for this task.\n\n")
    assert built.removeprefix("Use the workbench:skill-x skill for this task.\n\n") == prompt


def test_the_skill_is_named_after_the_case_directorys_parent(tmp_path):
    case_dir = _write_case(tmp_path, skill="another-skill", key_line="invoke_skill = true\n")
    assert build_dispatch_prompt(case_dir).splitlines()[0] == "Use the workbench:another-skill skill for this task."


def test_the_preamble_is_checked_for_acceptance_leaks_with_the_prompt(tmp_path):
    case_dir = _write_case(
        tmp_path,
        key_line="invoke_skill = true\n",
        acceptance="Use the workbench:skill-x skill for this task.\n",
    )
    with pytest.raises(AcceptanceLeakError):
        build_dispatch_prompt(case_dir)


# ---------------------------------------------------------------------------
# the no-skill arm
# ---------------------------------------------------------------------------


def test_the_no_skill_prompt_never_carries_the_preamble(tmp_path):
    on = _write_case(tmp_path / "on", key_line="invoke_skill = true\n")
    off = _write_case(tmp_path / "off")
    no_skill = build_no_skill_prompt(on)
    assert no_skill == build_no_skill_prompt(off)
    assert no_skill == f"{_PROMPT.strip()}\n\n{_NO_SKILL_INSTRUCTION}\n"
    assert "workbench" not in no_skill
    assert "for this task" not in no_skill


def test_the_no_skill_prompt_is_built_from_the_prompt_file_not_the_skill_arm_prompt(tmp_path, monkeypatch):
    case_dir = _write_case(tmp_path, key_line="invoke_skill = true\n")
    monkeypatch.setattr(dispatch, "build_dispatch_prompt", lambda _case_dir: "SKILL ARM PROMPT")
    assert "SKILL ARM PROMPT" not in build_no_skill_prompt(case_dir)


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("key_line", ["invoke_skill = true\n", "invoke_skill = false\n"])
def test_the_key_is_refused_on_a_case_with_a_triggering_item(tmp_path, key_line):
    case_dir = _write_case(tmp_path, key_line=key_line, kind="triggering")
    for entry in (build_dispatch_prompt, build_no_skill_prompt):
        with pytest.raises(CaseContractError, match="invoke_skill.*triggering"):
            entry(case_dir)
    with pytest.raises(CaseContractError, match="invoke_skill.*triggering"):
        score_attempt(case_dir, [], None, set())


def test_a_triggering_case_without_the_key_is_unaffected(tmp_path):
    case_dir = _write_case(tmp_path, kind="triggering")
    assert build_dispatch_prompt(case_dir) == _PROMPT


@pytest.mark.parametrize("key_line", ['invoke_skill = "yes"\n', "invoke_skill = 1\n", "invoke_skill = []\n"])
def test_the_key_must_be_a_boolean(tmp_path, key_line):
    case_dir = _write_case(tmp_path, key_line=key_line)
    with pytest.raises(CaseContractError, match="invoke_skill.*true or false"):
        build_dispatch_prompt(case_dir)


# ---------------------------------------------------------------------------
# compute_input_hash
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True)


def _hashable_case(tmp_path: Path, key_line: str) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    case_dir = _write_case(repo / "evals", key_line=key_line)
    (case_dir / "fixture").mkdir()
    (case_dir / "fixture" / "input.txt").write_text("fixture\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "case")
    return repo, case_dir


def test_the_input_hash_changes_when_the_key_is_turned_on(tmp_path):
    _repo, off_case = _hashable_case(tmp_path / "off", "")
    _repo, on_case = _hashable_case(tmp_path / "on", "invoke_skill = true\n")
    assert compute_input_hash(on_case) != compute_input_hash(off_case)


def test_the_input_hash_changes_when_the_same_case_toggles_the_key(tmp_path):
    _repo, case_dir = _hashable_case(tmp_path, "")
    before = compute_input_hash(case_dir)
    text = (case_dir / "case.toml").read_text(encoding="utf-8")
    (case_dir / "case.toml").write_text("invoke_skill = true\n" + text, encoding="utf-8")
    assert compute_input_hash(case_dir) != before


def test_a_false_key_hashes_like_an_absent_key(tmp_path):
    _repo, absent = _hashable_case(tmp_path / "absent", "")
    _repo, false = _hashable_case(tmp_path / "false", "invoke_skill = false\n")
    assert compute_input_hash(false) == compute_input_hash(absent)


def test_a_case_without_the_key_keeps_the_hash_it_had_before_the_key_existed(tmp_path):
    repo, case_dir = _hashable_case(tmp_path, "")
    # The four-part payload documented before the key existed; a recorded calibration stays current.
    legacy_payload = json.dumps(
        [
            _PROMPT,
            _fixture_component(repo, case_dir),
            [{"id": "item-a", "kind": "gate-candidate", "scorer": "never_called", "params": {}}],
            None,
        ],
        sort_keys=True,
        separators=(",", ":"),
    )
    assert compute_input_hash(case_dir) == hashlib.sha256(legacy_payload.encode("utf-8")).hexdigest()


def _fixture_component(repo: Path, case_dir: Path) -> str:
    return tree_hash([case_dir.joinpath("fixture").relative_to(repo).as_posix()], repo=repo)


# ---------------------------------------------------------------------------
# every committed case
# ---------------------------------------------------------------------------


def _committed_cases() -> list[Path]:
    return discover_case_dirs(_EVALS_ROOT)


def _label(case_dir: Path) -> str:
    return f"{case_dir.parent.name}/{case_dir.name}"


def test_every_committed_case_dispatches_its_prompt_untouched_unless_it_opted_in():
    assert _committed_cases(), "no committed cases found"
    for case_dir in _committed_cases():
        case_toml = tomllib.loads((case_dir / "case.toml").read_text(encoding="utf-8"))
        prompt = (case_dir / case_toml["prompt"]).read_text(encoding="utf-8")
        if "invoke_skill" in case_toml:
            assert _label(case_dir) in _OPT_IN_CASES, _label(case_dir)
            continue
        assert build_dispatch_prompt(case_dir) == prompt, _label(case_dir)


def test_only_the_listed_cases_opt_in_and_they_name_their_skill_first():
    for case_dir in _committed_cases():
        case_toml = tomllib.loads((case_dir / "case.toml").read_text(encoding="utf-8"))
        if "invoke_skill" not in case_toml:
            continue
        label = _label(case_dir)
        assert label in _OPT_IN_CASES, label
        assert case_toml["invoke_skill"] is True, label
        prompt = (case_dir / case_toml["prompt"]).read_text(encoding="utf-8")
        expected = f"Use the workbench:{case_dir.parent.name} skill for this task.\n\n{prompt}"
        assert build_dispatch_prompt(case_dir) == expected, label
        assert all(item["kind"] != "triggering" for item in case_toml.get("items", [])), label


def test_a_committed_case_that_opts_in_still_builds_a_clean_no_skill_prompt():
    for case_dir in _committed_cases():
        case_toml = tomllib.loads((case_dir / "case.toml").read_text(encoding="utf-8"))
        if "invoke_skill" not in case_toml:
            continue
        no_skill = build_no_skill_prompt(case_dir)
        assert "Use the workbench:" not in no_skill, _label(case_dir)
        assert no_skill.endswith(f"{_NO_SKILL_INSTRUCTION}\n"), _label(case_dir)
