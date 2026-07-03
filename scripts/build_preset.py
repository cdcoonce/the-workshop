"""Assemble a Claude plugin from core + preset delta.

Build order (plugin format):
1. Copy core skills -> dist/<preset>/skills/
2. Copy preset skills -> dist/<preset>/skills/ (override on collision)
3. Copy core agents -> dist/<preset>/agents/
4. Copy preset agents -> dist/<preset>/agents/ (override on collision)
5. Copy agent-matching.md -> dist/<preset>/docs/
6. Copy hook scripts to dist/<preset>/hooks/scripts/
7. Generate hooks/hooks.json (merged hook config)
8. Generate settings.json at root (hooks removed)
9. Generate .claude-plugin/plugin.json
10. Generate README.md
11. Apply exclusions
"""

from __future__ import annotations

import copy
import json
import shutil
import sys
from pathlib import Path


class BuildValidationError(Exception):
    """Raised when manifest validation fails."""


def _validate_manifest(
    manifest: dict,
    core_path: Path,
    preset_path: Path,
) -> None:
    """Validate all manifest references exist. Fail fast if not (D19)."""
    errors: list[str] = []

    for hook_name in manifest["core"].get("hooks", []):
        if not (core_path / "hooks" / hook_name).exists():
            errors.append(f"Core hook not found: {hook_name}")

    skills_setting = manifest["core"].get("skills", "all")
    if isinstance(skills_setting, str) and skills_setting != "all":
        errors.append(
            f"core.skills must be 'all' or a list of skill names, got: {skills_setting!r}"
        )
    elif isinstance(skills_setting, list):
        for skill_name in skills_setting:
            if not (core_path / "skills" / skill_name).exists():
                errors.append(f"Core skill not found: {skill_name}")

    agents_setting = manifest["core"].get("agents", "all")
    if isinstance(agents_setting, str) and agents_setting != "all":
        errors.append(
            f"core.agents must be 'all' or a list of agent names, got: {agents_setting!r}"
        )

    for skill_name in manifest.get("preset_skills", []):
        if not (preset_path / "skills" / skill_name).exists():
            errors.append(f"Preset skill not found: {skill_name}")

    for hook_name in manifest.get("preset_hooks", []):
        if not (preset_path / "hooks" / hook_name).exists():
            errors.append(f"Preset hook not found: {hook_name}")

    for agent_name in manifest.get("preset_agents", []):
        if not (preset_path / "agents" / agent_name).exists():
            errors.append(f"Preset agent not found: {agent_name}")

    preset_skill_names = {f"skills/{s}" for s in manifest.get("preset_skills", [])}
    excluded = set(manifest.get("exclude", []))
    conflicts = preset_skill_names & excluded
    if conflicts:
        errors.append(
            f"Skills in both preset_skills and exclude: {', '.join(conflicts)}. "
            f"A preset override cannot also be excluded."
        )

    preset_agent_names = {f"agents/{a}" for a in manifest.get("preset_agents", [])}
    agent_conflicts = preset_agent_names & excluded
    if agent_conflicts:
        errors.append(
            f"Agents in both preset_agents and exclude: {', '.join(agent_conflicts)}. "
            f"A preset override cannot also be excluded."
        )

    if errors:
        raise BuildValidationError(
            "Manifest validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
        )


def _merge_settings(base_path: Path, preset_path: Path) -> dict:
    """Shallow-merge base + preset settings. Preset hook arrays append to base (D13)."""
    base = json.loads(base_path.read_text())
    preset = json.loads(preset_path.read_text())

    merged = copy.deepcopy(base)

    for hook_type, hook_list in preset.get("hooks", {}).items():
        if hook_type in merged.get("hooks", {}):
            merged["hooks"][hook_type].extend(hook_list)
        else:
            merged.setdefault("hooks", {})[hook_type] = hook_list

    return merged


