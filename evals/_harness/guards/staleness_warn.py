"""Guard: warn when an active skill's newest green run is more than 30 days old.

For each active rostered skill (per ``evals._harness.activation.is_active``),
finds the newest green run file — the latest by filename timestamp among
its run files whose ``verdict`` is ``green`` — and warns if that run's
``fingerprint.run_date`` is more than 30 days before today. A newer red or
void run file never suppresses the warning: it is the newest GREEN run's
age that matters. Never fails, and skips inactive skills entirely.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from evals._harness.activation import ROSTERED_SKILLS, is_active
from evals._harness.guards import GuardContext, Result

_GUARD_NAME = "staleness_warn"
_STALE_AFTER_DAYS = 30


def _load_runs(runs_dir: Path) -> list[dict]:
    return [
        json.loads(run_file.read_text(encoding="utf-8"))
        for run_file in sorted(runs_dir.glob("*.json"))
    ]


def check(ctx: GuardContext) -> list[Result]:
    """Warn on an active rostered skill whose newest green run is stale.

    Parameters
    ----------
    ctx : GuardContext
        Only ``ctx.repo_root`` is used — this guard inspects state at HEAD,
        not a base-relative diff.

    Returns
    -------
    list[Result]
        One ``warn`` per active rostered skill whose newest green run file
        is more than 30 days old.
    """
    results: list[Result] = []
    for skill in ROSTERED_SKILLS:
        skill_dir = ctx.repo_root / "evals" / skill
        if not skill_dir.is_dir() or not is_active(skill_dir):
            continue

        runs_dir = skill_dir / "runs"
        if not runs_dir.is_dir():
            continue

        green_runs = [run for run in _load_runs(runs_dir) if run.get("verdict") == "green"]
        if not green_runs:
            continue

        newest_green = green_runs[-1]
        run_date_str = newest_green.get("fingerprint", {}).get("run_date")
        if not run_date_str:
            continue

        run_date = datetime.strptime(run_date_str, "%Y-%m-%d").date()
        age_days = (date.today() - run_date).days
        if age_days > _STALE_AFTER_DAYS:
            results.append(
                Result(
                    level="warn",
                    guard=_GUARD_NAME,
                    message=(
                        f"{skill}: newest green run is {age_days} days old "
                        f"(run_date={run_date_str})"
                    ),
                )
            )
    return results
