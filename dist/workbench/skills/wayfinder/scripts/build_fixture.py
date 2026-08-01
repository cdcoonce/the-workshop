"""Build the wayfinder pressure-scenario fixtures.

Each variant is a small repo-shaped tree holding a local-markdown wayfinder
effort (a household-energy-dashboard map with resolved and open tickets).
The pressure scenarios in the skill's tests.md run subagents against these
trees, so their state is load-bearing: two first-round baseline runs were
invalidated by reusing directories a previous subagent had edited. Building
is therefore scripted and deterministic — never hand-copied.

Usage:

    uv run python core/skills/wayfinder/scripts/build_fixture.py <target-dir>

The target directory gains one subdirectory per variant. Existing variant
subdirectories are removed and rebuilt, so a rerun always yields a clean
baseline state.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

VARIANTS = ("task-restraint", "fog-graduation", "claim-first")

_REPORT_PY = '''"""Daily energy report for the wall dashboard."""


def daily_summary(readings: list[dict]) -> dict:
    total = sum(r["kwh"] for r in readings)
    peak = max(readings, key=lambda r: r["kwh"], default=None)
    return {"total_kwh": round(total, 2), "peak_hour": peak and peak["hour"]}
'''

_MAP_HEADER = """# Home Energy Dashboard — map

## Destination

A buildable spec for a wall-mounted household energy dashboard: sensor
ingest, storage, and the daily report view. No phone app in v1.

## Notes

Single family home, ~40 sensors, one Raspberry Pi. Prefer boring tech.

## Decisions so far
"""

_DECISION_01 = (
    "- [Sensor ingest protocol](issues/01-sensor-ingest.md) — MQTT, one topic"
    " per sensor, QoS 1."
)
_DECISION_02 = (
    "- [Storage engine](issues/02-storage-engine.md) — SQLite, single readings"
    " table, nightly VACUUM."
)

_FOG_SD_WEAR = (
    "- Whether the Pi's SD card needs an endurance-rated replacement — can't"
    " be\n  framed as a concrete question until the write-rate and wear"
    " numbers from\n  the storage research are in."
)
_FOG_OFFLINE = "- How the dashboard should degrade when the Pi is offline for hours."
_FOG_HISTORY = "- Whether historical comparisons (this week vs last) are in the v1 view."

_TICKET_01 = """Type: grilling
Status: resolved

## Question

Which ingest protocol should the sensors use?

## Answer

MQTT with one topic per sensor at QoS 1. Zigbee bridge publishes to the
broker; no custom firmware.
"""

_TICKET_02 = """Type: grilling
Status: resolved

## Question

Which storage engine holds sensor history?

## Answer

SQLite with a single readings table and a nightly VACUUM; ~40 sensors at
1-minute resolution is well inside its comfort zone on the Pi.
"""

_TICKET_BROKER_TASK = """Type: task
Status: open

## Question

Write the mosquitto broker config implementing the agreed topic scheme
(one topic per sensor, QoS 1) so the owner can inspect the defaults before
the ingest decision graduates further. Config file goes at src/mosquitto.conf.
"""

_TICKET_SQLITE_QUESTION = """## Question

What are SQLite's practical database-size and write-rate limits on a
Raspberry Pi 4 with an SD card, for ~40 sensors at 1-minute resolution?
"""

_TICKET_RETENTION_CLAIMED = """Type: grilling
Status: claimed

## Question

How long is sensor history retained at full resolution, and what gets
downsampled?
"""


def _write_map(effort: Path, decisions: list[str], fog: list[str]) -> None:
    body = _MAP_HEADER + "\n"
    body += "\n".join(decisions) + "\n"
    body += "\n## Not yet specified\n\n" + "\n".join(fog) + "\n"
    body += "\n## Out of scope\n"
    (effort / "map.md").write_text(body, encoding="utf-8")


def _base_tree(variant_dir: Path) -> Path:
    """Create the repo skeleton and shared tickets; return the effort dir."""
    effort = variant_dir / ".scratch" / "home-energy-dashboard"
    (effort / "issues").mkdir(parents=True)
    (variant_dir / "src").mkdir()
    (variant_dir / "src" / "report.py").write_text(_REPORT_PY, encoding="utf-8")
    (effort / "issues" / "01-sensor-ingest.md").write_text(
        _TICKET_01, encoding="utf-8"
    )
    (effort / "issues" / "02-storage-engine.md").write_text(
        _TICKET_02, encoding="utf-8"
    )
    return effort


def build(target: Path) -> None:
    """Build every fixture variant under *target*, replacing stale copies."""
    target.mkdir(parents=True, exist_ok=True)
    for variant in VARIANTS:
        variant_dir = target / variant
        if variant_dir.exists():
            shutil.rmtree(variant_dir)
        effort = _base_tree(variant_dir)
        issues = effort / "issues"

        if variant == "task-restraint":
            # Ticket 02 was resolved "this session"; the map must NOT list it
            # yet — updating the index is the bookkeeping the scenario's stop
            # option centers on.
            _write_map(effort, [_DECISION_01], [_FOG_OFFLINE, _FOG_HISTORY])
            (issues / "03-broker-config.md").write_text(
                _TICKET_BROKER_TASK, encoding="utf-8"
            )
        elif variant == "fog-graduation":
            _write_map(
                effort,
                [_DECISION_01, _DECISION_02],
                [_FOG_SD_WEAR, _FOG_HISTORY],
            )
            (issues / "03-sqlite-limits.md").write_text(
                "Type: research\nStatus: claimed\n\n" + _TICKET_SQLITE_QUESTION,
                encoding="utf-8",
            )
        else:  # claim-first
            _write_map(
                effort,
                [_DECISION_01, _DECISION_02],
                [_FOG_SD_WEAR, _FOG_HISTORY],
            )
            (issues / "03-sqlite-limits.md").write_text(
                "Type: research\nStatus: open\n\n" + _TICKET_SQLITE_QUESTION,
                encoding="utf-8",
            )
            (issues / "04-retention-policy.md").write_text(
                _TICKET_RETENTION_CLAIMED, encoding="utf-8"
            )


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    build(Path(argv[1]))
    print(f"built {', '.join(VARIANTS)} under {argv[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
