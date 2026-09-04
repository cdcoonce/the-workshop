"""Tests for ci_watch.

glab behaviour is exercised through a fake `glab` binary on PATH rather than
mocks: the failure modes this script exists to survive (stderr noise with
empty stdout, transient nonzero exits, roll-up green hiding a red job) are
process-boundary behaviours, and a mock would just re-assert our own
assumptions. Git behaviour (SHA expansion, remote-head resolution) runs
against real fixture repositories.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ci_watch  # noqa: E402

SCRIPT = Path(__file__).resolve().parent.parent / "ci_watch.py"

FAKE_GLAB = '''#!/usr/bin/env python3
"""Fake glab: routes each `glab api <path>` call to a canned response bucket.

Buckets are consumed sequentially; an exhausted bucket repeats its last entry.
Every argv is appended to calls.log for assertions on query parameters.
"""
import json, os, sys

state = os.environ["FAKE_GLAB_DIR"]
with open(os.path.join(state, "calls.log"), "a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")

path = sys.argv[2] if len(sys.argv) > 2 else ""
if "/jobs" in path:
    bucket = "jobs"
elif "/bridges" in path:
    bucket = "bridges"
elif "merge_requests" in path:
    bucket = "mr"
else:
    bucket = "pipelines"

with open(os.path.join(state, "responses.json")) as fh:
    responses = json.load(fh)
entries = responses.get(bucket, [])
if not entries:
    sys.stderr.write("fake glab: no canned response for bucket %s\\n" % bucket)
    sys.exit(70)

counter_path = os.path.join(state, bucket + ".count")
n = 0
if os.path.exists(counter_path):
    n = int(open(counter_path).read())
open(counter_path, "w").write(str(n + 1))

entry = entries[min(n, len(entries) - 1)]
out = entry.get("stdout", "")
if not isinstance(out, str):
    out = json.dumps(out)
sys.stdout.write(out)
sys.stderr.write(entry.get("stderr", ""))
sys.exit(entry.get("exit", 0))
'''

GITLAB_REMOTE = "git@gitlab.com:group/project.git"


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repo with one commit and a gitlab.com origin (never contacted)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    (repo / "file.txt").write_text("content\n")
    git(repo, "add", "file.txt")
    git(repo, "commit", "-q", "-m", "initial")
    git(repo, "remote", "add", "origin", GITLAB_REMOTE)
    return repo


@pytest.fixture
def fake_glab(tmp_path: Path) -> Path:
    """Install the fake glab on PATH; returns its state dir for scripting."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    glab = bin_dir / "glab"
    glab.write_text(FAKE_GLAB)
    glab.chmod(0o755)
    state = tmp_path / "glab-state"
    state.mkdir()
    (state / "calls.log").write_text("")
    return state


def script_responses(state: Path, **buckets: list) -> None:
    buckets.setdefault("bridges", [{"stdout": []}])
    (state / "responses.json").write_text(json.dumps(buckets))


def calls(state: Path) -> list[list[str]]:
    lines = (state / "calls.log").read_text().splitlines()
    return [json.loads(line) for line in lines]


