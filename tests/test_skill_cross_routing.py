"""Skills that act on recorded claims must route to the skill that verifies them.

`stale-artifact-sweep` shipped with no inbound references: its own SKILL.md named
the skills it should precede, but none of them pointed back, so it only ran when
someone happened to remember it. A skill nobody routes to does not run.

These are the workflows that take a recorded artifact — a review finding, a bug
report, an MR queue — and act on it as though it were still true.
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

CONSUMERS = ("mr-review-fixes", "triage-issue", "mr-merge-order")


@pytest.mark.parametrize("skill", CONSUMERS)
def test_skill_routes_to_stale_artifact_sweep(skill: str) -> None:
    text = (REPO_ROOT / "core" / "skills" / skill / "SKILL.md").read_text()

    assert "stale-artifact-sweep" in text, (
        f"{skill} acts on recorded artifacts but never routes to the skill that "
        "verifies them are still true"
    )


def test_the_sweep_names_the_workflows_it_precedes() -> None:
    """The reverse direction: the sweep must say where it belongs in a workflow."""
    text = (REPO_ROOT / "core" / "skills" / "stale-artifact-sweep" / "SKILL.md").read_text()

    for skill in CONSUMERS:
        assert skill in text, f"stale-artifact-sweep does not mention {skill}"
