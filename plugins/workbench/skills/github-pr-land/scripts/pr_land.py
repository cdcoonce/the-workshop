#!/usr/bin/env python3
"""Land a GitHub PR only at a CI-tested head.

Subcommands:

- ``watch <sha>`` waits on one exact commit's required checks, read from the
  check-runs and statuses of that SHA — never the combined state,
  ``gh pr checks`` or ``statusCheckRollup``, which on these repos read
  ``pending`` with ``total_count: 0`` forever.
- ``land <pr>`` refreshes a behind head, gates it, waits for GitHub to register
  it, watches it, merges pinned to it, and checks the landed tree is the
  tested tree.
- ``promote <pr>`` watches a ``dev``→``main`` PR's head SHA and fast-forwards
  ``main`` to that literal SHA, exiting 2 when the push bypassed protection.

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
    before = runner.run(["git", "diff", "--no-color", "--no-ext-diff", fork_point.stdout.strip(), head_sha])

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

        after = runner.run(["git", "diff", "--no-color", "--no-ext-diff", base_sha, "HEAD"], cwd=scratch)
        if before.returncode != 0 or after.returncode != 0:
            return _refused(info, "git diff failed while computing the PR's delta")
        if not before.stdout.strip() or not after.stdout.strip():
            return _refused(info, "the PR's delta is empty on one side of the refresh; the base already contains it")
        before_id, after_id = _patch_id(before.stdout), _patch_id(after.stdout)
        if not before_id or not after_id:
            return _refused(
                info, "git patch-id produced no id for the PR's delta; cannot compare it across the refresh"
            )
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


def _base_moved(runner: Runner, repo: str, info: PrInfo) -> bool | None:
    """Whether the live ``git/ref/heads/<base_ref>`` tip left the round's base; ``None`` if unreadable.

    Never ``pulls/<pr>.base.sha``: GitHub does not update it when the base moves.
    """
    ref = _api_json(runner, repo, f"repos/{repo}/git/ref/heads/{info.base_ref}")
    target = ref.get("object") if isinstance(ref, dict) else None
    tip = target.get("sha") if isinstance(target, dict) else None
    if not isinstance(tip, str) or not FULL_SHA.fullmatch(tip):
        print(f"cannot read the tip of {info.base_ref}", file=sys.stderr)
        return None
    return tip != info.base_sha


def _pr_head(runner: Runner, repo: str, pr: int) -> str | None:
    payload = _api_json(runner, repo, f"repos/{repo}/pulls/{pr}")
    head = payload.get("head") if isinstance(payload, dict) else None
    sha = head.get("sha") if isinstance(head, dict) else None
    return sha if isinstance(sha, str) else None


def _tree(runner: Runner, commit: str) -> str | None:
    result = runner.run(["git", "rev-parse", f"{commit}^{{tree}}"])
    tree = result.stdout.strip()
    return tree if result.returncode == 0 and FULL_SHA.fullmatch(tree) else None


def _pr_view(runner: Runner, repo: str, pr: int) -> dict | None:
    """``gh pr view <pr> --json mergeCommit,state`` as a dict; ``None`` if the read fails or is not an object."""
    view = gh(runner, repo, "pr", "view", str(pr), "--json", "mergeCommit,state")
    try:
        payload = json.loads(view.stdout) if view.returncode == 0 else None
    except json.JSONDecodeError:
        payload = None
    return payload if isinstance(payload, dict) else None


def _verify_landed(runner: Runner, pr: int, payload: dict, tested: RefreshResult, watched: WatchResult) -> int:
    """Given a ``MERGED`` view *payload*, confirm the landed tree is the tested tree, then print the ledger line."""
    commit = payload.get("mergeCommit")
    oid = commit.get("oid") if isinstance(commit, dict) else None
    if not isinstance(oid, str) or not FULL_SHA.fullmatch(oid):
        print(f"pull request {pr} is MERGED but names no mergeCommit", file=sys.stderr)
        return INDETERMINATE
    fetched = runner.run(["git", "fetch", "origin", oid])
    if fetched.returncode != 0:
        print(f"git fetch of the merge commit failed: {fetched.stderr.strip()}", file=sys.stderr)
        return INDETERMINATE
    landed = _tree(runner, oid)
    if landed is None:
        print(f"cannot read tree for {oid}", file=sys.stderr)
        return INDETERMINATE
    expected = _tree(runner, tested.tested_sha)
    if expected is None:
        print(f"cannot read tree for {tested.tested_sha}", file=sys.stderr)
        return INDETERMINATE
    if landed != expected:
        print(f"LANDED TREE DIFFERS FROM TESTED TREE: landed {landed} ({oid}), tested {expected} ({tested.tested_sha})", file=sys.stderr)
        return INDETERMINATE
    checks = ",".join([*(str(run_id) for run_id in watched.run_ids), *(f"status:{status_id}" for status_id in watched.status_ids)])
    print(f"landed pr={pr} tested={tested.tested_sha} gate={tested.gate_note} checks={checks} merge={oid}")
    return GREEN


def _check_landed(runner: Runner, repo: str, pr: int, tested: RefreshResult, watched: WatchResult) -> int:
    """Confirm *pr* merged with the tested tree, then print the ledger line."""
    payload = _pr_view(runner, repo, pr)
    state = payload.get("state") if payload is not None else None
    if state != "MERGED":
        print(f"pull request {pr} is in state {state} after gh pr merge, not MERGED", file=sys.stderr)
        return INDETERMINATE
    return _verify_landed(runner, pr, payload, tested, watched)


def land_pr(
    runner: Runner,
    repo: str,
    pr: int,
    *,
    method: str,
    gate: str,
    gate_evidence: str | None = None,
    require: Sequence[str] = (),
    accept_delta_change: bool = False,
    max_rounds: int = 3,
    trunk: str = "dev",
    release: str = "main",
    timeout: float = 2700,
    interval: float = 15,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Refresh, gate, wait on and merge *pr* at exactly the head that was tested.

    Each round refreshes against the live base, waits for GitHub to register
    the pushed head, watches that SHA's checks, and merges pinned to it with
    ``--match-head-commit``. A base that moves during the round starts another,
    up to *max_rounds*. Never passes ``--admin`` or ``--auto``.

    Parameters
    ----------
    runner : Runner
        Runs ``git`` and ``gh`` in the target clone.
    repo : str
        ``owner/name`` every ``gh`` call is pinned to.
    pr : int
        The pull request number.
    method : str
        ``merge``, ``squash`` or ``rebase``.
    gate, gate_evidence, accept_delta_change, trunk, release
        Passed to ``refresh_and_gate``.
    require : Sequence[str]
        Extra required check names, passed to ``watch_sha``.
    max_rounds : int
        Rounds before a base that keeps moving exits 2.
    timeout : float
        Seconds for head registration, and separately for the watch.
    interval : float
        Seconds between polls.
    clock, sleep : Callable
        Injectable time source and sleeper, used for every poll.

    Returns
    -------
    int
        0 landed with the tested tree (after the one ledger line), 1 gate or
        checks red, 2 refused or indeterminate.
    """
    for round_no in range(1, max_rounds + 1):
        try:
            info = read_pr(runner, repo, pr)
        except Refused as exc:
            print(f"refused: {exc}", file=sys.stderr)
            return INDETERMINATE
        tested = refresh_and_gate(
            runner,
            repo,
            info,
            gate=gate,
            gate_evidence=gate_evidence,
            accept_delta_change=accept_delta_change,
            trunk=trunk,
            release=release,
        )
        if tested.exit_code != 0:
            print(tested.message, file=sys.stderr)
            return tested.exit_code

        deadline = clock() + timeout
        while _pr_head(runner, repo, pr) != tested.tested_sha:
            if clock() >= deadline:
                print(f"timed out after {timeout}s waiting for pull request {pr} to show head {tested.tested_sha}", file=sys.stderr)
                return INDETERMINATE
            sleep(interval)

        watched = watch_sha(
            runner,
            repo,
            tested.tested_sha,
            branch=info.base_ref,
            require=require,
            timeout=timeout,
            interval=interval,
            clock=clock,
            sleep=sleep,
        )
        if watched.code != 0:
            return watched.code

        moved = _base_moved(runner, repo, info)
        if moved is False:
            merged = gh(runner, repo, "pr", "merge", str(pr), f"--{method}", "--match-head-commit", tested.tested_sha)
            if merged.returncode == 0:
                return _check_landed(runner, repo, pr, tested, watched)
            # Read the PR before the base: if gh merged it and then errored,
            # our own landing commit has moved the base, and a re-read would
            # start a round on an already-merged PR.
            view = _pr_view(runner, repo, pr)
            state = view.get("state") if view is not None else None
            if state == "MERGED":
                print(f"gh pr merge exited {merged.returncode} but the PR is MERGED: {merged.stderr.strip()}", file=sys.stderr)
                return _verify_landed(runner, pr, view, tested, watched)
            if state != "OPEN":
                if isinstance(state, str):
                    problem = f"pull request {pr} is in state {state} after a failed gh pr merge"
                else:
                    problem = f"cannot read the state of pull request {pr} after a failed gh pr merge"
                print(f"{problem}: {merged.stderr.strip()}", file=sys.stderr)
                return INDETERMINATE
            print(f"gh pr merge failed: {merged.stderr.strip()}", file=sys.stderr)
            moved = _base_moved(runner, repo, info)
            if moved is False:
                return INDETERMINATE
        if moved is None:
            return INDETERMINATE
        print(f"{info.base_ref} moved during round {round_no}", file=sys.stderr)
    print(f"base moved {max_rounds} times", file=sys.stderr)
    return INDETERMINATE


