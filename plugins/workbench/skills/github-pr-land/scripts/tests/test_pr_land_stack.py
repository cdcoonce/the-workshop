"""Tests for ``pr_land``'s refresh of a PR stacked on a squash-merged base PR.

A PR cut from another PR's branch carries that PR's commits. Once the base PR
is squash-merged, ``git merge <main>`` picks the pre-stack fork point as merge
base, sees main's squash and the head's carried copy as two different additions
at one spot, and conflicts. With the base PR's final head as merge base the same
merge is clean. These tests build that history for real: a bare ``origin``, a
squash commit on ``main``, and ``refs/pull/<n>/head`` pushed the way GitHub keeps
it. ``gh`` is the scripted FakeGh from conftest; ``git`` runs for real.

Each test's docstring names the defect it guards against.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

import pr_land
from conftest import CompositeRunner, FakeGh, http_error, json_result
from pr_land import PrInfo, RefreshResult, Result, refresh_and_gate

REPO = "acme/widget"
LINES = "".join(f"{n}\n" for n in range(1, 11))
BLOCK_A = "a1\na2\nshared1\nshared2\n"
BLOCK_B = "b1\nb2\nshared1\nshared2\n"
BLOCK_C = "c1\nc2\nshared1\nshared2\n"
TODAYS_REFUSAL = "merging main conflicts; resolve by hand:\nt.txt"
A_PR, B_PR, C_PR = 5, 6, 7


def git(cwd: Path, *args: str, stdin: str | None = None) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True, input=stdin
    ).stdout.strip()


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

    def squash(self, branch: str, message: str) -> str:
        """Land *branch*'s final tree on main as one new commit, as a squash merge does."""
        git(self.author, "checkout", "-q", "main")
        git(self.author, "checkout", branch, "--", ".")
        git(self.author, "commit", "-q", "-m", message)
        git(self.author, "push", "-q", "origin", "main")
        return git(self.author, "rev-parse", "HEAD")

    def publish(self, sha: str, pr: int) -> None:
        """Keep *sha* at ``refs/pull/<pr>/head`` on origin, as GitHub does after the branch is deleted."""
        git(self.author, "push", "-q", "origin", f"{sha}:refs/pull/{pr}/head")

    def serve_pr(self, pr: int, *, merged: bool, merge_commit: str) -> None:
        """Script ``pulls/<pr>`` as GitHub would answer it."""
        payload = {"number": pr, "merged": merged, "merge_commit_sha": merge_commit}
        self.fake.script(["gh", "api", f"repos/{REPO}/pulls/{pr}"], json_result(payload))

    def origin_ref(self, ref: str) -> str:
        return git(self.origin, "rev-parse", f"refs/heads/{ref}")

    def info(self, head_sha: str, base_sha: str, *, head_ref: str, number: int) -> PrInfo:
        return PrInfo(number, head_sha, head_ref, REPO, "main", base_sha)

    def caller_state(self) -> tuple[str, str, str, str]:
        return (
            git(self.clone, "rev-parse", "HEAD"),
            git(self.clone, "symbolic-ref", "HEAD"),
            git(self.clone, "status", "--porcelain"),
            git(self.clone, "worktree", "list", "--porcelain"),
        )

    def argvs(self) -> list[list[str]]:
        return [argv for argv, _ in self.runner.calls]


@pytest.fixture
def world(git_repo: Path, tmp_path: Path) -> World:
    origin = tmp_path / "acme" / "widget.git"
    author = tmp_path / "author"
    subprocess.run(["git", "clone", "-q", str(origin), str(author)], check=True, capture_output=True)
    git(author, "config", "user.name", "Author")
    git(author, "config", "user.email", "author@example.com")
    fake = FakeGh()
    return World(git_repo, origin, author, CompositeRunner(fake, git_repo), fake, tmp_path)


@dataclass
class Stack:
    """A dependent PR whose base PR was squash-merged, ready to land.

    ``stack_head`` is the base PR's final head, the merge base the refresh should
    use; ``older_head`` is an earlier commit of that PR, a wrong one.
    """

    info: PrInfo
    stack_head: str
    older_head: str
    base: str


