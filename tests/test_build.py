"""Tests for build_preset.py — verifies plugin-format output assembly."""

import json
from pathlib import Path

from scripts.build_preset import build_preset


class TestBuildPluginStructure:
    """Build produces correct plugin output structure."""

    def test_build_creates_dist_directory(self, tmp_repo: Path) -> None:
        build_preset("python-api", repo_root=tmp_repo)
        dist = tmp_repo / "dist" / "python-api"
        assert dist.exists()

    def test_build_creates_plugin_json(self, tmp_repo: Path) -> None:
        build_preset("python-api", repo_root=tmp_repo)
        plugin_json = (
            tmp_repo / "dist" / "python-api" / ".claude-plugin" / "plugin.json"
        )
        assert plugin_json.exists()
        data = json.loads(plugin_json.read_text())
        assert data["name"] == "python-api"
        assert data["version"] == "1.0.0"
        assert data["description"] == "Python backend services"

    def test_build_creates_codex_plugin_json(self, tmp_repo: Path) -> None:
        build_preset("python-api", repo_root=tmp_repo)
        plugin_json = tmp_repo / "dist" / "python-api" / ".codex-plugin" / "plugin.json"
        assert plugin_json.exists()
        data = json.loads(plugin_json.read_text())
        assert data["name"] == "python-api"
        assert data["version"] == "1.0.0"
        assert data["description"] == "Python backend services"
        assert data["author"] == {"name": "Charles Coonce"}
        assert data["skills"] == "./skills/"
        assert data["interface"]["developerName"] == "Charles Coonce"

    def test_build_no_claude_subdir(self, tmp_repo: Path) -> None:
        """Plugin format must not contain a .claude/ subdirectory."""
        build_preset("python-api", repo_root=tmp_repo)
        claude_dir = tmp_repo / "dist" / "python-api" / ".claude"
        assert not claude_dir.exists()

    def test_build_no_claude_md(self, tmp_repo: Path) -> None:
        """Plugin format must not contain CLAUDE.md."""
        build_preset("python-api", repo_root=tmp_repo)
        claude_md = tmp_repo / "dist" / "python-api" / "CLAUDE.md"
        assert not claude_md.exists()

    def test_build_no_template_version(self, tmp_repo: Path) -> None:
        """Plugin format must not contain .template-version."""
        build_preset("python-api", repo_root=tmp_repo)
        dist = tmp_repo / "dist" / "python-api"
        assert not (dist / ".template-version").exists()
        assert not (dist / ".claude" / ".template-version").exists()

    def test_build_no_agent_role_defaults(self, tmp_repo: Path) -> None:
        """Plugin format must not contain agent-role-defaults.json."""
        build_preset("python-api", repo_root=tmp_repo)
        dist = tmp_repo / "dist" / "python-api"
        assert not (dist / "agent-role-defaults.json").exists()
        assert not (dist / ".claude" / "agent-role-defaults.json").exists()


