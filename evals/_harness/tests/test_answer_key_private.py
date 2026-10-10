"""Tests for evals._harness.guards.answer_key_private (#1130)."""

from __future__ import annotations

from pathlib import Path

import pytest

from evals._harness.guards import GuardContext
from evals._harness.guards.answer_key_private import check, looks_like_answer_key

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _case(repo: Path, files: list[str], *, private: list[str] | None = None, extra_toml: str = "",
          local_builder: bool = False) -> Path:
    case = repo / "evals" / "skill" / "X"
    for rel in files:
        path = case / "fixture" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")
    case.mkdir(parents=True, exist_ok=True)
    lines = ['mode = "inline"', 'prompt = "prompt.md"']
    if private is not None:
        lines.append("fixture_private = [" + ", ".join(f'"{p}"' for p in private) + "]")
    (case / "case.toml").write_text("\n".join(lines) + "\n" + extra_toml, encoding="utf-8")
    if local_builder:
        (case / "build_fixture.py").write_text("", encoding="utf-8")
    return case


def _run(repo: Path):
    return check(GuardContext(base="unused", repo_root=repo))


@pytest.mark.parametrize(
    "name",
    ["defects.json", "Defects.JSON", "answers.json", "answer_key.txt", "ground_truth.json", "ground_truth_v2.md",
     "expected.json", "expected_output.txt", "key.json", "scoring_key.json", "KEY-v2.JSON"],
)
def test_the_name_heuristic_flags_answer_key_names(name):
    assert looks_like_answer_key(name)


@pytest.mark.parametrize("name", ["diff.patch", "spec.md", "pricing.py", "README.md", "pyproject.toml", "key.md", "plan.md"])
def test_the_name_heuristic_leaves_ordinary_fixture_names_alone(name):
    assert not looks_like_answer_key(name)


def test_fails_an_unlisted_answer_key_in_a_static_fixture_naming_the_file(tmp_path):
    _case(tmp_path, ["diff.patch", "defects.json"])
    results = _run(tmp_path)
    assert len(results) == 1 and results[0].level == "fail" and results[0].guard == "answer_key_private"
    assert "skill/X" in results[0].message and "defects.json" in results[0].message


def test_fails_an_answer_key_at_depth(tmp_path):
    _case(tmp_path, ["diff.patch", "gt/expected_output.txt"])
    assert "gt/expected_output.txt" in _run(tmp_path)[0].message


def test_passes_when_the_key_is_listed_in_fixture_private(tmp_path):
    _case(tmp_path, ["diff.patch", "defects.json"], private=["defects.json"])
    assert _run(tmp_path) == []


def test_passes_when_a_listed_directory_covers_the_key(tmp_path):
    _case(tmp_path, ["diff.patch", "gt/defects.json"], private=["gt"])
    assert _run(tmp_path) == []


def test_listing_a_different_file_does_not_cover_the_key(tmp_path):
    _case(tmp_path, ["diff.patch", "defects.json", "notes.md"], private=["notes.md"])
    assert len(_run(tmp_path)) == 1


def test_a_case_with_a_builder_key_is_not_checked(tmp_path):
    _case(tmp_path, ["defects.json"], extra_toml='builder = "x.py"\n')
    assert _run(tmp_path) == []


def test_a_case_with_a_local_builder_is_not_checked(tmp_path):
    _case(tmp_path, ["defects.json"], local_builder=True)
    assert _run(tmp_path) == []


def test_a_case_with_no_fixture_dir_is_skipped(tmp_path):
    case = _case(tmp_path, [])
    assert not (case / "fixture").exists()
    assert _run(tmp_path) == []


def test_a_bad_declaration_fails_rather_than_passing_silently(tmp_path):
    _case(tmp_path, ["diff.patch", "defects.json"], private=["gone.json"])
    results = _run(tmp_path)
    assert len(results) == 1 and results[0].level == "fail" and "gone.json" in results[0].message


def test_underscore_and_hidden_skill_dirs_are_not_walked(tmp_path):
    case = tmp_path / "evals" / "_harness" / "X"
    (case / "fixture").mkdir(parents=True)
    (case / "fixture" / "defects.json").write_text("x", encoding="utf-8")
    (case / "case.toml").write_text('mode = "inline"\nprompt = "p.md"\n', encoding="utf-8")
    assert _run(tmp_path) == []


def test_every_committed_case_passes_the_guard_today():
    assert _run(_REPO_ROOT) == []


def test_a2_declares_its_answer_key_private():
    from evals._harness.fixture_copy import private_fixture_paths

    assert private_fixture_paths(_REPO_ROOT / "evals" / "adversarial-review" / "A2") == ("defects.json",)
