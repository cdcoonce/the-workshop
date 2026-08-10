"""Sync Manager — handles git pull/push with conflict detection.

Public interface:
    pull(vault_path) → SyncResult
    push(vault_path, message, pre_push_check) → SyncResult
"""

from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

@dataclass
class SyncResult:
    """Result of a git sync operation."""
    success: bool
    message: str
    conflicts: list[str] = field(default_factory=list)  # conflicting file paths


class GitCommandError(Exception):
    """Raised by _has_remote/_has_changes when the underlying git command fails."""

    def __init__(self, cmd: str, stderr: str) -> None:
        self.cmd = cmd
        self.stderr = stderr
        super().__init__(f"git {cmd} failed: {stderr}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Only one pull may run at a time per repo: `git pull` fetches into FETCH_HEAD and
# then re-reads it for the rebase phase, so a concurrent fetch (a second session's
# hook, the editor's git integration) that rewrites FETCH_HEAD between those two
# phases produces "fatal: Cannot rebase onto multiple branches". Naming the remote
# and branch narrows the window but does not close it.
_LOCK_FILENAME = "vault-sync.lock"
_LOCK_STALE_SECONDS = 120  # a healthy pull holds the lock well under this (25s git timeout + one retry)
_FETCH_HEAD_RACE_ERR = "cannot rebase onto multiple branches"
_RETRY_DELAY_SECONDS = 1.0


def _run_git(args: list[str], cwd: Path, timeout: int = 25) -> subprocess.CompletedProcess[str]:
    """Run a git command and return the result."""
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def _git_dir(cwd: Path) -> Path | None:
    """Resolve the repo's git directory without shelling out.

    Handles both a normal repo (``.git`` is a directory) and a linked worktree
    (``.git`` is a file containing ``gitdir: <path>``, relative paths resolved
    against the directory holding the file). Returns None outside a repo — the
    caller then proceeds without locking.
    """
    dot_git = cwd / ".git"
    if dot_git.is_dir():
        return dot_git
    if dot_git.is_file():
        try:
            text = dot_git.read_text().strip()
        except OSError:
            return None
        if text.startswith("gitdir:"):
            gitdir = Path(text.split(":", 1)[1].strip())
            return gitdir if gitdir.is_absolute() else (cwd / gitdir)
    return None


def _try_lock(lock_path: Path) -> bool | None:
    """Try to take the exclusive sync lock via O_CREAT|O_EXCL.

    Returns True if acquired (caller must release), False if another sync holds
    a fresh lock, None if locking is unavailable (e.g. unwritable git dir) — in
    which case the caller proceeds unlocked rather than silently never pulling.
    A lock older than _LOCK_STALE_SECONDS is from a crashed holder: break it and
    retry once.
    """
    for _ in range(2):
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                age = time.time() - lock_path.stat().st_mtime
            except OSError:
                continue  # holder released between open and stat — retry acquisition
            if age < _LOCK_STALE_SECONDS:
                return False
            try:
                lock_path.unlink()
            except OSError:
                return False  # another process is breaking the stale lock — let it win
            continue
        except OSError:
            return None
        try:
            os.write(fd, f"{os.getpid()}\n".encode())
        finally:
            os.close(fd)
        return True
    return False


def _has_remote(cwd: Path) -> bool:
    """Check if the repo has a remote configured."""
    result = _run_git(["remote"], cwd)
    if result.returncode != 0:
        raise GitCommandError("remote", result.stderr)
    return result.stdout.strip() != ""


def _has_changes(cwd: Path) -> bool:
    """Check if there are any uncommitted changes."""
    result = _run_git(["status", "--porcelain"], cwd)
    if result.returncode != 0:
        raise GitCommandError("status", result.stderr)
    return result.stdout.strip() != ""


def _parse_conflict_files(output: str) -> list[str]:
    """Extract conflicting file paths from git output — only when a path can be isolated confidently.

    Vault paths contain spaces (e.g. ``brain/North Star.md``), so token-splitting is unreliable; we
    only parse the two forms where the path is unambiguously delimited, and DROP anything else rather
    than surface git's free-text description as a fake filename (the count-based message still reports
    the conflict). Never auto-resolve; reporting must be accurate.
    """
    conflicts = []
    for line in output.splitlines():
        if "CONFLICT" not in line:
            continue
        if "Merge conflict in " in line:
            # content / add-add: "CONFLICT (...): Merge conflict in <path>"
            conflicts.append(line.split("Merge conflict in ", 1)[1].strip())
        elif "modify/delete" in line and ": " in line and " deleted in " in line:
            # "CONFLICT (modify/delete): <path> deleted in HEAD and modified in <branch>"
            conflicts.append(line.split(": ", 1)[1].split(" deleted in ", 1)[0].strip())
        # other types (rename/rename, rename/delete, …): no confidently-isolable path → drop.
    return conflicts


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def pull(vault_path: str | Path) -> SyncResult:
    """Pull latest changes from remote with rebase.

    If a conflict occurs, aborts the rebase and returns the conflict list.
    Never auto-resolves conflicts.

    Concurrent-safe: takes an exclusive lockfile in the git dir so simultaneous
    invocations (two sessions starting together both run the SessionStart hook)
    don't race each other on FETCH_HEAD; a locked-out caller skips with success.
    Fetches we don't own (editor git integration) can still rewrite FETCH_HEAD
    mid-pull, so the specific race error gets one delayed retry.

    Args:
        vault_path: Path to the vault root directory.

    Returns:
        SyncResult with success status, message, and any conflict file paths.
    """
    cwd = Path(vault_path)

    # Check if remote exists
    try:
        has_remote = _has_remote(cwd)
    except GitCommandError as e:
        return SyncResult(success=False, message=f"Git {e.cmd} failed: {e.stderr}")
    except subprocess.TimeoutExpired:
        return SyncResult(success=False, message="Git pull timed out after 25 seconds.")
    except FileNotFoundError:
        return SyncResult(success=False, message="Git is not installed or not on PATH.")
    if not has_remote:
        return SyncResult(success=True, message="No remote configured — skipping pull.")

    lock_path = None
    git_dir = _git_dir(cwd)
    if git_dir is not None:
        lock_path = git_dir / _LOCK_FILENAME
        acquired = _try_lock(lock_path)
        if acquired is False:
            # A concurrent sync is already pulling for us — skipping is success.
            return SyncResult(success=True, message="Another sync in progress — skipping pull.")
        if acquired is None:
            lock_path = None  # locking unavailable; proceed unlocked (retry below still guards)

    try:
        # Resolve the current branch and pull from origin explicitly, so the
        # fetch phase only writes the one branch we intend to rebase onto.
        branch_result = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd)
        branch = branch_result.stdout.strip()
        # --autostash: the vault is edited continuously and its auto-commit runs
        # at Stop, so SessionStart routinely fires with a dirty working tree.
        # Without this, git refuses outright ("cannot pull with rebase: You have
        # unstaged changes") and the vault silently stops syncing until someone
        # notices. Git stashes, rebases, and restores in one step; on conflict
        # the abort below restores the pre-pull state.
        base_args = ["pull", "--rebase", "--autostash"]
        pull_args = [*base_args, "origin", branch] if branch and branch != "HEAD" else base_args

        try:
            result = _run_git(pull_args, cwd)
            if result.returncode != 0 and _FETCH_HEAD_RACE_ERR in result.stderr.lower():
                # A fetch we don't control rewrote FETCH_HEAD between this pull's
                # fetch and rebase phases. The error fires before the rebase
                # starts (nothing to abort) — wait out the racer and retry once.
                time.sleep(_RETRY_DELAY_SECONDS)
                result = _run_git(pull_args, cwd)
        except subprocess.TimeoutExpired:
            return SyncResult(success=False, message="Git pull timed out after 25 seconds.")
        except FileNotFoundError:
            return SyncResult(success=False, message="Git is not installed or not on PATH.")

        if result.returncode == 0:
            stdout = result.stdout.strip()
            if "Already up to date" in stdout:
                return SyncResult(success=True, message="Already up to date.")
            return SyncResult(success=True, message=f"Pulled successfully.\n{stdout}")

        # Pull failed — likely conflict
        all_output = f"{result.stdout}\n{result.stderr}"
        conflicts = _parse_conflict_files(all_output)

        # Abort the rebase to return to clean state
        abort_result = _run_git(["rebase", "--abort"], cwd)
        abort_failed = abort_result.returncode != 0

        if conflicts:
            message = (
                f"Merge conflict in {len(conflicts)} file(s). "
                + (
                    f"Repo left mid-rebase: {abort_result.stderr.strip()}"
                    if abort_failed
                    else "Rebase aborted."
                )
            )
            return SyncResult(
                success=False,
                message=message,
                conflicts=conflicts,
            )

        message = f"Pull failed: {result.stderr.strip()}"
        if abort_failed:
            message += f"\nRepo left mid-rebase: {abort_result.stderr.strip()}"
        return SyncResult(
            success=False,
            message=message,
        )
    finally:
        if lock_path is not None:
            lock_path.unlink(missing_ok=True)


