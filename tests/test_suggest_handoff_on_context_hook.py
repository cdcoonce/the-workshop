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
    REPO_ROOT
    / "plugins"
    / "workbench"
    / "hooks"
    / "scripts"
    / "suggest-handoff-on-context.py"
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


def _sidechain_line(input_t: int, cache_read: int, cache_create: int) -> str:
    record = json.loads(_assistant_line(input_t, cache_read, cache_create))
    record["isSidechain"] = True
    return json.dumps(record)


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

    def test_at_or_above_threshold_suggests_wrap_up(
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
        assert "/wrap-up" in hso["additionalContext"]
        assert "/handoff" not in hso["additionalContext"]
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
        assert "/wrap-up" in out["hookSpecificOutput"]["additionalContext"]


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


class TestSidechainSkipped:
    """A subagent (isSidechain) turn must not be read as the main thread's usage."""

    def test_trailing_sidechain_turn_does_not_mask_main_thread_usage(
        self, tmp_path: Path, markers: Path
    ) -> None:
        # Main thread is large; the last record is a tiny subagent turn.
        transcript = _transcript(
            tmp_path,
            _assistant_line(2, 305_000, 0),
            _sidechain_line(2, 5_000, 0),
        )
        result = run(
            {"session_id": "s1", "transcript_path": str(transcript)}, tmpdir=markers
        )
        assert result.returncode == 0
        assert "/wrap-up" in json.loads(result.stdout)["hookSpecificOutput"][
            "additionalContext"
        ]

    def test_trailing_huge_sidechain_turn_does_not_trigger(
        self, tmp_path: Path, markers: Path
    ) -> None:
        transcript = _transcript(
            tmp_path,
            _assistant_line(2, 10_000, 0),
            _sidechain_line(2, 400_000, 0),
        )
        result = run(
            {"session_id": "s1", "transcript_path": str(transcript)}, tmpdir=markers
        )
        assert result.returncode == 0
        assert result.stdout == ""


class TestRearmOnContextCollapse:
    """The marker is per large-context episode: /clear or compaction re-arms it."""

    def _fire(self, tmp_path: Path, markers: Path, tokens: int, name: str):
        transcript = _transcript(tmp_path, _assistant_line(2, tokens, 0), name=name)
        return run(
            {"session_id": "s1", "transcript_path": str(transcript)}, tmpdir=markers
        )

    def _marker(self, markers: Path) -> Path:
        import hashlib

        key = hashlib.sha1(b"s1").hexdigest()
        return markers / "workshop-handoff-gate" / key

    def test_clear_shaped_scenario_warns_again_after_collapse_and_regrowth(
        self, tmp_path: Path, markers: Path
    ) -> None:
        assert self._fire(tmp_path, markers, 305_000, "a.jsonl").stdout != ""
        # /clear: same session_id, context collapses below the re-arm floor.
        assert self._fire(tmp_path, markers, 10_000, "b.jsonl").stdout == ""
        # Regrows past the threshold: second warning.
        again = self._fire(tmp_path, markers, 305_000, "c.jsonl")
        assert again.returncode == 0
        assert "/wrap-up" in json.loads(again.stdout)["hookSpecificOutput"][
            "additionalContext"
        ]

    def test_still_high_context_stays_suppressed_without_a_drop(
        self, tmp_path: Path, markers: Path
    ) -> None:
        assert self._fire(tmp_path, markers, 305_000, "a.jsonl").stdout != ""
        # Above the re-arm floor (threshold // 2) but never collapsed.
        assert self._fire(tmp_path, markers, 200_000, "b.jsonl").stdout == ""
        assert self._fire(tmp_path, markers, 320_000, "c.jsonl").stdout == ""

    def test_marker_records_the_measured_token_count(
        self, tmp_path: Path, markers: Path
    ) -> None:
        self._fire(tmp_path, markers, 305_000, "a.jsonl")
        assert self._marker(markers).read_text(encoding="utf-8").strip() == "305002"

    @pytest.mark.parametrize("content", ["", "garbage \x00 not a number"])
    def test_legacy_or_malformed_marker_suppresses_until_a_drop(
        self, tmp_path: Path, markers: Path, content: str
    ) -> None:
        marker = self._marker(markers)
        marker.parent.mkdir(parents=True)
        marker.write_text(content, encoding="utf-8")

        high = self._fire(tmp_path, markers, 320_000, "a.jsonl")
        assert high.returncode == 0
        assert high.stdout == ""
        assert "Traceback" not in high.stderr

        assert self._fire(tmp_path, markers, 10_000, "b.jsonl").stdout == ""
        assert self._fire(tmp_path, markers, 305_000, "c.jsonl").stdout != ""


class TestRearmFloorAndUnreadableTranscript:
    """Pins the re-arm floor boundary and that an unmeasurable turn never re-arms."""

    THRESHOLD = "1000"  # floor = threshold // 2 = 500

    def _fire(self, tmp_path: Path, markers: Path, name: str, content):
        path = tmp_path / name
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
        return run(
            {"session_id": "s1", "transcript_path": str(path)},
            tmpdir=markers,
            threshold=self.THRESHOLD,
        )

    def _tokens(self, tmp_path: Path, markers: Path, name: str, tokens: int):
        return self._fire(tmp_path, markers, name, _assistant_line(0, tokens, 0) + "\n")

    def _marker(self, markers: Path) -> Path:
        import hashlib

        return markers / "workshop-handoff-gate" / hashlib.sha1(b"s1").hexdigest()

    @pytest.mark.parametrize(
        "content",
        [
            json.dumps({"type": "user", "message": {"content": "hi"}}) + "\n",
            b"\xff\xfe\x80 not utf-8\n",
        ],
        ids=["no-usage-record", "invalid-utf8"],
    )
    def test_unreadable_transcript_does_not_rearm(
        self, tmp_path: Path, markers: Path, content
    ) -> None:
        assert self._tokens(tmp_path, markers, "a.jsonl", 1500).stdout != ""
        assert self._marker(markers).exists()

        unreadable = self._fire(tmp_path, markers, "b.jsonl", content)
        assert unreadable.returncode == 0
        assert unreadable.stdout == ""
        assert self._marker(markers).exists()

        assert self._tokens(tmp_path, markers, "c.jsonl", 1500).stdout == ""

    def test_reading_exactly_at_the_floor_stays_suppressed(
        self, tmp_path: Path, markers: Path
    ) -> None:
        assert self._tokens(tmp_path, markers, "a.jsonl", 1500).stdout != ""
        assert self._tokens(tmp_path, markers, "b.jsonl", 500).stdout == ""
        assert self._marker(markers).exists()
        assert self._tokens(tmp_path, markers, "c.jsonl", 1500).stdout == ""

    def test_reading_one_below_the_floor_rearms(
        self, tmp_path: Path, markers: Path
    ) -> None:
        assert self._tokens(tmp_path, markers, "a.jsonl", 1500).stdout != ""
        assert self._tokens(tmp_path, markers, "b.jsonl", 499).stdout == ""
        assert not self._marker(markers).exists()
        assert self._tokens(tmp_path, markers, "c.jsonl", 1500).stdout != ""
