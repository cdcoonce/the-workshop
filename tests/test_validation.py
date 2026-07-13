"""Tests for build validation — bad manifests cause fail-fast errors (D19)."""

import json
from pathlib import Path

import pytest

from scripts.build_preset import build_preset, BuildValidationError


class TestValidation:
    """Build fails fast on invalid input."""

    def test_missing_preset_raises_error(self, tmp_repo: Path) -> None:
        with pytest.raises(BuildValidationError, match="not-a-preset"):
            build_preset("not-a-preset", repo_root=tmp_repo)

    def test_missing_preset_skill_raises_error(self, bad_manifest_repo: Path) -> None:
        with pytest.raises(BuildValidationError, match="nonexistent-skill"):
            build_preset("broken", repo_root=bad_manifest_repo)

    def test_missing_core_skill_in_list_raises_error(self, tmp_repo: Path) -> None:
        manifest_path = tmp_repo / "presets" / "python-api" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["core"]["skills"] = ["commit", "nonexistent-core-skill"]
        manifest_path.write_text(json.dumps(manifest))

        with pytest.raises(BuildValidationError, match="nonexistent-core-skill"):
            build_preset("python-api", repo_root=tmp_repo)

    def test_core_skills_typo_scalar_raises_error(self, tmp_repo: Path) -> None:
        manifest_path = tmp_repo / "presets" / "python-api" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["core"]["skills"] = "alll"
        manifest_path.write_text(json.dumps(manifest))

        with pytest.raises(BuildValidationError, match="core.skills"):
            build_preset("python-api", repo_root=tmp_repo)

    def test_core_agents_typo_scalar_raises_error(self, tmp_repo: Path) -> None:
        manifest_path = tmp_repo / "presets" / "python-api" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["core"]["agents"] = "none"
        manifest_path.write_text(json.dumps(manifest))

        with pytest.raises(BuildValidationError, match="core.agents"):
            build_preset("python-api", repo_root=tmp_repo)

    def test_missing_preset_hook_raises_error(self, tmp_repo: Path) -> None:
        preset = tmp_repo / "presets" / "bad-hook"
        preset.mkdir()
        (preset / "manifest.json").write_text(
            json.dumps(
                {
                    "name": "bad-hook",
                    "description": "Bad hook reference",
                    "core": {"skills": "all", "hooks": ["protect-files.py"]},
                    "exclude": [],
                    "preset_skills": [],
                    "preset_hooks": ["missing-hook.py"],
                }
            )
        )
        (preset / "settings-preset.json").write_text(json.dumps({"hooks": {}}))
        preset_hooks = preset / "hooks"
        preset_hooks.mkdir()

        with pytest.raises(BuildValidationError, match="missing-hook.py"):
            build_preset("bad-hook", repo_root=tmp_repo)

    def test_missing_core_hook_raises_error(self, tmp_repo: Path) -> None:
        preset = tmp_repo / "presets" / "python-api"
        manifest_path = preset / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["core"]["hooks"] = ["nonexistent-hook.py"]
        manifest_path.write_text(json.dumps(manifest))

        with pytest.raises(BuildValidationError, match="nonexistent-hook.py"):
            build_preset("python-api", repo_root=tmp_repo)

    def test_exclude_conflicts_with_preset_skill(self, tmp_repo: Path) -> None:
        preset = tmp_repo / "presets" / "conflict"
        preset.mkdir()
        (preset / "manifest.json").write_text(
            json.dumps(
                {
                    "name": "conflict",
                    "description": "Conflict test",
                    "core": {"skills": "all", "hooks": ["protect-files.py"]},
                    "exclude": ["skills/deploy"],
                    "preset_skills": ["deploy"],
                    "preset_hooks": [],
                }
            )
        )
        (preset / "settings-preset.json").write_text(json.dumps({"hooks": {}}))
        preset_skills = preset / "skills" / "deploy"
        preset_skills.mkdir(parents=True)
        (preset_skills / "SKILL.md").write_text("# deploy")

        with pytest.raises(
            BuildValidationError, match="both preset_skills and exclude"
        ):
            build_preset("conflict", repo_root=tmp_repo)

    def test_conventions_must_be_list_of_strings(self, tmp_repo: Path) -> None:
        manifest_path = tmp_repo / "presets" / "python-api" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["conventions"] = "not a list"
        manifest_path.write_text(json.dumps(manifest))

        with pytest.raises(BuildValidationError, match="conventions must be a list"):
            build_preset("python-api", repo_root=tmp_repo)

    def test_conventions_list_of_strings_accepted(self, tmp_repo: Path) -> None:
        manifest_path = tmp_repo / "presets" / "python-api" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["conventions"] = ["Ruff linting", "Structured logging"]
        manifest_path.write_text(json.dumps(manifest))

        dist = build_preset("python-api", repo_root=tmp_repo)
        assert "Ruff linting" in (dist / "README.md").read_text()
