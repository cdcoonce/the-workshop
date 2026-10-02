"""Tests for evals._harness.guards.runs_immutable.

Every repo here is a synthetic git repo built under ``tmp_path``; nothing
touches a real ``evals/<skill>/`` directory.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from evals._harness.guards import GuardContext
from evals._harness.guards.runs_immutable import check

_RUN = "evals/example-skill/runs/20260101T000000Z-aaaaaaaa.json"
_RAW = "evals/example-skill/runs/20260101T000000Z-aaaaaaaa/case-a/attempt-1/final.txt"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def _write(repo: Path, rel_path: str, content: str) -> None:
    path = repo / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _base_repo(tmp_path: Path) -> tuple[Path, str]:
    """A repo whose base commit already holds one run file and one raw."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _write(repo, _RUN, '{"verdict": "green"}\n')
    _write(repo, _RAW, "original raw\n")
    _write(repo, "evals/example-skill/checks.manifest", "")
    _write(repo, "evals/example-skill/case-a/prompt.md", "do it\n")
    return repo, _commit(repo, "base")


def _run(repo: Path, base: str):
    return check(GuardContext(base=base, repo_root=repo))


def test_fails_when_an_existing_run_file_is_modified(tmp_path):
    repo, base = _base_repo(tmp_path)
    _write(repo, _RUN, '{"verdict": "red"}\n')
    _commit(repo, "rewrite the run file")

    results = _run(repo, base)

    assert len(results) == 1
    assert results[0].level == "fail"
    assert results[0].guard == "runs_immutable"
    assert _RUN in results[0].message


def test_fails_when_an_existing_raw_under_the_stem_directory_is_modified(tmp_path):
    repo, base = _base_repo(tmp_path)
    _write(repo, _RAW, "doctored raw\n")
    _commit(repo, "rewrite the raw")

    results = _run(repo, base)

    assert len(results) == 1
    assert results[0].level == "fail"
    assert _RAW in results[0].message


def test_fails_when_an_existing_run_file_is_deleted(tmp_path):
    repo, base = _base_repo(tmp_path)
    (repo / _RUN).unlink()
    _commit(repo, "delete the run file")

    results = _run(repo, base)

    assert len(results) == 1
    assert results[0].level == "fail"
    assert _RUN in results[0].message


def test_fails_when_an_existing_raw_is_deleted(tmp_path):
    repo, base = _base_repo(tmp_path)
    (repo / _RAW).unlink()
    _commit(repo, "delete the raw")

    results = _run(repo, base)

    assert len(results) == 1
    assert _RAW in results[0].message


def test_fails_when_an_existing_run_file_is_renamed_out_of_runs(tmp_path):
    """A rename must read as delete plus add: with rename detection on, git
    prints only the new (unprotected) path and the protected old path escapes.
    """
    repo, base = _base_repo(tmp_path)
    _git(repo, "mv", _RUN, "evals/example-skill/elsewhere.json")
    _commit(repo, "rename the run file out of runs/")

    results = _run(repo, base)

    assert len(results) == 1
    assert results[0].level == "fail"
    assert _RUN in results[0].message


def test_reports_a_rename_and_a_modification_in_the_same_diff(tmp_path):
    """Both protected files are reported. With rename detection on, git's
    ``-z`` output carries a third field for the rename, which shifts every
    status/path pair after it, so the modification would be lost.
    """
    repo, base = _base_repo(tmp_path)
    _git(repo, "mv", _RUN, "evals/example-skill/elsewhere.json")
    _write(repo, _RAW, "doctored raw\n")
    _commit(repo, "rename one protected file and rewrite another")

    results = _run(repo, base)

    assert sorted(result.message.split(":")[0] for result in results) == sorted([_RUN, _RAW])


def test_fails_when_an_existing_run_file_is_renamed_within_runs(tmp_path):
    repo, base = _base_repo(tmp_path)
    renamed = "evals/example-skill/runs/20260102T000000Z-bbbbbbbb.json"
    _git(repo, "mv", _RUN, renamed)
    _commit(repo, "rename the run file inside runs/")

    results = _run(repo, base)

    assert len(results) == 1
    assert results[0].level == "fail"
    assert _RUN in results[0].message


