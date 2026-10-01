"""Guard: the floor — an active rostered skill must have at least one gated ID.

For each rostered skill directory that exists and is active (per
``evals._harness.activation.is_active``), fails if its ``checks.manifest``
lists zero gated IDs. A skill can only be active with an empty manifest via
its ``retired.md`` holding at least one entry — an inactive skill with an
empty manifest is the expected starting state and is never evaluated here.

Checks state at HEAD, not a base-relative diff: ``ctx.base`` is unused.
"""

from __future__ import annotations

from evals._harness.activation import ROSTERED_SKILLS, is_active, parse_checks_manifest
from evals._harness.guards import GuardContext, Result

_GUARD_NAME = "empty_gated_set"


def check(ctx: GuardContext) -> list[Result]:
    """Fail an active rostered skill whose ``checks.manifest`` has zero gated IDs.

    Parameters
    ----------
    ctx : GuardContext
        Only ``ctx.repo_root`` is used — this guard inspects state at HEAD,
        not a base-relative diff.

    Returns
    -------
    list[Result]
        One ``fail`` per active rostered skill directory whose manifest
        lists zero gated IDs.
    """
    results: list[Result] = []
    for skill in ROSTERED_SKILLS:
        skill_dir = ctx.repo_root / "evals" / skill
        if not skill_dir.is_dir():
            continue
        if not is_active(skill_dir):
            continue

        manifest_path = skill_dir / "checks.manifest"
        manifest_text = manifest_path.read_text(encoding="utf-8") if manifest_path.exists() else ""
        if not parse_checks_manifest(manifest_text):
            results.append(
                Result(
                    level="fail",
                    guard=_GUARD_NAME,
                    message=f"{skill}: active with zero gated IDs in checks.manifest",
                )
            )
    return results
