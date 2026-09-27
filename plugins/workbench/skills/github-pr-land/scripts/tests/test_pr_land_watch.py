"""Tests for ``pr_land watch``: waiting on one exact SHA's required checks.

Each test's docstring names the defect it guards against. ``gh`` is the
scripted FakeGh from conftest, so any endpoint the code was never meant to read
raises; ``git`` runs for real against a local bare origin.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

import pr_land
from conftest import CompositeRunner, FakeClock, FakeGh, http_error, json_result
from pr_land import GREEN, INDETERMINATE, RED, Result

REPO = "acme/widget"
ACTIONS_APP = 15368
OTHER_APP = 99999
REPO_VIEW = ["gh", "repo", "view", "--json", "nameWithOwner"]


@dataclass
class World:
    fake: FakeGh
    runner: CompositeRunner
    clock: FakeClock
    sha: str
    clone: Path


@pytest.fixture
def world(git_repo: Path) -> World:
    fake = FakeGh()
    fake.script(REPO_VIEW, json_result({"nameWithOwner": REPO}))
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=git_repo, capture_output=True, text=True, check=True
    ).stdout.strip()
    return World(fake=fake, runner=CompositeRunner(fake, git_repo), clock=FakeClock(), sha=sha, clone=git_repo)


def checks_argv(sha: str, page: int = 1) -> list[str]:
    return ["gh", "api", f"repos/{REPO}/commits/{sha}/check-runs?per_page=100&page={page}"]


def statuses_argv(sha: str, page: int = 1) -> list[str]:
    return ["gh", "api", f"repos/{REPO}/commits/{sha}/statuses?per_page=100&page={page}"]


def protection_argv(branch: str = "dev") -> list[str]:
    return ["gh", "api", f"repos/{REPO}/branches/{branch}/protection"]


def check_run(
    run_id: int,
    *,
    name: str = "test",
    suite: int = 1,
    conclusion: str | None = "success",
    status: str = "completed",
    app_id: int = ACTIONS_APP,
) -> dict:
    return {
        "id": run_id,
        "name": name,
        "status": status,
        "conclusion": conclusion if status == "completed" else None,
        "check_suite": {"id": suite},
        "app": {"id": app_id, "slug": "github-actions"},
    }


def commit_status(status_id: int, *, context: str = "test", state: str = "success") -> dict:
    return {"id": status_id, "context": context, "state": state}


def runs_page(*runs: dict) -> Result:
    return json_result({"total_count": len(runs), "check_runs": list(runs)})


def protected(*contexts: str, app_id: int | None = ACTIONS_APP) -> Result:
    return json_result(
        {
            "required_status_checks": {
                "strict": True,
                "contexts": list(contexts),
                "checks": [{"context": c, "app_id": app_id} for c in contexts],
            }
        }
    )


def script_ci(world: World, *polls: list[dict], statuses: list[dict] | None = None) -> None:
    """Script one check-runs page per poll, and a single statuses page."""
    world.fake.script(checks_argv(world.sha), *(runs_page(*runs) for runs in polls))
    world.fake.script(statuses_argv(world.sha), json_result(statuses if statuses is not None else []))


def watch(world: World, sha: str | None = None, **kwargs: object) -> pr_land.WatchResult:
    kwargs.setdefault("timeout", 60)
    kwargs.setdefault("interval", 15)
    return pr_land.watch_sha(
        world.runner,
        REPO,
        sha if sha is not None else world.sha,
        clock=world.clock.clock,
        sleep=world.clock.sleep,
        **kwargs,
    )


def gh_argvs(world: World) -> list[list[str]]:
    return [argv for argv, _cwd in world.runner.calls if argv[:1] == ["gh"]]


# --- deciding -----------------------------------------------------------------


def test_required_name_with_nothing_reported_times_out_indeterminate(world: World) -> None:
    """Guards against zero runs reading as green: a required check that never reported must pend, then exit 2."""
    script_ci(world, [])
    result = watch(world, require=["test"])
    assert result.code == INDETERMINATE
    assert world.clock.sleeps, "a required name with nothing reported must be polled again, not decided"
    assert world.clock.now >= 1000.0 + 60


def test_green_check_runs_pass_without_reading_combined_status(world: World) -> None:
    """Guards against reading the combined state, which on these repos reads pending with total_count 0 forever.

    The combined-status endpoint is deliberately left unscripted, so reading it
    raises in the FakeGh.
    """
    script_ci(world, [check_run(11)])
    world.fake.script(protection_argv(), protected("test"))
    assert watch(world, branch="dev").code == GREEN
    assert not any(argv[2].endswith("/status") for argv in gh_argvs(world) if argv[1] == "api")


def test_neutral_conclusion_is_indeterminate(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    """Guards against a neutral run being counted as a pass."""
    script_ci(world, [check_run(21, conclusion="neutral")])
    assert watch(world, require=["test"]).code == INDETERMINATE
    assert "test suite=1 run=21 neutral" in capsys.readouterr().out


def test_failure_in_one_suite_is_not_hidden_by_green_in_another(world: World) -> None:
    """Guards against keeping only the latest run per name, which lets a newer green suite mask a failed one."""
    script_ci(world, [check_run(31, suite=1, conclusion="failure"), check_run(32, suite=2)])
    assert watch(world, require=["test"]).code == RED


def test_newer_rerun_in_same_suite_replaces_older_failure(world: World) -> None:
    """Guards against judging a suite by its oldest run instead of its latest re-run."""
    script_ci(world, [check_run(42, suite=1), check_run(41, suite=1, conclusion="failure")])
    assert watch(world, require=["test"]).code == GREEN


def test_waits_for_pending_rerun_before_deciding_red(world: World) -> None:
    """Guards against deciding red while another required check is still pending: a re-run can still replace the failure."""
    script_ci(
        world,
        [check_run(51, name="lint", suite=1, conclusion="failure"), check_run(52, suite=2, status="in_progress")],
        [check_run(53, name="lint", suite=1), check_run(51, name="lint", suite=1, conclusion="failure"), check_run(52, suite=2)],
    )
    assert watch(world, require=["lint", "test"]).code == GREEN
    assert world.clock.sleeps == [15]


@pytest.mark.parametrize(
    ("kind", "outcome", "expected"),
    [
        ("run", "failure", RED),
        ("run", "cancelled", RED),
        ("run", "timed_out", RED),
        ("run", "action_required", RED),
        ("run", "startup_failure", RED),
        ("status", "failure", RED),
        ("status", "error", RED),
        ("run", "skipped", INDETERMINATE),
        ("run", "stale", INDETERMINATE),
    ],
)
def test_terminal_outcomes_map_to_exit_codes(world: World, kind: str, outcome: str, expected: int) -> None:
    """Guards against a terminal red or indeterminate outcome being mapped to the wrong exit code."""
    if kind == "run":
        script_ci(world, [check_run(61, conclusion=outcome)])
    else:
        script_ci(world, [], statuses=[commit_status(62, state=outcome)])
    assert watch(world, require=["test"]).code == expected


def test_unrecognized_conclusion_is_indeterminate(world: World) -> None:
    """Guards against an unknown conclusion GitHub may add later being read as a pass."""
    script_ci(world, [check_run(71, conclusion="brand_new_conclusion")])
    assert watch(world, require=["test"]).code == INDETERMINATE


# --- required names -----------------------------------------------------------


def test_unprotected_branch_without_require_refuses(world: World) -> None:
    """Guards against an empty required set passing vacuously: nothing to wait on is not green."""
    world.fake.script(protection_argv(), http_error(404, "Branch not protected"))
    script_ci(world, [check_run(81)])
    assert watch(world, branch="dev").code == INDETERMINATE


def test_unprotected_branch_with_require_uses_the_required_names(world: World) -> None:
    """Guards against treating "Branch not protected" as a failure instead of contributing no names."""
    world.fake.script(protection_argv(), http_error(404, "Branch not protected"))
    script_ci(world, [check_run(91)])
    assert watch(world, branch="dev", require=["test"]).code == GREEN


def test_protection_server_error_refuses(world: World) -> None:
    """Guards against a failed protection read being treated as an unprotected branch."""
    world.fake.script(protection_argv(), http_error(500, "Server Error"))
    script_ci(world, [check_run(101)])
    assert watch(world, branch="dev", require=["test"]).code == INDETERMINATE


def test_protection_not_found_is_not_unprotected(world: World) -> None:
    """Guards against any 404 reading as unprotected: "Not Found" means no access or no branch, not no rules."""
    world.fake.script(protection_argv(), http_error(404, "Not Found"))
    script_ci(world, [check_run(111)])
    assert watch(world, branch="dev", require=["test"]).code == INDETERMINATE


def test_require_adds_to_protection_instead_of_replacing_it(world: World) -> None:
    """Guards against --require overriding the protection contexts, so a protected check nobody ran passes."""
    world.fake.script(protection_argv(), protected("test"))
    script_ci(world, [check_run(121, name="lint")])
    assert watch(world, branch="dev", require=["lint"]).code == INDETERMINATE
    assert world.clock.sleeps


def test_run_from_another_app_does_not_satisfy_a_pinned_name(world: World) -> None:
    """Guards against ignoring the protection app_id, so any app can post a green `test`."""
    world.fake.script(protection_argv(), protected("test"))
    script_ci(world, [check_run(131, app_id=OTHER_APP)])
    assert watch(world, branch="dev").code == INDETERMINATE
    assert world.clock.sleeps


def test_null_app_id_accepts_any_app(world: World) -> None:
    """Guards against a null app_id pin being read as "no app matches"."""
    world.fake.script(protection_argv(), protected("test", app_id=None))
    script_ci(world, [check_run(141, app_id=OTHER_APP)])
    assert watch(world, branch="dev").code == GREEN


def test_status_success_satisfies_an_unpinned_name(world: World) -> None:
    """Guards against ignoring commit statuses, which some required checks report through instead of check runs."""
    script_ci(world, [], statuses=[commit_status(151)])
    result = watch(world, require=["test"])
    assert result.code == GREEN
    assert result.status_ids == [151]


def test_status_never_satisfies_an_app_pinned_name(world: World) -> None:
    """Guards against a status from any poster satisfying a name protection pins to one app."""
    world.fake.script(protection_argv(), protected("test"))
    script_ci(world, [], statuses=[commit_status(161)])
    assert watch(world, branch="dev").code == INDETERMINATE


def test_latest_status_per_context_wins(world: World) -> None:
    """Guards against judging a context by an older status instead of the newest-first head of the list."""
    script_ci(world, [], statuses=[commit_status(172), commit_status(171, state="failure")])
    assert watch(world, require=["test"]).code == GREEN


# --- reading ------------------------------------------------------------------


def test_required_run_on_second_page_is_found(world: World) -> None:
    """Guards against reading only the first page of check runs."""
    filler = [check_run(1000 + i, name=f"other-{i}", suite=500 + i) for i in range(100)]
    world.fake.script(checks_argv(world.sha, 1), runs_page(*filler))
    world.fake.script(checks_argv(world.sha, 2), runs_page(check_run(181)))
    world.fake.script(statuses_argv(world.sha), json_result([]))
    assert watch(world, require=["test"]).code == GREEN


def test_abbreviated_sha_is_expanded(world: World) -> None:
    """Guards against querying GitHub with an abbreviated SHA, which the API rejects."""
    script_ci(world, [check_run(191)])
    assert watch(world, world.sha[:7], require=["test"]).code == GREEN


@pytest.mark.parametrize("target", ["tree", "missing"])
def test_non_commit_refuses_before_any_gh_call(world: World, target: str) -> None:
    """Guards against watching something that is not a commit."""
    ref = (
        subprocess.run(
            ["git", "rev-parse", "HEAD^{tree}"], cwd=world.clone, capture_output=True, text=True, check=True
        ).stdout.strip()
        if target == "tree"
        else "no-such-ref"
    )
    assert watch(world, ref, require=["test"]).code == INDETERMINATE
    assert gh_argvs(world) == []


def test_every_gh_call_is_pinned_to_the_repo(world: World) -> None:
    """Guards against a gh call running against whatever repo gh infers, or passing -R to `gh api`, which rejects it."""
    world.fake.script(protection_argv(), protected("test"))
    script_ci(world, [check_run(201)])
    assert pr_land.main(["watch", world.sha, "--branch", "dev"], runner=world.runner, clock=world.clock.clock, sleep=world.clock.sleep) == GREEN
    calls = gh_argvs(world)
    assert calls.count(REPO_VIEW) == 1
    for argv in calls:
        if argv == REPO_VIEW:
            continue
        if argv[1] == "api":
            assert argv[2].startswith(f"repos/{REPO}/"), argv
            assert "-R" not in argv, argv
        else:
            assert argv[-2:] == ["-R", REPO], argv


def test_never_reads_rollups_or_shells_out_to_timeout(world: World) -> None:
    """Guards against drifting onto the rollup views or wrapping gh in `timeout`."""
    world.fake.script(protection_argv(), protected("test"))
    script_ci(world, [check_run(211, status="queued")], [check_run(211)])
    assert watch(world, branch="dev").code == GREEN
    for argv, _cwd in world.runner.calls:
        joined = " ".join(argv)
        assert "pr checks" not in joined
        assert "statusCheckRollup" not in joined
        assert "/status?" not in joined
        assert not any(part.endswith("/status") for part in argv)
        assert "timeout" not in joined


# --- CLI and output -----------------------------------------------------------


def test_green_run_prints_its_line_and_returns_its_id(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    """Guards against a verdict nobody can trace back to the run it came from."""
    script_ci(world, [check_run(221, suite=7)])
    result = watch(world, require=["test"])
    assert result.code == GREEN
    assert result.run_ids == [221]
    assert re.search(r"^test suite=\d+ run=\d+ success$", capsys.readouterr().out, re.M)


def test_status_line_names_context_id_and_state(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    """Guards against a status verdict printed without the status it came from."""
    script_ci(world, [], statuses=[commit_status(231)])
    watch(world, require=["test"])
    assert "test status=231 success" in capsys.readouterr().out.splitlines()


def test_origin_that_differs_from_gh_repo_refuses(git_repo: Path) -> None:
    """Guards against pinning every call to a repo other than the clone's origin."""
    fake = FakeGh()
    fake.script(REPO_VIEW, json_result({"nameWithOwner": "someone/else"}))
    clock = FakeClock()
    runner = CompositeRunner(fake, git_repo)
    assert pr_land.main(["watch", "HEAD", "--require", "test"], runner=runner, clock=clock.clock, sleep=clock.sleep) == INDETERMINATE
    assert fake.calls == [REPO_VIEW]


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/acme/widget.git",
        "https://github.com/acme/widget",
        "git@github.com:acme/widget.git",
        "ssh://git@github.com/acme/widget.git",
    ],
)
def test_resolve_repo_parses_every_origin_form(world: World, url: str) -> None:
    """Guards against an origin URL form (https, ssh, scp-like, .git suffix) failing to parse to owner/name."""
    subprocess.run(["git", "remote", "set-url", "origin", url], cwd=world.clone, check=True)
    assert pr_land.resolve_repo(world.runner) == REPO