def test_fails_when_a_file_replaces_an_existing_run_file_via_type_change(tmp_path):
    """A non-add, non-modify status (here a symlink swapped in) is still a change."""
    repo, base = _base_repo(tmp_path)
    (repo / _RUN).unlink()
    (repo / _RUN).symlink_to("elsewhere.json")
    _commit(repo, "replace the run file with a symlink")

    results = _run(repo, base)

    assert len(results) == 1
    assert _RUN in results[0].message


def test_reports_every_protected_file_that_changed(tmp_path):
    repo, base = _base_repo(tmp_path)
    _write(repo, _RUN, '{"verdict": "red"}\n')
    _write(repo, _RAW, "doctored raw\n")
    _commit(repo, "rewrite both")

    results = _run(repo, base)

    assert len(results) == 2
    messages = " ".join(result.message for result in results)
    assert _RUN in messages and _RAW in messages


def test_protects_every_skills_runs_directory(tmp_path):
    repo, base = _base_repo(tmp_path)
    other = "evals/other-skill/runs/20260101T000000Z-cccccccc.json"
    _write(repo, other, "{}\n")
    base = _commit(repo, "another skill's run file")
    _write(repo, other, '{"changed": true}\n')
    _commit(repo, "rewrite it")

    results = _run(repo, base)

    assert len(results) == 1
    assert other in results[0].message


def test_passes_a_diff_that_only_adds_new_runs(tmp_path):
    repo, base = _base_repo(tmp_path)
    _write(repo, "evals/example-skill/runs/20260102T000000Z-bbbbbbbb.json", "{}\n")
    _write(repo, "evals/example-skill/runs/20260102T000000Z-bbbbbbbb/case-a/attempt-1/final.txt", "raw\n")
    _commit(repo, "a new run")

    assert _run(repo, base) == []


def test_passes_when_a_file_outside_runs_is_renamed_into_runs(tmp_path):
    """Moving an unprotected file into runs/ creates a new path there: an add."""
    repo, base = _base_repo(tmp_path)
    _git(repo, "mv", "evals/example-skill/case-a/prompt.md", "evals/example-skill/runs/new.json")
    _commit(repo, "move a file into runs/")

    assert _run(repo, base) == []


def test_passes_an_empty_diff(tmp_path):
    repo, base = _base_repo(tmp_path)

    assert _run(repo, base) == []


def test_passes_a_diff_that_changes_only_files_outside_runs(tmp_path):
    repo, base = _base_repo(tmp_path)
    _write(repo, "evals/example-skill/case-a/prompt.md", "changed\n")
    _write(repo, "evals/example-skill/checks.manifest", "item.a described\n")
    _commit(repo, "edit a case")

    assert _run(repo, base) == []


@pytest.mark.parametrize(
    "rel_path",
    [
        "evals/example-skill/case-a/runs/note.json",
        "evals/runs/note.json",
        "notes/evals/example-skill/runs/note.json",
    ],
)
def test_passes_a_change_to_a_runs_directory_that_is_not_a_skills_runs_directory(tmp_path, rel_path):
    repo, base = _base_repo(tmp_path)
    _write(repo, rel_path, "one\n")
    base = _commit(repo, "seed it")
    _write(repo, rel_path, "two\n")
    _commit(repo, "change it")

    assert _run(repo, base) == []


def test_ignores_a_base_only_change_via_the_three_dot_range(tmp_path):
    """The diff is base...HEAD (merge-base relative): a protected file the BASE
    branch rewrote after this branch forked is not this branch's change.
    """
    repo, fork = _base_repo(tmp_path)
    branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    _git(repo, "branch", "base-line", fork)
    _git(repo, "checkout", "-q", "base-line")
    _write(repo, _RUN, '{"base": "progressed"}\n')
    base_head = _commit(repo, "base rewrites the run file")
    _git(repo, "checkout", "-q", branch)
    _write(repo, "unrelated.txt", "hello\n")
    _commit(repo, "this branch touches something else")

    assert _run(repo, base_head) == []
