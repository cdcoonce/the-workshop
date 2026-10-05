"""A2's answer key must not reach a dispatched agent through the conductor's fixture copy (#1130).

``fixture/defects.json`` stays where it is (moving it would change the input
hash and stale A2-D2's calibration record). ``case.toml`` lists it under
``fixture_private`` and ``evals._harness.fixture_copy`` omits it.
"""

from __future__ import annotations

import shutil
import subprocess
import sys

from evals._harness.fixture_copy import copy_fixture, find_private_leaks, private_fixture_paths


def test_case_toml_declares_the_answer_key_private(case_dir):
    assert private_fixture_paths(case_dir) == ("defects.json",)


def test_the_key_still_sits_in_fixture_so_the_input_hash_is_unchanged(case_dir):
    assert (case_dir / "fixture" / "defects.json").is_file()


def test_the_default_copy_step_omits_the_key_and_keeps_the_two_review_files(case_dir, tmp_path):
    dest = tmp_path / "agent-dir"
    copied = copy_fixture(case_dir, dest)
    assert copied == ["diff.patch", "spec.md"]
    assert not (dest / "defects.json").exists()
    assert sorted(p.name for p in dest.rglob("*") if p.is_file()) == ["diff.patch", "spec.md"]
    for name in ("diff.patch", "spec.md"):
        assert (dest / name).read_bytes() == (case_dir / "fixture" / name).read_bytes()
    assert find_private_leaks(case_dir, dest) == []


def test_a_whole_tree_copy_of_the_fixture_is_flagged_positive_control(case_dir, tmp_path):
    dest = tmp_path / "hand-copy"
    shutil.copytree(case_dir / "fixture", dest)
    assert (dest / "defects.json").is_file()
    assert find_private_leaks(case_dir, dest) == ["defects.json"]


def test_the_command_lines_skill_md_gives_copy_clean_and_check_clean(case_dir, repo_root, tmp_path):
    dest = tmp_path / "cli-dest"
    base = [sys.executable, "-B", "-m", "evals._harness.fixture_copy"]
    copy = subprocess.run([*base, str(case_dir), str(dest)], cwd=repo_root, capture_output=True, text=True, check=False)
    assert copy.returncode == 0, copy.stderr
    assert copy.stdout.split() == ["diff.patch", "spec.md"]
    check = subprocess.run([*base, "--check", str(case_dir), str(dest)], cwd=repo_root, capture_output=True, text=True, check=False)
    assert check.returncode == 0, check.stdout + check.stderr


def test_the_check_command_fails_on_a_hand_copy_of_the_fixture(case_dir, repo_root, tmp_path):
    dest = tmp_path / "hand-copy"
    shutil.copytree(case_dir / "fixture", dest)
    check = subprocess.run(
        [sys.executable, "-B", "-m", "evals._harness.fixture_copy", "--check", str(case_dir), str(dest)],
        cwd=repo_root, capture_output=True, text=True, check=False,
    )
    assert check.returncode != 0
    assert "defects.json" in check.stdout