def _branch_tip(runner: Runner, repo: str, branch: str) -> str | None:
    payload = _api_json(runner, repo, f"repos/{repo}/branches/{branch}")
    commit = payload.get("commit") if isinstance(payload, dict) else None
    sha = commit.get("sha") if isinstance(commit, dict) else None
    return sha if isinstance(sha, str) and FULL_SHA.fullmatch(sha) else None


def promote_pr(
    runner: Runner,
    repo: str,
    pr: int,
    *,
    trunk: str = "dev",
    release: str = "main",
    timeout: float = 2700,
    interval: float = 15,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Fast-forward *release* to the ``trunk``→``release`` PR's tested head SHA.

    The head SHA is read once, watched, and pushed as a literal SHA — never a
    ref name, never forced — so what lands is exactly what CI tested. A push
    that GitHub let through by bypassing a rule is reported, not accepted.

    Parameters
    ----------
    runner : Runner
        Runs ``git`` and ``gh`` in the target clone.
    repo : str
        ``owner/name`` every ``gh`` call is pinned to.
    pr : int
        The promotion pull request number.
    trunk, release : str
        The PR's required head and base branches.
    timeout : float
        Seconds for the watch, and separately for the post-push poll.
    interval : float
        Seconds between polls.
    clock, sleep : Callable
        Injectable time source and sleeper, used for every poll.

    Returns
    -------
    int
        0 promoted, 1 checks red, 2 refused, bypassed or indeterminate.
    """
    payload = _api_json(runner, repo, f"repos/{repo}/pulls/{pr}")
    head = payload.get("head") if isinstance(payload, dict) else None
    base = payload.get("base") if isinstance(payload, dict) else None
    head_ref = head.get("ref") if isinstance(head, dict) else None
    base_ref = base.get("ref") if isinstance(base, dict) else None
    sha = head.get("sha") if isinstance(head, dict) else None
    if not isinstance(sha, str) or not FULL_SHA.fullmatch(sha):
        print(f"refused: cannot read the head of pull request {pr}", file=sys.stderr)
        return INDETERMINATE
    if head_ref != trunk or base_ref != release:
        print(f"refused: pull request {pr} is {head_ref} into {base_ref}, not {trunk} into {release}", file=sys.stderr)
        return INDETERMINATE
    fetched = runner.run(["git", "fetch", "origin", sha, release])
    if fetched.returncode != 0:
        print(f"refused: git fetch failed: {fetched.stderr.strip()}", file=sys.stderr)
        return INDETERMINATE

    tip = _branch_tip(runner, repo, release)
    if tip is None:
        print(f"refused: cannot read the tip of {release}", file=sys.stderr)
        return INDETERMINATE
    contained = runner.run(["git", "merge-base", "--is-ancestor", tip, sha])
    if contained.returncode != 0:
        print(f"refused: {release} at {tip} is not an ancestor of {sha}; not a fast-forward", file=sys.stderr)
        return INDETERMINATE

    watched = watch_sha(runner, repo, sha, branch=release, timeout=timeout, interval=interval, clock=clock, sleep=sleep)
    if watched.code != 0:
        return watched.code

    pushed = runner.run(["git", "push", "origin", f"{sha}:refs/heads/{release}"])
    if pushed.returncode != 0:
        print(f"push to {release} refused: {pushed.stderr.strip()}", file=sys.stderr)
        return INDETERMINATE
    bypassed = [line for line in pushed.stderr.splitlines() if "Bypassed rule violations" in line]
    if bypassed:
        for line in bypassed:
            print(line, file=sys.stderr)
        print(f"{sha} landed on {release}, but protection was bypassed, not satisfied", file=sys.stderr)
        return INDETERMINATE

    deadline = clock() + timeout
    while True:
        view = _api_json(runner, repo, f"repos/{repo}/pulls/{pr}")
        if _branch_tip(runner, repo, release) == sha and isinstance(view, dict) and view.get("merged") is True:
            print(f"promoted pr={pr} sha={sha}")
            return GREEN
        if clock() >= deadline:
            print(f"timed out after {timeout}s waiting for {release} to show {sha} and pull request {pr} to be merged", file=sys.stderr)
            return INDETERMINATE
        sleep(interval)


def _rounds(value: str) -> int:
    """An argparse ``type`` for ``--max-rounds``: an integer of at least 1."""
    rounds = int(value)
    if rounds < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, got {rounds}")
    return rounds


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pr_land.py", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    watch = commands.add_parser("watch", help="wait on one exact SHA's required checks")
    watch.add_argument("sha")
    watch.add_argument("--branch", default=None, help="base branch whose protection lists the required checks")
    watch.add_argument("--require", action="append", default=[], metavar="NAME", help="extra required check (repeatable)")
    watch.add_argument("--timeout", type=float, default=2700)
    watch.add_argument("--interval", type=float, default=15)
    land = commands.add_parser("land", help="refresh, gate, watch and merge a PR at its tested head")
    land.add_argument("pr", type=int)
    land.add_argument("--method", choices=["merge", "squash", "rebase"], required=True)
    land.add_argument("--gate", required=True, metavar="CMD", help="gate run in the refreshed tree")
    land.add_argument("--gate-evidence", default=None, metavar="REGEX", help="must match the gate's output")
    land.add_argument("--require", action="append", default=[], metavar="NAME", help="extra required check (repeatable)")
    land.add_argument("--accept-delta-change", action="store_true")
    land.add_argument("--max-rounds", type=_rounds, default=3)
    land.add_argument("--trunk", default="dev")
    land.add_argument("--release", default="main")
    land.add_argument("--timeout", type=float, default=2700)
    land.add_argument("--interval", type=float, default=15)
    promote = commands.add_parser("promote", help="fast-forward the release branch to a promotion PR's tested head")
    promote.add_argument("pr", type=int)
    promote.add_argument("--trunk", default="dev")
    promote.add_argument("--release", default="main")
    promote.add_argument("--timeout", type=float, default=2700)
    promote.add_argument("--interval", type=float, default=15)
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
    if args.command == "land":
        return land_pr(
            runner,
            repo,
            args.pr,
            method=args.method,
            gate=args.gate,
            gate_evidence=args.gate_evidence,
            require=args.require,
            accept_delta_change=args.accept_delta_change,
            max_rounds=args.max_rounds,
            trunk=args.trunk,
            release=args.release,
            timeout=args.timeout,
            interval=args.interval,
            clock=clock,
            sleep=sleep,
        )
    if args.command == "promote":
        return promote_pr(
            runner,
            repo,
            args.pr,
            trunk=args.trunk,
            release=args.release,
            timeout=args.timeout,
            interval=args.interval,
            clock=clock,
            sleep=sleep,
        )
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
