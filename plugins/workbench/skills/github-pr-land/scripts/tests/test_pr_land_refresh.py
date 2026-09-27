"""Tests for ``pr_land``'s land refresh: ``read_pr`` and ``refresh_and_gate``.

Each test's docstring names the defect it guards against. ``gh`` is the
scripted FakeGh from conftest; ``git`` runs for real. The PR's commits are made
in a separate ``author`` clone and pushed to the bare origin, so the caller
clone starts without them — exactly as a PR from another machine would — and
must stay on its own branch, HEAD and clean status throughout.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from conftest import CompositeRunner, FakeGh, json_result
from pr_land import PrInfo, RefreshResult, read_pr, refresh_and_gate

REPO = "acme/widget"
LINES = "".join(f"{n}\n" for n in range(1, 11))


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


@dataclass
class World:
    clone: Path
    origin: Path
    author: Path
    runner: CompositeRunner
    fake: FakeGh
    tmp: Path

    def commit(self, branch: str, path: str, content: str, message: str) -> str:
        """Commit *content* to *path* on *branch* in the author clone and push it."""
        git(self.author, "checkout", "-q", branch)
        (self.author / path).write_text(content, encoding="utf-8")
        git(self.author, "add", path)
        git(self.author, "commit", "-q", "-m", message)
        git(self.author, "push", "-q", "origin", branch)
        return git(self.author, "rev-parse", "HEAD")

    def branch(self, name: str, start: str = "main") -> None:
        git(self.author, "branch", name, start)

    def origin_ref(self, ref: str) -> str:
        return git(self.origin, "rev-parse", f"refs/heads/{ref}")

    def info(self, head_sha: str, base_sha: str, *, head_ref: str = "feat/x", base_ref: str = "main") -> PrInfo:
        return PrInfo(
            number=7, head_sha=head_sha, head_ref=head_ref, head_repo=REPO, base_ref=base_ref, base_sha=base_sha
        )

    def caller_state(self) -> tuple[str, str, str, str]:
        return (
            git(self.clone, "rev-parse", "HEAD"),
            git(self.clone, "symbolic-ref", "HEAD"),
            git(self.clone, "status", "--porcelain"),
            git(self.clone, "worktree", "list", "--porcelain"),
        )

    def git_argvs(self) -> list[list[str]]:
        return [argv for argv, _ in self.runner.calls if argv[:1] == ["git"]]


@pytest.fixture
def world(git_repo: Path, tmp_path: Path) -> World:
    origin = tmp_path / "acme" / "widget.git"
    author = tmp_path / "author"
    subprocess.run(["git", "clone", "-q", str(origin), str(author)], check=True, capture_output=True)
    git(author, "config", "user.name", "Author")
    git(author, "config", "user.email", "author@example.com")
    fake = FakeGh()
    return World(git_repo, origin, author, CompositeRunner(fake, git_repo), fake, tmp_path)


def behind(world: World) -> tuple[str, str]:
    """A PR head one commit ahead of an older main; main has since moved on."""
    world.branch("feat/x")
    head = world.commit("feat/x", "a.txt", "a\n", "feat: a")
    base = world.commit("main", "b.txt", "b\n", "chore: b")
    return head, base


def line_edit(n: int, text: str) -> str:
    return "".join(f"{text if i == n else i}\n" for i in range(1, 11))


def nearby(world: World) -> tuple[str, str]:
    """PR edits line 5; main edits line 8 of the same file, so the merge is clean."""
    world.commit("main", "f.txt", LINES, "chore: f")
    world.branch("feat/x")
    head = world.commit("feat/x", "f.txt", line_edit(5, "five"), "feat: five")
    base = world.commit("main", "f.txt", line_edit(8, "eight"), "chore: eight")
    return head, base


def empty_delta(world: World) -> tuple[str, str]:
    """main already carries the PR's exact change as a different commit."""
    world.branch("feat/x")
    head = world.commit("feat/x", "a.txt", "a\n", "feat: a")
    base = world.commit("main", "a.txt", "a\n", "feat: a (cherry-picked)")
    return head, base


def run(world: World, head: str, base: str, gate: str = "true", **kwargs: object) -> RefreshResult:
    before = world.caller_state()
    result = refresh_and_gate(world.runner, REPO, world.info(head, base), gate=gate, **kwargs)
    assert world.caller_state() == before
    return result


def test_behind_head_merges_and_pushes(world: World) -> None:
    """Guards against a refresh that does nothing and reports the stale head as tested."""
    head, base = behind(world)
    result = run(world, head, base)
    assert (result.exit_code, result.pushed, result.gate_note) == (0, True, "exit 0")
    assert result.tested_sha not in (head, base)
    assert git(world.origin, "rev-parse", f"{result.tested_sha}^1", f"{result.tested_sha}^2").split() == [head, base]
    assert world.origin_ref("feat/x") == result.tested_sha


