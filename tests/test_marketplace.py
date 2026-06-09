"""Tests for marketplace.json generation."""

import json
from pathlib import Path

import pytest

from scripts.build_marketplace import build_marketplace


class TestBuildMarketplace:
    """build_marketplace generates .claude-plugin/marketplace.json at repo root."""

    def test_creates_marketplace_json_file(self, tmp_repo: Path) -> None:
        build_marketplace(tmp_repo)
        marketplace_path = tmp_repo / ".claude-plugin" / "marketplace.json"
        assert marketplace_path.exists()

    def test_marketplace_json_is_valid_json(self, tmp_repo: Path) -> None:
        build_marketplace(tmp_repo)
        marketplace_path = tmp_repo / ".claude-plugin" / "marketplace.json"
        data = json.loads(marketplace_path.read_text())
        assert "plugins" in data

    def test_marketplace_has_name(self, tmp_repo: Path) -> None:
        build_marketplace(tmp_repo)
        marketplace_path = tmp_repo / ".claude-plugin" / "marketplace.json"
        data = json.loads(marketplace_path.read_text())
        assert data["name"] == "claude-workflow"

    def test_marketplace_has_owner(self, tmp_repo: Path) -> None:
        build_marketplace(tmp_repo)
        marketplace_path = tmp_repo / ".claude-plugin" / "marketplace.json"
        data = json.loads(marketplace_path.read_text())
        assert "owner" in data
        assert "name" in data["owner"]

    def test_marketplace_lists_all_presets(self, tmp_repo: Path) -> None:
        """All presets under presets/ appear in the plugins list."""
        build_marketplace(tmp_repo)
        marketplace_path = tmp_repo / ".claude-plugin" / "marketplace.json"
        data = json.loads(marketplace_path.read_text())
        names = [p["name"] for p in data["plugins"]]
        assert "python-api" in names

    def test_marketplace_plugin_has_required_fields(self, tmp_repo: Path) -> None:
        build_marketplace(tmp_repo)
        marketplace_path = tmp_repo / ".claude-plugin" / "marketplace.json"
        data = json.loads(marketplace_path.read_text())
        for plugin in data["plugins"]:
            assert "name" in plugin
            assert "version" in plugin
            assert "description" in plugin
            assert "source" in plugin

    def test_marketplace_plugin_source_points_to_dist(self, tmp_repo: Path) -> None:
        build_marketplace(tmp_repo)
        marketplace_path = tmp_repo / ".claude-plugin" / "marketplace.json"
        data = json.loads(marketplace_path.read_text())
        for plugin in data["plugins"]:
            assert plugin["source"].startswith("./dist/")

    def test_marketplace_description_from_manifest(self, tmp_repo: Path) -> None:
        build_marketplace(tmp_repo)
        marketplace_path = tmp_repo / ".claude-plugin" / "marketplace.json"
        data = json.loads(marketplace_path.read_text())
        python_api = [p for p in data["plugins"] if p["name"] == "python-api"][0]
        assert python_api["description"] == "Python backend services"

    def test_marketplace_plugins_sorted_by_name(self, tmp_repo: Path) -> None:
        """Plugins are listed in alphabetical order for consistency."""
        # Add a second preset so we can verify sorting
        second_preset = tmp_repo / "presets" / "alpha-preset"
        second_preset.mkdir()
        (second_preset / "manifest.json").write_text(
            json.dumps(
                {
                    "name": "alpha-preset",
                    "description": "Alpha preset for testing sort order",
                    "version": "1.0.0",
                    "core": {"skills": "all", "hooks": ["protect-files.py"]},
                    "exclude": [],
                    "preset_skills": [],
                    "preset_hooks": [],
                }
            )
        )

        build_marketplace(tmp_repo)
        marketplace_path = tmp_repo / ".claude-plugin" / "marketplace.json"
        data = json.loads(marketplace_path.read_text())
        names = [p["name"] for p in data["plugins"]]
        assert names == sorted(names)

    def test_marketplace_creates_directory_if_missing(self, tmp_repo: Path) -> None:
        """The .claude-plugin/ directory is created if it does not exist."""
        claude_plugin_dir = tmp_repo / ".claude-plugin"
        assert not claude_plugin_dir.exists()
        build_marketplace(tmp_repo)
        assert claude_plugin_dir.exists()

    def test_marketplace_skips_preset_dir_without_manifest(
        self, tmp_repo: Path
    ) -> None:
        """Preset directories without manifest.json are silently skipped."""
        (tmp_repo / "presets" / "no-manifest-preset").mkdir()
        build_marketplace(tmp_repo)
        marketplace_path = tmp_repo / ".claude-plugin" / "marketplace.json"
        data = json.loads(marketplace_path.read_text())
        names = [p["name"] for p in data["plugins"]]
        assert "no-manifest-preset" not in names

    def test_marketplace_skips_non_directory_in_presets(self, tmp_repo: Path) -> None:
        """Non-directory files in presets/ are ignored."""
        (tmp_repo / "presets" / "README.md").write_text("# Presets")
        build_marketplace(tmp_repo)
        marketplace_path = tmp_repo / ".claude-plugin" / "marketplace.json"
        data = json.loads(marketplace_path.read_text())
        # Should still have exactly the presets that existed before
        names = [p["name"] for p in data["plugins"]]
        assert "python-api" in names

    def test_marketplace_manifest_missing_name_raises_clear_error(
        self, tmp_repo: Path
    ) -> None:
        """A manifest missing 'name' raises an error naming the offending preset."""
        broken = tmp_repo / "presets" / "nameless-preset"
        broken.mkdir()
        (broken / "manifest.json").write_text(
            json.dumps(
                {
                    "description": "Manifest with no name field",
                    "version": "1.0.0",
                }
            )
        )

        with pytest.raises(ValueError, match="nameless-preset"):
            build_marketplace(tmp_repo)
