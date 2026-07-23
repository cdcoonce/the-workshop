"""Tests for build_preset.py — verifies plugin-format output assembly."""

import json
import os
from pathlib import Path
import subprocess

import pytest

from scripts.build_preset import BuildValidationError, _merge_settings, build_preset


def test_workbench_manifest_includes_gitlab_mr_create() -> None:
    """Workbench ships the GitLab MR creation guard."""
    repository_root = Path(__file__).resolve().parents[1]
    manifest_path = repository_root / "presets" / "workbench" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())

    assert "gitlab-mr-create" in manifest["preset_skills"]


def test_workbench_manifest_includes_gitlab_promotion_flow() -> None:
    """Workbench ships the GitLab integration/promotion policy skill."""
    repository_root = Path(__file__).resolve().parents[1]
    manifest_path = repository_root / "presets" / "workbench" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())

    assert "gitlab-promotion-flow" in manifest["preset_skills"]


def test_gitlab_promotion_flow_skill_source_exists() -> None:
    """The promotion-flow skill has a canonical SKILL.md in the workbench preset."""
    repository_root = Path(__file__).resolve().parents[1]
    skill = (
        repository_root
        / "presets/workbench/skills/gitlab-promotion-flow/SKILL.md"
    )

    assert skill.is_file()


def test_workshop_maintainer_ships_only_maintenance_skills() -> None:
    """Workshop maintenance tooling stays out of domain presets."""
    repository_root = Path(__file__).resolve().parents[1]
    maintainer = json.loads(
        (repository_root / "presets/workshop-maintainer/manifest.json").read_text()
    )
    vault_ops = json.loads(
        (repository_root / "presets/vault-ops/manifest.json").read_text()
    )

    assert maintainer["core"]["skills"] == [
        "using-workflow",
        "grill-me",
        "tdd",
        "commit",
        "daa-code-review",
    ]
    assert maintainer["core"]["agents"] == []
    assert maintainer["preset_skills"] == [
        "skill-inventory",
        "workshop-skill-creator",
        "improve-skill",
        "add-the-workshop-hook",
        "persona-builder",
    ]
    assert maintainer["preset_agents"] == [
        "skill-analyst",
        "qa-tester",
        "skill-writer",
        "strategy",
        "skill-builder",
        "skill-reviewer",
    ]
    assert vault_ops["core"]["skills"] == []


def test_maintenance_components_have_preset_only_ownership() -> None:
    """Maintenance components must not leak into the universal core."""
    repository_root = Path(__file__).resolve().parents[1]
    maintainer = repository_root / "presets/workshop-maintainer"
    workbench_manifest = json.loads(
        (repository_root / "presets/workbench/manifest.json").read_text()
    )

    maintenance_skills = {
        "workshop-skill-creator",
        "improve-skill",
        "add-the-workshop-hook",
        "persona-builder",
    }
    maintenance_agents = {
        "skill-analyst",
        "qa-tester",
        "skill-writer",
        "strategy",
        "skill-builder",
        "skill-reviewer",
    }

    assert not (repository_root / "core/skills/write-a-skill").exists()
    for skill_name in maintenance_skills:
        assert (maintainer / "skills" / skill_name / "SKILL.md").exists()
        assert not (repository_root / "core/skills" / skill_name).exists()
    for agent_name in maintenance_agents:
        assert (maintainer / "agents" / agent_name / "AGENT.md").exists()
        assert not (repository_root / "core/agents" / agent_name).exists()
        assert agent_name not in workbench_manifest["preset_agents"]


