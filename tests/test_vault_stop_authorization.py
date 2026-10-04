"""Exercise the shipped Stop entry point without allowing any Git effects."""

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "plugins/workbench/hooks/scripts/vault-stop-3-session-sync.py"


def test_ordinary_stop_never_invokes_git(tmp_path: Path) -> None:
    """Stop must reach the engine's no-authorization return, through the wrapper."""
    vault = tmp_path / "vault"
    for directory in ("brain", "perf", ".vault"):
        (vault / directory).mkdir(parents=True)
    (vault / "CLAUDE.md").write_text("# Test vault\n")
    (vault / ".vault/vault.json").write_text('{"vault": "test"}\n')
    (vault / "brain/foreign.md").write_text("Other session's unfinished work\n")
    spy = tmp_path / "bin"
    spy.mkdir()
    log = tmp_path / "git-calls"
    git = spy / "git"
    git.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$STOP_GIT_LOG"\nexit 99\n')
    git.chmod(0o755)
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(vault), STOP_GIT_LOG=str(log))
    env["PATH"] = str(spy) + os.pathsep + env.get("PATH", "")
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    result = subprocess.run(
        [sys.executable, str(WRAPPER)], cwd=vault, env=env,
        input='{"hook_event_name":"Stop","session_id":"test-session"}',
        capture_output=True, text=True, check=False,
    )

    assert result.returncode == 0, result.stderr
    assert not log.exists(), log.read_text() if log.exists() else ""
    assert "Git sync skipped" in result.stdout
    assert (vault / "brain/foreign.md").read_text() == "Other session's unfinished work\n"
