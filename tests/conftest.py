"""Shared test fixtures for the template system."""

import json
from pathlib import Path

import pytest


@pytest.fixture
def make_preset():
    """Build a minimal installable preset bundle on disk.

    The installer tests each grew their own copy of this, differing only in
    whether a `skills/` directory and a skill file were created — so a new
    required manifest field had to be found and fixed in three places.

    Parameters
    ----------
    skills : bool
        Create the `skills/` directory. The CLI tests rely on its absence.
    skill_file : str | None
        Name of a skill file to write inside `skills/`, when one is needed.

    Returns
    -------
    Callable[..., Path]
        Builder returning the preset directory.
    """

    def _make_preset(
        root: Path, name: str, *, skills: bool = True, skill_file: str | None = None
    ) -> Path:
        plugin_dir = root / name / ".claude-plugin"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "plugin.json").write_text(
            json.dumps({"name": name, "version": "1.0.0"})
        )
        if skills or skill_file:
            (root / name / "skills").mkdir()
        if skill_file:
            (root / name / "skills" / skill_file).write_text("# skill")
        return root / name

    return _make_preset


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    """Create a minimal template repo structure for testing."""
    core = tmp_path / "core"
    core.mkdir()

    skills = core / "skills"
    skills.mkdir()
    for skill_name in ["commit", "daa-code-review", "tdd"]:
        skill_dir = skills / skill_name
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            f"---\nname: {skill_name}\ndescription: {skill_name} skill\n---\n\n"
            f"# {skill_name} skill\n"
        )

    hooks = core / "hooks"
    hooks.mkdir()
    (hooks / "protect-files.py").write_text("# protect files hook")

    agents = core / "agents"
    agents.mkdir()
    for agent_name, role in [("tdd-implementer", "implementer"), ("code-reviewer", "reviewer")]:
        agent_dir = agents / agent_name
        agent_dir.mkdir()
        (agent_dir / "AGENT.md").write_text(
            f"---\nname: {agent_name}\ndescription: {agent_name} agent\nrole: {role}\n---\n\n# {agent_name}\n"
        )

    docs = core / "docs"
    docs.mkdir()
    (docs / "agent-matching.md").write_text(
        "# Agent-Matching Algorithm\n\nCanonical matching spec for tests.\n"
    )
    # Methodology docs bundled into every preset (#97); project.md must NOT ship.
    for _doc in [
        "tdd.md",
        "root-cause-tracing.md",
        "subagent-development.md",
        "parallel-agents.md",
    ]:
        (docs / _doc).write_text(f"# {_doc}\n\nMethodology doc for tests.\n")
    (docs / "project.md").write_text(
        "# Project\n\nProject-specific — must not ship in a preset.\n"
    )

    (core / "settings-base.json").write_text(json.dumps({
        "hooks": {
            "PreToolUse": [{"matcher": "Edit|Write", "hooks": [
                {"type": "command", "command": 'python3 "$CLAUDE_PLUGIN_ROOT"/hooks/scripts/protect-files.py'}
            ]}]
        }
    }))

    presets = tmp_path / "presets"
    presets.mkdir()

    preset = presets / "python-api"
    preset.mkdir()
    (preset / "manifest.json").write_text(json.dumps({
        "name": "python-api",
        "description": "Python backend services",
        "version": "1.0.0",
        "core": {"skills": "all", "hooks": ["protect-files.py"]},
        "exclude": [],
        "preset_skills": ["deploy"],
        "preset_hooks": ["post-edit-lint.py"],
    }))
    (preset / "settings-preset.json").write_text(json.dumps({
        "hooks": {
            "PostToolUse": [{"matcher": "Edit|Write", "hooks": [
                {"type": "command", "command": 'python3 "$CLAUDE_PLUGIN_ROOT"/hooks/scripts/post-edit-lint.py'}
            ]}]
        }
    }))

    preset_skills = preset / "skills"
    preset_skills.mkdir()
    deploy_skill = preset_skills / "deploy"
    deploy_skill.mkdir()
    (deploy_skill / "SKILL.md").write_text(
        "---\nname: deploy\ndescription: deploy skill\n---\n\n# deploy skill\n"
    )

    preset_hooks = preset / "hooks"
    preset_hooks.mkdir()
    (preset_hooks / "post-edit-lint.py").write_text("# lint hook")

    preset_agents = preset / "agents"
    preset_agents.mkdir()
    api_builder = preset_agents / "api-builder"
    api_builder.mkdir()
    (api_builder / "AGENT.md").write_text(
        "---\nname: api-builder\ndescription: Builds API endpoints\nrole: implementer\n---\n\n# API Builder\n"
    )

    (tmp_path / "dist").mkdir()

    return tmp_path


@pytest.fixture
def bad_manifest_repo(tmp_repo: Path) -> Path:
    """Create a repo with an invalid manifest (references nonexistent skill)."""
    preset = tmp_repo / "presets" / "broken"
    preset.mkdir()
    (preset / "manifest.json").write_text(json.dumps({
        "name": "broken",
        "description": "Broken preset for testing",
        "version": "0.1.0",
        "core": {"skills": "all", "hooks": ["protect-files.py"]},
        "exclude": [],
        "preset_skills": ["nonexistent-skill"],
        "preset_hooks": ["post-edit-lint.py"],
    }))
    (preset / "settings-preset.json").write_text(json.dumps({"hooks": {}}))

    preset_hooks = preset / "hooks"
    preset_hooks.mkdir()
    (preset_hooks / "post-edit-lint.py").write_text("# lint hook")

    return tmp_repo