def run_watch(
    repo: Path, state: Path, *args: str, timeout: int = 30
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PATH"] = f"{state.parent / 'bin'}{os.pathsep}{env['PATH']}"
    env["FAKE_GLAB_DIR"] = str(state)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args, "--interval", "0"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def pipeline(status: str, pid: int = 101, ref: str = "dev") -> dict:
    # Real listings always carry `ref`; the default matches the mr/branch-mode
    # tests that watch dev, so only tests about ref selection name it.
    return {
        "id": pid,
        "status": status,
        "ref": ref,
        "web_url": f"https://gitlab.com/p/{pid}",
    }


def job(name: str, status: str, allow_failure: bool = False) -> dict:
    return {"name": name, "status": status, "allow_failure": allow_failure}


GREEN_JOBS = [job("lint", "success"), job("test", "success"), job("build", "success")]


# --- verdicts -----------------------------------------------------------------


def test_green_pipeline_reports_every_job_and_exits_zero(repo, fake_glab):
    script_responses(
        fake_glab,
        pipelines=[{"stdout": [pipeline("running")]}, {"stdout": [pipeline("success")]}],
        jobs=[{"stdout": GREEN_JOBS}],
    )
    result = run_watch(repo, fake_glab, "sha")
    assert result.returncode == 0, result.stderr
    for name in ("lint", "test", "build"):
        assert name in result.stdout


def test_failed_job_under_green_rollup_is_red(repo, fake_glab):
    """The house rule is every job green — roll-up success is not the report.

    An allow_failure job that failed leaves the pipeline green; a watcher that
    checks only the roll-up exits 0 here and this test is what catches it.
    """
    script_responses(
        fake_glab,
        pipelines=[{"stdout": [pipeline("success")]}],
        jobs=[{"stdout": GREEN_JOBS + [job("audit", "failed", allow_failure=True)]}],
    )
    result = run_watch(repo, fake_glab, "sha")
    assert result.returncode == 1
    assert "audit" in result.stdout
    assert "failed" in result.stdout


def test_failed_pipeline_exits_one_with_job_report(repo, fake_glab):
    script_responses(
        fake_glab,
        pipelines=[{"stdout": [pipeline("failed")]}],
        jobs=[{"stdout": GREEN_JOBS + [job("test", "failed")]}],
    )
    result = run_watch(repo, fake_glab, "sha")
    assert result.returncode == 1
    assert "failed" in result.stdout


def test_manual_pipeline_is_terminal_indeterminate(repo, fake_glab):
    """A pipeline blocked on a manual job never reaches success/failed; the
    watcher must report and stop rather than hold the session for the full
    timeout."""
    script_responses(
        fake_glab,
        pipelines=[{"stdout": [pipeline("manual")]}],
        jobs=[{"stdout": GREEN_JOBS + [job("deploy", "manual")]}],
    )
    result = run_watch(repo, fake_glab, "sha")
    assert result.returncode == 2


# --- resilience ---------------------------------------------------------------


def test_transient_glab_failure_skips_tick_not_crash(repo, fake_glab):
    """glab emits errors on stderr with empty stdout; one bad poll must mean
    one skipped tick, not a dead watcher."""
    script_responses(
        fake_glab,
        pipelines=[
            {"exit": 1, "stderr": "dial tcp: i/o timeout\n"},
            {"stdout": "", "exit": 0},
            {"stdout": [pipeline("success")]},
        ],
        jobs=[{"stdout": GREEN_JOBS}],
    )
    result = run_watch(repo, fake_glab, "sha")
    assert result.returncode == 0, result.stderr
    assert len([c for c in calls(fake_glab) if "/jobs" not in c[1]]) >= 3


def test_repeated_glab_failure_exits_indeterminate(repo, fake_glab):
    script_responses(
        fake_glab, pipelines=[{"exit": 1, "stderr": "dial tcp: i/o timeout\n"}]
    )
    result = run_watch(repo, fake_glab, "sha")
    assert result.returncode == 2


def test_no_pipeline_yet_keeps_polling(repo, fake_glab):
    """An empty pipeline list means "not created yet", not an error."""
    script_responses(
        fake_glab,
        pipelines=[{"stdout": []}, {"stdout": [pipeline("success")]}],
        jobs=[{"stdout": GREEN_JOBS}],
    )
    result = run_watch(repo, fake_glab, "sha")
    assert result.returncode == 0, result.stderr


def test_jobs_fetch_failure_marks_requery_needed(repo, fake_glab):
    """Per-job green unverified is not success: report the roll-up, mark the
    gap, exit indeterminate."""
    script_responses(
        fake_glab,
        pipelines=[{"stdout": [pipeline("success")]}],
        jobs=[{"exit": 1, "stderr": "500\n"}],
    )
    result = run_watch(repo, fake_glab, "sha")
    assert result.returncode == 2
    assert "re-query" in result.stdout.lower()


def test_timeout_exits_indeterminate(repo, fake_glab):
    script_responses(fake_glab, pipelines=[{"stdout": [pipeline("running")]}])
    result = run_watch(repo, fake_glab, "sha", "--timeout", "1")
    assert result.returncode == 2


def test_setup_failure_exits_indeterminate_not_red(repo, fake_glab):
    """Exit 1 is reserved for "CI is red". A watcher that could not even start
    (wrong cwd, missing remote) must exit 2, or the session relays a pipeline
    failure that never happened."""
    git(repo, "remote", "remove", "origin")
    script_responses(fake_glab, pipelines=[{"stdout": [pipeline("success")]}])
    result = run_watch(repo, fake_glab, "sha")
    assert result.returncode == 2


def test_malformed_pipeline_entry_is_a_skipped_tick(repo, fake_glab):
    """An entry without an id (or a non-dict) is API noise, not a crash —
    an uncaught exception would exit 1 and read as a red verdict."""
    script_responses(
        fake_glab,
        pipelines=[{"stdout": [{"status": "success"}]}, {"stdout": [pipeline("success")]}],
        jobs=[{"stdout": GREEN_JOBS}],
    )
    result = run_watch(repo, fake_glab, "sha")
    assert result.returncode == 0, result.stderr


def test_newest_pipeline_wins(repo, fake_glab):
    """The API returns newest first; a retried pipeline's fresh run on the
    same ref is the verdict, not the old red one."""
    script_responses(
        fake_glab,
        pipelines=[{"stdout": [pipeline("success", pid=202), pipeline("failed", pid=101)]}],
        jobs=[{"stdout": GREEN_JOBS}],
    )
    result = run_watch(repo, fake_glab, "sha")
    assert result.returncode == 0, result.stderr
    assert any("pipelines/202/jobs" in c[1] for c in calls(fake_glab))


def test_canceling_pipeline_is_not_terminal(repo, fake_glab):
    """GitLab 17 reports `canceling` before `canceled`; treating it as
    terminal returns indeterminate one tick before the true red."""
    script_responses(
        fake_glab,
        pipelines=[{"stdout": [pipeline("canceling")]}, {"stdout": [pipeline("canceled")]}],
        jobs=[{"stdout": GREEN_JOBS + [job("test", "canceled")]}],
    )
    result = run_watch(repo, fake_glab, "sha")
    assert result.returncode == 1
    pipeline_queries = [c for c in calls(fake_glab) if "pipelines?sha=" in c[1]]
    assert len(pipeline_queries) >= 2, "watcher must re-poll through `canceling`"


# --- bridges (trigger jobs) ---------------------------------------------------


def test_failed_bridge_is_red_even_when_jobs_are_green(repo, fake_glab):
    """Trigger jobs live on /bridges, not /jobs — a red downstream pipeline
    must not pass as green just because every regular job succeeded."""
    script_responses(
        fake_glab,
        pipelines=[{"stdout": [pipeline("success")]}],
        jobs=[{"stdout": GREEN_JOBS}],
        bridges=[{"stdout": [job("downstream-deploy", "failed", allow_failure=True)]}],
    )
    result = run_watch(repo, fake_glab, "sha")
    assert result.returncode == 1
    assert "downstream-deploy" in result.stdout


def test_job_page_cap_is_unverifiable_not_green(monkeypatch):
    """If pagination gives up before the listing ends, per-job green is
    unproven — the fetch must say so instead of passing a truncated list."""
    monkeypatch.setattr(
        ci_watch, "glab_api", lambda path: [{"name": "j", "status": "success"}] * 100
    )
    assert ci_watch.fetch_listing("proj", 1, "jobs", 0) is None


# --- SHA handling -------------------------------------------------------------


def test_short_sha_expanded_to_full(repo, fake_glab):
    """`pipelines?sha=` silently matches nothing on an abbreviated SHA, which
    reads as "still pending" forever — the script must expand it first."""
    full = git(repo, "rev-parse", "HEAD")
    script_responses(
        fake_glab,
        pipelines=[{"stdout": [pipeline("success")]}],
        jobs=[{"stdout": GREEN_JOBS}],
    )
    result = run_watch(repo, fake_glab, "sha", full[:7])
    assert result.returncode == 0, result.stderr
    assert any(f"sha={full}" in c[1] for c in calls(fake_glab))


def test_sha_defaults_to_head(repo, fake_glab):
    full = git(repo, "rev-parse", "HEAD")
    script_responses(
        fake_glab,
        pipelines=[{"stdout": [pipeline("success")]}],
        jobs=[{"stdout": GREEN_JOBS}],
    )
    result = run_watch(repo, fake_glab, "sha")
    assert result.returncode == 0, result.stderr
    assert any(f"sha={full}" in c[1] for c in calls(fake_glab))


# --- multiple pipelines per SHA -----------------------------------------------


def test_green_mr_pipeline_does_not_mask_red_branch_pipeline(repo, fake_glab):
    """One SHA can carry an MR-head pipeline AND a branch pipeline. Latching
    onto whichever the API lists first exits 0 on the green MR pipeline while
    the branch pipeline is red — the verdict must span every ref's newest."""
    script_responses(
        fake_glab,
        pipelines=[
            {
                "stdout": [
                    pipeline("success", pid=202, ref="refs/merge-requests/5/head"),
                    pipeline("failed", pid=101, ref="dev"),
                ]
            }
        ],
        jobs=[{"stdout": GREEN_JOBS}, {"stdout": GREEN_JOBS + [job("test", "failed")]}],
    )
    result = run_watch(repo, fake_glab, "sha")
    assert result.returncode == 1
    assert any("pipelines/101/jobs" in c[1] for c in calls(fake_glab))


def test_two_green_pipelines_on_different_refs_exit_zero(repo, fake_glab):
    script_responses(
        fake_glab,
        pipelines=[
            {
                "stdout": [
                    pipeline("success", pid=202, ref="refs/merge-requests/5/head"),
                    pipeline("success", pid=101, ref="dev"),
                ]
            }
        ],
        jobs=[{"stdout": GREEN_JOBS}],
    )
    result = run_watch(repo, fake_glab, "sha")
    assert result.returncode == 0, result.stderr


def test_ref_flag_filters_out_other_refs_client_side(repo, fake_glab):
    """--ref must hold even when the server ignores the query parameter: a
    pipeline on another ref is never part of this ref's verdict."""
    script_responses(
        fake_glab,
        pipelines=[
            {
                "stdout": [
                    pipeline("success", pid=202, ref="refs/merge-requests/5/head"),
                    pipeline("failed", pid=101, ref="dev"),
                ]
            }
        ],
        jobs=[{"stdout": GREEN_JOBS + [job("test", "failed")]}],
    )
    result = run_watch(repo, fake_glab, "sha", "--ref", "dev")
    assert result.returncode == 1
    fetched = [c[1] for c in calls(fake_glab) if "/jobs" in c[1]]
    assert fetched and all("pipelines/101/jobs" in q for q in fetched)


def test_sha_waits_for_every_refs_pipeline_to_reach_terminal(repo, fake_glab):
    """A terminal green on one ref must not end the watch while another ref's
    pipeline is still running — that running pipeline is the one that can
    still turn the verdict red."""
    mr_pipe = pipeline("success", pid=202, ref="refs/merge-requests/5/head")
    script_responses(
        fake_glab,
        pipelines=[
            {"stdout": [mr_pipe, pipeline("running", pid=101, ref="dev")]},
            {"stdout": [mr_pipe, pipeline("failed", pid=101, ref="dev")]},
        ],
        jobs=[{"stdout": GREEN_JOBS}, {"stdout": GREEN_JOBS + [job("test", "failed")]}],
    )
    result = run_watch(repo, fake_glab, "sha")
    assert result.returncode == 1
    pipeline_queries = [c for c in calls(fake_glab) if "pipelines?sha=" in c[1]]
    assert len(pipeline_queries) >= 2, "watcher must re-poll while any ref is pending"


# --- pipeline mode ------------------------------------------------------------


def test_pipeline_mode_watches_the_given_id(repo, fake_glab):
    """A SHA with several pipelines needs a way to target exactly one — the
    pipeline mode polls that id until terminal with the same job report."""
    detail = dict(pipeline("running", pid=555), sha="e" * 40)
    script_responses(
        fake_glab,
        pipelines=[{"stdout": detail}, {"stdout": dict(detail, status="success")}],
        jobs=[{"stdout": GREEN_JOBS}],
    )
    result = run_watch(repo, fake_glab, "pipeline", "555")
    assert result.returncode == 0, result.stderr
    detail_queries = [c[1] for c in calls(fake_glab) if c[1].endswith("pipelines/555")]
    assert len(detail_queries) >= 2, "watcher must poll the id until terminal"
    for name in ("lint", "test", "build"):
        assert name in result.stdout


def test_pipeline_mode_red_job_exits_one(repo, fake_glab):
    script_responses(
        fake_glab,
        pipelines=[{"stdout": dict(pipeline("failed", pid=555), sha="e" * 40)}],
        jobs=[{"stdout": GREEN_JOBS + [job("test", "failed")]}],
    )
    result = run_watch(repo, fake_glab, "pipeline", "555")
    assert result.returncode == 1
    assert "failed" in result.stdout


def test_pipeline_mode_unknown_id_is_indeterminate(repo, fake_glab):
    """A 404 on the pipeline id is "could not verify", never a red verdict."""
    script_responses(fake_glab, pipelines=[{"exit": 1, "stderr": "404 Not Found\n"}])
    result = run_watch(repo, fake_glab, "pipeline", "999")
    assert result.returncode == 2


# --- MR mode ------------------------------------------------------------------


def test_mr_closed_bails_loudly(repo, fake_glab):
    script_responses(fake_glab, mr=[{"stdout": {"state": "closed", "iid": 7}}])
    result = run_watch(repo, fake_glab, "mr", "7")
    assert result.returncode == 2
    assert "closed" in result.stdout.lower()


def test_mr_merge_happens_later_then_watches_merge_commit(repo, fake_glab):
    """`glab mr merge` can return 405 or flip to auto-merge; the watcher owns
    "merge will happen later": poll state, then watch the merge commit on the
    target branch."""
    merge_sha = "a" * 40
    script_responses(
        fake_glab,
        mr=[
            {"stdout": {"state": "opened", "iid": 7}},
            {
                "stdout": {
                    "state": "merged",
                    "iid": 7,
                    "merge_commit_sha": merge_sha,
                    "target_branch": "dev",
                }
            },
        ],
        pipelines=[{"stdout": [pipeline("success")]}],
        jobs=[{"stdout": GREEN_JOBS}],
    )
    result = run_watch(repo, fake_glab, "mr", "7")
    assert result.returncode == 0, result.stderr
    watched = [c[1] for c in calls(fake_glab) if "sha=" in c[1]]
    assert watched and all(f"sha={merge_sha}" in q for q in watched)
    assert any("ref=dev" in q for q in watched)


def test_mr_timeout_exits_indeterminate(repo, fake_glab):
    script_responses(fake_glab, mr=[{"stdout": {"state": "opened", "iid": 7}}])
    result = run_watch(repo, fake_glab, "mr", "7", "--timeout", "1")
    assert result.returncode == 2


def test_mr_merge_prefers_merge_commit_over_squash(repo, fake_glab):
    """With merge-commit method + the squash checkbox, GitLab fills BOTH
    fields; only the merge commit heads the target branch, so pipelines for
    the squash SHA never exist and the watch would time out on green CI."""
    squash_sha = "b" * 40
    merge_sha = "c" * 40
    script_responses(
        fake_glab,
        mr=[
            {
                "stdout": {
                    "state": "merged",
                    "iid": 7,
                    "squash_commit_sha": squash_sha,
                    "merge_commit_sha": merge_sha,
                    "target_branch": "dev",
                }
            }
        ],
        pipelines=[{"stdout": [pipeline("success")]}],
        jobs=[{"stdout": GREEN_JOBS}],
    )
    result = run_watch(repo, fake_glab, "mr", "7")
    assert result.returncode == 0, result.stderr
    watched = [c[1] for c in calls(fake_glab) if "sha=" in c[1]]
    assert watched and all(f"sha={merge_sha}" in q for q in watched)


# --- branch mode --------------------------------------------------------------


def test_branch_mode_resolves_remote_head(repo, fake_glab, tmp_path):
    """Post-merge watching resolves the integration branch head remotely —
    the local clone may be behind."""
    bare = tmp_path / "bare.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", str(bare)], check=True, capture_output=True
    )
    git(repo, "remote", "set-url", "origin", str(bare))
    git(repo, "push", "-q", "origin", "main:dev")
    head = git(repo, "rev-parse", "HEAD")
    script_responses(
        fake_glab,
        pipelines=[{"stdout": [pipeline("success")]}],
        jobs=[{"stdout": GREEN_JOBS}],
    )
    result = run_watch(
        repo, fake_glab, "branch", "dev", "--project", "group/project"
    )
    assert result.returncode == 0, result.stderr
    assert any(f"sha={head}" in c[1] and "ref=dev" in c[1] for c in calls(fake_glab))


