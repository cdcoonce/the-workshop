#!/usr/bin/env python3
"""Recommend a merge order for MRs/PRs racing into the same branch.

Read-only. Uses `git merge-tree` / `git commit-tree`, which write objects but
never move refs or touch the working tree. Nothing here checks out, rebases,
merges, or pushes.

The non-obvious property this exists to surface: two branches can each merge
into the target cleanly and still conflict with *each other*, so "does it
conflict with dev?" is the wrong question. We simulate "A merged first" and
re-test B.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path

MIN_GIT = (2, 38)  # merge-tree --write-tree


# --------------------------------------------------------------------------
# git helpers
# --------------------------------------------------------------------------


def run_git(repo: Path | str, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=check,
    )


def supports_write_tree(version_output: str) -> bool:
    """`git merge-tree --write-tree` needs git >= 2.38."""
    match = re.search(r"(\d+)\.(\d+)", version_output)
    if not match:
        return False
    return (int(match.group(1)), int(match.group(2))) >= MIN_GIT


def detect_platform(remote_url: str) -> str | None:
    if "gitlab.com" in remote_url or "gitlab." in remote_url:
        return "gitlab"
    if "github.com" in remote_url:
        return "github"
    return None


def ref_exists(repo: Path | str, ref: str) -> bool:
    return run_git(repo, "rev-parse", "--verify", "--quiet", ref, check=False).returncode == 0


def resolve_target(repo: Path | str, target: str) -> tuple[str, str | None]:
    """Resolve the target to the remote-tracking ref when one exists.

    A local branch is routinely stale (a checkout that has not pulled), and
    analysing against it silently fabricates conflicts that do not exist on the
    real target. Prefer `origin/<target>` and say so; never quietly use a base
    the user did not mean.
    """
    remote_ref = f"origin/{target}"
    if ref_exists(repo, remote_ref):
        note = None
        if ref_exists(repo, target):
            behind = run_git(
                repo, "rev-list", "--count", f"{target}..{remote_ref}", check=False
            ).stdout.strip()
            if behind.isdigit() and int(behind) > 0:
                note = (
                    f"local `{target}` is {behind} commit(s) behind `{remote_ref}`; "
                    f"analysed against `{remote_ref}`"
                )
        return remote_ref, note
    return target, f"no `{remote_ref}`; analysed against local `{target}`"


def merges_clean(repo: Path | str, base_ref: str, branch: str) -> bool:
    """True if `branch` merges into `base_ref` without conflict."""
    result = run_git(repo, "merge-tree", "--write-tree", base_ref, branch, check=False)
    return result.returncode == 0


def _simulate_merge(repo: Path | str, base_ref: str, branch: str) -> str | None:
    """Return a commit sha representing base_ref with `branch` merged in.

    Creates a dangling commit object; no ref is updated, so this is invisible
    to the working tree and garbage-collected in due course.
    """
    tree = run_git(repo, "merge-tree", "--write-tree", base_ref, branch, check=False)
    if tree.returncode != 0:
        return None
    tree_sha = tree.stdout.strip().splitlines()[0]
    commit = run_git(
        repo,
        "commit-tree",
        tree_sha,
        "-p",
        base_ref,
        "-m",
        f"simulated merge of {branch}",
        check=False,
    )
    if commit.returncode != 0:
        return None
    return commit.stdout.strip()


def _conflicted_files(repo: Path | str, base_ref: str, branch: str) -> list[str]:
    result = run_git(
        repo, "merge-tree", "--write-tree", "--name-only", base_ref, branch, check=False
    )
    if result.returncode == 0:
        return []
    lines = [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]
    # Output is: <tree-sha>, then the conflicted paths, then informational text.
    files = [
        ln
        for ln in lines[1:]
        if not ln.startswith(("Auto-merging", "CONFLICT", "warning:", "error:"))
        and not re.fullmatch(r"[0-9a-f]{40}", ln)
    ]
    return sorted(set(files))


def pairwise_conflicts(
    repo: Path | str, target: str, branches: list[str]
) -> dict[tuple[str, str], list[str]]:
    """For each pair, the files that conflict when one merges after the other.

    Keys are ordered tuples (sorted) so lookups are stable.
    """
    conflicts: dict[tuple[str, str], list[str]] = {}
    for a, b in combinations(sorted(branches), 2):
        simulated = _simulate_merge(repo, target, a)
        if simulated is None:
            # `a` cannot even merge into target; not a pairwise question.
            conflicts[(a, b)] = []
            continue
        conflicts[(a, b)] = _conflicted_files(repo, simulated, b)
    return conflicts


def contested_size(repo: Path | str, target: str, branch: str, path: str) -> int:
    """Added + deleted lines this branch makes to `path`, vs the merge base."""
    result = run_git(
        repo, "diff", "--numstat", f"{target}...{branch}", "--", path, check=False
    )
    total = 0
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            added, deleted = parts[0], parts[1]
            if added.isdigit():
                total += int(added)
            if deleted.isdigit():
                total += int(deleted)
    return total


# --------------------------------------------------------------------------
# merge requests
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class MergeRequest:
    ident: str
    source: str
    target: str
    draft: bool = False
    title: str = ""


def detect_chains(mrs: list[MergeRequest]) -> list[list[str]]:
    """Stacked MRs: one targeting another's source branch.

    Returns each chain as an ordered list of branch names, bottom first.
    """
    by_source = {mr.source: mr for mr in mrs}
    children: dict[str, str] = {}
    for mr in mrs:
        if mr.target in by_source:
            children[mr.target] = mr.source

    bottoms = [mr.source for mr in mrs if mr.target not in by_source and mr.source in children]
    chains: list[list[str]] = []
    for bottom in sorted(bottoms):
        chain = [bottom]
        node = bottom
        while node in children:
            node = children[node]
            if node in chain:  # defensive: never loop on a cycle
                break
            chain.append(node)
        if len(chain) > 1:
            chains.append(chain)
    return chains


def list_merge_requests(
    platform: str, target: str | None, repo: Path | str = "."
) -> list[MergeRequest]:
    """Query open MRs/PRs via glab or gh. Returns [] if the CLI is unavailable.

    `repo` matters: glab/gh resolve the project from the working directory, so
    running them from the caller's cwd silently reports a *different* repo's
    merge requests.
    """
    if platform == "gitlab":
        cmd = ["glab", "mr", "list", "--output", "json"]
    elif platform == "github":
        cmd = [
            "gh", "pr", "list", "--state", "open", "--json",
            "number,headRefName,baseRefName,isDraft,title",
        ]
    else:
        return []

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=False, cwd=str(repo)
        )
    except FileNotFoundError:
        return []
    if result.returncode != 0 or not result.stdout.strip():
        return []

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []

    mrs: list[MergeRequest] = []
    for item in payload:
        if platform == "gitlab":
            title = item.get("title", "") or ""
            mrs.append(
                MergeRequest(
                    ident=str(item.get("iid", item.get("id", "?"))),
                    source=item.get("source_branch", ""),
                    target=item.get("target_branch", ""),
                    draft=bool(item.get("draft")) or title.lower().startswith("draft:"),
                    title=title,
                )
            )
        else:
            mrs.append(
                MergeRequest(
                    ident=str(item.get("number", "?")),
                    source=item.get("headRefName", ""),
                    target=item.get("baseRefName", ""),
                    draft=bool(item.get("isDraft")),
                    title=item.get("title", "") or "",
                )
            )

    if target:
        chain_targets = {mr.source for mr in mrs}
        mrs = [mr for mr in mrs if mr.target == target or mr.target in chain_targets]
    return mrs


# --------------------------------------------------------------------------
# ordering
# --------------------------------------------------------------------------


@dataclass
class Order:
    sequence: list[str]
    rationale: list[str] = field(default_factory=list)
    any_order: bool = False
    contested: bool = False


def recommend_order(
    branches: list[str],
    conflicts: dict[tuple[str, str], list[str]],
    sizes: dict[tuple[str, str], int],
    drafts: set[str],
    chains: list[list[str]],
) -> Order:
    """Order branches so the cheapest total rebase effort follows.

    Rule: for a conflicting pair, the branch with the LARGER contested diff
    merges first — re-applying a small edit onto a settled file is cheaper
    than re-applying a large block onto a changed one. Ties break toward the
    non-draft (it can actually merge), then by name for determinism.
    """
    real_conflicts = {pair: files for pair, files in conflicts.items() if files}

    if not real_conflicts and not chains:
        return Order(sequence=sorted(branches), any_order=True,
                     rationale=["No pairwise conflicts — any merge order works."])

    # Hard dependencies from stacked chains.
    must_precede: set[tuple[str, str]] = set()
    for chain in chains:
        for earlier, later in zip(chain, chain[1:]):
            must_precede.add((earlier, later))

    rationale: list[str] = []
    contested = False

    for (a, b), files in sorted(real_conflicts.items()):
        if (a, b) in must_precede or (b, a) in must_precede:
            continue
        size_a = max((sizes.get((a, f), 0) for f in files), default=0)
        size_b = max((sizes.get((b, f), 0) for f in files), default=0)
        shown = ", ".join(files)
        if size_a > size_b:
            must_precede.add((a, b))
            rationale.append(
                f"{a} before {b}: {a} changes {shown} more ({size_a} vs {size_b} lines), "
                f"so {b} does the cheaper rebase."
            )
        elif size_b > size_a:
            must_precede.add((b, a))
            rationale.append(
                f"{b} before {a}: {b} changes {shown} more ({size_b} vs {size_a} lines), "
                f"so {a} does the cheaper rebase."
            )
        else:
            contested = True
            first, second = (b, a) if a in drafts and b not in drafts else (a, b)
            must_precede.add((first, second))
            rationale.append(
                f"{first} before {second}: equal contested size on {shown}; "
                f"broke the tie toward the non-draft. This order is arbitrary — "
                f"either sequence costs the same."
            )

    sequence = _toposort(sorted(branches), must_precede)
    for chain in chains:
        rationale.insert(0, f"Hard dependency (stacked): {' -> '.join(chain)}.")
    return Order(sequence=sequence, rationale=rationale, contested=contested)


def _toposort(nodes: list[str], edges: set[tuple[str, str]]) -> list[str]:
    """Stable topological sort; falls back to name order inside a cycle."""
    remaining = list(nodes)
    ordered: list[str] = []
    while remaining:
        free = [
            n for n in remaining
            if not any(b == n and a in remaining for a, b in edges)
        ]
        if not free:  # cycle — emit deterministically rather than fabricate
            ordered.extend(sorted(remaining))
            break
        pick = sorted(free)[0]
        ordered.append(pick)
        remaining.remove(pick)
    return ordered


# --------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------


def build_report(
    repo_slug: str,
    target: str,
    mrs: list[MergeRequest],
    conflicts: dict[tuple[str, str], list[str]],
    order: Order,
    note: str | None = None,
) -> str:
    by_branch = {mr.source: mr for mr in mrs}
    lines = [f"# Merge order — {repo_slug} (target: {target})", ""]
    if note:
        lines += [f"> **Base note:** {note}.", ""]

    lines.append(f"## Analysed ({len(mrs)} open)")
    lines.append("")
    if not mrs:
        lines.append("No open merge requests found.")
    for mr in sorted(mrs, key=lambda m: m.source):
        label = f"!{mr.ident} " if mr.ident != "?" else ""
        draft = " *(draft)*" if mr.draft else ""
        lines.append(f"- {label}`{mr.source}` → `{mr.target}`{draft}")
    lines.append("")

    lines.append("## Recommended order")
    lines.append("")
    if order.any_order:
        lines.append("No pairwise conflicts — **any order works**.")
    else:
        for i, branch in enumerate(order.sequence, 1):
            mr = by_branch.get(branch)
            label = f"!{mr.ident} " if mr and mr.ident != "?" else ""
            draft = " *(draft)*" if mr and mr.draft else ""
            lines.append(f"{i}. {label}`{branch}`{draft}")
    lines.append("")

    if order.rationale:
        lines.append("## Why")
        lines.append("")
        lines.extend(f"- {r}" for r in order.rationale)
        lines.append("")

    real = {p: f for p, f in conflicts.items() if f}
    lines.append("## Conflict matrix")
    lines.append("")
    if not real:
        lines.append("No pairwise conflicts detected.")
    else:
        lines.append("| A | B | Contested files |")
        lines.append("| --- | --- | --- |")
        for (a, b), files in sorted(real.items()):
            lines.append(f"| `{a}` | `{b}` | {', '.join(f'`{f}`' for f in files)} |")
    lines.append("")

    if order.contested:
        lines.append(
            "> At least one pair had an equal contested diff, so its order is "
            "arbitrary and was broken by draft status. Either sequence costs the same."
        )
        lines.append("")

    lines.append(
        "_Read-only analysis. No branch was checked out, rebased, merged, or pushed._"
    )
    return "\n".join(lines)


def output_path(repo_slug: str) -> Path:
    base = Path(os.environ.get("WORKSHOP_HOME", Path.home() / ".workshop"))
    return base / "mr-merge-order" / f"{repo_slug}.md"


# --------------------------------------------------------------------------
# cli
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".", help="Path to the git repo")
    parser.add_argument("--target", default=None, help="Target branch (default: detect)")
    parser.add_argument("--branches", nargs="*", help="Branches to analyse (skips MR lookup)")
    parser.add_argument("--no-write", action="store_true", help="Print only; do not persist")
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()

    version = run_git(repo, "--version", check=False).stdout
    if not supports_write_tree(version):
        print(
            f"error: needs git >= {MIN_GIT[0]}.{MIN_GIT[1]} for "
            f"`merge-tree --write-tree` (found: {version.strip()})",
            file=sys.stderr,
        )
        return 2

    remote = run_git(repo, "remote", "get-url", "origin", check=False).stdout.strip()
    platform = detect_platform(remote)
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", remote.split("/")[-1].removesuffix(".git")) or "repo"

    target = args.target or run_git(
        repo, "symbolic-ref", "--short", "refs/remotes/origin/HEAD", check=False
    ).stdout.strip().removeprefix("origin/") or "main"

    target_ref, target_note = resolve_target(repo, target)

    if args.branches:
        mrs = [MergeRequest(ident="?", source=b, target=target) for b in args.branches]
    else:
        mrs = list_merge_requests(platform or "", target, repo)
        if not mrs:
            print(
                "No open merge requests found (or no glab/gh available). "
                "Pass --branches to analyse branches directly.",
                file=sys.stderr,
            )
            return 1

    chains = detect_chains(mrs)
    chained = {b for chain in chains for b in chain}
    branches = [mr.source for mr in mrs]
    independent = [b for b in branches if b not in chained]

    conflicts = pairwise_conflicts(repo, target_ref, independent) if len(independent) > 1 else {}
    sizes: dict[tuple[str, str], int] = {}
    for (a, b), files in conflicts.items():
        for f in files:
            sizes.setdefault((a, f), contested_size(repo, target_ref, a, f))
            sizes.setdefault((b, f), contested_size(repo, target_ref, b, f))

    order = recommend_order(
        branches=branches,
        conflicts=conflicts,
        sizes=sizes,
        drafts={mr.source for mr in mrs if mr.draft},
        chains=chains,
    )

    report = build_report(slug, target_ref, mrs, conflicts, order, note=target_note)
    print(report)

    if not args.no_write:
        dest = output_path(slug)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(report + "\n")
        print(f"\nSaved to {dest}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
