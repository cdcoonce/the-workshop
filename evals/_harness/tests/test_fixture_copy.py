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
    ["defects.json", [""], [3], ["/etc/passwd"], ["../x"], ["sub/../../x"], ["."], ["missing.json"],
     ["../case.toml"], ["sub/../defects.json"]],
    ids=["string-not-list", "empty-entry", "non-string", "absolute", "dotdot", "nested-dotdot", "fixture-root", "stale",
         "dotdot-onto-a-real-file-outside", "dotdot-that-lands-back-inside"],
)
def test_a_malformed_or_stale_declaration_fails_closed_naming_case_and_entry(tmp_path, bad):
    case = _case(tmp_path, _FILES, bad)
    with pytest.raises(FixtureCopyError) as err:
        private_fixture_paths(case)
    assert "X" in str(err.value)
    if isinstance(bad, list) and bad and isinstance(bad[0], str) and bad[0]:
        assert bad[0] in str(err.value)


def test_an_absolute_entry_that_points_inside_fixture_is_still_refused(tmp_path):
    case = _case(tmp_path, _FILES)
    inside = (case / "fixture" / "defects.json").resolve()
    (case / "case.toml").write_text(
        f'mode = "inline"\nprompt = "prompt.md"\nfixture_private = ["{inside.as_posix()}"]\n', encoding="utf-8"
    )
    with pytest.raises(FixtureCopyError, match="relative"):
        private_fixture_paths(case)


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


def test_a_private_file_is_found_by_basename_even_under_a_different_directory(tmp_path):
    case = _case(tmp_path, {"keep.md": "k", "gt/answers/key.json": "K"}, ["gt/answers/key.json"])
    dest = tmp_path / "dest"
    copy_fixture(case, dest)
    (dest / "elsewhere").mkdir()
    (dest / "elsewhere" / "key.json").write_text("moved", encoding="utf-8")
    assert find_private_leaks(case, dest) == ["elsewhere/key.json"]


def test_the_files_of_a_private_directory_are_found_by_basename_too(tmp_path):
    case = _case(tmp_path, {"keep.md": "k", "gt/a.json": "A"}, ["gt"])
    dest = tmp_path / "dest"
    copy_fixture(case, dest)
    (dest / "a.json").write_text("moved", encoding="utf-8")
    assert find_private_leaks(case, dest) == ["a.json"]


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


# ======================================================================================
# Review fixes (S1-S4) and the gaps the reviewer's mutations survived
# ======================================================================================

import unicodedata  # noqa: E402

from evals._harness.fixture_copy import fixture_dirty_paths, has_builder  # noqa: E402


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false", "-C", str(repo), *args],
        capture_output=True, text=True, check=True,
    )
    return result.stdout