class TestBuildPluginSkills:
    """Skills are placed at root level in plugin format."""

    def test_build_copies_core_skills_to_root(self, tmp_repo: Path) -> None:
        build_preset("python-api", repo_root=tmp_repo)
        skills = tmp_repo / "dist" / "python-api" / "skills"
        assert (skills / "commit" / "SKILL.md").exists()
        assert (skills / "daa-code-review" / "SKILL.md").exists()
        assert (skills / "tdd" / "SKILL.md").exists()

    def test_build_copies_preset_skills_to_root(self, tmp_repo: Path) -> None:
        build_preset("python-api", repo_root=tmp_repo)
        skills = tmp_repo / "dist" / "python-api" / "skills"
        assert (skills / "deploy" / "SKILL.md").exists()

    def test_build_copies_specific_core_skills(self, tmp_repo: Path) -> None:
        """core.skills as a list copies exactly the named core skills."""
        manifest_path = tmp_repo / "presets" / "python-api" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["core"]["skills"] = ["commit", "tdd"]
        manifest_path.write_text(json.dumps(manifest))

        build_preset("python-api", repo_root=tmp_repo)
        skills = tmp_repo / "dist" / "python-api" / "skills"
        assert (skills / "commit" / "SKILL.md").exists()
        assert (skills / "tdd" / "SKILL.md").exists()
        assert not (skills / "daa-code-review").exists()

    def test_preset_skill_overrides_core(self, tmp_repo: Path) -> None:
        override = tmp_repo / "presets" / "python-api" / "skills" / "tdd"
        override.mkdir()
        (override / "SKILL.md").write_text("# OVERRIDDEN tdd skill")

        manifest_path = tmp_repo / "presets" / "python-api" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["preset_skills"].append("tdd")
        manifest_path.write_text(json.dumps(manifest))

        build_preset("python-api", repo_root=tmp_repo)
        skill_md = tmp_repo / "dist" / "python-api" / "skills" / "tdd" / "SKILL.md"
        assert "OVERRIDDEN" in skill_md.read_text()


class TestBuildPluginAgents:
    """Agents are placed at root level in plugin format."""

    def test_build_copies_core_agents_to_root(self, tmp_repo: Path) -> None:
        build_preset("python-api", repo_root=tmp_repo)
        agents = tmp_repo / "dist" / "python-api" / "agents"
        assert (agents / "tdd-implementer" / "AGENT.md").exists()
        assert (agents / "code-reviewer" / "AGENT.md").exists()

    def test_build_copies_core_agents_default_all(self, tmp_repo: Path) -> None:
        """core.agents defaults to 'all' when omitted."""
        build_preset("python-api", repo_root=tmp_repo)
        agents = tmp_repo / "dist" / "python-api" / "agents"
        assert (agents / "tdd-implementer" / "AGENT.md").exists()
        assert (agents / "code-reviewer" / "AGENT.md").exists()

    def test_build_copies_specific_core_agents(self, tmp_repo: Path) -> None:
        manifest_path = tmp_repo / "presets" / "python-api" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["core"]["agents"] = ["tdd-implementer"]
        manifest_path.write_text(json.dumps(manifest))

        build_preset("python-api", repo_root=tmp_repo)
        agents = tmp_repo / "dist" / "python-api" / "agents"
        assert (agents / "tdd-implementer" / "AGENT.md").exists()
        assert not (agents / "code-reviewer").exists()

    def test_build_copies_preset_agents(self, tmp_repo: Path) -> None:
        manifest_path = tmp_repo / "presets" / "python-api" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["preset_agents"] = ["api-builder"]
        manifest_path.write_text(json.dumps(manifest))

        build_preset("python-api", repo_root=tmp_repo)
        agents = tmp_repo / "dist" / "python-api" / "agents"
        assert (agents / "api-builder" / "AGENT.md").exists()

    def test_preset_agent_overrides_core(self, tmp_repo: Path) -> None:
        override_dir = (
            tmp_repo / "presets" / "python-api" / "agents" / "tdd-implementer"
        )
        override_dir.mkdir(parents=True, exist_ok=True)
        (override_dir / "AGENT.md").write_text(
            "---\nname: tdd-implementer\nrole: implementer\n---\n\n# OVERRIDDEN\n"
        )

        manifest_path = tmp_repo / "presets" / "python-api" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["preset_agents"] = ["tdd-implementer"]
        manifest_path.write_text(json.dumps(manifest))

        build_preset("python-api", repo_root=tmp_repo)
        agent_md = (
            tmp_repo / "dist" / "python-api" / "agents" / "tdd-implementer" / "AGENT.md"
        )
        assert "OVERRIDDEN" in agent_md.read_text()

    def test_build_skips_agents_when_dir_missing(self, tmp_repo: Path) -> None:
        import shutil

        shutil.rmtree(tmp_repo / "core" / "agents")
        build_preset("python-api", repo_root=tmp_repo)
        agents = tmp_repo / "dist" / "python-api" / "agents"
        assert not agents.exists()

    def test_preset_agents_defaults_empty(self, tmp_repo: Path) -> None:
        build_preset("python-api", repo_root=tmp_repo)
        agents = tmp_repo / "dist" / "python-api" / "agents"
        assert (agents / "tdd-implementer").exists()
        assert (agents / "code-reviewer").exists()
        assert not (agents / "api-builder").exists()


