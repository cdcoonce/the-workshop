#!/usr/bin/env python3
"""Watch GitLab CI until terminal and report per-job status.

Modes:
  ci_watch.py sha [SHA]      watch every pipeline for a pushed commit (default HEAD)
  ci_watch.py mr IID         poll an MR until merged, then watch the merge commit
  ci_watch.py branch NAME    watch the remote head of an integration branch
  ci_watch.py pipeline ID    watch one specific pipeline until terminal

Exit contract (the verdict a session must relay, per verify-ci-green):
  0  pipeline succeeded AND every job green — or, with --manual-gate JOB,
     it rests only on named gates and every job that ran is green
  1  red — pipeline failed/canceled, or any job failed/canceled (roll-up
     success with a failed allow_failure job is still red)
  2  indeterminate — setup failure (wrong cwd, missing remote), crash,
     timeout, MR closed, blocked on a manual job no --manual-gate named,
     repeated API failures, or per-job status unverifiable

Every glab call is guarded: stderr noise, empty stdout, or a nonzero exit is
one skipped tick, never a dead watcher. The project is derived from the remote
URL and passed explicitly, so glab's own remote inference (alphabetically
first when several gitlab.com remotes exist) never picks the wrong repo.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path
from typing import NoReturn

GREEN = 0
RED = 1
INDETERMINATE = 2

PENDING_STATUSES = {
    "created",
    "waiting_for_resource",
    "preparing",
    "pending",
    "running",
    "scheduled",
    "canceling",
}
RED_STATUSES = {"failed", "canceled"}
# Job statuses a pipeline parked on its manual gates may hold: finished, the
# gates themselves (or optional manual jobs), and jobs queued behind a gate.
PARKED_STATUSES = {"success", "skipped", "manual", "created"}
MAX_CONSECUTIVE_FAILURES = 15
# An empty pipeline list is ambiguous: a ref the rules exclude looks exactly
# like one whose pipeline has not been created yet. Confirm across several
# polls so an open MR's pipeline arriving late is never called unreachable.
UNREACHABLE_CONFIRM_POLLS = 3
JOB_FETCH_RETRIES = 3
MAX_JOB_PAGES = 10
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


def say(message: str) -> None:
    print(message, flush=True)


def fail_setup(message: str) -> NoReturn:
    """Exit 1 is reserved for a red pipeline: a watch that never started is
    indeterminate, or the session relays a CI failure that never happened."""
    say(message)
    raise SystemExit(INDETERMINATE)


def run(args: list[str]) -> tuple[int, str, str]:
    result = subprocess.run(args, capture_output=True, text=True)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def glab_api(path: str) -> object | None:
    """One guarded API call: any failure shape collapses to None (skip a tick)."""
    code, stdout, _stderr = run(["glab", "api", path])
    if code != 0 or not stdout:
        return None
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return None


def parse_project_path(url: str) -> str | None:
    """Namespace path from a GitLab remote URL (ssh scp-form, ssh://, https)."""
    if "://" in url:
        path = urllib.parse.urlsplit(url).path
    elif ":" in url:
        path = url.split(":", 1)[1]
    else:
        return None
    path = path.strip("/")
    if path.endswith(".git"):
        path = path[: -len(".git")]
    return path or None


def resolve_project(remote: str, override: str | None) -> str:
    """URL-encoded project path for the API, from --project or the remote URL."""
    if override:
        return urllib.parse.quote(override, safe="")
    code, url, stderr = run(["git", "remote", "get-url", remote])
    if code != 0:
        fail_setup(f"cannot read remote {remote!r}: {stderr}")
    path = parse_project_path(url)
    if path is None:
        fail_setup(f"cannot derive a project path from remote URL {url!r}; pass --project")
    return urllib.parse.quote(path, safe="")


def fetch_listing(
    project: str, pipeline_id: int, endpoint: str, interval: float
) -> list[dict] | None:
    entries: list[dict] = []
    for page in range(1, MAX_JOB_PAGES + 1):
        path = (
            f"projects/{project}/pipelines/{pipeline_id}/{endpoint}"
            f"?per_page=100&page={page}"
        )
        for attempt in range(JOB_FETCH_RETRIES):
            data = glab_api(path)
            if isinstance(data, list):
                break
            if attempt < JOB_FETCH_RETRIES - 1:
                time.sleep(interval)
        else:
            return None
        entries.extend(data)
        if len(data) < 100:
            return entries
    # Page cap exhausted with more likely remaining: completeness is unproven,
    # and an incomplete listing must never pass as "every job green".
    return None


def manual_verdict(entries: list[dict], manual_gates: frozenset[str]) -> int:
    """Verdict for a pipeline GitLab reports as `manual`, with no job red.

    Blocking manual jobs (`when: manual` without `allow_failure: true`) are
    what hold it there. It passes only when each one is a named gate and one
    of them is actually waiting, with nothing else able to run on its own —
    jobs still `created` can then start only once a human plays a gate.
    """
    waiting = sorted(
        e.get("name", "?")
        for e in entries
        if e.get("status") == "manual" and not e.get("allow_failure")
    )
    if not waiting:
        say("verdict: pipeline reports manual but no job waits on a human — re-query needed")
        return INDETERMINATE
    ungated = [name for name in waiting if name not in manual_gates]
    if ungated:
        flags = " ".join(f"--manual-gate {name}" for name in ungated)
        say(
            f"verdict: blocked on manual job(s) {', '.join(ungated)} — not a pass;"
            f" if that is an expected gate, add {flags}"
        )
        return INDETERMINATE
    unfinished = sorted(
        f"{e.get('name', '?')} ({e.get('status', 'unknown')})"
        for e in entries
        if e.get("status") not in PARKED_STATUSES
    )
    if unfinished:
        say(f"verdict: automatic work remains — {', '.join(unfinished)} — not a pass")
        return INDETERMINATE
    behind = sorted(e.get("name", "?") for e in entries if e.get("status") == "created")
    held = f"; not run behind it: {', '.join(behind)}" if behind else ""
    say(f"verdict: every job green up to manual gate {', '.join(waiting)}{held}")
    return GREEN


def report(
    project: str,
    pipe: dict,
    sha: str,
    interval: float,
    manual_gates: frozenset[str] = frozenset(),
) -> int:
    """Print the per-job report for a terminal pipeline and return the verdict.

    Trigger jobs live on /bridges, not /jobs — a red downstream pipeline is
    part of the verdict, so both listings are required.
    """
    status = pipe.get("status", "unknown")
    say(f"pipeline {pipe['id']} for {sha}: {status}  {pipe.get('web_url', '')}")
    jobs = fetch_listing(project, pipe["id"], "jobs", interval)
    bridges = fetch_listing(project, pipe["id"], "bridges", interval)
    if jobs is None or bridges is None:
        say("per-job status unavailable — re-query needed before trusting this result")
        return INDETERMINATE
    any_red = False
    entries = jobs + [dict(b, _bridge=True) for b in bridges]
    for job in entries:
        job_status = job.get("status", "unknown")
        suffix = " [bridge]" if job.get("_bridge") else ""
        if job.get("allow_failure") and job_status == "failed":
            suffix += " (allow_failure — roll-up stays green, house rule says red)"
        say(f"  {job.get('name', '?')}: {job_status}{suffix}")
        if job_status in RED_STATUSES:
            any_red = True
    if status in RED_STATUSES or any_red:
        say("verdict: RED — do not declare this work done")
        return RED
    if status == "success":
        say("verdict: every job green")
        return GREEN
    if status == "manual":
        return manual_verdict(entries, manual_gates)
    say(f"verdict: pipeline is {status} — needs attention, not a pass")
    return INDETERMINATE


def newest_per_ref(data: list, ref: str | None) -> list[dict] | None:
    """Select the pipelines whose verdicts matter, in listing order.

    One SHA can carry several pipelines at once — an MR-head pipeline and a
    branch pipeline — and a green one on one ref must never stand in for a
    red one on another, so every ref's newest pipeline (the API lists newest
    first) is selected; a retried run still supersedes its predecessor on the
    same ref. With `ref`, entries on other refs (or with no provable ref) are
    dropped even if the server ignored the query parameter. A malformed entry
    poisons the whole listing (None): selecting around noise could silently
    drop the red pipeline.
    """
    selected: list[dict] = []
    seen_refs: set[str | None] = set()
    for pipe in data:
        if not isinstance(pipe, dict) or "id" not in pipe:
            return None
        pipe_ref = pipe.get("ref")
        if ref is not None and pipe_ref != ref:
            continue
        if pipe_ref in seen_refs:
            continue
        seen_refs.add(pipe_ref)
        selected.append(pipe)
    return selected


def _workflow_rules(root: Path) -> list[tuple[str, str]] | None:
    """``workflow.rules`` from .gitlab-ci.yml as (if-expression, when) pairs.

    Deliberately a small line scanner rather than a YAML dependency: this
    script is stdlib-only and invoked as plain ``python3``. Anything it cannot
    read confidently returns None, which the caller treats as "no opinion".
    """
    path = root / ".gitlab-ci.yml"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None

    body: list[str] = []
    inside = False
    for line in lines:
        if not inside:
            if line.rstrip() == "workflow:":
                inside = True
            continue
        if line.strip() and not line.startswith((" ", "\t")):
            break  # dedented back to a new top-level key
        body.append(line)
    if not inside:
        return None  # no workflow gate: branch pipelines are not restricted

    rules: list[tuple[str, str]] = []
    in_rules = False
    for line in body:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped == "rules:":
            in_rules = True
            continue
        if not in_rules:
            continue
        if stripped.startswith("- "):
            item = stripped[2:].strip()
            if not item.startswith("if:"):
                return None  # a rule shape this scanner does not model
            rules.append((item[len("if:"):].strip(), "on_success"))
        elif stripped.startswith("when:") and rules:
            expression, _ = rules[-1]
            rules[-1] = (expression, stripped[len("when:"):].strip())
        elif stripped.startswith("if:") and rules:
            return None  # continuation shape not modelled
    return rules or None


def _atom_matches_branch_push(atom: str, ref: str) -> bool | None:
    """Evaluate one ``if:`` atom against a branch pipeline on ``ref``."""
    atom = atom.strip().strip("()").strip()
    equality = re.match(
        r'^\$(\w+)\s*(==|!=)\s*[\'"]([^\'"]*)[\'"]$', atom
    )
    if equality:
        name, operator, value = equality.groups()
        if name == "CI_COMMIT_BRANCH":
            actual: str | None = ref
        elif name == "CI_PIPELINE_SOURCE":
            actual = "push"
        elif name in {"CI_COMMIT_TAG", "CI_MERGE_REQUEST_IID"}:
            actual = None
        else:
            return None
        result = (actual == value) if operator == "==" else (actual != value)
        return result
    bare = re.match(r"^\$(\w+)$", atom)
    if bare:
        name = bare.group(1)
        if name == "CI_COMMIT_BRANCH":
            return True
        if name in {"CI_COMMIT_TAG", "CI_MERGE_REQUEST_IID", "CI_OPEN_MERGE_REQUESTS"}:
            # A tag ref is not this ref; MR variables are absent on a branch
            # push. CI_OPEN_MERGE_REQUESTS is unknowable from here, but it only
            # ever appears in suppression rules, so treating it as absent
            # cannot turn a reachable ref into an unreachable verdict.
            return False
        return None
    return None


def _expression_matches_branch_push(expression: str, ref: str) -> bool | None:
    """Evaluate an ``if:`` expression; None whenever any atom is unmodelled."""
    if "||" in expression:
        parts = [_atom_matches_branch_push(a, ref) for a in expression.split("||")]
        if None in parts:
            return None
        return any(parts)
    if "&&" in expression:
        parts = [_atom_matches_branch_push(a, ref) for a in expression.split("&&")]
        if None in parts:
            return None
        return all(parts)
    return _atom_matches_branch_push(expression, ref)


def branch_pipeline_reachable(root: Path, ref: str) -> bool | None:
    """Can a plain push to ``ref`` create a pipeline at all?

    True/False when ``workflow.rules`` answers it confidently, None when this
    scanner cannot tell — the caller must keep waiting on None, because a
    wrong "unreachable" is a false verdict and waiting is merely slow.
    """
    rules = _workflow_rules(root)
    if rules is None:
        return None
    for expression, when in rules:
        matched = _expression_matches_branch_push(expression, ref)
        if matched is None:
            return None  # cannot know which rule wins; offer no opinion
        if matched:
            return when != "never"  # first match decides
    return False  # every rule evaluated and none matched


def repo_root() -> Path | None:
    code, out, _stderr = run(["git", "rev-parse", "--show-toplevel"])
    return Path(out) if code == 0 and out else None


def current_branch() -> str | None:
    code, out, _stderr = run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    return out if code == 0 and out and out != "HEAD" else None


def unreachable_reason(ref: str | None) -> str | None:
    """Message explaining why ``ref`` can never produce a pipeline, or None."""
    root = repo_root()
    if root is None or not ref:
        return None
    if branch_pipeline_reachable(root, ref) is not False:
        return None
    return (
        f"no pipeline will be created for {ref!r}: .gitlab-ci.yml workflow.rules "
        "excludes a plain push to this ref. Opening a merge request is what runs "
        "CI here — nothing to watch until then."
    )


def watch_pipeline(
    project: str,
    sha: str,
    ref: str | None,
    interval: float,
    deadline: float,
    manual_gates: frozenset[str] = frozenset(),
) -> int:
    query = f"projects/{project}/pipelines?sha={sha}"
    if ref:
        query += f"&ref={urllib.parse.quote(ref, safe='')}"
    failures = 0
    last_status: dict[int, str] = {}
    waiting_announced = False
    empty_polls = 0
    rules_ref = ref or current_branch()
    while True:
        if time.time() > deadline:
            say(f"timed out waiting on a terminal pipeline for {sha}")
            return INDETERMINATE
        data = glab_api(query)
        pipes = newest_per_ref(data, ref) if isinstance(data, list) else None
        if pipes is None:
            failures += 1
            if failures >= MAX_CONSECUTIVE_FAILURES:
                say(f"{failures} consecutive API failures — giving up, re-query needed")
                return INDETERMINATE
            time.sleep(interval)
            continue
        failures = 0
        if not pipes:
            empty_polls += 1
            if not waiting_announced:
                target = f"{sha} on {ref}" if ref else sha
                say(f"no pipeline for {target} yet — waiting")
                waiting_announced = True
            if empty_polls >= UNREACHABLE_CONFIRM_POLLS:
                reason = unreachable_reason(rules_ref)
                if reason:
                    say(reason)
                    return INDETERMINATE
            time.sleep(interval)
            continue
        empty_polls = 0
        for pipe in pipes:
            status = pipe.get("status", "unknown")
            if last_status.get(pipe["id"]) != status:
                say(f"pipeline {pipe['id']} ({pipe.get('ref', '?')}): {status}")
                last_status[pipe["id"]] = status
        if any(pipe.get("status") in PENDING_STATUSES for pipe in pipes):
            time.sleep(interval)
            continue
        if len(pipes) > 1:
            say(f"{len(pipes)} pipelines for {sha} — every one is part of the verdict")
        verdicts = [report(project, pipe, sha, interval, manual_gates) for pipe in pipes]
        if RED in verdicts:
            return RED
        if INDETERMINATE in verdicts:
            return INDETERMINATE
        return GREEN


def watch_pipeline_by_id(
    project: str,
    pipeline_id: str,
    interval: float,
    deadline: float,
    manual_gates: frozenset[str] = frozenset(),
) -> int:
    """Watch one specific pipeline — the direct escape hatch when a SHA
    carries several pipelines and exactly one of them is the question."""
    failures = 0
    last_status: str | None = None
    while True:
        if time.time() > deadline:
            say(f"timed out waiting on pipeline {pipeline_id} to reach a terminal state")
            return INDETERMINATE
        data = glab_api(f"projects/{project}/pipelines/{pipeline_id}")
        if not isinstance(data, dict) or "id" not in data:
            failures += 1
            if failures >= MAX_CONSECUTIVE_FAILURES:
                say(f"{failures} consecutive API failures — giving up, re-query needed")
                return INDETERMINATE
            time.sleep(interval)
            continue
        failures = 0
        status = data.get("status", "unknown")
        if status != last_status:
            say(f"pipeline {pipeline_id}: {status}")
            last_status = status
        if status not in PENDING_STATUSES:
            return report(project, data, data.get("sha", "?"), interval, manual_gates)
        time.sleep(interval)


def watch_mr(
    project: str,
    iid: str,
    interval: float,
    timeout: float,
    manual_gates: frozenset[str] = frozenset(),
) -> int:
    deadline = time.time() + timeout
    failures = 0
    last_state: str | None = None
    while True:
        if time.time() > deadline:
            say(f"timed out waiting for MR !{iid} to merge")
            return INDETERMINATE
        data = glab_api(f"projects/{project}/merge_requests/{iid}")
        if not isinstance(data, dict):
            failures += 1
            if failures >= MAX_CONSECUTIVE_FAILURES:
                say(f"{failures} consecutive API failures — giving up, re-query needed")
                return INDETERMINATE
            time.sleep(interval)
            continue
        failures = 0
        state = data.get("state", "unknown")
        if state != last_state:
            say(f"MR !{iid}: {state}")
            last_state = state
        if state == "closed":
            say(f"MR !{iid} was CLOSED without merging — the merge is not happening")
            return INDETERMINATE
        if state == "merged":
            # The merge commit heads the target branch and is what its branch
            # pipeline runs on; the squash commit heads it instead when the
            # merge was squashed. A `merge_method: ff` project creates
            # neither — no merge commit, and squash is off — so both fields
            # come back null. A fast-forward is defined as making the target
            # branch's tip exactly the source branch's tip, and `sha` (the
            # MR's own diff-head SHA) is already that commit, known the
            # instant the merge lands — no `git ls-remote` guess, and no
            # race with something else landing on the target branch after.
            sha = (
                data.get("merge_commit_sha")
                or data.get("squash_commit_sha")
                or data.get("sha")
            )
            if not sha:
                say(f"MR !{iid} merged but reports no merge commit — re-query needed")
                return INDETERMINATE
            ref = data.get("target_branch")
            say(f"MR !{iid} merged as {sha} — watching {ref}")
            # Fresh budget: a slow merge must not leave zero time for the watch.
            return watch_pipeline(
                project, sha, ref, interval, time.time() + timeout, manual_gates
            )
        time.sleep(interval)


def resolve_sha(argument: str | None) -> str:
    """Expand to the full 40-char SHA — an abbreviated one matches no pipelines
    and reads as "still pending" forever."""
    code, sha, stderr = run(["git", "rev-parse", argument or "HEAD"])
    if code != 0:
        fail_setup(f"cannot resolve {argument or 'HEAD'!r}: {stderr}")
    if not FULL_SHA.match(sha):
        fail_setup(f"{argument!r} did not resolve to a full SHA (got {sha!r})")
    return sha


def resolve_branch_head(remote: str, branch: str) -> str:
    """Remote head of the branch — the local clone may be behind the merge."""
    code, out, stderr = run(["git", "ls-remote", remote, f"refs/heads/{branch}"])
    if code != 0 or not out:
        fail_setup(f"cannot resolve {branch!r} on remote {remote!r}: {stderr}")
    return out.split()[0]


def main() -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--remote", default="origin")
    common.add_argument("--project", help="override group/project derived from the remote")
    common.add_argument("--interval", type=float, default=20.0)
    common.add_argument("--timeout", type=float, default=2700.0)
    common.add_argument(
        "--manual-gate",
        action="append",
        metavar="JOB",
        help="a manual job the pipeline is expected to park on; repeatable",
    )
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    sha_cmd = sub.add_parser("sha", parents=[common], help="watch pipelines for a commit")
    sha_cmd.add_argument("commit", nargs="?", help="commit-ish, default HEAD")
    sha_cmd.add_argument("--ref", help="restrict to pipelines on this ref")
    mr_cmd = sub.add_parser("mr", parents=[common], help="poll an MR until merged, then watch")
    mr_cmd.add_argument("iid")
    branch_cmd = sub.add_parser(
        "branch", parents=[common], help="watch the remote head of a branch"
    )
    branch_cmd.add_argument("name")
    pipeline_cmd = sub.add_parser(
        "pipeline", parents=[common], help="watch one specific pipeline id"
    )
    pipeline_cmd.add_argument("id")
    args = parser.parse_args()

    project = resolve_project(args.remote, args.project)
    deadline = time.time() + args.timeout
    gates = frozenset(args.manual_gate or ())
    if args.mode == "sha":
        return watch_pipeline(
            project, resolve_sha(args.commit), args.ref, args.interval, deadline, gates
        )
    if args.mode == "mr":
        return watch_mr(project, args.iid, args.interval, args.timeout, gates)
    if args.mode == "pipeline":
        return watch_pipeline_by_id(project, args.id, args.interval, deadline, gates)
    head = resolve_branch_head(args.remote, args.name)
    return watch_pipeline(project, head, args.name, args.interval, deadline, gates)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:  # noqa: BLE001 — a crash is not a red pipeline
        say(f"watcher crashed ({type(error).__name__}: {error}) — re-query needed")
        sys.exit(INDETERMINATE)
