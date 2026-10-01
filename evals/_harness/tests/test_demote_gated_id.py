"""Tests for evals._harness.guards.demote_gated_id."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from evals._harness.guards import GuardContext
from evals._harness.guards.demote_gated_id import check


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


def _base_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "evals/commit/marker.txt", "original\n")
    _write(repo, "evals/commit/deps", 'direct = ["evals/commit/marker.txt"]\ninjection = []\n')
    _write(repo, "evals/commit/checks.manifest", "gated.one A description\ngated.two B description\n")
    base_sha = _commit(repo, "base")
    return repo, base_sha


def test_fails_when_direct_tier_changes_and_a_gated_id_is_removed(tmp_path):
    repo, base_sha = _base_repo(tmp_path)
    _write(repo, "evals/commit/marker.txt", "changed\n")
    _write(repo, "evals/commit/checks.manifest", "gated.one A description\n")
    _commit(repo, "change the tier and drop a gated id")

    results = check(GuardContext(base=base_sha, repo_root=repo))

    assert len(results) == 1
    assert results[0].level == "fail"
    assert results[0].guard == "demote_gated_id"
    assert "commit" in results[0].message


def test_passes_when_direct_tier_changes_with_no_gated_id_removed(tmp_path):
    repo, base_sha = _base_repo(tmp_path)
    _write(repo, "evals/commit/marker.txt", "changed\n")
    _commit(repo, "change the tier only")

    results = check(GuardContext(base=base_sha, repo_root=repo))

    assert results == []


def test_passes_when_a_gated_id_is_removed_with_no_direct_tier_change(tmp_path):
    repo, base_sha = _base_repo(tmp_path)
    _write(repo, "evals/commit/checks.manifest", "gated.one A description\n")
    _commit(repo, "drop a gated id only")

    results = check(GuardContext(base=base_sha, repo_root=repo))

    assert results == []


def test_no_fail_on_an_empty_diff(tmp_path):
    repo, base_sha = _base_repo(tmp_path)

    results = check(GuardContext(base=base_sha, repo_root=repo))

    assert results == []


def test_skips_a_skill_with_no_deps_file(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "evals/tdd/checks.manifest", "gated.one A description\n")
    base_sha = _commit(repo, "base")
    _write(repo, "evals/tdd/checks.manifest", "")
    _commit(repo, "drop the only gated id, no deps file present")

    results = check(GuardContext(base=base_sha, repo_root=repo))

    assert results == []


def _diverged_repo(tmp_path: Path) -> tuple[Path, str]:
    """Fork at F; base branch moves on; the PR branch changes only an unrelated file.

    Returns (repo, base_branch_name) with HEAD checked out on the PR branch.
    The base branch TIP differs from the merge-base in exactly the ways every
    guard here reads: it adds gated id ``y``, adds retired entry ``z``, and
    edits a direct-tier file. A guard that reads the TIP of base instead of
    the merge-base sees all of that as the PR removing/editing it.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "evals/commit/checks.manifest", "x A description\n")
    _write(repo, "evals/commit/retired.md", "")
    _write(repo, "evals/commit/marker.txt", "original\n")
    _write(repo, "evals/commit/deps", 'direct = ["evals/commit/marker.txt"]\ninjection = []\n')
    _commit(repo, "fork point")
    base_branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")

    _git(repo, "checkout", "-q", "-b", "pr")
    _write(repo, "unrelated.txt", "pr change\n")
    _commit(repo, "pr: unrelated change")

    _git(repo, "checkout", "-q", base_branch)
    _write(repo, "evals/commit/checks.manifest", "x A description\ny B description\n")
    _write(
        repo,
        "evals/commit/retired.md",
        "## z\n- date: 2026-01-01\n- reason: noise\n- evidence: flaked repeatedly\n",
    )
    _write(repo, "evals/commit/marker.txt", "base moved on\n")
    _commit(repo, "base moves on after the fork")

    _git(repo, "checkout", "-q", "pr")
    return repo, base_branch


def test_reads_base_content_at_the_merge_base_not_the_base_tip(tmp_path):
    repo, base_branch = _diverged_repo(tmp_path)

    results = check(GuardContext(base=base_branch, repo_root=repo))

    assert results == []


def test_fails_loudly_when_the_base_ref_cannot_be_resolved(tmp_path):
    repo, _base_branch = _diverged_repo(tmp_path)

    with pytest.raises(subprocess.CalledProcessError):
        check(GuardContext(base="no-such-ref", repo_root=repo))


def _forked_repo(tmp_path: Path) -> tuple[Path, str]:
    """A fork point with gated ids x and y and a direct-tier marker, on the base branch."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "evals/commit/checks.manifest", "x A description\ny B description\n")
    _write(repo, "evals/commit/marker.txt", "original\n")
    _write(repo, "evals/commit/deps", 'direct = ["evals/commit/marker.txt"]\ninjection = []\n')
    _commit(repo, "fork point")
    return repo, _git(repo, "rev-parse", "--abbrev-ref", "HEAD")


def test_ok_when_the_pr_retires_an_id_and_only_the_base_branch_moved_the_tier(tmp_path):
    # The tier hash at the base TIP differs from the PR's, but the PR itself did
    # not touch the tier -- so removing y here is not a demotion.
    repo, base_branch = _forked_repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "pr")
    _write(repo, "evals/commit/checks.manifest", "x A description\n")
    _commit(repo, "pr: retire y")
    _git(repo, "checkout", "-q", base_branch)
    _write(repo, "evals/commit/marker.txt", "base moved the tier\n")
    _commit(repo, "base: edit the tier")
    _git(repo, "checkout", "-q", "pr")

    results = check(GuardContext(base=base_branch, repo_root=repo))

    assert results == []


def test_ok_when_the_pr_edits_the_tier_and_the_base_branch_independently_added_an_id(tmp_path):
    # The base TIP manifest has z, which the PR's manifest lacks -- but the PR
    # never had z, so it did not remove anything.
    repo, base_branch = _forked_repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "pr")
    _write(repo, "evals/commit/marker.txt", "pr edits the tier\n")
    _commit(repo, "pr: edit the tier")
    _git(repo, "checkout", "-q", base_branch)
    _write(repo, "evals/commit/checks.manifest", "x A description\ny B description\nz C description\n")
    _commit(repo, "base: add z")
    _git(repo, "checkout", "-q", "pr")

    results = check(GuardContext(base=base_branch, repo_root=repo))

    assert results == []