def _generate_readme(manifest: dict, skills: list[str], agents: list[str]) -> str:
    """Generate a simple README.md for the plugin.

    Parameters
    ----------
    manifest
        The preset manifest dict.
    skills
        List of skill directory names in the output.
    agents
        List of agent directory names in the output.

    Returns
    -------
    str
        README content.
    """
    name = manifest["name"]
    description = manifest.get("description", "")
    lines = [
        f"# {name}",
        "",
        description,
        "",
    ]

    if skills:
        lines.append("## Skills")
        lines.append("")
        for skill in sorted(skills):
            lines.append(f"- {skill}")
        lines.append("")

    if agents:
        lines.append("## Agents")
        lines.append("")
        for agent in sorted(agents):
            lines.append(f"- {agent}")
        lines.append("")

    lines.append("## CLAUDE.md Template")
    lines.append("")
    lines.append(
        "Copy the following into your project's `CLAUDE.md` to reference this plugin:"
    )
    lines.append("")
    lines.append("```")
    lines.append("# Project Name")
    lines.append("")
    lines.append("## Plugins")
    lines.append("")
    lines.append(f"This project uses the {name} plugin for Claude Code configuration.")
    lines.append("")
    lines.append("## Methodology")
    lines.append("")
    lines.append(
        "See plugin documentation for TDD, root cause tracing, and subagent development processes."
    )
    lines.append("```")
    lines.append("")

    return "\n".join(lines)