def assert_plain_merge_conflicts(world: World, branch: str) -> None:
    """Positive control: without it every case below would be vacuous, the stack merging clean anyway."""
    git(world.author, "checkout", "-q", branch)
    plain = subprocess.run(
        ["git", "merge", "--no-edit", "main"], cwd=world.author, capture_output=True, text=True, check=False
    )
    assert plain.returncode != 0, "fixture is vacuous: a plain merge of main into the dependent does not conflict"
    git(world.author, "merge", "--abort")


def stacked(world: World, *, follow_up: bool = False, serve: str = "final") -> Stack:
    """PR A appends a block; PR B, cut from A, appends another at the same spot; A is squash-merged.

    With ``follow_up`` A gets a second commit after B was cut, which B merged by
    hand, so B carries A's final head as a merge commit's parent. *serve* picks
    which of A's commits ``refs/pull/<A>/head`` names: ``final`` or ``first``.
    """
    world.commit("main", "t.txt", LINES, "chore: t")
    world.branch("feat/a")
    a_first = world.commit("feat/a", "t.txt", LINES + BLOCK_A, "feat: a")
    world.branch("feat/b", "feat/a")
    b_head = world.commit("feat/b", "t.txt", LINES + BLOCK_A + BLOCK_B, "feat: b")
    a_head = a_first
    if follow_up:
        a_head = world.commit("feat/a", "t.txt", "one\n" + LINES[2:] + BLOCK_A, "fix: a follow-up")
        git(world.author, "checkout", "-q", "feat/b")
        git(world.author, "merge", "-q", "--no-edit", "feat/a")
        git(world.author, "push", "-q", "origin", "feat/b")
        b_head = git(world.author, "rev-parse", "HEAD")
    squash = world.squash("feat/a", "feat: a (#5)")
    assert git(world.author, "rev-parse", f"{squash}^{{tree}}") == git(world.author, "rev-parse", f"{a_head}^{{tree}}")
    assert_plain_merge_conflicts(world, "feat/b")
    world.publish(a_first if serve == "first" else a_head, A_PR)
    world.publish(b_head, B_PR)
    return Stack(world.info(b_head, squash, head_ref="feat/b", number=B_PR), a_head, a_first, squash)


def serve_squashed(world: World, stack: Stack) -> None:
    """Script GitHub's answers for the fixture: A merged as the squash commit.

    B is scripted merged too, though it is the PR being landed: only the
    self-exclusion keeps its own head, which refs/pull lists, from being picked.
    """
    world.serve_pr(A_PR, merged=True, merge_commit=stack.base)
    world.serve_pr(B_PR, merged=True, merge_commit=stack.base)


def run(world: World, stack: Stack, gate: str = "true", **kwargs: object) -> RefreshResult:
    before = world.caller_state()
    result = refresh_and_gate(world.runner, REPO, stack.info, gate=gate, **kwargs)
    assert world.caller_state() == before
    return result


def own_change_tree(world: World, base: str, old: str, new: str) -> str:
    """The tree of *base* with the diff ``old..new`` applied: what landing the dependent should produce."""
    git(world.author, "checkout", "-q", "-B", "expected", base)
    patch = subprocess.run(
        ["git", "diff", old, new], cwd=world.author, capture_output=True, text=True, check=True
    ).stdout
    git(world.author, "apply", "--index", "-", stdin=patch)
    return git(world.author, "write-tree")