def push(
    vault_path: str | Path,
    message: str = "vault: auto-sync session changes",
    pre_push_check: Callable[[Path], tuple[bool, str]] | None = None,
) -> SyncResult:
    """Stage all changes, commit, and push to remote.

    Args:
        vault_path: Path to the vault root directory.
        message: Commit message.
        pre_push_check: Optional gate run after commit, before pull/push. Takes
            the repo path and returns ``(ok, detail)``; a caller-supplied check
            (e.g. a vault-health gate) so this module stays generic — most
            consumers of this vendored engine have no such check to run. On
            failure the commit is kept locally (never lost) and the push is
            skipped, leaving a human to fix and re-sync rather than shipping a
            regression straight to the shared remote.

    Returns:
        SyncResult with success status and message.
    """
    cwd = Path(vault_path)

    # Check if remote exists
    try:
        has_remote = _has_remote(cwd)
    except GitCommandError as e:
        return SyncResult(success=False, message=f"Git {e.cmd} failed: {e.stderr}")
    except subprocess.TimeoutExpired:
        return SyncResult(success=False, message="Git operation timed out.")
    except FileNotFoundError:
        return SyncResult(success=False, message="Git is not installed or not on PATH.")
    if not has_remote:
        return SyncResult(success=True, message="No remote configured — skipping push.")

    # Check for changes
    try:
        has_changes = _has_changes(cwd)
    except GitCommandError as e:
        return SyncResult(success=False, message=f"Git {e.cmd} failed: {e.stderr}")
    except subprocess.TimeoutExpired:
        return SyncResult(success=False, message="Git operation timed out.")
    except FileNotFoundError:
        return SyncResult(success=False, message="Git is not installed or not on PATH.")
    if not has_changes:
        return SyncResult(success=True, message="No changes to commit.")

    # Stage all changes
    try:
        result = _run_git(["add", "."], cwd)
        if result.returncode != 0:
            return SyncResult(success=False, message=f"Git add failed: {result.stderr.strip()}")

        # Commit
        result = _run_git(["commit", "-m", message], cwd)
        if result.returncode != 0:
            return SyncResult(success=False, message=f"Git commit failed: {result.stderr.strip()}")

        # Gate the push (not the commit) on the caller's check — the commit above already
        # happened, so a regression is captured locally rather than lost, but never reaches
        # the shared remote unvetted.
        if pre_push_check is not None:
            check_ok, check_detail = pre_push_check(cwd)
            if not check_ok:
                return SyncResult(
                    success=False,
                    message=(
                        "Pre-push check failed — commit kept locally, push skipped.\n"
                        f"{check_detail}"
                    ),
                )

        # Rebase-pull before pushing — integrate the other machine's commits first
        # (the vault syncs across two machines; CLAUDE.md requires rebase-first). Never
        # auto-resolve: if the rebase conflicts (or otherwise fails), return that result
        # and do NOT push, leaving the local commit for a human to reconcile.
        pull_result = pull(cwd)
        if not pull_result.success:
            return pull_result

        # Push — resolve the current branch and set upstream so this works on
        # any branch, not just main. A bare `git push` fails on a fresh feature
        # branch with "no upstream branch"; `push -u origin <branch>` sets the
        # upstream on first push and is a harmless no-op once it's tracking.
        # Mirrors the branch-aware resolution already used by pull().
        branch_result = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd)
        branch = branch_result.stdout.strip()
        push_args = ["push", "-u", "origin", branch] if branch and branch != "HEAD" else ["push"]
        result = _run_git(push_args, cwd)
        if result.returncode != 0:
            return SyncResult(
                success=False,
                message=f"Git push failed: {result.stderr.strip()}\nTry pulling first.",
            )

        return SyncResult(success=True, message="Changes committed and pushed.")

    except subprocess.TimeoutExpired:
        return SyncResult(success=False, message="Git operation timed out.")
    except FileNotFoundError:
        return SyncResult(success=False, message="Git is not installed or not on PATH.")
