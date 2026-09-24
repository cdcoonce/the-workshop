"""End-to-end tests for sync_boundary_squash.py against real git repositories.

Every scenario builds a bare "remote" plus one or two clones -- the second
clone stands in for the vault's other machine -- then runs the script as a
subprocess from the clone's root, exactly as the wrap-up sync boundary does
(issue #892). The assertions are about repository state, not script output:
how many commits sit between the session base and HEAD, whether a pushed
commit kept its SHA, whether the tree survived byte-for-byte.

Git environment is isolated (no global/system config) so results do not
depend on the developer's gpgsign, hooks path, or default branch settings.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))

from sync_boundary_squash import classify_pushed_prefix  # noqa: E402

SCRIPT = SCRIPTS_DIR / "sync_boundary_squash.py"


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
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        env=_env(),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _commit_file(repo: Path, rel: str, text: str, message: str) -> str:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    _git(repo, "add", rel)
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _make_remote_and_clone(tmp_path: Path) -> tuple[Path, Path, str]:
    """Bare remote plus a clone holding one pushed seed commit.

    Returns ``(remote, local, base)`` where ``base`` -- the seed commit -- is
    what the wrap-up flow calls "the commit before this session's first
    commit".
    """
    remote = tmp_path / "remote.git"
    remote.mkdir()
    _git(remote, "init", "-q", "--bare", "-b", "main")
    local = tmp_path / "local"
    _git(tmp_path, "clone", "-q", str(remote), str(local))
    _git(local, "symbolic-ref", "HEAD", "refs/heads/main")
    base = _commit_file(local, "README.md", "seed\n", "seed")
    _git(local, "push", "-q", "-u", "origin", "main")
    return remote, local, base


def _clone_peer(tmp_path: Path, remote: Path, name: str = "peer") -> Path:
    peer = tmp_path / name
    _git(tmp_path, "clone", "-q", str(remote), str(peer))
    return peer


def _run_raw(local: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=local,
        env=_env(),
        capture_output=True,
        text=True,
    )


def _run_squash(local: Path, base: str, *extra: str) -> dict:
    result = _run_raw(local, "--base", base, "--json", *extra)
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    return json.loads(result.stdout)


def _head(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD")


def _tree(repo: Path, rev: str) -> str:
    return _git(repo, "rev-parse", f"{rev}^{{tree}}")


def _subject(repo: Path, rev: str) -> str:
    return _git(repo, "log", "-1", "--format=%s", rev)


def _range_shas(repo: Path, base: str) -> list[str]:
    out = _git(repo, "rev-list", "--reverse", f"{base}..HEAD")
    return out.splitlines() if out else []


def _make_session_commits(local: Path, n: int = 3) -> list[str]:
    """N session commits touching the same file, the last one the wrap-up."""
    shas = []
    lines = ""
    for i in range(1, n + 1):
        lines += f"line {i}\n"
        message = "vault wrap-up 2026-09-20" if i == n else f"session commit {i}"
        shas.append(_commit_file(local, "brain/notes.md", lines, message))
    return shas


# ---------------------------------------------------------------------------
# Acceptance (a): 3+ unpushed commits collapse to exactly one commit
# ---------------------------------------------------------------------------


def test_collapses_three_unpushed_commits_into_one(tmp_path: Path) -> None:
    _remote, local, base = _make_remote_and_clone(tmp_path)
    _make_session_commits(local, n=3)
    tree_before = _tree(local, "HEAD")

    report = _run_squash(local, base)

    assert report["action"] == "squashed"
    assert report["session_commits"] == 3
    assert report["pushed"] == 0
    assert report["unpushed"] == 3
    session = _range_shas(local, base)
    assert len(session) == 1
    assert _tree(local, "HEAD") == tree_before
    assert _subject(local, "HEAD") == "vault wrap-up 2026-09-20"
    assert _git(local, "rev-parse", "HEAD^") == base
    assert report["new_head"] == _head(local)
    assert report["squash_base"] == base


def test_single_squashed_commit_rebases_onto_moved_remote(tmp_path: Path) -> None:
    """The point of the boundary: one commit rides `pull --rebase`, not N.

    The peer push also makes the fresh ls-remote head an object the local
    clone has never fetched, so this exercises the fetch-objects path.
    """
    remote, local, base = _make_remote_and_clone(tmp_path)
    peer = _clone_peer(tmp_path, remote)
    peer_sha = _commit_file(peer, "peer.md", "peer work\n", "peer session")
    _git(peer, "push", "-q")
    _make_session_commits(local, n=3)

    report = _run_squash(local, base)

    assert report["action"] == "squashed"
    assert report["remote_head"] == peer_sha
    assert len(_range_shas(local, base)) == 1

    _git(local, "pull", "-q", "--rebase")
    assert _git(local, "rev-list", "--count", "--merges", f"{base}..HEAD") == "0"
    session = _range_shas(local, base)
    assert len(session) == 2
    assert session[0] == peer_sha
    assert _subject(local, "HEAD") == "vault wrap-up 2026-09-20"
    _git(local, "push", "-q")


# ---------------------------------------------------------------------------
# Acceptance (b): a session commit already on the remote is never rewritten
# ---------------------------------------------------------------------------


def test_pushed_first_commit_is_not_rewritten(tmp_path: Path) -> None:
    _remote, local, base = _make_remote_and_clone(tmp_path)
    c1 = _commit_file(local, "brain/notes.md", "line 1\n", "session commit 1")
    _git(local, "push", "-q")
    _commit_file(local, "brain/notes.md", "line 1\nline 2\n", "session commit 2")
    _commit_file(local, "brain/notes.md", "line 1\nline 2\nline 3\n", "vault wrap-up 2026-09-20")
    tree_before = _tree(local, "HEAD")

    report = _run_squash(local, base)

    assert report["action"] == "squashed"
    assert report["pushed"] == 1
    assert report["unpushed"] == 2
    assert report["squash_base"] == c1
    session = _range_shas(local, base)
    assert len(session) == 2
    assert session[0] == c1, "the pushed commit must keep its SHA"
    assert _git(local, "rev-parse", "HEAD^") == c1
    assert _tree(local, "HEAD") == tree_before
    assert _subject(local, "HEAD") == "vault wrap-up 2026-09-20"


def test_all_session_commits_pushed_is_a_no_op(tmp_path: Path) -> None:
    _remote, local, base = _make_remote_and_clone(tmp_path)
    _make_session_commits(local, n=2)
    _git(local, "push", "-q")
    head_before = _head(local)

    report = _run_squash(local, base)

    assert report["action"] == "none"
    assert _head(local) == head_before


def test_single_unpushed_commit_is_a_no_op(tmp_path: Path) -> None:
    _remote, local, base = _make_remote_and_clone(tmp_path)
    c1 = _commit_file(local, "brain/notes.md", "line 1\n", "vault wrap-up 2026-09-20")

    report = _run_squash(local, base)

    assert report["action"] == "none"
    assert _head(local) == c1, "a lone wrap-up commit must not be rewritten"


# ---------------------------------------------------------------------------
# Acceptance (c): pushed-ness comes from a fresh ls-remote, never the
# remote-tracking ref
# ---------------------------------------------------------------------------


def test_ignores_stale_tracking_ref_that_claims_commit_pushed(tmp_path: Path) -> None:
    """A lying origin/main must not shrink the squash.

    The tracking ref says session commit 1 is on the remote; the actual
    remote never received it. A tracking-ref implementation would preserve
    commit 1 and squash only the rest -- the fresh ls-remote answer is that
    everything is unpushed, so everything collapses.
    """
    _remote, local, base = _make_remote_and_clone(tmp_path)
    shas = _make_session_commits(local, n=3)
    _git(local, "update-ref", "refs/remotes/origin/main", shas[0])

    report = _run_squash(local, base)

    assert report["action"] == "squashed"
    assert report["pushed"] == 0
    assert report["squash_base"] == base
    assert len(_range_shas(local, base)) == 1


def test_finds_pushed_commit_despite_missing_tracking_ref(tmp_path: Path) -> None:
    """The reverse lie: no tracking ref at all, yet commit 1 is on the remote.

    An implementation that reads refs/remotes/* would conclude nothing is
    pushed and rewrite the pushed commit; ls-remote says otherwise.
    """
    _remote, local, base = _make_remote_and_clone(tmp_path)
    c1 = _commit_file(local, "brain/notes.md", "line 1\n", "session commit 1")
    _git(local, "push", "-q")
    _git(local, "update-ref", "-d", "refs/remotes/origin/main")
    _commit_file(local, "brain/notes.md", "line 1\nline 2\n", "session commit 2")
    _commit_file(local, "brain/notes.md", "line 1\nline 2\nline 3\n", "vault wrap-up 2026-09-20")

    report = _run_squash(local, base)

    assert report["action"] == "squashed"
    assert report["squash_base"] == c1
    session = _range_shas(local, base)
    assert session[0] == c1, "the pushed commit must keep its SHA"
    assert len(session) == 2


def _add_session_worktree(local: Path, tmp_path: Path, branch: str = "claude/clever-benz") -> Path:
    """The desktop app's layout: a linked worktree on an unpublished session
    branch cut from local ``main``, with no upstream and no remote namesake."""
    worktree = tmp_path / "worktree"
    _git(local, "worktree", "add", "-q", "-b", branch, str(worktree), "main")
    return worktree


def test_worktree_session_branch_measures_pushed_ness_against_main(tmp_path: Path) -> None:
    """A session branch the remote has never heard of integrates into main.

    Pushed-ness measured against ``refs/heads/claude/...`` finds nothing, calls
    every commit unpushed, and rewrites the one ``origin/main`` already holds
    -- the vault's 2026-09-24 worktree wrap-up exposed this.
    """
    _remote, local, base = _make_remote_and_clone(tmp_path)
    worktree = _add_session_worktree(local, tmp_path)
    c1 = _commit_file(worktree, "brain/notes.md", "line 1\n", "session commit 1")
    _git(worktree, "push", "-q", "origin", "HEAD:main")
    _commit_file(worktree, "brain/notes.md", "line 1\nline 2\n", "session commit 2")
    _commit_file(
        worktree, "brain/notes.md", "line 1\nline 2\nline 3\n", "vault wrap-up 2026-09-24"
    )
    tree_before = _tree(worktree, "HEAD")

    report = _run_squash(worktree, base)

    assert report["action"] == "squashed"
    assert report["pushed"] == 1
    session = _range_shas(worktree, base)
    assert session[0] == c1, "the commit origin/main holds must keep its SHA"
    assert len(session) == 2
    assert _tree(worktree, "HEAD") == tree_before


def _add_detached_worktree(local: Path, tmp_path: Path) -> Path:
    """Codex's layout: a linked worktree on a detached HEAD cut from local
    ``main`` -- no branch at all, so no branch name can say where work goes."""
    worktree = tmp_path / "codex-worktree"
    _git(local, "worktree", "add", "-q", "--detach", str(worktree), "main")
    return worktree


def _local_branches(repo: Path) -> str:
    """Every local branch and its tip -- shared by all of a repo's worktrees."""
    return _git(repo, "for-each-ref", "--format=%(refname) %(objectname)", "refs/heads")


def test_detached_worktree_session_squashes_and_stays_detached(tmp_path: Path) -> None:
    """Codex runs vault sessions on a detached HEAD, and the boundary once
    skipped there outright, so every Codex wrap-up rode the rebase as N
    commits. The sync target (origin's default branch) defines pushed-ness
    exactly as on a branch; only HEAD moves, and it stays detached."""
    _remote, local, base = _make_remote_and_clone(tmp_path)
    worktree = _add_detached_worktree(local, tmp_path)
    c1 = _commit_file(worktree, "brain/notes.md", "line 1\n", "session commit 1")
    _git(worktree, "push", "-q", "origin", "HEAD:main")
    _commit_file(worktree, "brain/notes.md", "line 1\nline 2\n", "session commit 2")
    _commit_file(
        worktree, "brain/notes.md", "line 1\nline 2\nline 3\n", "vault wrap-up 2026-09-24"
    )
    tree_before = _tree(worktree, "HEAD")
    branches_before = _local_branches(local)

    report = _run_squash(worktree, base)

    assert report["action"] == "squashed", report["reason"]
    assert report["branch"] is None
    assert report["target"] == "main"
    assert report["target_source"] == "remote-default"
    assert report["pushed"] == 1
    session = _range_shas(worktree, base)
    assert session[0] == c1, "the commit origin/main holds must keep its SHA"
    assert len(session) == 2
    assert _tree(worktree, "HEAD") == tree_before
    assert _subject(worktree, "HEAD") == "vault wrap-up 2026-09-24"
    head_ref = subprocess.run(
        ["git", "symbolic-ref", "-q", "HEAD"], cwd=worktree, env=_env(), capture_output=True
    )
    assert head_ref.returncode == 1, "a detached session must stay detached"
    assert _local_branches(local) == branches_before, (
        "a detached squash must not create or move any local branch"
    )


def test_unresolvable_sync_target_skips_squash(tmp_path: Path) -> None:
    """A session branch the remote does not know, on a remote that names no
    default branch, has no sync target. Falling back to the branch name would
    call every commit unpushed -- the pre-fix behavior -- so the boundary
    skips instead and leaves the repository untouched."""
    remote, local, base = _make_remote_and_clone(tmp_path)
    worktree = _add_session_worktree(local, tmp_path)
    _git(remote, "symbolic-ref", "HEAD", "refs/heads/unborn")
    _make_session_commits(worktree, n=2)
    head_before = _head(worktree)

    report = _run_squash(worktree, base)

    assert report["action"] == "skipped"
    assert "sync target" in report["reason"]
    assert _head(worktree) == head_before


def test_remote_branch_absent_treats_all_commits_as_unpushed(tmp_path: Path) -> None:
    remote = tmp_path / "remote.git"
    remote.mkdir()
    _git(remote, "init", "-q", "--bare", "-b", "main")
    local = tmp_path / "local"
    _git(tmp_path, "clone", "-q", str(remote), str(local))
    _git(local, "symbolic-ref", "HEAD", "refs/heads/main")
    base = _commit_file(local, "README.md", "seed\n", "seed")
    _make_session_commits(local, n=2)
    assert _git(local, "ls-remote", "origin", "refs/heads/main") == ""

    report = _run_squash(local, base)

    assert report["action"] == "squashed"
    assert report["remote_head"] is None
    assert len(_range_shas(local, base)) == 1


# ---------------------------------------------------------------------------
# Acceptance (d): ambiguous history skips the squash and changes nothing
# ---------------------------------------------------------------------------


def test_merge_commit_in_session_range_skips_squash(tmp_path: Path) -> None:
    """A merge in the session range (e.g. a hand-built recovery merge) is the
    reachable ambiguous case: rewriting across it is unsafe, so the boundary
    proceeds exactly as today."""
    _remote, local, base = _make_remote_and_clone(tmp_path)
    _commit_file(local, "brain/notes.md", "line 1\n", "session commit 1")
    _git(local, "checkout", "-q", "-b", "side", base)
    _commit_file(local, "side.md", "side\n", "side work")
    _git(local, "checkout", "-q", "main")
    _git(local, "merge", "-q", "--no-ff", "-m", "recovery merge", "side")
    _commit_file(local, "brain/notes.md", "line 1\nline 2\n", "vault wrap-up 2026-09-20")
    head_before = _head(local)
    range_before = _range_shas(local, base)

    report = _run_squash(local, base)

    assert report["action"] == "skipped"
    assert "merge" in report["reason"]
    assert _head(local) == head_before
    assert _range_shas(local, base) == range_before


@pytest.mark.parametrize(
    ("flags", "expected"),
    [
        ([], 0),
        ([False, False, False], 0),
        ([True, False, False], 1),
        ([True, True], 2),
        ([True, False, True], None),
        ([False, True], None),
    ],
)
def test_classify_pushed_prefix(flags: list[bool], expected: int | None) -> None:
    """Unit coverage for the interleave guard the linear range cannot reach:
    pushed-ness is inherited by ancestors, so a real linear stack always
    yields a prefix -- but an inconsistent classification must skip, never
    guess."""
    assert classify_pushed_prefix(flags) == expected


# ---------------------------------------------------------------------------
# Fail-open guards: every refusal leaves the repository untouched
# ---------------------------------------------------------------------------


def test_staged_uncommitted_changes_skip_squash(tmp_path: Path) -> None:
    _remote, local, base = _make_remote_and_clone(tmp_path)
    _make_session_commits(local, n=2)
    staged = local / "staged.md"
    staged.write_text("staged but uncommitted\n", encoding="utf-8")
    _git(local, "add", "staged.md")
    head_before = _head(local)

    report = _run_squash(local, base)

    assert report["action"] == "skipped"
    assert "staged" in report["reason"]
    assert _head(local) == head_before
    assert _git(local, "diff", "--cached", "--name-only") == "staged.md"


def test_unreachable_remote_skips_squash(tmp_path: Path) -> None:
    _remote, local, base = _make_remote_and_clone(tmp_path)
    _make_session_commits(local, n=2)
    _git(local, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    head_before = _head(local)

    report = _run_squash(local, base)

    assert report["action"] == "skipped"
    assert "ls-remote" in report["reason"]
    assert _head(local) == head_before


def test_bisect_in_progress_skips_squash(tmp_path: Path) -> None:
    """A bisect detaches HEAD at a commit under test. Once the boundary
    stopped skipping every detached HEAD, it must still recognize this one as
    an operation in flight: squashing would rewrite the commit being tested."""
    _remote, local, base = _make_remote_and_clone(tmp_path)
    shas = _make_session_commits(local, n=4)
    _git(local, "bisect", "start", shas[-1], base)
    head_before = _head(local)
    assert head_before != shas[-1], "fixture must be mid-bisect"
    assert len(_range_shas(local, base)) >= 2, "fixture must leave something to squash"

    report = _run_squash(local, base)

    assert report["action"] == "skipped"
    assert "in progress" in report["reason"]
    assert _head(local) == head_before
    assert (local / ".git" / "BISECT_LOG").exists(), "the bisect must survive the skip"


def test_base_not_an_ancestor_skips_squash(tmp_path: Path) -> None:
    _remote, local, base = _make_remote_and_clone(tmp_path)
    _git(local, "checkout", "-q", "-b", "side", base)
    side = _commit_file(local, "side.md", "side\n", "side work")
    _git(local, "checkout", "-q", "main")
    _make_session_commits(local, n=2)
    head_before = _head(local)

    report = _run_squash(local, side)

    assert report["action"] == "skipped"
    assert "ancestor" in report["reason"]
    assert _head(local) == head_before


def test_unknown_base_is_a_usage_error(tmp_path: Path) -> None:
    _remote, local, _base = _make_remote_and_clone(tmp_path)
    result = _run_raw(local, "--base", "0" * 40, "--json")
    assert result.returncode == 2
    assert "base" in result.stderr


def test_net_empty_session_skips_squash(tmp_path: Path) -> None:
    """Session commits that cancel out would need an --allow-empty commit;
    proceeding as today is safer than inventing an empty wrap-up commit."""
    _remote, local, base = _make_remote_and_clone(tmp_path)
    _commit_file(local, "scratch.md", "scratch\n", "session commit 1")
    _git(local, "rm", "-q", "scratch.md")
    _git(local, "commit", "-q", "-m", "vault wrap-up 2026-09-20")
    head_before = _head(local)

    report = _run_squash(local, base)

    assert report["action"] == "skipped"
    assert "empty" in report["reason"]
    assert _head(local) == head_before
    assert len(_range_shas(local, base)) == 2


def test_unstaged_worktree_changes_survive_and_stay_out_of_the_commit(tmp_path: Path) -> None:
    _remote, local, base = _make_remote_and_clone(tmp_path)
    _make_session_commits(local, n=3)
    committed = (local / "brain/notes.md").read_text(encoding="utf-8")
    (local / "brain/notes.md").write_text(committed + "dirty edit\n", encoding="utf-8")

    report = _run_squash(local, base)

    assert report["action"] == "squashed"
    on_disk = (local / "brain/notes.md").read_text(encoding="utf-8")
    assert on_disk == committed + "dirty edit\n"
    assert _git(local, "diff", "--name-only") == "brain/notes.md"
    assert _git(local, "diff", "--cached", "--name-only") == ""
    in_head = _git(local, "show", "HEAD:brain/notes.md")
    assert "dirty edit" not in in_head
