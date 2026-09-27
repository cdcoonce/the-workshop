"""Writes the write-once red-run report.

Reads a run file (#993's own ``ledger.py`` output) as read-only input. Never
edits a run file, never touches a raw's content — only the run file's own
recorded data (case names, item ids, raw paths, fingerprint fields).
"""

from __future__ import annotations

import json
from pathlib import Path

_HOME = str(Path.home())
_HOME_PLACEHOLDER = "<HOME>"

_COUNTED_MISS_CAP = 3

_FINGERPRINT_FIELDS = [
    "direct_tier_hash",
    "injection_tier_hash",
    "plugin_version",
    "claude_code_version",
    "run_date",
]


def _scrub(text: str) -> str:
    return text.replace(_HOME, _HOME_PLACEHOLDER)


def _item_status(outcomes: list[str]) -> str:
    if "hit" in outcomes:
        return "hit"
    if outcomes.count("miss") >= _COUNTED_MISS_CAP:
        return "red"
    return "void"


def _failing_items(run: dict) -> list[dict]:
    failing = []
    for case in run["cases"]:
        attempts = case["attempts"]
        for item_id in case["gated_items"]:
            outcomes = [
                attempt["items"][item_id] for attempt in attempts if item_id in attempt["items"]
            ]
            status = _item_status(outcomes)
            if status in ("red", "void"):
                failing.append({"case": case["case"], "item": item_id, "status": status})
    return failing


def _raws_for_case(run: dict, case_name: str) -> list[str]:
    for case in run["cases"]:
        if case["case"] == case_name:
            return [attempt["raw"] for attempt in case["attempts"]]
    return []


def _newest_green_run(run_file: Path, skill: str) -> dict | None:
    newest: tuple[str, dict] | None = None
    for candidate_path in sorted(run_file.parent.glob("*.json")):
        if candidate_path == run_file:
            continue
        candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
        if candidate.get("skill") != skill or candidate.get("verdict") != "green":
            continue
        if newest is None or candidate_path.name > newest[0]:
            newest = (candidate_path.name, candidate)
    return newest[1] if newest is not None else None


def _fingerprint_diff_lines(run: dict, green: dict | None) -> list[str]:
    if green is None:
        return ["No prior green run for this skill."]
    lines = []
    for field in _FINGERPRINT_FIELDS:
        old = green["fingerprint"][field]
        new = run["fingerprint"][field]
        if old == new:
            lines.append(f"- {field}: unchanged ({new})")
        else:
            lines.append(f"- {field}: {old} -> {new}")
    return lines


def write_report(run_file: Path) -> Path | None:
    """Write the write-once red-run report for *run_file*.

    Parameters
    ----------
    run_file : Path
        A run file written by ``ledger.write_run``.

    Returns
    -------
    Path | None
        The written report's path, or ``None`` if the run is not red.

    Raises
    ------
    FileExistsError
        If the report path already exists.
    """
    run = json.loads(run_file.read_text(encoding="utf-8"))
    if run["verdict"] != "red":
        return None

    report_path = run_file.with_name(run_file.stem + ".report.md")
    if report_path.exists():
        raise FileExistsError(f"report already exists: {report_path}")

    failing = _failing_items(run)
    green = _newest_green_run(run_file, run["skill"])

    lines = [f"# Red run report: {run['skill']} ({run_file.stem})", "", "## Failing items"]
    for entry in failing:
        lines.append(f"- {entry['case']} / {entry['item']}: {entry['status']}")

    lines += ["", "## Raws"]
    seen_cases: set[str] = set()
    for entry in failing:
        case_name = entry["case"]
        if case_name in seen_cases:
            continue
        seen_cases.add(case_name)
        lines.append(f"### {case_name}")
        for raw in _raws_for_case(run, case_name):
            lines.append(f"- {raw}")

    lines += ["", "## Fingerprint diff"]
    lines += _fingerprint_diff_lines(run, green)

    text = _scrub("\n".join(lines) + "\n")
    report_path.write_text(text, encoding="utf-8")
    return report_path
