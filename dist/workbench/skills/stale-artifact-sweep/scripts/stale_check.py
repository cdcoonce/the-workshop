#!/usr/bin/env python3
"""Verify recorded artifacts against current git reality. Read-only.

A recorded claim about state — "this commit is pending", "this branch still
needs reviving", "this review finding blocks the merge" — is a *claim*, not a
fact. It was true when written. This script re-derives, from git, whether it is
still true, and reports the evidence that decided it.

Nothing here moves a ref, checks out, merges, or touches the working tree.
Patch checks run against a temporary index (``GIT_INDEX_FILE``), never the
repository's own index.

Issue/ticket state and CI results are deliberately NOT checked here: they need
network calls that unattended runs cannot approve. The skill procedure covers
them.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

STILL_VALID = "STILL_VALID"
ALREADY_DONE = "ALREADY_DONE"
SUPERSEDED = "SUPERSEDED"
NO_LONGER_REPRODUCES = "NO_LONGER_REPRODUCES"
UNVERIFIABLE = "UNVERIFIABLE"

EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


# --------------------------------------------------------------------------
# git helpers
# --------------------------------------------------------------------------


def run_git(
    repo: Path | str,
    *args: str,
    check: bool = False,
    stdin: str | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=check,
        input=stdin,
        env=env,
    )


def resolve(repo: Path | str, rev: str) -> str | None:
    """Full sha for a revision, or None when it does not resolve."""
    result = run_git(repo, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}")
    return result.stdout.strip() or None


def is_ancestor(repo: Path | str, maybe_ancestor: str, descendant: str) -> bool:
    return run_git(repo, "merge-base", "--is-ancestor", maybe_ancestor, descendant).returncode == 0


def cherry_equivalent(repo: Path | str, sha: str, target: str) -> bool:
    """True when an equivalent patch already exists on the target.

    ``git cherry`` prefixes a commit with ``-`` when the upstream already
    carries the same change under a different sha — a rebase, a cherry-pick, or
    the same edit committed twice.
    """
    parent = resolve(repo, f"{sha}^")
    if parent is None:
        return False
    result = run_git(repo, "cherry", target, sha, parent)
    return result.returncode == 0 and result.stdout.strip().startswith("-")


def commit_patch(repo: Path | str, sha: str) -> str:
    parent = resolve(repo, f"{sha}^") or EMPTY_TREE
    return run_git(repo, "diff", "--binary", parent, sha).stdout


def applies_to(
    repo: Path | str,
    patch: str,
    target: str,
    reverse: bool = False,
    context: int | None = None,
) -> bool:
    """Does `patch` apply to the target tree? Checked against a throwaway index.

    `context` trims how many context lines must match. The forward check runs at
    full context — it decides whether a commit is safe to land, so it must be
    strict. The reverse check asks the looser question "is this change's effect
    already here?", where surrounding lines are expected to have moved; a hunk
    anchored at line 1 will not shift under full context even when its added
    lines are plainly present.
    """
    if not patch.strip():
        return False
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(tmp) / "index")}
        if run_git(repo, "read-tree", target, env=env).returncode != 0:
            return False
        args = ["apply", "--cached", "--check"]
        if reverse:
            args.append("--reverse")
        if context is not None:
            args.append(f"-C{context}")
        return run_git(repo, *args, "-", stdin=patch, env=env).returncode == 0


def changed_files(repo: Path | str, sha: str) -> list[str]:
    out = run_git(repo, "show", "--pretty=format:", "--name-only", sha).stdout
    return [line for line in out.splitlines() if line.strip()]


def commits_touching(repo: Path | str, rev_range: str, paths: list[str]) -> list[str]:
    """`<short sha> <subject>` for each commit in the range touching `paths`."""
    args = ["log", "--format=%h %s", rev_range]
    if paths:
        args += ["--", *paths]
    out = run_git(repo, *args).stdout
    return [line for line in out.splitlines() if line.strip()]


# --------------------------------------------------------------------------
# results
# --------------------------------------------------------------------------


@dataclass
class Result:
    """One artifact's verdict, and the evidence that produced it."""

    kind: str
    artifact: str
    verdict: str
    evidence: list[str] = field(default_factory=list)
    commits: list[Result] = field(default_factory=list)


def _unverifiable(kind: str, artifact: str, why: str) -> Result:
    return Result(kind=kind, artifact=artifact, verdict=UNVERIFIABLE, evidence=[why])


# --------------------------------------------------------------------------
# checks
# --------------------------------------------------------------------------


def commit_status(repo: Path | str, rev: str, target: str) -> Result:
    """Is this commit already in the target, stale against it, or genuinely pending?"""
    sha = resolve(repo, rev)
    if sha is None:
        return _unverifiable("commit", rev, f"{rev!r} does not resolve to a commit in this repo")
    target_sha = resolve(repo, target)
    if target_sha is None:
        return _unverifiable("commit", rev, f"target {target!r} does not resolve to a commit")

    short = sha[:7]
    if is_ancestor(repo, sha, target_sha):
        return Result("commit", short, ALREADY_DONE, [f"{short} is an ancestor of {target}"])

    if cherry_equivalent(repo, sha, target_sha):
        return Result(
            "commit",
            short,
            ALREADY_DONE,
            [f"an equivalent patch is already on {target} (git cherry reports it upstream)"],
        )

    patch = commit_patch(repo, sha)
    if not patch.strip():
        return _unverifiable("commit", short, f"{short} has an empty diff; nothing to compare")

    if applies_to(repo, patch, target_sha, reverse=True, context=1):
        return Result(
            "commit",
            short,
            ALREADY_DONE,
            [f"its effect is already present in {target} (the diff reverse-applies cleanly)"],
        )

    if applies_to(repo, patch, target_sha):
        return Result(
            "commit",
            short,
            STILL_VALID,
            [f"applies cleanly to {target} and is not present there"],
        )

    files = changed_files(repo, sha)
    base = run_git(repo, "merge-base", sha, target_sha).stdout.strip() or target_sha
    movers = commits_touching(repo, f"{base}..{target_sha}", files)
    evidence = [f"does not apply to {target}: the target moved under it"]
    evidence.append("files it edits: " + ", ".join(files) if files else "no files recorded")
    evidence += [f"changed on {target} since the base by {line}" for line in movers[:5]]
    return Result("commit", short, SUPERSEDED, evidence)


