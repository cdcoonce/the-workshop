"""Tests for the audit-config-change ConfigChange hook."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_PATH = REPO_ROOT / "core" / "hooks" / "audit-config-change.py"


def run(payload) -> subprocess.CompletedProcess[str]:
    stdin = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)


@pytest.mark.parametrize("payload", ["", "not json", "{ broken"])
def test_fails_open_on_malformed_stdin(payload: str) -> None:
    result = run(payload)
    assert result.returncode == 0
    assert "Traceback" not in result.stderr


def test_missing_file_path_no_ops(tmp_path: Path) -> None:
    result = run({"cwd": str(tmp_path), "config_source": "project_settings"})
    assert result.returncode == 0
    assert result.stdout == ""


def test_never_blocks(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    result = run(
        {
            "cwd": str(tmp_path),
            "config_source": "project_settings",
            "file_path": str(tmp_path / ".claude" / "settings.json"),
        }
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert "decision" not in payload


def test_surfaces_a_warning_message(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    settings_path = tmp_path / ".claude" / "settings.json"
    result = run(
        {
            "cwd": str(tmp_path),
            "config_source": "local_settings",
            "file_path": str(settings_path),
        }
    )
    payload = json.loads(result.stdout)
    assert str(settings_path) in payload["systemMessage"]
    assert "local_settings" in payload["systemMessage"]


def test_appends_audit_log_entry(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    settings_path = tmp_path / ".claude" / "settings.json"

    run(
        {
            "cwd": str(tmp_path),
            "config_source": "skills",
            "file_path": str(settings_path),
            "session_id": "sess-1",
        }
    )

    log_file = tmp_path / ".git" / "the-workshop-config-audit.log"
    assert log_file.exists()
    entry = json.loads(log_file.read_text().splitlines()[0])
    assert entry["source"] == "skills"
    assert entry["file_path"] == str(settings_path)
    assert entry["session_id"] == "sess-1"


def test_multiple_changes_append_not_overwrite(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)

    run({"cwd": str(tmp_path), "config_source": "project_settings", "file_path": "a.json"})
    run({"cwd": str(tmp_path), "config_source": "local_settings", "file_path": "b.json"})

    log_file = tmp_path / ".git" / "the-workshop-config-audit.log"
    lines = log_file.read_text().splitlines()
    assert len(lines) == 2


def test_outside_git_repo_still_warns_but_does_not_crash(tmp_path: Path) -> None:
    result = run(
        {
            "cwd": str(tmp_path),
            "config_source": "project_settings",
            "file_path": str(tmp_path / "settings.json"),
        }
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert "systemMessage" in payload
    assert not (tmp_path / ".git").exists()
