"""Tests for smoke_test.py -- validates internal consistency of built plugins."""

import json
from pathlib import Path

import pytest

from scripts.build_preset import build_preset
from scripts.smoke_test import smoke_test

REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_PRESETS = sorted(p.name for p in (REPO_ROOT / "presets").iterdir() if p.is_dir())


class TestSmokeRealPresets:
    """Build and smoke-test every real preset against the actual core/+presets/ tree."""

    @pytest.mark.parametrize("preset_name", REAL_PRESETS)
    def test_real_preset_builds_and_passes_smoke_test(self, preset_name: str) -> None:
        dist_path = build_preset(preset_name, repo_root=REPO_ROOT)
        result = smoke_test(dist_path)
        assert result.passed, f"{preset_name} smoke test failed: {result.errors}"


class TestSmokePluginJson:
    """Smoke test validates .claude-plugin/plugin.json."""

    def test_valid_build_passes_smoke_test(self, tmp_repo: Path) -> None:
        build_preset("python-api", repo_root=tmp_repo)
        dist = tmp_repo / "dist" / "python-api"
        result = smoke_test(dist)
        assert result.passed is True
        assert len(result.errors) == 0

    def test_missing_plugin_json_fails(self, tmp_repo: Path) -> None:
        build_preset("python-api", repo_root=tmp_repo)
        dist = tmp_repo / "dist" / "python-api"

        (dist / ".claude-plugin" / "plugin.json").unlink()

        result = smoke_test(dist)
        assert result.passed is False
        assert any("plugin.json" in e for e in result.errors)

    def test_plugin_json_missing_name_fails(self, tmp_repo: Path) -> None:
        build_preset("python-api", repo_root=tmp_repo)
        dist = tmp_repo / "dist" / "python-api"

        plugin_json = dist / ".claude-plugin" / "plugin.json"
        data = json.loads(plugin_json.read_text())
        del data["name"]
        plugin_json.write_text(json.dumps(data))

        result = smoke_test(dist)
        assert result.passed is False
        assert any("name" in e for e in result.errors)

    def test_plugin_json_missing_version_fails(self, tmp_repo: Path) -> None:
        build_preset("python-api", repo_root=tmp_repo)
        dist = tmp_repo / "dist" / "python-api"

        plugin_json = dist / ".claude-plugin" / "plugin.json"
        data = json.loads(plugin_json.read_text())
        del data["version"]
        plugin_json.write_text(json.dumps(data))

        result = smoke_test(dist)
        assert result.passed is False
        assert any("version" in e for e in result.errors)

    def test_plugin_json_missing_description_fails(self, tmp_repo: Path) -> None:
        build_preset("python-api", repo_root=tmp_repo)
        dist = tmp_repo / "dist" / "python-api"

        plugin_json = dist / ".claude-plugin" / "plugin.json"
        data = json.loads(plugin_json.read_text())
        del data["description"]
        plugin_json.write_text(json.dumps(data))

        result = smoke_test(dist)
        assert result.passed is False
        assert any("description" in e for e in result.errors)


class TestSmokeSkills:
    """Smoke test validates skill structure."""

    def test_skill_with_skill_md_passes(self, tmp_repo: Path) -> None:
        build_preset("python-api", repo_root=tmp_repo)
        dist = tmp_repo / "dist" / "python-api"
        result = smoke_test(dist)
        assert result.passed is True

    def test_skill_directory_missing_skill_md_fails(self, tmp_repo: Path) -> None:
        build_preset("python-api", repo_root=tmp_repo)
        dist = tmp_repo / "dist" / "python-api"

        # Remove SKILL.md from one skill
        (dist / "skills" / "commit" / "SKILL.md").unlink()

        result = smoke_test(dist)
        assert result.passed is False
        assert any("commit" in e and "SKILL.md" in e for e in result.errors)


class TestSmokeAgents:
    """Smoke test validates agent integrity."""

    def test_valid_agents_pass(self, tmp_repo: Path) -> None:
        build_preset("python-api", repo_root=tmp_repo)
        dist = tmp_repo / "dist" / "python-api"
        result = smoke_test(dist)
        assert result.passed

    def test_agent_missing_agent_md_fails(self, tmp_repo: Path) -> None:
        build_preset("python-api", repo_root=tmp_repo)
        dist = tmp_repo / "dist" / "python-api"

        (dist / "agents" / "tdd-implementer" / "AGENT.md").unlink()

        result = smoke_test(dist)
        assert not result.passed
        assert any("tdd-implementer" in e and "AGENT.md" in e for e in result.errors)

    def test_missing_frontmatter_fails(self, tmp_repo: Path) -> None:
        build_preset("python-api", repo_root=tmp_repo)
        dist = tmp_repo / "dist" / "python-api"
        agent_md = dist / "agents" / "tdd-implementer" / "AGENT.md"
        agent_md.write_text("# No frontmatter here\n")
        result = smoke_test(dist)
        assert not result.passed
        assert any(
            "frontmatter" in e.lower() or "required" in e.lower() for e in result.errors
        )

    def test_invalid_role_fails(self, tmp_repo: Path) -> None:
        build_preset("python-api", repo_root=tmp_repo)
        dist = tmp_repo / "dist" / "python-api"
        agent_md = dist / "agents" / "tdd-implementer" / "AGENT.md"
        agent_md.write_text(
            "---\nname: tdd-implementer\ndescription: test\nrole: invalid\n---\n"
        )
        result = smoke_test(dist)
        assert not result.passed
        assert any("role" in e for e in result.errors)

    def test_non_implementer_role_accepted(self, tmp_repo: Path) -> None:
        build_preset("python-api", repo_root=tmp_repo)
        dist = tmp_repo / "dist" / "python-api"
        agent_md = dist / "agents" / "tdd-implementer" / "AGENT.md"
        agent_md.write_text(
            "---\nname: tdd-implementer\ndescription: test\nrole: analyst\n---\n"
        )
        result = smoke_test(dist)
        assert not any("role" in e for e in result.errors)

    def test_name_mismatch_fails(self, tmp_repo: Path) -> None:
        build_preset("python-api", repo_root=tmp_repo)
        dist = tmp_repo / "dist" / "python-api"
        agent_md = dist / "agents" / "tdd-implementer" / "AGENT.md"
        agent_md.write_text(
            "---\nname: wrong-name\ndescription: test\nrole: implementer\n---\n"
        )
        result = smoke_test(dist)
        assert not result.passed
        assert any("name" in e and "match" in e for e in result.errors)

    def test_missing_skill_reference_fails(self, tmp_repo: Path) -> None:
        build_preset("python-api", repo_root=tmp_repo)
        dist = tmp_repo / "dist" / "python-api"
        agent_md = dist / "agents" / "tdd-implementer" / "AGENT.md"
        agent_md.write_text(
            "---\nname: tdd-implementer\ndescription: test\nrole: implementer\n"
            "skills:\n  add: [nonexistent-skill]\n---\n"
        )
        result = smoke_test(dist)
        assert not result.passed
        assert any("nonexistent-skill" in e for e in result.errors)


