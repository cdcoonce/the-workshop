"""The sync_target.py CLI that /sync's pull and push steps read.

The resolution rule itself is exercised across every checkout shape, through
both this module and the engine's copy, by the repo-root
tests/test_sync_target_parity.py; these tests pin the command-line contract the
vault-sync command reference depends on: JSON on stdout, exit 0 resolved,
1 unresolved, 2 outside a repository.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "sync_target.py"


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_SYSTEM=os.devnull,
        GIT_AUTHOR_NAME="Test",
        GIT_AUTHOR_EMAIL="test@example.com",
        GIT_COMMITTER_NAME="Test",
        GIT_COMMITTER_EMAIL="test@example.com",
    )
    return env


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, env=_env(), check=True, capture_output=True, text=True
    ).stdout.strip()


def _run(cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT)], cwd=cwd, env=_env(), capture_output=True, text=True
    )


def _desktop_worktree(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    remote.mkdir()
    _git(remote, "init", "-q", "--bare", "-b", "main")
    local = tmp_path / "vault"
    _git(tmp_path, "clone", "-q", str(remote), str(local))
    _git(local, "symbolic-ref", "HEAD", "refs/heads/main")
    (local / "seed.md").write_text("seed\n", encoding="utf-8")
    _git(local, "add", "seed.md")
    _git(local, "commit", "-q", "-m", "seed")
    _git(local, "push", "-q", "-u", "origin", "main")
    worktree = tmp_path / "wt"
    _git(local, "worktree", "add", "-q", "-b", "claude/clever-benz", str(worktree), "main")
    return local, worktree


def test_prints_the_target_for_a_desktop_worktree(tmp_path: Path) -> None:
    _local, worktree = _desktop_worktree(tmp_path)

    result = _run(worktree)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "remote": "origin",
        "branch": "claude/clever-benz",
        "target": "main",
        "source": "remote-default",
    }


def test_unresolved_target_exits_1_with_the_reason(tmp_path: Path) -> None:
    local, worktree = _desktop_worktree(tmp_path)
    _git(local, "remote", "set-url", "origin", str(tmp_path / "gone.git"))

    result = _run(worktree)

    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert "target" not in report
    assert "ls-remote" in report["error"]


def test_outside_a_repository_is_a_usage_error(tmp_path: Path) -> None:
    result = _run(tmp_path)

    assert result.returncode == 2
    assert "not inside a git repository" in result.stderr
