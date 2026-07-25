"""Integration test -- session-stop hook updates term frequency."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(SCRIPTS_DIR))

from term_tracker import load_frequencies, record_terms


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
