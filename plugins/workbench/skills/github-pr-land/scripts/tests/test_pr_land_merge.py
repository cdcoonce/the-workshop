"""Tests for ``pr_land land``: wait, rounds, pinned merge, landed tree, ledger.

Each test's docstring names the defect it guards against. ``git`` runs for
real against a local bare origin; ``gh`` is a ``Hub`` responder wrapping the
conftest FakeGh. The refreshed head only exists at run time, so the hub answers
``pulls/<pr>`` and ``git/ref/heads/<base>`` from the bare origin at call time,
pushes new base commits before serving them, and on ``gh pr merge`` writes a
landing commit into the origin — a commit distinct from the tested head whose
tree equals it.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

import pr_land
from conftest import CompositeRunner, FakeClock, FakeGh, http_error, json_result
from pr_land import GREEN, INDETERMINATE, RED, Result, land_pr

REPO = "acme/widget"
PR = 7
HEAD_REF = "feat/x"
REPO_VIEW = ["gh", "repo", "view", "--json", "nameWithOwner"]
PULLS = f"repos/{REPO}/pulls/{PR}"
BASE_REF = f"repos/{REPO}/git/ref/heads/main"
CHECK_RUNS = re.compile(rf"repos/{REPO}/commits/([0-9a-f]{{40}})/check-runs\?per_page=100&page=1")
STATUSES = re.compile(rf"repos/{REPO}/commits/[0-9a-f]{{40}}/statuses\?per_page=100&page=1")
MERGE = ["gh", "pr", "merge"]
VIEW = ["gh", "pr", "view"]
ACTIONS_APP = 15368
RUN_IDS = (4101, 4102)
STATUS_IDS = (5101, 5102)
LEDGER = re.compile(
    r"^landed pr=\d+ tested=[0-9a-f]{40} gate=.+ checks=(?:\d+|status:\d+)(?:,(?:\d+|status:\d+))* merge=[0-9a-f]{40}$"
)


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


class Hub:
    """A ``gh`` that answers the PR, base and merge endpoints from the bare origin.

    Anything it does not answer itself goes to the wrapped FakeGh, which also
    records every argv the hub answered, so ``fake.calls`` is the full ``gh`` log.
    """

    def __init__(self, fake: FakeGh, origin: Path, author: Path) -> None:
        self.fake = fake
        self.origin = origin
        self.author = author
        self.frozen_base = git(origin, "rev-parse", "refs/heads/main")
        self.head_lag = 0
        self.base_moves: set[int] = set()
        self.base_reads = 0
        self.pushed_bases: list[str] = []
        self.conclusion = "success"
        self.merge_failures: list[str] = []
        self.lands = True
        self.land_base_tree = False
        self.merge_oid: str | None = None
        self.fail_after_landing: str | None = None
        self.on_merge: Callable[[], None] | None = None
        self.view_result: Result | None = None
        self.view_sequence: list[str | Result] | None = None
        self._view_calls = 0
        self.clock: FakeClock | None = None
        self.view_sleep_counts: list[int] = []
        self.base_read_failures: set[int] = set()
        self.serve_runs = True
        self.statuses: list[dict] = []
        self.pending_polls = 0
        self._served_head: str | None = None

    def ref(self, branch: str) -> str:
        return git(self.origin, "rev-parse", f"refs/heads/{branch}")

    def push_base(self) -> str:
        """Commit a new file to main in the author clone and push it to the origin."""
        git(self.author, "fetch", "-q", "origin")
        git(self.author, "checkout", "-q", "main")
        git(self.author, "reset", "-q", "--hard", "origin/main")
        name = f"base{len(self.pushed_bases) + 1}.txt"
        (self.author / name).write_text(f"{name}\n", encoding="utf-8")
        git(self.author, "add", name)
        git(self.author, "commit", "-q", "-m", f"chore: {name}")
        git(self.author, "push", "-q", "origin", "main")
        self.pushed_bases.append(git(self.author, "rev-parse", "HEAD"))
        return self.pushed_bases[-1]

    def run(self, argv: list[str], cwd: str | None = None) -> Result:
        endpoint = argv[2] if argv[:2] == ["gh", "api"] and len(argv) > 2 else ""
        if endpoint == PULLS:
            result = self._pull()
        elif endpoint == BASE_REF:
            result = self._base()
        elif CHECK_RUNS.fullmatch(endpoint):
            result = self._check_runs()
        elif STATUSES.fullmatch(endpoint):
            result = json_result(self.statuses)
        elif argv[:3] == MERGE:
            result = self._merge()
        elif argv[:3] == VIEW:
            result = self._view()
        else:
            return self.fake.run(argv, cwd=cwd)
        self.fake.calls.append(list(argv))
        return result

    def _pull(self) -> Result:
        live = self.ref(HEAD_REF)
        if self._served_head is not None and live != self._served_head and self.head_lag > 0:
            self.head_lag -= 1
        else:
            self._served_head = live
        return json_result(
            {
                "number": PR,
                "head": {"sha": self._served_head, "ref": HEAD_REF, "repo": {"full_name": REPO}},
                "base": {"ref": "main", "sha": self.frozen_base, "repo": {"full_name": REPO}},
            }
        )

    def _base(self) -> Result:
        self.base_reads += 1
        if self.base_reads in self.base_read_failures:
            return http_error(502, "Server Error")
        if self.base_reads in self.base_moves:
            self.push_base()
        return json_result({"ref": "refs/heads/main", "object": {"sha": self.ref("main"), "type": "commit"}})

    def _check_runs(self) -> Result:
        if not self.serve_runs:
            return json_result({"total_count": 0, "check_runs": []})
        pending = self.pending_polls > 0
        if pending:
            self.pending_polls -= 1
        runs = [
            {
                "id": run_id,
                "name": name,
                "status": "in_progress" if pending else "completed",
                "conclusion": None if pending else self.conclusion,
                "check_suite": {"id": run_id},
                "app": {"id": ACTIONS_APP, "slug": "github-actions"},
            }
            for run_id, name in zip(RUN_IDS, ("test", "lint"))
        ]
        return json_result({"total_count": len(runs), "check_runs": runs})

    def _merge(self) -> Result:
        if self.merge_failures:
            return Result(1, "", self.merge_failures.pop(0))
        if not self.lands:
            return Result(0, "", "")
        base = self.ref("main")
        tree = f"{base}^{{tree}}" if self.land_base_tree else f"{self.ref(HEAD_REF)}^{{tree}}"
        oid = git(
            self.origin, "-c", "user.name=Hub", "-c", "user.email=hub@example.com", "commit-tree", tree, "-p", base, "-m", "land"
        )
        git(self.origin, "update-ref", "refs/heads/main", oid)
        self.merge_oid = oid
        if self.on_merge is not None:
            self.on_merge()
        if self.fail_after_landing is not None:
            return Result(1, "", self.fail_after_landing)
        return Result(0, "", "")

    def _view(self) -> Result:
        if self.view_sequence is not None:
            if self.clock is not None:
                self.view_sleep_counts.append(len(self.clock.sleeps))
            index = min(self._view_calls, len(self.view_sequence) - 1)
            self._view_calls += 1
            entry = self.view_sequence[index]
            if isinstance(entry, Result):
                return entry
            if entry == "MERGED":
                return json_result({"state": "MERGED", "mergeCommit": {"oid": self.merge_oid}})
            return json_result({"state": entry, "mergeCommit": None})
        if self.view_result is not None:
            return self.view_result
        if self.merge_oid is None:
            return json_result({"state": "OPEN", "mergeCommit": None})
        return json_result({"state": "MERGED", "mergeCommit": {"oid": self.merge_oid}})


@dataclass
class World:
    clone: Path
    origin: Path
    author: Path
    fake: FakeGh
    hub: Hub
    runner: CompositeRunner
    clock: FakeClock

    def branch(self, name: str, start: str = "main") -> None:
        git(self.author, "branch", name, start)

    def commit(self, branch: str, path: str, content: str, message: str) -> str:
        git(self.author, "checkout", "-q", branch)
        (self.author / path).write_text(content, encoding="utf-8")
        git(self.author, "add", path)
        git(self.author, "commit", "-q", "-m", message)
        git(self.author, "push", "-q", "origin", branch)
        return git(self.author, "rev-parse", "HEAD")

    def gh_argvs(self) -> list[list[str]]:
        return [argv for argv, _ in self.runner.calls if argv[:1] == ["gh"]]

    def git_argvs(self) -> list[list[str]]:
        return [argv for argv, _ in self.runner.calls if argv[:1] == ["git"]]

    def merges(self) -> list[list[str]]:
        return [argv for argv in self.gh_argvs() if argv[:3] == MERGE]

    def refreshes(self) -> list[list[str]]:
        return [argv for argv in self.git_argvs() if argv[:3] == ["git", "merge", "--no-edit"]]

    def pushes(self) -> list[list[str]]:
        return [argv for argv in self.git_argvs() if argv[:2] == ["git", "push"]]

    def reads(self, endpoint: str) -> list[int]:
        return [i for i, argv in enumerate(self.gh_argvs()) if argv[:3] == ["gh", "api", endpoint]]

    def watched(self) -> bool:
        return any(CHECK_RUNS.fullmatch(argv[2]) for argv in self.gh_argvs() if argv[:2] == ["gh", "api"])

    def after_first_merge(self) -> tuple[list[int], list[int]]:
        """Indexes into ``gh_argvs()`` of the ``gh pr view`` calls and base reads after the first ``gh pr merge``."""
        gh_argvs = self.gh_argvs()
        merge_at = next(i for i, argv in enumerate(gh_argvs) if argv[:3] == MERGE)
        views = [i for i, argv in enumerate(gh_argvs) if i > merge_at and argv[:3] == VIEW]
        return views, [i for i in self.reads(BASE_REF) if i > merge_at]


@pytest.fixture
def world(git_repo: Path, tmp_path: Path) -> World:
    origin = tmp_path / "acme" / "widget.git"
    author = tmp_path / "author"
    subprocess.run(["git", "clone", "-q", str(origin), str(author)], check=True, capture_output=True)
    git(author, "config", "user.name", "Author")
    git(author, "config", "user.email", "author@example.com")
    fake = FakeGh()
    fake.script(REPO_VIEW, json_result({"nameWithOwner": REPO}))
    fake.script(
        ["gh", "api", f"repos/{REPO}/branches/main/protection"],
        json_result(
            {
                "required_status_checks": {
                    "strict": True,
                    "contexts": ["test", "lint"],
                    "checks": [{"context": c, "app_id": ACTIONS_APP} for c in ("test", "lint")],
                }
            }
        ),
    )
    hub = Hub(fake, origin, author)
    clock = FakeClock()
    hub.clock = clock
    return World(git_repo, origin, author, fake, hub, CompositeRunner(hub, git_repo), clock)


def behind(world: World) -> tuple[str, str]:
    """A PR head one commit ahead of an older main; main has since moved on."""
    world.branch(HEAD_REF)
    head = world.commit(HEAD_REF, "a.txt", "a\n", "feat: a")
    base = world.commit("main", "b.txt", "b\n", "chore: b")
    return head, base


def contexts_only(world: World) -> None:
    """Swap in a fresh FakeGh whose protection lists test and lint with no app pins, so statuses count."""
    fake = FakeGh()
    fake.script(REPO_VIEW, json_result({"nameWithOwner": REPO}))
    fake.script(
        ["gh", "api", f"repos/{REPO}/branches/main/protection"],
        json_result({"required_status_checks": {"strict": True, "contexts": ["test", "lint"]}}),
    )
    world.hub.fake = fake


def serve_statuses(world: World) -> None:
    world.hub.statuses = [{"id": sid, "context": name, "state": "success"} for sid, name in zip(STATUS_IDS, ("test", "lint"))]


def land(world: World, **kwargs: object) -> int:
    kwargs.setdefault("method", "squash")
    kwargs.setdefault("gate", "true")
    kwargs.setdefault("timeout", 60)
    kwargs.setdefault("interval", 15)
    return land_pr(world.runner, REPO, PR, clock=world.clock.clock, sleep=world.clock.sleep, **kwargs)


def ledger_lines(out: str) -> list[str]:
    return [line for line in out.splitlines() if line.startswith("landed ")]


# --- landing ------------------------------------------------------------------


def test_behind_pr_lands_end_to_end(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    """Guards against a land that does nothing and returns 0 without refreshing, merging or printing a ledger."""
    head, _ = behind(world)
    code = pr_land.main(
        ["land", str(PR), "--method", "squash", "--gate", "true", "--timeout", "60", "--interval", "15"],
        runner=world.runner,
        clock=world.clock.clock,
        sleep=world.clock.sleep,
    )
    out = capsys.readouterr().out
    assert code == GREEN
    tested = world.hub.ref(HEAD_REF)
    assert tested != head
    assert len(world.pushes()) == 1 and len(world.merges()) == 1
    assert world.watched()
    oid = world.hub.merge_oid
    assert oid is not None and oid != tested
    assert git(world.origin, "rev-parse", f"{oid}^{{tree}}") == git(world.origin, "rev-parse", f"{tested}^{{tree}}")
    assert ledger_lines(out) == [f"landed pr={PR} tested={tested} gate=exit 0 checks=4101,4102 merge={oid}"]


def test_merge_waits_for_pull_to_register_the_pushed_head(world: World) -> None:
    """Guards against merging before pulls/<pr> shows the pushed head, which pins the merge to a head GitHub has not seen."""
    behind(world)
    world.hub.head_lag = 2
    assert land(world) == GREEN
    tested = world.hub.ref(HEAD_REF)
    gh_argvs = world.gh_argvs()
    pulls = world.reads(PULLS)
    assert len(pulls) == 4  # read_pr, then stale, stale, registered
    assert len(world.merges()) == 1
    merge_at = next(i for i, argv in enumerate(gh_argvs) if argv[:3] == MERGE)
    assert merge_at > pulls[-1]
    assert world.clock.sleeps[:2] == [15, 15]
    assert tested in world.merges()[0]


def test_base_moved_after_watch_runs_a_second_round(world: World) -> None:
    """Guards against skipping the post-watch base re-check, which merges a head that no longer contains the live base."""
    behind(world)
    world.hub.base_moves = {2}
    assert land(world) == GREEN
    new_base = world.hub.pushed_bases[0]
    refreshes = world.refreshes()
    assert len(refreshes) == 2
    assert refreshes[1][-1] == new_base
    assert len(world.merges()) == 1
    assert git(world.origin, "merge-base", "--is-ancestor", new_base, world.hub.ref(HEAD_REF)) == ""


def test_base_moving_every_round_gives_up_after_max_rounds(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    """Guards against an off-by-one in max_rounds, which refreshes once more than allowed (or once fewer)."""
    behind(world)
    world.hub.base_moves = {2, 4, 6, 8}
    assert land(world) == INDETERMINATE
    assert "base moved 3 times" in capsys.readouterr().err
    assert len(world.refreshes()) == 3
    assert len(world.pushes()) == 3
    assert world.merges() == []


def test_every_base_decision_reads_the_live_ref(world: World) -> None:
    """Guards against deciding the base moved from pulls/<pr>.base.sha, which GitHub freezes and never updates."""
    behind(world)
    world.hub.base_moves = {2}
    assert land(world) == GREEN
    assert world.hub.frozen_base != world.hub.pushed_bases[0]
    assert len(world.reads(BASE_REF)) == 4  # read_pr and the re-check, in each of two rounds
    assert len(world.reads(PULLS)) == 4  # read_pr and one registration poll, in each of two rounds


def test_merge_failure_with_unchanged_base_echoes_stderr(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    """Guards against swallowing gh's stderr when the merge fails for a reason other than a moved base."""
    behind(world)
    reason = "X Pull request acme/widget#7 is not mergeable: the merge commit cannot be cleanly created."
    world.hub.merge_failures = [reason]
    assert land(world) == INDETERMINATE
    captured = capsys.readouterr()
    assert reason in captured.err
    assert len(world.merges()) == 1
    assert ledger_lines(captured.out) == []
    views, rereads = world.after_first_merge()
    assert views and rereads and views[0] < rereads[0]


