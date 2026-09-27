"""Trend aggregation over a skill's committed run files.

Reads only ``evals/<skill>/runs/*.json`` run files — never a raw or a
report — and never mutates them.
"""

from __future__ import annotations

import json
from pathlib import Path


def _load_runs(runs_dir: Path) -> list[dict]:
    return [
        json.loads(run_file.read_text(encoding="utf-8"))
        for run_file in sorted(runs_dir.glob("*.json"))
    ]


def _attempts_needed(attempts: list[dict], item_id: str) -> int:
    """Return the attempts needed to reach *item_id*'s first hit.

    The retry loop keeps running after an item hits because other items in
    the same case may still be missing, so simply counting every attempt
    that recorded an outcome for the item overstates how many it needed.
    This returns the 1-based attempt index of the item's first hit, or the
    number of attempts that recorded it if it never hit.
    """
    recorded = [attempt["attempt"] for attempt in attempts if item_id in attempt["items"]]
    hit_attempts = [
        attempt["attempt"] for attempt in attempts if attempt["items"].get(item_id) == "hit"
    ]
    if hit_attempts:
        return min(hit_attempts)
    return len(recorded)


def summarize(runs_dir: Path) -> dict:
    """Summarize every run file under *runs_dir*.

    Parameters
    ----------
    runs_dir : Path
        A skill's ``evals/<skill>/runs/`` directory.

    Returns
    -------
    dict
        ``{"tokens": int, "wall_time_s": float, "unmatched_findings": int,
        "attempts_per_item": dict[str, int]}`` — totals across every run
        file, where ``attempts_per_item`` sums, for each gated item id and
        each case it appears in, the 1-based attempt index of that item's
        first hit in the case (or the number of attempts recorded for it, if
        it never hit).
    """
    total_tokens = 0
    total_wall_time = 0.0
    total_unmatched = 0
    attempts_per_item: dict[str, int] = {}

    for run in _load_runs(runs_dir):
        total_tokens += run["tokens"]
        total_wall_time += run["wall_time_s"]
        for case in run["cases"]:
            attempts = case["attempts"]
            for attempt in attempts:
                total_unmatched += attempt["unmatched_findings"]
            for item_id in case["gated_items"]:
                needed = _attempts_needed(attempts, item_id)
                attempts_per_item[item_id] = attempts_per_item.get(item_id, 0) + needed

    return {
        "tokens": total_tokens,
        "wall_time_s": total_wall_time,
        "unmatched_findings": total_unmatched,
        "attempts_per_item": attempts_per_item,
    }


def history(runs_dir: Path) -> list[dict]:
    """Return one entry per run file under *runs_dir*, in chronological order.

    Parameters
    ----------
    runs_dir : Path
        A skill's ``evals/<skill>/runs/`` directory.

    Returns
    -------
    list[dict]
        One ``{"run_file", "run_date", "tokens", "wall_time_s",
        "unmatched_findings", "items"}`` per run file, ordered by filename
        (``<utc-timestamp>`` prefix) ascending. ``items`` maps each gated
        item id to ``{"hit": bool, "first_hit_attempt": int | None,
        "attempts_used": int}``.
    """
    entries: list[dict] = []
    for run_file in sorted(runs_dir.glob("*.json")):
        run = json.loads(run_file.read_text(encoding="utf-8"))

        unmatched = 0
        items: dict[str, dict] = {}
        for case in run["cases"]:
            attempts = case["attempts"]
            for attempt in attempts:
                unmatched += attempt["unmatched_findings"]
            for item_id in case["gated_items"]:
                hit_attempts = [
                    attempt["attempt"]
                    for attempt in attempts
                    if attempt["items"].get(item_id) == "hit"
                ]
                items[item_id] = {
                    "hit": len(hit_attempts) > 0,
                    "first_hit_attempt": min(hit_attempts) if hit_attempts else None,
                    "attempts_used": len(attempts),
                }

        entries.append(
            {
                "run_file": run_file.name,
                "run_date": run["fingerprint"]["run_date"],
                "tokens": run["tokens"],
                "wall_time_s": run["wall_time_s"],
                "unmatched_findings": unmatched,
                "items": items,
            }
        )

    return entries
