
import pytest

from scripts.installer.bundle import Bundle, BundleError


def test_load_returns_bundle_for_valid_preset(tmp_path, make_preset):
    make_preset(tmp_path, "data-pipeline")
    b = Bundle.load(tmp_path, "data-pipeline")
    assert b.name == "data-pipeline"
    assert b.path == tmp_path / "data-pipeline"


def test_load_raises_for_missing_preset(tmp_path):
    with pytest.raises(BundleError):
        Bundle.load(tmp_path, "nope")


def test_available_lists_only_valid_presets(tmp_path, make_preset):
    make_preset(tmp_path, "analysis")
    make_preset(tmp_path, "data-pipeline")
    (tmp_path / "not-a-preset").mkdir()  # no .claude-plugin/plugin.json
    assert Bundle.available(tmp_path) == ["analysis", "data-pipeline"]
