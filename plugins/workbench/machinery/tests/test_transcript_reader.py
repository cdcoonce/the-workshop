"""Tests for transcript_reader, the one reader both cost instruments share.

The hand-built fixtures under ``fixtures/transcript_reader/`` are laid out as
Claude Code writes them (``<project-key>/<session>.jsonl`` and
``<project-key>/<session>/subagents/agent-<id>.jsonl``). ``EXPECTED.json`` next
to them was derived from the spec before the fixtures were built; one test
compares the reader's output to it for every fixture.
"""

from __future__ import annotations

import dataclasses
import json
import os
import sys
from pathlib import Path

import pytest

ENGINE_DIR = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(ENGINE_DIR))

import transcript_reader as tr

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "transcript_reader"
EXPECTED = json.loads((FIXTURES / "EXPECTED.json").read_text(encoding="utf-8"))
FIXTURE_NAMES = [k for k in EXPECTED if not k.startswith("_")]


def _key(call: tr.Call) -> str:
    return "/".join(call.key)


def _write(path: Path, lines: list) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join((x if isinstance(x, str) else json.dumps(x)) + "\n" for x in lines),
        encoding="utf-8",
    )
    return path


def _asst(mid="m1", rid="r1", ts="2026-11-10T10:00:00Z", **usage) -> dict:
    return {
        "type": "assistant",
        "requestId": rid,
        "timestamp": ts,
        "message": {"id": mid, "model": "claude-sonnet-4", "usage": usage},
    }


# ---------------------------------------------------------------------------
# fixtures vs EXPECTED.json (B1-B4, B6)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_reader_matches_expected_json(name: str) -> None:
    exp = EXPECTED[name]
    result = tr.read(FIXTURES / name)
    got = {_key(c): c for c in result.calls}
    assert sorted(got) == sorted(exp["calls"])
    assert len(result.calls) == len(exp["calls"])
    for key, want in exp["calls"].items():
        call = got[key]
        assert call.project == exp["project"]
        assert call.session_id == want["session"]
        assert call.is_subagent is want["subagent"]
        assert call.agent_id == want.get("agent_id")
        assert call.output_tokens == want["output"]
        assert call.cache_write_5m_tokens == want["write_5m"]
        assert call.cache_write_1h_tokens == want["write_1h"]
        if "input" in want:
            assert call.input_tokens == want["input"]
    assert result.coverage.malformed_lines == exp.get("malformed_lines", 0)
    got_att = [
        {
            "session": a.session_id,
            "subagent": a.is_subagent,
            "agent_id": a.agent_id,
            "subtype": a.subtype,
            "size": a.size,
        }
        for a in result.attachments
    ]
    assert sorted(got_att, key=json.dumps) == sorted(
        exp.get("attachments", []), key=json.dumps
    )


def test_window_matches_expected_json() -> None:
    exp = EXPECTED["malformed_and_window"]["window"]
    result = tr.read(
        FIXTURES / "malformed_and_window", since=exp["since"], until=exp["until"]
    )
    assert sorted(_key(c) for c in result.calls) == sorted(exp["calls"])


# ---------------------------------------------------------------------------
# B1 discovery
# ---------------------------------------------------------------------------
class TestDiscovery:
    def test_subagent_call_carries_top_level_project_not_subagents(self) -> None:
        result = tr.read(FIXTURES / "subagent")
        sub = [c for c in result.calls if c.is_subagent]
        assert len(sub) == 1
        assert sub[0].project == "-proj-alpha"
        assert sub[0].session_id == "sess-d1"
        assert sub[0].agent_id == "ad1"

    def test_main_call_has_no_agent_id(self) -> None:
        main = [c for c in tr.read(FIXTURES / "subagent").calls if not c.is_subagent]
        assert main[0].agent_id is None
        assert main[0].session_id == "sess-d1"

    def test_iter_records_file_info(self) -> None:
        infos = {
            (i.project, i.session_id, i.is_subagent, i.agent_id)
            for i, _ in tr.iter_records(FIXTURES / "subagent")
        }
        assert infos == {
            ("-proj-alpha", "sess-d1", False, None),
            ("-proj-alpha", "sess-d1", True, "ad1"),
        }
        for info, _ in tr.iter_records(FIXTURES / "subagent"):
            assert info.path.is_file()
            assert isinstance(info.mtime, float)

    def test_empty_or_missing_root(self, tmp_path: Path) -> None:
        assert tr.read(tmp_path).calls == []
        assert tr.read(tmp_path / "absent").calls == []


