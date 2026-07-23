"""Regression coverage for Workshop's repository integration policy."""

from pathlib import Path


def test_finish_branch_requires_explicit_integration_branch() -> None:
    """The default branch must never be assumed to be the integration branch."""
    repository_root = Path(__file__).resolve().parents[1]
    skill = " ".join(
        (repository_root / "core/skills/finish-branch/SKILL.md").read_text().split()
    )

    assert "Never infer the integration branch from the repository default branch." in skill
    assert "project instructions and CI/CD configuration" in skill


def test_workshop_declares_dev_first_promotion_path() -> None:
    """Workshop changes land on GitHub dev before GitLab promotion to main."""
    repository_root = Path(__file__).resolve().parents[1]
    instructions = (repository_root / "CLAUDE.md").read_text()

    assert "GitHub `dev` first" in instructions
    assert "Never push directly to `main`" in instructions


def test_router_requires_policy_resolution_and_afk_mode() -> None:
    """The universal router must work unattended without assuming CI policy."""
    repository_root = Path(__file__).resolve().parents[1]
    router = " ".join(
        (repository_root / "core/skills/using-workflow/SKILL.md").read_text().split()
    )

    assert "Resolve repository policy before selecting an integration workflow." in router
    assert "AFK / unattended" in router
    assert "capability gap" in router


def test_router_resolves_development_branch_naming_without_agent_prefixes() -> None:
    """Branch naming follows user/repository policy before a conventional fallback."""
    repository_root = Path(__file__).resolve().parents[1]
    router = " ".join(
        (repository_root / "core/skills/using-workflow/SKILL.md").read_text().split()
    )

    assert "Historical vendor- or agent-prefixed branches do not count as policy." in router
    assert "Resolve development branch naming separately from the integration target." in router
    assert (
        "Use this precedence: explicit user policy, then the nearest explicit repository "
        "policy, then the fallback `<type>/<kebab-case-slug>`."
        in router
    )
    assert (
        "Use Conventional Commit type vocabulary for the fallback: `feat/`, `fix/`, "
        "`docs/`, `refactor/`, `test/`, `chore/`, `ci/`, `perf/`, and `style/`."
        in router
    )
    assert (
        "Branch history may inform slug formatting only when it is consistent with the "
        "explicit policy."
        in router
    )
