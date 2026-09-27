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
from dataclasses import dataclass
from pathlib import Path

import pytest

import pr_land
from conftest import CompositeRunner, FakeClock, FakeGh, json_result
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
LEDGER = re.compile(r"^landed pr=\d+ tested=[0-9a-f]{40} gate=.+ checks=[0-9,]+ merge=[0-9a-f]{40}$")


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
            result = json_result([])
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
        if self.base_reads in self.base_moves:
            self.push_base()
        return json_result({"ref": "refs/heads/main", "object": {"sha": self.ref("main"), "type": "commit"}})

    def _check_runs(self) -> Result:
        runs = [
            {
                "id": run_id,
                "name": name,
                "status": "completed",
                "conclusion": self.conclusion,
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
        return Result(0, "", "")

    def _view(self) -> Result:
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
    return World(git_repo, origin, author, fake, hub, CompositeRunner(hub, git_repo), FakeClock())


def behind(world: World) -> tuple[str, str]:
    """A PR head one commit ahead of an older main; main has since moved on."""
    world.branch(HEAD_REF)
    head = world.commit(HEAD_REF, "a.txt", "a\n", "feat: a")
    base = world.commit("main", "b.txt", "b\n", "chore: b")
    return head, base


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


def test_merge_failure_after_base_moved_starts_a_new_round(world: World) -> None:
    """Guards against treating every merge failure as final, even when the base moved under it."""
    behind(world)
    world.hub.merge_failures = ["GraphQL: Base branch was modified. Review and try the merge again. (mergePullRequest)"]
    world.hub.base_moves = {3}
    assert land(world) == GREEN
    assert len(world.merges()) == 2
    assert len(world.refreshes()) == 2
    assert world.refreshes()[1][-1] == world.hub.pushed_bases[0]


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


def test_red_watch_returns_1_and_never_merges(world: World) -> None:
    """Guards against merging after a red watch."""
    behind(world)
    world.hub.conclusion = "failure"
    assert land(world) == RED
    assert world.watched()
    assert world.merges() == []
