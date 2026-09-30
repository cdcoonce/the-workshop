"""Guard: warn on a gated item that keeps needing multiple attempts.

For each gated item, looks at a skill's last 3 run files (by filename
timestamp; fewer than 3 existing is not an error). Reads that per-run
history with ``evals._harness.trend.history`` (owned by #993) rather than
re-deriving it from raw run-file JSON. Within a single run file, an item
"needed 2 or more attempts" if its ``first_hit_attempt`` is ``None`` (no hit
at all) or 2 or higher. If that holds for at least 2 of the last 3 run
files, warns. Never fails, and never forces recalibration.
"""

from __future__ import annotations

from evals._harness.activation import ROSTERED_SKILLS
from evals._harness.guards import GuardContext, Result
from evals._harness.trend import history

_GUARD_NAME = "flaky_item_warn"
_LOOKBACK = 3
_FLAKY_THRESHOLD = 2


def _needed_multiple_attempts(item: dict) -> bool:
    first_hit_attempt = item.get("first_hit_attempt")
    return first_hit_attempt is None or first_hit_attempt >= 2


def check(ctx: GuardContext) -> list[Result]:
    """Warn on a gated item flaky in at least 2 of its skill's last 3 runs.

    Parameters
    ----------
    ctx : GuardContext
        Only ``ctx.repo_root`` is used — this guard inspects run-file
        history at HEAD, not a base-relative diff.

    Returns
    -------
    list[Result]
        One ``warn`` per gated item that needed 2+ attempts in at least 2
        of its skill's last 3 run files.
    """
    results: list[Result] = []
    for skill in ROSTERED_SKILLS:
        runs_dir = ctx.repo_root / "evals" / skill / "runs"
        if not runs_dir.is_dir():
            continue

        recent = history(runs_dir)[-_LOOKBACK:]
        if not recent:
            continue

        item_ids: set[str] = set()
        for entry in recent:
            item_ids.update(entry["items"].keys())

        for item_id in sorted(item_ids):
            flaky_count = sum(
                1
                for entry in recent
                if item_id in entry["items"] and _needed_multiple_attempts(entry["items"][item_id])
            )
            if flaky_count >= _FLAKY_THRESHOLD:
                results.append(
                    Result(
                        level="warn",
                        guard=_GUARD_NAME,
                        message=(
                            f"{skill}: item {item_id!r} needed 2+ attempts in "
                            f"{flaky_count} of its last {len(recent)} runs"
                        ),
                    )
                )
    return results
