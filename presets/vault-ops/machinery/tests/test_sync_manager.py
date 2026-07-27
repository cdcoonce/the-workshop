"""Tests for the sync manager — git pull/push with conflict handling."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import call, patch

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(SCRIPTS_DIR))

import sync_manager as sm  # module alias for the integration tests below
from sync_manager import SyncResult, pull, push


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_result(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=["git"], returncode=returncode, stdout=stdout, stderr=stderr)


# ---------------------------------------------------------------------------
# Pull tests
# ---------------------------------------------------------------------------

class TestPull:
    @patch("sync_manager._run_git")
    def test_pull_success(self, mock_git, tmp_path: Path) -> None:
        mock_git.side_effect = [
            _make_result(stdout="origin"),  # remote check
            _make_result(stdout="main"),  # rev-parse --abbrev-ref HEAD
            _make_result(stdout="Updating abc..def\nFast-forward"),  # pull
        ]
        result = pull(tmp_path)
        assert result.success is True
        assert "Pulled" in result.message

    @patch("sync_manager._run_git")
    def test_pull_already_up_to_date(self, mock_git, tmp_path: Path) -> None:
        mock_git.side_effect = [
            _make_result(stdout="origin"),  # remote
            _make_result(stdout="main"),  # rev-parse --abbrev-ref HEAD
            _make_result(stdout="Already up to date."),  # pull
        ]
        result = pull(tmp_path)
        assert result.success is True
        assert "up to date" in result.message.lower()

    @patch("sync_manager._run_git")
    def test_pull_no_remote(self, mock_git, tmp_path: Path) -> None:
        mock_git.return_value = _make_result(stdout="")  # no remote
        result = pull(tmp_path)
        assert result.success is True
        assert "No remote" in result.message

    @patch("sync_manager._run_git")
    def test_pull_autostashes_local_edits(self, mock_git, tmp_path: Path) -> None:
        """A dirty working tree must not turn a routine sync into a hard failure.

        The vault is edited continuously and its auto-commit runs at Stop, so
        SessionStart routinely fires while files are uncommitted. Without
        --autostash git refuses outright ("cannot pull with rebase: You have
        unstaged changes") and the vault silently stops syncing.
        """
        mock_git.side_effect = [
            _make_result(stdout="origin"),  # remote
            _make_result(stdout="main"),  # rev-parse --abbrev-ref HEAD
            _make_result(stdout="Already up to date."),  # pull
        ]

        result = pull(tmp_path)

        assert result.success is True
        pull_call = [c for c in mock_git.call_args_list if c.args[0][0] == "pull"][0]
        assert "--autostash" in pull_call.args[0]

    @patch("sync_manager._run_git")
    def test_pull_conflict(self, mock_git, tmp_path: Path) -> None:
        mock_git.side_effect = [
            _make_result(stdout="origin"),  # remote
            _make_result(stdout="main"),  # rev-parse --abbrev-ref HEAD
            _make_result(  # pull --rebase with conflict
                returncode=1,
                stdout="CONFLICT (content): Merge conflict in brain/North Star.md",
                stderr="error: could not apply",
            ),
            _make_result(),  # rebase --abort
        ]
        result = pull(tmp_path)
        assert result.success is False
        assert len(result.conflicts) == 1
        assert "North Star.md" in result.conflicts[0]

    @patch("sync_manager._run_git")
    def test_pull_conflict_aborts_rebase(self, mock_git, tmp_path: Path) -> None:
        mock_git.side_effect = [
            _make_result(stdout="origin"),
            _make_result(stdout="main"),  # rev-parse --abbrev-ref HEAD
            _make_result(returncode=1, stdout="CONFLICT (content): Merge conflict in test.md"),
            _make_result(),  # rebase --abort
        ]
        pull(tmp_path)
        # Verify rebase --abort was called (now the 4th git call: remote, rev-parse, pull, abort)
        abort_call = mock_git.call_args_list[3]
        assert "abort" in str(abort_call)

    @patch("sync_manager._run_git")
    def test_pull_generic_failure(self, mock_git, tmp_path: Path) -> None:
        mock_git.side_effect = [
            _make_result(stdout="origin"),
            _make_result(stdout="main"),  # rev-parse --abbrev-ref HEAD
            _make_result(returncode=1, stderr="fatal: authentication failed"),
            _make_result(),  # rebase --abort (still called)
        ]
        result = pull(tmp_path)
        assert result.success is False
        assert "authentication" in result.message.lower()

    @patch("sync_manager._run_git")
    def test_pull_timeout(self, mock_git, tmp_path: Path) -> None:
        mock_git.side_effect = [
            _make_result(stdout="origin"),
            _make_result(stdout="main"),  # rev-parse --abbrev-ref HEAD
            subprocess.TimeoutExpired("git", 25),
        ]
        result = pull(tmp_path)
        assert result.success is False
        assert "timed out" in result.message.lower()

    @patch("sync_manager._run_git")
    def test_pull_git_not_found(self, mock_git, tmp_path: Path) -> None:
        mock_git.side_effect = [
            _make_result(stdout="origin"),
            _make_result(stdout="main"),  # rev-parse --abbrev-ref HEAD
            FileNotFoundError("git not found"),
        ]
        result = pull(tmp_path)
        assert result.success is False
        assert "not installed" in result.message.lower() or "not on PATH" in result.message.lower()


# ---------------------------------------------------------------------------
# Pull locking tests — concurrent invocations must not race on FETCH_HEAD
# ---------------------------------------------------------------------------

class TestPullLocking:
    @patch("sync_manager._run_git")
    def test_pull_skips_when_locked(self, mock_git, tmp_path: Path) -> None:
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        lock = git_dir / "vault-sync.lock"
        lock.write_text("12345\n")
        mock_git.return_value = _make_result(stdout="origin")
        result = pull(tmp_path)
        assert result.success is True  # skipping while another sync runs is success
        assert "in progress" in result.message.lower()
        assert lock.exists()  # the other sync's lock is left alone
        assert mock_git.call_count == 1  # only the remote check — no pull attempted

    @patch("sync_manager._run_git")
    def test_pull_acquires_and_releases_lock(self, mock_git, tmp_path: Path) -> None:
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        mock_git.side_effect = [
            _make_result(stdout="origin"),
            _make_result(stdout="main"),
            _make_result(stdout="Already up to date."),
        ]
        result = pull(tmp_path)
        assert result.success is True
        assert not (git_dir / "vault-sync.lock").exists()

    @patch("sync_manager._run_git")
    def test_pull_breaks_stale_lock(self, mock_git, tmp_path: Path) -> None:
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        lock = git_dir / "vault-sync.lock"
        lock.write_text("999\n")
        stale = time.time() - sm._LOCK_STALE_SECONDS - 60
        os.utime(lock, (stale, stale))
        mock_git.side_effect = [
            _make_result(stdout="origin"),
            _make_result(stdout="main"),
            _make_result(stdout="Already up to date."),
        ]
        result = pull(tmp_path)
        assert result.success is True
        assert "up to date" in result.message.lower()  # pull ran — stale lock was broken
        assert not lock.exists()

    @patch("sync_manager._run_git")
    def test_pull_releases_lock_on_failure(self, mock_git, tmp_path: Path) -> None:
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        mock_git.side_effect = [
            _make_result(stdout="origin"),
            _make_result(stdout="main"),
            subprocess.TimeoutExpired("git", 25),
        ]
        result = pull(tmp_path)
        assert result.success is False
        assert not (git_dir / "vault-sync.lock").exists()

    def test_git_dir_resolves_worktree_gitfile(self, tmp_path: Path) -> None:
        real = tmp_path / "repo" / ".git" / "worktrees" / "wt"
        real.mkdir(parents=True)
        wt = tmp_path / "wt"
        wt.mkdir()
        (wt / ".git").write_text(f"gitdir: {real}\n")
        assert sm._git_dir(wt) == real

    def test_git_dir_resolves_relative_gitfile(self, tmp_path: Path) -> None:
        real = tmp_path / "gitdir"
        real.mkdir()
        wt = tmp_path / "wt"
        wt.mkdir()
        (wt / ".git").write_text("gitdir: ../gitdir\n")
        assert sm._git_dir(wt) == wt / ".." / "gitdir"

    def test_git_dir_none_outside_repo(self, tmp_path: Path) -> None:
        assert sm._git_dir(tmp_path) is None

    def test_try_lock_second_caller_loses(self, tmp_path: Path) -> None:
        lock = tmp_path / "vault-sync.lock"
        assert sm._try_lock(lock) is True
        assert sm._try_lock(lock) is False  # fresh lock held by the first caller
        lock.unlink()


# ---------------------------------------------------------------------------
# Pull retry tests — FETCH_HEAD rewritten by a fetch we don't control
# ---------------------------------------------------------------------------

class TestPullRetry:
    @patch("sync_manager.time.sleep")
    @patch("sync_manager._run_git")
    def test_pull_retries_once_on_fetch_head_race(self, mock_git, mock_sleep, tmp_path: Path) -> None:
        mock_git.side_effect = [
            _make_result(stdout="origin"),
            _make_result(stdout="main"),
            _make_result(returncode=128, stderr="fatal: Cannot rebase onto multiple branches."),
            _make_result(stdout="Updating abc..def\nFast-forward"),  # retry succeeds
        ]
        result = pull(tmp_path)
        assert result.success is True
        assert "Pulled" in result.message
        mock_sleep.assert_called_once()
        pull_calls = [c for c in mock_git.call_args_list if "pull" in c.args[0]]
        assert len(pull_calls) == 2

    @patch("sync_manager.time.sleep")
    @patch("sync_manager._run_git")
    def test_pull_retry_exhausted_reports_failure(self, mock_git, mock_sleep, tmp_path: Path) -> None:
        mock_git.side_effect = [
            _make_result(stdout="origin"),
            _make_result(stdout="main"),
            _make_result(returncode=128, stderr="fatal: Cannot rebase onto multiple branches."),
            _make_result(returncode=128, stderr="fatal: Cannot rebase onto multiple branches."),
            _make_result(),  # rebase --abort
        ]
        result = pull(tmp_path)
        assert result.success is False
        assert "multiple branches" in result.message.lower()
        mock_sleep.assert_called_once()  # retried exactly once, not in a loop

    @patch("sync_manager.time.sleep")
    @patch("sync_manager._run_git")
    def test_pull_does_not_retry_other_failures(self, mock_git, mock_sleep, tmp_path: Path) -> None:
        mock_git.side_effect = [
            _make_result(stdout="origin"),
            _make_result(stdout="main"),
            _make_result(returncode=1, stderr="fatal: authentication failed"),
            _make_result(),  # rebase --abort
        ]
        result = pull(tmp_path)
        assert result.success is False
        mock_sleep.assert_not_called()
        assert mock_git.call_count == 4


# ---------------------------------------------------------------------------
# Push tests
# ---------------------------------------------------------------------------

class TestPush:
    @patch("sync_manager._has_changes", return_value=True)
    @patch("sync_manager._has_remote", return_value=True)
    @patch("sync_manager._run_git")
    def test_push_success(self, mock_git, _remote, _changes, tmp_path: Path) -> None:
        mock_git.return_value = _make_result()  # all succeed
        result = push(tmp_path)
        assert result.success is True
        assert "committed" in result.message.lower() or "pushed" in result.message.lower()

    @patch("sync_manager._has_changes", return_value=False)
    @patch("sync_manager._has_remote", return_value=True)
    def test_push_no_changes(self, _remote, _changes, tmp_path: Path) -> None:
        result = push(tmp_path)
        assert result.success is True
        assert "No changes" in result.message

    @patch("sync_manager._has_remote", return_value=False)
    def test_push_no_remote(self, _remote, tmp_path: Path) -> None:
        result = push(tmp_path)
        assert result.success is True
        assert "No remote" in result.message

    @patch("sync_manager._has_changes", return_value=True)
    @patch("sync_manager._has_remote", return_value=True)
    @patch("sync_manager._run_git")
    def test_push_commit_fails(self, mock_git, _remote, _changes, tmp_path: Path) -> None:
        mock_git.side_effect = [
            _make_result(),  # add succeeds
            _make_result(returncode=1, stderr="nothing to commit"),  # commit fails
        ]
        result = push(tmp_path)
        assert result.success is False

    @patch("sync_manager._has_changes", return_value=True)
    @patch("sync_manager._has_remote", return_value=True)
    @patch("sync_manager._run_git")
    def test_push_push_fails(self, mock_git, _remote, _changes, tmp_path: Path) -> None:
        mock_git.side_effect = [
            _make_result(),  # add
            _make_result(),  # commit
            # push() now rebase-pulls before pushing (#47): pull() runs rev-parse + pull --rebase
            _make_result(stdout="main"),  # pull(): rev-parse --abbrev-ref HEAD
            _make_result(stdout="Already up to date."),  # pull(): pull --rebase (succeeds)
            _make_result(stdout="main"),  # push: rev-parse --abbrev-ref HEAD
            _make_result(returncode=1, stderr="rejected: non-fast-forward"),  # push (fails)
        ]
        result = push(tmp_path)
        assert result.success is False
        assert "pull" in result.message.lower()

    @patch("sync_manager._has_changes", return_value=True)
    @patch("sync_manager._has_remote", return_value=True)
    @patch("sync_manager._run_git")
    def test_push_uses_custom_message(self, mock_git, _remote, _changes, tmp_path: Path) -> None:
        mock_git.return_value = _make_result()
        push(tmp_path, message="custom: test message")
        # Check commit was called with custom message
        commit_call = mock_git.call_args_list[1]  # second call is commit
        assert "custom: test message" in str(commit_call)

    @patch("sync_manager._has_changes", return_value=True)
    @patch("sync_manager._has_remote", return_value=True)
    @patch("sync_manager._run_git")
    def test_push_pre_push_check_blocks_push_but_keeps_commit(
        self, mock_git, _remote, _changes, tmp_path: Path
    ) -> None:
        """A failing gate must stop the push without undoing the local commit.

        The commit already happened by the time the gate runs — a regression
        (e.g. a broken wikilink) is captured locally, never lost, but must not
        reach the shared remote unvetted.
        """
        mock_git.side_effect = [
            _make_result(),  # add
            _make_result(),  # commit
        ]
        check = lambda cwd: (False, "max_unresolved_links: 1 exceeds limit 0")  # noqa: E731
        result = push(tmp_path, pre_push_check=check)
        assert result.success is False
        assert "commit kept locally" in result.message.lower()
        assert "max_unresolved_links" in result.message
        # Only add + commit ran — no pull, no push attempted.
        assert mock_git.call_count == 2

    @patch("sync_manager._has_changes", return_value=True)
    @patch("sync_manager._has_remote", return_value=True)
    @patch("sync_manager._run_git")
    def test_push_pre_push_check_passing_still_pushes(
        self, mock_git, _remote, _changes, tmp_path: Path
    ) -> None:
        mock_git.return_value = _make_result(stdout="main")
        check = lambda cwd: (True, "")  # noqa: E731
        result = push(tmp_path, pre_push_check=check)
        assert result.success is True
        assert "pushed" in result.message.lower() or "committed" in result.message.lower()

    @patch("sync_manager._has_changes", return_value=True)
    @patch("sync_manager._has_remote", return_value=True)
    @patch("sync_manager._run_git")
    def test_push_receives_repo_path_in_pre_push_check(
        self, mock_git, _remote, _changes, tmp_path: Path
    ) -> None:
        mock_git.return_value = _make_result(stdout="main")
        seen = []
        push(tmp_path, pre_push_check=lambda cwd: (seen.append(cwd) or True, ""))
        assert seen == [Path(tmp_path)]


# ---------------------------------------------------------------------------
# Integration tests — real git (bare remote + two clones). These exercise the
# rebase-first-push path (#47) and conflict reporting (#55) against actual git,
# complementing the mock-based unit tests above.
# ---------------------------------------------------------------------------

def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _setup(tmp_path):
    """A bare remote + two clones (A, B) sharing an initial commit on main."""
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "--initial-branch=main", str(remote)],
                   check=True, capture_output=True, text=True)
    a = tmp_path / "A"
    subprocess.run(["git", "clone", str(remote), str(a)], check=True, capture_output=True, text=True)
    _git(a, "config", "user.email", "t@t.t")
    _git(a, "config", "user.name", "t")
    (a / "seed.md").write_text("seed\n")
    _git(a, "add", ".")
    _git(a, "commit", "-m", "seed")
    _git(a, "branch", "-M", "main")
    _git(a, "push", "-u", "origin", "main")
    b = tmp_path / "B"
    subprocess.run(["git", "clone", str(remote), str(b)], check=True, capture_output=True, text=True)
    _git(b, "config", "user.email", "t@t.t")
    _git(b, "config", "user.name", "t")
    return a, b


def test_push_rebase_pulls_before_pushing(tmp_path):
    # Remote advances (B) with a NON-conflicting file while A has local changes.
    a, b = _setup(tmp_path)
    (b / "from_b.md").write_text("b\n")
    _git(b, "add", ".")
    _git(b, "commit", "-m", "b")
    _git(b, "push", "origin", "main")

    (a / "from_a.md").write_text("a\n")  # A's local (uncommitted) change
    res = sm.push(str(a))

    assert res.success, res.message               # would FAIL (non-fast-forward) without rebase-first
    assert (a / "from_b.md").exists()             # B's commit was integrated into A (rebase happened)
    _git(b, "pull", "--rebase", "origin", "main")
    assert (b / "from_a.md").exists()             # A's change reached the remote


def test_push_returns_conflict_and_does_not_push(tmp_path):
    # Remote (B) and A edit the SAME line → rebase conflict.
    a, b = _setup(tmp_path)
    (b / "seed.md").write_text("b version\n")
    _git(b, "add", ".")
    _git(b, "commit", "-m", "b edit")
    _git(b, "push", "origin", "main")

    (a / "seed.md").write_text("a version\n")
    res = sm.push(str(a))

    assert not res.success
    assert res.conflicts                          # reports the conflict (not just "try pulling")
    _git(b, "pull", "--rebase", "origin", "main")
    assert (b / "seed.md").read_text() == "b version\n"  # A's change was NOT pushed


# --- _parse_conflict_files: never surface free-text as a path (#55) ---

def test_parse_conflict_content_keeps_full_path_with_spaces():
    out = "CONFLICT (content): Merge conflict in brain/North Star.md"
    assert sm._parse_conflict_files(out) == ["brain/North Star.md"]


def test_parse_conflict_modify_delete_extracts_path_not_freetext():
    out = "CONFLICT (modify/delete): brain/X.md deleted in HEAD and modified in feat-branch."
    assert sm._parse_conflict_files(out) == ["brain/X.md"]


def test_parse_conflict_unparseable_type_is_dropped():
    out = "CONFLICT (rename/rename): some free-text description with no clean path"
    assert sm._parse_conflict_files(out) == []  # drop rather than emit garbage


def test_parse_conflict_ignores_non_conflict_lines():
    assert sm._parse_conflict_files("Auto-merging brain/A.md\nunrelated: line") == []
