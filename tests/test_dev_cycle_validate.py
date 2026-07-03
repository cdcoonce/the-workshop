"""Tests for dev_cycle_validate — state file parser and validator."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.dev_cycle_validate import parse_state_file, validate_state_file
from scripts.dev_cycle_validate import validate_directory


class TestParseStateFile:
    """Tests for YAML frontmatter parsing."""

    def test_parse_valid_state_file(self, tmp_path: Path) -> None:
        content = """\
---
schema_version: 1
feature: dark-mode-toggle
status: in_progress
current_phase: plan
created: 2026-03-21
updated: 2026-03-21
branch: feat/dark-mode-toggle
---

## Artifacts

| Phase       | Status      | Artifact                               |
| ----------- | ----------- | -------------------------------------- |
| brainstorm  | completed   | https://github.com/user/repo/issues/42 |
| plan        | in_progress | docs/plans/dark-mode-toggle.md         |
| ceo_review  | pending     | —                                      |

## Log

- 2026-03-21 10:15 — Brainstorm complete.
"""
        state_file = tmp_path / "dark-mode-toggle.state.md"
        state_file.write_text(content)

        result = parse_state_file(state_file)

        assert result.schema_version == 1
        assert result.feature == "dark-mode-toggle"
        assert result.status == "in_progress"
        assert result.current_phase == "plan"
        assert result.branch == "feat/dark-mode-toggle"
        assert result.path == state_file

    def test_parse_missing_frontmatter_raises(self, tmp_path: Path) -> None:
        state_file = tmp_path / "bad.md"
        state_file.write_text("# No frontmatter here\n")

        with pytest.raises(ValueError, match="frontmatter"):
            parse_state_file(state_file)

    def test_parse_missing_required_field_raises(self, tmp_path: Path) -> None:
        content = """\
---
schema_version: 1
feature: dark-mode-toggle
---
"""
        state_file = tmp_path / "incomplete.md"
        state_file.write_text(content)

        with pytest.raises(ValueError, match="status"):
            parse_state_file(state_file)

    def test_parse_missing_schema_version_defaults_to_1(self, tmp_path: Path) -> None:
        content = """\
---
feature: test-feature
status: in_progress
current_phase: plan
created: 2026-03-21
updated: 2026-03-21
---

## Artifacts

## Log
"""
        state_file = tmp_path / "test-feature.state.md"
        state_file.write_text(content)

        result = parse_state_file(state_file)
        assert result.schema_version == 1


class TestValidateStateFile:
    """Tests for field value validation."""

    def _write_state_file(self, tmp_path: Path, **overrides: str) -> Path:
        """Helper: write a valid state file, then override specific fields."""
        defaults = {
            "schema_version": "1",
            "feature": "test-feature",
            "status": "in_progress",
            "current_phase": "plan",
            "created": "2026-03-21",
            "updated": "2026-03-21",
            "branch": "",
        }
        defaults.update(overrides)
        fields = "\n".join(f"{k}: {v}" for k, v in defaults.items() if v)
        content = f"---\n{fields}\n---\n\n## Artifacts\n\n## Log\n"
        path = tmp_path / f"{defaults['feature']}.state.md"
        path.write_text(content)
        return path

    def test_valid_file_passes(self, tmp_path: Path) -> None:
        path = self._write_state_file(tmp_path)
        result = validate_state_file(path)
        assert result.passed

    def test_invalid_status_fails(self, tmp_path: Path) -> None:
        path = self._write_state_file(tmp_path, status="bogus")
        result = validate_state_file(path)
        assert not result.passed
        assert any("status" in e for e in result.errors)

    def test_invalid_phase_fails(self, tmp_path: Path) -> None:
        path = self._write_state_file(tmp_path, current_phase="testing")
        result = validate_state_file(path)
        assert not result.passed
        assert any("current_phase" in e for e in result.errors)

    def test_unsupported_schema_version_fails(self, tmp_path: Path) -> None:
        path = self._write_state_file(tmp_path, schema_version="99")
        result = validate_state_file(path)
        assert not result.passed
        assert any("schema_version" in e for e in result.errors)

    def test_missing_schema_version_produces_warning(self, tmp_path: Path) -> None:
        path = self._write_state_file(tmp_path, schema_version="")
        result = validate_state_file(path)
        assert result.passed
        assert any("schema_version" in w for w in result.warnings)

    def test_feature_slug_mismatch_fails(self, tmp_path: Path) -> None:
        """Feature slug must match the filename."""
        path = self._write_state_file(tmp_path, feature="wrong-name")
        # File is named 'wrong-name.md' by the helper, so rename it
        renamed = tmp_path / "different-name.state.md"
        path.rename(renamed)
        result = validate_state_file(renamed)
        assert not result.passed
        assert any("filename" in e for e in result.errors)


class TestArtifactCompleteness:
    """Completed phases must have non-empty artifacts."""

    def test_completed_phase_without_artifact_fails(self, tmp_path: Path) -> None:
        content = """\
---
schema_version: 1
feature: test-feature
status: in_progress
current_phase: plan
created: 2026-03-21
updated: 2026-03-21
---

## Artifacts

| Phase       | Status      | Artifact |
| ----------- | ----------- | -------- |
| brainstorm  | completed   | —        |
| plan        | in_progress | —        |

## Log
"""
        path = tmp_path / "test-feature.state.md"
        path.write_text(content)
        result = validate_state_file(path)
        assert not result.passed
        assert any("brainstorm" in e and "artifact" in e.lower() for e in result.errors)

    def test_completed_phase_with_artifact_passes(self, tmp_path: Path) -> None:
        content = """\
---
schema_version: 1
feature: test-feature
status: in_progress
current_phase: plan
created: 2026-03-21
updated: 2026-03-21
---

