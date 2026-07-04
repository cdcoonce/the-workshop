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

    def test_skill_missing_frontmatter_fails(self, tmp_repo: Path) -> None:
        build_preset("python-api", repo_root=tmp_repo)
        dist = tmp_repo / "dist" / "python-api"
        skill_md = dist / "skills" / "commit" / "SKILL.md"

        skill_md.write_text("# No frontmatter here\n")

        result = smoke_test(dist)
        assert result.passed is False
        assert any("commit/SKILL.md" in e and "frontmatter" in e for e in result.errors)

    def test_skill_missing_name_fails(self, tmp_repo: Path) -> None:
        build_preset("python-api", repo_root=tmp_repo)
        dist = tmp_repo / "dist" / "python-api"
        skill_md = dist / "skills" / "commit" / "SKILL.md"

        skill_md.write_text("---\ndescription: test\n---\n# Missing name\n")

        result = smoke_test(dist)
        assert result.passed is False
        assert any("commit/SKILL.md" in e and "name" in e for e in result.errors)

    def test_skill_missing_description_fails(self, tmp_repo: Path) -> None:
        build_preset("python-api", repo_root=tmp_repo)
        dist = tmp_repo / "dist" / "python-api"
        skill_md = dist / "skills" / "commit" / "SKILL.md"

        skill_md.write_text("---\nname: commit\n---\n# Missing description\n")

        result = smoke_test(dist)
        assert result.passed is False
        assert any("commit/SKILL.md" in e and "description" in e for e in result.errors)

    def test_skill_with_frontmatter_passes(self, tmp_repo: Path) -> None:
        build_preset("python-api", repo_root=tmp_repo)
        dist = tmp_repo / "dist" / "python-api"
        skill_md = dist / "skills" / "commit" / "SKILL.md"

        skill_md.write_text("---\nname: commit\ndescription: test\n---\n# Valid\n")

        result = smoke_test(dist)
        assert not any("commit/SKILL.md" in e for e in result.errors)

    def test_skill_with_folded_description_passes(self, tmp_repo: Path) -> None:
        build_preset("python-api", repo_root=tmp_repo)
        dist = tmp_repo / "dist" / "python-api"
        skill_md = dist / "skills" / "commit" / "SKILL.md"

        skill_md.write_text(
            "---\n"
            "name: commit\n"
            "description: >\n"
            "  A folded block scalar description that spans\n"
            "  multiple lines and even contains a colon: like this.\n"
            "---\n# Valid\n"
        )

        result = smoke_test(dist)
        assert not any("commit/SKILL.md" in e for e in result.errors)


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

    def test_mailto_links_skipped(self, tmp_repo: Path) -> None:
        """mailto: links are a URI scheme, not a relative file path."""
        build_preset("python-api", repo_root=tmp_repo)
        dist = tmp_repo / "dist" / "python-api"

        skill_dir = dist / "skills" / "test-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: test\ndescription: test\n---\n\n"
            "Contact [support](mailto:support@example.com) for help.\n"
        )

        result = smoke_test(dist)
        assert result.passed is True

    def test_broken_link_inside_fenced_code_block_skipped(self, tmp_repo: Path) -> None:
        """Illustrative example links inside ``` fences are not real references."""
        build_preset("python-api", repo_root=tmp_repo)
        dist = tmp_repo / "dist" / "python-api"

        skill_dir = dist / "skills" / "test-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: test\ndescription: test\n---\n\n"
            "```markdown\n"
            "See [example](references/nonexistent.md) for details.\n"
            "```\n"
        )

        result = smoke_test(dist)
        assert result.passed is True

    def test_broken_link_outside_fenced_code_block_fails(self, tmp_repo: Path) -> None:
        """The same link text outside a fence is still checked and still fails."""
        build_preset("python-api", repo_root=tmp_repo)
        dist = tmp_repo / "dist" / "python-api"

        skill_dir = dist / "skills" / "test-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: test\ndescription: test\n---\n\n"
            "See [example](references/nonexistent.md) for details.\n"
        )

        result = smoke_test(dist)
        assert result.passed is False
        assert any(
            "test-skill/SKILL.md" in e and "nonexistent.md" in e for e in result.errors
        )

    def test_anchored_cross_doc_link_passes(self, tmp_repo: Path) -> None:
        """A link with a #fragment resolves against the file portion only."""
        build_preset("python-api", repo_root=tmp_repo)
        dist = tmp_repo / "dist" / "python-api"

        skill_dir = dist / "skills" / "test-skill"
        skill_dir.mkdir(parents=True)
        refs_dir = skill_dir / "references"
        refs_dir.mkdir()
        (refs_dir / "guide.md").write_text("# Guide\n")
        (skill_dir / "SKILL.md").write_text(
            "---\nname: test\ndescription: test\n---\n\n"
            "See [guide](references/guide.md#section) for details.\n"
        )

        result = smoke_test(dist)
        assert result.passed is True

    def test_anchored_link_to_missing_file_fails(self, tmp_repo: Path) -> None:
        """The #fragment doesn't hide a missing file portion."""
        build_preset("python-api", repo_root=tmp_repo)
        dist = tmp_repo / "dist" / "python-api"

        skill_dir = dist / "skills" / "test-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: test\ndescription: test\n---\n\n"
            "See [missing](references/nonexistent.md#section) for details.\n"
        )

        result = smoke_test(dist)
        assert result.passed is False
        assert any(
            "test-skill/SKILL.md" in e and "nonexistent.md" in e for e in result.errors
        )


