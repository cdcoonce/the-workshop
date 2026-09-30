"""Guard: a direct-tier change co-occurring with a gated-ID removal reads as a demotion.

Diffs ``$(VERSION_BASE)...HEAD`` (``ctx.base`` against ``HEAD``). For every
rostered skill with a ``deps`` file, fails if the skill's direct-tier hash
(via ``evals._harness.deps.tree_hash``, owned by #993) changed between base
and head AND the set of gated IDs in ``checks.manifest`` at head is not a
superset of the set at base — any gated ID present at base but missing at
head. The manifest's ``<id> <description>`` format carries no separate
status field, so a removed ID co-occurring with a direct-tier change is the
only mechanically checkable reading of "demoted" available here.

Unconditional: no activation precondition at all, and it fires independent
of whether the skill is active at base, at head, or ever.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from evals._harness.activation import ROSTERED_SKILLS, parse_checks_manifest
from evals._harness.deps import parse_deps, tree_hash
from evals._harness.guards import GuardContext, Result

_GUARD_NAME = "demote_gated_id"


def _read_at_head(repo_root: Path, rel_path: str) -> str:
    path = repo_root / rel_path
    return path.read_text(encoding="utf-8") if path.exists() else ""


def check(ctx: GuardContext) -> list[Result]:
    """Fail a direct-tier change co-occurring with a gated-ID removal.

    Parameters
    ----------
    ctx : GuardContext
        ``ctx.base`` is the PR's base ref; ``ctx.repo_root`` is the work
        tree to diff against it, checked out at HEAD.

    Returns
    -------
    list[Result]
        One ``fail`` per rostered skill whose direct-tier hash changed
        between base and head while a gated ID was removed from its
        manifest in the same diff.
    """
    results: list[Result] = []
    for skill in ROSTERED_SKILLS:
        eval_dir = ctx.repo_root / "evals" / skill
        deps_path = eval_dir / "deps"
        if not deps_path.exists():
            continue

        direct_paths = parse_deps(deps_path.read_text(encoding="utf-8"))["direct"]
        head_hash = tree_hash(direct_paths, ref="HEAD", repo=ctx.repo_root)
        base_hash = tree_hash(direct_paths, ref=ctx.base, repo=ctx.repo_root)
        if head_hash == base_hash:
            continue

        manifest_rel = f"evals/{skill}/checks.manifest"
        base_result = subprocess.run(
            ["git", "-C", str(ctx.repo_root), "show", f"{ctx.base}:{manifest_rel}"],
            capture_output=True,
            text=True,
            check=False,
        )
        base_manifest_text = base_result.stdout if base_result.returncode == 0 else ""
        base_ids = set(parse_checks_manifest(base_manifest_text))
        head_ids = set(parse_checks_manifest(_read_at_head(ctx.repo_root, manifest_rel)))

        if base_ids - head_ids:
            results.append(
                Result(
                    level="fail",
                    guard=_GUARD_NAME,
                    message=(
                        f"{skill}: direct tier changed while a gated id was "
                        "removed from checks.manifest — looks like a demotion"
                    ),
                )
            )
    return results