def test_branch_ref_with_slash_is_urlencoded(repo, fake_glab, tmp_path):
    bare = tmp_path / "bare.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", str(bare)], check=True, capture_output=True
    )
    git(repo, "remote", "set-url", "origin", str(bare))
    git(repo, "push", "-q", "origin", "main:release/1.0")
    script_responses(
        fake_glab,
        pipelines=[{"stdout": [pipeline("success", ref="release/1.0")]}],
        jobs=[{"stdout": GREEN_JOBS}],
    )
    result = run_watch(
        repo, fake_glab, "branch", "release/1.0", "--project", "group/project"
    )
    assert result.returncode == 0, result.stderr
    assert any("ref=release%2F1.0" in c[1] for c in calls(fake_glab))


# --- pagination ---------------------------------------------------------------


def test_job_listing_paginates_past_one_page(repo, fake_glab):
    page_one = [job(f"job-{i:03d}", "success") for i in range(100)]
    page_two = [job("tail-a", "success"), job("tail-b", "success")]
    script_responses(
        fake_glab,
        pipelines=[{"stdout": [pipeline("success")]}],
        jobs=[{"stdout": page_one}, {"stdout": page_two}],
    )
    result = run_watch(repo, fake_glab, "sha")
    assert result.returncode == 0, result.stderr
    assert "tail-b" in result.stdout
    assert any("page=2" in c[1] for c in calls(fake_glab) if "/jobs" in c[1])


# --- project resolution (unit) ------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("git@gitlab.com:group/project.git", "group/project"),
        ("git@gitlab.com:group/sub/project.git", "group/sub/project"),
        ("https://gitlab.com/group/project.git", "group/project"),
        ("https://gitlab.com/group/sub/project", "group/sub/project"),
        ("ssh://git@gitlab.com/group/project.git", "group/project"),
    ],
)
def test_parse_project_path(url: str, expected: str) -> None:
    assert ci_watch.parse_project_path(url) == expected


def test_project_path_is_urlencoded_in_api_calls(repo, fake_glab):
    """Multi-remote glab inference picks the wrong repo alphabetically; the
    script must derive the project itself and pass it URL-encoded."""
    git(repo, "remote", "set-url", "origin", "git@gitlab.com:group/sub/project.git")
    script_responses(
        fake_glab,
        pipelines=[{"stdout": [pipeline("success")]}],
        jobs=[{"stdout": GREEN_JOBS}],
    )
    result = run_watch(repo, fake_glab, "sha")
    assert result.returncode == 0, result.stderr
    assert any(c[1].startswith("projects/group%2Fsub%2Fproject/") for c in calls(fake_glab))
