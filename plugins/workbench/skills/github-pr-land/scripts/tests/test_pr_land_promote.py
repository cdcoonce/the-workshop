"""Tests for ``pr_land promote``: pinned-SHA fast-forward and bypass detection.

Each test's docstring names the defect it guards against. ``git`` runs for
real against a local bare origin; ``gh`` is a ``Hub`` wrapping the conftest
FakeGh that answers ``pulls/<pr>`` and ``branches/main`` from the bare origin
at call time, so the release tip and ``merged`` follow what the push really did.
"""

from __future__ import annotations

import re
import stat
import subprocess
from pathlib import Path

import pytest

import pr_land
from conftest import CompositeRunner, FakeClock, FakeGh, json_result
from pr_land import GREEN, INDETERMINATE, RED, Result, promote_pr

REPO = "acme/widget"
PR = 9
REPO_VIEW = ["gh", "repo", "view", "--json", "nameWithOwner"]
PULLS = f"repos/{REPO}/pulls/{PR}"
BRANCH = f"repos/{REPO}/branches/main"
PROTECTION = ["gh", "api", f"repos/{REPO}/branches/main/protection"]
CHECK_RUNS = re.compile(rf"repos/{REPO}/commits/[0-9a-f]{{40}}/check-runs\?per_page=100&page=1")
STATUSES = re.compile(rf"repos/{REPO}/commits/[0-9a-f]{{40}}/statuses\?per_page=100&page=1")
ACTIONS_APP = 15368
BYPASSED = "remote: Bypassed rule violations for refs/heads/main:"


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


class Hub:
    """A ``gh`` answering the PR and release-branch endpoints from the bare origin.

    ``merged`` reads true once origin's ``main`` is the PR head, as GitHub marks
    a PR merged when its head lands on the base. Everything else goes to the
    wrapped FakeGh, which also records every argv the hub answered.
    """

    def __init__(self, fake: FakeGh, origin: Path, head_sha: str) -> None:
        self.fake = fake
        self.origin = origin
        self.head_sha = head_sha
        self.head_ref = "dev"
        self.initial_main = self.main()
        self.stale_reads = 0
        self.never_merged = False
        self.conclusion = "success"

    def main(self) -> str:
        return git(self.origin, "rev-parse", "refs/heads/main")

    def run(self, argv: list[str], cwd: str | None = None) -> Result:
        endpoint = argv[2] if argv[:2] == ["gh", "api"] and len(argv) > 2 else ""
        if endpoint == PULLS:
            merged = not self.never_merged and self.main() == self.head_sha
            result = json_result(
                {
                    "number": PR,
                    "merged": merged,
                    "head": {"sha": self.head_sha, "ref": self.head_ref, "repo": {"full_name": REPO}},
                    "base": {"ref": "main", "sha": self.initial_main, "repo": {"full_name": REPO}},
                }
            )
        elif endpoint == BRANCH:
            tip = self.main()
            if tip != self.initial_main and self.stale_reads > 0:
                self.stale_reads -= 1
                tip = self.initial_main
            result = json_result({"name": "main", "commit": {"sha": tip}, "protected": True})
        elif CHECK_RUNS.fullmatch(endpoint):
            run = {
                "id": 5101,
                "name": "test",
                "status": "completed",
                "conclusion": self.conclusion,
                "check_suite": {"id": 5101},
                "app": {"id": ACTIONS_APP, "slug": "github-actions"},
            }
            result = json_result({"total_count": 1, "check_runs": [run]})
        elif STATUSES.fullmatch(endpoint):
            result = json_result([])
        else:
            return self.fake.run(argv, cwd=cwd)
        self.fake.calls.append(list(argv))
        return result