class TestSmokeIntraAgentLinks:
    """Smoke test validates intra-agent reference links."""

    def test_valid_intra_agent_link_passes(self, tmp_repo: Path) -> None:
        build_preset("python-api", repo_root=tmp_repo)
        dist = tmp_repo / "dist" / "python-api"

        # Add an agent with a valid reference link
        agent_dir = dist / "agents" / "test-agent"
        agent_dir.mkdir(parents=True)
        refs_dir = agent_dir / "references"
        refs_dir.mkdir()
        (refs_dir / "spec.md").write_text("# Spec\n")
        (agent_dir / "AGENT.md").write_text(
            "---\nname: test-agent\ndescription: test\nrole: implementer\n---\n\n"
            "See [spec](references/spec.md) for details.\n"
        )

        result = smoke_test(dist)
        assert result.passed is True

    def test_broken_intra_agent_link_fails(self, tmp_repo: Path) -> None:
        build_preset("python-api", repo_root=tmp_repo)
        dist = tmp_repo / "dist" / "python-api"

        # Add an agent with a broken reference link
        agent_dir = dist / "agents" / "test-agent"
        agent_dir.mkdir(parents=True)
        (agent_dir / "AGENT.md").write_text(
            "---\nname: test-agent\ndescription: test\nrole: implementer\n---\n\n"
            "See [missing](references/nonexistent.md) for details.\n"
        )

        result = smoke_test(dist)
        assert result.passed is False
        assert any(
            "test-agent/AGENT.md" in e and "nonexistent.md" in e for e in result.errors
        )

    def test_anchored_cross_doc_link_passes(self, tmp_repo: Path) -> None:
        """A link with a #fragment resolves against the file portion only."""
        build_preset("python-api", repo_root=tmp_repo)
        dist = tmp_repo / "dist" / "python-api"

        agent_dir = dist / "agents" / "test-agent"
        agent_dir.mkdir(parents=True)
        refs_dir = agent_dir / "references"
        refs_dir.mkdir()
        (refs_dir / "spec.md").write_text("# Spec\n")
        (agent_dir / "AGENT.md").write_text(
            "---\nname: test-agent\ndescription: test\nrole: implementer\n---\n\n"
            "See [spec](references/spec.md#section) for details.\n"
        )

        result = smoke_test(dist)
        assert result.passed is True

    def test_external_links_skipped(self, tmp_repo: Path) -> None:
        build_preset("python-api", repo_root=tmp_repo)
        dist = tmp_repo / "dist" / "python-api"

        agent_dir = dist / "agents" / "test-agent"
        agent_dir.mkdir(parents=True)
        (agent_dir / "AGENT.md").write_text(
            "---\nname: test-agent\ndescription: test\nrole: implementer\n---\n\n"
            "See [docs](https://example.com) and [section](#anchor) for details.\n"
        )

        result = smoke_test(dist)
        assert result.passed is True

    def test_http_links_skipped(self, tmp_repo: Path) -> None:
        build_preset("python-api", repo_root=tmp_repo)
        dist = tmp_repo / "dist" / "python-api"

        agent_dir = dist / "agents" / "test-agent"
        agent_dir.mkdir(parents=True)
        (agent_dir / "AGENT.md").write_text(
            "---\nname: test-agent\ndescription: test\nrole: implementer\n---\n\n"
            "See [docs](http://example.com) for details.\n"
        )

        result = smoke_test(dist)
        assert result.passed is True

    def test_project_root_relative_links_skipped(self, tmp_repo: Path) -> None:
        """Links to .claude/ paths are project-root-relative, not plugin-internal."""
        build_preset("python-api", repo_root=tmp_repo)
        dist = tmp_repo / "dist" / "python-api"

        agent_dir = dist / "agents" / "test-agent"
        agent_dir.mkdir(parents=True)
        (agent_dir / "AGENT.md").write_text(
            "---\nname: test-agent\ndescription: test\nrole: implementer\n---\n\n"
            "See [project.md](.claude/docs/project.md) for details.\n"
        )

        result = smoke_test(dist)
        assert result.passed is True

    def test_mailto_links_skipped(self, tmp_repo: Path) -> None:
        """mailto: links are a URI scheme, not a relative file path."""
        build_preset("python-api", repo_root=tmp_repo)
        dist = tmp_repo / "dist" / "python-api"

        agent_dir = dist / "agents" / "test-agent"
        agent_dir.mkdir(parents=True)
        (agent_dir / "AGENT.md").write_text(
            "---\nname: test-agent\ndescription: test\nrole: implementer\n---\n\n"
            "Contact [support](mailto:support@example.com) for help.\n"
        )

        result = smoke_test(dist)
        assert result.passed is True


