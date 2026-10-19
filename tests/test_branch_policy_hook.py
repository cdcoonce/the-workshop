"""Tests for the branch-policy PreToolUse Bash hook (#542).

Drives the hook as a real subprocess against scratch git repos. The repo opts in
through `.afk/config.toml`'s `trunk_branch` (the same key warn-off-trunk reads),
which names the integration branch; a repo without it gets nothing.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_PATH = REPO_ROOT / "plugins" / "workbench" / "hooks" / "scripts" / "branch-policy.py"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def make_repo(tmp_path: Path, trunk: str | None = "dev", branch: str = "dev") -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", f"--initial-branch={branch}")
    _git(repo, "config", "user.email", "t@t.t")
    _git(repo, "config", "user.name", "t")
    (repo / "f.txt").write_text("x\n")
    _git(repo, "add", "f.txt")
    _git(repo, "commit", "-q", "-m", "seed")
    if trunk is not None:
        (repo / ".afk").mkdir()
        (repo / ".afk" / "config.toml").write_text(f'trunk_branch = "{trunk}"\n')
    return repo


def run_hook(command: object, cwd: Path, tool: str = "Bash") -> subprocess.CompletedProcess[str]:
    payload = {"tool_name": tool, "tool_input": {"command": command}, "cwd": str(cwd)}
    return subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
    )


BLOCKED = [
    "git checkout -b feat/x",
    "git checkout -b feat/x main",
    "git checkout -b feat/x HEAD",
    "git switch -c feat/x",
    "git switch -c feat/x dev",
    "git switch --create feat/x",
    "git checkout -B feat/x",
    "git fetch origin && git checkout -b feat/x",
    "git -C . checkout -b feat/x",
    "FOO=1 git checkout -b feat/x",
    "gh pr create --base main --title t",
    "gh pr create -B main",
    "gh pr create --base=main",
    "gh pr create --title t --base main --body b",
    "gh pr merge 5 --base main",
]

ALLOWED = [
    "git checkout -b feat/x origin/dev",
    "git switch -c feat/x origin/dev",
    "git checkout -b feat/x --track origin/dev",
    "git checkout -b feat/x origin/main",
    "git checkout main",
    "git checkout dev",
    "git switch dev",
    "git checkout -- f.txt",
    "gh pr create --base dev --title t",
    "gh pr create --title t",
    "gh pr merge 5 --squash",
    "gh pr view 5",
    'echo "git checkout -b feat/x"',
    "git status",
    "ls -la",
    "",
]


@pytest.mark.parametrize("command", BLOCKED)
def test_policy_violation_is_blocked_with_the_correct_path(command: str, tmp_path: Path) -> None:
    repo = make_repo(tmp_path, branch="feat/other")
    result = run_hook(command, repo)

    assert result.returncode == 2, result.stderr
    assert "origin/dev" in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("command", ALLOWED)
def test_compliant_or_unrelated_command_is_allowed(command: str, tmp_path: Path) -> None:
    repo = make_repo(tmp_path, branch="feat/other")
    result = run_hook(command, repo)

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""


def test_promotion_pr_from_the_integration_branch_is_allowed(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, branch="dev")
    assert run_hook("gh pr create --base main --title promote", repo).returncode == 0


def test_promotion_pr_with_explicit_head_is_allowed(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, branch="feat/other")
    assert run_hook("gh pr create --base main --head dev", repo).returncode == 0
    assert run_hook("gh pr create --base main -H dev", repo).returncode == 0
    assert run_hook("gh pr create --base main --head feat/other", repo).returncode == 2


def test_integration_branch_comes_from_config_not_a_hardcoded_dev(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, trunk="develop", branch="feat/other")

    blocked = run_hook("git checkout -b feat/x", repo)
    assert blocked.returncode == 2 and "origin/develop" in blocked.stderr
    assert run_hook("gh pr create --base develop", repo).returncode == 0
    assert run_hook("gh pr create --base main", repo).returncode == 2


def test_repo_whose_trunk_is_main_has_nothing_to_protect(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, trunk="main", branch="feat/other")
    assert run_hook("gh pr create --base main", repo).returncode == 0


def test_repo_without_afk_config_is_not_enrolled(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, trunk=None, branch="feat/other")
    assert run_hook("git checkout -b feat/x", repo).returncode == 0
    assert run_hook("gh pr create --base main", repo).returncode == 0


def test_non_bash_tool_is_ignored(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, branch="feat/other")
    assert run_hook("git checkout -b feat/x", repo, tool="Read").returncode == 0


@pytest.mark.parametrize(
    "command", [None, 5, ["git", "checkout", "-b", "x"], {"a": 1}, "git checkout -b 'unbalanced"]
)
def test_unusable_command_fails_open(command: object, tmp_path: Path) -> None:
    repo = make_repo(tmp_path, branch="feat/other")
    result = run_hook(command, repo)

    assert result.returncode == 0, result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("payload", ["not json", "[]", "null", ""])
def test_unusable_payload_fails_open(payload: str) -> None:
    result = subprocess.run(
        [sys.executable, str(HOOK_PATH)], input=payload, capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0
    assert "Traceback" not in result.stderr


def test_non_string_cwd_fails_open(tmp_path: Path) -> None:
    payload = {"tool_input": {"command": "git checkout -b x"}, "cwd": 5}
    result = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
        cwd=tmp_path,
    )
    assert result.returncode == 0
    assert "Traceback" not in result.stderr


def test_hook_fails_open_when_the_shared_helper_is_missing(tmp_path: Path) -> None:
    import shutil

    repo = make_repo(tmp_path, branch="feat/other")
    isolated = tmp_path / "hooks"
    isolated.mkdir()
    shutil.copy2(HOOK_PATH, isolated / HOOK_PATH.name)  # deliberately without _git_baseline.py
    payload = {"tool_input": {"command": "git checkout -b x"}, "cwd": str(repo)}
    result = subprocess.run(
        [sys.executable, str(isolated / HOOK_PATH.name)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert "Traceback" not in result.stderr
