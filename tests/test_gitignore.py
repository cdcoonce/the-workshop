"""Tests for repository ignore rules that affect plugin publishing."""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_dist_marketplace_payloads_are_not_ignored() -> None:
    """New generated plugin files must appear in git status."""
    payload_paths = [
        "dist/new-plugin/hooks/hooks.json",
        "dist/data-viz/hooks/scripts/new-hook.py",
        "dist/persona-terse-staff-eng/output-styles/new-style.md",
        "dist/new-plugin/skills/new-skill/SKILL.md",
    ]

    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "-v", *payload_paths],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1, result.stdout + result.stderr


def test_dist_python_package_archives_are_ignored() -> None:
    """Wheel/sdist outputs should stay local even though dist bundles are tracked."""
    archive_paths = [
        "dist/the_workshop-0.1.0-py3-none-any.whl",
        "dist/the_workshop-0.1.0.tar.gz",
    ]

    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "-v", *archive_paths],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
