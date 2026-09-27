"""Regression coverage: merging and promotion route through ``github-pr-land``.

A skill or policy that still teaches the hand ritual (``gh pr merge``,
``gh pr checks --watch``, ``git push origin origin/dev:main``) brings back the
merge-at-an-untested-head failure the tool exists to stop.
"""

import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SKILLS = REPOSITORY_ROOT / "plugins/workbench/skills"


def _normalized(path: Path) -> str:
    return " ".join(path.read_text().split())


def test_drain_queue_lands_through_pr_land() -> None:
    """Guards against drain-queue merging with a bare ``gh pr merge``, or losing its teardown."""
    skill = _normalized(SKILLS / "drain-queue/SKILL.md")

    assert "gh pr merge" not in skill
    assert "pr_land.py land" in skill
    assert "--method squash" in skill
    assert "gh issue view <N> --json state --jq .state" in skill
    assert "git worktree remove <worktree> && git branch -D <branch>" in skill


def test_github_cli_watches_and_merges_through_pr_land() -> None:
    """Guards against github-cli teaching ``gh pr checks --watch`` as the CI wait."""
    skill = _normalized(SKILLS / "github-cli/SKILL.md")

    assert "gh pr checks --watch" not in skill
    assert "pr_land.py watch" in skill
    assert "github-pr-land" in skill


def test_github_cli_merge_reference_points_to_pr_land() -> None:
    """Guards against the ``gh pr merge`` reference omitting the pointer, or losing its examples."""
    reference = _normalized(SKILLS / "github-cli/references/commands.md")
    section = re.search(r"### gh pr merge(.*?)###", reference)

    assert section is not None
    assert "github-pr-land" in section.group(1)
    assert "gh pr merge 45 --squash --delete-branch" in reference
    assert "gh pr merge 45 --auto" in reference


def test_finish_branch_and_policy_name_pr_land() -> None:
    """Guards against finish-branch or CLAUDE.md leaving landing to a hand ritual."""
    assert "github-pr-land" in _normalized(SKILLS / "finish-branch/SKILL.md")
    assert "github-pr-land" in _normalized(REPOSITORY_ROOT / "CLAUDE.md")


def test_policy_promotes_through_pr_land() -> None:
    """Guards against the promotion policy still pushing ``origin/dev:main`` by hand."""
    instructions = _normalized(REPOSITORY_ROOT / "CLAUDE.md")

    assert "git push origin origin/dev:main" not in instructions
    assert "pr_land.py promote" in instructions
    assert "never the merge button" in instructions