def build_preset(preset_name: str, *, repo_root: Path | None = None) -> Path:
    """Build a preset into dist/<preset_name>/ in plugin format.

    Parameters
    ----------
    preset_name
        Name of the preset directory under presets/.
    repo_root
        Root of the template repo. Defaults to current working directory.

    Returns
    -------
    Path
        Path to the built output directory.
    """
    root = repo_root or Path.cwd()
    core_path = root / "core"
    preset_path = root / "presets" / preset_name
    dist_path = root / "dist" / preset_name

    if not preset_path.exists():
        raise BuildValidationError(f"Preset '{preset_name}' not found at {preset_path}")

    manifest = json.loads((preset_path / "manifest.json").read_text())
    _validate_manifest(manifest, core_path, preset_path)

    if dist_path.exists():
        shutil.rmtree(dist_path)
    dist_path.mkdir(parents=True)

    # 1. Copy core skills -> skills/ (root level)
    skills_setting = manifest["core"].get("skills", "all")
    if skills_setting == "all":
        shutil.copytree(core_path / "skills", dist_path / "skills")
    elif isinstance(skills_setting, list):
        dest_skills = dist_path / "skills"
        dest_skills.mkdir(parents=True, exist_ok=True)
        for skill_name in skills_setting:
            shutil.copytree(core_path / "skills" / skill_name, dest_skills / skill_name)

    # 2. Copy preset skills -> skills/ (override on collision)
    for skill_name in manifest.get("preset_skills", []):
        src = preset_path / "skills" / skill_name
        dest = dist_path / "skills" / skill_name
        if dest.exists():
            print(
                f"WARNING: preset skill '{skill_name}' overrides core skill '{skill_name}'"
            )
            shutil.rmtree(dest)
        shutil.copytree(src, dest)

    # 3. Copy core agents -> agents/ (root level)
    core_agents_dir = core_path / "agents"
    agents_setting = manifest["core"].get("agents", "all")
    if core_agents_dir.exists():
        dest_agents = dist_path / "agents"
        if agents_setting == "all":
            shutil.copytree(core_agents_dir, dest_agents)
        elif isinstance(agents_setting, list):
            dest_agents.mkdir(parents=True, exist_ok=True)
            for agent_name in agents_setting:
                src = core_agents_dir / agent_name
                if src.exists():
                    shutil.copytree(src, dest_agents / agent_name)

    # 4. Copy preset agents -> agents/ (override on collision)
    for agent_name in manifest.get("preset_agents", []):
        src = preset_path / "agents" / agent_name
        dest = dist_path / "agents" / agent_name
        if dest.exists():
            print(
                f"WARNING: preset agent '{agent_name}' overrides core agent '{agent_name}'"
            )
            shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dest)

    # 5. Copy agent-matching.md -> docs/ (only when the plugin ships agents;
    # an agent-less plugin has no use for it).
    agent_matching_src = core_path / "docs" / "agent-matching.md"
    built_agents = dist_path / "agents"
    has_agents = built_agents.exists() and any(built_agents.iterdir())
    if agent_matching_src.exists() and has_agents:
        docs_dir = dist_path / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(agent_matching_src, docs_dir / "agent-matching.md")

    # 6. Copy hook scripts to hooks/scripts/
    hooks_scripts_dir = dist_path / "hooks" / "scripts"
    hooks_scripts_dir.mkdir(parents=True, exist_ok=True)
    for hook_name in manifest["core"].get("hooks", []):
        shutil.copy2(core_path / "hooks" / hook_name, hooks_scripts_dir / hook_name)
    for hook_name in manifest.get("preset_hooks", []):
        shutil.copy2(preset_path / "hooks" / hook_name, hooks_scripts_dir / hook_name)
    # Copy the portable run-hook.sh shim
    run_hook_src = core_path / "hooks" / "run-hook.sh"
    if run_hook_src.exists():
        shutil.copy2(run_hook_src, dist_path / "hooks" / "run-hook.sh")

    # 7. Generate hooks/hooks.json (merged hook config)
    merged_settings = _merge_settings(
        core_path / "settings-base.json",
        preset_path / "settings-preset.json",
    )
    hooks_config = {"hooks": merged_settings.get("hooks", {})}
    (dist_path / "hooks" / "hooks.json").write_text(
        json.dumps(hooks_config, indent=2) + "\n"
    )

    # 8. Generate settings.json at root (hooks removed)
    settings_without_hooks = {k: v for k, v in merged_settings.items() if k != "hooks"}
    (dist_path / "settings.json").write_text(
        json.dumps(settings_without_hooks, indent=2) + "\n"
    )

    # 9. Generate Claude, Codex, and Cortex plugin manifests
    plugin_json = {
        "name": manifest["name"],
        "version": manifest.get("version", "0.0.0"),
        "description": manifest.get("description", ""),
    }

    claude_plugin_dir = dist_path / ".claude-plugin"
    claude_plugin_dir.mkdir(parents=True)
    (claude_plugin_dir / "plugin.json").write_text(
        json.dumps(plugin_json, indent=2) + "\n"
    )

    codex_plugin_json = {
        **plugin_json,
        "author": {"name": "Charles Coonce"},
        "repository": "https://github.com/cdcoonce/claude-workflow",
        "skills": "./skills/",
        "interface": {
            "displayName": manifest["name"],
            "shortDescription": manifest.get("description", ""),
            "longDescription": manifest.get("description", ""),
            "developerName": "Charles Coonce",
            "category": "Productivity",
            "capabilities": ["Skills"],
        },
    }
    codex_plugin_dir = dist_path / ".codex-plugin"
    codex_plugin_dir.mkdir(parents=True)
    (codex_plugin_dir / "plugin.json").write_text(
        json.dumps(codex_plugin_json, indent=2) + "\n"
    )

    # Cortex Code (CoCo) uses the same extended manifest as Codex
    cortex_plugin_dir = dist_path / ".cortex-plugin"
    cortex_plugin_dir.mkdir(parents=True)
    (cortex_plugin_dir / "plugin.json").write_text(
        json.dumps(codex_plugin_json, indent=2) + "\n"
    )

    # 10. Generate README.md
    skill_names = []
    skills_dir = dist_path / "skills"
    if skills_dir.exists():
        skill_names = [d.name for d in skills_dir.iterdir() if d.is_dir()]
    agent_names = []
    agents_dir = dist_path / "agents"
    if agents_dir.exists():
        agent_names = [d.name for d in agents_dir.iterdir() if d.is_dir()]
    (dist_path / "README.md").write_text(
        _generate_readme(manifest, skill_names, agent_names)
    )

    # 11. Apply exclusions (paths are now relative to dist_path, not .claude/)
    for exclusion in manifest.get("exclude", []):
        excluded_path = (dist_path / exclusion).resolve()
        # Path containment check: ensure resolved path is within dist_path
        if not excluded_path.is_relative_to(dist_path.resolve()):
            print(
                f"WARNING: exclusion '{exclusion}' resolves outside build directory, skipping"
            )
            continue
        if excluded_path.exists():
            if excluded_path.is_dir():
                shutil.rmtree(excluded_path)
            else:
                excluded_path.unlink()

    return dist_path


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: uv run python -m scripts.build_preset <preset_name>")
        sys.exit(1)

    preset = sys.argv[1]
    output = build_preset(preset)
    print(f"\nBuilt plugin '{preset}' -> {output}/")
    print(f"  {output}/.claude-plugin/plugin.json")
    print(f"  {output}/.codex-plugin/plugin.json")
    print(f"  {output}/.cortex-plugin/plugin.json")
    print(f"  {output}/skills/")
    print(f"  {output}/agents/")
    print(f"  {output}/hooks/")
    print(f"  {output}/settings.json")
    print(f"  {output}/README.md")
