"""Tests for evals._harness.transcript — envelope parsing into tool-call events."""

from __future__ import annotations

import json
from pathlib import Path

from evals._harness.transcript import parse_transcript


def _write(tmp_path: Path, lines: list[dict]) -> Path:
    path = tmp_path / "agent-transcript.jsonl"
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n")
    return path


def _assistant_line(*, model: str, content: list[dict], timestamp: str | None = None) -> dict:
    line = {"type": "assistant", "message": {"model": model, "content": content}}
    if timestamp is not None:
        line["timestamp"] = timestamp
    return line


def _user_line(*, content: list[dict]) -> dict:
    return {"type": "user", "message": {"content": content}}


def test_parse_transcript_missing_file_returns_missing_status(tmp_path):
    transcript = parse_transcript(tmp_path / "does-not-exist.jsonl")
    assert transcript.status == "missing"
    assert transcript.events == []
    assert transcript.model_ids == []
    assert transcript.final_text == ""


def test_parse_transcript_parses_tool_use_and_matched_result_in_order(tmp_path):
    path = _write(
        tmp_path,
        [
            _assistant_line(
                model="claude-sonnet-5",
                timestamp="2026-09-27T00:00:00Z",
                content=[
                    {"type": "tool_use", "id": "toolu_1", "name": "Edit", "input": {"file_path": "a.py"}}
                ],
            ),
            _user_line(
                content=[
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_1",
                        "is_error": False,
                        "content": "ok",
                    }
                ]
            ),
            _assistant_line(
                model="claude-sonnet-5",
                content=[
                    {"type": "tool_use", "id": "toolu_2", "name": "Bash", "input": {"command": "ls"}}
                ],
            ),
        ],
    )
    transcript = parse_transcript(path)
    assert transcript.status == "complete"
    assert [e.name for e in transcript.events] == ["Edit", "Bash"]
    assert transcript.events[0].ordinal < transcript.events[1].ordinal
    assert transcript.events[0].timestamp == "2026-09-27T00:00:00Z"
    assert transcript.events[0].result.content == "ok"
    assert transcript.events[0].result.is_error is False
    assert transcript.events[1].result is None


def test_parse_transcript_multiple_tool_use_blocks_in_one_line_are_individually_ordered(tmp_path):
    path = _write(
        tmp_path,
        [
            _assistant_line(
                model="claude-sonnet-5",
                content=[
                    {"type": "tool_use", "id": "toolu_1", "name": "Edit", "input": {"file_path": "a.py"}},
                    {"type": "tool_use", "id": "toolu_2", "name": "Write", "input": {"file_path": "b.py"}},
                ],
            )
        ],
    )
    transcript = parse_transcript(path)
    assert [e.name for e in transcript.events] == ["Edit", "Write"]
    assert transcript.events[0].ordinal < transcript.events[1].ordinal


def test_parse_transcript_extracts_model_id_from_message_model_not_prose(tmp_path):
    path = _write(
        tmp_path,
        [
            _assistant_line(
                model="claude-haiku-4-5-20251001",
                content=[
                    {"type": "text", "text": "As Claude Opus, I can confirm this works."}
                ],
            )
        ],
    )
    transcript = parse_transcript(path)
    assert transcript.model_ids == ["claude-haiku-4-5-20251001"]


def test_parse_transcript_status_truncated_on_invalid_json_line(tmp_path):
    path = tmp_path / "agent-transcript.jsonl"
    path.write_text(
        json.dumps(_assistant_line(model="m1", content=[])) + "\n" + "not valid json at all\n"
    )
    transcript = parse_transcript(path)
    assert transcript.status == "truncated"


def test_parse_transcript_status_truncated_on_line_cut_mid_utf8_character(tmp_path):
    path = tmp_path / "cut-mid-write.jsonl"
    complete = json.dumps(_assistant_line(model="m1", content=[{"type": "text", "text": "ok"}]))
    partial = '{"type": "assistant", "message": {"content": "dash —'.encode()[:-1]
    path.write_bytes(complete.encode() + b"\n" + partial)
    transcript = parse_transcript(path)
    assert transcript.status == "truncated"


def test_parse_transcript_status_truncated_when_path_is_unreadable_directory(tmp_path):
    path = tmp_path / "is-a-directory.jsonl"
    path.mkdir()
    transcript = parse_transcript(path)
    assert transcript.status == "truncated"


def test_parse_transcript_status_truncated_on_missing_type(tmp_path):
    path = _write(tmp_path, [{"message": {"model": "m1", "content": []}}])
    transcript = parse_transcript(path)
    assert transcript.status == "truncated"


def test_parse_transcript_status_truncated_on_missing_message(tmp_path):
    path = tmp_path / "no-message.jsonl"
    path.write_text(json.dumps({"type": "assistant"}) + "\n")
    transcript = parse_transcript(path)
    assert transcript.status == "truncated"


def test_parse_transcript_status_api_error(tmp_path):
    path = tmp_path / "agent-transcript.jsonl"
    line = {
        "type": "assistant",
        "isApiErrorMessage": True,
        "message": {"model": "<synthetic>", "content": []},
    }
    path.write_text(json.dumps(line) + "\n")
    transcript = parse_transcript(path)
    assert transcript.status == "api_error"
    assert "<synthetic>" not in transcript.model_ids


def test_parse_transcript_status_complete_normal_transcript(tmp_path):
    path = _write(
        tmp_path,
        [_assistant_line(model="claude-sonnet-5", content=[{"type": "text", "text": "done"}])],
    )
    transcript = parse_transcript(path)
    assert transcript.status == "complete"


def test_parse_transcript_final_text_is_last_text_block_of_last_assistant_line_with_one(tmp_path):
    path = _write(
        tmp_path,
        [
            _assistant_line(model="m1", content=[{"type": "text", "text": "hello"}]),
            _assistant_line(
                model="m1",
                content=[{"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {}}],
            ),
        ],
    )
    transcript = parse_transcript(path)
    assert transcript.final_text == "hello"


def test_parse_transcript_final_text_empty_when_no_assistant_text_block(tmp_path):
    path = _write(
        tmp_path,
        [
            _assistant_line(
                model="m1",
                content=[{"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {}}],
            )
        ],
    )
    transcript = parse_transcript(path)
    assert transcript.final_text == ""
