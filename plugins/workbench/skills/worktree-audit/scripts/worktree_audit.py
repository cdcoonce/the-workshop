#!/usr/bin/env python3
"""Audit git worktrees across repos and classify each one with evidence.

Long-lived repos accumulate worktrees: agent sessions, dispatched slices, and
one-off checkouts that nothing ever cleans up. The question a sweep has to answer
is **"did this worktree author anything?"** — not "is its branch merged?"

Those come apart constantly. ``git worktree add -B <branch> <path> HEAD`` cuts the
branch from whatever the launch checkout is on, so a worktree created while the
repo sits on a feature branch is ahead of the trunk through no fault of its own,
and stays that way until an unrelated branch merges — possibly never. A sweep
gated on "merged" preserves those forever; one gated on "authored" clears them
while still refusing to touch real work.

Read-only unless ``--reap`` is passed. Nothing here rewrites history, pushes, or
touches a working tree's contents.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MIN_AGE_HOURS = 24.0


@dataclass(frozen=True)
class Worktree:
    """One linked worktree. ``name`` is the directory basename."""

    path: Path
    branch: str

    @property
    def name(self) -> str:
        return self.path.name


@dataclass(frozen=True)
class Verdict:
    """What to do about one worktree or orphan branch, and why."""

    name: str
    action: str  # "reap" | "keep" | "recent"
    reason: str
    path: Path | None = None
    branch: str | None = None


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def list_worktrees(repo: Path) -> list[Worktree]:
    """Every LINKED worktree of *repo*, excluding the main checkout.

    The main checkout is the first record ``git worktree list --porcelain`` emits
    and is never a candidate — reaping the directory you launched from is a
    different kind of accident entirely.
    """
    out = _git(repo, "worktree", "list", "--porcelain")
    records, current = [], {}
    for line in out.splitlines():
        if not line.strip():
            if current:
                records.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        current[key] = value
    if current:
        records.append(current)

    worktrees = []
    for record in records[1:]:  # [0] is the main checkout
        branch = record.get("branch", "")
        if branch.startswith("refs/heads/"):
            branch = branch[len("refs/heads/") :]
        worktrees.append(Worktree(path=Path(record["worktree"]), branch=branch))
    return worktrees


def authored_commits(repo: Path, branch: str, exclude: list[str]) -> int:
    """Commits on *branch* reachable from no other ref — this session's own work.

    Two flags carry the whole safety property, and both are easy to omit:

    ``--single-worktree`` — since git 2.7 ``--all`` also expands every OTHER
    worktree's HEAD. A branch checked out in its own worktree is therefore always
    reachable from itself, every count comes back 0, and a reaper built on this
    deletes committed work. Measured on a scratch repo: an authored commit counts
    0 without the flag and 1 with it.

    ``--exclude`` for each sibling under audit — a worktree cut from ANOTHER
    session's tip contains that session's commits without having written them, so
    without the exclusion the branch that did the work reads as empty and is the
    one reaped. Note the trade honestly: the exclusion also makes the inheriting
    sibling look like an author, so it is kept when it need not be. A false keep
    in exchange for a false reap is the right direction for a destructive
    operation. (Divergent siblings cut from a common base never mask each other,
    so this rule is narrower than it first appears.)

    *branch* is always excluded, not merely when the caller remembers to pass it.
    A branch still checked out is masked by ``--single-worktree``, but one whose
    worktree is already gone is an ordinary ref inside ``--all`` and vouches for
    its own commits — so an orphaned branch holding the only copy of its work
    read as empty and was reaped. Self-exclusion belongs here, where it cannot be
    forgotten at a call site.

    Any error reports 1 (i.e. "it authored something"), so the caller preserves.
    Never guess-reap.
    """
    excluded = dict.fromkeys([branch, *exclude])  # ordered, de-duplicated
    args = ["rev-list", "--count", branch, "--not", "--single-worktree"]
    args += [f"--exclude=refs/heads/{name}" for name in excluded]
    args.append("--all")
    try:
        return int(_git(repo, *args) or "0")
    except (subprocess.CalledProcessError, ValueError, OSError):
        return 1


def is_dirty(worktree: Path) -> bool:
    """True when the tree has uncommitted changes, or when we cannot tell."""
    try:
        return bool(_git(worktree, "status", "--porcelain"))
    except (subprocess.CalledProcessError, OSError):
        return True


def _age_hours(path: Path, now: float) -> float:
    try:
        return (now - path.stat().st_mtime) / 3600
    except OSError:
        return 0.0


def audit_repo(
    repo: Path,
    *,
    branch_prefix: str | None = None,
    min_age_hours: float = DEFAULT_MIN_AGE_HOURS,
    all_ages: bool = False,
    now: float | None = None,
) -> list[Verdict]:
    """Classify every linked worktree of *repo*. Read-only.

    ``branch_prefix`` scopes what may be REAPED. Without it everything is
    classified and nothing is reapable, because "clean and authored nothing" is
    not on its own grounds to delete: that is precisely what a long-lived
    infrastructure worktree looks like between merges. A live fleet run found
    afk's persistent integration worktree (``staging-wt``) marked reapable in four
    repos while a green test suite said the predicate was correct — the suite only
    ever saw session worktrees, because those were the only ones it created.

    ``all_ages`` is the escape hatch for "sweep everything now", and it exists so
    nobody reaches for a faked clock instead: passing ``now=0`` to an age check
    makes every delta negative, which reads as *everything is fresh* and silently
    reaps nothing.
    """
    now = time.time() if now is None else now
    worktrees = list_worktrees(repo)
    family = [w.branch for w in worktrees if w.branch]

    verdicts = []
    for wt in worktrees:
        if is_dirty(wt.path):
            verdicts.append(
                Verdict(wt.name, "keep", "uncommitted changes", wt.path, wt.branch)
            )
            continue
        if not wt.branch:
            verdicts.append(
                Verdict(wt.name, "keep", "detached HEAD — cannot attribute work", wt.path)
            )
            continue
        authored = authored_commits(repo, wt.branch, exclude=family)
        if authored:
            verdicts.append(
                Verdict(
                    wt.name,
                    "keep",
                    f"authored {authored} commit(s) reachable from no other ref",
                    wt.path,
                    wt.branch,
                )
            )
            continue
        if not branch_prefix or not wt.branch.startswith(branch_prefix):
            verdicts.append(
                Verdict(
                    wt.name,
                    "unscoped",
                    "clean and empty, but outside the reapable scope — "
                    "pass --branch-prefix to include it",
                    wt.path,
                    wt.branch,
                )
            )
            continue
        age = _age_hours(wt.path, now)
        if not all_ages and age < min_age_hours:
            verdicts.append(
                Verdict(
                    wt.name,
                    "recent",
                    f"clean and empty, but touched {age:.1f}h ago — may be live",
                    wt.path,
                    wt.branch,
                )
            )
            continue
        verdicts.append(
            Verdict(wt.name, "reap", "clean and authored nothing", wt.path, wt.branch)
        )
    return verdicts


def orphan_branch_verdicts(repo: Path, prefix: str) -> list[Verdict]:
    """Branches under *prefix* whose worktree is already gone.

    A worktree removed by any route other than the sweep (a manual
    ``git worktree remove``, a wiped scratch dir) leaves its branch behind
    forever, because branch deletion normally rides along with directory removal.

    Opt-in via an explicit prefix: "delete every local branch that authored
    nothing" is far too broad a hammer to point at a repo by default.
    """
    live = {w.branch for w in list_worktrees(repo)}
    try:
        listing = _git(repo, "branch", "--list", f"{prefix}*", "--format=%(refname:short)")
    except (subprocess.CalledProcessError, OSError):
        return []

    verdicts = []
    for branch in (b.strip() for b in listing.splitlines() if b.strip()):
        if branch in live:
            continue  # the worktree sweep owns it
        if authored_commits(repo, branch, exclude=list(live)):
            verdicts.append(
                Verdict(branch, "keep", "orphaned but holds the only copy of its work", branch=branch)
            )
        else:
            verdicts.append(
                Verdict(branch, "reap", "orphaned branch, authored nothing", branch=branch)
            )
    return verdicts


def reap(repo: Path, verdicts: list[Verdict]) -> list[str]:
    """Remove every ``reap`` verdict. Returns the names actually removed.

    A failure is skipped rather than raised: git refuses to delete a branch that
    is checked out in a worktree, which is a real guard rather than an error to
    work around.
    """
    removed = []
    for v in verdicts:
        if v.action != "reap":
            continue
        try:
            if v.path is not None:
                _git(repo, "worktree", "remove", "--force", str(v.path))
            if v.branch:
                _git(repo, "branch", "-D", v.branch)
        except (subprocess.CalledProcessError, OSError):
            continue
        removed.append(v.name)
    return removed


def find_repos(root: Path) -> list[Path]:
    """Immediate subdirectories of *root* that are git repos with linked worktrees."""
    repos = []
    for child in sorted(p for p in root.iterdir() if p.is_dir()):
        if not (child / ".git").exists():
            continue
        try:
            if len(list_worktrees(child)) or (child / ".git").is_dir():
                repos.append(child)
        except (subprocess.CalledProcessError, OSError):
            continue
    return repos


def _render(repo: Path, verdicts: list[Verdict]) -> str:
    actions = ("reap", "keep", "recent", "unscoped")
    counts = {a: sum(1 for v in verdicts if v.action == a) for a in actions}
    lines = [
        f"\n{repo}  —  {counts['reap']} reapable · {counts['keep']} keep · "
        f"{counts['recent']} recent · {counts['unscoped']} unscoped"
    ]
    for v in verdicts:
        mark = {"reap": "✗", "keep": "✓", "recent": "·", "unscoped": "?"}[v.action]
        lines.append(f"  {mark} {v.name} — {v.reason}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, help="sweep every repo under this directory")
    parser.add_argument("--repo", type=Path, help="audit a single repo")
    parser.add_argument(
        "--branch-prefix",
        help="branch prefix that marks a session worktree (e.g. 'session/'). "
        "Scopes what may be reaped, and enables the orphan-branch scan. "
        "Without it nothing is reapable — see audit_repo's docstring for why.",
    )
    parser.add_argument("--min-age-hours", type=float, default=DEFAULT_MIN_AGE_HOURS)
    parser.add_argument("--all-ages", action="store_true", help="ignore the age guard")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--reap", action="store_true", help="remove the reapable entries")
    args = parser.parse_args(argv)

    if args.repo:
        repos = [args.repo]
    elif args.root:
        repos = find_repos(args.root)
    else:
        repos = [Path.cwd()]

    payload, exit_code = {}, 0
    for repo in repos:
        try:
            verdicts = audit_repo(
                repo,
                branch_prefix=args.branch_prefix,
                min_age_hours=args.min_age_hours,
                all_ages=args.all_ages,
            )
            if args.branch_prefix:
                verdicts += orphan_branch_verdicts(repo, args.branch_prefix)
        except (subprocess.CalledProcessError, OSError) as exc:
            print(f"{repo}: skipped ({exc})", file=sys.stderr)
            exit_code = 1
            continue
        if not verdicts:
            continue
        removed = reap(repo, verdicts) if args.reap else []
        if args.json:
            payload[str(repo)] = {
                "verdicts": [vars(v) | {"path": str(v.path) if v.path else None} for v in verdicts],
                "removed": removed,
            }
        else:
            print(_render(repo, verdicts))
            if args.reap:
                print(f"  reaped {len(removed)}")

    if args.json:
        print(json.dumps(payload, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
