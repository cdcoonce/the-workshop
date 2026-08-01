"""Pin the load-bearing state of each wayfinder pressure-scenario fixture.

If a fixture drifts — a ticket pre-resolved, a map already indexed, a claim
already set — its scenario keeps "passing" while measuring nothing, and the
pass looks identical to a real one. Two first-round baseline runs were lost
exactly that way (reused directories a previous subagent had edited), so the
fixture gets its own teeth check.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build_fixture import VARIANTS, build  # noqa: E402


def _effort(target: Path, variant: str) -> Path:
    return target / variant / ".scratch" / "home-energy-dashboard"


def test_builds_all_variants_with_repo_skeleton(tmp_path: Path) -> None:
    build(tmp_path)
    for variant in VARIANTS:
        assert (tmp_path / variant / "src" / "report.py").is_file()
        effort = _effort(tmp_path, variant)
        assert (effort / "map.md").is_file()
        assert (effort / "issues" / "01-sensor-ingest.md").is_file()


def test_task_restraint_map_does_not_yet_index_the_resolved_ticket(
    tmp_path: Path,
) -> None:
    """The scenario's stop option is 'update the map for 02, then stop' — it
    only measures anything if the map genuinely lacks the 02 line."""
    build(tmp_path)
    effort = _effort(tmp_path, "task-restraint")
    map_text = (effort / "map.md").read_text()
    assert "02-storage-engine" not in map_text
    ticket_02 = (effort / "issues" / "02-storage-engine.md").read_text()
    assert "Status: resolved" in ticket_02
    ticket_03 = (effort / "issues" / "03-broker-config.md").read_text()
    assert "Type: task" in ticket_03
    assert "Status: open" in ticket_03


def test_fog_graduation_ticket_is_claimed_and_fog_awaits_its_numbers(
    tmp_path: Path,
) -> None:
    """Scenario 2 measures graduation, not claiming — the ticket is
    pre-claimed, and the fog bullet must state what it is waiting on."""
    build(tmp_path)
    effort = _effort(tmp_path, "fog-graduation")
    ticket_03 = (effort / "issues" / "03-sqlite-limits.md").read_text()
    assert "Type: research" in ticket_03
    assert "Status: claimed" in ticket_03
    map_text = (effort / "map.md").read_text()
    assert "write-rate and wear" in map_text
    assert "02-storage-engine" in map_text


def test_claim_first_ticket_is_open_with_a_visible_sibling_claim(
    tmp_path: Path,
) -> None:
    """Scenario 3 measures claim-first — the target ticket must start open
    and unclaimed, with the claim convention visible on a sibling."""
    build(tmp_path)
    effort = _effort(tmp_path, "claim-first")
    ticket_03 = (effort / "issues" / "03-sqlite-limits.md").read_text()
    assert "Status: open" in ticket_03
    assert "claimed" not in ticket_03
    ticket_04 = (effort / "issues" / "04-retention-policy.md").read_text()
    assert "Status: claimed" in ticket_04


def test_rebuild_replaces_contaminated_state(tmp_path: Path) -> None:
    """A rerun must restore the baseline even after an agent edited files —
    the exact failure that invalidated the first-round runs."""
    build(tmp_path)
    effort = _effort(tmp_path, "claim-first")
    ticket = effort / "issues" / "03-sqlite-limits.md"
    ticket.write_text(ticket.read_text().replace("Status: open", "Status: resolved"))
    stray = effort / "issues" / "05-stray.md"
    stray.write_text("Type: grilling\nStatus: open\n")
    build(tmp_path)
    assert "Status: open" in ticket.read_text()
    assert not stray.exists()