@pytest.fixture
def world(git_repo: Path) -> tuple[Hub, CompositeRunner, Path]:
    """A clone whose origin has ``dev`` one commit ahead of ``main``."""
    git(git_repo, "checkout", "-q", "-b", "dev")
    (git_repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    git(git_repo, "add", "feature.txt")
    git(git_repo, "commit", "-q", "-m", "feat: feature")
    git(git_repo, "push", "-q", "origin", "dev")
    origin = git_repo.parent / "acme" / "widget.git"
    fake = FakeGh()
    fake.script(REPO_VIEW, json_result({"nameWithOwner": REPO}))
    fake.script(
        PROTECTION,
        json_result({"required_status_checks": {"contexts": ["test"], "checks": [{"context": "test", "app_id": ACTIONS_APP}]}}),
    )
    hub = Hub(fake, origin, git(git_repo, "rev-parse", "HEAD"))
    return hub, CompositeRunner(hub, git_repo), origin


def promote(runner: CompositeRunner, clock: FakeClock, **kwargs: object) -> int:
    return promote_pr(runner, REPO, PR, clock=clock.clock, sleep=clock.sleep, **kwargs)


def pushes(runner: CompositeRunner) -> list[list[str]]:
    return [argv for argv, _ in runner.calls if argv[:2] == ["git", "push"]]


def test_happy_path_fast_forwards_release_to_the_pr_head(world, capsys) -> None:
    """Guards against a promote that does nothing and reports success."""
    hub, runner, origin = world
    code = promote(runner, FakeClock())
    assert code == GREEN
    assert hub.main() == hub.head_sha
    assert f"promoted pr={PR} sha={hub.head_sha}" in capsys.readouterr().out


def test_head_ref_other_than_trunk_refuses_without_pushing(world) -> None:
    """Guards against promoting a PR whose head is not the trunk branch."""
    hub, runner, origin = world
    hub.head_ref = "feat/x"
    assert promote(runner, FakeClock()) == INDETERMINATE
    assert pushes(runner) == []
    assert hub.main() == hub.initial_main


def test_release_tip_not_an_ancestor_refuses_as_not_a_fast_forward(world, capsys) -> None:
    """Guards against skipping the ancestor check and pushing a non-fast-forward."""
    hub, runner, origin = world
    clone = Path(runner.default_cwd)
    git(clone, "checkout", "-q", "-b", "hotfix", "origin/main")
    (clone / "hotfix.txt").write_text("hotfix\n", encoding="utf-8")
    git(clone, "add", "hotfix.txt")
    git(clone, "commit", "-q", "-m", "fix: hotfix")
    git(clone, "push", "-q", "origin", "HEAD:main")
    diverged = hub.main()
    hub.initial_main = diverged
    captured_code = promote(runner, FakeClock())
    captured = capsys.readouterr()
    assert captured_code == INDETERMINATE
    assert "not a fast-forward" in captured.out + captured.err
    assert pushes(runner) == []
    assert hub.main() == diverged


def test_red_watch_returns_1_and_never_pushes(world) -> None:
    """Guards against pushing a head whose own required checks are not green."""
    hub, runner, origin = world
    hub.conclusion = "failure"
    assert promote(runner, FakeClock()) == RED
    assert pushes(runner) == []
    assert hub.main() == hub.initial_main


def test_bypassed_rule_violations_exits_2_and_says_so(world, capsys) -> None:
    """Guards against reading a protection bypass on the push as a clean promotion."""
    hub, runner, origin = world
    runner.overlay(["git", "push"], append_stderr=f"{BYPASSED}\n")
    code = promote(runner, FakeClock())
    captured = capsys.readouterr()
    assert code == INDETERMINATE
    assert BYPASSED in captured.out + captured.err
    assert "protection was bypassed, not satisfied" in captured.out + captured.err
    assert "promoted" not in captured.out
    assert hub.main() == hub.head_sha


def test_poll_waits_for_the_release_branch_to_show_the_pushed_sha(world, capsys) -> None:
    """Guards against declaring success before ``branches/<release>`` shows the SHA."""
    hub, runner, origin = world
    hub.stale_reads = 2
    clock = FakeClock()
    assert promote(runner, clock, interval=15) == GREEN
    assert clock.sleeps == [15, 15]
    assert f"promoted pr={PR} sha={hub.head_sha}" in capsys.readouterr().out


def test_push_source_is_the_literal_head_sha(world) -> None:
    """Guards against pushing a ref name (``origin/dev``, ``HEAD``) instead of the tested SHA."""
    hub, runner, origin = world
    assert promote(runner, FakeClock()) == GREEN
    [argv] = pushes(runner)
    assert argv == ["git", "push", "origin", f"{hub.head_sha}:refs/heads/main"]
    source = argv[-1].split(":")[0]
    assert re.fullmatch(r"[0-9a-f]{40}", source) and source == hub.head_sha
    for arg in argv:
        assert "dev" not in arg and "origin/" not in arg and "HEAD" not in arg


def test_rejected_push_exits_2(world, capsys) -> None:
    """Guards against treating a push the origin rejected as a promotion."""
    hub, runner, origin = world
    hook = origin / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\necho 'rejected by test hook' >&2\nexit 1\n", encoding="utf-8")
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR)
    code = promote(runner, FakeClock())
    captured = capsys.readouterr()
    assert code == INDETERMINATE
    assert len(pushes(runner)) == 1
    assert "promoted" not in captured.out
    assert hub.main() == hub.initial_main


def test_pr_never_marked_merged_exits_2_at_the_deadline(world, capsys) -> None:
    """Guards against ignoring ``merged`` and promoting a PR GitHub never closed."""
    hub, runner, origin = world
    hub.never_merged = True
    clock = FakeClock()
    assert promote(runner, clock, timeout=60, interval=15) == INDETERMINATE
    assert sum(clock.sleeps) >= 60
    assert "promoted" not in capsys.readouterr().out


def test_no_argv_forces_or_bypasses(world) -> None:
    """Guards against a force push, a ``+`` refspec, ``--admin`` or ``--auto``."""
    hub, runner, origin = world
    runner.overlay(["git", "push"], append_stderr=f"{BYPASSED}\n")
    promote(runner, FakeClock())
    assert runner.calls
    for argv, _ in runner.calls:
        for arg in argv:
            assert not arg.startswith("--force") and arg != "-f"
            assert not arg.startswith("+")
            assert arg not in ("--admin", "--auto")


def test_cli_promote_resolves_repo_and_threads_its_flags(world, capsys) -> None:
    """Guards against the ``promote`` subcommand skipping ``resolve_repo`` or dropping ``--interval``."""
    hub, runner, origin = world
    hub.stale_reads = 1
    clock = FakeClock()
    code = pr_land.main(["promote", str(PR), "--interval", "7"], runner=runner, clock=clock.clock, sleep=clock.sleep)
    assert code == GREEN
    assert clock.sleeps == [7]
    assert hub.fake.calls[0] == REPO_VIEW
    assert f"promoted pr={PR} sha={hub.head_sha}" in capsys.readouterr().out
