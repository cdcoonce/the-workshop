"""Ownership and boundary coverage for `gitlab-ci-watch`.

The watch-until-terminal loop was hand-rolled ~7 times in one session before
being extracted here. Like `gitlab-mr-create`, the skill is script-backed so
the guarded parsing lives in one tested place, and the boundary with
`gitlab-cli` (broad interactive surface) is asserted rather than left to
prose discipline — the same carve `test_gitlab_skill_boundaries.py` enforces
for MR creation.
"""

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPOSITORY_ROOT / "plugins/workbench/skills/gitlab-ci-watch"
SKILL_MD = SKILL_DIR / "SKILL.md"
SCRIPT = SKILL_DIR / "scripts/ci_watch.py"
GITLAB_CLI = REPOSITORY_ROOT / "plugins/workbench/skills/gitlab-cli/SKILL.md"


def _normalized(path: Path) -> str:
    return " ".join(path.read_text().split())


def test_skill_is_owned_by_workbench() -> None:
    """Sibling of the other GitLab skills, so workbench owns the slug."""
    assert SKILL_MD.is_file()
    assert SCRIPT.is_file()


def test_skill_stays_within_progressive_disclosure_budget() -> None:
    """SKILL.md documents invocation and contract; behavior lives in the script."""
    assert len(SKILL_MD.read_text().splitlines()) < 100


def test_script_ships_its_own_test_suite() -> None:
    """Behavioral coverage rides the auto-discovered skill-script gate."""
    tests_dir = SKILL_DIR / "scripts/tests"
    assert any(tests_dir.glob("test_*.py"))


def test_gitlab_cli_hands_watching_to_the_watcher() -> None:
    """The broad skill routes post-push watching here instead of teaching a loop.

    Before the carve, gitlab-cli's own prose said to "watch the pipeline for
    the pushed SHA" with no mechanism — which is how the loop got hand-rolled
    seven times. The cross-route replaces the instruction, mirroring how MR
    creation was handed to gitlab-mr-create.
    """
    skill = _normalized(GITLAB_CLI)
    assert "gitlab-ci-watch" in skill


def test_watcher_defers_interactive_inspection() -> None:
    """The watcher owns watch-until-terminal only; browsing stays with gitlab-cli."""
    skill = _normalized(SKILL_MD)
    assert "gitlab-cli" in skill


def test_skill_documents_the_exit_contract() -> None:
    """The consumer is a session reading one completion notification: the
    verdict must be stated as exit codes, not implied by report tone."""
    skill = _normalized(SKILL_MD)
    for marker in ("exit 0", "exit 1", "exit 2"):
        assert marker in skill, f"exit contract missing {marker!r}"


def test_skill_warns_off_foreground_and_bare_paths() -> None:
    """The two invocation traps that kill the watcher in practice: foreground
    sleep is blocked in the harness, and the script path must be expanded from
    the announced base directory (#686 — $CLAUDE_PLUGIN_ROOT is hook-only)."""
    skill = _normalized(SKILL_MD)
    assert "run_in_background" in skill
    assert "base directory" in skill.lower()
