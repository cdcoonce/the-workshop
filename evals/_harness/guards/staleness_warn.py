"""Guard: warn when an active skill's newest green run is more than 30 days old.

For each active rostered skill (per ``evals._harness.activation.is_active``),
finds the newest green run file — the latest by filename timestamp among
its run files whose ``verdict`` is ``green`` — and warns if that run's
``fingerprint.run_date`` is more than 30 days before today. A newer red or
void run file never suppresses the warning: it is the newest GREEN run's
age that matters. Never fails, and skips inactive skills entirely. A
schema-valid but calendar-invalid ``run_date`` (``2026-02-30``) warns naming
the run file instead of crashing.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from evals._harness.activation import ROSTERED_SKILLS, is_active
from evals._harness.guards import GuardContext, Result

_GUARD_NAME = "staleness_warn"
_STALE_AFTER_DAYS = 30


def _load_runs(runs_dir: Path) -> list[tuple[Path, dict]]:
    return [
        (run_file, json.loads(run_file.read_text(encoding="utf-8")))
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

        green_runs = [
            (run_file, run)
            for run_file, run in _load_runs(runs_dir)
            if run.get("verdict") == "green"
        ]
        if not green_runs:
            continue

        newest_green_file, newest_green = green_runs[-1]
        run_date_str = newest_green.get("fingerprint", {}).get("run_date")
        if not run_date_str:
            continue

        try:
            run_date = datetime.strptime(run_date_str, "%Y-%m-%d").date()
        except ValueError:
            # The run-file schema only checks the \d{4}-\d{2}-\d{2} shape, so
            # a value like 2026-02-30 is schema-valid but not a date. This
            # guard never fails and must not crash: surface it as a warn
            # (staleness cannot be judged) rather than skip it silently.
            results.append(
                Result(
                    level="warn",
                    guard=_GUARD_NAME,
                    message=(
                        f"{skill}: cannot judge staleness; {newest_green_file.name} "
                        f"has a run_date that is not a real calendar date "
                        f"(run_date={run_date_str})"
                    ),
                )
            )
            continue
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
