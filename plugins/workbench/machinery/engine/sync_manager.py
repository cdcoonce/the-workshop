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
from typing import NamedTuple


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

@dataclass
class SyncResult:
    """Result of a git sync operation."""
    success: bool
    message: str
    conflicts: list[str] = field(default_factory=list)  # conflicting file paths


class SyncTarget(NamedTuple):
    """Where a checkout's session work goes: ``branch`` is the local branch
    (None when detached), ``target`` the remote branch pulls rebase onto and
    pushes land on, ``source`` the rule that chose it."""
    branch: str | None
    target: str
    source: str  # "upstream" | "same-name" | "remote-default"


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


def _rebase_in_progress(cwd: Path) -> bool:
    """Whether a rebase is still underway, read from git's own state markers.

    A pull that fails before its rebase phase (an unreachable remote, a
    missing remote branch) makes the unconditional ``rebase --abort`` fail with
    "no rebase in progress" -- which is not a repo left mid-rebase. An
    unresolvable git dir counts as in progress: this only decides whether to
    warn, and a false warning is cheaper than a missed one.
    """
    git_dir = _git_dir(cwd)
    if git_dir is None:
        return True
    return (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists()


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


_HEADS = "refs/heads/"


def _sync_target(cwd: Path, remote: str = "origin") -> SyncTarget | None:
    """The branch on ``remote`` this checkout's session work integrates into.

    HEAD's branch name is the answer only in the primary checkout on main. The
    desktop app runs vault sessions in linked worktrees on unpublished
    ``claude/*`` branches (Codex: a detached HEAD), whose names mean nothing on
    the remote. The rule, identical to the vault-sync and vault-wrap-up skills'
    ``sync_target.py`` and held to it by tests/test_sync_target_parity.py:

    1. the branch's configured upstream on ``remote`` (read from config, not
       ``@{u}``, which fails whenever the tracking ref is missing);
    2. else a same-named branch on ``remote`` (fresh ``ls-remote``);
    3. else ``remote``'s default branch (fresh ``ls-remote --symref``).

    Returns None when nothing resolves -- an unreachable remote, or one that
    names no default branch; callers then leave git to its own upstream
    handling rather than guess ``main``.
    """
    head = _run_git(["symbolic-ref", "--short", "-q", "HEAD"], cwd)
    branch = head.stdout.strip() if head.returncode == 0 else None

    if branch:
        up_remote = _run_git(["config", "--get", f"branch.{branch}.remote"], cwd).stdout.strip()
        up_merge = _run_git(["config", "--get", f"branch.{branch}.merge"], cwd).stdout.strip()
        if up_remote == remote and up_merge.startswith(_HEADS):
            return SyncTarget(branch, up_merge[len(_HEADS):], "upstream")

        ref = _HEADS + branch
        listed = _run_git(["ls-remote", "--", remote, ref], cwd)
        if listed.returncode != 0:
            return None
        if any(line.partition("\t")[2] == ref for line in listed.stdout.splitlines()):
            return SyncTarget(branch, branch, "same-name")

    symref = _run_git(["ls-remote", "--symref", "--", remote, "HEAD"], cwd)
    if symref.returncode != 0:
        return None
    for line in symref.stdout.splitlines():
        if not line.startswith("ref: "):
            continue
        name, _, what = line[len("ref: "):].partition("\t")
        if what == "HEAD" and name.startswith(_HEADS):
            return SyncTarget(branch, name[len(_HEADS):], "remote-default")
    return None


def _has_remote(cwd: Path) -> bool:
    """Check if the repo has a remote configured."""
    result = _run_git(["remote"], cwd)
    if result.returncode != 0:
        raise GitCommandError("remote", result.stderr)
    return result.stdout.strip() != ""


def _has_changes(cwd: Path) -> bool:
    """Check if there are any uncommitted changes."""
    return bool(_changed_paths(cwd))


def _changed_paths(cwd: Path) -> list[str]:
    """Return every changed path from porcelain-v1's NUL-delimited format.

    ``-z`` preserves spaces and other shell-sensitive characters verbatim. Rename
    and copy records contain a second NUL-delimited path; include both sides so
    ``git add -A -- <paths>`` stages the addition and deletion explicitly.
    """
    result = _run_git(
        ["status", "--porcelain=v1", "-z", "--untracked-files=all"], cwd
    )
    if result.returncode != 0:
        raise GitCommandError("status", result.stderr)

    records = result.stdout.split("\0")
    paths: list[str] = []
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        if len(record) < 4 or record[2] != " ":
            continue
        status = record[:2]
        paths.append(record[3:])
        if "R" in status or "C" in status:
            if index < len(records) and records[index]:
                paths.append(records[index])
            index += 1
    return list(dict.fromkeys(paths))


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
        # --autostash: the vault is edited continuously and its auto-commit runs
        # at Stop, so SessionStart routinely fires with a dirty working tree.
        # Without this, git refuses outright ("cannot pull with rebase: You have
        # unstaged changes") and the vault silently stops syncing until someone
        # notices. Git stashes, rebases, and restores in one step; on conflict
        # the abort below restores the pre-pull state.
        base_args = ["pull", "--rebase", "--autostash"]

        try:
            # Pull the sync target from origin explicitly, so the fetch phase
            # only writes the one branch we intend to rebase onto -- the
            # target, not the branch name, which in a worktree session names
            # nothing on the remote.
            sync_target = _sync_target(cwd)
            pull_args = [*base_args, "origin", sync_target.target] if sync_target else base_args
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
        abort_failed = abort_result.returncode != 0 and _rebase_in_progress(cwd)

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
        pre_push_check: Optional durability gate run before staging or committing. Takes
            the repo path and returns ``(ok, detail)``; a caller-supplied check
            (e.g. a vault-health gate) so this module stays generic — most
            consumers of this vendored engine have no such check to run. On
            failure all edits remain uncommitted and pull/push are skipped, leaving
            a human to fix the working tree before it becomes durable history.

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
        changed_paths = _changed_paths(cwd)
    except GitCommandError as e:
        return SyncResult(success=False, message=f"Git {e.cmd} failed: {e.stderr}")
    except subprocess.TimeoutExpired:
        return SyncResult(success=False, message="Git operation timed out.")
    except FileNotFoundError:
        return SyncResult(success=False, message="Git is not installed or not on PATH.")
    if not changed_paths:
        return SyncResult(success=True, message="No changes to commit.")

    # Validate the complete working tree before it becomes durable history. A
    # failing graph or policy gate must not be captured in a local commit, and
    # must not reach pull/rebase or push.
    if pre_push_check is not None:
        check_ok, check_detail = pre_push_check(cwd)
        if not check_ok:
            return SyncResult(
                success=False,
                message=(
                    "Pre-push check failed — changes left uncommitted; sync skipped.\n"
                    f"{check_detail}"
                ),
            )

    # Stage all changes
    try:
        result = _run_git(["add", "-A", "--", *changed_paths], cwd)
        if result.returncode != 0:
            return SyncResult(success=False, message=f"Git add failed: {result.stderr.strip()}")

        # Commit
        result = _run_git(["commit", "-m", message], cwd)
        if result.returncode != 0:
            return SyncResult(success=False, message=f"Git commit failed: {result.stderr.strip()}")

        # Rebase-pull before pushing — integrate the other machine's commits first
        # (the vault syncs across two machines; CLAUDE.md requires rebase-first). Never
        # auto-resolve: if the rebase conflicts (or otherwise fails), return that result
        # and do NOT push, leaving the local commit for a human to reconcile.
        pull_result = pull(cwd)
        if not pull_result.success:
            return pull_result

        # Push to the same sync target pull() rebased onto. When the target is
        # the branch's own namesake, `push -u origin <branch>` sets tracking on
        # a first push and is a no-op after. A session branch that integrates
        # elsewhere (a worktree's claude/* branch -> main) pushes
        # HEAD:<target>: pushing its own name would create a stray remote
        # branch the rest of the vault never pulls, which is how wrap-ups were
        # stranded before this resolution existed.
        sync_target = _sync_target(cwd)
        if sync_target is None:
            push_args = ["push"]
        elif sync_target.target == sync_target.branch:
            push_args = ["push", "-u", "origin", sync_target.target]
        else:
            push_args = ["push", "origin", f"HEAD:{sync_target.target}"]
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
