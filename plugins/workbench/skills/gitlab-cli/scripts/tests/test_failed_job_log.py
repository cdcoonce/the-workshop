"""Tests for failed_job_log: failing jobs only, cleaned log tails, honest exits."""

from __future__ import annotations

import failed_job_log
from _glab import INDETERMINATE

ESC = "\x1b"


def job(jid: int, name: str, status: str, **extra) -> dict:
    return {
        "id": jid,
        "name": name,
        "stage": "test",
        "status": status,
        "allow_failure": False,
        "failure_reason": "script_failure",
        "web_url": f"https://gitlab.com/group/project/-/jobs/{jid}",
        **extra,
    }


def numbered(n: int) -> str:
    return "".join(f"line {i}\n" for i in range(1, n + 1))


class TestCleanLog:
    def test_strips_ansi_color_codes(self):
        text = f"{ESC}[31;1mERROR{ESC}[0m: boom\n"
        assert failed_job_log.clean_log(text) == ["ERROR: boom"]

    def test_drops_runner_section_markers(self):
        text = f"section_start:1700:step_script\r{ESC}[0Ksetup\nreal output\nsection_end:1701:step_script\r{ESC}[0K\n"
        assert failed_job_log.clean_log(text) == ["setup", "real output"]

    def test_collapses_carriage_return_progress_to_final_frame(self):
        assert failed_job_log.clean_log("10%\r50%\r100% done\n") == ["100% done"]

    def test_strips_runner_timestamp_and_stream_prefixes(self):
        # Shape captured from a real trace on a runner with timestamps enabled:
        # `<utc ts> <2-digit section><O|E>[+ continuation]<content>`.
        text = (
            "2026-09-24T22:52:43.411369Z 01E fatal: couldn't find remote ref\n"
            "2026-09-24T22:52:43.535456Z 00O\n"
            "2026-09-24T22:52:43.536361Z 00O+\n"
            "2026-09-24T22:52:43.536367Z 00O+Uploading artifacts for failed job\n"
            "2026-09-24T22:52:44.394866Z 00O ERROR: Job failed: exit code 128\n"
        )
        assert failed_job_log.clean_log(text) == [
            "fatal: couldn't find remote ref",
            "Uploading artifacts for failed job",
            "ERROR: Job failed: exit code 128",
        ]

    def test_drops_blank_lines_and_truncates_long_ones(self):
        lines = failed_job_log.clean_log("a\n\n   \n" + "x" * 1000 + "\n")
        assert lines[0] == "a"
        assert len(lines) == 2
        assert len(lines[1]) <= failed_job_log.MAX_LINE_CHARS + 3
        assert lines[1].endswith("...")


class TestFailedJobs:
    def test_reports_only_failed_jobs_with_tail_and_never_fetches_green_logs(self, glab):
        glab.route(
            pipelines__99__jobs={
                "json": [job(1, "lint", "success"), job(2, "pytest", "failed")]
            },
            jobs__2__trace={"raw": numbered(100)},
        )
        result = glab.run("failed_job_log.py", "--pipeline", "99", "--tail", "5")
        assert result.returncode == failed_job_log.RED, result.stderr
        assert "pytest" in result.stdout
        assert "lint" not in result.stdout
        assert "line 100" in result.stdout and "line 96" in result.stdout
        assert "line 95" not in result.stdout
        assert not any("jobs/1/trace" in " ".join(c) for c in glab.calls())

    def test_names_failure_reason_and_allow_failure(self, glab):
        glab.route(
            pipelines__99__jobs={
                "json": [
                    job(
                        3,
                        "flaky",
                        "failed",
                        allow_failure=True,
                        failure_reason="runner_system_failure",
                    )
                ]
            },
            jobs__3__trace={"raw": "boom\n"},
        )
        result = glab.run("failed_job_log.py", "--pipeline", "99")
        assert "runner_system_failure" in result.stdout
        assert "allow_failure" in result.stdout

    def test_all_green_exits_zero_and_says_so(self, glab):
        glab.route(pipelines__99__jobs={"json": [job(1, "lint", "success")]})
        result = glab.run("failed_job_log.py", "--pipeline", "99")
        assert result.returncode == failed_job_log.GREEN
        assert "no failed jobs" in result.stdout

    def test_unavailable_trace_is_reported_not_dropped(self, glab):
        glab.route(
            pipelines__99__jobs={"json": [job(2, "pytest", "failed")]},
            jobs__2__trace={"exit": 1},
        )
        result = glab.run("failed_job_log.py", "--pipeline", "99")
        assert result.returncode == failed_job_log.RED
        assert "pytest" in result.stdout
        assert "log unavailable" in result.stdout

    def test_job_listing_failure_is_indeterminate_never_green(self, glab):
        glab.route(pipelines__99__jobs={"exit": 1})
        result = glab.run("failed_job_log.py", "--pipeline", "99")
        assert result.returncode == INDETERMINATE
        assert "no failed jobs" not in result.stdout


class TestPipelineResolution:
    def test_mr_resolves_through_head_pipeline(self, glab):
        glab.route(
            merge_requests__7={"json": {"head_pipeline": {"id": 99, "status": "failed"}}},
            pipelines__99__jobs={"json": [job(2, "pytest", "failed")]},
            jobs__2__trace={"raw": "boom\n"},
        )
        result = glab.run("failed_job_log.py", "--mr", "7")
        assert result.returncode == failed_job_log.RED, result.stderr
        assert "pytest" in result.stdout
        assert any("projects/group%2Fproject/" in " ".join(c) for c in glab.calls())

    def test_mr_without_a_pipeline_is_indeterminate(self, glab):
        glab.route(merge_requests__7={"json": {"head_pipeline": None}})
        result = glab.run("failed_job_log.py", "--mr", "7")
        assert result.returncode == INDETERMINATE
        assert "no pipeline" in result.stdout

    def test_default_walks_every_failed_pipeline_for_head_sha(self, glab):
        glab.route(
            **{
                "pipelines?sha=": {
                    "json": [
                        {"id": 98, "status": "success"},
                        {"id": 99, "status": "failed"},
                    ]
                }
            },
            pipelines__99__jobs={"json": [job(2, "pytest", "failed")]},
            jobs__2__trace={"raw": "boom\n"},
        )
        result = glab.run("failed_job_log.py")
        assert result.returncode == failed_job_log.RED, result.stderr
        assert "pytest" in result.stdout
        assert not any("pipelines/98" in " ".join(c) for c in glab.calls())

    def test_project_override_beats_remote(self, glab):
        glab.route(pipelines__99__jobs={"json": []})
        glab.run("failed_job_log.py", "--pipeline", "99", "--project", "other/repo")
        assert any("other%2Frepo" in " ".join(c) for c in glab.calls())