def test_gitlab_mr_guard_preserves_markdown_and_verifies(tmp_path: Path) -> None:
    """The guard owns MR metadata and checks GitLab's returned object."""
    repository_root = Path(__file__).resolve().parents[1]
    script_path = repository_root / "presets/workbench/skills/gitlab-mr-create/scripts/create-mr"
    description_path = tmp_path / "description.md"
    description_path.write_text("## Summary\n\n- Preserve Markdown line breaks\n")
    bin_path = tmp_path / "bin"
    bin_path.mkdir()
    arguments_path = tmp_path / "glab-arguments"
    (bin_path / "git").write_text(
        "#!/usr/bin/env bash\nprintf '%s\\n' 'fix(exports): sanitize standard template content'\n"
    )
    (bin_path / "glab").write_text(
        "#!/usr/bin/env bash\n"
        "if [[ $1 == mr && $2 == create ]]; then\n"
        f"  printf '%s\\n' \"$@\" > {arguments_path}\n"
        "  printf '%s\\n' 'https://gitlab.example/group/repo/-/merge_requests/83'\n"
        "else\n"
        "  printf '%s\\n' '{\"title\":\"fix(exports): sanitize standard template content\",\"description\":\"## Summary\\n\\n- Preserve Markdown line breaks\"}'\n"
        "fi\n"
    )
    for command in (bin_path / "git", bin_path / "glab"):
        command.chmod(0o755)

    environment = os.environ | {"PATH": f"{bin_path}:{os.environ['PATH']}"}
    result = subprocess.run(
        ["bash", str(script_path), str(description_path), "--yes"],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.endswith("title and Markdown description match.\n")
    assert arguments_path.read_text().splitlines() == [
        "mr", "create", "--title", "fix(exports): sanitize standard template content",
        "--description", "## Summary", "", "- Preserve Markdown line breaks", "--yes",
    ]


def write_persona_preset(tmp_repo: Path, settings: dict) -> Path:
    """Create a minimal persona preset for build tests."""
    preset = tmp_repo / "presets" / "persona"
    preset.mkdir()
    (preset / "manifest.json").write_text(
        json.dumps(
            {
                "name": "persona",
                "description": "Persona preset",
                "version": "1.0.0",
                "base_settings": False,
                "core": {"skills": [], "agents": [], "hooks": []},
                "exclude": [],
                "preset_skills": [],
                "preset_hooks": [],
                "preset_agents": [],
            }
        )
    )
    (preset / "settings-preset.json").write_text(json.dumps(settings))
    return preset


class TestMergeSettings:
    """_merge_settings must honor its full contract, not just hooks (#92)."""

    def test_carries_non_hook_keys_with_preset_override(self, tmp_path: Path) -> None:
        base = tmp_path / "base.json"
        base.write_text(json.dumps({"hooks": {}, "model": "base", "keep": 1}))
        preset = tmp_path / "preset.json"
        preset.write_text(json.dumps({"env": {"X": "1"}, "model": "preset"}))

        merged = _merge_settings(base, preset)
        assert merged["env"] == {"X": "1"}  # non-hook key carried through
        assert merged["model"] == "preset"  # preset wins on collision
        assert merged["keep"] == 1  # base-only key preserved

    def test_hook_arrays_still_append(self, tmp_path: Path) -> None:
        base = tmp_path / "base.json"
        base.write_text(json.dumps({"hooks": {"PreToolUse": ["a"]}}))
        preset = tmp_path / "preset.json"
        preset.write_text(json.dumps({"hooks": {"PreToolUse": ["b"]}}))

        merged = _merge_settings(base, preset)
        assert merged["hooks"]["PreToolUse"] == ["a", "b"]  # D13 append unchanged


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

    def test_preset_hook_colliding_with_core_hook_warns(
        self, tmp_repo: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """A silent hook overwrite ships the wrong script with no diagnostic."""
        preset_hooks = tmp_repo / "presets" / "python-api" / "hooks"
        (preset_hooks / "protect-files.py").write_text("# OVERRIDDEN protect hook")

        manifest_path = tmp_repo / "presets" / "python-api" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["preset_hooks"].append("protect-files.py")
        manifest_path.write_text(json.dumps(manifest))

        build_preset("python-api", repo_root=tmp_repo)

        assert "WARNING" in capsys.readouterr().out
        shipped = (
            tmp_repo / "dist" / "python-api" / "hooks" / "scripts" / "protect-files.py"
        )
        assert "OVERRIDDEN" in shipped.read_text()

    def test_non_colliding_hook_copy_is_silent(
        self, tmp_repo: Path, capsys: pytest.CaptureFixture
    ) -> None:
        build_preset("python-api", repo_root=tmp_repo)

        assert "overrides core hook" not in capsys.readouterr().out


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

    def test_build_fails_on_missing_core_agent(self, tmp_repo: Path) -> None:
        # A core.agents list naming a nonexistent agent must fail fast (D19), like
        # the core.skills check already does — not silently drop it (#88).
        manifest_path = tmp_repo / "presets" / "python-api" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["core"]["agents"] = ["does-not-exist"]
        manifest_path.write_text(json.dumps(manifest))

        with pytest.raises(BuildValidationError, match="Core agent not found: does-not-exist"):
            build_preset("python-api", repo_root=tmp_repo)

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

    def test_build_omits_agent_matching_when_missing_but_ships_methodology(
        self, tmp_repo: Path
    ) -> None:
        """agent-matching.md is agent-gated; methodology docs ship regardless (#97)."""
        (tmp_repo / "core" / "docs" / "agent-matching.md").unlink()
        build_preset("python-api", repo_root=tmp_repo)
        docs_dir = tmp_repo / "dist" / "python-api" / "docs"
        assert docs_dir.exists()
        assert not (docs_dir / "agent-matching.md").exists()
        assert (docs_dir / "tdd.md").exists()

    def test_build_bundles_methodology_docs(self, tmp_repo: Path) -> None:
        """#97: the methodology docs the README names ship, so the plugin is
        self-documenting rather than pointing at absent files."""
        build_preset("python-api", repo_root=tmp_repo)
        docs = tmp_repo / "dist" / "python-api" / "docs"
        for name in (
            "tdd.md",
            "root-cause-tracing.md",
            "subagent-development.md",
            "parallel-agents.md",
        ):
            assert (docs / name).exists(), f"{name} should be bundled"

    def test_build_excludes_project_doc(self, tmp_repo: Path) -> None:
        """#97: project.md is project-specific and must never ship in a preset."""
        build_preset("python-api", repo_root=tmp_repo)
        assert not (
            tmp_repo / "dist" / "python-api" / "docs" / "project.md"
        ).exists()

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

    def test_base_settings_false_omits_core_hooks(self, tmp_repo: Path) -> None:
        """Persona-style presets can opt out of inherited base hooks."""
        write_persona_preset(tmp_repo, {"hooks": {"SessionStart": [{"hooks": []}]}})

        build_preset("persona", repo_root=tmp_repo)
        hooks_json = tmp_repo / "dist" / "persona" / "hooks" / "hooks.json"
        data = json.loads(hooks_json.read_text())

        assert "SessionStart" in data["hooks"]
        assert len(data["hooks"]["SessionStart"]) == 1
        assert "PreToolUse" not in data["hooks"]
        assert not (
            tmp_repo
            / "dist"
            / "persona"
            / "hooks"
            / "scripts"
            / "protect-files.py"
        ).exists()

    def test_build_copies_preset_output_styles(self, tmp_repo: Path) -> None:
        """Persona presets ship their output-style payload with the hook."""
        preset = write_persona_preset(tmp_repo, {"hooks": {}})
        output_styles = preset / "output-styles"
        output_styles.mkdir()
        (output_styles / "persona.md").write_text("# Persona\n")

        build_preset("persona", repo_root=tmp_repo)

        assert (
            tmp_repo / "dist" / "persona" / "output-styles" / "persona.md"
        ).read_text() == "# Persona\n"


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

    def test_excluded_skill_absent_from_readme(self, tmp_repo: Path) -> None:
        # Exclusions must apply BEFORE the README scan, so an excluded skill is not
        # listed in a README for output that no longer contains it (#122).
        manifest_path = tmp_repo / "presets" / "python-api" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["exclude"] = ["skills/daa-code-review"]
        manifest_path.write_text(json.dumps(manifest))

        build_preset("python-api", repo_root=tmp_repo)
        dist = tmp_repo / "dist" / "python-api"
        assert not (dist / "skills" / "daa-code-review").exists()
        assert "daa-code-review" not in (dist / "README.md").read_text()

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

    def test_exclude_removes_single_file(self, tmp_repo: Path) -> None:
        manifest_path = tmp_repo / "presets" / "python-api" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["exclude"] = ["README.md"]
        manifest_path.write_text(json.dumps(manifest))

        build_preset("python-api", repo_root=tmp_repo)
        dist = tmp_repo / "dist" / "python-api"
        assert not (dist / "README.md").exists()
        assert (dist / ".claude-plugin" / "plugin.json").exists()

    def test_exclusion_path_containment(self, tmp_repo: Path) -> None:
        """Exclusion paths that escape dist_path are rejected."""
        manifest_path = tmp_repo / "presets" / "python-api" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["exclude"] = ["../../etc/passwd"]
        manifest_path.write_text(json.dumps(manifest))

        build_preset("python-api", repo_root=tmp_repo)
        assert (tmp_repo / "dist" / "python-api").exists()

    def test_exclusion_sibling_prefix_not_treated_as_contained(
        self, tmp_repo: Path
    ) -> None:
        """A sibling dir sharing dist_path's name as a prefix must not pass the
        containment check (a string startswith check would wrongly allow it)."""
        sibling = tmp_repo / "dist" / "python-api-evil"
        sibling.mkdir(parents=True)
        sentinel = sibling / "x"
        sentinel.write_text("do not delete")

        manifest_path = tmp_repo / "presets" / "python-api" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["exclude"] = ["../python-api-evil/x"]
        manifest_path.write_text(json.dumps(manifest))

        build_preset("python-api", repo_root=tmp_repo)
        assert sentinel.exists()
        assert sentinel.read_text() == "do not delete"

    def test_exclusion_missing_target_warns(self, tmp_repo: Path, capsys) -> None:
        """A typo'd exclusion that matches nothing still builds, but warns."""
        manifest_path = tmp_repo / "presets" / "python-api" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["exclude"] = ["skills/comit"]
        manifest_path.write_text(json.dumps(manifest))

        dist_path = build_preset("python-api", repo_root=tmp_repo)
        assert dist_path.exists()
        captured = capsys.readouterr()
        assert "WARNING" in captured.out
        assert "skills/comit" in captured.out


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

    def test_validation_catches_hook_in_both_preset_and_exclude(
        self, tmp_repo: Path
    ) -> None:
        import pytest
        from scripts.build_preset import BuildValidationError

        manifest_path = tmp_repo / "presets" / "python-api" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["preset_hooks"] = ["post-edit-lint.py"]
        manifest["exclude"] = ["hooks/scripts/post-edit-lint.py"]
        manifest_path.write_text(json.dumps(manifest))

        with pytest.raises(BuildValidationError, match="preset_hooks and exclude"):
            build_preset("python-api", repo_root=tmp_repo)


class TestConventionsValidation:
    """`conventions` must be a list of strings — build_docs' copy of this check
    was covered, build_preset's was not."""

    def _with_conventions(self, tmp_repo: Path, value: object) -> None:
        manifest_path = tmp_repo / "presets" / "python-api" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["conventions"] = value
        manifest_path.write_text(json.dumps(manifest))

    def test_non_list_conventions_fails(self, tmp_repo: Path) -> None:
        self._with_conventions(tmp_repo, "Lowercase SQL")

        with pytest.raises(BuildValidationError, match="conventions must be a list"):
            build_preset("python-api", repo_root=tmp_repo)

    def test_non_string_element_in_conventions_fails(self, tmp_repo: Path) -> None:
        self._with_conventions(tmp_repo, ["Lowercase SQL", {"rule": "Idempotent"}])

        with pytest.raises(BuildValidationError, match="conventions must be a list"):
            build_preset("python-api", repo_root=tmp_repo)

    def test_list_of_strings_is_accepted(self, tmp_repo: Path) -> None:
        """The guard must not reject the valid shape it exists to protect."""
        self._with_conventions(tmp_repo, ["Lowercase SQL", "Idempotent stages"])

        build_preset("python-api", repo_root=tmp_repo)

        conventions = tmp_repo / "dist" / "python-api" / "conventions.json"
        assert "Lowercase SQL" in conventions.read_text()


class TestManifestRequiredFields:
    """Validation for manifest.json required top-level fields."""

    def test_validation_fails_missing_name(self, tmp_repo: Path) -> None:
        import pytest
        from scripts.build_preset import BuildValidationError

        manifest_path = tmp_repo / "presets" / "python-api" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        del manifest["name"]
        manifest_path.write_text(json.dumps(manifest))

        with pytest.raises(BuildValidationError, match="'name'"):
            build_preset("python-api", repo_root=tmp_repo)

    def test_validation_fails_missing_core(self, tmp_repo: Path) -> None:
        import pytest
        from scripts.build_preset import BuildValidationError

        manifest_path = tmp_repo / "presets" / "python-api" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        del manifest["core"]
        manifest_path.write_text(json.dumps(manifest))

        with pytest.raises(BuildValidationError, match="'core'"):
            build_preset("python-api", repo_root=tmp_repo)


class TestManifestLoading:
    """Validation for manifest.json presence and JSON validity."""

    def test_validation_fails_missing_manifest_file(self, tmp_repo: Path) -> None:
        preset = tmp_repo / "presets" / "no-manifest"
        preset.mkdir()

        with pytest.raises(BuildValidationError, match="no-manifest.*manifest.json"):
            build_preset("no-manifest", repo_root=tmp_repo)

    def test_validation_fails_malformed_json(self, tmp_repo: Path) -> None:
        preset = tmp_repo / "presets" / "bad-json"
        preset.mkdir()
        (preset / "manifest.json").write_text("{not valid json")

        with pytest.raises(BuildValidationError, match="bad-json.*manifest.json"):
            build_preset("bad-json", repo_root=tmp_repo)


class TestConflictCopyGuard:
    """Build rejects macOS Finder conflict copies (e.g. 'SKILL 2.md') in skill dirs.

    These files are gitignored ('* 2.*') so they never reach git, but copytree
    would ship them verbatim into dist/.
    """

    def test_core_skill_conflict_copy_fails_build(self, tmp_repo: Path) -> None:
        (tmp_repo / "core" / "skills" / "tdd" / "SKILL 2.md").write_text("dupe")

        with pytest.raises(BuildValidationError, match=r"tdd/SKILL 2\.md"):
            build_preset("python-api", repo_root=tmp_repo)

    def test_preset_skill_conflict_copy_fails_build(self, tmp_repo: Path) -> None:
        deploy = tmp_repo / "presets" / "python-api" / "skills" / "deploy"
        (deploy / "references").mkdir()
        (deploy / "references" / "guide 2.md").write_text("dupe")

        with pytest.raises(BuildValidationError, match=r"guide 2\.md"):
            build_preset("python-api", repo_root=tmp_repo)

    def test_conflict_copy_never_reaches_dist(self, tmp_repo: Path) -> None:
        (tmp_repo / "core" / "skills" / "tdd" / "SKILL 2.md").write_text("dupe")

        with pytest.raises(BuildValidationError):
            build_preset("python-api", repo_root=tmp_repo)
        assert not (tmp_repo / "dist" / "python-api").exists()


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


class TestJunkDirExclusion:
    """Cache/junk dirs in source trees must not ship into dist (a shipped
    .ruff_cache churns on every test run and made the verify-generated drift
    digest nondeterministic)."""

    def test_junk_dirs_not_copied_into_dist(self, tmp_repo: Path) -> None:
        scripts_dir = tmp_repo / "core" / "skills" / "daa-code-review" / "scripts"
        (scripts_dir / ".ruff_cache").mkdir(parents=True)
        (scripts_dir / ".ruff_cache" / "CACHEDIR.TAG").write_text("cache")
        (scripts_dir / "__pycache__").mkdir()
        (scripts_dir / "__pycache__" / "mod.cpython-312.pyc").write_text("pyc")
        (scripts_dir / "analyzer.py").write_text("# real file ships")
        build_preset("python-api", repo_root=tmp_repo)
        shipped = (
            tmp_repo / "dist" / "python-api" / "skills" / "daa-code-review" / "scripts"
        )
        assert (shipped / "analyzer.py").exists()
        assert not (shipped / ".ruff_cache").exists()
        assert not (shipped / "__pycache__").exists()