def _write_valid_plugin_json(dist: Path) -> None:
    """Write a minimal valid .claude-plugin/plugin.json into ``dist``.

    Lets a hand-built dist tree clear the plugin.json validation gate so a test
    can exercise a later error branch (agents, hooks) without early-returning.
    """
    plugin_dir = dist / ".claude-plugin"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.json").write_text(
        json.dumps({"name": "demo", "version": "1.0.0", "description": "demo"})
    )


class TestSmokeMalformedInputs:
    """Smoke test reports malformed JSON and structurally invalid agents.

    Each test builds its own minimal dist tree under tmp_path so the corrupted
    input is the only variable, independent of any real preset's contents.
    """

    def test_invalid_plugin_json_fails(self, tmp_path: Path) -> None:
        plugin_dir = tmp_path / ".claude-plugin"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "plugin.json").write_text("{ not valid json")

        result = smoke_test(tmp_path)
        assert result.passed is False
        assert any("plugin.json is not valid JSON" in e for e in result.errors)

    def test_agent_directory_without_agent_md_fails(self, tmp_path: Path) -> None:
        _write_valid_plugin_json(tmp_path)
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        # A stray non-directory entry is skipped; the real agent directory has
        # no AGENT.md and must be reported.
        (agents_dir / "README.md").write_text("# not an agent\n")
        (agents_dir / "lonely-agent").mkdir()

        result = smoke_test(tmp_path)
        assert result.passed is False
        assert any("lonely-agent" in e and "no AGENT.md" in e for e in result.errors)

    def test_agent_md_missing_required_field_fails(self, tmp_path: Path) -> None:
        _write_valid_plugin_json(tmp_path)
        agent_dir = tmp_path / "agents" / "demo-agent"
        agent_dir.mkdir(parents=True)
        # Valid frontmatter, but the required ``role`` field is absent.
        (agent_dir / "AGENT.md").write_text(
            "---\nname: demo-agent\ndescription: test\n---\n\n# Demo\n"
        )

        result = smoke_test(tmp_path)
        assert result.passed is False
        assert any("missing required field" in e and "role" in e for e in result.errors)

    def test_invalid_hooks_json_fails(self, tmp_path: Path) -> None:
        _write_valid_plugin_json(tmp_path)
        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir()
        (hooks_dir / "hooks.json").write_text("{ not valid json")

        result = smoke_test(tmp_path)
        assert result.passed is False
        assert any("hooks/hooks.json is not valid JSON" in e for e in result.errors)


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