## Artifacts

| Phase       | Status      | Artifact                               |
| ----------- | ----------- | -------------------------------------- |
| brainstorm  | completed   | https://github.com/user/repo/issues/42 |
| plan        | in_progress | docs/plans/test-feature.md             |

## Log
"""
        path = tmp_path / "test-feature.state.md"
        path.write_text(content)
        result = validate_state_file(path)
        assert result.passed

    def test_invalid_artifact_status_fails(self, tmp_path: Path) -> None:
        content = """\
---
schema_version: 1
feature: test-feature
status: in_progress
current_phase: plan
created: 2026-03-21
updated: 2026-03-21
---

## Artifacts

| Phase       | Status      | Artifact                    |
| ----------- | ----------- | ---------------------------- |
| brainstorm  | done        | docs/plans/test-feature.md   |

## Log
"""
        path = tmp_path / "test-feature.state.md"
        path.write_text(content)
        result = validate_state_file(path)
        assert not result.passed
        assert any("brainstorm" in e and "done" in e for e in result.errors)


class TestValidateDirectory:
    """Tests for scanning docs/dev-cycle/ for slug collisions."""

    def test_no_collisions_passes(self, tmp_path: Path) -> None:
        dev_cycle = tmp_path / "docs" / "dev-cycle"
        dev_cycle.mkdir(parents=True)
        for name in ("feature-a", "feature-b"):
            (dev_cycle / f"{name}.state.md").write_text(
                f"---\nschema_version: 1\nfeature: {name}\n"
                f"status: in_progress\ncurrent_phase: brainstorm\n"
                f"created: 2026-03-21\nupdated: 2026-03-21\n---\n\n"
                f"## Artifacts\n\n## Log\n"
            )
        result = validate_directory(dev_cycle)
        assert result.passed

    def test_detects_slug_collision(self, tmp_path: Path) -> None:
        """Two files with the same feature slug is a collision.

        Note: feature-a-copy.md having feature=feature-a also triggers
        the slug-mismatch check. This is by design — a true collision
        necessarily co-produces a mismatch for at least one file.
        """
        dev_cycle = tmp_path / "docs" / "dev-cycle"
        dev_cycle.mkdir(parents=True)
        for filename in ("feature-a.state.md", "feature-a-copy.state.md"):
            (dev_cycle / filename).write_text(
                "---\nschema_version: 1\nfeature: feature-a\n"
                "status: in_progress\ncurrent_phase: brainstorm\n"
                "created: 2026-03-21\nupdated: 2026-03-21\n---\n\n"
                "## Artifacts\n\n## Log\n"
            )
        result = validate_directory(dev_cycle)
        assert not result.passed
        assert any(
            "collision" in e.lower() or "duplicate" in e.lower() for e in result.errors
        )

    def test_missing_schema_version_warning_in_directory(self, tmp_path: Path) -> None:
        dev_cycle = tmp_path / "docs" / "dev-cycle"
        dev_cycle.mkdir(parents=True)
        (dev_cycle / "feat-a.state.md").write_text(
            "---\nfeature: feat-a\n"
            "status: in_progress\ncurrent_phase: brainstorm\n"
            "created: 2026-03-21\nupdated: 2026-03-21\n---\n\n"
            "## Artifacts\n\n## Log\n"
        )
        result = validate_directory(dev_cycle)
        assert result.passed
        assert len(result.warnings) > 0

    def test_empty_directory_passes(self, tmp_path: Path) -> None:
        dev_cycle = tmp_path / "docs" / "dev-cycle"
        dev_cycle.mkdir(parents=True)
        result = validate_directory(dev_cycle)
        assert result.passed


import subprocess


class TestCLI:
    """Tests for the command-line interface."""

    def test_cli_reports_valid_directory(self, tmp_path: Path) -> None:
        dev_cycle = tmp_path / "docs" / "dev-cycle"
        dev_cycle.mkdir(parents=True)
        (dev_cycle / "feat-a.state.md").write_text(
            "---\nschema_version: 1\nfeature: feat-a\n"
            "status: in_progress\ncurrent_phase: brainstorm\n"
            "created: 2026-03-21\nupdated: 2026-03-21\n---\n\n"
            "## Artifacts\n\n## Log\n"
        )
        result = subprocess.run(
            ["uv", "run", "python", "scripts/dev_cycle_validate.py", str(dev_cycle)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "PASS" in result.stdout

    def test_cli_prints_warnings_but_passes(self, tmp_path: Path) -> None:
        dev_cycle = tmp_path / "docs" / "dev-cycle"
        dev_cycle.mkdir(parents=True)
        (dev_cycle / "feat-a.state.md").write_text(
            "---\nfeature: feat-a\n"
            "status: in_progress\ncurrent_phase: brainstorm\n"
            "created: 2026-03-21\nupdated: 2026-03-21\n---\n\n"
            "## Artifacts\n\n## Log\n"
        )
        result = subprocess.run(
            ["uv", "run", "python", "scripts/dev_cycle_validate.py", str(dev_cycle)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "WARNING" in result.stdout

    def test_cli_reports_errors(self, tmp_path: Path) -> None:
        dev_cycle = tmp_path / "docs" / "dev-cycle"
        dev_cycle.mkdir(parents=True)
        (dev_cycle / "bad.state.md").write_text(
            "---\nschema_version: 1\nfeature: bad\n"
            "status: bogus\ncurrent_phase: brainstorm\n"
            "created: 2026-03-21\nupdated: 2026-03-21\n---\n\n"
            "## Artifacts\n\n## Log\n"
        )
        result = subprocess.run(
            ["uv", "run", "python", "scripts/dev_cycle_validate.py", str(dev_cycle)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1
        assert "FAIL" in result.stdout
