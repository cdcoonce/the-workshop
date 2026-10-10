"""Prose contracts for the b19 docs bundle (#473, #728, #585, #1145, #1146, #492).

Each assertion pins one sentence-level rule that a later edit could silently
drop. Text is whitespace-collapsed so formatter re-wrapping does not trip them.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS = REPO_ROOT / "plugins" / "workbench" / "skills"


def _flat(path: Path) -> str:
    """Read ``path`` with whitespace collapsed to single spaces."""
    return " ".join(path.read_text().split())


def _section(text: str, heading: str, level: int) -> str:
    """Return the body of ``heading`` up to the next heading of <= ``level``."""
    marks = "#" * level
    match = re.search(rf"^{marks} {re.escape(heading)}[^\n]*\n", text, re.M)
    assert match, f"heading not found: {heading}"
    rest = text[match.end() :]
    end = re.search(rf"^#{{1,{level}}} ", rest, re.M)
    return rest[: end.start()] if end else rest


# --- #473 -----------------------------------------------------------------


def test_merge_corruption_cause_must_be_verified_against_parents() -> None:
    text = _flat(REPO_ROOT / "CLAUDE.md")
    assert "git log --graph --parents" in text
    assert "root cause" in text and "parent-commit" in text
    assert "#462" in text, "the grounding example is missing"
    assert "stale base" in text.lower()


# --- #728 -----------------------------------------------------------------


def test_closing_keywords_inert_on_dev_prs_is_documented() -> None:
    text = _flat(SKILLS / "github-cli" / "SKILL.md").lower()
    assert "closing keyword" in text
    assert "default branch" in text
    assert "#716" in text
    assert "gh issue close" in text


# --- #585 -----------------------------------------------------------------


def test_blueprint_attended_sessions_work_frontier_one_at_a_time() -> None:
    text = _flat(SKILLS / "blueprint" / "SKILL.md").lower()
    assert "one ticket at a time" in text
    assert "unattended" in text
    assert "checkpoint" in text
    # the unattended cap keeps its original name (pinned by test_blueprint_skill)
    assert "one ticket per session" in text


def test_blueprint_skill_stays_within_line_budget() -> None:
    lines = (SKILLS / "blueprint" / "SKILL.md").read_text().splitlines()
    assert len(lines) <= 100


def test_blueprint_scenarios_pin_both_attended_and_owner_away() -> None:
    text = _flat(SKILLS / "blueprint" / "tests.md")
    assert "`task-restraint`" in text and "owner away" in text
    assert "`attended-continuation`" in text
    assert "citing \"one ticket per session\" is the **fail** reading" in text


# --- #1145 ----------------------------------------------------------------


def test_dev_cycle_targets_dev_not_inferred_default_branch() -> None:
    skill = _flat(SKILLS / "dev-cycle" / "SKILL.md")
    assert "defaultBranchRef" not in skill
    assert re.search(r"\*\*Phase 7:\*\* PRs to `dev`", skill)
    assert "Branch and Promotion Policy" in skill
    transitions = _flat(SKILLS / "dev-cycle" / "references" / "phase-transitions.md")
    assert "from the default branch" not in transitions
    assert "Create a new branch from `dev`" in transitions


# --- #1146 ----------------------------------------------------------------


def test_persona_builder_delivery_branches_and_prs_into_dev() -> None:
    delivery = _flat(
        SKILLS / "persona-builder" / "references" / "delivery-and-pr.md"
    )
    assert "origin/main" not in delivery
    assert "off `origin/dev`" in delivery
    assert "promote to `main`" not in delivery
    assert "pull request into `dev`" in delivery
    skill = _flat(SKILLS / "persona-builder" / "SKILL.md")
    assert "origin/main" not in skill
    assert "fresh `origin/dev`" in skill


# --- #492 -----------------------------------------------------------------

PLATFORMS = (
    ("Claude Code", "claude plugin list"),
    ("Codex", "codex plugin list"),
    ("Cortex Code (CoCo Desktop)", "cortex skill list"),
)


def test_each_install_section_has_a_verify_block() -> None:
    readme = (REPO_ROOT / "README.md").read_text()
    install = _section(readme, "Installation", 2)
    for platform, list_command in PLATFORMS:
        body = _section(install, platform, 3)
        assert "Verify your install" in body, platform
        assert list_command in body, platform
        assert "brainstorm" in body, platform


def test_troubleshooting_covers_install_side_symptoms() -> None:
    readme = (REPO_ROOT / "README.md").read_text()
    table = _flat_text(_section(readme, "Troubleshooting", 2)).lower()
    assert "skill not found" in table
    assert "hooks" in table and "silent" in table
    assert "marketplace" in table and "unreachable" in table
    assert "#platform-support" in table


def _flat_text(text: str) -> str:
    return " ".join(text.split())
