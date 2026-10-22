"""check-plugin.sh answers three questions: is the plugin running, is the running
copy the current one, and do the platforms agree.

Every test runs the real script from a scratch vault against hand-written
breadcrumbs shaped like the ones ``vault-session-start.py`` writes.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "workbench"
CHECK_PLUGIN = PLUGIN / "machinery" / "scaffold" / "vault" / "check-plugin.sh"


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    (tmp_path / ".vault").mkdir()
    shutil.copy2(CHECK_PLUGIN, tmp_path / ".vault" / "check-plugin.sh")
    (tmp_path / ".vault" / "vault.json").write_text('{"min_plugin_version": "1.0.0"}\n')
    return tmp_path


def _crumb(vault: Path, name: str, *, version: str = "9.9.9", session: str | None = "s1",
           root: Path | None = None, platform: str = "claude-code") -> Path:
    record = {"root": str(root or vault / "cache" / version), "version": version, "platform": platform}
    if session is not None:
        record["session"] = session
    path = vault / ".vault" / name
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    return path


def _check(vault: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(vault / ".vault" / "check-plugin.sh")], capture_output=True, text=True, timeout=30
    )


def _sessions(vault: Path, count: int, *, start: int = 0) -> list[subprocess.CompletedProcess[str]]:
    """Run ``count`` sessions, each with a fresh session marker (the plugin ran)."""
    results = []
    for index in range(start, start + count):
        _crumb(vault, "plugin-state.json", session=f"live-{index}")
        _crumb(vault, "plugin-state.claude-code.json", session=f"live-{index}")
        results.append(_check(vault))
    return results


def test_a_plugin_that_runs_every_session_never_warns(vault: Path) -> None:
    for result in _sessions(vault, 8):
        assert result.returncode == 0
        assert result.stderr == ""


def test_an_unchanged_session_marker_warns_with_version_and_count(vault: Path) -> None:
    _crumb(vault, "plugin-state.json", version="8.10.0", session="frozen")
    results = [_check(vault) for _ in range(5)]

    warned = [r for r in results if "NOT RUNNING" in r.stderr]
    assert warned, "a marker unchanged for several sessions never warned"
    assert "8.10.0" in warned[-1].stderr
    assert any(str(n) in warned[-1].stderr for n in (3, 4))
    assert results[0].stderr == "" and results[1].stderr == ""


def test_a_removed_plugin_leaves_a_stale_breadcrumb_that_warns_within_n_sessions(vault: Path) -> None:
    _sessions(vault, 2)
    # The plugin is uninstalled: the files remain, nothing rewrites them.
    results = [_check(vault) for _ in range(6)]

    assert any("NOT RUNNING" in r.stderr for r in results)
    assert all(r.returncode == 0 for r in results)


def test_a_resumed_plugin_resets_the_stale_count(vault: Path) -> None:
    _crumb(vault, "plugin-state.json", session="frozen")
    for _ in range(5):
        _check(vault)
    assert _sessions(vault, 3)[-1].stderr == ""
    _crumb(vault, "plugin-state.json", session="frozen-again")
    assert _check(vault).stderr == ""


def test_the_missing_breadcrumb_branch_still_warns_after_the_grace_session(vault: Path) -> None:
    first, second = _check(vault), _check(vault)

    assert first.stderr == ""
    assert "VAULT PLUGIN MISSING" in second.stderr
    assert second.returncode == 0


def test_a_recorded_root_carrying_orphaned_at_warns_to_restart(vault: Path) -> None:
    root = vault / "cache" / "8.8.0"
    root.mkdir(parents=True)
    (root / ".orphaned_at").write_text("1758319010591")
    _crumb(vault, "plugin-state.json", version="8.8.0", root=root, session="live-1")

    result = _check(vault)

    assert result.returncode == 0
    assert "SUPERSEDED" in result.stderr
    assert "8.8.0" in result.stderr
    assert "restart" in result.stderr.lower()
    assert "update workbench" not in result.stderr


def test_a_recorded_root_without_the_marker_convention_is_silent(vault: Path) -> None:
    root = vault / "cache" / "8.10.0"
    (vault / "cache" / "8.9.0").mkdir(parents=True)
    root.mkdir(parents=True)
    _crumb(vault, "plugin-state.json", version="8.10.0", root=root, session="live-1")

    result = _check(vault)

    assert result.returncode == 0
    assert result.stderr == ""


def test_a_root_that_no_longer_exists_is_not_treated_as_superseded(vault: Path) -> None:
    _crumb(vault, "plugin-state.json", root=vault / "gone" / "9.9.9", session="live-1")

    assert _check(vault).stderr == ""


def test_platforms_recording_different_versions_warn_naming_both(vault: Path) -> None:
    _crumb(vault, "plugin-state.json", version="8.10.0", session="live-1")
    _crumb(vault, "plugin-state.claude-code.json", version="8.10.0", platform="claude-code", session="live-1")
    _crumb(vault, "plugin-state.codex.json", version="8.10.1", platform="codex", session="live-1")

    result = _check(vault)

    assert result.returncode == 0
    assert "DISAGREE" in result.stderr
    for token in ("claude-code", "8.10.0", "codex", "8.10.1"):
        assert token in result.stderr


def test_platforms_recording_the_same_version_do_not_disagree(vault: Path) -> None:
    _crumb(vault, "plugin-state.claude-code.json", version="8.10.0", platform="claude-code", session="live-1")
    _crumb(vault, "plugin-state.codex.json", version="8.10.0", platform="codex", session="live-1")

    assert _check(vault).stderr == ""


def test_a_legacy_only_breadcrumb_without_a_session_behaves_as_before(vault: Path) -> None:
    _crumb(vault, "plugin-state.json", session=None)

    results = [_check(vault) for _ in range(8)]

    assert all(r.returncode == 0 and r.stderr == "" for r in results)


def test_the_version_floor_still_warns_when_the_recorded_version_is_older(vault: Path) -> None:
    (vault / ".vault" / "vault.json").write_text('{"min_plugin_version": "99.0.0"}\n')
    _crumb(vault, "plugin-state.json", version="8.10.0", session="live-1")

    result = _check(vault)

    assert "VAULT PLUGIN STALE" in result.stderr
    assert "99.0.0" in result.stderr


def test_every_warning_path_exits_zero(vault: Path) -> None:
    root = vault / "cache" / "8.8.0"
    root.mkdir(parents=True)
    (root / ".orphaned_at").write_text("x")
    _crumb(vault, "plugin-state.json", version="8.8.0", root=root, session="frozen")
    _crumb(vault, "plugin-state.claude-code.json", version="8.8.0", platform="claude-code", session="frozen")
    _crumb(vault, "plugin-state.codex.json", version="8.9.0", platform="codex", session="frozen")
    results = [_check(vault) for _ in range(6)]

    assert all(r.returncode == 0 for r in results)
    assert "SUPERSEDED" in results[-1].stderr and "DISAGREE" in results[-1].stderr
    assert "NOT RUNNING" in results[-1].stderr


def test_a_corrupt_breadcrumb_fails_open(vault: Path) -> None:
    (vault / ".vault" / "plugin-state.json").write_bytes(b"\xff\x00{not json")
    (vault / ".vault" / "plugin-state.codex.json").write_text("")

    results = [_check(vault) for _ in range(5)]

    assert all(r.returncode == 0 for r in results)


def test_the_scaffolded_gitignore_covers_the_session_tracker() -> None:
    ignored = (PLUGIN / "machinery" / "scaffold" / "gitignore.tmpl").read_text()
    assert ".vault/.plugin-session-track" in ignored


def test_a_stale_shared_record_from_another_platform_does_not_decide_the_version_floor(vault: Path) -> None:
    # #1280: the shared file is last-writer-wins across platforms. A codex write
    # left an old version there; claude-code's own record is current.
    (vault / ".vault" / "vault.json").write_text('{"min_plugin_version": "9.0.0"}\n')
    _crumb(vault, "plugin-state.json", version="8.0.0", platform="codex", session="live-1")
    _crumb(vault, "plugin-state.claude-code.json", version="9.9.9", platform="claude-code", session="live-1")
    _crumb(vault, "plugin-state.codex.json", version="9.9.9", platform="codex", session="live-1")
    result = _check(vault)
    assert result.returncode == 0
    assert "STALE" not in result.stderr
