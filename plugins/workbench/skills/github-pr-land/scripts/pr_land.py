#!/usr/bin/env python3
"""Land a GitHub PR only at a CI-tested head.

Subcommands:

- ``watch <sha>`` waits on one exact commit's required checks, read from the
  check-runs and statuses of that SHA — never the combined state,
  ``gh pr checks`` or ``statusCheckRollup``, which on these repos read
  ``pending`` with ``total_count: 0`` forever.

Exit contract: 0 green, 1 red, 2 indeterminate (timeout, refusal, neutral or
unknown outcome, unreadable input). Must run inside a clone of the PR's repo;
every ``gh`` call is pinned to that repo.

Stdlib only, Python 3.10+.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Protocol

GREEN = 0
RED = 1
INDETERMINATE = 2

FULL_SHA = re.compile(r"[0-9a-f]{40}")
PAGE_SIZE = 100

RUN_GREEN = frozenset({"success"})
RUN_RED = frozenset({"failure", "cancelled", "timed_out", "action_required", "startup_failure"})
RUN_INDETERMINATE = frozenset({"neutral", "skipped", "stale"})
STATUS_GREEN = frozenset({"success"})
STATUS_RED = frozenset({"failure", "error"})
STATUS_PENDING = frozenset({"pending"})

NOT_PROTECTED = "Branch not protected"


@dataclass(frozen=True)
class Result:
    """What one command returned."""

    returncode: int
    stdout: str
    stderr: str


class Runner(Protocol):
    """Runs one argv and returns its Result."""

    def run(self, argv: list[str], cwd: str | None = None) -> Result: ...


class SubprocessRunner:
    """Runs argv as a real subprocess."""

    def run(self, argv: list[str], cwd: str | None = None) -> Result:
        """Run *argv* in *cwd*, capturing text output.

        Parameters
        ----------
        argv : list[str]
            Command and arguments.
        cwd : str | None
            Working directory; ``None`` means the current one.

        Returns
        -------
        Result
            The exit code and captured output. A missing binary is returncode
            127 rather than an exception.
        """
        try:
            proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, check=False)
        except OSError as exc:
            return Result(returncode=127, stdout="", stderr=f"{exc}\n")
        return Result(returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)


class Refused(Exception):
    """A precondition failed; the CLI maps this to exit 2."""


@dataclass
class WatchResult:
    """The verdict of one watch, and the check runs and statuses it accepted."""

    code: int
    run_ids: list[int] = field(default_factory=list)
    status_ids: list[int] = field(default_factory=list)


def _owner_name(url: str) -> str:
    parts = [p for p in re.split(r"[/:]", url.strip()) if p]
    if len(parts) < 2:
        return ""
    name = parts[-1][: -len(".git")] if parts[-1].endswith(".git") else parts[-1]
    return f"{parts[-2]}/{name}"


def resolve_repo(runner: Runner) -> str:
    """Return the ``owner/name`` that ``gh`` and ``origin`` agree on.

    Parameters
    ----------
    runner : Runner
        Runs ``gh`` and ``git`` in the target clone.

    Returns
    -------
    str
        The repo as ``gh repo view`` names it.

    Raises
    ------
    Refused
        When either lookup fails or ``origin`` points at a different repo.
    """
    viewed = runner.run(["gh", "repo", "view", "--json", "nameWithOwner"])
    if viewed.returncode != 0:
        raise Refused(f"gh repo view failed: {viewed.stderr.strip()}")
    try:
        payload = json.loads(viewed.stdout)
    except json.JSONDecodeError:
        payload = None
    repo = payload.get("nameWithOwner") if isinstance(payload, dict) else None
    if not isinstance(repo, str) or not repo:
        raise Refused("gh repo view returned no nameWithOwner")
    origin = runner.run(["git", "remote", "get-url", "origin"])
    if origin.returncode != 0:
        raise Refused(f"git remote get-url origin failed: {origin.stderr.strip()}")
    from_origin = _owner_name(origin.stdout)
    if from_origin.casefold() != repo.casefold():
        raise Refused(f"origin is {from_origin or origin.stdout.strip()!r} but gh resolves {repo!r}")
    return repo


def gh(runner: Runner, repo: str, *args: str) -> Result:
    """Run one ``gh`` command pinned to *repo*; never raises.

    ``gh api`` rejects ``-R``, so its endpoint — which must be the argument
    right after ``api`` — has to name the repo instead. Every other subcommand
    gets ``-R <repo>`` appended.

    Parameters
    ----------
    runner : Runner
        Runs the argv.
    repo : str
        ``owner/name`` every call is pinned to.
    *args : str
        The ``gh`` arguments, without ``gh`` itself.

    Returns
    -------
    Result
        The command's Result unchanged, or a returncode-2 Result without
        running anything when an ``api`` endpoint is not under the repo.
    """
    if args[:1] == ("api",):
        if len(args) < 2 or not args[1].startswith(f"repos/{repo}/"):
            return Result(returncode=2, stdout="", stderr=f"refused: gh api endpoint not under repos/{repo}/: {args[1:2]}\n")
        return runner.run(["gh", *args])
    return runner.run(["gh", *args, "-R", repo])


def _api_json(runner: Runner, repo: str, endpoint: str) -> object | None:
    result = gh(runner, repo, "api", endpoint)
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def _resolve_sha(runner: Runner, sha: str) -> str | None:
    result = runner.run(["git", "rev-parse", "--verify", f"{sha}^{{commit}}"])
    full = result.stdout.strip()
    if result.returncode != 0 or not FULL_SHA.fullmatch(full):
        return None
    return full


def _required_names(runner: Runner, repo: str, branch: str | None, require: Iterable[str]) -> dict[str, int | None] | None:
    """Map each required name to its pinned app id (``None`` = any source).

    Returns ``None`` when the protection read fails for any reason other than
    the branch being unprotected.
    """
    names: dict[str, int | None] = {name: None for name in require}
    if branch is None:
        return names
    result = gh(runner, repo, "api", f"repos/{repo}/branches/{branch}/protection")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        payload = None
    if result.returncode != 0:
        message = payload.get("message") if isinstance(payload, dict) else None
        if message == NOT_PROTECTED and "HTTP 404" in result.stderr:
            return names
        print(f"cannot read protection of {branch}: {result.stderr.strip()}", file=sys.stderr)
        return None
    if not isinstance(payload, dict):
        print(f"cannot parse protection of {branch}", file=sys.stderr)
        return None
    checks = payload.get("required_status_checks")
    if not isinstance(checks, dict):
        return names
    contexts = checks.get("contexts")
    for context in contexts if isinstance(contexts, list) else []:
        if isinstance(context, str):
            names.setdefault(context, None)
    pinned = checks.get("checks")
    for check in pinned if isinstance(pinned, list) else []:
        if isinstance(check, dict) and isinstance(check.get("context"), str):
            app_id = check.get("app_id")
            names[check["context"]] = app_id if isinstance(app_id, int) else None
    return names


def _fetch_pages(runner: Runner, repo: str, path: str, key: str | None) -> list[dict] | None:
    items: list[dict] = []
    page = 1
    while True:
        payload = _api_json(runner, repo, f"repos/{repo}/{path}?per_page={PAGE_SIZE}&page={page}")
        batch = payload.get(key) if key is not None and isinstance(payload, dict) else payload
        if not isinstance(batch, list):
            return None
        items.extend(item for item in batch if isinstance(item, dict))
        if len(batch) < PAGE_SIZE:
            return items
        page += 1


def _latest_runs(runs: list[dict], name: str, app_id: int | None) -> list[dict]:
    """Latest run per check suite (highest run id) among runs accepted for *name*."""
    latest: dict[int, dict] = {}
    for run in runs:
        suite = run.get("check_suite")
        app = run.get("app")
        if run.get("name") != name or not isinstance(run.get("id"), int) or not isinstance(suite, dict):
            continue
        if app_id is not None and not (isinstance(app, dict) and app.get("id") == app_id):
            continue
        suite_id = suite.get("id")
        if not isinstance(suite_id, int):
            continue
        best = latest.get(suite_id)
        if best is None or run["id"] > best["id"]:
            latest[suite_id] = run
    return [latest[key] for key in sorted(latest)]


def _latest_status(statuses: list[dict], name: str, app_id: int | None) -> dict | None:
    """The newest status for context *name*, unless the name is pinned to an app."""
    if app_id is not None:
        return None
    for status in statuses:
        if status.get("context") == name:
            return status
    return None


def _run_verdict(run: dict) -> int | None:
    """``None`` while pending, else the exit code this run alone implies."""
    if run.get("status") != "completed":
        return None
    conclusion = run.get("conclusion")
    if conclusion in RUN_GREEN:
        return GREEN
    if conclusion in RUN_RED:
        return RED
    return INDETERMINATE


def _status_verdict(status: dict) -> int | None:
    state = status.get("state")
    if state in STATUS_PENDING:
        return None
    if state in STATUS_GREEN:
        return GREEN
    if state in STATUS_RED:
        return RED
    return INDETERMINATE


def watch_sha(
    runner: Runner,
    repo: str,
    sha: str,
    *,
    branch: str | None = None,
    require: Sequence[str] = (),
    timeout: float = 2700,
    interval: float = 15,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> WatchResult:
    """Wait until every required check on *sha* is terminal, then judge it.

    Parameters
    ----------
    runner : Runner
        Runs ``git`` and ``gh`` in the target clone.
    repo : str
        ``owner/name`` every ``gh`` call is pinned to.
    sha : str
        Any commit-ish; expanded to the full 40-character SHA.
    branch : str | None
        Base branch whose protection supplies required names and app pins.
    require : Sequence[str]
        Extra required names, unioned with the protection's.
    timeout : float
        Seconds before an unfinished watch exits indeterminate.
    interval : float
        Seconds between polls.
    clock, sleep : Callable
        Injectable time source and sleeper.

    Returns
    -------
    WatchResult
        The exit code and the ids of the accepted check runs and statuses.
    """
    full = _resolve_sha(runner, sha)
    if full is None:
        print(f"not a commit: {sha}", file=sys.stderr)
        return WatchResult(INDETERMINATE)
    required = _required_names(runner, repo, branch, require)
    if required is None:
        return WatchResult(INDETERMINATE)
    if not required:
        print("no required checks: pass --require or --branch with required status checks", file=sys.stderr)
        return WatchResult(INDETERMINATE)

    deadline = clock() + timeout
    while True:
        runs = _fetch_pages(runner, repo, f"commits/{full}/check-runs", "check_runs")
        statuses = _fetch_pages(runner, repo, f"commits/{full}/statuses", None)
        lines: list[str] = []
        verdicts: list[int | None] = []
        run_ids: list[int] = []
        status_ids: list[int] = []
        if runs is None or statuses is None:
            print(f"could not read checks for {full}; polling again", file=sys.stderr)
            verdicts.append(None)
            runs, statuses = [], []
        for name, app_id in required.items():
            accepted = _latest_runs(runs, name, app_id)
            status = _latest_status(statuses, name, app_id)
            if not accepted and status is None:
                lines.append(f"{name} no check runs or statuses yet")
                verdicts.append(None)
            for run in accepted:
                shown = run.get("conclusion") if run.get("status") == "completed" else run.get("status")
                lines.append(f"{name} suite={run['check_suite'].get('id')} run={run['id']} {shown}")
                run_ids.append(run["id"])
                verdicts.append(_run_verdict(run))
            if status is not None:
                lines.append(f"{name} status={status.get('id')} {status.get('state')}")
                if isinstance(status.get("id"), int):
                    status_ids.append(status["id"])
                verdicts.append(_status_verdict(status))

        if None not in verdicts:
            for line in lines:
                print(line)
            if RED in verdicts:
                return WatchResult(RED, run_ids, status_ids)
            if INDETERMINATE in verdicts:
                return WatchResult(INDETERMINATE, run_ids, status_ids)
            return WatchResult(GREEN, run_ids, status_ids)
        if clock() >= deadline:
            for line in lines:
                print(line)
            print(f"timed out after {timeout}s waiting on {full}", file=sys.stderr)
            return WatchResult(INDETERMINATE, run_ids, status_ids)
        sleep(interval)


@dataclass(frozen=True)
class PrInfo:
    """The PR fields a land needs, with the base read at its live tip."""

    number: int
    head_sha: str
    head_ref: str
    head_repo: str
    base_ref: str
    base_sha: str


@dataclass(frozen=True)
class RefreshResult:
    """What the refresh-and-gate steps did, and the head the gate tested."""

    tested_sha: str
    pushed: bool
    gate_note: str
    exit_code: int
    message: str


def read_pr(runner: Runner, repo: str, pr: int) -> PrInfo:
    """Read *pr*'s head and the live tip of its base branch.

    ``pulls/<pr>.base.sha`` is never used: GitHub freezes it at the PR's last
    update, so it can trail the live base by any number of commits.

    Parameters
    ----------
    runner : Runner
        Runs ``gh``.
    repo : str
        ``owner/name`` every ``gh`` call is pinned to.
    pr : int
        The pull request number.

    Returns
    -------
    PrInfo
        The PR's head and base, ``base_sha`` read from ``git/ref/heads/<base_ref>``.

    Raises
    ------
    Refused
        When either read fails or returns an unexpected shape.
    """
    payload = _api_json(runner, repo, f"repos/{repo}/pulls/{pr}")
    head = payload.get("head") if isinstance(payload, dict) else None
    base = payload.get("base") if isinstance(payload, dict) else None
    head_repo = head.get("repo") if isinstance(head, dict) else None
    if not isinstance(payload, dict) or not isinstance(head, dict) or not isinstance(base, dict):
        raise Refused(f"cannot read pull request {pr}")
    number = payload.get("number")
    head_sha = head.get("sha")
    head_ref = head.get("ref")
    base_ref = base.get("ref")
    full_name = head_repo.get("full_name") if isinstance(head_repo, dict) else None
    if (
        not isinstance(number, int)
        or not isinstance(head_sha, str)
        or not FULL_SHA.fullmatch(head_sha)
        or not isinstance(head_ref, str)
        or not head_ref
        or not isinstance(base_ref, str)
        or not base_ref
        or not isinstance(full_name, str)
    ):
        raise Refused(f"pull request {pr} is missing its head or base")
    ref = _api_json(runner, repo, f"repos/{repo}/git/ref/heads/{base_ref}")
    target = ref.get("object") if isinstance(ref, dict) else None
    base_sha = target.get("sha") if isinstance(target, dict) else None
    if not isinstance(base_sha, str) or not FULL_SHA.fullmatch(base_sha):
        raise Refused(f"cannot read the tip of {base_ref}")
    return PrInfo(number, head_sha, head_ref, full_name, base_ref, base_sha)


def _refused(info: PrInfo, message: str, gate_note: str = "not run") -> RefreshResult:
    return RefreshResult(info.head_sha, False, gate_note, INDETERMINATE, message)


def _patch_id(diff: str) -> str:
    proc = subprocess.run(
        ["git", "patch-id", "--stable"], input=diff, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False
    )
    return proc.stdout.split()[0] if proc.returncode == 0 and proc.stdout.split() else ""


def _remove_worktree(runner: Runner, scratch: str) -> None:
    """Remove *scratch* and prune its record; never raises."""
    try:
        runner.run(["git", "worktree", "remove", "--force", scratch])
        runner.run(["git", "worktree", "prune"])
    except Exception as exc:  # cleanup must not mask the caller's outcome
        print(f"cleanup of {scratch} failed: {exc}", file=sys.stderr)
    shutil.rmtree(scratch, ignore_errors=True)


def refresh_and_gate(
    runner: Runner,
    repo: str,
    info: PrInfo,
    *,
    gate: str,
    gate_evidence: str | None = None,
    accept_delta_change: bool = False,
    trunk: str = "dev",
    release: str = "main",
) -> RefreshResult:
    """Merge the live base into the PR head, gate the result, and push it.

    Every step after the ancestry check runs in a detached scratch worktree;
    the caller's working tree and branch are never touched. The push is a plain
    fast-forward, so a head that moved on origin since it was read refuses.

    Parameters
    ----------
    runner : Runner
        Runs ``git`` in the caller's clone and in the scratch worktree.
    repo : str
        ``owner/name`` the head must live in.
    info : PrInfo
        The PR, as ``read_pr`` returned it.
    gate : str
        Shell command run as ``bash -o pipefail -c <gate>`` in the scratch worktree.
    gate_evidence : str | None
        Regex that must match the gate's output for a pass to count.
    accept_delta_change : bool
        Proceed when the PR's patch-id changed across the refresh.
    trunk, release : str
        A ``trunk`` head into a ``release`` base is a promotion, refused here.

    Returns
    -------
    RefreshResult
        Exit 0 tested (and pushed, when a refresh was needed), 1 gate red,
        2 refused or indeterminate with ``message`` saying why.
    """
    if info.head_repo.casefold() != repo.casefold():
        return _refused(info, f"head lives in {info.head_repo!r}, not {repo!r}; fork PRs are not landed")
    if info.head_ref == trunk and info.base_ref == release:
        return _refused(info, f"{trunk} into {release} is a promotion; use promote")
    head_sha, base_sha = info.head_sha, info.base_sha

    fetched = runner.run(["git", "fetch", "origin", head_sha, base_sha])
    if fetched.returncode != 0:
        return _refused(info, f"git fetch failed: {fetched.stderr.strip()}")
    contained = runner.run(["git", "merge-base", "--is-ancestor", base_sha, head_sha])
    if contained.returncode == 0:
        return RefreshResult(head_sha, False, "not run (head contained base)", GREEN, "")
    if contained.returncode != 1:
        return _refused(info, f"git merge-base --is-ancestor exited {contained.returncode}: {contained.stderr.strip()}")
    fork_point = runner.run(["git", "merge-base", base_sha, head_sha])
    if fork_point.returncode != 0:
        return _refused(info, f"git merge-base failed: {fork_point.stderr.strip()}")
    before = runner.run(["git", "diff", fork_point.stdout.strip(), head_sha])

    scratch = tempfile.mkdtemp(prefix="pr-land-")
    try:
        added = runner.run(["git", "worktree", "add", "--detach", scratch, head_sha])
        if added.returncode != 0:
            return _refused(info, f"git worktree add failed: {added.stderr.strip()}")
        merged = runner.run(["git", "merge", "--no-edit", base_sha], cwd=scratch)
        if merged.returncode != 0:
            conflicted = runner.run(["git", "diff", "--name-only", "--diff-filter=U"], cwd=scratch)
            runner.run(["git", "merge", "--abort"], cwd=scratch)
            files = conflicted.stdout.strip() or "(none listed)"
            return _refused(info, f"merging {info.base_ref} conflicts; resolve by hand:\n{files}")

        after = runner.run(["git", "diff", base_sha, "HEAD"], cwd=scratch)
        if before.returncode != 0 or after.returncode != 0:
            return _refused(info, "git diff failed while computing the PR's delta")
        if not before.stdout.strip() or not after.stdout.strip():
            return _refused(info, "the PR's delta is empty on one side of the refresh; the base already contains it")
        before_id, after_id = _patch_id(before.stdout), _patch_id(after.stdout)
        if before_id != after_id and not accept_delta_change:
            return _refused(
                info, "the PR's patch-id changed across the refresh; review the merge, then pass accept_delta_change"
            )

        proc = subprocess.run(
            ["bash", "-o", "pipefail", "-c", gate],
            cwd=scratch,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if proc.returncode in (126, 127):
            note = f"did not run ({proc.returncode})"
            return _refused(info, f"gate did not run: {proc.stderr.strip()}", note)
        if proc.returncode != 0:
            return RefreshResult(head_sha, False, f"exit {proc.returncode}", RED, "gate failed")
        note = "exit 0"
        if gate_evidence is not None:
            match = re.search(gate_evidence, proc.stdout + proc.stderr)
            if match is None:
                return _refused(info, f"gate output has no match for {gate_evidence!r}", note)
            note += f", evidence '{match.group(0)}'"

        tip = runner.run(["git", "rev-parse", "HEAD"], cwd=scratch)
        if tip.returncode != 0 or not FULL_SHA.fullmatch(tip.stdout.strip()):
            return _refused(info, "cannot read the refreshed head", note)
        pushed = runner.run(["git", "push", "origin", f"HEAD:refs/heads/{info.head_ref}"], cwd=scratch)
        if pushed.returncode != 0:
            return _refused(info, f"push to {info.head_ref} refused: {pushed.stderr.strip()}", note)
        return RefreshResult(tip.stdout.strip(), True, note, GREEN, "")
    finally:
        _remove_worktree(runner, scratch)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pr_land.py", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    watch = commands.add_parser("watch", help="wait on one exact SHA's required checks")
    watch.add_argument("sha")
    watch.add_argument("--branch", default=None, help="base branch whose protection lists the required checks")
    watch.add_argument("--require", action="append", default=[], metavar="NAME", help="extra required check (repeatable)")
    watch.add_argument("--timeout", type=float, default=2700)
    watch.add_argument("--interval", type=float, default=15)
    return parser


def main(
    argv: list[str] | None = None,
    *,
    runner: Runner | None = None,
    clock: Callable[[], float] | None = None,
    sleep: Callable[[float], None] | None = None,
) -> int:
    """Run the CLI and return its exit code.

    Parameters
    ----------
    argv : list[str] | None
        Arguments; ``None`` reads ``sys.argv``.
    runner, clock, sleep
        Injectable dependencies; ``None`` selects the real ones.

    Returns
    -------
    int
        0 green, 1 red, 2 indeterminate.
    """
    args = _parser().parse_args(argv)
    runner = runner if runner is not None else SubprocessRunner()
    clock = clock if clock is not None else time.monotonic
    sleep = sleep if sleep is not None else time.sleep
    try:
        repo = resolve_repo(runner)
    except Refused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return INDETERMINATE
    result = watch_sha(
        runner,
        repo,
        args.sha,
        branch=args.branch,
        require=args.require,
        timeout=args.timeout,
        interval=args.interval,
        clock=clock,
        sleep=sleep,
    )
    return result.code


if __name__ == "__main__":
    raise SystemExit(main())
