"""Tests for evals._harness.fixture_copy: the conductor's private-aware fixture copy (#1130)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from evals._harness.fixture_copy import (
    FixtureCopyError,
    copy_fixture,
    find_private_leaks,
    private_fixture_paths,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _case(tmp_path: Path, files: dict[str, str], private: object = None, *, toml_extra: str = "") -> Path:
    case = tmp_path / "evals" / "skill" / "X"
    for rel, text in files.items():
        path = case / "fixture" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    lines = ['mode = "inline"', 'prompt = "prompt.md"']
    if private is not None:
        lines.append(f"fixture_private = {private!r}".replace("'", '"'))
    case.mkdir(parents=True, exist_ok=True)
    (case / "case.toml").write_text("\n".join(lines) + "\n" + toml_extra, encoding="utf-8")
    return case


_FILES = {"diff.patch": "d", "spec.md": "s", "defects.json": "KEY", "sub/notes.md": "n"}


# --- private_fixture_paths ------------------------------------------------------------


def test_no_declaration_means_nothing_is_private(tmp_path):
    assert private_fixture_paths(_case(tmp_path, _FILES)) == ()


def test_the_declared_entries_come_back_as_posix_paths(tmp_path):
    case = _case(tmp_path, _FILES, ["defects.json", "sub"])
    assert private_fixture_paths(case) == ("defects.json", "sub")


@pytest.mark.parametrize(
    "bad",
    ["defects.json", [""], [3], ["/etc/passwd"], ["../x"], ["sub/../../x"], ["."], ["missing.json"]],
    ids=["string-not-list", "empty-entry", "non-string", "absolute", "dotdot", "nested-dotdot", "fixture-root", "stale"],
)
def test_a_malformed_or_stale_declaration_fails_closed_naming_case_and_entry(tmp_path, bad):
    case = _case(tmp_path, _FILES, bad)
    with pytest.raises(FixtureCopyError) as err:
        private_fixture_paths(case)
    assert "X" in str(err.value)
    if isinstance(bad, list) and bad and isinstance(bad[0], str) and bad[0]:
        assert bad[0] in str(err.value)


def test_an_entry_that_escapes_fixture_through_a_symlink_is_refused(tmp_path):
    case = _case(tmp_path, _FILES, ["link"])
    outside = tmp_path / "outside.txt"
    outside.write_text("x", encoding="utf-8")
    (case / "fixture" / "link").symlink_to(outside)
    with pytest.raises(FixtureCopyError, match="link"):
        private_fixture_paths(case)


# --- copy_fixture ---------------------------------------------------------------------


def test_copy_omits_a_private_file_and_copies_the_rest_byte_for_byte(tmp_path):
    case = _case(tmp_path, _FILES, ["defects.json"])
    dest = tmp_path / "dest"
    copied = copy_fixture(case, dest)
    assert copied == ["diff.patch", "spec.md", "sub/notes.md"]
    assert not (dest / "defects.json").exists()
    for rel in copied:
        assert (dest / rel).read_bytes() == (case / "fixture" / rel).read_bytes()


def test_copy_omits_a_whole_private_directory(tmp_path):
    case = _case(tmp_path, _FILES, ["sub"])
    dest = tmp_path / "dest"
    assert copy_fixture(case, dest) == ["defects.json", "diff.patch", "spec.md"]
    assert not (dest / "sub").exists()


def test_a_case_without_a_declaration_is_copied_whole(tmp_path):
    case = _case(tmp_path, _FILES)
    assert copy_fixture(case, tmp_path / "dest") == sorted(_FILES)


def test_copy_refuses_an_existing_dest(tmp_path):
    case = _case(tmp_path, _FILES, ["defects.json"])
    dest = tmp_path / "dest"
    dest.mkdir()
    with pytest.raises(FixtureCopyError, match="already exists"):
        copy_fixture(case, dest)
    assert list(dest.iterdir()) == []


def test_copy_refuses_a_dangling_symlink_as_dest(tmp_path):
    case = _case(tmp_path, _FILES, ["defects.json"])
    dest = tmp_path / "dest"
    dest.symlink_to(tmp_path / "nowhere")
    with pytest.raises(FixtureCopyError, match="already exists"):
        copy_fixture(case, dest)


def test_copy_raises_when_the_case_has_no_fixture_dir(tmp_path):
    case = _case(tmp_path, {}, None)
    shutil.rmtree(case / "fixture", ignore_errors=True)
    with pytest.raises(FixtureCopyError, match="fixture"):
        copy_fixture(case, tmp_path / "dest")


def test_copy_refuses_a_symlink_inside_the_fixture_and_leaves_no_dest(tmp_path):
    case = _case(tmp_path, _FILES, ["defects.json"])
    (case / "fixture" / "pointer").symlink_to(case / "fixture" / "defects.json")
    dest = tmp_path / "dest"
    with pytest.raises(FixtureCopyError, match="pointer"):
        copy_fixture(case, dest)
    assert not os.path.lexists(dest)


def test_a_stale_declaration_stops_the_copy_before_anything_is_written(tmp_path):
    case = _case(tmp_path, _FILES, ["gone.json"])
    dest = tmp_path / "dest"
    with pytest.raises(FixtureCopyError, match="gone.json"):
        copy_fixture(case, dest)
    assert not os.path.lexists(dest)


# --- find_private_leaks ---------------------------------------------------------------


def test_a_clean_copy_has_no_leaks(tmp_path):
    case = _case(tmp_path, _FILES, ["defects.json"])
    dest = tmp_path / "dest"
    copy_fixture(case, dest)
    assert find_private_leaks(case, dest) == []


def test_a_whole_tree_copytree_is_flagged_positive_control(tmp_path):
    case = _case(tmp_path, _FILES, ["defects.json"])
    dest = tmp_path / "dest"
    shutil.copytree(case / "fixture", dest)
    assert find_private_leaks(case, dest) == ["defects.json"]


def test_a_private_file_found_by_basename_at_depth_is_a_leak(tmp_path):
    case = _case(tmp_path, _FILES, ["defects.json"])
    dest = tmp_path / "dest"
    copy_fixture(case, dest)
    (dest / "a" / "b").mkdir(parents=True)
    (dest / "a" / "b" / "defects.json").write_text("renamed copy", encoding="utf-8")
    assert find_private_leaks(case, dest) == ["a/b/defects.json"]


def test_a_nested_private_path_matches_by_relative_path_at_depth(tmp_path):
    case = _case(tmp_path, {"keep.md": "k", "gt/answers/key.json": "K"}, ["gt/answers"])
    dest = tmp_path / "dest"
    copy_fixture(case, dest)
    (dest / "wrapper" / "gt" / "answers").mkdir(parents=True)
    (dest / "wrapper" / "gt" / "answers" / "other.txt").write_text("x", encoding="utf-8")
    assert "wrapper/gt/answers/other.txt" in find_private_leaks(case, dest)


def test_acceptance_md_and_ab_raws_in_dest_are_leaks_even_without_a_declaration(tmp_path):
    case = _case(tmp_path, _FILES)
    dest = tmp_path / "dest"
    copy_fixture(case, dest)
    (dest / "acceptance.md").write_text("private", encoding="utf-8")
    (dest / "ab_raws" / "a").mkdir(parents=True)
    (dest / "ab_raws" / "a" / "r1.txt").write_text("raw", encoding="utf-8")
    assert find_private_leaks(case, dest) == ["ab_raws/a/r1.txt", "acceptance.md"]


def test_a_missing_dest_is_an_error_not_a_pass(tmp_path):
    case = _case(tmp_path, _FILES, ["defects.json"])
    with pytest.raises(FixtureCopyError, match="dest"):
        find_private_leaks(case, tmp_path / "never-made")


# --- the command line the SKILL.md tells the conductor to run ---------------------------


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-B", "-m", "evals._harness.fixture_copy", *args],
        cwd=_REPO_ROOT, capture_output=True, text=True, check=False,
    )


def test_cli_copies_and_prints_the_copied_paths(tmp_path):
    case = _case(tmp_path, _FILES, ["defects.json"])
    dest = tmp_path / "dest"
    result = _run(str(case), str(dest))
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["diff.patch", "spec.md", "sub/notes.md"]
    assert not (dest / "defects.json").exists()


def test_cli_check_exits_zero_on_a_clean_dest_and_nonzero_naming_each_leak(tmp_path):
    case = _case(tmp_path, _FILES, ["defects.json"])
    clean = tmp_path / "clean"
    copy_fixture(case, clean)
    assert _run("--check", str(case), str(clean)).returncode == 0

    leaky = tmp_path / "leaky"
    shutil.copytree(case / "fixture", leaky)
    (leaky / "acceptance.md").write_text("p", encoding="utf-8")
    result = _run("--check", str(case), str(leaky))
    assert result.returncode != 0
    assert "defects.json" in result.stdout + result.stderr
    assert "acceptance.md" in result.stdout + result.stderr


def test_cli_exits_nonzero_with_the_reason_when_the_dest_exists(tmp_path):
    case = _case(tmp_path, _FILES, ["defects.json"])
    dest = tmp_path / "dest"
    dest.mkdir()
    result = _run(str(case), str(dest))
    assert result.returncode != 0
    assert "already exists" in result.stderr
