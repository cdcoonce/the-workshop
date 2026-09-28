"""Tests for evals._harness.guards.direct_tier."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from evals._harness.deps import tree_hash
from evals._harness.guards import GuardContext
from evals._harness.guards.direct_tier import check


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _write(repo: Path, rel_path: str, content: str) -> None:
    path = repo / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _base_repo(tmp_path: Path, *, active: bool) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "evals/commit/marker.txt", "original\n")
    _write(repo, "evals/commit/deps", 'direct = ["evals/commit/marker.txt"]\ninjection = []\n')
    manifest = "gated.one A description\n" if active else ""
    _write(repo, "evals/commit/checks.manifest", manifest)
    _write(repo, "evals/commit/retired.md", "")
    base_sha = _commit(repo, "base")
    return repo, base_sha


def _run_file(*, verdict: str, direct_tier_hash: str) -> str:
    return json.dumps(
        {
            "skill": "commit",
            "verdict": verdict,
            "fingerprint": {
                "direct_tier_hash": direct_tier_hash,
                "injection_tier_hash": "irrelevant",
                "plugin_version": "0.1.0",
                "claude_code_version": "1.0.0",
                "run_date": "2026-01-01",
            },
            "tokens": 0,
            "wall_time_s": 0,
            "cases": [],
        }
    )


def test_fails_when_active_skills_direct_tier_changes_with_no_matching_run(tmp_path):
    repo, base_sha = _base_repo(tmp_path, active=True)
    _write(repo, "evals/commit/marker.txt", "changed\n")
    _commit(repo, "change marker")

    results = check(GuardContext(base=base_sha, repo_root=repo))

    assert len(results) == 1
    assert results[0].level == "fail"
    assert results[0].guard == "direct_tier"
    assert "commit" in results[0].message


def test_passes_with_a_matching_green_run_file(tmp_path):
    repo, base_sha = _base_repo(tmp_path, active=True)
    _write(repo, "evals/commit/marker.txt", "changed\n")
    _commit(repo, "change marker")
    expected_hash = tree_hash(["evals/commit/marker.txt"], ref="HEAD", repo=repo)
    _write(repo, "evals/commit/runs/run1.json", _run_file(verdict="green", direct_tier_hash=expected_hash))
    _commit(repo, "add green run")

    results = check(GuardContext(base=base_sha, repo_root=repo))

    assert results == []


@pytest.mark.parametrize("verdict", ["red", "void"])
def test_fails_with_a_non_green_run_file(tmp_path, verdict):
    repo, base_sha = _base_repo(tmp_path, active=True)
    _write(repo, "evals/commit/marker.txt", "changed\n")
    _commit(repo, "change marker")
    expected_hash = tree_hash(["evals/commit/marker.txt"], ref="HEAD", repo=repo)
    _write(repo, "evals/commit/runs/run1.json", _run_file(verdict=verdict, direct_tier_hash=expected_hash))
    _commit(repo, "add non-green run")

    results = check(GuardContext(base=base_sha, repo_root=repo))

    assert len(results) == 1
    assert results[0].level == "fail"


def test_does_not_evaluate_an_inactive_skills_direct_tier_change(tmp_path):
    repo, base_sha = _base_repo(tmp_path, active=False)
    _write(repo, "evals/commit/marker.txt", "changed\n")
    _commit(repo, "change marker")

    results = check(GuardContext(base=base_sha, repo_root=repo))

    assert results == []


def test_no_fail_when_the_diff_never_touches_the_direct_tier(tmp_path):
    repo, base_sha = _base_repo(tmp_path, active=True)
    _write(repo, "evals/commit/unrelated.txt", "hello\n")
    _commit(repo, "unrelated change")

    results = check(GuardContext(base=base_sha, repo_root=repo))

    assert results == []


def test_skips_an_active_skill_with_no_deps_file(tmp_path):
    repo, base_sha = _base_repo(tmp_path, active=True)
    _write(repo, "evals/tdd/checks.manifest", "gated.one A description\n")
    _commit(repo, "activate tdd without a deps file")

    results = check(GuardContext(base=base_sha, repo_root=repo))

    assert results == []


def test_no_fail_on_an_empty_diff(tmp_path):
    repo, base_sha = _base_repo(tmp_path, active=True)

    results = check(GuardContext(base=base_sha, repo_root=repo))

    assert results == []


def test_fails_when_a_green_run_files_hash_does_not_match(tmp_path):
    repo, base_sha = _base_repo(tmp_path, active=True)
    _write(repo, "evals/commit/marker.txt", "changed\n")
    _commit(repo, "change marker")
    _write(repo, "evals/commit/runs/run1.json", _run_file(verdict="green", direct_tier_hash="stale-hash"))
    _commit(repo, "add stale-hash green run")

    results = check(GuardContext(base=base_sha, repo_root=repo))

    assert len(results) == 1
    assert results[0].level == "fail"


def test_ignores_a_matching_green_run_file_added_outside_the_skills_runs_dir(tmp_path):
    repo, base_sha = _base_repo(tmp_path, active=True)
    _write(repo, "evals/commit/marker.txt", "changed\n")
    _commit(repo, "change marker")
    expected_hash = tree_hash(["evals/commit/marker.txt"], ref="HEAD", repo=repo)
    _write(repo, "evals/commit/not-runs/run1.json", _run_file(verdict="green", direct_tier_hash=expected_hash))
    _commit(repo, "add green run in the wrong place")

    results = check(GuardContext(base=base_sha, repo_root=repo))

    assert len(results) == 1
    assert results[0].level == "fail"


def test_a_modified_preexisting_run_file_does_not_satisfy_the_requirement(tmp_path):
    repo, base_sha = _base_repo(tmp_path, active=True)
    _write(repo, "evals/commit/runs/run1.json", _run_file(verdict="red", direct_tier_hash="stale-hash"))
    _commit(repo, "seed a preexisting run file")
    base_sha = _git(repo, "rev-parse", "HEAD")

    _write(repo, "evals/commit/marker.txt", "changed\n")
    _commit(repo, "change marker")
    expected_hash = tree_hash(["evals/commit/marker.txt"], ref="HEAD", repo=repo)
    # Modifies (not adds) the preexisting run file — a genuine "M" in the
    # diff, never an "A" — so it must not satisfy the requirement even
    # though its content now looks green and matches the current hash.
    _write(repo, "evals/commit/runs/run1.json", _run_file(verdict="green", direct_tier_hash=expected_hash))
    _commit(repo, "modify the preexisting run file to look green")

    results = check(GuardContext(base=base_sha, repo_root=repo))

    assert len(results) == 1
    assert results[0].level == "fail"


def test_fails_when_a_direct_tier_file_is_deleted(tmp_path):
    repo, base_sha = _base_repo(tmp_path, active=True)
    (repo / "evals/commit/marker.txt").unlink()
    _commit(repo, "delete the direct-tier file")

    results = check(GuardContext(base=base_sha, repo_root=repo))

    assert len(results) == 1
    assert results[0].level == "fail"


def test_fails_when_a_direct_tier_file_is_renamed_out_of_the_tier(tmp_path):
    """F1: a plain `git diff --name-only` auto-detects the rename and shows only
    the new path, which is not itself a tier member, so the base-side union
    that catches deletions never sees the old path either unless renames are
    disabled on the diff.
    """
    repo, base_sha = _base_repo(tmp_path, active=True)
    _git(repo, "mv", "evals/commit/marker.txt", "outside.txt")
    _commit(repo, "rename marker out of the tier")

    results = check(GuardContext(base=base_sha, repo_root=repo))

    assert len(results) == 1
    assert results[0].level == "fail"


def test_a_non_json_run_file_does_not_satisfy_the_requirement(tmp_path):
    """N2: a file directly in evals/<skill>/runs/ without a .json suffix must
    never satisfy the guard, even with otherwise-valid green content and the
    current hash -- only ``.json`` run files are ever written by the ledger.
    """
    repo, base_sha = _base_repo(tmp_path, active=True)
    _write(repo, "evals/commit/marker.txt", "changed\n")
    _commit(repo, "change marker")
    expected_hash = tree_hash(["evals/commit/marker.txt"], ref="HEAD", repo=repo)
    _write(repo, "evals/commit/runs/run1.txt", _run_file(verdict="green", direct_tier_hash=expected_hash))
    _commit(repo, "add a non-json run file")

    results = check(GuardContext(base=base_sha, repo_root=repo))

    assert len(results) == 1
    assert results[0].level == "fail"


def test_a_nested_raw_json_under_runs_does_not_satisfy_the_requirement(tmp_path):
    """F2: only files directly in evals/<skill>/runs/ are run files; anything
    deeper (an attempt's raw output) must never satisfy the guard.
    """
    repo, base_sha = _base_repo(tmp_path, active=True)
    _write(repo, "evals/commit/marker.txt", "changed\n")
    _commit(repo, "change marker")
    expected_hash = tree_hash(["evals/commit/marker.txt"], ref="HEAD", repo=repo)
    _write(
        repo,
        "evals/commit/runs/20260101T000000Z-abc/case1/attempt-1/out.json",
        _run_file(verdict="green", direct_tier_hash=expected_hash),
    )
    _commit(repo, "add a nested raw json")

    results = check(GuardContext(base=base_sha, repo_root=repo))

    assert len(results) == 1
    assert results[0].level == "fail"


def test_a_run_file_under_a_different_skills_runs_dir_does_not_satisfy_the_requirement(tmp_path):
    """F5/I5: a run file only counts for skill S if it is under evals/S/runs/."""
    repo, base_sha = _base_repo(tmp_path, active=True)
    _write(repo, "evals/commit/marker.txt", "changed\n")
    _commit(repo, "change marker")
    expected_hash = tree_hash(["evals/commit/marker.txt"], ref="HEAD", repo=repo)
    _write(repo, "evals/tdd/runs/run1.json", _run_file(verdict="green", direct_tier_hash=expected_hash))
    _commit(repo, "add a matching green run under the wrong skill's runs dir")

    results = check(GuardContext(base=base_sha, repo_root=repo))

    assert len(results) == 1
    assert results[0].level == "fail"


def test_a_green_run_file_with_a_missing_direct_tier_hash_does_not_satisfy_the_requirement(tmp_path):
    """F5/I4: a green run file whose recorded hash is absent never satisfies the guard."""
    repo, base_sha = _base_repo(tmp_path, active=True)
    _write(repo, "evals/commit/marker.txt", "changed\n")
    _commit(repo, "change marker")
    _write(
        repo,
        "evals/commit/runs/run1.json",
        json.dumps({"skill": "commit", "verdict": "green", "fingerprint": {}}),
    )
    _commit(repo, "add a green run with no recorded hash")

    results = check(GuardContext(base=base_sha, repo_root=repo))

    assert len(results) == 1
    assert results[0].level == "fail"


def test_a_green_run_file_with_an_empty_direct_tier_hash_does_not_satisfy_the_requirement(tmp_path):
    """F5/I4: a green run file whose recorded hash is empty never satisfies the guard."""
    repo, base_sha = _base_repo(tmp_path, active=True)
    _write(repo, "evals/commit/marker.txt", "changed\n")
    _commit(repo, "change marker")
    _write(
        repo,
        "evals/commit/runs/run1.json",
        _run_file(verdict="green", direct_tier_hash=""),
    )
    _commit(repo, "add a green run with an empty recorded hash")

    results = check(GuardContext(base=base_sha, repo_root=repo))

    assert len(results) == 1
    assert results[0].level == "fail"


def test_ignores_base_only_changes_via_three_dot_range(tmp_path):
    """F5/I1: the diff must be $(VERSION_BASE)...HEAD (three-dot, merge-base
    relative). With divergent history, a commit the base branch makes to the
    skill's direct tier AFTER the PR branch forked must not fail a PR that
    never touches it — a two-dot diff would incorrectly include it.
    """
    repo, fork_sha = _base_repo(tmp_path, active=True)
    initial_branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")

    _git(repo, "branch", "base-line", fork_sha)
    _git(repo, "checkout", "-q", "base-line")
    _write(repo, "evals/commit/marker.txt", "base progressed after the fork\n")
    base_head_sha = _commit(repo, "base branch edits the tier after the fork")

    _git(repo, "checkout", "-q", initial_branch)
    _write(repo, "unrelated.txt", "hello\n")
    _commit(repo, "PR branch touches something unrelated")

    results = check(GuardContext(base=base_head_sha, repo_root=repo))

    assert results == []