class TestBuildPluginDocs:
    """agent-matching.md is copied into docs/ for every preset."""

    def test_build_copies_agent_matching_doc(self, tmp_repo: Path) -> None:
        build_preset("python-api", repo_root=tmp_repo)
        doc = tmp_repo / "dist" / "python-api" / "docs" / "agent-matching.md"
        assert doc.exists()

    def test_build_agent_matching_doc_has_content(self, tmp_repo: Path) -> None:
        build_preset("python-api", repo_root=tmp_repo)
        doc = tmp_repo / "dist" / "python-api" / "docs" / "agent-matching.md"
        assert doc.read_text().strip() != ""

    def test_build_skips_docs_when_agent_matching_missing(self, tmp_repo: Path) -> None:
        """No docs/ dir when source agent-matching.md is absent."""
        (tmp_repo / "core" / "docs" / "agent-matching.md").unlink()
        build_preset("python-api", repo_root=tmp_repo)
        docs_dir = tmp_repo / "dist" / "python-api" / "docs"
        assert not docs_dir.exists()

    def test_build_no_claude_subdir_in_docs(self, tmp_repo: Path) -> None:
        """docs/ must not be nested under .claude/ in plugin format."""
        build_preset("python-api", repo_root=tmp_repo)
        dist = tmp_repo / "dist" / "python-api"
        assert not (dist / ".claude").exists()


class TestBuildPluginHooks:
    """Hook scripts go to hooks/scripts/, hook config goes to hooks/hooks.json."""

    def test_build_copies_core_hook_scripts(self, tmp_repo: Path) -> None:
        build_preset("python-api", repo_root=tmp_repo)
        scripts_dir = tmp_repo / "dist" / "python-api" / "hooks" / "scripts"
        assert (scripts_dir / "protect-files.py").exists()

    def test_build_copies_preset_hook_scripts(self, tmp_repo: Path) -> None:
        build_preset("python-api", repo_root=tmp_repo)
        scripts_dir = tmp_repo / "dist" / "python-api" / "hooks" / "scripts"
        assert (scripts_dir / "post-edit-lint.py").exists()

    def test_build_creates_hooks_json(self, tmp_repo: Path) -> None:
        build_preset("python-api", repo_root=tmp_repo)
        hooks_json = tmp_repo / "dist" / "python-api" / "hooks" / "hooks.json"
        assert hooks_json.exists()
        data = json.loads(hooks_json.read_text())
        assert "hooks" in data

    def test_hooks_json_has_rewritten_paths(self, tmp_repo: Path) -> None:
        """Hook commands reference hooks/scripts/ not .claude/hooks/."""
        build_preset("python-api", repo_root=tmp_repo)
        hooks_json = tmp_repo / "dist" / "python-api" / "hooks" / "hooks.json"
        data = json.loads(hooks_json.read_text())

        # Check PreToolUse hook command has rewritten path
        pre_hooks = data["hooks"]["PreToolUse"]
        assert len(pre_hooks) >= 1
        cmd = pre_hooks[0]["hooks"][0]["command"]
        assert "hooks/scripts/protect-files.py" in cmd
        assert ".claude/hooks/" not in cmd

    def test_hooks_json_uses_plugin_root(self, tmp_repo: Path) -> None:
        """Hook commands use $CLAUDE_PLUGIN_ROOT."""
        build_preset("python-api", repo_root=tmp_repo)
        hooks_json = tmp_repo / "dist" / "python-api" / "hooks" / "hooks.json"
        data = json.loads(hooks_json.read_text())

        pre_hooks = data["hooks"]["PreToolUse"]
        cmd = pre_hooks[0]["hooks"][0]["command"]
        assert "$CLAUDE_PLUGIN_ROOT" in cmd

    def test_hooks_json_includes_preset_hooks(self, tmp_repo: Path) -> None:
        """Merged hooks from preset appear in hooks.json."""
        build_preset("python-api", repo_root=tmp_repo)
        hooks_json = tmp_repo / "dist" / "python-api" / "hooks" / "hooks.json"
        data = json.loads(hooks_json.read_text())

        assert "PostToolUse" in data["hooks"]
        post_hooks = data["hooks"]["PostToolUse"]
        assert len(post_hooks) >= 1
        cmd = post_hooks[0]["hooks"][0]["command"]
        assert "hooks/scripts/post-edit-lint.py" in cmd


