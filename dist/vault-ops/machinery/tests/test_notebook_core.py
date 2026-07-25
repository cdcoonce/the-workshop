"""Tests for notebook_core — pure helpers extracted from notebook-distill.py (#61).

The hyphenated hook ``notebook-distill.py`` is not importable; its pure
transcript-parsing and prompt-building logic lives in ``notebook_core.py`` so it
can be unit-tested. Mirrors session_terms.py / transcript_backup.py.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(SCRIPTS_DIR))

from notebook_core import _block_text, build_prompt, latest_turn


# ---------------------------------------------------------------------------
# _block_text
# ---------------------------------------------------------------------------

class TestBlockText:
    def test_string_content_returned_as_is(self) -> None:
        assert _block_text({"content": "hello"}) == "hello"

    def test_list_of_text_blocks_joined(self) -> None:
        msg = {"content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]}
        assert _block_text(msg) == "a\nb"

    def test_non_text_blocks_ignored(self) -> None:
        # tool_use / tool_result blocks contribute nothing.
        msg = {"content": [{"type": "tool_use", "name": "x"}, {"type": "text", "text": "keep"}]}
        assert _block_text(msg) == "keep"

    def test_missing_content_returns_empty(self) -> None:
        assert _block_text({}) == ""


# ---------------------------------------------------------------------------
# latest_turn
# ---------------------------------------------------------------------------

def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


class TestLatestTurn:
    def test_returns_last_user_and_assistant(self, tmp_path: Path) -> None:
        p = tmp_path / "t.jsonl"
        _write_jsonl(p, [
            {"type": "user", "message": {"content": "first user"}},
            {"type": "assistant", "message": {"content": "first asst"}},
            {"type": "user", "message": {"content": "second user"}},
            {"type": "assistant", "message": {"content": "second asst"}},
        ])
        user, asst = latest_turn(p)
        assert user == "second user"
        assert asst == "second asst"

    def test_skips_malformed_json_lines(self, tmp_path: Path) -> None:
        p = tmp_path / "t.jsonl"
        p.write_text('not json\n{"type":"user","message":{"content":"ok"}}\n', encoding="utf-8")
        user, _asst = latest_turn(p)
        assert user == "ok"

    def test_missing_file_returns_empty_pair(self, tmp_path: Path) -> None:
        assert latest_turn(tmp_path / "nope.jsonl") == ("", "")

    def test_truncates_to_max_turn_chars(self, tmp_path: Path) -> None:
        p = tmp_path / "t.jsonl"
        _write_jsonl(p, [{"type": "user", "message": {"content": "x" * 100}}])
        user, _asst = latest_turn(p, max_turn_chars=10)
        assert user == "x" * 10  # kept the LAST max_turn_chars characters

    def test_entry_without_message_dict_skipped(self, tmp_path: Path) -> None:
        p = tmp_path / "t.jsonl"
        _write_jsonl(p, [
            {"type": "user", "message": None},
            {"type": "user", "message": {"content": "real"}},
        ])
        user, _asst = latest_turn(p)
        assert user == "real"

    def test_blank_lines_ignored(self, tmp_path: Path) -> None:
        p = tmp_path / "t.jsonl"
        p.write_text('\n\n{"type":"assistant","message":{"content":"a"}}\n\n', encoding="utf-8")
        _user, asst = latest_turn(p)
        assert asst == "a"


# ---------------------------------------------------------------------------
# build_prompt
# ---------------------------------------------------------------------------

class TestBuildPrompt:
    def test_includes_notebook_and_both_turn_sides(self) -> None:
        out = build_prompt("CURRENT NB BODY", "the user question", "the assistant answer")
        assert "CURRENT NB BODY" in out
        assert "the user question" in out
        assert "the assistant answer" in out

    def test_includes_section_skeleton_instruction(self) -> None:
        out = build_prompt("nb", "u", "a")
        assert "Now / Established / Open loops / Touched" in out