def test_fetch_precedes_ancestry_check(world: World) -> None:
    """Guards against checking ancestry before fetching, which exits 128 on objects the clone lacks."""
    head, base = behind(world)
    result = run(world, head, base)
    assert result.exit_code == 0
    argvs = world.git_argvs()
    fetch = argvs.index(["git", "fetch", "origin", head, base])
    assert fetch < argvs.index(["git", "merge-base", "--is-ancestor", base, head])


def test_head_containing_base_skips_refresh_and_gate(world: World) -> None:
    """Guards against refreshing and gating a head that already contains the base."""
    world.branch("feat/x")
    head = world.commit("feat/x", "a.txt", "a\n", "feat: a")
    base = world.origin_ref("main")
    marker = world.tmp / "gate-ran"
    result = run(world, head, base, gate=f"touch {marker}")
    assert result == RefreshResult(head, False, "not run (head contained base)", 0, result.message)
    assert not marker.exists()
    assert world.origin_ref("feat/x") == head


def test_read_pr_takes_live_base_tip_not_frozen_base_sha(world: World) -> None:
    """Guards against using pulls/<pr>.base.sha, which GitHub freezes at the PR's last update."""
    stale, live, head = "1" * 40, "2" * 40, "3" * 40
    world.fake.script(
        ["gh", "api", f"repos/{REPO}/pulls/7"],
        json_result(
            {
                "number": 7,
                "head": {"sha": head, "ref": "feat/x", "repo": {"full_name": REPO}},
                "base": {"sha": stale, "ref": "main", "repo": {"full_name": REPO}},
            }
        ),
    )
    world.fake.script(["gh", "api", f"repos/{REPO}/git/ref/heads/main"], json_result({"object": {"sha": live}}))
    info = read_pr(world.runner, REPO, 7)
    assert info == PrInfo(number=7, head_sha=head, head_ref="feat/x", head_repo=REPO, base_ref="main", base_sha=live)


def test_shas_come_from_the_api_not_origin_refs(world: World) -> None:
    """Guards against resolving head or base from the clone's origin/* refs instead of the API."""
    head, base = behind(world)
    world.fake.script(
        ["gh", "api", f"repos/{REPO}/pulls/7"],
        json_result(
            {
                "number": 7,
                "head": {"sha": head, "ref": "feat/x", "repo": {"full_name": REPO}},
                "base": {"sha": "f" * 40, "ref": "main", "repo": {"full_name": REPO}},
            }
        ),
    )
    world.fake.script(["gh", "api", f"repos/{REPO}/git/ref/heads/main"], json_result({"object": {"sha": base}}))
    info = read_pr(world.runner, REPO, 7)
    before = world.caller_state()
    result = refresh_and_gate(world.runner, REPO, info, gate="true")
    assert world.caller_state() == before
    assert result.exit_code == 0
    argvs = world.git_argvs()
    assert ["git", "fetch", "origin", head, base] in argvs
    assert not [a for a in argvs if "rev-parse" in a and any("origin/" in part for part in a)]


def test_conflict_names_files_and_pushes_nothing(world: World) -> None:
    """Guards against a conflict that is reported without naming the conflicted files."""
    world.commit("main", "f.txt", LINES, "chore: f")
    world.branch("feat/x")
    head = world.commit("feat/x", "f.txt", line_edit(5, "five"), "feat: five")
    base = world.commit("main", "f.txt", line_edit(5, "FIVE"), "chore: FIVE")
    result = run(world, head, base)
    assert (result.exit_code, result.pushed) == (2, False)
    assert "f.txt" in result.message
    assert world.origin_ref("feat/x") == head


def test_nearby_base_edit_changes_patch_id_and_refuses(world: World) -> None:
    """Guards against skipping the patch-id comparison when the merge is clean but the delta moved."""
    head, base = nearby(world)
    result = run(world, head, base)
    assert (result.exit_code, result.pushed) == (2, False)
    assert world.origin_ref("feat/x") == head


def test_accept_delta_change_pushes_a_changed_delta(world: World) -> None:
    """Guards against accept_delta_change being ignored, refusing every changed delta."""
    head, base = nearby(world)
    result = run(world, head, base, accept_delta_change=True)
    assert (result.exit_code, result.pushed) == (0, True)
    assert world.origin_ref("feat/x") == result.tested_sha


@pytest.mark.parametrize("accept", [False, True])
def test_empty_delta_refuses_even_when_accepted(world: World, accept: bool) -> None:
    """Guards against letting accept_delta_change push a PR the base already contains."""
    head, base = empty_delta(world)
    result = run(world, head, base, accept_delta_change=accept)
    assert (result.exit_code, result.pushed) == (2, False)
    assert result.message
    assert world.origin_ref("feat/x") == head