class TestSmokeHooks:
    """Smoke test validates hook references."""

    def test_valid_hooks_pass(self, tmp_repo: Path) -> None:
        build_preset("python-api", repo_root=tmp_repo)
        dist = tmp_repo / "dist" / "python-api"
        result = smoke_test(dist)
        assert result.passed

    def test_hooks_json_refs_missing_script_fails(self, tmp_repo: Path) -> None:
        build_preset("python-api", repo_root=tmp_repo)
        dist = tmp_repo / "dist" / "python-api"

        # Remove a hook script that hooks.json references
        (dist / "hooks" / "scripts" / "protect-files.py").unlink()

        result = smoke_test(dist)
        assert result.passed is False
        assert any("protect-files.py" in e for e in result.errors)


class TestSmokeIntraSkillLinks:
    """Smoke test validates intra-skill reference links."""

    def test_valid_intra_skill_link_passes(self, tmp_repo: Path) -> None:
        build_preset("python-api", repo_root=tmp_repo)
        dist = tmp_repo / "dist" / "python-api"

        # Add a skill with a valid reference link
        skill_dir = dist / "skills" / "test-skill"
        skill_dir.mkdir(parents=True)
        refs_dir = skill_dir / "references"
        refs_dir.mkdir()
        (refs_dir / "guide.md").write_text("# Guide\n")
        (skill_dir / "SKILL.md").write_text(
            "---\nname: test\ndescription: test\n---\n\n"
            "See [guide](references/guide.md) for details.\n"
        )

        result = smoke_test(dist)
        assert result.passed is True

    def test_broken_intra_skill_link_fails(self, tmp_repo: Path) -> None:
        build_preset("python-api", repo_root=tmp_repo)
        dist = tmp_repo / "dist" / "python-api"

        # Add a skill with a broken reference link
        skill_dir = dist / "skills" / "test-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: test\ndescription: test\n---\n\n"
            "See [missing](references/nonexistent.md) for details.\n"
        )

        result = smoke_test(dist)
        assert result.passed is False
        assert any(
            "test-skill/SKILL.md" in e and "nonexistent.md" in e for e in result.errors
        )

    def test_external_links_skipped(self, tmp_repo: Path) -> None:
        build_preset("python-api", repo_root=tmp_repo)
        dist = tmp_repo / "dist" / "python-api"

        skill_dir = dist / "skills" / "test-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: test\ndescription: test\n---\n\n"
            "See [docs](https://example.com) and [section](#anchor) for details.\n"
        )

        result = smoke_test(dist)
        assert result.passed is True

    def test_http_links_skipped(self, tmp_repo: Path) -> None:
        build_preset("python-api", repo_root=tmp_repo)
        dist = tmp_repo / "dist" / "python-api"

        skill_dir = dist / "skills" / "test-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: test\ndescription: test\n---\n\n"
            "See [docs](http://example.com) for details.\n"
        )

        result = smoke_test(dist)
        assert result.passed is True

    def test_project_root_relative_links_skipped(self, tmp_repo: Path) -> None:
        """Links to .claude/ paths are project-root-relative, not plugin-internal."""
        build_preset("python-api", repo_root=tmp_repo)
        dist = tmp_repo / "dist" / "python-api"

        skill_dir = dist / "skills" / "test-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: test\ndescription: test\n---\n\n"
            "See [project.md](.claude/docs/project.md) for details.\n"
        )

        result = smoke_test(dist)
        assert result.passed is True


class TestSmokeSettingsJson:
    """Smoke test validates settings.json."""

    def test_valid_settings_json_passes(self, tmp_repo: Path) -> None:
        build_preset("python-api", repo_root=tmp_repo)
        dist = tmp_repo / "dist" / "python-api"
        result = smoke_test(dist)
        assert result.passed

    def test_invalid_settings_json_fails(self, tmp_repo: Path) -> None:
        build_preset("python-api", repo_root=tmp_repo)
        dist = tmp_repo / "dist" / "python-api"

        (dist / "settings.json").write_text("not valid json {{{")

        result = smoke_test(dist)
        assert result.passed is False
        assert any("settings.json" in e for e in result.errors)