def test_main_threads_runner_and_clock_into_watch(world: World) -> None:
    """Guards against main dropping the injected clock and sleep, so the watch really sleeps."""
    script_ci(world, [check_run(241, status="in_progress")], [check_run(241)])
    code = pr_land.main(
        ["watch", world.sha, "--require", "test", "--interval", "7", "--timeout", "30"],
        runner=world.runner,
        clock=world.clock.clock,
        sleep=world.clock.sleep,
    )
    assert code == GREEN
    assert world.clock.sleeps == [7]


# --- gh() and runners ---------------------------------------------------------


def test_gh_pins_non_api_subcommands_with_R() -> None:
    """Guards against a non-api gh subcommand running against whatever repo gh infers from cwd."""
    fake = FakeGh()
    fake.script(["gh", "pr", "view"], Result(0, "{}", ""))
    pr_land.gh(fake, REPO, "pr", "view", "12")
    assert fake.calls == [["gh", "pr", "view", "12", "-R", REPO]]


def test_gh_refuses_api_endpoint_outside_the_repo() -> None:
    """Guards against a `gh api` call escaping the pinned repo."""
    fake = FakeGh()
    result = pr_land.gh(fake, REPO, "api", "repos/other/thing/pulls")
    assert result.returncode != 0
    assert fake.calls == []