class TestBuildPluginSettings:
    """Settings at root level without hooks section."""

    def test_build_creates_root_settings(self, tmp_repo: Path) -> None:
        build_preset("python-api", repo_root=tmp_repo)
        settings = tmp_repo / "dist" / "python-api" / "settings.json"
        assert settings.exists()

    def test_settings_has_no_hooks(self, tmp_repo: Path) -> None:
        """Settings at root should not contain hooks (they are in hooks.json)."""
        build_preset("python-api", repo_root=tmp_repo)
        settings = tmp_repo / "dist" / "python-api" / "settings.json"
        data = json.loads(settings.read_text())
        assert "hooks" not in data


class TestBuildPluginReadme:
    """README.md is generated with plugin info."""

    def test_build_creates_readme(self, tmp_repo: Path) -> None:
        build_preset("python-api", repo_root=tmp_repo)
        readme = tmp_repo / "dist" / "python-api" / "README.md"
        assert readme.exists()

    def test_readme_contains_plugin_name(self, tmp_repo: Path) -> None:
        build_preset("python-api", repo_root=tmp_repo)
        readme = tmp_repo / "dist" / "python-api" / "README.md"
        content = readme.read_text()
        assert "python-api" in content

    def test_readme_contains_description(self, tmp_repo: Path) -> None:
        build_preset("python-api", repo_root=tmp_repo)
        readme = tmp_repo / "dist" / "python-api" / "README.md"
        content = readme.read_text()
        assert "Python backend services" in content

    def test_readme_contains_claude_md_template_section(self, tmp_repo: Path) -> None:
        build_preset("python-api", repo_root=tmp_repo)
        readme = tmp_repo / "dist" / "python-api" / "README.md"
        content = readme.read_text()
        assert "## CLAUDE.md Template" in content

    def test_readme_claude_md_template_references_plugin_name(
        self, tmp_repo: Path
    ) -> None:
        build_preset("python-api", repo_root=tmp_repo)
        readme = tmp_repo / "dist" / "python-api" / "README.md"
        content = readme.read_text()
        # The template section should mention the plugin name
        template_start = content.index("## CLAUDE.md Template")
        template_section = content[template_start:]
        assert "python-api" in template_section

    def test_readme_claude_md_template_has_code_block(self, tmp_repo: Path) -> None:
        build_preset("python-api", repo_root=tmp_repo)
        readme = tmp_repo / "dist" / "python-api" / "README.md"
        content = readme.read_text()
        template_start = content.index("## CLAUDE.md Template")
        template_section = content[template_start:]
        assert "```" in template_section