def test_merge_failure_after_base_moved_starts_a_new_round(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    """Guards against treating every merge failure as final, even when the base moved under it, and against dropping gh's stderr before the new round."""
    behind(world)
    reason = "GraphQL: Base branch was modified. Review and try the merge again. (mergePullRequest)"
    world.hub.merge_failures = [reason]
    world.hub.base_moves = {3}
    assert land(world) == GREEN
    assert len(world.merges()) == 2
    assert len(world.refreshes()) == 2
    assert world.refreshes()[1][-1] == world.hub.pushed_bases[0]
    err = capsys.readouterr().err
    assert reason in err and "main moved during round 1" in err
    assert err.index(reason) < err.index("main moved during round 1")


def test_merge_failure_with_unreadable_base_echoes_stderr(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    """Guards against dropping gh's stderr when the merge fails and the base re-read after it is unreadable."""
    behind(world)
    reason = "X Pull request acme/widget#7 is not mergeable: the merge commit cannot be cleanly created."
    world.hub.merge_failures = [reason]
    world.hub.base_read_failures = {3}  # read_pr, the pre-merge re-check, then the post-merge re-read
    assert land(world) == INDETERMINATE
    captured = capsys.readouterr()
    assert "cannot read the tip of main" in captured.err
    assert reason in captured.err
    assert len(world.merges()) == 1 and len(world.refreshes()) == 1
    assert ledger_lines(captured.out) == []


def test_failed_merge_that_landed_does_not_start_a_new_round(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    """Guards against reading our own landing commit as a moved base when gh pr merge exits nonzero after merging, which starts a round on a merged PR."""
    behind(world)
    reason = "X Pull request acme/widget#7 was merged, but failed to delete branch feat/x: HTTP 422"
    world.hub.fail_after_landing = reason
    assert land(world) == GREEN
    captured = capsys.readouterr()
    tested = world.hub.ref(HEAD_REF)
    oid = world.hub.merge_oid
    assert oid is not None
    assert len(world.refreshes()) == 1 and len(world.pushes()) == 1 and len(world.merges()) == 1
    assert ledger_lines(captured.out) == [f"landed pr={PR} tested={tested} gate=exit 0 checks=4101,4102 merge={oid}"]
    assert f"gh pr merge exited 1 but the PR is MERGED: {reason}" in captured.err
    gh_argvs = world.gh_argvs()
    merge_at = next(i for i, argv in enumerate(gh_argvs) if argv[:3] == MERGE)
    assert gh_argvs[merge_at + 1][:3] == VIEW
    views, rereads = world.after_first_merge()
    assert rereads == []
    assert len(views) == 1


@pytest.mark.parametrize(
    ("view", "message"),
    [
        (json_result({"state": "CLOSED", "mergeCommit": None}), "pull request 7 is in state CLOSED after a failed gh pr merge"),
        (Result(1, "", "GraphQL: Could not resolve to a PullRequest\n"), "cannot read the state of pull request 7 after a failed gh pr merge"),
        (json_result({"mergeCommit": None}), "cannot read the state of pull request 7 after a failed gh pr merge"),
        (Result(0, "not json", ""), "cannot read the state of pull request 7 after a failed gh pr merge"),
    ],
    ids=["closed", "view-fails", "no-state", "unparseable"],
)
def test_merge_failure_with_pr_neither_merged_nor_open_exits_2(
    world: World, capsys: pytest.CaptureFixture[str], view: Result, message: str
) -> None:
    """Guards against a failed merge on a PR that is neither MERGED nor OPEN falling through to the base re-read and another round."""
    behind(world)
    reason = "X Pull request acme/widget#7 is closed"
    world.hub.merge_failures = [reason]
    world.hub.view_result = view
    world.hub.base_moves = {3}  # a post-merge re-read would see a moved base and start a round
    assert land(world) == INDETERMINATE
    captured = capsys.readouterr()
    assert message in captured.err
    assert reason in captured.err
    _, rereads = world.after_first_merge()
    assert rereads == []
    assert len(world.refreshes()) == 1
    assert ledger_lines(captured.out) == []


def test_lagging_open_view_is_reread_until_merged(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    """Guards against trusting a lagging OPEN view after a failed-but-landed merge, which starts a spurious round."""
    behind(world)
    reason = "X Pull request acme/widget#7 was merged, but failed to delete branch feat/x: HTTP 422"
    world.hub.fail_after_landing = reason
    world.hub.view_sequence = ["OPEN", "OPEN", "MERGED"]
    assert land(world, interval=7) == GREEN
    captured = capsys.readouterr()
    tested = world.hub.ref(HEAD_REF)
    oid = world.hub.merge_oid
    assert oid is not None
    assert len(world.refreshes()) == 1 and len(world.pushes()) == 1 and len(world.merges()) == 1
    views, _ = world.after_first_merge()
    assert len(views) == 3
    assert world.clock.sleeps == [7, 7]
    assert world.hub.view_sleep_counts == [0, 1, 2]
    failed_line = f"gh pr merge failed: {reason}"
    merged_line = f"gh pr merge exited 1 but the PR is MERGED: {reason}"
    assert failed_line in captured.err
    assert merged_line in captured.err
    assert captured.err.index(failed_line) < captured.err.index(merged_line)
    assert ledger_lines(captured.out) == [f"landed pr={PR} tested={tested} gate=exit 0 checks=4101,4102 merge={oid}"]


@pytest.mark.parametrize("max_rounds", [3, 2])
def test_persistently_open_view_after_landing_starts_a_new_round(
    world: World, capsys: pytest.CaptureFixture[str], max_rounds: int
) -> None:
    """Guards against re-reading forever (or not re-reading at all) when GitHub's view never catches up to our own landing.

    Parametrized over ``max_rounds`` (the round budget, unrelated to the fixed
    3-re-read bound) to guard against the re-read loop mistakenly using
    ``max_rounds`` instead of its own hardcoded 3: with the default 3 the two
    numbers coincide, so only ``max_rounds=2`` tells them apart.
    """
    behind(world)
    reason = "X Pull request acme/widget#7 was merged, but failed to delete branch feat/x: HTTP 422"
    world.hub.fail_after_landing = reason
    world.hub.view_sequence = ["OPEN"]
    assert land(world, max_rounds=max_rounds) == INDETERMINATE
    captured = capsys.readouterr()
    views, base_reads_after = world.after_first_merge()
    assert len(views) == 4
    assert world.clock.sleeps == [15, 15, 15]
    assert world.hub.view_sleep_counts == [0, 1, 2, 3]
    # Exactly the post-merge-failure re-check and round 2's fresh read_pr — no
    # extra _base_moved call once the re-read loop exhausts.
    assert len(base_reads_after) == 2
    assert "main moved during round 1" in captured.err
    assert "the PR's delta is empty on one side of the refresh; the base already contains it" in captured.err
    assert len(world.refreshes()) == 2
    assert len(world.pushes()) == 1
    assert len(world.merges()) == 1
    assert ledger_lines(captured.out) == []


@pytest.mark.parametrize(
    "setup",
    ["unchanged", "unreadable"],
)
def test_open_after_merge_is_not_reread_when_base_did_not_move(
    world: World, capsys: pytest.CaptureFixture[str], setup: str
) -> None:
    """Guards against re-reading a lagging view when the base recheck itself was unchanged or unreadable, not moved."""
    behind(world)
    reason = "X Pull request acme/widget#7 is not mergeable: the merge commit cannot be cleanly created."
    world.hub.merge_failures = [reason]
    if setup == "unreadable":
        world.hub.base_read_failures = {3}  # read_pr, the pre-merge re-check, then the post-merge re-read
    assert land(world) == INDETERMINATE
    captured = capsys.readouterr()
    assert reason in captured.err
    views, _ = world.after_first_merge()
    assert len(views) == 1
    assert world.clock.sleeps == []
    assert len(world.merges()) == 1
    assert ledger_lines(captured.out) == []


@pytest.mark.parametrize(
    ("view", "message"),
    [
        ("CLOSED", "pull request 7 is in state CLOSED after a failed gh pr merge"),
        (Result(1, "", "GraphQL: Could not resolve to a PullRequest\n"), "cannot read the state of pull request 7 after a failed gh pr merge"),
    ],
    ids=["closed", "view-fails"],
)
def test_reread_turning_non_open_non_merged_exits_2(
    world: World, capsys: pytest.CaptureFixture[str], view: str | Result, message: str
) -> None:
    """Guards against a re-read that turns CLOSED or unreadable being treated as still OPEN, which would keep re-reading or start a round."""
    behind(world)
    reason = "X Pull request acme/widget#7 is closed"
    world.hub.merge_failures = [reason]
    world.hub.base_moves = {3}
    world.hub.view_sequence = ["OPEN", view]
    assert land(world) == INDETERMINATE
    captured = capsys.readouterr()
    assert message in captured.err
    assert reason in captured.err
    views, _ = world.after_first_merge()
    assert len(views) == 2
    assert world.clock.sleeps == [15]
    assert len(world.refreshes()) == 1
    assert ledger_lines(captured.out) == []


def test_landed_tree_differing_from_tested_tree_exits_2(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    """Guards against skipping the landed-tree check, which reports a land whose tree was never tested."""
    behind(world)
    world.hub.land_base_tree = True
    assert land(world) == INDETERMINATE
    captured = capsys.readouterr()
    oid = world.hub.merge_oid
    landed = git(world.origin, "rev-parse", f"{oid}^{{tree}}")
    tested = git(world.origin, "rev-parse", f"{world.hub.ref(HEAD_REF)}^{{tree}}")
    assert landed != tested
    assert "LANDED TREE DIFFERS FROM TESTED TREE" in captured.err
    assert landed in captured.err and tested in captured.err
    assert ledger_lines(captured.out) == []


def test_ledger_line_names_tested_head_checks_and_merge(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    """Guards against a ledger that names the pre-refresh head, other checks, or anything but the landing commit."""
    behind(world)
    assert land(world) == GREEN
    lines = ledger_lines(capsys.readouterr().out)
    assert len(lines) == 1 and LEDGER.fullmatch(lines[0])
    assert f"tested={world.hub.ref(HEAD_REF)} " in lines[0]
    assert lines[0].endswith(f" merge={world.hub.merge_oid}")
    assert " checks=4101,4102 " in lines[0]


def test_failed_merge_that_landed_a_different_tree_exits_2(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    """Guards against the failed-but-landed path printing the ledger without comparing the landed tree to the tested tree."""
    behind(world)
    world.hub.fail_after_landing = "X Pull request acme/widget#7 was merged, but failed to delete branch feat/x: HTTP 422"
    world.hub.land_base_tree = True
    assert land(world) == INDETERMINATE
    captured = capsys.readouterr()
    assert "LANDED TREE DIFFERS FROM TESTED TREE" in captured.err
    assert ledger_lines(captured.out) == []
    _, rereads = world.after_first_merge()
    assert rereads == []
    assert len(world.refreshes()) == 1


def test_failed_merge_whose_merged_view_names_no_merge_commit_exits_2(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Guards against a MERGED view with no mergeCommit after a failed merge falling through to the base re-read."""
    behind(world)
    world.hub.fail_after_landing = "X Pull request acme/widget#7 was merged, but failed to delete branch feat/x: HTTP 422"
    world.hub.view_result = json_result({"state": "MERGED", "mergeCommit": None})
    assert land(world) == INDETERMINATE
    captured = capsys.readouterr()
    assert "is MERGED but names no mergeCommit" in captured.err
    assert ledger_lines(captured.out) == []
    _, rereads = world.after_first_merge()
    assert rereads == []
    assert len(world.refreshes()) == 1


def test_statuses_only_green_names_status_ids_in_checks(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    """Guards against an empty checks= when the required names are satisfied only by commit statuses."""
    behind(world)
    contexts_only(world)
    world.hub.serve_runs = False
    serve_statuses(world)
    assert land(world) == GREEN
    (line,) = ledger_lines(capsys.readouterr().out)
    assert LEDGER.fullmatch(line)
    assert re.search(r" checks=status:\d+(,status:\d+)* ", line)
    assert " checks= " not in line and " checks=status:5101,status:5102 " in line


def test_ledger_checks_list_runs_then_statuses(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    """Guards against interleaving or reordering checks=, which must list every run id before every status id."""
    behind(world)
    contexts_only(world)
    serve_statuses(world)
    assert land(world) == GREEN
    (line,) = ledger_lines(capsys.readouterr().out)
    assert LEDGER.fullmatch(line)
    assert " checks=4101,4102,status:5101,status:5102 " in line


def test_watch_gets_a_fresh_timeout_after_registration(world: World) -> None:
    """Guards against the watch inheriting only the time left after head registration instead of its own --timeout."""
    behind(world)
    world.hub.head_lag = 3  # registration polls at 0, 15, 30, 45 of a 60 s timeout
    world.hub.pending_polls = 2  # pending at 45 and 60: past the 15 s left, well inside a fresh 60 s
    assert land(world, timeout=60, interval=15) == GREEN
    assert world.clock.now - 1000.0 > 60
    assert len(world.merges()) == 1


@pytest.mark.parametrize("side", ["landed", "tested", "both"])
def test_unreadable_tree_is_not_a_mismatch(world: World, capsys: pytest.CaptureFixture[str], side: str) -> None:
    """Guards against reporting a tree git could not read as LANDED TREE DIFFERS with a None tree id, and against checking the tested side first."""
    behind(world)
    unreadable: dict[str, str] = {}

    def break_tree() -> None:
        shas = {"landed": world.hub.merge_oid, "tested": world.hub.ref(HEAD_REF)}
        for name, sha in shas.items():
            assert sha is not None
            if side in (name, "both"):
                unreadable[name] = sha
                world.runner.overlay(["git", "rev-parse", f"{sha}^{{tree}}"], returncode=128)

    world.hub.on_merge = break_tree
    assert land(world) == INDETERMINATE
    captured = capsys.readouterr()
    named = unreadable["tested" if side == "tested" else "landed"]
    assert f"cannot read tree for {named}" in captured.err
    if side == "both":
        assert f"cannot read tree for {unreadable['tested']}" not in captured.err
    assert "LANDED TREE DIFFERS" not in captured.err
    assert ledger_lines(captured.out) == []


@pytest.mark.parametrize("method", ["merge", "squash", "rebase"])
def test_merge_is_pinned_to_the_tested_head(world: World, method: str) -> None:
    """Guards against dropping --match-head-commit, which lets a head pushed after the watch merge untested."""
    behind(world)
    assert land(world, method=method) == GREEN
    (argv,) = world.merges()
    tested = world.hub.ref(HEAD_REF)
    assert argv[:4] == ["gh", "pr", "merge", str(PR)]
    assert f"--{method}" in argv
    assert argv[argv.index("--match-head-commit") + 1] == tested
    assert argv[argv.index("-R") + 1] == REPO


def test_no_argv_bypasses_protection_or_queues_a_merge(world: World) -> None:
    """Guards against --admin or --auto anywhere, which bypasses protection or hands the merge to GitHub unpinned."""
    behind(world)
    assert land(world) == GREEN
    for argv, _ in world.runner.calls:
        assert "--admin" not in argv and "--auto" not in argv


# --- refusing -----------------------------------------------------------------


def test_origin_that_differs_from_gh_repo_refuses(world: World) -> None:
    """Guards against landing before resolve_repo, which merges a PR in a repo the clone's origin is not."""
    behind(world)
    fake = FakeGh()
    fake.script(REPO_VIEW, json_result({"nameWithOwner": "someone/else"}))
    world.hub.fake = fake
    code = pr_land.main(
        ["land", str(PR), "--method", "squash", "--gate", "true"],
        runner=world.runner,
        clock=world.clock.clock,
        sleep=world.clock.sleep,
    )
    assert code == INDETERMINATE
    assert not any("pulls/" in arg for argv in world.gh_argvs() for arg in argv)
    assert world.merges() == []


def test_head_never_registered_exits_2_at_deadline(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    """Guards against proceeding to watch and merge when the registration poll times out."""
    behind(world)
    world.hub.head_lag = 10**6
    assert land(world, timeout=60, interval=15) == INDETERMINATE
    assert "timed out" in capsys.readouterr().err
    assert world.clock.now - 1000.0 == 60
    assert not world.watched()
    assert world.merges() == []


def test_refresh_conflict_stops_before_watch_and_merge(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    """Guards against carrying on after refresh_and_gate refuses, which watches and merges the un-refreshed head."""
    world.branch(HEAD_REF)
    world.commit(HEAD_REF, "a.txt", "ours\n", "feat: a")
    world.commit("main", "a.txt", "theirs\n", "chore: a")
    assert land(world) == INDETERMINATE
    assert "conflicts" in capsys.readouterr().err
    assert not world.watched()
    assert world.merges() == []


def test_open_after_merge_call_exits_2_without_ledger(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    """Guards against trusting gh pr merge's exit code when the PR is still OPEN afterwards."""
    behind(world)
    world.hub.lands = False
    assert land(world) == INDETERMINATE
    captured = capsys.readouterr()
    assert "state OPEN" in captured.err
    assert ledger_lines(captured.out) == []


@pytest.mark.parametrize("missing", ["--method", "--gate"])
def test_land_requires_method_and_gate(world: World, missing: str) -> None:
    """Guards against defaulting --method or --gate, which merges by a method or gate nobody chose."""
    argv = ["land", str(PR), "--method", "squash", "--gate", "true"]
    flag = argv.index(missing)
    del argv[flag : flag + 2]
    with pytest.raises(SystemExit) as exc:
        pr_land.main(argv, runner=world.runner, clock=world.clock.clock, sleep=world.clock.sleep)
    assert exc.value.code == 2
    assert world.runner.calls == []


@pytest.mark.parametrize("rounds", ["0", "-1", "abc"])
def test_max_rounds_below_one_is_rejected_before_any_call(
    world: World, capsys: pytest.CaptureFixture[str], rounds: str
) -> None:
    """Guards against accepting --max-rounds 0, which runs no round and reports "base moved 0 times", or a non-integer."""
    argv = ["land", str(PR), "--method", "squash", "--gate", "true", "--max-rounds", rounds]
    with pytest.raises(SystemExit) as exc:
        pr_land.main(argv, runner=world.runner, clock=world.clock.clock, sleep=world.clock.sleep)
    assert exc.value.code == 2
    assert world.runner.calls == []
    assert "at least 1" in capsys.readouterr().err


def test_red_watch_returns_1_and_never_merges(world: World) -> None:
    """Guards against merging after a red watch."""
    behind(world)
    world.hub.conclusion = "failure"
    assert land(world) == RED
    assert world.watched()
    assert world.merges() == []
