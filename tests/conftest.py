"""Shared test fixtures for the flat plugin tree.

The fixtures that lived here before the flat reorg modelled the composition
build: a `core/` tier, per-preset `manifest.json` files declaring what to
compose in, and a `dist/` directory to build into. None of those exist, so
none of those fixtures survived. What replaces them is smaller, because the
thing being modelled is smaller — a plugin is now just a directory.
"""

import json
from pathlib import Path

import pytest

# A hook that declares its own wiring, which is all `scripts/stamp.py` needs to
# generate a plugin's `hooks/hooks.json`. Kept deliberately minimal: tests that
# care about hook *behaviour* run the real hooks, not this one.
_DEMO_HOOK = '''#!/usr/bin/env python3
"""SessionStart hook: a test double that does nothing and exits clean."""

WORKSHOP_HOOK = {"event": "SessionStart"}

import sys  # noqa: E402

sys.exit(0)
'''

_RUN_HOOK = """#!/usr/bin/env bash
HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$HOOK_DIR/scripts/$1" "${@:2}"
"""


def _skill(path: Path, slug: str, description: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text(
        f"---\nname: {slug}\ndescription: {description}\n---\n\n# {slug}\n"
    )


def _agent(path: Path, slug: str, description: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "AGENT.md").write_text(
        f"---\nname: {slug}\ndescription: {description}\nrole: builder\n---\n\n# {slug}\n"
    )


@pytest.fixture
def make_plugin():
    """Build one plugin directory under ``<root>/plugins/<name>/``.

    Returns the plugin dir. Every part is optional so a test can build the
    smallest plugin that exercises what it cares about — a manifest-only plugin
    is a legitimate shape now that nothing composes content into it.
    """

    def _make(
        root: Path,
        name: str,
        *,
        version: str = "1.0.0",
        description: str | None = None,
        conventions: list[str] | None = None,
        skills: list[str] | None = None,
        agents: list[str] | None = None,
        hooks: bool = False,
    ) -> Path:
        plugin = root / "plugins" / name
        manifest_dir = plugin / ".claude-plugin"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        doc: dict[str, object] = {
            "name": name,
            "version": version,
            "description": description or f"{name} test plugin",
        }
        if conventions:
            doc["conventions"] = conventions
        (manifest_dir / "plugin.json").write_text(json.dumps(doc, indent=2) + "\n")

        for slug in skills or []:
            _skill(plugin / "skills" / slug, slug, f"Test skill {slug}.")
        for slug in agents or []:
            _agent(plugin / "agents" / slug, slug, f"Test agent {slug}.")

        if hooks:
            hooks_dir = plugin / "hooks"
            (hooks_dir / "scripts").mkdir(parents=True, exist_ok=True)
            (hooks_dir / "run-hook.sh").write_text(_RUN_HOOK)
            (hooks_dir / "scripts" / "demo-hook.py").write_text(_DEMO_HOOK)

        return plugin

    return _make


@pytest.fixture
def flat_repo(tmp_path: Path, make_plugin) -> Path:
    """A minimal but complete repo in the flat layout, ready to stamp.

    One plugin with every component class present, plus the two repo-level
    inputs the stamper reads (`scripts/platform-support.json`) and writes into
    (`docs/reference/`). Tests that need a second plugin add one with
    ``make_plugin``.
    """
    make_plugin(
        tmp_path,
        "demo",
        description="A demo plugin.",
        conventions=["Test-driven development: write the failing test first"],
        skills=["demo-skill"],
        agents=["demo-agent"],
        hooks=True,
    )

    (tmp_path / "plugins" / "demo" / "docs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "plugins" / "demo" / "docs" / "tdd.md").write_text(
        "# Test-Driven Development\n\nWrite the failing test first.\n"
    )

    scripts = tmp_path / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / "platform-support.json").write_text(
        json.dumps(
            {
                "platforms": ["Claude Code", "Codex", "Cortex Code"],
                "components": [
                    {
                        "name": "Skills",
                        "cells": {
                            platform: {
                                "status": "works",
                                "note": "Loads natively.",
                                "compat": f"{platform} → Skills",
                            }
                            for platform in ("Claude Code", "Codex", "Cortex Code")
                        },
                    }
                ],
            },
            indent=2,
        )
        + "\n"
    )

    (tmp_path / "docs" / "reference").mkdir(parents=True, exist_ok=True)
    return tmp_path
