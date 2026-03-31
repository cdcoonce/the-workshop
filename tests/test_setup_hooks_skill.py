"""Tests for core/skills/setup-hooks — validates skill structure and content."""

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = REPO_ROOT / "core" / "skills" / "setup-hooks"
SKILL_MD = SKILL_DIR / "SKILL.md"
HOOK_PROTOCOL_REF = SKILL_DIR / "references" / "hook-protocol.md"


class TestSetupHooksSkillExists:
    """The setup-hooks skill directory and required files exist."""

    def test_skill_directory_exists(self) -> None:
        assert SKILL_DIR.is_dir(), f"Expected directory at {SKILL_DIR}"

    def test_skill_md_exists(self) -> None:
        assert SKILL_MD.is_file(), f"Expected SKILL.md at {SKILL_MD}"

    def test_hook_protocol_reference_exists(self) -> None:
        assert HOOK_PROTOCOL_REF.is_file(), (
            f"Expected hook-protocol.md at {HOOK_PROTOCOL_REF}"
        )


class TestSetupHooksSkillMdFrontmatter:
    """SKILL.md has valid YAML frontmatter with required fields."""

    def test_starts_with_frontmatter_delimiter(self) -> None:
        content = SKILL_MD.read_text(encoding="utf-8")
        assert content.startswith("---"), "SKILL.md must start with --- frontmatter"

    def test_frontmatter_contains_name(self) -> None:
        content = SKILL_MD.read_text(encoding="utf-8")
        frontmatter = _extract_frontmatter(content)
        assert "name: setup-hooks" in frontmatter

    def test_frontmatter_contains_description(self) -> None:
        content = SKILL_MD.read_text(encoding="utf-8")
        frontmatter = _extract_frontmatter(content)
        assert "description:" in frontmatter


class TestSetupHooksSkillMdContent:
    """SKILL.md contains the required interview flow sections."""

    def test_contains_prerequisites_section(self) -> None:
        content = SKILL_MD.read_text(encoding="utf-8")
        assert "## Prerequisites" in content or "## prerequisite" in content.lower()

    def test_contains_event_type_question(self) -> None:
        content = SKILL_MD.read_text(encoding="utf-8")
        assert "PreToolUse" in content
        assert "PostToolUse" in content

    def test_contains_matcher_pattern_question(self) -> None:
        content = SKILL_MD.read_text(encoding="utf-8")
        assert "Edit|Write" in content
        assert "Bash" in content

    def test_contains_behavior_description_question(self) -> None:
        content = SKILL_MD.read_text(encoding="utf-8")
        content_lower = content.lower()
        assert "behavior" in content_lower or "behaviour" in content_lower

    def test_contains_ask_user_question_references(self) -> None:
        content = SKILL_MD.read_text(encoding="utf-8")
        assert "AskUserQuestion" in content

    def test_phase_2_placeholder_is_removed(self) -> None:
        content = SKILL_MD.read_text(encoding="utf-8")
        assert "<!-- Phase 2:" not in content


class TestSetupHooksScriptGeneration:
    """SKILL.md contains script generation instructions (Step 4)."""

    def test_contains_script_generation_section(self) -> None:
        content = SKILL_MD.read_text(encoding="utf-8")
        assert "## Step 4" in content
        assert "Generate Hook Script" in content

    def test_mentions_canonical_template_elements(self) -> None:
        content = SKILL_MD.read_text(encoding="utf-8")
        assert "json.load(sys.stdin)" in content
        assert "sys.exit" in content

    def test_mentions_stderr_for_messages(self) -> None:
        content = SKILL_MD.read_text(encoding="utf-8")
        assert "stderr" in content

    def test_mentions_hooks_target_directory(self) -> None:
        content = SKILL_MD.read_text(encoding="utf-8")
        assert ".claude/hooks/" in content

    def test_handles_filename_collision(self) -> None:
        content = SKILL_MD.read_text(encoding="utf-8").lower()
        assert "overwrite" in content
        assert "cancel" in content

    def test_mentions_stdlib_only(self) -> None:
        content = SKILL_MD.read_text(encoding="utf-8").lower()
        assert "stdlib" in content or "standard library" in content

    def test_mentions_shutil_which_for_external_tools(self) -> None:
        content = SKILL_MD.read_text(encoding="utf-8")
        assert "shutil.which" in content


