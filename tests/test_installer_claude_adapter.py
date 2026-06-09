import json

import pytest

from scripts.installer.adapters import ClaudeCodeAdapter, adapter_names, get_adapter
from scripts.installer.bundle import Bundle
from scripts.installer.report import Scope


def test_get_adapter_unknown_raises():
    with pytest.raises(KeyError):
        get_adapter("does-not-exist")


def test_claude_code_is_registered():
    assert "claude-code" in adapter_names()


def _make_preset(root, name):
    p = root / name / ".claude-plugin"
    p.mkdir(parents=True)
    (p / "plugin.json").write_text(json.dumps({"name": name, "version": "1.0.0"}))
    (root / name / "skills").mkdir()
    (root / name / "skills" / "s.md").write_text("# skill")
    return root / name


def test_detect_true_when_claude_dir_present(tmp_path):
    (tmp_path / ".claude").mkdir()
    assert ClaudeCodeAdapter().detect(tmp_path) is True


def test_detect_false_on_bare_dir(tmp_path):
    assert ClaudeCodeAdapter().detect(tmp_path) is False


def test_install_places_plugin_and_reports(tmp_path):
    presets = tmp_path / "presets"
    presets.mkdir()
    _make_preset(presets, "data-pipeline")
    repo = tmp_path / "repo"
    repo.mkdir()

    report = ClaudeCodeAdapter().install(
        Bundle.load(presets, "data-pipeline"), repo, Scope.PROJECT
    )

    dest = repo / ".claude" / "plugins" / "data-pipeline"
    assert (dest / ".claude-plugin" / "plugin.json").is_file()
    assert (dest / "skills" / "s.md").is_file()
    assert report.installed and not report.skipped


def test_install_is_idempotent(tmp_path):
    presets = tmp_path / "presets"
    presets.mkdir()
    _make_preset(presets, "data-pipeline")
    repo = tmp_path / "repo"
    repo.mkdir()
    adapter = ClaudeCodeAdapter()
    bundle = Bundle.load(presets, "data-pipeline")

    adapter.install(bundle, repo, Scope.PROJECT)
    adapter.install(bundle, repo, Scope.PROJECT)  # second run must not raise

    assert (repo / ".claude" / "plugins" / "data-pipeline" / "skills" / "s.md").is_file()


def test_uninstall_removes_then_reports_skip_when_absent(tmp_path):
    presets = tmp_path / "presets"
    presets.mkdir()
    _make_preset(presets, "data-pipeline")
    repo = tmp_path / "repo"
    repo.mkdir()
    adapter = ClaudeCodeAdapter()
    adapter.install(Bundle.load(presets, "data-pipeline"), repo, Scope.PROJECT)

    r1 = adapter.uninstall(repo, "data-pipeline")
    assert not (repo / ".claude" / "plugins" / "data-pipeline").exists()
    assert r1.installed  # recorded the removal

    r2 = adapter.uninstall(repo, "data-pipeline")  # already gone
    assert r2.skipped == [("data-pipeline", "not installed")]
