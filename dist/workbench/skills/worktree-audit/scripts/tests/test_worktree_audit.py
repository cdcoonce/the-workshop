"""Tests for worktree_audit — the reap predicate and the guards around it.

The safety property under test is one-directional: a worktree holding work must
never be reaped, while an empty one merely accumulates. Every test that asserts
"keep" is a data-loss test; every test that asserts "reap" is a housekeeping one.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest

from worktree_audit import (
    audit_repo,
    authored_commits,
    orphan_branch_verdicts,
    reap,
)


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-b", "main")
    _git(r, "config", "user.email", "t@e.com")
    _git(r, "config", "user.name", "T")
    (r / "f.txt").write_text("x\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-m", "init")
    return r


def _worktree(repo: Path, name: str, base: str = "HEAD") -> Path:
    path = repo.parent / name
    _git(repo, "worktree", "add", "-B", f"session/{name}", str(path), base)
    return path


def _age(path: Path, hours: float) -> None:
    old = time.time() - hours * 3600
    import os

    os.utime(path, (old, old))


# --- the reachability predicate ----------------------------------------------


def test_authored_commits_sees_a_commit_made_inside_its_own_worktree(repo: Path):
    # THE regression test. `rev-list --all` also expands every other worktree's
    # HEAD (git >= 2.7), and a session branch is checked out in its own worktree
    # — so without --single-worktree the branch is always reachable from itself,
    # every count is 0, and the reaper deletes committed work.
    wt = _worktree(repo, "alpha")
    _git(wt, "commit", "--allow-empty", "-m", "real work")

    assert authored_commits(repo, "session/alpha", exclude=["session/alpha"]) == 1


def test_authored_commits_ignores_commits_inherited_from_the_launch_head(repo: Path):
    # A worktree is cut from whatever the launch checkout is on. Commits it
    # inherited that way are not its work, and asking "is this branch merged into
    # main?" would preserve it forever whenever the checkout sat on a feature
    # branch — which is most of the time.
    _git(repo, "checkout", "-q", "-b", "feature/x")
    _git(repo, "commit", "--allow-empty", "-m", "someone else's commit")
    _worktree(repo, "beta")

    assert authored_commits(repo, "session/beta", exclude=["session/beta"]) == 0


def test_a_sibling_cut_from_this_branch_does_not_mask_its_work(repo: Path):
    # Divergent siblings never mask each other, so this needs the case that
    # actually distinguishes: gamma authors work, then delta is cut from gamma's
    # TIP and so contains that commit without having written it. Without
    # excluding the family, gamma reads as empty and gets reaped.
    wt_a = _worktree(repo, "gamma")
    _git(wt_a, "commit", "--allow-empty", "-m", "gamma's work")
    _git(repo, "worktree", "add", "-B", "session/delta", str(repo.parent / "delta"), "session/gamma")
    family = ["session/gamma", "session/delta"]

    assert authored_commits(repo, "session/gamma", exclude=family) == 1


def test_the_family_exclusion_errs_toward_keeping(repo: Path):
    # The honest cost of the rule above: delta authored nothing, yet excluding
    # the family makes gamma's inherited commit look like delta's own, so delta
    # is kept too. A false keep for a false reap is the right trade for a
    # destructive operation — but it is a trade, not a free win.
    wt_a = _worktree(repo, "epsilon")
    _git(wt_a, "commit", "--allow-empty", "-m", "epsilon's work")
    _git(repo, "worktree", "add", "-B", "session/zeta", str(repo.parent / "zeta"), "session/epsilon")

    assert authored_commits(repo, "session/zeta", exclude=["session/epsilon", "session/zeta"]) == 1


# --- classification -----------------------------------------------------------


def _verdict(verdicts, name):
    return next(v for v in verdicts if v.name == name)


def test_a_worktree_that_authored_nothing_is_reapable(repo: Path):
    wt = _worktree(repo, "empty")
    _age(wt, 48)

    assert _verdict(audit_repo(repo, branch_prefix="session/"), "empty").action == "reap"


def test_a_worktree_that_authored_work_is_kept(repo: Path):
    wt = _worktree(repo, "authored")
    _git(wt, "commit", "--allow-empty", "-m", "work")
    _age(wt, 48)

    v = _verdict(audit_repo(repo, branch_prefix="session/"), "authored")
    assert v.action == "keep"
    assert "authored" in v.reason


def test_a_dirty_worktree_is_kept(repo: Path):
    wt = _worktree(repo, "dirty")
    (wt / "scratch.txt").write_text("uncommitted")
    _age(wt, 48)

    v = _verdict(audit_repo(repo, branch_prefix="session/"), "dirty")
    assert v.action == "keep"
    assert "uncommitted" in v.reason


def test_a_recent_worktree_is_held_back_rather_than_reaped(repo: Path):
    # A concurrently-active session's tree is clean between commits. Age is the
    # cheap proxy that stops the sweep reaping it out from under the worker.
    _worktree(repo, "fresh")

    assert _verdict(audit_repo(repo, branch_prefix="session/"), "fresh").action == "recent"


def test_all_ages_reaches_a_recent_worktree(repo: Path):
    # The escape hatch exists so nobody reaches for a faked clock: passing now=0
    # to an age check makes every delta negative, which reads as "everything is
    # fresh" and silently reaps nothing.
    _worktree(repo, "fresh")

    assert _verdict(audit_repo(repo, branch_prefix="session/", all_ages=True), "fresh").action == "reap"


def test_the_main_checkout_is_never_a_candidate(repo: Path):
    _worktree(repo, "other")

    assert all(v.name != "repo" for v in audit_repo(repo, branch_prefix="session/"))


# --- orphan branches ----------------------------------------------------------


def test_an_orphan_branch_with_no_worktree_and_no_work_is_reapable(repo: Path):
    # _reap deletes a branch only as part of removing its directory, so a
    # worktree removed by any other route orphans its branch permanently.
    wt = _worktree(repo, "orphan")
    _git(repo, "worktree", "remove", "--force", str(wt))

    v = _verdict(orphan_branch_verdicts(repo, "session/"), "session/orphan")
    assert v.action == "reap"


def test_an_orphan_branch_that_authored_work_is_kept(repo: Path):
    # The branch is the only remaining copy of that work.
    wt = _worktree(repo, "orphanwork")
    _git(wt, "commit", "--allow-empty", "-m", "work")
    _git(repo, "worktree", "remove", "--force", str(wt))

    v = _verdict(orphan_branch_verdicts(repo, "session/"), "session/orphanwork")
    assert v.action == "keep"


def test_orphan_scan_ignores_branches_outside_the_prefix(repo: Path):
    _git(repo, "branch", "feature/keep-me")

    names = [v.name for v in orphan_branch_verdicts(repo, "session/")]
    assert "feature/keep-me" not in names


# --- read-only by default -----------------------------------------------------


def test_auditing_removes_nothing(repo: Path):
    wt = _worktree(repo, "untouched")
    _age(wt, 48)

    audit_repo(repo)

    assert wt.exists()


def test_reap_removes_only_the_reap_verdicts(repo: Path):
    doomed = _worktree(repo, "doomed")
    kept = _worktree(repo, "kept")
    _git(kept, "commit", "--allow-empty", "-m", "work")
    _age(doomed, 48)
    _age(kept, 48)

    reap(repo, audit_repo(repo, branch_prefix="session/"))

    assert not doomed.exists()
    assert kept.exists()


def test_a_branch_never_vouches_for_its_own_commits(repo: Path):
    # Regression for the orphan case: once the worktree is gone the branch is an
    # ordinary ref inside `--all`, so without self-exclusion it makes its own
    # commits look reachable elsewhere and the only copy of the work is reaped.
    wt = _worktree(repo, "selfvouch")
    _git(wt, "commit", "--allow-empty", "-m", "the only copy")
    _git(repo, "worktree", "remove", "--force", str(wt))

    assert authored_commits(repo, "session/selfvouch", exclude=[]) == 1


# --- scoping: nothing is reapable unless you say what a session looks like ----


def test_without_a_prefix_nothing_is_reapable(repo: Path):
    # Found by running the fleet for real, not by the suite: `staging-wt` — afk's
    # PERSISTENT integration worktree — is clean and authored nothing in four
    # repos, because that is exactly what long-lived infrastructure looks like
    # between merges. "Clean and empty" is not sufficient grounds to delete.
    wt = _worktree(repo, "infra")
    _age(wt, 48)

    v = _verdict(audit_repo(repo), "infra")
    assert v.action == "unscoped"
    assert "--branch-prefix" in v.reason


def test_a_prefix_leaves_non_matching_worktrees_unscoped(repo: Path):
    _git(repo, "worktree", "add", "-B", "afk/staging", str(repo.parent / "staging-wt"), "HEAD")
    _age(repo.parent / "staging-wt", 48)

    assert _verdict(audit_repo(repo, branch_prefix="session/"), "staging-wt").action == "unscoped"


def test_reap_never_touches_an_unscoped_worktree(repo: Path):
    wt = _worktree(repo, "infra2")
    _age(wt, 48)

    reap(repo, audit_repo(repo))

    assert wt.exists()