class TestSetupHooksConfigWiring:
    """SKILL.md contains config wiring instructions (Step 5)."""

    def test_contains_config_wiring_section(self) -> None:
        content = SKILL_MD.read_text(encoding="utf-8")
        assert "## Step 5" in content
        assert "Wire Hook into Settings" in content

    def test_mentions_settings_json(self) -> None:
        content = SKILL_MD.read_text(encoding="utf-8")
        assert "settings.json" in content

    def test_mentions_append_semantics(self) -> None:
        """Config wiring must use append/extend, not replace."""
        content = SKILL_MD.read_text(encoding="utf-8").lower()
        assert "append" in content or "extend" in content

    def test_contains_json_skeleton_for_missing_settings(self) -> None:
        content = SKILL_MD.read_text(encoding="utf-8")
        assert '"hooks"' in content
        assert '"PreToolUse"' in content
        assert '"PostToolUse"' in content

    def test_contains_hook_entry_shape(self) -> None:
        content = SKILL_MD.read_text(encoding="utf-8")
        assert '"matcher"' in content
        assert '"type": "command"' in content


class TestSetupHooksConfirmation:
    """SKILL.md contains a confirmation/summary section (Step 6)."""

    def test_contains_confirmation_section(self) -> None:
        content = SKILL_MD.read_text(encoding="utf-8")
        assert "## Step 6" in content
        assert "Confirm" in content

    def test_mentions_testing_instructions(self) -> None:
        content = SKILL_MD.read_text(encoding="utf-8").lower()
        assert "test" in content
        assert "matching tool call" in content or "matched tool" in content


class TestHookProtocolReference:
    """hook-protocol.md contains complete protocol documentation."""

    def test_documents_stdin_json_schema(self) -> None:
        content = HOOK_PROTOCOL_REF.read_text(encoding="utf-8")
        assert "tool_name" in content
        assert "tool_input" in content

    def test_documents_exit_code_meanings(self) -> None:
        content = HOOK_PROTOCOL_REF.read_text(encoding="utf-8")
        # Must mention exit 0 = allow for PreToolUse
        assert "exit" in content.lower()
        assert "block" in content.lower()

    def test_documents_matcher_syntax(self) -> None:
        content = HOOK_PROTOCOL_REF.read_text(encoding="utf-8")
        assert "Edit|Write" in content
        assert "matcher" in content.lower() or "Matcher" in content

    def test_documents_stderr_messaging(self) -> None:
        content = HOOK_PROTOCOL_REF.read_text(encoding="utf-8")
        assert "stderr" in content

    def test_documents_environment_variables(self) -> None:
        content = HOOK_PROTOCOL_REF.read_text(encoding="utf-8")
        assert "CLAUDE_PLUGIN_ROOT" in content

    def test_contains_pretooluse_example(self) -> None:
        content = HOOK_PROTOCOL_REF.read_text(encoding="utf-8")
        # Should contain annotated code from protect-files.py
        assert "protect-files" in content.lower() or "json.load(sys.stdin)" in content

    def test_contains_posttooluse_example(self) -> None:
        content = HOOK_PROTOCOL_REF.read_text(encoding="utf-8")
        # Should contain annotated code from post-edit-lint.py
        assert "post-edit-lint" in content.lower() or "subprocess" in content

    def test_links_in_skill_md_resolve(self) -> None:
        """Any relative links in SKILL.md must point to real files."""
        content = SKILL_MD.read_text(encoding="utf-8")
        link_pattern = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
        for match in link_pattern.finditer(content):
            target = match.group(2)
            if target.startswith(("http://", "https://", "#", ".claude/")):
                continue
            resolved = (SKILL_MD.parent / target).resolve()
            assert resolved.exists(), (
                f"SKILL.md links to '{target}' but file not found at {resolved}"
            )


class TestSetupHooksSmokeTest:
    """The new skill passes the build + smoke test pipeline."""

    def test_smoke_test_passes_with_setup_hooks(self, tmp_repo: Path) -> None:
        """Build data-pipeline preset (core skills=all) and smoke-test it."""
        # The tmp_repo fixture only has 3 core skills. We need to add setup-hooks.
        skill_dir = tmp_repo / "core" / "skills" / "setup-hooks"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            SKILL_MD.read_text(encoding="utf-8"), encoding="utf-8"
        )
        refs_dir = skill_dir / "references"
        refs_dir.mkdir()
        (refs_dir / "hook-protocol.md").write_text(
            HOOK_PROTOCOL_REF.read_text(encoding="utf-8"), encoding="utf-8"
        )

        from scripts.build_preset import build_preset
        from scripts.smoke_test import smoke_test

        dist = build_preset("python-api", repo_root=tmp_repo)
        result = smoke_test(dist)
        assert result.passed, f"Smoke test failed: {result.errors}"

        # Verify setup-hooks was included in the build
        built_skill = dist / "skills" / "setup-hooks" / "SKILL.md"
        assert built_skill.exists()
        built_ref = dist / "skills" / "setup-hooks" / "references" / "hook-protocol.md"
        assert built_ref.exists()


def _extract_frontmatter(text: str) -> str:
    """Extract raw frontmatter string between --- delimiters."""
    if not text.startswith("---"):
        return ""
    end = text.find("---", 3)
    if end == -1:
        return ""
    return text[3:end]