# ---------------------------------------------------------------------------
# B2 / B3 dedup and keep-largest
# ---------------------------------------------------------------------------
class TestDedup:
    def test_two_lines_one_call(self) -> None:
        assert len(tr.read(FIXTURES / "two_line_call").calls) == 1

    def test_same_call_in_two_files_yielded_once(self) -> None:
        calls = tr.read(FIXTURES / "cross_file").calls
        assert sorted(_key(c) for c in calls) == ["msg_c1/req_c1", "msg_c2/req_c2"]

    def test_keep_largest_not_first_line(self) -> None:
        call = next(
            c for c in tr.read(FIXTURES / "disagreeing_usage").calls if c.key[0] == "msg_b1"
        )
        assert call.output_tokens == 80  # first-line rule would give 10
        assert call.input_tokens == 120  # every number from the kept line

    def test_tie_goes_to_the_later_line(self) -> None:
        call = next(
            c for c in tr.read(FIXTURES / "disagreeing_usage").calls if c.key[0] == "msg_b2"
        )
        assert call.input_tokens == 9

    def test_same_message_different_request_are_two_calls(self, tmp_path: Path) -> None:
        _write(
            tmp_path / "p" / "s.jsonl",
            [_asst("m", "r1", output_tokens=1), _asst("m", "r2", output_tokens=1)],
        )
        assert len(tr.read(tmp_path).calls) == 2

    def test_missing_ids_fall_back_to_uuid(self, tmp_path: Path) -> None:
        a = _asst(output_tokens=1)
        b = _asst(output_tokens=2)
        for rec, uid in ((a, "u1"), (b, "u2")):
            rec["message"].pop("id")
            rec.pop("requestId")
            rec["uuid"] = uid
        dup = dict(a)
        _write(tmp_path / "p" / "s.jsonl", [a, b, dup])
        assert len(tr.read(tmp_path).calls) == 2

    def test_unidentifiable_lines_each_count(self, tmp_path: Path) -> None:
        a = _asst(output_tokens=1)
        a["message"].pop("id")
        a.pop("requestId")
        _write(tmp_path / "p" / "s.jsonl", [a, dict(a)])
        assert len(tr.read(tmp_path).calls) == 2


# ---------------------------------------------------------------------------
# B4 call fields
# ---------------------------------------------------------------------------
class TestCallFields:
    def test_fixture_fields(self) -> None:
        (c,) = tr.read(FIXTURES / "two_line_call").calls
        assert c.model == "claude-sonnet-4"
        assert c.timestamp == "2026-11-10T10:00:01Z"
        assert (c.input_tokens, c.output_tokens, c.cache_read_tokens) == (100, 50, 10)
        assert (c.cache_write_tokens, c.cache_write_5m_tokens, c.cache_write_1h_tokens) == (20, 15, 5)

    def test_split_absent_means_all_5m(self, tmp_path: Path) -> None:
        _write(tmp_path / "p" / "s.jsonl", [_asst(output_tokens=1, cache_creation_input_tokens=9)])
        (c,) = tr.read(tmp_path).calls
        assert (c.cache_write_tokens, c.cache_write_5m_tokens, c.cache_write_1h_tokens) == (9, 9, 0)

    def test_attribution_passthrough_and_absent(self, tmp_path: Path) -> None:
        full = _asst("m1", "r1", output_tokens=1)
        full.update(
            attributionSkill="s",
            attributionPlugin="p",
            attributionAgent="a",
            attributionMcpServer="srv",
            attributionMcpTool="tool",
        )
        bare = _asst("m2", "r2", output_tokens=1)
        _write(tmp_path / "p" / "s.jsonl", [full, bare])
        by = {c.key[0]: c for c in tr.read(tmp_path).calls}
        f = by["m1"]
        assert (f.attribution_skill, f.attribution_plugin, f.attribution_agent) == ("s", "p", "a")
        assert (f.attribution_mcp_server, f.attribution_mcp_tool) == ("srv", "tool")
        b = by["m2"]
        assert (b.attribution_skill, b.attribution_plugin, b.attribution_agent) == (None, None, None)
        assert (b.attribution_mcp_server, b.attribution_mcp_tool) == (None, None)

    def test_attribution_comes_from_the_kept_line(self, tmp_path: Path) -> None:
        first = _asst(output_tokens=1)
        first["attributionSkill"] = "early"
        last = _asst(output_tokens=9)
        last["attributionSkill"] = "late"
        _write(tmp_path / "p" / "s.jsonl", [first, last])
        assert tr.read(tmp_path).calls[0].attribution_skill == "late"

    def test_call_is_frozen(self) -> None:
        (c,) = tr.read(FIXTURES / "two_line_call").calls
        with pytest.raises(dataclasses.FrozenInstanceError):
            c.output_tokens = 1  # type: ignore[misc]