def test_gate_command_not_found_is_indeterminate(world: World) -> None:
    """Guards against mapping a gate that could not run (127) to red or green."""
    head, base = behind(world)
    result = run(world, head, base, gate="nonexistent-cmd-xyz")
    assert (result.exit_code, result.pushed, result.gate_note) == (2, False, "did not run (127)")
    assert world.origin_ref("feat/x") == head


def test_gate_not_executable_is_indeterminate(world: World) -> None:
    """Guards against mapping a gate that could not execute (126) to red."""
    head, base = behind(world)
    result = run(world, head, base, gate="exit 126")
    assert (result.exit_code, result.gate_note) == (2, "did not run (126)")


def test_gate_pipeline_failure_is_red(world: World) -> None:
    """Guards against dropping pipefail, which lets `false | true` pass."""
    head, base = behind(world)
    result = run(world, head, base, gate="false | true")
    assert (result.exit_code, result.pushed) == (1, False)
    assert world.origin_ref("feat/x") == head


def test_gate_evidence_missing_is_indeterminate(world: World) -> None:
    """Guards against pushing on a green gate whose output lacks the required evidence."""
    head, base = behind(world)
    result = run(world, head, base, gate="echo 3 passed", gate_evidence=r"\d+ failed")
    assert (result.exit_code, result.pushed) == (2, False)
    assert world.origin_ref("feat/x") == head


def test_gate_evidence_is_quoted_in_the_note(world: World) -> None:
    """Guards against a gate note that drops the evidence match."""
    head, base = behind(world)
    result = run(world, head, base, gate="echo 3 passed", gate_evidence=r"\d+ passed")
    assert (result.exit_code, result.gate_note) == (0, "exit 0, evidence '3 passed'")


def test_origin_head_advanced_before_push_is_refused(world: World) -> None:
    """Guards against a forced push that overwrites a commit pushed after the PR was read."""
    head, base = behind(world)
    newer = world.commit("feat/x", "c.txt", "c\n", "feat: c")
    result = run(world, head, base)
    assert (result.exit_code, result.pushed) == (2, False)
    assert world.origin_ref("feat/x") == newer


def test_push_is_never_forced(world: World) -> None:
    """Guards against a push argv carrying --force, -f or a +refspec."""
    head, base = behind(world)
    run(world, head, base)
    pushes = [argv for argv in world.git_argvs() if argv[1:2] == ["push"]]
    assert pushes == [["git", "push", "origin", "HEAD:refs/heads/feat/x"]]
    for argv in pushes:
        assert not {"--force", "-f"} & set(argv)
        assert not [part for part in argv[2:] if part.startswith("+")]


def test_fork_head_is_refused(world: World) -> None:
    """Guards against refreshing a head that lives in another repository."""
    head, base = behind(world)
    info = world.info(head, base)
    fork = PrInfo(info.number, info.head_sha, info.head_ref, "someone/widget", info.base_ref, info.base_sha)
    result = refresh_and_gate(world.runner, REPO, fork, gate="true")
    assert (result.exit_code, result.pushed) == (2, False)
    assert result.message
    assert world.git_argvs() == []


def test_dev_into_main_is_refused_toward_promote(world: World) -> None:
    """Guards against landing a trunk-to-release PR instead of pointing at promote."""
    head, base = behind(world)
    result = refresh_and_gate(
        world.runner, REPO, world.info(head, base, head_ref="dev", base_ref="main"), gate="true"
    )
    assert (result.exit_code, result.pushed) == (2, False)
    assert "promote" in result.message
    assert world.git_argvs() == []


def test_gate_exception_propagates_after_cleanup(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    """Guards against a scratch worktree left behind when the gate raises."""
    head, base = behind(world)
    real_run = subprocess.run

    def fake_run(argv: list[str], *args: object, **kwargs: object) -> object:
        if argv[:1] == ["bash"]:
            raise RuntimeError("gate blew up")
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", fake_run)
    before = world.caller_state()
    with pytest.raises(RuntimeError, match="gate blew up"):
        refresh_and_gate(world.runner, REPO, world.info(head, base), gate="true")
    monkeypatch.undo()
    listed = git(world.clone, "worktree", "list", "--porcelain").splitlines()
    assert [line for line in listed if line.startswith("worktree ")] == [f"worktree {world.clone}"]
    assert world.caller_state() == before


def test_caller_clone_is_never_touched(world: World) -> None:
    """Guards against merging in the caller's clone instead of the scratch worktree."""
    head, base = behind(world)
    main_before = git(world.clone, "rev-parse", "refs/heads/main")
    before = world.caller_state()
    result = refresh_and_gate(world.runner, REPO, world.info(head, base), gate="true")
    assert world.caller_state() == before
    assert git(world.clone, "rev-parse", "refs/heads/main") == main_before
    assert result.exit_code == 0
    merges = [(argv, cwd) for argv, cwd in world.runner.calls if argv[1:2] == ["merge"]]
    assert merges and all(cwd != str(world.clone) for _, cwd in merges)