def test_stacked_pr_refreshes_onto_a_squash_merged_base(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    """Guards against stopping on a conflict that vanishes once the base PR's final head is the merge base."""
    stack = stacked(world)
    serve_squashed(world, stack)
    marker = world.tmp / "gate-head"
    result = run(world, stack, gate=f"grep -q b1 t.txt && grep -q a1 t.txt && git rev-parse HEAD > {marker}")
    assert (result.exit_code, result.pushed, result.message) == (0, True, "")
    tip = result.tested_sha
    assert git(world.origin, "rev-parse", f"{tip}^1", f"{tip}^2").split() == [stack.info.head_sha, stack.base]
    assert git(world.origin, "rev-parse", f"{tip}^{{tree}}") == own_change_tree(
        world, stack.base, stack.stack_head, stack.info.head_sha
    )
    assert git(world.origin, "diff", stack.base, tip) == git(world.origin, "diff", stack.stack_head, stack.info.head_sha)
    assert world.origin_ref("feat/b") == tip
    assert marker.read_text(encoding="utf-8").strip() == tip
    assert f"stack: refreshed with PR #{A_PR} head {stack.stack_head[:7]} as merge base" in capsys.readouterr().err


def test_stacked_pr_with_a_follow_up_commit_refreshes(world: World) -> None:
    """Guards against a stack base that only works when the head carries the base PR's first commit."""
    stack = stacked(world, follow_up=True)
    serve_squashed(world, stack)
    result = run(world, stack)
    assert (result.exit_code, result.pushed) == (0, True)
    assert git(world.origin, "rev-parse", f"{result.tested_sha}^{{tree}}") == own_change_tree(
        world, stack.base, stack.stack_head, stack.info.head_sha
    )


def test_own_pr_head_is_never_its_own_stack_base(world: World) -> None:
    """Guards against a PR's own head, which refs/pull lists too, being picked as the base it refreshes onto."""
    stack = stacked(world)
    serve_squashed(world, stack)
    result = run(world, stack)
    assert (result.exit_code, result.pushed) == (0, True)
    assert not [a for a in world.argvs() if a[:3] == ["gh", "api", f"repos/{REPO}/pulls/{B_PR}"]]


def chained(world: World, *, b_merged: bool = True) -> Stack:
    """A, B (cut from A) and C (cut from B) with A then B squash-merged: C lands against main.

    With ``b_merged`` false B is never landed (GitHub reports it unmerged), so A's
    final head is the only usable stack base.
    """
    world.commit("main", "t.txt", LINES, "chore: t")
    world.branch("feat/a")
    a_head = world.commit("feat/a", "t.txt", LINES + BLOCK_A, "feat: a")
    world.branch("feat/b", "feat/a")
    b_head = world.commit("feat/b", "t.txt", LINES + BLOCK_A + BLOCK_B, "feat: b")
    world.branch("feat/c", "feat/b")
    c_head = world.commit("feat/c", "t.txt", LINES + BLOCK_A + BLOCK_B + BLOCK_C, "feat: c")
    squash_a = world.squash("feat/a", "feat: a (#5)")
    squash_b = world.squash("feat/b", "feat: b (#6)") if b_merged else squash_a
    assert_plain_merge_conflicts(world, "feat/c")
    world.publish(a_head, A_PR)
    world.publish(b_head, B_PR)
    world.publish(c_head, C_PR)
    world.serve_pr(A_PR, merged=True, merge_commit=squash_a)
    world.serve_pr(B_PR, merged=b_merged, merge_commit=squash_b)
    stack_head = b_head if b_merged else a_head
    return Stack(world.info(c_head, squash_b, head_ref="feat/c", number=C_PR), stack_head, a_head, squash_b)


def test_chain_refreshes_with_the_newest_merged_base(world: World) -> None:
    """Guards against picking the oldest candidate: in A<-B<-C, B's final head contains A's, not the reverse."""
    stack = chained(world)
    a_head, b_head = stack.older_head, stack.stack_head
    result = run(world, stack)
    assert (result.exit_code, result.pushed) == (0, True)
    merge_trees = [a for a in world.argvs() if a[:2] == ["git", "merge-tree"]]
    assert [f"--merge-base={b_head}" in a for a in merge_trees] == [True]
    assert not [a for a in merge_trees if f"--merge-base={a_head}" in a]
    assert git(world.origin, "rev-parse", f"{result.tested_sha}^{{tree}}") == own_change_tree(
        world, stack.base, b_head, stack.info.head_sha
    )
    assert git(world.origin, "diff", stack.base, result.tested_sha) == git(
        world.origin, "diff", b_head, stack.info.head_sha
    )


def test_unmerged_newest_candidate_is_skipped_for_an_older_merged_one(world: World) -> None:
    """Guards against an unmerged candidate ending the search: B is open, but A's head under it is a valid base."""
    stack = chained(world, b_merged=False)
    a_head, c_head = stack.stack_head, stack.info.head_sha
    result = run(world, stack)
    assert (result.exit_code, result.pushed, result.message) == (0, True, "")
    tip = result.tested_sha
    assert git(world.origin, "rev-parse", f"{tip}^1", f"{tip}^2").split() == [c_head, stack.base]
    assert git(world.origin, "rev-parse", f"{tip}^{{tree}}") == own_change_tree(world, stack.base, a_head, c_head)
    reads = [a[2] for a in world.argvs() if a[:2] == ["gh", "api"]]
    assert reads == [f"repos/{REPO}/pulls/{B_PR}", f"repos/{REPO}/pulls/{A_PR}"]
    merge_trees = [a for a in world.argvs() if a[:2] == ["git", "merge-tree"]]
    assert [f"--merge-base={a_head}" in a for a in merge_trees] == [True]


def test_ancestry_check_error_gives_up_without_trying_an_older_candidate(world: World) -> None:
    """Guards against a git error on the ancestry check reading as landed, or as a reason to try the next candidate."""
    stack = chained(world)
    # The prefix names the merge commit then the base: with base == B's merge commit, the earlier
    # head-contains-base call also starts with that sha, so a shorter prefix would hit it instead.
    prefix = ["git", "merge-base", "--is-ancestor", stack.base, stack.info.base_sha]
    world.runner.overlay(prefix, returncode=128)
    result = run(world, stack)
    assert (result.exit_code, result.pushed, result.message) == (2, False, TODAYS_REFUSAL)
    assert world.origin_ref("feat/c") == stack.info.head_sha
    assert [a for a in world.argvs() if a[: len(prefix)] == prefix] == [prefix]
    assert not [a for a in world.argvs() if a[:3] == ["gh", "api", f"repos/{REPO}/pulls/{A_PR}"]]
    assert not [a for a in world.argvs() if a[:2] == ["git", "merge-tree"]]


def test_candidate_pr_not_merged_keeps_todays_refusal(world: World) -> None:
    """Guards against treating an open or closed-unmerged PR as a squash-merged base."""
    stack = stacked(world)
    world.serve_pr(A_PR, merged=False, merge_commit=stack.base)
    result = run(world, stack)
    assert (result.exit_code, result.pushed, result.message) == (2, False, TODAYS_REFUSAL)
    assert world.origin_ref("feat/b") == stack.info.head_sha


def test_merge_commit_outside_the_base_keeps_todays_refusal(world: World) -> None:
    """Guards against accepting a merged PR whose merge commit is not in the base's history."""
    stack = stacked(world)
    world.serve_pr(A_PR, merged=True, merge_commit=stack.stack_head)
    result = run(world, stack)
    assert (result.exit_code, result.pushed, result.message) == (2, False, TODAYS_REFUSAL)
    assert world.origin_ref("feat/b") == stack.info.head_sha


def test_ordinary_conflict_keeps_todays_refusal(world: World) -> None:
    """Guards against the stack search changing the message, or leaving the scratch tree, on a plain conflict."""
    world.commit("main", "t.txt", LINES, "chore: t")
    world.branch("feat/x")
    head = world.commit("feat/x", "t.txt", LINES.replace("5\n", "five\n"), "feat: five")
    base = world.commit("main", "t.txt", LINES.replace("5\n", "FIVE\n"), "chore: FIVE")
    world.publish(world.origin_ref("main"), 9)
    info = world.info(head, base, head_ref="feat/x", number=B_PR)
    before = world.caller_state()
    result = refresh_and_gate(world.runner, REPO, info, gate="true")
    assert world.caller_state() == before
    assert (result.exit_code, result.pushed, result.message) == (2, False, TODAYS_REFUSAL)
    assert world.origin_ref("feat/x") == head
    assert not [a for a in world.argvs() if a[:2] == ["gh", "api"]]


def test_real_conflict_with_the_stack_base_refuses_and_names_it(world: World) -> None:
    """Guards against pushing a tree with conflict markers when main also changed the dependent's region."""
    stack = stacked(world)
    serve_squashed(world, stack)
    moved = world.commit("main", "t.txt", LINES + BLOCK_A + "m1\n", "chore: main moved")
    stack.info = world.info(stack.info.head_sha, moved, head_ref="feat/b", number=B_PR)
    result = run(world, stack)
    assert (result.exit_code, result.pushed) == (2, False)
    assert f"PR #{A_PR}" in result.message
    assert stack.stack_head in result.message
    assert "t.txt" in result.message
    assert world.origin_ref("feat/b") == stack.info.head_sha


def test_a_commit_the_base_already_has_is_never_a_stack_base(world: World) -> None:
    """Guards against the candidate walk covering all of the head's history, not just what only the head carries."""
    world.commit("main", "t.txt", LINES, "chore: t")
    fork = git(world.author, "rev-parse", "HEAD")
    world.branch("feat/x")
    head = world.commit("feat/x", "t.txt", LINES.replace("5\n", "five\n"), "feat: five")
    base = world.commit("main", "t.txt", LINES.replace("5\n", "FIVE\n"), "chore: FIVE")
    world.publish(fork, 9)
    world.serve_pr(9, merged=True, merge_commit=base)
    info = world.info(head, base, head_ref="feat/x", number=B_PR)
    result = refresh_and_gate(world.runner, REPO, info, gate="true")
    assert (result.exit_code, result.pushed, result.message) == (2, False, TODAYS_REFUSAL)
    assert world.origin_ref("feat/x") == head
    assert not [a for a in world.argvs() if a[:3] == ["gh", "api", f"repos/{REPO}/pulls/9"]]


def test_stack_repair_pushes_a_plain_fast_forward(world: World) -> None:
    """Guards against the repaired head being force-pushed, which would invalidate the CI run the land is pinned to."""
    stack = stacked(world)
    serve_squashed(world, stack)
    result = run(world, stack)
    assert (result.exit_code, result.pushed) == (0, True)
    pushes = [a for a in world.argvs() if a[:2] == ["git", "push"]]
    assert pushes == [["git", "push", "origin", "HEAD:refs/heads/feat/b"]]


def test_delta_beyond_the_dependents_own_change_refuses(world: World) -> None:
    """Guards against the patch-id check passing a repaired merge that carries more than the dependent's change."""
    stack = stacked(world, follow_up=True, serve="first")
    serve_squashed(world, stack)
    result = run(world, stack)
    assert (result.exit_code, result.pushed) == (2, False)
    assert "patch-id" in result.message
    assert world.origin_ref("feat/b") == stack.info.head_sha


@pytest.mark.parametrize("failure", ["ls-remote", "api", "shape"])
def test_stack_lookup_failure_keeps_todays_refusal(world: World, failure: str) -> None:
    """Guards against a failed ls-remote or pulls read raising, or being read as a stack, instead of falling back."""
    stack = stacked(world)
    if failure == "ls-remote":
        serve_squashed(world, stack)
        world.runner.overlay(["git", "ls-remote"], returncode=128)
    else:
        reply = http_error(502, "Bad Gateway") if failure == "api" else json_result(["not", "a", "pull"])
        world.fake.script(["gh", "api", f"repos/{REPO}/pulls/{A_PR}"], reply)
    result = run(world, stack)
    assert (result.exit_code, result.pushed, result.message) == (2, False, TODAYS_REFUSAL)
    assert world.origin_ref("feat/b") == stack.info.head_sha


def test_clean_refresh_never_looks_for_a_stack(world: World) -> None:
    """Guards against paying the ls-remote and pulls reads on a refresh that merged cleanly."""
    world.branch("feat/x")
    head = world.commit("feat/x", "a.txt", "a\n", "feat: a")
    base = world.commit("main", "b.txt", "b\n", "chore: b")
    info = world.info(head, base, head_ref="feat/x", number=B_PR)
    result = refresh_and_gate(world.runner, REPO, info, gate="true")
    assert (result.exit_code, result.pushed) == (0, True)
    argvs = world.argvs()
    assert not [a for a in argvs if a[:1] == ["gh"] or a[:2] == ["git", "ls-remote"] or a[:2] == ["git", "merge-tree"]]


class StubRunner:
    """Answers every argv with one canned Result."""

    def __init__(self, result: Result) -> None:
        self.result = result

    def run(self, argv: list[str], cwd: str | None = None) -> Result:
        return self.result


def test_pull_head_listing_skips_malformed_lines() -> None:
    """Guards against a stray line in ls-remote output raising or mapping a bogus PR."""
    sha_a, sha_b = "a" * 40, "b" * 40
    listing = "\n".join(
        [
            f"{sha_a}\trefs/pull/5/head",
            "garbage",
            f"{sha_b}\trefs/pull/x/head",
            "nothex\trefs/pull/8/head",
            f"{sha_b}\trefs/pull/9/head",
            f"{sha_b}\trefs/pull/12/head",
            "",
        ]
    )
    assert pr_land._pull_heads(StubRunner(Result(0, listing, ""))) == {sha_a: [5], sha_b: [12, 9]}
    assert pr_land._pull_heads(StubRunner(Result(128, listing, "fatal"))) is None
