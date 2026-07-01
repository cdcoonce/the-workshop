"""Tests for marketplace.json generation."""

import json
from pathlib import Path

from scripts.build_marketplace import _scan_presets, build_marketplace


class TestBuildMarketplace:
    """build_marketplace generates .claude-plugin/marketplace.json at repo root."""

    def test_creates_marketplace_json_file(self, tmp_repo: Path) -> None:
        build_marketplace(tmp_repo)
        marketplace_path = tmp_repo / ".claude-plugin" / "marketplace.json"
        assert marketplace_path.exists()

    def test_creates_codex_marketplace_json_file(self, tmp_repo: Path) -> None:
        build_marketplace(tmp_repo)
        marketplace_path = tmp_repo / ".agents" / "plugins" / "marketplace.json"
        assert marketplace_path.exists()

    def test_codex_marketplace_has_expected_shape(self, tmp_repo: Path) -> None:
        build_marketplace(tmp_repo)
        marketplace_path = tmp_repo / ".agents" / "plugins" / "marketplace.json"
        data = json.loads(marketplace_path.read_text())
        assert data["name"] == "claude-workflow"
        assert data["interface"]["displayName"] == "Claude Workflow"
        for plugin in data["plugins"]:
            assert plugin["source"]["source"] == "local"
            assert plugin["source"]["path"].startswith("./dist/")
            assert plugin["policy"] == {
                "installation": "AVAILABLE",
                "authentication": "ON_INSTALL",
            }
            assert plugin["category"] == "Productivity"

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
        (second_preset / "manifest.json").write_text(json.dumps({
            "name": "alpha-preset",
            "description": "Alpha preset for testing sort order",
            "version": "1.0.0",
            "core": {"skills": "all", "hooks": ["protect-files.py"]},
            "exclude": [],
            "preset_skills": [],
            "preset_hooks": [],
        }))

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

    def test_marketplace_skips_preset_dir_without_manifest(self, tmp_repo: Path) -> None:
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


class TestScanPresets:
    """Unit tests for _scan_presets helper."""

    def test_returns_list_of_dicts(self, tmp_repo: Path) -> None:
        result = _scan_presets(tmp_repo / "presets")
        assert isinstance(result, list)
        assert all(isinstance(item, dict) for item in result)

    def test_includes_preset_with_manifest(self, tmp_repo: Path) -> None:
        result = _scan_presets(tmp_repo / "presets")
        names = [p["name"] for p in result]
        assert "python-api" in names

    def test_entry_has_required_fields(self, tmp_repo: Path) -> None:
        result = _scan_presets(tmp_repo / "presets")
        for entry in result:
            assert "name" in entry
            assert "version" in entry
            assert "description" in entry
            assert "source" in entry

    def test_source_uses_dist_prefix(self, tmp_repo: Path) -> None:
        result = _scan_presets(tmp_repo / "presets")
        for entry in result:
            assert entry["source"].startswith("./dist/")

    def test_skips_dir_without_manifest(self, tmp_repo: Path) -> None:
        (tmp_repo / "presets" / "bare-dir").mkdir()
        result = _scan_presets(tmp_repo / "presets")
        names = [p["name"] for p in result]
        assert "bare-dir" not in names

    def test_skips_non_directory_entries(self, tmp_repo: Path) -> None:
        (tmp_repo / "presets" / "README.md").write_text("# hi")
        result = _scan_presets(tmp_repo / "presets")
        names = [p["name"] for p in result]
        assert "README.md" not in names
