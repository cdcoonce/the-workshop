"""Tests for evals._harness.guards.demote_gated_id."""

from __future__ import annotations

import subprocess
from pathlib import Path

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