def _repo_case(tmp_path: Path, files: dict[str, str], private: object = None) -> Path:
    """A case inside a real, committed git work tree."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    case = _case(repo, files, private)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return case


# --- gap tests: backslash, empty private dir, exit codes -----------------------------


def test_a_backslash_entry_is_refused_even_when_such_a_file_exists(tmp_path):
    case = _case(tmp_path, {**_FILES, "sub\\x": "odd"}, ["sub\\x"])
    with pytest.raises(FixtureCopyError, match="relative POSIX"):
        private_fixture_paths(case)


def test_an_empty_ab_raws_directory_in_dest_is_a_leak(tmp_path):
    case = _case(tmp_path, _FILES)
    dest = tmp_path / "dest"
    copy_fixture(case, dest)
    (dest / "ab_raws").mkdir()
    assert find_private_leaks(case, dest) == ["ab_raws"]


def test_an_empty_directory_named_like_a_private_directory_is_a_leak(tmp_path):
    case = _case(tmp_path, _FILES, ["sub"])
    dest = tmp_path / "dest"
    copy_fixture(case, dest)
    (dest / "sub").mkdir()
    assert find_private_leaks(case, dest) == ["sub"]


def test_cli_exit_codes_are_0_clean_1_leak_2_error(tmp_path):
    case = _case(tmp_path, _FILES, ["defects.json"])
    clean = tmp_path / "clean"
    copy_fixture(case, clean)
    assert _run("--check", str(case), str(clean)).returncode == 0
    (clean / "defects.json").write_text("x", encoding="utf-8")
    assert _run("--check", str(case), str(clean)).returncode == 1
    assert _run("--check", str(case), str(tmp_path / "missing")).returncode == 2
    existing = tmp_path / "existing"
    existing.mkdir()
    assert _run(str(case), str(existing)).returncode == 2


# --- S1: spelling and normalization ---------------------------------------------------


def test_a_declaration_spelled_differently_from_the_disk_is_refused_naming_both(tmp_path):
    case = _case(tmp_path, _FILES, ["Defects.json"])
    with pytest.raises(FixtureCopyError) as err:
        private_fixture_paths(case)
    message = str(err.value)
    assert "X" in message and "Defects.json" in message and "defects.json" in message and "spell" in message


def test_a_declaration_in_another_unicode_normalization_is_refused(tmp_path):
    on_disk = unicodedata.normalize("NFC", "café.json")
    declared = unicodedata.normalize("NFD", on_disk)
    assert on_disk != declared
    case = _case(tmp_path, {"diff.patch": "d", on_disk: "KEY"}, [declared])
    with pytest.raises(FixtureCopyError, match="spell"):
        private_fixture_paths(case)


def test_a_wrongly_spelled_component_deeper_in_the_path_is_refused(tmp_path):
    case = _case(tmp_path, _FILES, ["Sub/notes.md"])
    with pytest.raises(FixtureCopyError, match="spell"):
        private_fixture_paths(case)


def test_a_dest_file_in_another_case_is_a_leak(tmp_path):
    case = _case(tmp_path, _FILES, ["defects.json"])
    dest = tmp_path / "dest"
    copy_fixture(case, dest)
    (dest / "DEFECTS.JSON").write_text("different bytes", encoding="utf-8")
    assert find_private_leaks(case, dest) == ["DEFECTS.JSON"]


def test_a_dest_file_in_another_unicode_normalization_is_a_leak(tmp_path):
    nfc = unicodedata.normalize("NFC", "café.json")
    nfd = unicodedata.normalize("NFD", nfc)
    case = _case(tmp_path, {"diff.patch": "d", nfc: "KEY"}, [nfc])
    dest = tmp_path / "dest"
    copy_fixture(case, dest)
    (dest / nfd).write_text("different bytes", encoding="utf-8")
    assert find_private_leaks(case, dest) == [nfd]


# --- S2: content and symlinks ---------------------------------------------------------


def test_a_byte_identical_copy_under_another_name_is_a_leak(tmp_path):
    case = _case(tmp_path, _FILES, ["defects.json"])
    dest = tmp_path / "dest"
    copy_fixture(case, dest)
    (dest / "notes").mkdir()
    (dest / "notes" / "totally-innocent.txt").write_bytes((case / "fixture" / "defects.json").read_bytes())
    assert find_private_leaks(case, dest) == ["notes/totally-innocent.txt"]


def test_a_symlink_to_an_identical_copy_elsewhere_is_a_leak_through_its_content(tmp_path):
    case = _case(tmp_path, _FILES, ["defects.json"])
    dest = tmp_path / "dest"
    copy_fixture(case, dest)
    elsewhere = tmp_path / "elsewhere.txt"
    elsewhere.write_bytes((case / "fixture" / "defects.json").read_bytes())
    (dest / "alias").symlink_to(elsewhere)
    assert "alias" in find_private_leaks(case, dest)


def test_a_symlink_into_fixture_is_a_leak_even_to_a_non_private_file(tmp_path):
    case = _case(tmp_path, _FILES, ["defects.json"])
    dest = tmp_path / "dest"
    copy_fixture(case, dest)
    (dest / "back").symlink_to(case / "fixture" / "spec.md")
    assert find_private_leaks(case, dest) == ["back"]


def test_a_symlink_to_an_unrelated_file_is_not_a_leak(tmp_path):
    case = _case(tmp_path, _FILES, ["defects.json"])
    dest = tmp_path / "dest"
    copy_fixture(case, dest)
    other = tmp_path / "other.txt"
    other.write_text("unrelated", encoding="utf-8")
    (dest / "ok").symlink_to(other)
    assert find_private_leaks(case, dest) == []


def test_an_empty_private_file_does_not_flag_every_empty_file(tmp_path):
    case = _case(tmp_path, {"diff.patch": "d", "empty.key": ""}, ["empty.key"])
    dest = tmp_path / "dest"
    copy_fixture(case, dest)
    (dest / "__init__.py").write_text("", encoding="utf-8")
    assert find_private_leaks(case, dest) == []


# --- S3: dest inside fixture, builder cases, non-cases ---------------------------------


def test_a_dest_inside_the_fixture_is_refused_and_nothing_is_written(tmp_path):
    case = _case(tmp_path, _FILES, ["defects.json"])
    dest = case / "fixture" / "inner"
    with pytest.raises(FixtureCopyError, match="inside"):
        copy_fixture(case, dest)
    assert not os.path.lexists(dest)


def test_a_dest_reached_through_a_symlink_into_the_fixture_is_refused(tmp_path):
    case = _case(tmp_path, _FILES, ["defects.json"])
    (tmp_path / "alias").symlink_to(case / "fixture")
    with pytest.raises(FixtureCopyError, match="inside"):
        copy_fixture(case, tmp_path / "alias" / "inner")


def test_a_case_with_a_builder_key_is_refused_with_the_builder_command(tmp_path):
    case = _case(tmp_path, _FILES, ["defects.json"], toml_extra='builder = "x.py"\n')
    with pytest.raises(FixtureCopyError, match=r"python <builder> <dest>"):
        copy_fixture(case, tmp_path / "dest")
    assert not (tmp_path / "dest").exists()


def test_a_case_with_a_local_build_fixture_script_is_refused(tmp_path):
    case = _case(tmp_path, _FILES, ["defects.json"])
    (case / "build_fixture.py").write_text("", encoding="utf-8")
    with pytest.raises(FixtureCopyError, match="builder"):
        copy_fixture(case, tmp_path / "dest")


def test_has_builder_agrees_with_calibration_on_every_committed_case():
    from evals._harness.calibration import _load_case_toml, _resolve_builder

    cases = sorted(p.parent for p in (_REPO_ROOT / "evals").glob("*/*/case.toml") if not p.parts[-3].startswith("_"))
    assert cases
    for case in cases:
        expected = _resolve_builder(case, _REPO_ROOT, _load_case_toml(case)) is not None
        assert has_builder(case) is expected, case


def test_a_directory_without_case_toml_is_not_a_case_not_a_missing_fixture(tmp_path):
    not_a_case = tmp_path / "plain"
    (not_a_case / "fixture").mkdir(parents=True)
    with pytest.raises(FixtureCopyError, match="is not a case"):
        copy_fixture(not_a_case, tmp_path / "dest")
    with pytest.raises(FixtureCopyError, match="is not a case"):
        private_fixture_paths(not_a_case)
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(FixtureCopyError, match="is not a case"):
        copy_fixture(empty, tmp_path / "dest2")


# --- S4: the copy must describe what fixture_fingerprint hashed ------------------------


def test_outside_a_git_work_tree_there_is_nothing_to_compare_and_the_copy_proceeds(tmp_path):
    case = _case(tmp_path, _FILES, ["defects.json"])
    assert fixture_dirty_paths(case) is None
    assert copy_fixture(case, tmp_path / "dest") == ["diff.patch", "spec.md", "sub/notes.md"]


def test_a_committed_clean_fixture_in_a_git_work_tree_copies(tmp_path):
    case = _repo_case(tmp_path, _FILES, ["defects.json"])
    assert fixture_dirty_paths(case) == []
    assert copy_fixture(case, tmp_path / "dest") == ["diff.patch", "spec.md", "sub/notes.md"]


def test_an_untracked_file_in_the_fixture_is_refused_naming_it(tmp_path):
    case = _repo_case(tmp_path, _FILES, ["defects.json"])
    (case / "fixture" / "defects.json.bak").write_text("KEY", encoding="utf-8")
    with pytest.raises(FixtureCopyError, match=r"defects\.json\.bak"):
        copy_fixture(case, tmp_path / "dest")
    assert not (tmp_path / "dest").exists()


def test_a_locally_modified_tracked_file_is_refused_naming_it(tmp_path):
    case = _repo_case(tmp_path, _FILES, ["defects.json"])
    (case / "fixture" / "spec.md").write_text("edited", encoding="utf-8")
    with pytest.raises(FixtureCopyError, match=r"spec\.md"):
        copy_fixture(case, tmp_path / "dest")


def test_a_staged_but_uncommitted_file_is_refused(tmp_path):
    case = _repo_case(tmp_path, _FILES, ["defects.json"])
    (case / "fixture" / "new.md").write_text("n", encoding="utf-8")
    _git(case, "add", "fixture/new.md")
    with pytest.raises(FixtureCopyError, match=r"new\.md"):
        copy_fixture(case, tmp_path / "dest")


def test_an_ignored_file_present_in_the_fixture_is_refused(tmp_path):
    case = _repo_case(tmp_path, _FILES, ["defects.json"])
    (tmp_path / "repo" / ".gitignore").write_text("*.cache\n", encoding="utf-8")
    (case / "fixture" / "stale.cache").write_text("c", encoding="utf-8")
    with pytest.raises(FixtureCopyError, match=r"stale\.cache"):
        copy_fixture(case, tmp_path / "dest")


def test_changes_outside_the_fixture_do_not_block_the_copy(tmp_path):
    case = _repo_case(tmp_path, _FILES, ["defects.json"])
    (case / "prompt.md").write_text("edited prompt", encoding="utf-8")
    assert copy_fixture(case, tmp_path / "dest")
