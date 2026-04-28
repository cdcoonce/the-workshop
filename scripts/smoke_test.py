"""Validate internal consistency of a built plugin.

Checks:
- .claude-plugin/plugin.json exists with required fields (name, version, description)
- Every directory in skills/ has a SKILL.md
- Every directory in agents/ has a valid AGENT.md (frontmatter with name, description, role)
- Agent names match their directory names
- Agent roles are 'implementer' or 'reviewer'
- Agent skills.add references resolve to existing skills in skills/
- hooks/hooks.json references scripts that exist in hooks/scripts/
- Every relative link in SKILL.md files resolves within the skill directory
- settings.json at root is valid JSON
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SmokeTestResult:
    """Result of a smoke test run."""

    errors: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return len(self.errors) == 0


def _parse_frontmatter(text: str) -> dict | None:
    """Parse YAML frontmatter from markdown text.

    Parameters
    ----------
    text
        Full markdown text that may begin with ``---`` delimited frontmatter.

    Returns
    -------
    dict | None
        Parsed key-value pairs, or None if no valid frontmatter found.
    """
    if not text.startswith("---"):
        return None
    end = text.find("---", 3)
    if end == -1:
        return None
    frontmatter_text = text[3:end].strip()
    if not frontmatter_text:
        return None
    result: dict = {}
    current_key: str | None = None
    for line in frontmatter_text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        is_indented = line != line.lstrip()
        if ":" in stripped and not stripped.startswith("-") and not is_indented:
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip()
            if value.startswith("[") and value.endswith("]"):
                result[key] = [v.strip() for v in value[1:-1].split(",") if v.strip()]
            elif value:
                result[key] = value
            else:
                result[key] = {}
                current_key = key
        elif current_key and ":" in stripped and is_indented:
            sub_key, _, sub_value = stripped.partition(":")
            sub_key = sub_key.strip()
            sub_value = sub_value.strip()
            if sub_value.startswith("[") and sub_value.endswith("]"):
                result[current_key][sub_key] = [
                    v.strip() for v in sub_value[1:-1].split(",") if v.strip()
                ]
            else:
                result[current_key][sub_key] = sub_value
    return result if result else None


def smoke_test(dist_path: Path) -> SmokeTestResult:
    """Validate internal consistency of a built plugin.

    Parameters
    ----------
    dist_path
        Path to the built plugin directory (e.g., dist/python-api/).

    Returns
    -------
    SmokeTestResult
        Result with any errors found.
    """
    result = SmokeTestResult()

    # 1. Validate .claude-plugin/plugin.json
    plugin_json_path = dist_path / ".claude-plugin" / "plugin.json"
    if not plugin_json_path.exists():
        result.errors.append("plugin.json not found at .claude-plugin/plugin.json")
        return result

    try:
        plugin_data = json.loads(plugin_json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        result.errors.append("plugin.json is not valid JSON")
        return result

    for required_field in ["name", "version", "description"]:
        if required_field not in plugin_data:
            result.errors.append(
                f"plugin.json missing required field '{required_field}'"
            )

    # 2. Validate skills: every directory in skills/ has a SKILL.md
    skills_dir = dist_path / "skills"
    if skills_dir.exists():
        for skill_dir in sorted(skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            if not (skill_dir / "SKILL.md").exists():
                result.errors.append(
                    f"Skill '{skill_dir.name}' directory has no SKILL.md"
                )

    # 3. Validate agents: every directory in agents/ has a valid AGENT.md
    agents_dir = dist_path / "agents"
    if agents_dir.exists():
        for agent_dir in sorted(agents_dir.iterdir()):
            if not agent_dir.is_dir():
                continue
            agent_md = agent_dir / "AGENT.md"
            if not agent_md.exists():
                result.errors.append(
                    f"Agent '{agent_dir.name}' directory has no AGENT.md"
                )
                continue

            frontmatter = _parse_frontmatter(agent_md.read_text(encoding="utf-8"))
            if frontmatter is None:
                result.errors.append(
                    f"Agent '{agent_dir.name}/AGENT.md' has no valid frontmatter"
                )
                continue

            # Check required fields
            for req_field in ["name", "description", "role"]:
                if req_field not in frontmatter:
                    result.errors.append(
                        f"Agent '{agent_dir.name}/AGENT.md' missing required "
                        f"field '{req_field}'"
                    )

            # Validate role
            role = frontmatter.get("role", "")
            if role and role not in ("implementer", "reviewer"):
                result.errors.append(
                    f"Agent '{agent_dir.name}/AGENT.md' has invalid role "
                    f"'{role}' (must be 'implementer' or 'reviewer')"
                )

            # Validate name matches directory
            name = frontmatter.get("name", "")
            if name and name != agent_dir.name:
                result.errors.append(
                    f"Agent '{agent_dir.name}/AGENT.md' name '{name}' does not "
                    f"match directory name '{agent_dir.name}'"
                )

            # Validate skills.add references
            skills_config = frontmatter.get("skills", {})
            if isinstance(skills_config, dict):
                for skill_ref in skills_config.get("add", []):
                    if not skills_dir.exists() or not (skills_dir / skill_ref).is_dir():
                        result.errors.append(
                            f"Agent '{agent_dir.name}/AGENT.md' references skill "
                            f"'{skill_ref}' in skills.add but skill not found "
                            f"in skills/"
                        )

    # 4. Validate hooks: hooks.json references scripts that exist in hooks/scripts/
    hooks_json_path = dist_path / "hooks" / "hooks.json"
    if hooks_json_path.exists():
        try:
            hooks_data = json.loads(hooks_json_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            result.errors.append("hooks/hooks.json is not valid JSON")
            hooks_data = {}

        hooks_scripts_dir = dist_path / "hooks" / "scripts"
        for hook_type, hook_entries in hooks_data.get("hooks", {}).items():
            for entry in hook_entries:
                for hook in entry.get("hooks", []):
                    command = hook.get("command", "")
                    # Extract script filename from $CLAUDE_PLUGIN_ROOT/hooks/scripts/<file>
                    hook_match = re.search(
                        r'hooks/scripts/([^\s"]+)', command
                    )
                    if hook_match:
                        script_name = hook_match.group(1)
                        if not (hooks_scripts_dir / script_name).exists():
                            result.errors.append(
                                f"Hook script '{script_name}' referenced in "
                                f"hooks.json but not found in hooks/scripts/"
                            )

    # 5. Validate intra-skill reference links in SKILL.md files
    link_pattern = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
    code_span_pattern = re.compile(r"`[^`]+`")
    if skills_dir.exists():
        for skill_md in skills_dir.rglob("SKILL.md"):
            skill_content = skill_md.read_text(encoding="utf-8")
            # Strip inline code spans to avoid matching example links
            stripped_content = code_span_pattern.sub("", skill_content)
            for match in link_pattern.finditer(stripped_content):
                link_target = match.group(2)
                # Skip external URLs, anchors, and project-root-relative paths
                if link_target.startswith(("http://", "https://", "#", ".claude/")):
                    continue
                resolved = (skill_md.parent / link_target).resolve()
                if not resolved.exists():
                    skill_name = skill_md.parent.name
                    result.errors.append(
                        f"Skill '{skill_name}/SKILL.md' links to "
                        f"'{link_target}' but file not found"
                    )

    # 6. Validate settings.json is valid JSON
    settings_path = dist_path / "settings.json"
    if settings_path.exists():
        try:
            json.loads(settings_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            result.errors.append("settings.json is not valid JSON")

    return result


if __name__ == "__main__":
    from scripts.build_preset import build_preset

    if len(sys.argv) != 2:
        print("Usage: uv run python -m scripts.smoke_test <preset_name>")
        sys.exit(1)

    preset_name = sys.argv[1]
    dist_path = build_preset(preset_name)
    result = smoke_test(dist_path)

    if result.passed:
        print(f"PASS: plugin '{preset_name}' is internally consistent")
    else:
        print(f"FAIL: plugin '{preset_name}' has {len(result.errors)} error(s):")
        for error in result.errors:
            print(f"  - {error}")
        sys.exit(1)
