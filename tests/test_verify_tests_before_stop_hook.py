"""Tests for the verify-tests-before-stop Stop hook.

Drives the hook as a real subprocess against a scratch git repo so the
git-status-based change-detection and Makefile-based test-command detection
are exercised for real, not mocked.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_PATH = REPO_ROOT / "core" / "hooks" / "verify-tests-before-stop.py"


def run_hook(payload: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
    )


def run_hook_raw(raw_stdin: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=raw_stdin,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)


def _write_makefile(path: Path, exit_code: int) -> None:
    (path / "Makefile").write_text(f"test:\n\t@exit {exit_code}\n")


@pytest.mark.parametrize("payload", ["", "   ", "not json", "{ broken"])
def test_malformed_stdin_fails_open(payload: str) -> None:
    result = run_hook_raw(payload)
    assert result.returncode == 0
    assert "Traceback" not in result.stderr


def test_no_test_command_detected_exits_clean(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    result = run_hook({"cwd": str(tmp_path)})
    assert result.returncode == 0
    assert result.stderr == ""


def test_stop_hook_active_skips_entirely(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    _write_makefile(tmp_path, exit_code=1)  # would fail if it ran
    (tmp_path / "dirty.txt").write_text("uncommitted")

    result = run_hook({"cwd": str(tmp_path), "stop_hook_active": True})

    assert result.returncode == 0
    assert result.stderr == ""


def test_non_git_directory_exits_clean_even_with_test_command(tmp_path: Path) -> None:
    _write_makefile(tmp_path, exit_code=1)  # would fail if it ran

    result = run_hook({"cwd": str(tmp_path)})

    assert result.returncode == 0
    assert result.stderr == ""


def test_first_check_on_clean_tree_still_verifies_once(tmp_path: Path) -> None:
    # No prior state file exists yet, so even a clean tree gets one baseline
    # verification run — there's nothing cached to trust yet.
    _init_git_repo(tmp_path)
    _write_makefile(tmp_path, exit_code=0)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)

    result = run_hook({"cwd": str(tmp_path)})

    assert result.returncode == 0
    assert result.stderr == ""


def test_failing_tests_block_with_exit_2_and_output(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    _write_makefile(tmp_path, exit_code=1)
    (tmp_path / "dirty.txt").write_text("uncommitted change")

    result = run_hook({"cwd": str(tmp_path), "session_id": "s1"})

    assert result.returncode == 2
    assert "Tests are failing" in result.stderr
    assert "make test" in result.stderr


def test_passing_tests_exit_clean_and_write_state(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    _write_makefile(tmp_path, exit_code=0)
    (tmp_path / "dirty.txt").write_text("uncommitted change")

    result = run_hook({"cwd": str(tmp_path), "session_id": "s2"})

    assert result.returncode == 0
    state_file = tmp_path / ".git" / "claude-workflow-stop-gate" / "s2.txt"
    assert state_file.exists()


def test_unchanged_signature_skips_rerun_after_green_pass(tmp_path: Path) -> None:
    # The signature hashes file *content*, so mutating the Makefile itself
    # (an untracked file) would legitimately change the signature. To prove
    # the second call actually skips re-invoking the test command — rather
    # than just happening to pass again — the Makefile leaves a marker file
    # behind each time it runs, and nothing in the repo changes between calls.
    _init_git_repo(tmp_path)
    marker = tmp_path / "ran.marker"
    (tmp_path / "Makefile").write_text(f"test:\n\t@touch {marker}\n\t@exit 0\n")
    (tmp_path / "dirty.txt").write_text("uncommitted change")

    first = run_hook({"cwd": str(tmp_path), "session_id": "s3"})
    assert first.returncode == 0
    assert marker.exists()
    marker.unlink()

    second = run_hook({"cwd": str(tmp_path), "session_id": "s3"})

    assert second.returncode == 0
    assert not marker.exists(), "test command was re-invoked despite an unchanged signature"


def test_changed_signature_after_green_pass_reruns_tests(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    _write_makefile(tmp_path, exit_code=0)
    (tmp_path / "dirty.txt").write_text("uncommitted change")

    first = run_hook({"cwd": str(tmp_path), "session_id": "s4"})
    assert first.returncode == 0

    _write_makefile(tmp_path, exit_code=1)
    (tmp_path / "dirty.txt").write_text("a different uncommitted change")

    second = run_hook({"cwd": str(tmp_path), "session_id": "s4"})
    assert second.returncode == 2
