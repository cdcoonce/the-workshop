"""Regression coverage for the GitLab skill pair's ownership boundary.

`gitlab-cli` is the broad terminal surface (issues, branches, MR review, CI) and
`gitlab-mr-create` is the narrow, script-backed MR-creation path. Two skills that
both answer "work with GitLab merge requests" would race on the same trigger, so
the boundary is asserted here rather than left to prose discipline.
"""

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
GITLAB_CLI = REPOSITORY_ROOT / "core/skills/gitlab-cli/SKILL.md"
GITLAB_MR_CREATE = REPOSITORY_ROOT / "presets/workbench/skills/gitlab-mr-create/SKILL.md"
DAA_CODE_REVIEW = REPOSITORY_ROOT / "core/skills/daa-code-review/SKILL.md"
DAA_PYTHON_CHECKS = REPOSITORY_ROOT / "core/skills/daa-code-review/references/python-checks.md"


def _normalized(path: Path) -> str:
    return " ".join(path.read_text().split())


def test_gitlab_cli_is_owned_by_core() -> None:
    """`gitlab-cli` is the sibling of `github-cli`, so core owns it."""
    assert GITLAB_CLI.is_file()
    assert (REPOSITORY_ROOT / "core/skills/github-cli/SKILL.md").is_file()


def test_gitlab_cli_defers_merge_request_creation() -> None:
    """The broad skill must hand MR creation to the narrow one, not duplicate it."""
    skill = _normalized(GITLAB_CLI)

    assert "gitlab-mr-create" in skill
    # The vendored copy this was migrated from taught `glab mr create` directly.
    # Keeping that would give two skills the same trigger and let the unverified
    # path win by being listed first.
    assert "glab mr create" not in skill


def test_gitlab_mr_create_remains_the_merge_request_owner() -> None:
    """The narrow skill keeps its exclusive claim on MR creation."""
    skill = _normalized(GITLAB_MR_CREATE)

    assert "Use whenever creating a GitLab merge request." in skill
    assert "Do not invoke `glab mr create` directly." in skill


def test_gitlab_cli_stays_within_progressive_disclosure_budget() -> None:
    """SKILL.md is the index; the command catalog belongs in references/."""
    assert len(GITLAB_CLI.read_text().splitlines()) < 100
    assert (REPOSITORY_ROOT / "core/skills/gitlab-cli/references/commands.md").is_file()


def test_code_review_judges_engineering_practice_not_just_linters() -> None:
    """The engineering-practice framing a vendored OneStream copy carried already
    lives here via progressive disclosure: the principle in SKILL.md, the worked
    naming example in the reference. This asserts it stays, so the vendored copy
    can be deleted without loss."""
    skill = _normalized(DAA_CODE_REVIEW)
    assert "SOLID/DRY/YAGNI" in skill
    assert "descriptive variable naming" in skill

    naming = _normalized(DAA_PYTHON_CHECKS)
    assert "private_key_bytes" in naming
