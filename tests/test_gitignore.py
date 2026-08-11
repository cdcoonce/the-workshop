"""Tests for repository ignore rules that affect plugin publishing.

The failure these guard against is silent in both directions. An ignore rule
that swallows a plugin payload file means the file never reaches a commit and
the plugin ships incomplete, with nothing red anywhere. An ignore rule too
narrow to catch build debris means `__pycache__` or a stray wheel rides along
into a published plugin directory.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _check_ignore(paths: list[str]) -> subprocess.CompletedProcess[str]:
    """Ask git whether each path would be ignored. Returncode 0 = all ignored."""
    return subprocess.run(
        ["git", "check-ignore", "--no-index", "-v", *paths],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_plugin_payload_files_are_not_ignored() -> None:
    """Plugin files are served from source now, so an ignored one simply vanishes.

    Under the old build these paths lived in `dist/` and a rebuild would have
    put them back. There is no rebuild: `plugins/` is what ships, and a file
    git refuses to see is a file no installed plugin ever gets.
    """
    payload_paths = [
        "plugins/new-plugin/.claude-plugin/plugin.json",
        "plugins/new-plugin/hooks/hooks.json",
        "plugins/new-plugin/hooks/scripts/new-hook.py",
        "plugins/persona-terse-staff-eng/output-styles/new-style.md",
        "plugins/new-plugin/skills/new-skill/SKILL.md",
        "plugins/new-plugin/agents/new-agent/AGENT.md",
        "plugins/workbench/machinery/engine/new_engine.py",
    ]

    result = _check_ignore(payload_paths)

    assert result.returncode == 1, result.stdout + result.stderr


def test_build_debris_inside_a_plugin_is_ignored() -> None:
    """Debris in a served directory is debris in a published plugin.

    `vendor_map_gen.py` walks the filesystem rather than git, so an unignored
    `__pycache__` under a skill's `scripts/` gets swept into generated output —
    which is how it was found.
    """
    debris_paths = [
        "plugins/workbench/hooks/scripts/__pycache__/protect-files.cpython-313.pyc",
        "plugins/workbench/skills/blueprint/scripts/__pycache__/build_fixture.cpython-313.pyc",
        "plugins/workbench/machinery/engine/__pycache__/context_loader.cpython-313.pyc",
    ]

    result = _check_ignore(debris_paths)

    assert result.returncode == 0, result.stdout + result.stderr


def test_python_package_archives_are_ignored() -> None:
    """Nothing builds a wheel any more, so a local one must never become a commit."""
    archive_paths = [
        "dist/the_workshop-0.1.0-py3-none-any.whl",
        "dist/the_workshop-0.1.0.tar.gz",
    ]

    result = _check_ignore(archive_paths)

    assert result.returncode == 0, result.stdout + result.stderr
