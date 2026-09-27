"""Guard: an active rostered skill's direct tier cannot change without a fresh green run.

For each rostered skill that is active (per ``evals._harness.activation``),
diffs ``$(VERSION_BASE)...HEAD`` (the ``ctx.base`` value the guard runner
receives, against ``HEAD``) and fails if that diff touches any path in the
skill's direct tier (from its ``deps`` file — parsed and expanded via
``evals._harness.deps``, owned by #993), unless the diff also adds a green
run file for that skill (under ``evals/<skill>/runs/``) whose recorded
direct-tier hash matches the tier's hash at HEAD. A red or void run file
never satisfies this — only a matching green one does.

An inactive rostered skill is never evaluated: this guard does not fire for
it at all, regardless of what its direct tier's diff contains.
"""

from __future__ import annotations

import json
import posixpath
import subprocess
from pathlib import Path

from evals._harness.activation import ROSTERED_SKILLS, is_active
from evals._harness.deps import expand_paths, parse_deps, tree_hash
from evals._harness.guards import GuardContext, Result

_GUARD_NAME = "direct_tier"


def _run_git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _changed_paths(repo_root: Path, base: str) -> set[str]:
    # --no-renames: a plain `git diff --name-only` auto-detects renames and
    # prints only the new path, so a direct-tier file renamed OUT of the tier
    # (its new path is not a tier member) would otherwise vanish from the
    # diff entirely — the base-side union below exists to catch deletions,
    # but a rename is never a deletion under rename detection.
    output = _run_git(repo_root, "diff", "--no-renames", "--name-only", f"{base}...HEAD")
    return {line for line in output.splitlines() if line}


def _added_paths(repo_root: Path, base: str) -> set[str]:
    # --no-renames: keeps a renamed-and-modified file from reading as a plain
    # "A" (added) status pair with the rest of this module's diff calls.
    output = _run_git(repo_root, "diff", "--no-renames", "--name-status", f"{base}...HEAD")
    added: set[str] = set()
    for line in output.splitlines():
        if not line:
            continue
        parts = line.split("\t")
        status, path = parts[0], parts[-1]
        if status.startswith("A"):
            added.add(path)
    return added


def _has_matching_green_run(
    repo_root: Path, skill: str, base: str, expected_hash: str
) -> bool:
    # Only a file DIRECTLY in evals/<skill>/runs/ is a run file — anything
    # deeper (an attempt's raw output under runs/<stem>/...) is a raw, never
    # a run file, and a run file only counts for THIS skill, never another
    # rostered skill's runs/ directory.
    runs_dir = f"evals/{skill}/runs"
    for added_path in _added_paths(repo_root, base):
        if posixpath.dirname(added_path) != runs_dir:
            continue
        if not added_path.endswith(".json"):
            continue
        run_path = repo_root / added_path
        try:
            run = json.loads(run_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if run.get("verdict") != "green":
            continue
        if run.get("fingerprint", {}).get("direct_tier_hash") == expected_hash:
            return True
    return False


def check(ctx: GuardContext) -> list[Result]:
    """Fail an active rostered skill's direct-tier change with no matching green run.

    Parameters
    ----------
    ctx : GuardContext
        ``ctx.base`` is the PR's base ref; ``ctx.repo_root`` is the work
        tree to diff against it, checked out at HEAD.

    Returns
    -------
    list[Result]
        One ``fail`` per active rostered skill whose direct tier changed in
        the diff without a matching green run file also added by it.
    """
    results: list[Result] = []
    changed = _changed_paths(ctx.repo_root, ctx.base)

    for skill in ROSTERED_SKILLS:
        eval_dir = ctx.repo_root / "evals" / skill
        deps_path = eval_dir / "deps"
        if not deps_path.exists():
            continue
        if not is_active(eval_dir):
            continue

        direct_paths = parse_deps(deps_path.read_text(encoding="utf-8"))["direct"]
        tier_files = set(
            expand_paths(direct_paths, ref="HEAD", repo=ctx.repo_root)
        ) | set(expand_paths(direct_paths, ref=ctx.base, repo=ctx.repo_root))

        if not (tier_files & changed):
            continue

        expected_hash = tree_hash(direct_paths, ref="HEAD", repo=ctx.repo_root)
        if _has_matching_green_run(ctx.repo_root, skill, ctx.base, expected_hash):
            continue

        results.append(
            Result(
                level="fail",
                guard=_GUARD_NAME,
                message=(
                    f"{skill}: direct tier changed without a matching green run "
                    f"file under evals/{skill}/runs/"
                ),
            )
        )
    return results
