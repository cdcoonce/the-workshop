"""Tests for the frontmatter engine — validation and generation."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add scripts dir to path
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(SCRIPTS_DIR))

from frontmatter_engine import ValidationError, generate, validate


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def vault(tmp_path: Path) -> Path:
    """Create a minimal vault structure for testing."""
    (tmp_path / "CLAUDE.md").write_text("# Vault")
    (tmp_path / "brain").mkdir()
    (tmp_path / "work" / "active").mkdir(parents=True)
    (tmp_path / "templates").mkdir()
    (tmp_path / "thinking").mkdir()
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".obsidian").mkdir()
    return tmp_path


def _write_note(vault: Path, rel_path: str, content: str) -> Path:
    """Helper to write a note file in the vault."""
    p = vault / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Valid frontmatter
# ---------------------------------------------------------------------------

class TestValidFrontmatter:
    def test_valid_work_note(self, vault: Path) -> None:
        p = _write_note(vault, "work/active/my-project.md", (
            "---\n"
            "date: 2026-04-04\n"
            "description: \"A short description of the project\"\n"
            "tags:\n  - work-note\n"
            "status: active\n"
            "project: \"My Project\"\n"
            "quarter: \"Q2 2026\"\n"
            "---\n\n"
            "# My Project\n\nSome short content.\n"
        ))
        errors = validate(p, vault)
        assert errors == []

    def test_valid_decision_record(self, vault: Path) -> None:
        p = _write_note(vault, "work/active/use-snowflake.md", (
            "---\n"
            "date: 2026-03-15\n"
            "description: \"Decision to migrate from Redshift to Snowflake\"\n"
            "tags:\n  - decision\n"
            "status: decided\n"
            "---\n\n"
            "# Use Snowflake\n\nShort note.\n"
        ))
        errors = validate(p, vault)
        assert errors == []

    def test_valid_note_with_wikilinks_over_threshold(self, vault: Path) -> None:
        body = "x" * 301 + "\n\nSee [[Some Other Note]] for details."
        p = _write_note(vault, "brain/test-note.md", (
            "---\n"
            "date: 2026-04-04\n"
            "description: \"A long note with wikilinks\"\n"
            "tags:\n  - index\n"
            "---\n\n" + body
        ))
        errors = validate(p, vault)
        assert errors == []


# ---------------------------------------------------------------------------
# Missing universal fields
# ---------------------------------------------------------------------------

class TestMissingFields:
    def test_missing_date(self, vault: Path) -> None:
        p = _write_note(vault, "work/active/no-date.md", (
            "---\n"
            "description: \"Has description\"\n"
            "tags:\n  - work-note\n"
            "status: active\n"
            "project: \"Foo\"\n"
            "---\n\nContent.\n"
        ))
        errors = validate(p, vault)
        field_names = [e.field for e in errors]
        assert "date" in field_names

    def test_missing_description(self, vault: Path) -> None:
        p = _write_note(vault, "work/active/no-desc.md", (
            "---\n"
            "date: 2026-04-04\n"
            "tags:\n  - work-note\n"
            "status: active\n"
            "project: \"Foo\"\n"
            "---\n\nContent.\n"
        ))
        errors = validate(p, vault)
        field_names = [e.field for e in errors]
        assert "description" in field_names

    def test_empty_description(self, vault: Path) -> None:
        p = _write_note(vault, "work/active/empty-desc.md", (
            "---\n"
            "date: 2026-04-04\n"
            "description: \"\"\n"
            "tags:\n  - work-note\n"
            "status: active\n"
            "project: \"Foo\"\n"
            "---\n\nContent.\n"
        ))
        errors = validate(p, vault)
        field_names = [e.field for e in errors]
        assert "description" in field_names

    def test_missing_tags(self, vault: Path) -> None:
        p = _write_note(vault, "brain/no-tags.md", (
            "---\n"
            "date: 2026-04-04\n"
            "description: \"Has description\"\n"
            "---\n\nContent.\n"
        ))
        errors = validate(p, vault)
        field_names = [e.field for e in errors]
        assert "tags" in field_names

    def test_empty_tags_list(self, vault: Path) -> None:
        p = _write_note(vault, "brain/empty-tags.md", (
            "---\n"
            "date: 2026-04-04\n"
            "description: \"Has description\"\n"
            "tags: []\n"
            "---\n\nContent.\n"
        ))
        errors = validate(p, vault)
        field_names = [e.field for e in errors]
        assert "tags" in field_names


# ---------------------------------------------------------------------------
# Bad date format
# ---------------------------------------------------------------------------

class TestBadDateFormat:
    def test_date_wrong_format(self, vault: Path) -> None:
        p = _write_note(vault, "brain/bad-date.md", (
            "---\n"
            "date: April 4 2026\n"
            "description: \"Has description\"\n"
            "tags:\n  - index\n"
            "---\n\nContent.\n"
        ))
        errors = validate(p, vault)
        date_errors = [e for e in errors if e.field == "date"]
        assert len(date_errors) == 1
        assert "YYYY-MM-DD" in date_errors[0].message

    def test_date_us_format(self, vault: Path) -> None:
        p = _write_note(vault, "brain/us-date.md", (
            "---\n"
            "date: 04/04/2026\n"
            "description: \"Has description\"\n"
            "tags:\n  - index\n"
            "---\n\nContent.\n"
        ))
        errors = validate(p, vault)
        date_errors = [e for e in errors if e.field == "date"]
        assert len(date_errors) == 1


# ---------------------------------------------------------------------------
# Wikilink requirement
# ---------------------------------------------------------------------------

class TestWikilinkRequirement:
    def test_long_note_without_wikilinks(self, vault: Path) -> None:
        body = "This is a long note. " * 30  # well over 300 chars
        p = _write_note(vault, "brain/long-orphan.md", (
            "---\n"
            "date: 2026-04-04\n"
            "description: \"A long note\"\n"
            "tags:\n  - index\n"
            "---\n\n" + body
        ))
        errors = validate(p, vault)
        wiki_errors = [e for e in errors if e.field == "wikilinks"]
        assert len(wiki_errors) == 1

    def test_short_note_without_wikilinks_ok(self, vault: Path) -> None:
        p = _write_note(vault, "brain/short.md", (
            "---\n"
            "date: 2026-04-04\n"
            "description: \"A short note\"\n"
            "tags:\n  - index\n"
            "---\n\nShort content.\n"
        ))
        errors = validate(p, vault)
        assert errors == []

    def test_long_note_with_wikilinks_ok(self, vault: Path) -> None:
        body = "This is a long note. " * 30 + "\n\nSee [[Related Topic]] for more."
        p = _write_note(vault, "brain/long-linked.md", (
            "---\n"
            "date: 2026-04-04\n"
            "description: \"A long note with links\"\n"
            "tags:\n  - index\n"
            "---\n\n" + body
        ))
        errors = validate(p, vault)
        assert errors == []

    def test_long_transient_task_ledger_does_not_need_wikilinks(self, vault: Path) -> None:
        body = "- [ ] Task\n" * 60
        p = _write_note(vault, "work/Tasks.md", (
            "---\n"
            "date: 2026-07-08\n"
            "description: \"Work task ledger\"\n"
            "tags:\n"
            "  - tasks\n"
            "week: 2026-W28\n"
            "---\n\n" + body
        ))

        errors = validate(p, vault)

        assert [e.field for e in errors] == []


# ---------------------------------------------------------------------------
# Type-specific validation
# ---------------------------------------------------------------------------

class TestTypeSpecificValidation:
    def test_work_note_missing_status(self, vault: Path) -> None:
        p = _write_note(vault, "work/active/missing-status.md", (
            "---\n"
            "date: 2026-04-04\n"
            "description: \"A work note\"\n"
            "tags:\n  - work-note\n"
            "project: \"Foo\"\n"
            "---\n\nContent.\n"
        ))
        errors = validate(p, vault)
        field_names = [e.field for e in errors]
        assert "status" in field_names

    def test_1_1_missing_participant(self, vault: Path) -> None:
        p = _write_note(vault, "work/1-1/no-participant.md", (
            "---\n"
            "date: 2026-04-04\n"
            "description: \"1:1 meeting\"\n"
            "tags:\n  - 1-1\n"
            "---\n\nContent.\n"
        ))
        errors = validate(p, vault)
        field_names = [e.field for e in errors]
        assert "participant" in field_names

    def test_competency_missing_levels(self, vault: Path) -> None:
        p = _write_note(vault, "perf/competencies/sql.md", (
            "---\n"
            "date: 2026-04-04\n"
            "description: \"SQL competency\"\n"
            "tags:\n  - competency\n"
            "---\n\nContent.\n"
        ))
        errors = validate(p, vault)
        field_names = [e.field for e in errors]
        assert "current_level" in field_names
        assert "target_level" in field_names

    def test_incident_missing_fields(self, vault: Path) -> None:
        p = _write_note(vault, "work/incidents/outage.md", (
            "---\n"
            "date: 2026-04-04\n"
            "description: \"Production outage\"\n"
            "tags:\n  - incident\n"
            "---\n\nContent.\n"
        ))
        errors = validate(p, vault)
        field_names = [e.field for e in errors]
        assert "ticket" in field_names
        assert "severity" in field_names


# ---------------------------------------------------------------------------
# Exclusion paths
# ---------------------------------------------------------------------------

class TestExclusions:
    def test_template_excluded(self, vault: Path) -> None:
        p = _write_note(vault, "templates/Work Note.md", (
            "---\ndate: {{date}}\ntags:\n  - work-note\n---\n"
        ))
        errors = validate(p, vault)
        assert errors == []

    def test_claude_dir_excluded(self, vault: Path) -> None:
        p = _write_note(vault, ".claude/commands/standup.md", (
            "No frontmatter here.\n"
        ))
        errors = validate(p, vault)
        assert errors == []

    def test_codex_dir_excluded(self, vault: Path) -> None:
        p = _write_note(vault, ".codex/agents/cross-linker.md", (
            "No frontmatter here.\n"
        ))
        errors = validate(p, vault)
        assert errors == []

    def test_thinking_excluded(self, vault: Path) -> None:
        p = _write_note(vault, "thinking/2026-04-04-draft.md", (
            "Just a draft, no frontmatter.\n"
        ))
        errors = validate(p, vault)
        assert errors == []

    def test_root_claude_md_excluded(self, vault: Path) -> None:
        p = vault / "CLAUDE.md"
        errors = validate(p, vault)
        assert errors == []

    def test_nested_claude_md_excluded(self, vault: Path) -> None:
        # Workspace-scoped operating files (work/CLAUDE.md, personal/CLAUDE.md)
        # carry rules, not vault notes — they must be excluded at ANY depth,
        # not just the vault root.
        p = _write_note(
            vault, "work/CLAUDE.md", "# Work workspace rules\nNo frontmatter.\n"
        )
        errors = validate(p, vault)
        assert errors == []

    def test_nested_agents_md_excluded(self, vault: Path) -> None:
        p = _write_note(
            vault, "work/AGENTS.md", "# Work workspace rules\nNo frontmatter.\n"
        )
        errors = validate(p, vault)
        assert errors == []

    def test_root_setup_md_excluded(self, vault: Path) -> None:
        p = _write_note(vault, "SETUP.md", "Setup content")
        errors = validate(p, vault)
        assert errors == []

    def test_obsidian_excluded(self, vault: Path) -> None:
        p = _write_note(vault, ".obsidian/plugins/test.md", "Plugin stuff")
        errors = validate(p, vault)
        assert errors == []

    def test_dotfile_excluded(self, vault: Path) -> None:
        p = _write_note(vault, ".gitignore", "*.pyc")
        errors = validate(p, vault)
        assert errors == []

    def test_brain_dir_excluded(self, vault: Path) -> None:
        # .brain/ holds ephemeral session state (handoff, notebook, gardener
        # queue) — markdown without frontmatter by design; never validate it.
        p = _write_note(vault, ".brain/handoff-personal.md", "Resume notes, no frontmatter.\n")
        errors = validate(p, vault)
        assert errors == []


# ---------------------------------------------------------------------------
# YAML parse errors (warning, not blocking — decision 4A)
# ---------------------------------------------------------------------------

class TestYamlParseErrors:
    def test_malformed_yaml_is_warning(self, vault: Path) -> None:
        p = _write_note(vault, "brain/bad-yaml.md", (
            "---\n"
            "date: 2026-04-04\n"
            "tags: [unclosed\n"
            "---\n\nContent.\n"
        ))
        errors = validate(p, vault)
        assert len(errors) == 1
        assert errors[0].severity == "warning"
        assert "YAML" in errors[0].message

    def test_no_frontmatter_at_all(self, vault: Path) -> None:
        p = _write_note(vault, "brain/no-fm.md", (
            "# Just a heading\n\nNo frontmatter here.\n"
        ))
        errors = validate(p, vault)
        assert len(errors) == 1
        assert errors[0].severity == "warning"


# ---------------------------------------------------------------------------
# Non-markdown files
# ---------------------------------------------------------------------------

class TestNonMarkdown:
    def test_python_file_skipped(self, vault: Path) -> None:
        p = vault / "scripts" / "test.py"
        p.parent.mkdir(exist_ok=True)
        p.write_text("print('hello')")
        errors = validate(p, vault)
        assert errors == []

    def test_json_file_skipped(self, vault: Path) -> None:
        p = vault / "data.json"
        p.write_text("{}")
        errors = validate(p, vault)
        assert errors == []


# ---------------------------------------------------------------------------
# generate()
# ---------------------------------------------------------------------------

class TestGenerate:
    def test_generate_work_note(self) -> None:
        result = generate("work-note", {
            "date": "2026-04-04",
            "description": "My project note",
            "project": "Pipeline Redesign",
        })
        assert "---" in result
        assert "work-note" in result
        assert "Pipeline Redesign" in result
        assert "status:" in result
        assert "project:" in result

    def test_generate_decision(self) -> None:
        result = generate("decision", {
            "date": "2026-04-04",
            "description": "Use Snowflake",
        })
        assert "decision" in result
        assert "status:" in result

    def test_generate_defaults_date_to_today(self) -> None:
        from datetime import date
        result = generate("idea")
        assert date.today().isoformat() in result

    def test_generate_unknown_type(self) -> None:
        result = generate("custom-type", {
            "date": "2026-04-04",
            "description": "Custom note",
        })
        assert "custom-type" in result
        assert "date:" in result


# ---------------------------------------------------------------------------
# Tasks type validation
# ---------------------------------------------------------------------------

class TestTasksType:
    def test_valid_tasks_note(self, vault: Path) -> None:
        p = _write_note(vault, "personal/tasks/2026-W14-tasks.md", (
            "---\n"
            "date: 2026-04-04\n"
            "description: \"Personal tasks for week 14, 2026\"\n"
            "tags:\n  - tasks\n"
            "week: \"2026-W14\"\n"
            "---\n\n# Tasks — 2026-W14\n"
        ))
        errors = validate(p, vault)
        assert errors == []

    def test_missing_week_field(self, vault: Path) -> None:
        p = _write_note(vault, "personal/tasks/no-week.md", (
            "---\n"
            "date: 2026-04-04\n"
            "description: \"Personal tasks\"\n"
            "tags:\n  - tasks\n"
            "---\n\n# Tasks\n"
        ))
        errors = validate(p, vault)
        field_names = [e.field for e in errors]
        assert "week" in field_names

    def test_generate_tasks_type(self) -> None:
        result = generate("tasks", {
            "date": "2026-04-04",
            "description": "Personal tasks for week 14, 2026",
            "week": "2026-W14",
        })
        assert "tasks" in result
        assert "week:" in result
        assert "2026-W14" in result
