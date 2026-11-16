"""Tests for slice 10 (issue 1337): cost by trigger and the largest-sessions views.

Every transcript is built by hand into a tmp projects root. Calls carry input
tokens only, so a call's dollars are its input tokens times one known per-token
rate, read once from the pricer.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

ENGINE = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(ENGINE))

import context_spend
import cost_ledger
import transcript_reader as tr

TODAY = date(2026, 11, 14)
MODEL = "claude-opus-4-8"
PROJ = "-proj-a"
SKILL_REFS = Path(__file__).resolve().parents[2] / "skills" / "vault-budget" / "references"
SCHEMA_DOC = SKILL_REFS / "cost-ledger-schema.md"
COMMAND_DOC = SKILL_REFS / "command.md"


def _rate() -> float:
    """Dollars per input token for MODEL, from the pricer itself."""
    import budget_burn
    import pricing

    call = tr.Call(
        key=("k",), project="p", session_id="s", is_subagent=False, agent_id=None,
        model=MODEL, timestamp="2026-11-11T00:00:00Z", input_tokens=1_000_000,
        output_tokens=0, cache_read_tokens=0, cache_write_tokens=0,
        cache_write_5m_tokens=0, cache_write_1h_tokens=0,
    )
    return pricing.Pricer(budget_burn.MODEL_PRICES).price(call).total_usd / 1_000_000


RATE = _rate()


def usd(tokens: int) -> float:
    return tokens * RATE


def write(path: Path, lines: list) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
    return path


def asst(rid: str, i: int = 0, cr: int = 0, cw: int = 0, ts: str = "2026-11-11T10:00:00Z") -> dict:
    usage = {"input_tokens": i, "cache_read_input_tokens": cr, "cache_creation_input_tokens": cw}
    return {
        "type": "assistant", "requestId": rid, "timestamp": ts,
        "message": {"id": f"m_{rid}", "model": MODEL, "usage": usage},
    }


def user(origin: str | None = None, text: str = "go", meta: bool = False) -> dict:
    rec: dict = {"type": "user", "timestamp": "2026-11-11T09:59:00Z", "message": {"content": text}}
    if origin:
        rec["origin"] = {"kind": origin}
    if meta:
        rec["isMeta"] = True
    return rec


def result_rec() -> dict:
    return {
        "type": "user", "timestamp": "2026-11-11T09:59:30Z",
        "message": {"content": [{"type": "tool_result", "tool_use_id": "t", "content": "x"}]},
    }


def main_file(root: Path, session: str, lines: list, project: str = PROJ) -> Path:
    return write(root / project / f"{session}.jsonl", lines)


def sub_file(root: Path, session: str, agent: str, lines: list, project: str = PROJ) -> Path:
    return write(root / project / session / "subagents" / f"agent-{agent}.jsonl", lines)


def build(root: Path) -> dict:
    return cost_ledger.build_ledger(root, since="2026-11-01", until="2026-11-30", today=TODAY)


def trig(ledger: dict, label: str) -> dict:
    return next(r for r in ledger["triggers"] if r["trigger"] == label)


def session(ledger: dict, sid: str) -> dict:
    return next(s for s in ledger["sessions"] if s["session_id"] == sid)


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ENGINE / "cost_ledger.py"), *args], capture_output=True, text=True
    )


# ---------------------------------------------------------------------------
# A1: one classifier
# ---------------------------------------------------------------------------
class TestSharedClassifier:
    def test_context_spend_reexports_the_readers_objects(self) -> None:
        assert context_spend.classify_trigger is tr.classify_trigger
        assert context_spend.TRIGGERS is tr.TRIGGERS

    def test_labels_and_order(self) -> None:
        assert tr.TRIGGERS == (
            "human-typed", "task-notification", "meta/system-injected", "programmatic", "hook",
        )

    def test_ledger_has_no_second_classifier(self) -> None:
        assert not hasattr(cost_ledger, "classify_trigger")


# ---------------------------------------------------------------------------
# B: cost by trigger
# ---------------------------------------------------------------------------
class TestTriggerRows:
    def make(self, root: Path) -> None:
        main_file(root, "s1", [
            user("human"), asst("h", i=100),
            user("task-notification"), asst("tn", i=200),
            user(meta=True), asst("mt", i=300),
            user(), asst("pg", i=400),
            user(text="Stop hook feedback: x"), asst("hk", i=500),
        ])

    def test_each_label_reaches_its_row(self, tmp_path: Path) -> None:
        self.make(tmp_path)
        ledger = build(tmp_path)
        want = {
            "human-typed": 100, "task-notification": 200, "meta/system-injected": 300,
            "programmatic": 400, "hook": 500, "none": 0,
        }
        for label, tokens in want.items():
            row = trig(ledger, label)
            assert row["usd"] == pytest.approx(usd(tokens), abs=1e-6)
            assert row["calls"] == (1 if tokens else 0)

    def test_all_six_rows_in_order_with_zeros(self, tmp_path: Path) -> None:
        main_file(tmp_path, "s1", [user("human"), asst("a", i=10)])
        rows = build(tmp_path)["triggers"]
        assert [r["trigger"] for r in rows] == [*tr.TRIGGERS, "none"]
        assert len(rows) == 6
        empty = trig(build(tmp_path), "hook")
        assert empty == {
            "trigger": "hook", "calls": 0, "usd": 0.0, "main_usd": 0.0, "subagent_usd": 0.0,
            "after_tool_result_calls": 0, "after_tool_result_usd": 0.0,
            "share_of_total": 0.0,
        }

    def test_none_when_no_user_record_before_the_call(self, tmp_path: Path) -> None:
        main_file(tmp_path, "s1", [asst("a", i=10), user("human"), asst("b", i=20)])
        ledger = build(tmp_path)
        assert trig(ledger, "none")["calls"] == 1
        assert trig(ledger, "human-typed")["calls"] == 1

    def test_tool_result_between_keeps_trigger_and_flags_call(self, tmp_path: Path) -> None:
        main_file(tmp_path, "s1", [user("human"), result_rec(), asst("a", i=100)])
        row = trig(build(tmp_path), "human-typed")
        assert row["calls"] == 1
        assert row["after_tool_result_calls"] == 1
        assert row["after_tool_result_usd"] == pytest.approx(usd(100), abs=1e-6)

    def test_second_call_with_no_new_user_record_keeps_trigger_and_clears_flag_not(
        self, tmp_path: Path
    ) -> None:
        # The flag follows the last *user* record, so an assistant record between does not clear it.
        main_file(tmp_path, "s1", [
            user("human"), asst("a", i=100), result_rec(), asst("b", i=200), asst("c", i=300),
        ])
        row = trig(build(tmp_path), "human-typed")
        assert row["calls"] == 3
        assert row["after_tool_result_calls"] == 2  # b and c, not a
        assert row["after_tool_result_usd"] == pytest.approx(usd(500), abs=1e-6)

    def test_new_user_record_clears_the_flag(self, tmp_path: Path) -> None:
        main_file(tmp_path, "s1", [result_rec(), asst("a", i=1), user("human"), asst("b", i=2)])
        ledger = build(tmp_path)
        assert trig(ledger, "none")["after_tool_result_calls"] == 1
        assert trig(ledger, "human-typed")["after_tool_result_calls"] == 0

    def test_subagent_file_does_not_inherit_parent_trigger(self, tmp_path: Path) -> None:
        main_file(tmp_path, "s1", [user("human"), asst("m", i=100)])
        sub_file(tmp_path, "s1", "x", [asst("sa", i=50), user("task-notification"), asst("sb", i=70)])
        ledger = build(tmp_path)
        assert trig(ledger, "none")["calls"] == 1
        assert trig(ledger, "none")["subagent_usd"] == pytest.approx(usd(50), abs=1e-6)
        assert trig(ledger, "task-notification")["subagent_usd"] == pytest.approx(usd(70), abs=1e-6)
        assert trig(ledger, "human-typed")["calls"] == 1

    def test_main_subagent_split(self, tmp_path: Path) -> None:
        main_file(tmp_path, "s1", [user("human"), asst("m", i=100)])
        sub_file(tmp_path, "s1", "x", [user("human"), asst("s", i=300)])
        row = trig(build(tmp_path), "human-typed")
        assert row["main_usd"] == pytest.approx(usd(100), abs=1e-6)
        assert row["subagent_usd"] == pytest.approx(usd(300), abs=1e-6)
        assert row["usd"] == pytest.approx(row["main_usd"] + row["subagent_usd"], abs=1e-6)

    def test_conservation_and_shares(self, tmp_path: Path) -> None:
        TestTriggerRows().make(tmp_path)
        sub_file(tmp_path, "s1", "x", [asst("sa", i=50)])
        ledger = build(tmp_path)
        rows = ledger["triggers"]
        assert round(sum(r["usd"] for r in rows), 6) == round(ledger["totals"]["usd"], 6)
        assert sum(r["calls"] for r in rows) == ledger["totals"]["calls"] == 6
        assert sum(r["share_of_total"] for r in rows) == pytest.approx(1.0, abs=1e-5)
        assert trig(ledger, "hook")["share_of_total"] == round(
            trig(ledger, "hook")["usd"] / ledger["totals"]["usd"], 6
        )

    def test_out_of_window_calls_are_not_counted(self, tmp_path: Path) -> None:
        main_file(tmp_path, "s1", [user("human"), asst("a", i=10, ts="2026-10-01T00:00:00Z"), asst("b", i=20)])
        ledger = build(tmp_path)
        assert sum(r["calls"] for r in ledger["triggers"]) == 1

    def test_empty_window_share_is_null(self, tmp_path: Path) -> None:
        tmp_path.mkdir(exist_ok=True)
        ledger = build(tmp_path)
        assert [r["share_of_total"] for r in ledger["triggers"]] == [None] * 6
        assert all(r["calls"] == 0 for r in ledger["triggers"])

    def test_text_section_order_and_sum_line(self, tmp_path: Path) -> None:
        TestTriggerRows().make(tmp_path)
        text = cost_ledger.report(build(tmp_path))
        head = (
            "Cost by trigger (all calls; a call's trigger is the last user record before it "
            "in its own transcript)"
        )
        assert head in text
        section = text.split(head, 1)[1].split("\n  Top 15 skills", 1)[0].strip().splitlines()
        labels = [ln.split()[0] for ln in section[:-1]]
        assert labels == ["hook", "programmatic", "meta/system-injected", "task-notification", "human-typed"]
        assert "none" not in labels  # zero-call rows are not printed
        assert "after tool result: $0.00 in 0 calls" in section[0]
        assert "%" in section[0] and section[0].split("%")[0][-1].isdigit()
        total = cost_ledger.build_ledger(
            tmp_path, since="2026-11-01", until="2026-11-30", today=TODAY
        )["totals"]["usd"]
        assert section[-1].strip() == f"Sum of rows ${total:,.2f}; window total ${total:,.2f}"

    def test_text_ties_break_by_label(self, tmp_path: Path) -> None:
        main_file(tmp_path, "s1", [user("human"), asst("a", i=10), user(), asst("b", i=10)])
        text = cost_ledger.report(build(tmp_path))
        assert text.index("human-typed  ") < text.index("programmatic  ")


class TestExport:
    def test_export_carries_triggers_and_no_shape(self, tmp_path: Path) -> None:
        root = tmp_path / "projects"
        main_file(root, "s1", [user("human"), asst("a", i=300_000)])
        agg = tmp_path / "agg.json"
        full = tmp_path / "full.json"
        proc = run_cli("--since", "2026-11-01", "--until", "2026-11-30", "--projects-root", str(root),
                       "--json", str(full), "--export-aggregates", str(agg))
        assert proc.returncode == 0, proc.stderr
        obj = json.loads(agg.read_text())
        assert obj["aggregates_version"] == 1
        assert obj["triggers"] == json.loads(full.read_text())["triggers"]
        text = agg.read_text()
        assert "shape" not in text and "long_context" not in text and "s1" not in text

    def test_export_has_no_largest_session_rows(self, tmp_path: Path) -> None:
        main_file(tmp_path, "s1", [asst("a", i=10)])
        agg = cost_ledger.build_aggregates(build(tmp_path))
        assert "sessions" not in agg


# ---------------------------------------------------------------------------
# C: largest sessions
# ---------------------------------------------------------------------------
class TestShape:
    def test_constant_and_json_key(self, tmp_path: Path) -> None:
        assert cost_ledger.LONG_CONTEXT_TOKENS == 200_000
        main_file(tmp_path, "s1", [asst("a", i=1)])
        assert build(tmp_path)["long_context_tokens"] == 200_000

    def test_context_is_input_plus_read_plus_total_write(self, tmp_path: Path) -> None:
        main_file(tmp_path, "s1", [asst("a", i=10, cr=200, cw=3000)])
        shape = session(build(tmp_path), "s1")["shape"]
        assert shape["context_first"] == shape["context_median"] == shape["context_max"] == 3210

    def test_first_median_max_odd(self, tmp_path: Path) -> None:
        main_file(tmp_path, "s1", [asst("a", i=500), asst("b", i=100), asst("c", i=300)])
        shape = session(build(tmp_path), "s1")["shape"]
        assert shape == {
            "main_calls": 3, "context_first": 500, "context_median": 300, "context_max": 500,
            "usd_above_long_context": 0.0, "share_above_long_context": 0.0,
        }

    def test_median_even(self, tmp_path: Path) -> None:
        main_file(tmp_path, "s1", [asst("a", i=100), asst("b", i=200), asst("c", i=700), asst("d", i=900)])
        shape = session(build(tmp_path), "s1")["shape"]
        assert shape["context_median"] == 450
        assert shape["context_first"] == 100 and shape["context_max"] == 900

    def test_subagents_excluded_from_context_included_in_dollars(self, tmp_path: Path) -> None:
        main_file(tmp_path, "s1", [asst("a", i=1000)])
        sub_file(tmp_path, "s1", "x", [asst("s", i=250_000)])
        s = session(build(tmp_path), "s1")
        shape = s["shape"]
        assert shape["main_calls"] == 1
        assert shape["context_max"] == 1000
        assert shape["usd_above_long_context"] == pytest.approx(usd(250_000), abs=1e-6)
        assert shape["share_above_long_context"] == round(
            usd(250_000) / (usd(251_000)), 6
        ) or shape["share_above_long_context"] == pytest.approx(250_000 / 251_000, abs=1e-5)

    def test_threshold_is_strict(self, tmp_path: Path) -> None:
        main_file(tmp_path, "s1", [asst("a", i=200_000)])
        main_file(tmp_path, "s2", [asst("b", i=200_001)])
        ledger = build(tmp_path)
        assert session(ledger, "s1")["shape"]["usd_above_long_context"] == 0.0
        assert session(ledger, "s2")["shape"]["usd_above_long_context"] == pytest.approx(
            usd(200_001), abs=1e-6
        )

    def test_threshold_counts_cache_tokens(self, tmp_path: Path) -> None:
        main_file(tmp_path, "s1", [asst("a", i=1, cr=100_000, cw=100_000)])
        assert session(build(tmp_path), "s1")["shape"]["usd_above_long_context"] > 0

    def test_zero_dollar_session(self, tmp_path: Path) -> None:
        main_file(tmp_path, "s1", [asst("a")])
        shape = session(build(tmp_path), "s1")["shape"]
        assert shape["main_calls"] == 1 and shape["context_max"] == 0
        assert shape["share_above_long_context"] is None
        assert shape["usd_above_long_context"] == 0.0

    def test_session_with_no_main_calls(self, tmp_path: Path) -> None:
        sub_file(tmp_path, "s1", "x", [asst("s", i=300_000)])
        shape = session(build(tmp_path), "s1")["shape"]
        assert shape["main_calls"] == 0
        assert shape["context_first"] is None
        assert shape["context_median"] is None
        assert shape["context_max"] is None
        assert shape["usd_above_long_context"] > 0

    def test_largest_sessions_section_matches_top_ten(self, tmp_path: Path) -> None:
        for n in range(12):
            main_file(tmp_path, f"s{n:02d}", [asst(f"r{n}", i=1000 * (n + 1))])
        ledger = build(tmp_path)
        text = cost_ledger.report(ledger)
        head = "Largest sessions (context = input + cache read + cache write tokens per main-thread call)"
        assert text.index("Top 10 sessions:") < text.index(head) < text.index("Cost by trigger")
        top = text.split("Top 10 sessions:", 1)[1].split(head, 1)[0].strip().splitlines()
        shaped = text.split(head, 1)[1].split("Cost by trigger", 1)[0].strip().splitlines()
        assert len(top) == len(shaped) == 10
        top_ids = [ln.split()[2] for ln in top]
        shaped_ids = [ln.split()[2] for ln in shaped]
        assert top_ids == shaped_ids
        assert top_ids[0] == "s11" and "s00" not in top_ids

    def test_row_text(self, tmp_path: Path) -> None:
        main_file(tmp_path, "s1", [asst("a", i=1000), asst("b", i=300_000), asst("c", i=2000)])
        sub_file(tmp_path, "s1", "x", [asst("s", i=1)])
        text = cost_ledger.report(build(tmp_path))
        row = next(ln for ln in text.splitlines() if "context first" in ln)
        total = session(build(tmp_path), "s1")["usd"]
        above = session(build(tmp_path), "s1")["shape"]["usd_above_long_context"]
        assert "3 main calls" in row
        assert "first 1,000 / median 2,000 / max 300,000" in row
        pct = above / total * 100
        assert f"above 200k: ${above:,.2f} of ${total:,.2f} ({pct:.1f}%)" in row

    def test_null_context_prints_dash(self, tmp_path: Path) -> None:
        sub_file(tmp_path, "s1", "x", [asst("s", i=300_000)])
        row = next(ln for ln in cost_ledger.report(build(tmp_path)).splitlines() if "context first" in ln)
        assert "context first - / median - / max -" in row
        assert "above 200k:" in row


# ---------------------------------------------------------------------------
# schema and documents
# ---------------------------------------------------------------------------
class TestVersionAndDocs:
    def test_schema_version(self) -> None:
        assert cost_ledger.SCHEMA_VERSION == 7
        assert cost_ledger.AGGREGATES_VERSION == 1

    def test_schema_doc_states_version_and_new_fields(self) -> None:
        doc = SCHEMA_DOC.read_text(encoding="utf-8")
        assert "Current `schema_version`: 7." in doc
        for path in ("triggers", "long_context_tokens", "sessions[].shape"):
            assert f"| `{path}` |" in doc

    def test_command_doc_names_the_new_sections(self) -> None:
        doc = COMMAND_DOC.read_text(encoding="utf-8")
        assert "Largest sessions" in doc and "Cost by trigger" in doc