def test_subprocess_runner_captures_real_output() -> None:
    """Guards against the real runner not capturing output, which every parser depends on."""
    result = pr_land.SubprocessRunner().run(["git", "--version"])
    assert result.returncode == 0
    assert result.stdout.startswith("git version")


def test_composite_runner_records_calls_and_overlays_real_git(git_repo: Path) -> None:
    """Guards against the shared fake losing calls or faking the git call an overlay decorates."""
    fake = FakeGh()
    fake.script(REPO_VIEW, json_result({"nameWithOwner": REPO}))
    runner = CompositeRunner(fake, git_repo)
    runner.run(REPO_VIEW)
    runner.run(["git", "status", "--short"], cwd=str(git_repo.parent))
    (git_repo / "CHANGELOG.md").write_text("one\n", encoding="utf-8")
    subprocess.run(["git", "add", "CHANGELOG.md"], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "two"], cwd=git_repo, check=True)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=git_repo, capture_output=True, text=True, check=True).stdout.strip()
    runner.overlay(["git", "push"], append_stderr="X")
    pushed = runner.run(["git", "push", "origin", "main"])
    assert pushed.returncode == 0
    assert pushed.stderr.endswith("X")
    origin = git_repo.parent / "acme" / "widget.git"
    remote_head = subprocess.run(
        ["git", "--git-dir", str(origin), "rev-parse", "main"], capture_output=True, text=True, check=True
    ).stdout.strip()
    assert remote_head == head
    assert runner.calls == [
        (REPO_VIEW, str(git_repo)),
        (["git", "status", "--short"], str(git_repo.parent)),
        (["git", "push", "origin", "main"], str(git_repo)),
    ]
