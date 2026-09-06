"""Teeth-verified-build contract for the `using-workflow` router.

A Workflow-dispatched build proved that a green builder stage is not evidence
the tests guard anything: an adversarial teeth stage that re-injected one
representative defect per named test caught a comparison that could never
fail, inside a spec the orchestrator itself had written. The router is the
one skill loaded before any workflow is authored, so the trigger lives here —
builds get the verification stage by default, not when someone remembers a
separate skill. `detector-teeth-check` keeps the mechanics; the router pins
when they fire and what failing them means.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SLUG = "using-workflow"
SKILL_MD = REPO_ROOT / "plugins" / "workbench" / "skills" / SLUG / "SKILL.md"


def _skill_text() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def test_skill_is_owned_by_workbench() -> None:
    """Membership is the filesystem; one slug lives in exactly one plugin."""
    assert SKILL_MD.is_file(), f"{SKILL_MD} is missing"
    twins = [
        p
        for p in REPO_ROOT.glob(f"plugins/*/skills/{SLUG}/SKILL.md")
        if "worktrees" not in p.relative_to(REPO_ROOT).parts
    ]
    assert len(twins) == 1, f"slug {SLUG} shipped by {len(twins)} plugins"


def test_router_wires_workflow_builds_to_a_teeth_stage() -> None:
    """The router, not operator memory, adds the verification stage."""
    text = _skill_text().lower()
    assert "detector-teeth-check" in text, (
        "router must hand the mutation mechanics to detector-teeth-check"
    )
    assert "adversarial" in text, (
        "the teeth stage must be adversarial — a second agent, not the builder"
    )
    assert "builder" in text, (
        "the teeth stage is defined relative to the builder stage it follows"
    )


def test_teeth_stage_semantics_are_pinned() -> None:
    """Red on the predicted test, clean reversion, survivors fail the review."""
    text = _skill_text().lower()
    assert "red on the predicted test" in text, (
        "each mutation must name the one test expected to catch it"
    )
    assert "revert" in text, "mutations must be reverted after each check"
    assert "vacuous" in text, (
        "a surviving mutation must be named for what it is: a vacuous guard"
    )
    assert "fails the build review" in text, (
        "a survivor is a build failure, not a note"
    )


def test_skill_md_stays_under_the_line_budget() -> None:
    """Progressive disclosure: the invocation-loaded file stays readable."""
    line_count = len(_skill_text().splitlines())
    assert line_count < 100, f"SKILL.md is {line_count} lines"
