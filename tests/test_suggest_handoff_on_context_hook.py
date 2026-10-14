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


def _checkpoint(used_k: int, limit_k: int) -> str:
    """The one notice text the hook may print, for a given reading and threshold."""
    return (
        f"Context checkpoint: this session's context is ~{used_k}k tokens "
        f"(threshold {limit_k}k; set WORKSHOP_HANDOFF_CONTEXT_TOKENS to change it)."
    )


def _notice(result) -> str:
    """The user-facing notice, asserting it is the hook's ONLY output.

    stdout must parse as exactly one JSON object whose only key is the top-level
    ``systemMessage`` (shown to the user, never added to the model's context).
    """
    assert result.returncode == 0
    out = json.loads(result.stdout)
    assert isinstance(out, dict)
    assert set(out) == {"systemMessage"}
    assert isinstance(out["systemMessage"], str)
    return out["systemMessage"]


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

    def test_at_or_above_threshold_emits_a_user_only_system_message(
        self, tmp_path: Path, markers: Path
    ) -> None:
        transcript = _transcript(tmp_path, _assistant_line(2, 305_000, 2_000))
        result = run(
            {"session_id": "s1", "transcript_path": str(transcript)}, tmpdir=markers
        )
        assert _notice(result) == _checkpoint(307, 300)

    @pytest.mark.parametrize(
        ("threshold", "tokens", "expected"),
        [
            pytest.param(None, 300_000, _checkpoint(300, 300), id="default-threshold"),
            pytest.param(
                "200000", 200_000, _checkpoint(200, 200), id="env-override-threshold"
            ),
        ],
    )
    def test_reading_exactly_at_the_threshold_fires(
        self, tmp_path: Path, markers: Path, threshold, tokens: int, expected: str
    ) -> None:
        # "Crosses a threshold" is inclusive: a reading equal to the threshold fires.
        transcript = _transcript(tmp_path, _assistant_line(0, tokens, 0))
        result = run(
            {"session_id": "s1", "transcript_path": str(transcript)},
            tmpdir=markers,
            threshold=threshold,
        )
        assert _notice(result) == expected

    def test_reading_one_below_the_threshold_is_silent(
        self, tmp_path: Path, markers: Path
    ) -> None:
        transcript = _transcript(tmp_path, _assistant_line(0, 299_999, 0))
        result = run(
            {"session_id": "s1", "transcript_path": str(transcript)}, tmpdir=markers
        )
        assert result.returncode == 0
        assert result.stdout == ""

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
        assert _notice(result) == _checkpoint(50, 40)


class TestUserOnlyNotice:
    """The checkpoint is for the human: top-level ``systemMessage``, no instruction.

    ``additionalContext`` and plain stdout reach the model as a system-reminder it
    treats as the user's voice, and the user never sees them. The session lifecycle
    is the user's call, so the hook reports the reading to the user and tells the
    agent nothing.
    """

    FORBIDDEN = ("/wrap-up", "/handoff", "Tell the user")

    def _fire(self, tmp_path: Path, markers: Path, *, tokens: int, threshold=None):
        transcript = _transcript(tmp_path, _assistant_line(0, tokens, 0))
        return run(
            {"session_id": "s1", "transcript_path": str(transcript)},
            tmpdir=markers,
            threshold=threshold,
        )

    def test_only_key_is_system_message(self, tmp_path: Path, markers: Path) -> None:
        result = self._fire(tmp_path, markers, tokens=305_000)
        out = json.loads(result.stdout)
        assert set(out) == {"systemMessage"}
        assert "hookSpecificOutput" not in result.stdout
        assert "additionalContext" not in result.stdout

    def test_stdout_is_exactly_one_json_object(
        self, tmp_path: Path, markers: Path
    ) -> None:
        result = self._fire(tmp_path, markers, tokens=305_000)
        # Any stray stdout around the object would turn the whole output into
        # plain-text model context, so the full stream must parse as one object.
        assert isinstance(json.loads(result.stdout), dict)
        assert len(result.stdout.strip().splitlines()) == 1

    @pytest.mark.parametrize(
        ("tokens", "threshold", "expected"),
        [
            pytest.param(
                305_000,
                None,
                "Context checkpoint: this session's context is ~305k tokens "
                "(threshold 300k; set WORKSHOP_HANDOFF_CONTEXT_TOKENS to change it).",
                id="default-threshold",
            ),
            pytest.param(
                250_000,
                "200000",
                "Context checkpoint: this session's context is ~250k tokens "
                "(threshold 200k; set WORKSHOP_HANDOFF_CONTEXT_TOKENS to change it).",
                id="env-override-shows-the-threshold-in-force",
            ),
            pytest.param(
                304_600,
                None,
                "Context checkpoint: this session's context is ~305k tokens "
                "(threshold 300k; set WORKSHOP_HANDOFF_CONTEXT_TOKENS to change it).",
                id="rounds-rather-than-floors",
            ),
            pytest.param(
                250_000,
                "200600",
                "Context checkpoint: this session's context is ~250k tokens "
                "(threshold 201k; set WORKSHOP_HANDOFF_CONTEXT_TOKENS to change it).",
                id="threshold-rounds-rather-than-floors",
            ),
        ],
    )
    def test_message_text_is_exact(
        self, tmp_path: Path, markers: Path, tokens: int, threshold, expected: str
    ) -> None:
        result = self._fire(tmp_path, markers, tokens=tokens, threshold=threshold)
        assert _notice(result) == expected

    @pytest.mark.parametrize("threshold", [None, "200000"])
    def test_message_carries_no_instruction(
        self, tmp_path: Path, markers: Path, threshold
    ) -> None:
        message = _notice(
            self._fire(tmp_path, markers, tokens=305_000, threshold=threshold)
        )
        for forbidden in self.FORBIDDEN:
            assert forbidden not in message


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
        assert _notice(result) == _checkpoint(305, 300)

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
        assert _notice(again) == _checkpoint(305, 300)

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
