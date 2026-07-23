"""Assemble a Claude plugin from core + preset delta.

Build order (plugin format):
1. Copy core skills -> dist/<preset>/skills/
2. Copy preset skills -> dist/<preset>/skills/ (override on collision)
3. Copy core agents -> dist/<preset>/agents/
4. Copy preset agents -> dist/<preset>/agents/ (override on collision)
5. Copy agent-matching.md -> dist/<preset>/docs/ (when agents ship)
6. Copy hook scripts to dist/<preset>/hooks/scripts/
7. Copy preset output styles -> dist/<preset>/output-styles/ (when present)
8. Generate hooks/hooks.json (merged hook config)
9. Generate settings.json at root (hooks removed)
10. Generate .claude-plugin/plugin.json
11. Write conventions.json -> dist/<preset>/conventions.json (preset conventions,
    for the inject-skill-router SessionStart hook to read at runtime)
12. Apply exclusions
13. Generate README.md
"""

from __future__ import annotations

import copy
import json
import re
import shutil
import sys
from pathlib import Path

# macOS Finder conflict copies ("SKILL 2.md") are gitignored ('* 2.*') so they
# never reach git, but copytree ships them verbatim into dist/. Matches the
# " N." infix Finder inserts before the extension.
_CONFLICT_COPY_PATTERN = re.compile(r" \d+\.")

# run-hook.sh resolves a bare script name against the preset's hooks/scripts/.
_HOOK_SCRIPT_REFERENCE = re.compile(r"run-hook\.sh\s+(\S+\.py)")

# Cache/junk dirs that live in source trees (test runs regenerate them) must
# never ship into dist: a shipped .ruff_cache churns on every `make test` and
# made the verify-generated drift digest nondeterministic. Applied to every
# copytree below.
_JUNK_IGNORE = shutil.ignore_patterns(
    ".ruff_cache", "__pycache__", ".pytest_cache", ".mypy_cache", ".DS_Store"
)


class BuildValidationError(Exception):
    """Raised when manifest validation fails."""


def _find_conflict_copies(skills_path: Path) -> list[str]:
    """Find macOS conflict-copy files (e.g. 'SKILL 2.md') under a skills tree.

    Parameters
    ----------
    skills_path
        A skills/ source directory to scan recursively. May not exist.

    Returns
    -------
    list[str]
        Sorted paths (relative to ``skills_path``) of offending files.
    """
    if not skills_path.exists():
        return []
    return sorted(
        str(path.relative_to(skills_path))
        for path in skills_path.rglob("*")
        if _CONFLICT_COPY_PATTERN.search(path.name)
    )


def _copy_with_override(src: Path, dest: Path, *, kind: str) -> None:
    """Copy src to dest, warning and replacing dest if it already exists (D19)."""
    if dest.exists():
        print(
            f"WARNING: preset {kind} '{dest.name}' overrides core {kind} '{dest.name}'"
        )
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest, ignore=_JUNK_IGNORE)