class TestBuildExclusions:
    """Exclusions remove items from plugin output using root-level paths."""

    def test_exclude_removes_skill(self, tmp_repo: Path) -> None:
        manifest_path = tmp_repo / "presets" / "python-api" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["exclude"] = ["skills/tdd"]
        manifest_path.write_text(json.dumps(manifest))

        build_preset("python-api", repo_root=tmp_repo)
        skills = tmp_repo / "dist" / "python-api" / "skills"
        assert not (skills / "tdd").exists()
        assert (skills / "commit").exists()

    def test_exclude_removes_agent(self, tmp_repo: Path) -> None:
        manifest_path = tmp_repo / "presets" / "python-api" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["exclude"] = ["agents/tdd-implementer"]
        manifest_path.write_text(json.dumps(manifest))

        build_preset("python-api", repo_root=tmp_repo)
        agents = tmp_repo / "dist" / "python-api" / "agents"
        assert not (agents / "tdd-implementer").exists()
        assert (agents / "code-reviewer" / "AGENT.md").exists()

    def test_exclusion_path_containment(self, tmp_repo: Path) -> None:
        """Exclusion paths that escape dist_path are rejected."""
        manifest_path = tmp_repo / "presets" / "python-api" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["exclude"] = ["../../etc/passwd"]
        manifest_path.write_text(json.dumps(manifest))

        build_preset("python-api", repo_root=tmp_repo)
        assert (tmp_repo / "dist" / "python-api").exists()


class TestBuildPresetAgentValidation:
    """Validation for preset agents."""

    def test_validation_fails_missing_preset_agent(self, tmp_repo: Path) -> None:
        import pytest
        from scripts.build_preset import BuildValidationError

        manifest_path = tmp_repo / "presets" / "python-api" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["preset_agents"] = ["nonexistent-agent"]
        manifest_path.write_text(json.dumps(manifest))

        with pytest.raises(BuildValidationError, match="Preset agent not found"):
            build_preset("python-api", repo_root=tmp_repo)

    def test_validation_fails_missing_core_agent(self, tmp_repo: Path) -> None:
        import pytest
        from scripts.build_preset import BuildValidationError

        manifest_path = tmp_repo / "presets" / "python-api" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["core"]["agents"] = ["nonexistent-agent"]
        manifest_path.write_text(json.dumps(manifest))

        with pytest.raises(BuildValidationError, match="Core agent not found"):
            build_preset("python-api", repo_root=tmp_repo)

    def test_validation_catches_agent_in_both_preset_and_exclude(
        self, tmp_repo: Path
    ) -> None:
        import pytest
        from scripts.build_preset import BuildValidationError

        manifest_path = tmp_repo / "presets" / "python-api" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["preset_agents"] = ["api-builder"]
        manifest["exclude"] = ["agents/api-builder"]
        manifest_path.write_text(json.dumps(manifest))

        with pytest.raises(BuildValidationError, match="preset_agents and exclude"):
            build_preset("python-api", repo_root=tmp_repo)


class TestSettingsMerge:
    """Settings merge handles edge cases correctly."""

    def test_duplicate_hook_type_appends_in_hooks_json(self, tmp_repo: Path) -> None:
        """When base and preset both define PreToolUse, hooks.json appends them."""
        preset_settings = tmp_repo / "presets" / "python-api" / "settings-preset.json"
        preset_settings.write_text(
            json.dumps(
                {
                    "hooks": {
                        "PreToolUse": [{"matcher": "Bash", "hooks": []}],
                        "PostToolUse": [
                            {
                                "matcher": "Edit|Write",
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": 'python3 "$CLAUDE_PLUGIN_ROOT"/hooks/scripts/post-edit-lint.py',
                                    }
                                ],
                            }
                        ],
                    }
                }
            )
        )

        build_preset("python-api", repo_root=tmp_repo)
        hooks_json = tmp_repo / "dist" / "python-api" / "hooks" / "hooks.json"
        data = json.loads(hooks_json.read_text())

        assert len(data["hooks"]["PreToolUse"]) == 2
        assert data["hooks"]["PreToolUse"][0]["matcher"] == "Edit|Write"
        assert data["hooks"]["PreToolUse"][1]["matcher"] == "Bash"
