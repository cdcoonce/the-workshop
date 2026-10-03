"""Provenance of every file A2 copies from the terse-lens-contract A/B experiment.

Each recorded ``source_blob_sha`` is checked against ``git rev-parse
<resolved_ref>:<source_path>`` (the experiment as it stood at the resolved
ref), never against a hash of working-tree bytes of a file this case does not
own. The experiment's own files are copy-only: this case neither edits nor
references them in place.
"""

from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

import pytest
_EXPERIMENT = "docs/experiments/2026-09-21-terse-lens-contract-ab"


@pytest.fixture(scope="module")
def provenance(case_dir) -> dict:
    return tomllib.loads((case_dir / "provenance.toml").read_text(encoding="utf-8"))


def test_provenance_records_a_full_resolved_commit_sha(provenance):
    ref = provenance["resolved_ref"]
    assert len(ref) == 40 and set(ref) <= set("0123456789abcdef")


def test_every_copied_fixture_file_has_a_provenance_entry(provenance, case_dir):
    recorded = {entry["file"] for entry in provenance["files"]}
    on_disk = {
        path.relative_to(case_dir).as_posix() for path in (case_dir / "fixture").rglob("*") if path.is_file()
    }
    assert on_disk == {"fixture/defects.json", "fixture/diff.patch", "fixture/spec.md"}
    assert on_disk <= recorded


def test_every_copied_ab_raw_has_a_provenance_entry(provenance, case_dir):
    recorded = {entry["file"] for entry in provenance["files"]}
    on_disk = {
        path.relative_to(case_dir).as_posix() for path in (case_dir / "ab_raws").rglob("*") if path.is_file()
    }
    assert len(on_disk) == 18  # 3 arms (a, b, a2) x 3 lenses x 2 replicates
    assert on_disk <= recorded


def test_provenance_lists_no_file_that_is_not_in_the_case(provenance, case_dir):
    for entry in provenance["files"]:
        assert (case_dir / entry["file"]).is_file(), entry["file"]


def test_each_entry_names_a_source_inside_the_experiment(provenance):
    for entry in provenance["files"]:
        assert entry["source_path"].startswith(_EXPERIMENT + "/"), entry


def test_each_source_blob_sha_is_what_git_resolves_at_the_resolved_ref(provenance, git):
    for entry in provenance["files"]:
        resolved = git("rev-parse", f"{provenance['resolved_ref']}:{entry['source_path']}").strip()
        assert entry["source_blob_sha"] == resolved, entry["file"]


def test_each_copy_is_byte_identical_to_its_source_blob(provenance, case_dir, git):
    for entry in provenance["files"]:
        copied = git("hash-object", "--", str(case_dir / entry["file"])).strip()
        assert copied == entry["source_blob_sha"], entry["file"]


def _committed_changes(repo: Path, ref: str, path: str) -> str:
    """Committed changes under *path* since *ref*; the working tree is not consulted."""
    result = subprocess.run(
        ["git", "-C", str(repo), "diff", "--stat", f"{ref}...HEAD", "--", path],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _scratch_repo(tmp_path: Path) -> Path:
    """A throwaway repo holding one tracked file under the experiment's path; the real repo is never written."""
    repo = tmp_path / "scratch-repo"
    (repo / _EXPERIMENT).mkdir(parents=True)
    (repo / _EXPERIMENT / "prereg.md").write_text("frozen\n", encoding="utf-8")
    env = ["-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false"]
    for args in (["init", "-q"], ["add", "."], [*env, "commit", "-q", "-m", "base"]):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    return repo


def test_the_experiment_directory_has_no_committed_change_since_the_resolved_ref(provenance, repo_root):
    """The experiment is a frozen record: A2 copies from it and never edits it."""
    assert _committed_changes(repo_root, provenance["resolved_ref"], _EXPERIMENT).strip() == ""


def test_an_untracked_file_under_the_experiment_does_not_turn_the_check_red(tmp_path):
    repo = _scratch_repo(tmp_path)
    (repo / _EXPERIMENT / "results").mkdir()
    (repo / _EXPERIMENT / "results" / "stray-untracked-note.txt").write_text("local scratch\n", encoding="utf-8")
    assert _committed_changes(repo, "HEAD", _EXPERIMENT).strip() == ""


def test_an_uncommitted_edit_to_a_tracked_file_does_not_turn_the_check_red_either(tmp_path):
    repo = _scratch_repo(tmp_path)
    (repo / _EXPERIMENT / "prereg.md").write_text("edited but not committed\n", encoding="utf-8")
    assert _committed_changes(repo, "HEAD", _EXPERIMENT).strip() == ""


def test_the_committed_change_check_does_see_a_committed_edit(tmp_path):
    repo = _scratch_repo(tmp_path)
    (repo / _EXPERIMENT / "prereg.md").write_text("edited and committed\n", encoding="utf-8")
    env = ["-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false"]
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), *env, "commit", "-q", "-m", "edit"], check=True, capture_output=True)
    assert _committed_changes(repo, "HEAD~1", _EXPERIMENT).strip() != ""