def _validate_manifest(
    manifest: dict,
    core_path: Path,
    preset_path: Path,
) -> None:
    """Validate all manifest references exist. Fail fast if not (D19)."""
    errors: list[str] = []

    for required_key in ("name", "core"):
        if required_key not in manifest:
            errors.append(f"Manifest missing required field: '{required_key}'")

    if errors:
        raise BuildValidationError(
            "Manifest validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
        )

    for hook_name in manifest["core"].get("hooks", []):
        if not (core_path / "hooks" / hook_name).exists():
            errors.append(f"Core hook not found: {hook_name}")

    core_skills = manifest["core"].get("skills", "all")
    if isinstance(core_skills, list):
        for skill_name in core_skills:
            if not (core_path / "skills" / skill_name).exists():
                errors.append(f"Core skill not found: {skill_name}")
    elif core_skills != "all":
        errors.append(
            f"core.skills must be 'all' or a list of skill names, got: {core_skills!r}"
        )

    core_agents = manifest["core"].get("agents", "all")
    if isinstance(core_agents, list):
        for agent_name in core_agents:
            if not (core_path / "agents" / agent_name).exists():
                errors.append(f"Core agent not found: {agent_name}")
    elif core_agents != "all":
        errors.append(
            f"core.agents must be 'all' or a list of agent names, got: {core_agents!r}"
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

    preset_hook_names = {f"hooks/scripts/{h}" for h in manifest.get("preset_hooks", [])}
    hook_conflicts = preset_hook_names & excluded
    if hook_conflicts:
        errors.append(
            f"Hooks in both preset_hooks and exclude: {', '.join(hook_conflicts)}. "
            f"A preset override cannot also be excluded."
        )

    conventions = manifest.get("conventions", [])
    if not isinstance(conventions, list) or not all(
        isinstance(c, str) for c in conventions
    ):
        errors.append(
            "conventions must be a list of strings (each a one-line convention "
            "the preset enforces), got: "
            f"{conventions!r}"
        )

    # Every hook the built hooks.json invokes must have a script behind it.
    # A preset inheriting settings-base.json picks up the core PreToolUse hooks
    # whether or not it declares them, and step 6 only copies what the manifest
    # names. When the two disagree the plugin ships commands pointing at absent
    # scripts, and PreToolUse failures block the matching tool outright.
    if manifest.get("base_settings", True):
        declared_hooks = set(manifest["core"].get("hooks", [])) | set(
            manifest.get("preset_hooks", [])
        )
        base_settings = json.loads((core_path / "settings-base.json").read_text())
        inherited_hooks = set(
            _HOOK_SCRIPT_REFERENCE.findall(json.dumps(base_settings.get("hooks", {})))
        )
        for hook_name in sorted(inherited_hooks - declared_hooks):
            errors.append(
                f"Hook wired but not shipped: {hook_name}. settings-base.json "
                f"invokes it, so it lands in hooks.json, but the manifest does "
                f"not list it in core.hooks or preset_hooks and the build would "
                f"omit the script. Declare it, or set base_settings to false."
            )

    if errors:
        raise BuildValidationError(
            "Manifest validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
        )


def _merge_settings(base_path: Path, preset_path: Path) -> dict:
    """Shallow-merge base + preset settings. Preset hook arrays append to base (D13)."""
    if not base_path.exists():
        raise BuildValidationError(f"Base settings not found at {base_path}")
    if not preset_path.exists():
        raise BuildValidationError(
            f"Preset settings not found at {preset_path}. "
            "Every preset must have a settings-preset.json (an empty '{}' is fine "
            "if the preset contributes no settings/hooks of its own)."
        )
    base = json.loads(base_path.read_text())
    preset = json.loads(preset_path.read_text())

    merged = copy.deepcopy(base)

    for hook_type, hook_list in preset.get("hooks", {}).items():
        if hook_type in merged.get("hooks", {}):
            merged["hooks"][hook_type].extend(hook_list)
        else:
            merged.setdefault("hooks", {})[hook_type] = hook_list

    # Shallow-merge every non-hook top-level key so a preset can contribute
    # env/permissions/model/etc.; preset wins on collision (#92). hooks are handled
    # above (arrays append, D13), so skip them here.
    for key, value in preset.items():
        if key == "hooks":
            continue
        merged[key] = value

    return merged


def _skill_doc_from_dir(skill_dir: Path):
    """Read a built skill dir into a SkillDoc, degrading to name-only on bad input.

    The dist tree is the source of truth for what actually shipped (post-exclusion),
    so the README reflects reality. Frontmatter here is already validated upstream
    by smoke_test/build_docs; this stays tolerant so a README can still build.
    """
    from scripts.build_docs import SkillDoc
    from scripts.smoke_test import _parse_frontmatter

    frontmatter = _parse_frontmatter(
        (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    )
    if not frontmatter:
        return SkillDoc(name=skill_dir.name, description="", source="dist")
    return SkillDoc(
        name=str(frontmatter.get("name", skill_dir.name)),
        description=str(frontmatter.get("description", "")).strip(),
        source="dist",
    )


def _agent_doc_from_dir(agent_dir: Path):
    """Read a built agent dir into an AgentDoc, degrading gracefully on bad input."""
    from scripts.build_docs import AgentDoc
    from scripts.smoke_test import _parse_frontmatter

    frontmatter = _parse_frontmatter(
        (agent_dir / "AGENT.md").read_text(encoding="utf-8")
    )
    if not frontmatter:
        return AgentDoc(
            name=agent_dir.name, description="", role="", skills_add=(), source="dist"
        )
    return AgentDoc(
        name=str(frontmatter.get("name", agent_dir.name)),
        description=str(frontmatter.get("description", "")).strip(),
        role=str(frontmatter.get("role", "")),
        skills_add=(),
        source="dist",
    )


def _generate_readme(manifest: dict, dist_path: Path) -> str:
    """Generate a rich README for the built plugin from its shipped components.

    Parameters
    ----------
    manifest
        The preset manifest dict.
    dist_path
        The built plugin directory. Its (post-exclusion) skills/ and agents/ trees
        are the source of what the README lists.

    Returns
    -------
    str
        README content, using the shared renderers in build_docs so the dist
        README shares the repo reference's shape.
    """
    from scripts.build_docs import render_preset_readme

    skills = []
    skills_dir = dist_path / "skills"
    if skills_dir.exists():
        for skill_dir in sorted(d for d in skills_dir.iterdir() if d.is_dir()):
            if (skill_dir / "SKILL.md").exists():
                skills.append(_skill_doc_from_dir(skill_dir))

    agents = []
    agents_dir = dist_path / "agents"
    if agents_dir.exists():
        for agent_dir in sorted(d for d in agents_dir.iterdir() if d.is_dir()):
            if (agent_dir / "AGENT.md").exists():
                agents.append(_agent_doc_from_dir(agent_dir))

    return render_preset_readme(
        name=manifest["name"],
        description=manifest.get("description", ""),
        skills=skills,
        agents=agents,
        conventions=tuple(manifest.get("conventions", [])),
    )


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

    manifest_path = preset_path / "manifest.json"
    if not manifest_path.exists():
        raise BuildValidationError(
            f"Preset '{preset_name}' has no manifest.json at {manifest_path}"
        )
    try:
        manifest = json.loads(manifest_path.read_text())
    except json.JSONDecodeError as exc:
        raise BuildValidationError(
            f"Preset '{preset_name}' has invalid JSON in {manifest_path}: {exc}"
        ) from exc
    _validate_manifest(manifest, core_path, preset_path)

    conflict_copies = [
        f"{skills_src.relative_to(root)}/{relative_path}"
        for skills_src in (core_path / "skills", preset_path / "skills")
        for relative_path in _find_conflict_copies(skills_src)
    ]
    if conflict_copies:
        raise BuildValidationError(
            "macOS conflict copies found in skill dirs (delete before building):\n"
            + "\n".join(f"  - {c}" for c in conflict_copies)
        )

    if dist_path.exists():
        shutil.rmtree(dist_path)
    dist_path.mkdir(parents=True)

    # 1. Copy core skills -> skills/ (root level)
    skills_setting = manifest["core"].get("skills", "all")
    if skills_setting == "all":
        shutil.copytree(core_path / "skills", dist_path / "skills", ignore=_JUNK_IGNORE)
    elif isinstance(skills_setting, list):
        dest_skills = dist_path / "skills"
        dest_skills.mkdir(parents=True, exist_ok=True)
        for skill_name in skills_setting:
            shutil.copytree(
                core_path / "skills" / skill_name,
                dest_skills / skill_name,
                ignore=_JUNK_IGNORE,
            )

    # 2. Copy preset skills -> skills/ (override on collision)
    for skill_name in manifest.get("preset_skills", []):
        src = preset_path / "skills" / skill_name
        dest = dist_path / "skills" / skill_name
        _copy_with_override(src, dest, kind="skill")

    # 3. Copy core agents -> agents/ (root level)
    core_agents_dir = core_path / "agents"
    agents_setting = manifest["core"].get("agents", "all")
    if core_agents_dir.exists():
        dest_agents = dist_path / "agents"
        if agents_setting == "all":
            shutil.copytree(core_agents_dir, dest_agents, ignore=_JUNK_IGNORE)
        elif isinstance(agents_setting, list):
            dest_agents.mkdir(parents=True, exist_ok=True)
            for agent_name in agents_setting:
                src = core_agents_dir / agent_name
                if src.exists():
                    shutil.copytree(src, dest_agents / agent_name, ignore=_JUNK_IGNORE)

    # 4. Copy preset agents -> agents/ (override on collision)
    for agent_name in manifest.get("preset_agents", []):
        src = preset_path / "agents" / agent_name
        dest = dist_path / "agents" / agent_name
        _copy_with_override(src, dest, kind="agent")

    # 5. Copy core/docs -> docs/ (#97). The methodology docs the README names
    # (tdd, root-cause-tracing, subagent-development) plus parallel-agents always
    # ship, so the plugin is self-documenting rather than pointing at absent
    # files. agent-matching.md ships only when the plugin has agents (an
    # agent-less plugin -- e.g. a style-only persona -- has no use for the
    # selection algorithm). project.md is project-specific and never ships.
    docs_src = core_path / "docs"
    if docs_src.exists():
        built_agents = dist_path / "agents"
        has_agents = built_agents.exists() and any(built_agents.iterdir())
        docs_dir = dist_path / "docs"
        for doc in sorted(docs_src.glob("*.md")):
            if doc.name == "project.md":
                continue
            if doc.name == "agent-matching.md" and not has_agents:
                continue
            docs_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(doc, docs_dir / doc.name)

    # 6. Copy hook scripts to hooks/scripts/
    hooks_scripts_dir = dist_path / "hooks" / "scripts"
    hooks_scripts_dir.mkdir(parents=True, exist_ok=True)
    for hook_name in manifest["core"].get("hooks", []):
        shutil.copy2(core_path / "hooks" / hook_name, hooks_scripts_dir / hook_name)
    for hook_name in manifest.get("preset_hooks", []):
        dest = hooks_scripts_dir / hook_name
        if dest.exists():
            print(
                f"WARNING: preset hook '{hook_name}' overrides core hook '{hook_name}'"
            )
        shutil.copy2(preset_path / "hooks" / hook_name, dest)
    # Copy the portable run-hook.sh shim
    run_hook_src = core_path / "hooks" / "run-hook.sh"
    if run_hook_src.exists():
        shutil.copy2(run_hook_src, dist_path / "hooks" / "run-hook.sh")
    # Shared hook library modules (leading underscore = not a hook). Hooks import
    # these as siblings — run-hook.sh runs `python3 hooks/scripts/<name>`, so
    # sys.path[0] is that directory. Shipped unconditionally, like run-hook.sh:
    # a preset carrying a hook without its helper would crash on the user's
    # tool path, and the manifests list hooks, not the libraries behind them.
    for module in sorted((core_path / "hooks").glob("_*.py")):
        shutil.copy2(module, hooks_scripts_dir / module.name)

    # 7. Copy optional preset output styles used by persona SessionStart hooks.
    output_styles_src = preset_path / "output-styles"
    if output_styles_src.exists():
        shutil.copytree(
            output_styles_src, dist_path / "output-styles", ignore=_JUNK_IGNORE
        )

    # 8. Generate hooks/hooks.json (merged hook config). Some presets are
    # pure SessionStart/persona layers and opt out of base settings so they do
    # not inherit core PreToolUse hooks without shipping the paired scripts.
    preset_settings_path = preset_path / "settings-preset.json"
    if manifest.get("base_settings", True):
        merged_settings = _merge_settings(
            core_path / "settings-base.json",
            preset_settings_path,
        )
    else:
        if not preset_settings_path.exists():
            raise BuildValidationError(
                f"Preset settings not found at {preset_settings_path}. "
                "Every preset must have a settings-preset.json (an empty '{}' is "
                "fine if the preset contributes no settings/hooks of its own)."
            )
        merged_settings = json.loads(preset_settings_path.read_text())
    hooks_config = {"hooks": merged_settings.get("hooks", {})}
    (dist_path / "hooks" / "hooks.json").write_text(
        json.dumps(hooks_config, indent=2) + "\n"
    )

    # 9. Generate settings.json at root (hooks removed)
    settings_without_hooks = {k: v for k, v in merged_settings.items() if k != "hooks"}
    (dist_path / "settings.json").write_text(
        json.dumps(settings_without_hooks, indent=2) + "\n"
    )

    # 10. Generate Claude, Codex, and Cortex plugin manifests
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

    # Determine capabilities based on what the plugin actually contains
    has_skills = any((dist_path / "skills").glob("*/SKILL.md"))
    capabilities = ["Skills"] if has_skills else []

    codex_plugin_json = {
        **plugin_json,
        "author": {"name": "Charles Coonce"},
        "repository": "https://github.com/cdcoonce/the-workshop",
        **({"skills": "./skills/"} if has_skills else {}),
        "interface": {
            "displayName": manifest["name"],
            "shortDescription": manifest.get("description", ""),
            "longDescription": manifest.get("description", ""),
            "developerName": "Charles Coonce",
            "category": "Productivity",
            **({"capabilities": capabilities} if capabilities else {}),
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

    # 11. Write conventions.json -> dist/<preset>/conventions.json. The
    # inject-skill-router SessionStart hook runs from the installed plugin root
    # and has no other way to read the source manifest's conventions array.
    (dist_path / "conventions.json").write_text(
        json.dumps({"conventions": manifest.get("conventions", [])}, indent=2) + "\n"
    )

    # 12. Apply exclusions BEFORE the README scan, so the skill/agent listings
    # reflect the final built output — an excluded dir must not appear in the
    # generated README (#122). Paths are relative to dist_path, not .claude/.
    # Steps 7-9 (settings/hooks/plugin.json) read the manifest, not the dist tree,
    # so applying exclusions here does not affect them.
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
        else:
            print(f"WARNING: exclusion '{exclusion}' did not match anything, skipping")

    # 13. Generate README.md (scans the post-exclusion dist tree), unless README.md
    # is itself excluded — exclusions already ran, so generating it here would undo
    # a README-targeting exclusion.
    excluded_paths = {
        (dist_path / exclusion).resolve() for exclusion in manifest.get("exclude", [])
    }
    if (dist_path / "README.md").resolve() not in excluded_paths:
        (dist_path / "README.md").write_text(_generate_readme(manifest, dist_path))

    return dist_path


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: uv run python -m scripts.build_preset <preset_name>")
        sys.exit(1)

    preset = sys.argv[1]
    try:
        output = build_preset(preset)
    except BuildValidationError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    print(f"\nBuilt plugin '{preset}' -> {output}/")
    print(f"  {output}/.claude-plugin/plugin.json")
    print(f"  {output}/.codex-plugin/plugin.json")
    print(f"  {output}/.cortex-plugin/plugin.json")
    print(f"  {output}/skills/")
    print(f"  {output}/agents/")
    print(f"  {output}/hooks/")
    print(f"  {output}/settings.json")
    print(f"  {output}/README.md")
