"""Tests for the PreCompact hook entrypoint (``engine/pre-compact.py``).

The backup/retention helpers are covered in ``test_transcript_backup.py``; this
file exercises the hook script itself: stdin JSON parsing, ``transcript_path`` /
``trigger`` extraction, the no-vault early return, and the emitted
``systemMessage``. The script is hyphenated, so it runs as a real subprocess.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ENGINE_DIR = Path(__file__).resolve().parent.parent / "engine"
HOOK = ENGINE_DIR / "pre-compact.py"


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    (root / "brain").mkdir(parents=True)
    (root / "perf").mkdir()
    (root / ".vault").mkdir()
    (root / ".vault" / "vault.json").write_text('{"vault": "test"}\n', encoding="utf-8")
    (root / "CLAUDE.md").write_text("# Vault", encoding="utf-8")
    return root


def _run(stdin: str, *, project_dir: Path | None, cwd: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("CLAUDE_PROJECT_DIR", None)
    if project_dir is not None:
        env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=stdin,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _backups(vault: Path) -> list[Path]:
    return sorted((vault / "thinking" / "session-logs").glob("session_*.jsonl"))


class TestPreCompactMain:
    def test_valid_event_backs_up_and_emits_system_message(self, vault: Path, tmp_path: Path) -> None:
        transcript = tmp_path / "t.jsonl"
        transcript.write_text('{"a": 1}\n', encoding="utf-8")
        event = {"transcript_path": str(transcript), "trigger": "auto"}

        result = _run(json.dumps(event), project_dir=vault, cwd=vault)

        assert result.returncode == 0, result.stderr
        backups = _backups(vault)
        assert len(backups) == 1
        assert backups[0].name.startswith("session_auto_")
        assert backups[0].read_text(encoding="utf-8") == '{"a": 1}\n'
        payload = json.loads(result.stdout)
        assert set(payload) == {"systemMessage"}
        message = payload["systemMessage"]
        assert message.startswith(f"✓ Session transcript backed up to {backups[0].name}")
        assert "run /handoff (it rewrites" in message

    def test_missing_trigger_defaults_to_unknown(self, vault: Path, tmp_path: Path) -> None:
        transcript = tmp_path / "t.jsonl"
        transcript.write_text("x\n", encoding="utf-8")

        result = _run(json.dumps({"transcript_path": str(transcript)}), project_dir=vault, cwd=vault)

        assert result.returncode == 0, result.stderr
        assert _backups(vault)[0].name.startswith("session_unknown_")

    @pytest.mark.parametrize(
        "event",
        [{}, {"transcript_path": ""}, {"transcript_path": "/nonexistent/transcript.jsonl"}],
        ids=["absent", "empty", "nonexistent"],
    )
    def test_missing_or_invalid_transcript_path_is_a_silent_noop(
        self, vault: Path, event: dict[str, str]
    ) -> None:
        result = _run(json.dumps(event), project_dir=vault, cwd=vault)

        assert result.returncode == 0, result.stderr
        assert result.stdout == ""
        assert result.stderr == ""  # a swallowed crash would still exit 0
        assert _backups(vault) == []

    @pytest.mark.parametrize("stdin", ["", "   \n", "{not json"], ids=["empty", "blank", "malformed"])
    def test_empty_or_malformed_stdin_is_a_silent_noop(self, vault: Path, stdin: str) -> None:
        result = _run(stdin, project_dir=vault, cwd=vault)

        assert result.returncode == 0, result.stderr
        assert result.stdout == ""
        assert result.stderr == ""  # a swallowed crash would still exit 0
        assert _backups(vault) == []

    def test_no_vault_root_returns_without_backing_up(self, tmp_path: Path) -> None:
        elsewhere = tmp_path / "not-a-vault"
        elsewhere.mkdir()
        transcript = tmp_path / "t.jsonl"
        transcript.write_text("x\n", encoding="utf-8")
        event = {"transcript_path": str(transcript), "trigger": "manual"}

        result = _run(json.dumps(event), project_dir=None, cwd=elsewhere)

        assert result.returncode == 0, result.stderr
        assert result.stdout == ""
        assert result.stderr == ""  # a swallowed crash would still exit 0
        assert not (elsewhere / "thinking").exists()


class TestPreCompactHardening:
    def test_main_enforces_max_backups(self, vault: Path, tmp_path: Path) -> None:
        from transcript_backup import DEFAULT_MAX_BACKUPS

        log_dir = vault / "thinking" / "session-logs"
        log_dir.mkdir(parents=True)
        for i in range(DEFAULT_MAX_BACKUPS + 5):
            old = log_dir / f"session_auto_2020010{i % 10}_0000{i:02d}.jsonl"
            old.write_text("x\n", encoding="utf-8")
            os.utime(old, (1_000_000 + i, 1_000_000 + i))
        transcript = tmp_path / "t.jsonl"
        transcript.write_text("y\n", encoding="utf-8")

        result = _run(json.dumps({"transcript_path": str(transcript), "trigger": "auto"}), project_dir=vault, cwd=vault)

        assert result.returncode == 0, result.stderr
        assert len(_backups(vault)) == DEFAULT_MAX_BACKUPS

    @pytest.mark.parametrize("stdin", ["[]", '{"transcript_path": 5}'])
    def test_malformed_event_shapes_exit_zero(self, vault: Path, stdin: str) -> None:
        result = _run(stdin, project_dir=vault, cwd=vault)

        assert result.returncode == 0
        assert "Traceback" not in result.stderr
