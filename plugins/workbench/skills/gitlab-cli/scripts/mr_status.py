#!/usr/bin/env python3
"""One compact summary of a GitLab MR: what stands between it and a merge.

  mr_status.py [IID]   default: the open MR for the current branch

Prints state, merge status, pipeline, approvals and unresolved review threads
in a handful of lines. A fact it could not read is printed as "unavailable",
never as zero.

Exit contract:
  0  the MR was read (blockers are in the output, not the exit code)
  2  indeterminate: bad setup, MR unreadable, or no open MR for the branch
"""

from __future__ import annotations

import argparse
import urllib.parse

from _glab import (
    INDETERMINATE,
    fail_setup,
    glab_json,
    glab_list,
    resolve_project,
    run,
    say,
)


def count_unresolved(discussions: list[dict]) -> int:
    """Threads with at least one resolvable note that is still unresolved."""
    return sum(
        1
        for d in discussions
        if any(n.get("resolvable") and not n.get("resolved") for n in d.get("notes", []))
    )


def find_branch_mr(project: str, remote: str) -> int:
    code, branch, stderr = run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    if code != 0:
        fail_setup(f"cannot read current branch: {stderr}")
    encoded = urllib.parse.quote(branch, safe="")
    found = glab_list(f"projects/{project}/merge_requests?source_branch={encoded}&state=opened")
    if found is None:
        fail_setup(f"cannot look up MRs for branch {branch}")
    if not found:
        fail_setup(f"no open MR for branch {branch}")
    return found[0]["iid"]


def approvals_line(project: str, iid: int) -> str:
    data = glab_json(f"projects/{project}/merge_requests/{iid}/approvals")
    if not isinstance(data, dict):
        return "approvals: unavailable"
    required = data.get("approvals_required", 0)
    got = required - data.get("approvals_left", 0)
    line = f"approvals: {got} of {required}"
    who = [a["user"]["username"] for a in data.get("approved_by", [])]
    return f"{line} ({', '.join(who)})" if who else line


def threads_line(project: str, iid: int) -> str:
    discussions = glab_list(f"projects/{project}/merge_requests/{iid}/discussions")
    if discussions is None:
        return "unresolved threads: unavailable"
    return f"unresolved threads: {count_unresolved(discussions)}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("iid", nargs="?", type=int)
    parser.add_argument("--project", help="namespace/path; default from the remote URL")
    parser.add_argument("--remote", default="origin")
    args = parser.parse_args()

    project = resolve_project(args.remote, args.project)
    iid = args.iid if args.iid is not None else find_branch_mr(project, args.remote)
    mr = glab_json(f"projects/{project}/merge_requests/{iid}")
    if not isinstance(mr, dict):
        say(f"cannot read MR !{iid}")
        return INDETERMINATE

    flags = [mr.get("state", "?")]
    if mr.get("draft"):
        flags.append("draft")
    if mr.get("has_conflicts"):
        flags.append("conflicts")
    pipeline = mr.get("head_pipeline")
    say(f"!{iid} {mr.get('title', '')} [{', '.join(flags)}]")
    say(f"{mr.get('source_branch')} -> {mr.get('target_branch')}")
    say(f"merge status: {mr.get('detailed_merge_status', 'unknown')}")
    say(f"pipeline: {pipeline['status'] if pipeline else 'none'}")
    say(approvals_line(project, iid))
    say(threads_line(project, iid))
    if mr.get("web_url"):
        say(mr["web_url"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
