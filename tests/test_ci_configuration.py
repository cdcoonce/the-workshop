"""Regression guards for CI runner dependencies."""

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_gitlab_runner_installs_gitlab_mr_guard_dependencies() -> None:
    """GitLab's minimal Python image must provide the guard's jq dependency."""
    gitlab_ci = (REPOSITORY_ROOT / ".gitlab-ci.yml").read_text()

    assert "make git jq" in gitlab_ci