def branch_status(repo: Path | str, branch: str, target: str) -> Result:
    """Per-commit containment for a branch — is reviving it worth anything?"""
    head = resolve(repo, branch)
    if head is None:
        return _unverifiable("branch", branch, f"branch {branch!r} does not resolve to a commit")
    target_sha = resolve(repo, target)
    if target_sha is None:
        return _unverifiable("branch", branch, f"target {target!r} does not resolve to a commit")

    revs = run_git(repo, "rev-list", "--reverse", f"{target_sha}..{head}").stdout.split()
    if not revs:
        return Result(
            "branch",
            branch,
            ALREADY_DONE,
            [f"every commit on {branch} is already contained in {target}"],
        )

    commits = [commit_status(repo, rev, target) for rev in revs]
    contained = [c for c in commits if c.verdict == ALREADY_DONE]
    pending = [c for c in commits if c.verdict != ALREADY_DONE]

    evidence = [f"{len(contained)} of {len(commits)} commits are already in {target}"]
    if contained:
        evidence.append("drop: " + ", ".join(c.artifact for c in contained))
    if pending:
        evidence.append("genuinely additive: " + ", ".join(c.artifact for c in pending))

    verdict = ALREADY_DONE if not pending else STILL_VALID
    return Result("branch", branch, verdict, evidence, commits=commits)


def finding_status(
    repo: Path | str, reviewed_rev: str, target: str, files: list[str]
) -> Result:
    """Could the fix for a review finding have landed since the review was written?

    This never claims a finding is fixed — only git can say whether the ground
    it stands on moved. A moved file makes the finding UNVERIFIABLE until the
    original check is re-run against the current head.
    """
    reviewed = resolve(repo, reviewed_rev)
    if reviewed is None:
        return _unverifiable(
            "finding", reviewed_rev, f"{reviewed_rev!r} does not resolve to a commit"
        )
    target_sha = resolve(repo, target)
    if target_sha is None:
        return _unverifiable("finding", reviewed_rev, f"target {target!r} does not resolve")

    short = reviewed[:7]
    if not is_ancestor(repo, reviewed, target_sha):
        return _unverifiable(
            "finding",
            short,
            f"the reviewed commit {short} is not in {target}'s history — "
            f"the review may cite a rebased or force-pushed branch; re-run the check",
        )

    movers = commits_touching(repo, f"{reviewed}..{target_sha}", files)
    scope = ", ".join(files) if files else "the whole tree"
    if not movers:
        return Result(
            "finding",
            short,
            STILL_VALID,
            [f"{scope} is untouched on {target} since {short}; the finding still stands"],
        )

    evidence = [f"{len(movers)} commit(s) changed {scope} on {target} since {short}:"]
    evidence += [f"  {line}" for line in movers[:5]]
    evidence.append(
        "re-run the original check against the current head before trusting this finding — "
        f"only a passing re-run justifies {NO_LONGER_REPRODUCES}"
    )
    return Result("finding", short, UNVERIFIABLE, evidence)


# --------------------------------------------------------------------------
# reporting
# --------------------------------------------------------------------------


def format_report(results: list[Result]) -> str:
    lines = ["# Stale artifact sweep", "", "Read-only: nothing was checked out, merged, or moved.", ""]
    for result in results:
        lines.append(f"## {result.kind} {result.artifact} — {result.verdict}")
        lines += [f"- {line}" for line in result.evidence]
        for commit in result.commits:
            lines.append(f"  - {commit.artifact}: {commit.verdict}")
            lines += [f"    - {line}" for line in commit.evidence]
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify recorded artifacts against git reality.")
    parser.add_argument("--repo", default=".", help="repository to inspect")
    parser.add_argument("--target", default="dev", help="branch the artifact claims to be pending against")
    sub = parser.add_subparsers(dest="kind", required=True)

    commit_parser = sub.add_parser("commit", help="is this commit already in the target?")
    commit_parser.add_argument("rev", nargs="+")

    branch_parser = sub.add_parser("branch", help="is reviving this branch worth anything?")
    branch_parser.add_argument("name", nargs="+")

    finding_parser = sub.add_parser("finding", help="has the ground under a review finding moved?")
    finding_parser.add_argument("rev", help="the commit the review cites")
    finding_parser.add_argument("--file", action="append", default=[], dest="files")

    args = parser.parse_args(argv)
    repo = Path(args.repo)

    if args.kind == "commit":
        results = [commit_status(repo, rev, args.target) for rev in args.rev]
    elif args.kind == "branch":
        results = [branch_status(repo, name, args.target) for name in args.name]
    else:
        results = [finding_status(repo, args.rev, args.target, args.files)]

    print(format_report(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
