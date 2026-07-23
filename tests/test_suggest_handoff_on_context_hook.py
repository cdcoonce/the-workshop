"""Tests for the suggest-handoff-on-context UserPromptSubmit hook.

Drives the hook as a real subprocess with JSON on stdin, against real transcript
fixtures. The once-per-session marker lives under ``tempfile.gettempdir()``; every
run points ``TMPDIR`` at a per-test scratch dir so markers never collide.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_PATH = (
    REPO_ROOT / "presets" / "vault-ops" / "hooks" / "suggest-handoff-on-context.py"
)


def run(payload, *, tmpdir: Path, threshold: str | None = None):
    stdin = payload if isinstance(payload, str) else json.dumps(payload)
    env = {**os.environ, "TMPDIR": str(tmpdir)}
    env.pop("WORKSHOP_HANDOFF_CONTEXT_TOKENS", None)
    if threshold is not None:
        env["WORKSHOP_HANDOFF_CONTEXT_TOKENS"] = threshold
    return subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )


def _assistant_line(input_t: int, cache_read: int, cache_create: int) -> str:
    return json.dumps(
        {
            "type": "assistant",
            "message": {
                "usage": {
                    "input_tokens": input_t,
                    "cache_read_input_tokens": cache_read,
                    "cache_creation_input_tokens": cache_create,
                    "output_tokens": 500,
                }
            },
        }
    )


def _transcript(tmp_path: Path, *lines: str, name: str = "t.jsonl") -> Path:
    path = tmp_path / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def markers(tmp_path: Path) -> Path:
    d = tmp_path / "markers"
    d.mkdir()
    return d


class TestFailOpen:
    @pytest.mark.parametrize("payload", ["", "not json", "{ broken", "[]", "123"])
    def test_malformed_stdin_no_ops(self, payload: str, markers: Path) -> None:
        result = run(payload, tmpdir=markers)
        assert result.returncode == 0
        assert result.stdout == ""
        assert "Traceback" not in result.stderr

    def test_missing_transcript_path_no_ops(self, markers: Path) -> None:
        result = run({"session_id": "s1"}, tmpdir=markers)
        assert result.returncode == 0
        assert result.stdout == ""

    def test_transcript_path_not_a_file_no_ops(
        self, tmp_path: Path, markers: Path
    ) -> None:
        result = run(
            {"session_id": "s1", "transcript_path": str(tmp_path / "nope.jsonl")},
            tmpdir=markers,
        )
        assert result.returncode == 0
        assert result.stdout == ""

    def test_transcript_without_usage_no_ops(
        self, tmp_path: Path, markers: Path
    ) -> None:
        transcript = _transcript(
            tmp_path,
            json.dumps({"type": "user", "message": {"content": "hi"}}),
            "garbage not json",
            json.dumps({"type": "assistant", "message": {}}),
        )
        result = run(
            {"session_id": "s1", "transcript_path": str(transcript)}, tmpdir=markers
        )
        assert result.returncode == 0
        assert result.stdout == ""


class TestThreshold:
    def test_below_threshold_no_ops(self, tmp_path: Path, markers: Path) -> None:
        transcript = _transcript(tmp_path, _assistant_line(2, 100_000, 1_000))
        result = run(
            {"session_id": "s1", "transcript_path": str(transcript)}, tmpdir=markers
        )
        assert result.returncode == 0
        assert result.stdout == ""

    def test_at_or_above_threshold_suggests_handoff(
        self, tmp_path: Path, markers: Path
    ) -> None:
        transcript = _transcript(tmp_path, _assistant_line(2, 305_000, 2_000))
        result = run(
            {"session_id": "s1", "transcript_path": str(transcript)}, tmpdir=markers
        )
        assert result.returncode == 0
        out = json.loads(result.stdout)
        hso = out["hookSpecificOutput"]
        assert hso["hookEventName"] == "UserPromptSubmit"
        assert "/handoff" in hso["additionalContext"]
        assert "do not run" in hso["additionalContext"].lower()

    def test_uses_last_assistant_usage_not_earlier(
        self, tmp_path: Path, markers: Path
    ) -> None:
        # An early huge turn must not count once context shrinks (it never does in
        # practice, but the hook must read the LAST usage, not the max).
        transcript = _transcript(
            tmp_path,
            _assistant_line(2, 400_000, 0),
            _assistant_line(2, 10_000, 0),
        )
        result = run(
            {"session_id": "s1", "transcript_path": str(transcript)}, tmpdir=markers
        )
        assert result.stdout == ""

    def test_env_override_threshold(self, tmp_path: Path, markers: Path) -> None:
        transcript = _transcript(tmp_path, _assistant_line(2, 50_000, 0))
        result = run(
            {"session_id": "s1", "transcript_path": str(transcript)},
            tmpdir=markers,
            threshold="40000",
        )
        out = json.loads(result.stdout)
        assert "/handoff" in out["hookSpecificOutput"]["additionalContext"]


class TestOncePerSession:
    def test_second_turn_suppressed_by_marker(
        self, tmp_path: Path, markers: Path
    ) -> None:
        transcript = _transcript(tmp_path, _assistant_line(2, 305_000, 0))
        payload = {"session_id": "s1", "transcript_path": str(transcript)}

        first = run(payload, tmpdir=markers)
        assert first.stdout != ""

        second = run(payload, tmpdir=markers)
        assert second.returncode == 0
        assert second.stdout == ""

    def test_different_sessions_each_fire(
        self, tmp_path: Path, markers: Path
    ) -> None:
        transcript = _transcript(tmp_path, _assistant_line(2, 305_000, 0))
        a = run(
            {"session_id": "a", "transcript_path": str(transcript)}, tmpdir=markers
        )
        b = run(
            {"session_id": "b", "transcript_path": str(transcript)}, tmpdir=markers
        )
        assert a.stdout != ""
        assert b.stdout != ""

    def test_missing_session_id_dedups_on_transcript_path(
        self, tmp_path: Path, markers: Path
    ) -> None:
        transcript = _transcript(tmp_path, _assistant_line(2, 305_000, 0))
        payload = {"transcript_path": str(transcript)}  # no session_id (agnostic host)

        first = run(payload, tmpdir=markers)
        second = run(payload, tmpdir=markers)
        assert first.stdout != ""
        assert second.stdout == ""
