#!/usr/bin/env python3
"""Print only the failing jobs of a GitLab pipeline, each with a cleaned log tail.

Modes (default: every pipeline for the HEAD commit that is not green):
  failed_job_log.py                 pipelines for HEAD
  failed_job_log.py --mr IID        the MR's head pipeline
  failed_job_log.py --pipeline ID   one specific pipeline

Passing jobs are never fetched. Log tails drop ANSI colors, runner timestamp
prefixes, section markers, carriage-return progress frames and blank lines, so the lines that
come back are the lines that explain the failure.

Exit contract (same shape as ci_watch):
  0  no failed jobs
  1  failed jobs reported (a failed allow_failure job counts, and is labelled)
  2  indeterminate: bad setup, API failure, or no pipeline to read
"""

from __future__ import annotations

import argparse
import re

from _glab import (
    GREEN,
    RED,
    fail_setup,
    glab_json,
    glab_list,
    glab_raw,
    resolve_project,
    run,
    say,
)

MAX_LINE_CHARS = 300
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
# Runners with timestamps enabled prefix every line: `<utc ts> <NN><O|E>[+ ]`.
RUNNER_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}T[\d:.]+Z \d{2}[OE][+ ]?")


def clean_log(text: str) -> list[str]:
    """Readable, non-blank lines from a raw job trace.

    Parameters
    ----------
    text : str
        Raw trace as GitLab serves it.

    Returns
    -------
    list[str]
        Lines with ANSI, section markers and progress frames removed.
    """
    lines: list[str] = []
    for raw_line in text.split("\n"):
        line = ANSI.sub("", raw_line.split("\r")[-1])
        line = RUNNER_PREFIX.sub("", line)
        line = line.rstrip()
        if not line.strip():
            continue
        if len(line) > MAX_LINE_CHARS:
            line = line[:MAX_LINE_CHARS] + "..."
        lines.append(line)
    return lines


def pipelines_for_sha(project: str, sha: str) -> list[dict] | None:
    return glab_list(f"projects/{project}/pipelines?sha={sha}")


def resolve_pipeline_ids(project: str, mr: int | None, pipeline: int | None) -> list[int]:
    """Pipeline ids to inspect, or exit INDETERMINATE when there is nothing to read."""
    if pipeline is not None:
        return [pipeline]
    if mr is not None:
        data = glab_json(f"projects/{project}/merge_requests/{mr}")
        if not isinstance(data, dict):
            fail_setup(f"cannot read MR !{mr}")
        head = data.get("head_pipeline")
        if not head:
            fail_setup(f"MR !{mr} has no pipeline")
        return [head["id"]]
    code, sha, stderr = run(["git", "rev-parse", "HEAD"])
    if code != 0:
        fail_setup(f"cannot read HEAD: {stderr}")
    pipelines = pipelines_for_sha(project, sha)
    if pipelines is None:
        fail_setup(f"cannot list pipelines for {sha[:8]}")
    if not pipelines:
        fail_setup(f"no pipeline for {sha[:8]}")
    return [p["id"] for p in pipelines if p.get("status") != "success"]


def describe(job: dict) -> str:
    label = f"== {job.get('name', '?')} (stage {job.get('stage', '?')}) job {job['id']}"
    label += f" failed: {job.get('failure_reason') or 'unknown'}"
    if job.get("allow_failure"):
        label += " [allow_failure]"
    return label


def report_pipeline(project: str, pipeline_id: int, tail: int) -> int:
    """Print the failed jobs of one pipeline; returns how many were reported."""
    jobs = glab_list(f"projects/{project}/pipelines/{pipeline_id}/jobs")
    if jobs is None:
        fail_setup(f"cannot list jobs for pipeline {pipeline_id}")
    failed = [j for j in jobs if j.get("status") == "failed"]
    for job in failed:
        say(describe(job))
        if job.get("web_url"):
            say(job["web_url"])
        trace = glab_raw(f"projects/{project}/jobs/{job['id']}/trace")
        if trace is None:
            say("(log unavailable)")
            continue
        for line in clean_log(trace)[-tail:]:
            say(line)
    return len(failed)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    which = parser.add_mutually_exclusive_group()
    which.add_argument("--mr", type=int, help="inspect this MR's head pipeline")
    which.add_argument("--pipeline", type=int, help="inspect this pipeline")
    parser.add_argument("--tail", type=int, default=40, help="log lines per failed job")
    parser.add_argument("--project", help="namespace/path; default from the remote URL")
    parser.add_argument("--remote", default="origin")
    args = parser.parse_args()

    project = resolve_project(args.remote, args.project)
    reported = 0
    for pipeline_id in resolve_pipeline_ids(project, args.mr, args.pipeline):
        reported += report_pipeline(project, pipeline_id, args.tail)
    if reported == 0:
        say("no failed jobs")
        return GREEN
    return RED


if __name__ == "__main__":
    raise SystemExit(main())