# ---------------------------------------------------------------------------
# B5 window
# ---------------------------------------------------------------------------
class TestWindow:
    def test_no_window_includes_everything_even_without_timestamp(self) -> None:
        assert len(tr.read(FIXTURES / "malformed_and_window").calls) == 4

    def test_out_of_window_call_excluded_from_a_mixed_file(self) -> None:
        keys = {_key(c) for c in tr.read(FIXTURES / "malformed_and_window", since="2026-11-01").calls}
        assert "msg_e2/req_e2" not in keys
        assert "msg_e1/req_e1" in keys

    def test_bounds_are_inclusive(self) -> None:
        r = tr.read(FIXTURES / "malformed_and_window", since="2026-11-10", until="2026-11-30")
        assert sorted(_key(c) for c in r.calls) == ["msg_e1/req_e1", "msg_e3/req_e3"]
        r = tr.read(FIXTURES / "malformed_and_window", until="2026-10-01")
        assert [_key(c) for c in r.calls] == ["msg_e2/req_e2"]

    def test_no_usable_timestamp_excluded_when_windowed(self) -> None:
        r = tr.read(FIXTURES / "malformed_and_window", until="2099-01-01")
        assert "msg_e4/req_e4" not in {_key(c) for c in r.calls}

    def test_window_uses_message_timestamp_not_file_mtime(self, tmp_path: Path) -> None:
        p = _write(tmp_path / "p" / "s.jsonl", [_asst(ts="2026-11-05T00:00:00Z", output_tokens=1)])
        os.utime(p, (1_700_000_000, 1_700_000_000))
        assert len(tr.read(tmp_path, since="2026-11-01").calls) == 1

    def test_attachments_follow_the_window(self) -> None:
        r = tr.read(FIXTURES / "attachments", since="2026-11-11")
        assert r.attachments == []


# ---------------------------------------------------------------------------
# B6 attachments
# ---------------------------------------------------------------------------
class TestAttachments:
    def test_size_is_compact_json_length(self, tmp_path: Path) -> None:
        att = {"type": "x", "a": [1, 2], "t": "é"}
        _write(tmp_path / "p" / "s.jsonl", [{"type": "attachment", "attachment": att}])
        (a,) = tr.read(tmp_path).attachments
        assert a.size == len(json.dumps(att, separators=(",", ":"), ensure_ascii=False))
        assert a.subtype == "x"
        assert (a.project, a.session_id, a.is_subagent, a.agent_id) == ("p", "s", False, None)

    def test_main_and_subagent_attachment(self) -> None:
        by = {a.is_subagent: a for a in tr.read(FIXTURES / "attachments").attachments}
        assert by[True].agent_id == "af1" and by[True].session_id == "sess-f1"
        assert by[False].agent_id is None

    def test_non_object_attachment_ignored(self, tmp_path: Path) -> None:
        _write(tmp_path / "p" / "s.jsonl", [{"type": "attachment", "attachment": "x"}])
        assert tr.read(tmp_path).attachments == []


# ---------------------------------------------------------------------------
# B7 coverage
# ---------------------------------------------------------------------------
class TestCoverage:
    def test_counts(self) -> None:
        cov = tr.read(FIXTURES / "subagent").coverage
        assert (cov.files_found, cov.files_read, cov.files_skipped) == (2, 2, [])
        assert tr.read(FIXTURES / "malformed_and_window").coverage.malformed_lines == 2

    def test_unreadable_file_is_skipped_with_reason(self, tmp_path: Path) -> None:
        good = _write(tmp_path / "p" / "good.jsonl", [_asst(output_tokens=1)])
        bad = _write(tmp_path / "p" / "bad.jsonl", [_asst("m2", "r2", output_tokens=1)])
        bad.chmod(0)
        try:
            if os.access(bad, os.R_OK):
                pytest.skip("running as a user that ignores file modes")
            r = tr.read(tmp_path)
        finally:
            bad.chmod(0o600)
        assert good.exists()
        assert len(r.calls) == 1
        assert r.coverage.files_found == 2 and r.coverage.files_read == 1
        ((path, reason),) = r.coverage.files_skipped
        assert Path(path).name == "bad.jsonl" and reason

    def test_mtime_prefilter_is_reported_as_skipped(self, tmp_path: Path) -> None:
        p = _write(tmp_path / "p" / "s.jsonl", [_asst(output_tokens=1)])
        os.utime(p, (1_700_000_000, 1_700_000_000))
        cov = tr.Coverage()
        assert list(tr.iter_records(tmp_path, since="2026-11-01", coverage=cov)) == []
        assert cov.files_found == 1 and cov.files_read == 0
        assert len(cov.files_skipped) == 1 and cov.files_skipped[0][1]

    def test_bad_utf8_decodes_with_replacement(self, tmp_path: Path) -> None:
        p = tmp_path / "p" / "s.jsonl"
        p.parent.mkdir(parents=True)
        line = json.dumps(_asst(output_tokens=3)).encode() + b"\n\xff\xfe junk\n"
        p.write_bytes(line)
        r = tr.read(tmp_path)
        assert len(r.calls) == 1
        assert r.coverage.malformed_lines == 1


