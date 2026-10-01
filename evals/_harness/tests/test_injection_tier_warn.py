"""Tests for evals._harness.guards.injection_tier_warn.

The nine watched paths are duplicated here as a literal tuple rather than
imported from the guard module: parametrizing directly off the guard's own
``_WATCHED_PATHS`` would make a mutation that shrinks that tuple invisible
to pytest's collection (the removed path's case would simply never be
collected, and the run would look green rather than red).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from evals._harness.guards import GuardContext
from evals._harness.guards.injection_tier_warn import check

_EXPECTED_WATCHED_PATHS = (
    "plugins/workbench/hooks/hooks.json",
    "plugins/workbench/hooks/run-hook.sh",
    "plugins/workbench/hooks/run-vault-hook.sh",
    "plugins/workbench/hooks/scripts/inject-skill-router.py",
    "plugins/workbench/hooks/scripts/vault-session-start.py",
    "plugins/workbench/hooks/scripts/snapshot-subagent-start.py",
    "plugins/workbench/hooks/scripts/suggest-handoff-on-context.py",
    "plugins/workbench/hooks/scripts/vault-skill-alias.py",
    "plugins/workbench/skills/using-workflow/SKILL.md",
)


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
    for watched_path in _EXPECTED_WATCHED_PATHS:
        _write(repo, watched_path, "original\n")
    _write(repo, "unrelated.txt", "hello\n")
    base_sha = _commit(repo, "base")
    return repo, base_sha


def test_no_result_when_no_watched_path_changed(tmp_path):
    repo, base_sha = _base_repo(tmp_path)
    _write(repo, "unrelated.txt", "changed\n")
    _commit(repo, "unrelated change")

    results = check(GuardContext(base=base_sha, repo_root=repo))

    assert results == []


@pytest.mark.parametrize("watched_path", _EXPECTED_WATCHED_PATHS)
def test_warns_when_a_watched_path_changed(tmp_path, watched_path):
    repo, base_sha = _base_repo(tmp_path)
    _write(repo, watched_path, "changed\n")
    _commit(repo, f"change {watched_path}")

    results = check(GuardContext(base=base_sha, repo_root=repo))

    assert len(results) == 1
    assert results[0].level == "warn"
    assert results[0].guard == "injection_tier_warn"
    assert watched_path in results[0].message
