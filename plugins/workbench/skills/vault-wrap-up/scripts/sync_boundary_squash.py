"""Collapse this session's unpushed vault commits into one at the sync boundary.

vault-wrap-up runs this from the vault root immediately after the wrap-up
commit and immediately before /sync's ``git pull --rebase`` (issue #892), so
a conflicted rebase replays one session commit instead of N. ``--base`` is
the commit before this session's first commit -- the same base the wrap-up
audit already tracks.

Which commits are "unpushed" comes from a fresh ``git ls-remote`` of the
sync target (``sync_target.py``), never from the remote-tracking ref:
tracking refs go stale the moment the vault's other machine pushes, and a
stale answer here would rewrite a commit the remote already has. The target
is the branch this checkout's work integrates into, not the current branch's
namesake -- in a desktop-app worktree on an unpublished ``claude/*`` branch
that namesake does not exist on the remote, and measuring against it once
called every session commit unpushed. A Codex session on a detached HEAD
squashes the same way; only HEAD moves. When the ls-remote head is an object
this clone has never fetched, the script fetches the target once, purely to
make the ancestry test possible.

Fail-open contract: every guard failure reports ``skipped`` and leaves the
repository byte-for-byte untouched, so the boundary degrades to today's
behavior. A successful squash preserves the tree exactly -- ``reset --soft``
then ``commit -C <old HEAD>`` reshapes history without touching the index or
worktree -- and never moves the squash base below the newest session commit
the remote already has.

Exit codes: 0 for ``squashed``, ``none``, and ``skipped`` (sync proceeds in
all three cases); 2 for usage errors; 1 for unexpected internal failures.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from sync_target import UnresolvedTarget
from sync_target import resolve as resolve_sync_target


class GitError(RuntimeError):
    """A git invocation failed in a way the boundary cannot interpret."""


@dataclass
class Report:
    """What the boundary did, machine-readable via ``--json``."""

    action: str  # "squashed" | "none" | "skipped"
    reason: str
    branch: str | None = None
    target: str | None = None
    target_source: str | None = None
    remote: str = "origin"
    base: str | None = None
    old_head: str | None = None
    new_head: str | None = None
    squash_base: str | None = None
    session_commits: int = 0
    pushed: int = 0
    unpushed: int = 0
    remote_head: str | None = None


def _run_git(*args: str) -> subprocess.CompletedProcess[str]:
    """Run git in the current directory, capturing output, never raising."""
    return subprocess.run(["git", *args], capture_output=True, text=True, check=False)


def _git_out(*args: str) -> str:
    """Run git and return stripped stdout, raising GitError on failure."""
    proc = _run_git(*args)
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or "no output"
        raise GitError(f"git {' '.join(args)}: {detail}")
    return proc.stdout.strip()


def _object_exists(sha: str) -> bool:
    return _run_git("cat-file", "-e", f"{sha}^{{commit}}").returncode == 0


def _is_ancestor(ancestor: str, descendant: str) -> bool:
    proc = _run_git("merge-base", "--is-ancestor", ancestor, descendant)
    if proc.returncode not in (0, 1):
        raise GitError(f"merge-base --is-ancestor failed: {proc.stderr.strip()}")
    return proc.returncode == 0


def _ls_remote_head(remote: str, branch: str) -> str | None:
    """Fresh remote tip for ``branch``, or None when the branch is absent.

    This is the one source of truth for pushed-ness; the remote-tracking ref
    is never consulted.
    """
    ref = f"refs/heads/{branch}"
    out = _git_out("ls-remote", "--", remote, ref)
    for line in out.splitlines():
        sha, _, name = line.partition("\t")
        if name == ref:
            return sha
    return None


def classify_pushed_prefix(pushed_flags: Sequence[bool]) -> int | None:
    """Length of the leading pushed run, or None when pushed/unpushed interleave.

    For a linear session range interleaving is impossible -- being on the
    remote is inherited by ancestors, so pushed commits always form a prefix
    -- but issue #892 requires skipping, not guessing, if the classification
    ever comes back inconsistent.
    """
    first_unpushed = len(pushed_flags)
    for index, flag in enumerate(pushed_flags):
        if not flag:
            first_unpushed = index
            break
    if any(pushed_flags[first_unpushed:]):
        return None
    return first_unpushed


def _operation_in_progress() -> str | None:
    """Name of any in-flight git operation that makes rewriting unsafe.

    ``BISECT_LOG`` matters because a bisect detaches HEAD, and a detached
    HEAD is otherwise a legitimate session state (a Codex worktree).
    """
    git_dir = Path(_git_out("rev-parse", "--absolute-git-dir"))
    for marker in (
        "rebase-merge",
        "rebase-apply",
        "MERGE_HEAD",
        "CHERRY_PICK_HEAD",
        "REVERT_HEAD",
        "BISECT_LOG",
    ):
        if (git_dir / marker).exists():
            return marker
    return None


def squash(base: str, remote: str) -> Report:
    """Collapse the trailing run of unpushed session commits into one commit.

    Parameters
    ----------
    base:
        Resolved SHA of the commit before this session's first commit.
    remote:
        Remote name whose branch tip defines pushed-ness.

    Returns
    -------
    Report
        ``squashed`` on success, ``none`` when there is nothing to collapse,
        ``skipped`` when any guard refuses -- the repository is untouched in
        the last two cases.
    """
    report = Report(action="skipped", reason="", remote=remote, base=base)

    # Reported only: pushed-ness is measured against the sync target, and the
    # rewrite below never names a branch, so a detached HEAD (a Codex
    # worktree) squashes like any other.
    branch_proc = _run_git("symbolic-ref", "--short", "-q", "HEAD")
    report.branch = branch_proc.stdout.strip() if branch_proc.returncode == 0 else None

    marker = _operation_in_progress()
    if marker is not None:
        report.reason = f"git operation in progress ({marker}); not rewriting"
        return report

    head = _git_out("rev-parse", "HEAD")
    report.old_head = head
    if not _is_ancestor(base, head):
        report.reason = f"base {base[:12]} is not an ancestor of HEAD"
        return report

    staged = _run_git("diff", "--cached", "--quiet")
    if staged.returncode == 1:
        report.reason = "staged but uncommitted changes present; not sweeping them into a squash"
        return report
    if staged.returncode != 0:
        raise GitError(f"diff --cached failed: {staged.stderr.strip()}")

    if _git_out("rev-list", "--count", "--merges", f"{base}..{head}") != "0":
        report.reason = "session range contains a merge commit; history is ambiguous"
        return report

    rev_list = _git_out("rev-list", "--reverse", f"{base}..{head}")
    session = rev_list.splitlines() if rev_list else []
    report.session_commits = len(session)
    if len(session) < 2:
        report.action = "none"
        report.reason = (
            "no session commits between base and HEAD"
            if not session
            else "session is already a single commit"
        )
        report.unpushed = len(session)
        return report

    try:
        sync_target = resolve_sync_target(remote)
    except UnresolvedTarget as exc:
        report.reason = f"cannot resolve the sync target ({exc}); cannot verify pushed-ness"
        return report
    target = sync_target.target
    report.target = target
    report.target_source = sync_target.source

    try:
        remote_head = _ls_remote_head(remote, target)
    except GitError as exc:
        report.reason = f"fresh ls-remote failed ({exc}); cannot verify pushed-ness"
        return report

    if remote_head is not None and not _object_exists(remote_head):
        _run_git("fetch", "--quiet", "--", remote, target)
        if not _object_exists(remote_head):
            try:
                refreshed = _ls_remote_head(remote, target)
            except GitError as exc:
                report.reason = f"fresh ls-remote failed ({exc}); cannot verify pushed-ness"
                return report
            if refreshed is not None and not _object_exists(refreshed):
                report.reason = (
                    f"remote head {refreshed[:12]} is not available locally even after "
                    "fetching; cannot verify pushed-ness"
                )
                return report
            remote_head = refreshed
    report.remote_head = remote_head

    if remote_head is None:
        pushed_flags = [False] * len(session)
    else:
        pushed_flags = [_is_ancestor(sha, remote_head) for sha in session]

    prefix = classify_pushed_prefix(pushed_flags)
    if prefix is None:
        report.reason = "pushed and unpushed session commits interleave; history is ambiguous"
        return report
    report.pushed = prefix
    report.unpushed = len(session) - prefix

    if report.unpushed == 0:
        report.action = "none"
        report.reason = "every session commit is already on the remote"
        return report
    if report.unpushed == 1:
        report.action = "none"
        report.reason = "only one unpushed commit; nothing to collapse"
        return report

    squash_base = base if prefix == 0 else session[prefix - 1]
    report.squash_base = squash_base
    old_tree = _git_out("rev-parse", f"{head}^{{tree}}")
    if _git_out("rev-parse", f"{squash_base}^{{tree}}") == old_tree:
        report.squash_base = None
        report.reason = "unpushed commits are net-empty; a squash would need an empty commit"
        return report

    _git_out("reset", "--soft", squash_base)
    committed = _run_git("commit", "--quiet", "-C", head)
    if committed.returncode != 0:
        _run_git("reset", "--soft", head)
        report.squash_base = None
        report.reason = (
            f"commit failed ({committed.stderr.strip() or 'no output'}); repository restored"
        )
        return report

    new_head = _git_out("rev-parse", "HEAD")
    new_tree = _git_out("rev-parse", f"{new_head}^{{tree}}")
    new_parent = _git_out("rev-parse", f"{new_head}^")
    if new_tree != old_tree or new_parent != squash_base:
        _run_git("reset", "--soft", head)
        report.squash_base = None
        report.reason = "squashed commit failed verification; repository restored"
        return report

    report.action = "squashed"
    report.reason = f"collapsed {report.unpushed} unpushed session commits into one"
    report.new_head = new_head
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Squash this session's unpushed vault commits into the single wrap-up "
            "commit before /sync's git pull --rebase."
        )
    )
    parser.add_argument(
        "--base",
        required=True,
        help="commit before this session's first commit (the wrap-up audit base)",
    )
    parser.add_argument("--remote", default="origin", help="remote defining pushed-ness")
    parser.add_argument("--json", action="store_true", dest="as_json", help="emit a JSON report")
    args = parser.parse_args(argv)

    if _run_git("rev-parse", "--git-dir").returncode != 0:
        print("error: not inside a git repository", file=sys.stderr)
        return 2
    base_proc = _run_git("rev-parse", "--verify", "--quiet", f"{args.base}^{{commit}}")
    if base_proc.returncode != 0:
        print(f"error: --base {args.base!r} is not a commit in this repository", file=sys.stderr)
        return 2

    try:
        report = squash(base_proc.stdout.strip(), args.remote)
    except GitError as exc:
        report = Report(action="skipped", reason=f"git failure: {exc}", remote=args.remote)

    if args.as_json:
        print(json.dumps(asdict(report), indent=2))
    else:
        print(f"{report.action}: {report.reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
