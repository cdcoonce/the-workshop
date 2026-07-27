"""Integration test -- session-stop hook updates term frequency."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(SCRIPTS_DIR))

from term_tracker import load_frequencies, record_terms

# session-stop.py has a hyphen, so it can't be `import`ed by name — load it by path,
# same pattern used for the other hyphenated hook scripts in this test suite. Registered
# in sys.modules so string-based `patch("session_stop.x")` targets resolve like a real import.
_spec = importlib.util.spec_from_file_location("session_stop", SCRIPTS_DIR / "session-stop.py")
session_stop = importlib.util.module_from_spec(_spec)
sys.modules["session_stop"] = session_stop
_spec.loader.exec_module(session_stop)


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    (tmp_path / "CLAUDE.md").write_text("# Vault", encoding="utf-8")
    (tmp_path / ".claude" / "data").mkdir(parents=True)
    (tmp_path / "brain").mkdir()
    return tmp_path


class TestTermFrequencyUpdate:
    """Verify that term frequency logic works in session-stop context."""

    def test_frequency_file_created(self, vault: Path) -> None:
        record_terms(vault, ["REC", "AMRT"])
        data = load_frequencies(vault)
        assert "REC" in data
        assert "AMRT" in data

    def test_frequency_increments_across_calls(self, vault: Path) -> None:
        record_terms(vault, ["REC"])
        record_terms(vault, ["REC"])
        data = load_frequencies(vault)
        assert data["REC"]["sessions"] == 2


def test_bare_hook_invocation_never_commits(vault: Path) -> None:
    """A lifecycle Stop event is not authorization to sync the vault."""
    (vault / "perf").mkdir()
    remote = vault.parent / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True)
    subprocess.run(["git", "init", "-b", "main"], cwd=vault, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=vault, check=True
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"], cwd=vault, check=True
    )
    subprocess.run(["git", "add", "."], cwd=vault, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=vault, check=True)
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=vault, check=True)
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=vault, check=True)

    dirty_file = vault / "brain" / "unsynced.md"
    dirty_file.write_text("keep local", encoding="utf-8")
    initial_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=vault,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(vault)
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "session-stop.py")],
        cwd=vault,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    final_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=vault,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert result.returncode == 0
    assert final_head == initial_head
    assert dirty_file.exists()


class TestVaultHealthCheck:
    """`_vault_health_check` gates the auto-sync push — see sync_manager.push's
    `pre_push_check`. It must never be able to block sync on its own account
    (missing script, timeout, crash), only on a real reported regression.
    """

    def test_no_health_script_is_a_pass(self, tmp_path: Path) -> None:
        ok, detail = session_stop._vault_health_check(tmp_path)
        assert ok is True
        assert detail == ""

    def test_passing_script_is_a_pass(self, tmp_path: Path) -> None:
        ci = tmp_path / "ci"
        ci.mkdir()
        (ci / "vault_health.py").write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
        with patch("session_stop.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["uv"], returncode=0, stdout="ok\n", stderr=""
            )
            ok, detail = session_stop._vault_health_check(tmp_path)
        assert ok is True
        assert detail == ""

    def test_failing_script_blocks_with_detail(self, tmp_path: Path) -> None:
        ci = tmp_path / "ci"
        ci.mkdir()
        (ci / "vault_health.py").write_text("import sys\nsys.exit(1)\n", encoding="utf-8")
        with patch("session_stop.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["uv"], returncode=1, stdout="",
                stderr="max_unresolved_links: 1 exceeds limit 0",
            )
            ok, detail = session_stop._vault_health_check(tmp_path)
        assert ok is False
        assert "max_unresolved_links" in detail

    def test_timeout_fails_open(self, tmp_path: Path) -> None:
        ci = tmp_path / "ci"
        ci.mkdir()
        (ci / "vault_health.py").write_text("", encoding="utf-8")
        with patch("session_stop.subprocess.run", side_effect=subprocess.TimeoutExpired("uv", 30)):
            ok, detail = session_stop._vault_health_check(tmp_path)
        assert ok is True  # a hung/unavailable checker must never block sync

    def test_push_is_called_with_health_check_gate(
        self, vault: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The main() flow must wire the health check into push(), not bypass it."""
        (vault / "perf").mkdir()
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(vault))
        with patch("session_stop.push") as mock_push, \
             patch("session_stop._sync_branch_status", return_value=(True, "main", "main")), \
             patch.object(sys, "argv", ["session-stop.py", "--explicit-sync"]):
            from sync_manager import SyncResult
            mock_push.return_value = SyncResult(success=True, message="ok")
            session_stop.main()
            _, kwargs = mock_push.call_args
            assert kwargs.get("pre_push_check") is session_stop._vault_health_check
