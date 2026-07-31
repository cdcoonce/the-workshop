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


# ---------------------------------------------------------------------------
# A finding can reproduce exactly as written and still be wrong
# ---------------------------------------------------------------------------


def test_the_sweep_has_a_verdict_for_a_sound_finding_with_an_unsound_remedy() -> None:
    """The gap the five original verdicts leave open.

    All of `STILL_VALID`, `ALREADY_DONE`, `SUPERSEDED`, `NO_LONGER_REPRODUCES` and
    `UNVERIFIABLE` ask whether the record is *stale*. None covers the case where the
    finding reproduces exactly as written, is not stale in any way, and its diagnosis
    or prescribed fix is simply wrong — so `STILL_VALID` reads as authorization to
    implement it.

    Found in a PCI curve-audit review: a finding recorded as the queue's
    highest-priority item quoted a code comment as its contract, the comment
    contradicted the module it described, and the prescribed fix would have rendered
    a phantom success CLEAN. It reproduced perfectly. It was still wrong.
    """
    text = (REPO_ROOT / "core" / "skills" / "stale-artifact-sweep" / "SKILL.md").read_text()

    assert "REMEDY_UNSOUND" in text, (
        "the sweep can only classify a finding as stale or not; a finding that "
        "reproduces but whose prescribed fix is wrong has no verdict"
    )


def test_the_sweep_routes_the_unsound_remedy_check_to_detector_teeth_check() -> None:
    """Proving a remedy wrong means applying it and watching the suite go red —
    which is `detector-teeth-check`'s job, not a second copy of it here."""
    text = (REPO_ROOT / "core" / "skills" / "stale-artifact-sweep" / "SKILL.md").read_text()

    assert "detector-teeth-check" in text
