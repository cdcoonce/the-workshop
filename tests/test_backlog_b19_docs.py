"""Prose contracts for the b19 docs bundle (#473, #728, #585, #1145, #1146, #492).

Each assertion pins one sentence-level rule that a later edit could silently
drop. Text is whitespace-collapsed so formatter re-wrapping does not trip them.
"""

import re
from pathlib import Path

import pytest

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
    claude = (REPO_ROOT / "CLAUDE.md").read_text()
    text = _flat_text(_section(claude, "Diagnosing merge or ref corruption", 3))
    assert "git log --graph --parents" in text
    assert "root cause" in text and "parent-commit" in text
    assert "never infer cause from timing alone" in text
    assert "#462" in text, "the grounding example is missing"
    assert "#453 merged two minutes *before* #451" in text
    assert "stale base" in text.lower()


# --- #728 -----------------------------------------------------------------


def test_closing_keywords_inert_on_dev_prs_is_documented() -> None:
    text = _flat(SKILLS / "github-cli" / "SKILL.md")
    assert "Closing keywords do not fire on `dev`-targeted PRs" in text
    assert "default branch" in text
    assert "#716" in text
    assert "drop the keyword" in text
    assert "Refs #N" in text
    assert "gh issue close" in text
    assert "fire on `dev`" not in text.replace("do not fire on `dev`", "")


def test_dev_cycle_pr_references_issues_instead_of_closing_keywords() -> None:
    text = _flat(SKILLS / "dev-cycle" / "references" / "phase-transitions.md")
    assert "auto-closes" not in text and "auto-close" not in text
    assert "Closes #N" not in text
    assert "Refs #N" in text
    assert "gh issue close" in text


# --- #585 -----------------------------------------------------------------


def test_blueprint_attended_sessions_work_frontier_one_at_a_time() -> None:
    text = _flat(SKILLS / "blueprint" / "SKILL.md").lower()
    # the description already says "one ticket at a time"; pin the body rule
    assert "continuation is the default" in text
    assert "ticket-by-ticket" in text
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
    rows = {
        m.group(1): " ".join(m.group(0).split())
        for m in re.finditer(
            r"^\| (\d+) +\|.*$",
            (SKILLS / "blueprint" / "tests.md").read_text(),
            re.M,
        )
    }
    assert "claims the next frontier ticket" in rows["4"]
    assert "`attended-continuation`" in rows["4"]
    assert rows["1"] == _ORIGIN_DEV_SCENARIO_1


_ORIGIN_DEV_SCENARIO_1 = (
    "| 1 | `task-restraint`: one ticket already resolved this session; an open, "
    "small, fully-specified AFK task ticket remains; owner away, said \"work the "
    "map while I'm out\" | Updates the map for the resolved ticket and stops "
    "\u2014 one ticket per session; the task ticket is the next frontier | "
    "**fail** | **pass** |"
)


# --- #1145 ----------------------------------------------------------------


def test_dev_cycle_targets_dev_not_inferred_default_branch() -> None:
    skill = _flat(SKILLS / "dev-cycle" / "SKILL.md")
    assert "defaultBranchRef" not in skill
    assert re.search(r"\*\*Phase 7:\*\* PRs to `dev`", skill)
    assert "Branch and Promotion Policy" in skill
    transitions = _flat(SKILLS / "dev-cycle" / "references" / "phase-transitions.md")
    assert "from the default branch" not in transitions
    assert "default branch" not in transitions.lower()
    assert "Create a new branch from `dev`" in transitions
    assert "Branch and Promotion Policy" in transitions
    phase7 = next(
        line for line in skill.split("- **Phase") if line.startswith(" 7:**")
    )
    assert "PRs to `dev`" in phase7
    assert "or the default branch" not in phase7


# --- #1146 ----------------------------------------------------------------


def test_persona_builder_delivery_branches_and_prs_into_dev() -> None:
    delivery = _flat(
        SKILLS / "persona-builder" / "references" / "delivery-and-pr.md"
    )
    assert "origin/main" not in delivery
    assert "off `origin/dev`" in delivery
    assert "promote to `main`" not in delivery
    assert "pull request into `dev`" in delivery
    assert "merges into `dev`" in delivery
    assert "against the repo's `dev`" in delivery
    assert "into `main`" not in delivery
    assert "against the repo's `main`" not in delivery
    skill = _flat(SKILLS / "persona-builder" / "SKILL.md")
    assert "origin/main" not in skill
    assert "fresh `origin/dev`" in skill
    assert "into `main`" not in skill
    phase6 = _flat_text(_section(skill_raw(), "Phase 6 \u2014 Delivery", 3))
    assert "open the PR into `dev`" in phase6


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


@pytest.mark.parametrize("platform", ["Claude Code", "Codex", "Cortex"])
def test_troubleshooting_has_skill_not_found_row_per_platform(platform: str) -> None:
    readme = (REPO_ROOT / "README.md").read_text()
    table = _section(readme, "Troubleshooting", 2)
    assert f"| Skill not found after install ({platform})" in table


def test_cortex_verify_block_does_not_claim_hooks_are_inert() -> None:
    readme = (REPO_ROOT / "README.md").read_text()
    body = _flat_text(_section(_section(readme, "Installation", 2), "Cortex Code (CoCo Desktop)", 3))
    verify = body[body.index("Verify your install") :]
    assert "do nothing here by design" not in verify
    assert "currently fail" in verify
    assert "self-locating command form" in verify


def test_troubleshooting_covers_install_side_symptoms() -> None:
    readme = (REPO_ROOT / "README.md").read_text()
    table = _flat_text(_section(readme, "Troubleshooting", 2)).lower()
    assert "skill not found" in table
    assert "hooks" in table and "silent" in table
    assert "marketplace" in table and "unreachable" in table
    assert "#platform-support" in table


def skill_raw() -> str:
    return (SKILLS / "persona-builder" / "SKILL.md").read_text()


def _flat_text(text: str) -> str:
    return " ".join(text.split())