# ---------------------------------------------------------------------------
# B8 untrusted input
# ---------------------------------------------------------------------------
class TestUntrusted:
    @pytest.mark.parametrize(
        "bad", [True, 1.5, "7", -3, None, [1], {"a": 1}], ids=repr
    )
    def test_bad_token_value_counts_as_zero(self, tmp_path: Path, bad) -> None:
        _write(
            tmp_path / "p" / "s.jsonl",
            [_asst(input_tokens=bad, output_tokens=4, cache_read_input_tokens=bad,
                   cache_creation_input_tokens=bad)],
        )
        (c,) = tr.read(tmp_path).calls
        assert (c.input_tokens, c.cache_read_tokens, c.cache_write_tokens) == (0, 0, 0)
        assert c.output_tokens == 4

    def test_bad_split_values(self, tmp_path: Path) -> None:
        rec = _asst(output_tokens=1, cache_creation_input_tokens=5)
        rec["message"]["usage"]["cache_creation"] = {
            "ephemeral_5m_input_tokens": "x",
            "ephemeral_1h_input_tokens": 2,
        }
        _write(tmp_path / "p" / "s.jsonl", [rec])
        (c,) = tr.read(tmp_path).calls
        assert (c.cache_write_5m_tokens, c.cache_write_1h_tokens) == (0, 2)

    def test_non_object_cache_creation_means_absent(self, tmp_path: Path) -> None:
        rec = _asst(output_tokens=1, cache_creation_input_tokens=5)
        rec["message"]["usage"]["cache_creation"] = "oops"
        _write(tmp_path / "p" / "s.jsonl", [rec])
        (c,) = tr.read(tmp_path).calls
        assert (c.cache_write_5m_tokens, c.cache_write_1h_tokens) == (5, 0)

    @pytest.mark.parametrize(
        "mutate",
        [
            lambda r: r.update(message="text"),
            lambda r: r.update(message=None),
            lambda r: r.update(message=[1]),
            lambda r: r["message"].update(usage="text"),
            lambda r: r["message"].update(usage=[1, 2]),
            lambda r: r["message"].update(usage={}),
            lambda r: r["message"].pop("usage"),
        ],
    )
    def test_unusable_usage_yields_no_call(self, tmp_path: Path, mutate) -> None:
        rec = _asst(output_tokens=1)
        mutate(rec)
        _write(tmp_path / "p" / "s.jsonl", [rec])
        assert tr.read(tmp_path).calls == []

    def test_non_string_model_and_timestamp(self, tmp_path: Path) -> None:
        rec = _asst(output_tokens=1)
        rec["message"]["model"] = {"x": 1}
        rec["timestamp"] = 12345
        _write(tmp_path / "p" / "s.jsonl", [rec])
        (c,) = tr.read(tmp_path).calls
        assert c.model is None and c.timestamp is None
        assert tr.read(tmp_path, since="2000-01-01").calls == []

    def test_unhashable_ids_do_not_raise(self, tmp_path: Path) -> None:
        rec = _asst(output_tokens=1)
        rec["message"]["id"] = ["a"]
        rec["requestId"] = {"b": 1}
        rec["uuid"] = ["c"]
        _write(tmp_path / "p" / "s.jsonl", [rec, dict(rec)])
        assert len(tr.read(tmp_path).calls) == 2

    def test_non_dict_attachment_record_and_subtype(self, tmp_path: Path) -> None:
        _write(
            tmp_path / "p" / "s.jsonl",
            [{"type": "attachment", "attachment": {"type": ["x"]}}, {"type": "attachment"}],
        )
        (a,) = tr.read(tmp_path).attachments
        assert a.subtype is None
