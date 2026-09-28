"""Guard: warn on every rostered skill that has no calibrated checks yet.

For each rostered skill directory that exists and is inactive (per
``evals._harness.activation.is_active``), emits a ``warn``-level result
naming it as uncalibrated. Never emits ``fail`` — an inactive skill is an
expected, temporary state on the way to calibration, not a defect to block
a PR over.
"""

from __future__ import annotations

from evals._harness.activation import ROSTERED_SKILLS, is_active
from evals._harness.guards import GuardContext, Result

_GUARD_NAME = "uncalibrated"


def check(ctx: GuardContext) -> list[Result]:
    """Warn on every rostered skill directory that exists and is inactive.

    Parameters
    ----------
    ctx : GuardContext
        Only ``ctx.repo_root`` is used — this guard inspects state at HEAD,
        not a base-relative diff.

    Returns
    -------
    list[Result]
        One ``warn`` per inactive rostered skill directory present.
    """
    results: list[Result] = []
    for skill in ROSTERED_SKILLS:
        skill_dir = ctx.repo_root / "evals" / skill
        if not skill_dir.is_dir():
            continue
        if not is_active(skill_dir):
            results.append(
                Result(
                    level="warn",
                    guard=_GUARD_NAME,
                    message=f"{skill}: uncalibrated (no gated checks or retired entries yet)",
                )
            )
    return results
