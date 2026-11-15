"""Tests for cost_ledger, the per-session and per-agent spend ledger (slice 4, #1331).

The oracle is ``fixtures/cost_ledger_rows/EXPECTED.json``, derived from the spec
before the module existed. Token counts in the fixture are multiples of 62500, so
every dollar figure is exact in binary floating point and in six decimals; the
tests compare dollars with ``==``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

ENGINE = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(ENGINE))

import cost_ledger

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "cost_ledger_rows"
ROOT = FIXTURES / "projects"
EXPECTED = json.loads((FIXTURES / "EXPECTED.json").read_text())
TODAY = date(2026, 11, 14)
KINDS = ("input", "output", "cache_read", "write_5m", "write_1h")


def build(root: Path = ROOT, since: str | None = "2026-11-10", until: str | None = "2026-11-12") -> dict:
    return cost_ledger.build_ledger(root, since=since, until=until, today=TODAY)


def agents(ledger: dict) -> list[tuple[dict, dict]]:
    return [(s, a) for s in ledger["sessions"] for a in s["agents"]]


def agent_row(ledger: dict, project: str, session: str, agent_id: str) -> dict:
    for s, a in agents(ledger):
        if (s["project"], s["session_id"], a["agent_id"]) == (project, session, agent_id):
            return a
    raise AssertionError(f"no agent row {project}/{session}/{agent_id}")


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ENGINE / "cost_ledger.py"), *args],
        capture_output=True,
        text=True,
    )


# ---------------------------------------------------------------------------
# L1, L3, L6 totals against the oracle
# ---------------------------------------------------------------------------
class TestTotals:
    def test_totals_match_oracle(self) -> None:
        totals = build()["totals"]
        want = EXPECTED["totals"]
        assert totals["calls"] == want["calls"]
        assert totals["unpriced_calls"] == want["unpriced_calls"]
        assert totals["usd"] == want["usd"]
        assert totals["usd_breakdown"] == want["usd_breakdown"]
        assert totals["tokens"] == want["tokens"]
        assert totals["main_usd"] == want["main_usd"]
        assert totals["subagent_usd"] == want["subagent_usd"]

    def test_window_is_inclusive_on_both_ends_and_per_call(self) -> None:
        # m1 (day before since) and m4 (day after until) share a file with m2 and m3.
        ledger = build()
        main = agent_row(ledger, "-proj-alpha", "sess-1", "main")
        assert main["calls"] == 3  # m2 on since, m3 on until, m6 unpriced

    def test_coverage_matches_oracle(self) -> None:
        assert build()["coverage"] == EXPECTED["coverage"]

    def test_undated_call_in_no_row(self) -> None:
        ledger = build()
        assert ledger["coverage"]["undated_calls"] == 1
        total_tokens = sum(a["tokens"]["input"] for _, a in agents(ledger))
        assert total_tokens == EXPECTED["totals"]["tokens"]["input"]

    def test_unpriced_lists_in_window_calls_only(self) -> None:
        unpriced = build()["unpriced"]
        assert [(r["model"], r["calls"]) for r in unpriced] == [("claude-unlisted-9", 1)]

    def test_unpriced_call_counts_tokens_but_no_dollars(self) -> None:
        main = agent_row(build(), "-proj-alpha", "sess-1", "main")
        assert main["unpriced_calls"] == 1
        # m2 + m3 + m6 input units 2 + 1 + 3
        assert main["tokens"]["input"] == 6 * 62500
        assert main["by_model"]["claude-unlisted-9"] == {"calls": 1, "usd": 0.0}


# ---------------------------------------------------------------------------
# L4 session rows
# ---------------------------------------------------------------------------
class TestSessionRows:
    def test_same_session_id_under_two_projects_is_two_rows(self) -> None:
        keys = [(s["project"], s["session_id"]) for s in build()["sessions"]]
        assert keys == [("-proj-alpha", "sess-1"), ("-proj-beta", "sess-1")]

    def test_session_without_window_calls_has_no_row(self) -> None:
        assert ("-proj-beta", "sess-2") not in [
            (s["project"], s["session_id"]) for s in build()["sessions"]
        ]

    def test_session_usd_matches_oracle(self) -> None:
        got = {f"{s['project']}/{s['session_id']}": s["usd"] for s in build()["sessions"]}
        assert got == EXPECTED["session_usd"]

    def test_first_and_last_timestamp_are_raw_in_window_extremes(self) -> None:
        s = build()["sessions"][0]
        assert s["first_timestamp"] == "2026-11-10T00:00:00Z"
        assert s["last_timestamp"] == "2026-11-12T23:59:59Z"

    def test_session_fields(self) -> None:
        s = build()["sessions"][0]
        assert set(s) == {
            "project", "session_id", "first_timestamp", "last_timestamp", "calls",
            "unpriced_calls", "usd", "tokens", "usd_breakdown", "agents",
        }
        assert set(s["tokens"]) == set(KINDS)
        assert set(s["usd_breakdown"]) == set(KINDS)


# ---------------------------------------------------------------------------
# L5 agent rows
# ---------------------------------------------------------------------------
class TestAgentRows:
    def test_main_first_then_agent_id(self) -> None:
        ids = [a["agent_id"] for a in build()["sessions"][0]["agents"]]
        assert ids == ["main", "aa1", "aa2", "aa3", "aa4", "aa5", "aa6"]

    def test_agent_row_has_no_nested_agents(self) -> None:
        for _, a in agents(build()):
            assert "agents" not in a
            assert set(a) == {
                "agent_id", "agent_type", "model", "by_model", "calls", "unpriced_calls",
                "usd", "tokens", "usd_breakdown",
            }

    def test_agent_types(self) -> None:
        ledger = build()
        got = {a["agent_id"]: a["agent_type"] for a in ledger["sessions"][0]["agents"]}
        assert got == {
            "main": "main", "aa1": "reviewer", "aa2": "explorer", "aa3": "reviewer",
            "aa4": "scout",  # no meta file: attributionAgent
            "aa5": "unknown",  # neither
            "aa6": "fallback-name",  # malformed meta never raises, falls back
        }

    def test_two_subagents_of_one_type_are_two_rows(self) -> None:
        ledger = build()
        reviewers = [a for _, a in agents(ledger) if a["agent_type"] == "reviewer"]
        assert sorted(a["agent_id"] for a in reviewers) == ["aa1", "aa3"]

    def test_model_single_mixed_and_by_model(self) -> None:
        ledger = build()
        main = agent_row(ledger, "-proj-alpha", "sess-1", "main")
        assert main["model"] == "mixed"
        assert set(main["by_model"]) == {"claude-opus-4-8", "claude-opus-4-7", "claude-unlisted-9"}
        assert sum(v["calls"] for v in main["by_model"].values()) == main["calls"]
        assert round(sum(v["usd"] for v in main["by_model"].values()), 6) == main["usd"]
        assert agent_row(ledger, "-proj-alpha", "sess-1", "aa2")["model"] == "claude-opus-4-8"
        assert agent_row(ledger, "-proj-alpha", "sess-1", "aa1")["model"] == "mixed"

    def test_model_unknown_when_no_call_has_one(self, tmp_path: Path) -> None:
        d = tmp_path / "-p" / "s1.jsonl"
        d.parent.mkdir()
        rec = {"type": "assistant", "requestId": "r1", "timestamp": "2026-11-11T00:00:00Z",
               "message": {"id": "m1", "usage": {"input_tokens": 5, "output_tokens": 1}}}
        d.write_text(json.dumps(rec) + "\n")
        row = build(tmp_path)["sessions"][0]["agents"][0]
        assert row["model"] == "unknown"
        assert row["by_model"] == {"unknown": {"calls": 1, "usd": 0.0}}


# ---------------------------------------------------------------------------
# L6 conservation and per-call membership
# ---------------------------------------------------------------------------
class TestConservation:
    def test_agents_sum_to_sessions_and_sessions_to_totals(self) -> None:
        ledger = build()
        for s in ledger["sessions"]:
            assert sum(a["calls"] for a in s["agents"]) == s["calls"]
            assert sum(a["unpriced_calls"] for a in s["agents"]) == s["unpriced_calls"]
            assert round(sum(a["usd"] for a in s["agents"]), 6) == s["usd"]
            for k in KINDS:
                assert sum(a["tokens"][k] for a in s["agents"]) == s["tokens"][k]
                assert round(sum(a["usd_breakdown"][k] for a in s["agents"]), 6) == s["usd_breakdown"][k]
        t = ledger["totals"]
        assert sum(s["calls"] for s in ledger["sessions"]) == t["calls"]
        assert round(sum(s["usd"] for s in ledger["sessions"]), 6) == t["usd"]
        for k in KINDS:
            assert sum(s["tokens"][k] for s in ledger["sessions"]) == t["tokens"][k]
            assert round(sum(s["usd_breakdown"][k] for s in ledger["sessions"]), 6) == t["usd_breakdown"][k]
        assert round(t["main_usd"] + t["subagent_usd"], 6) == t["usd"]

    @pytest.mark.parametrize("call_key", sorted(EXPECTED["calls"]))
    def test_each_in_window_call_is_in_exactly_its_session_and_agent_row(
        self, call_key: str, tmp_path: Path
    ) -> None:
        # Isolate one call: copy only its transcript line (and meta file) into a
        # fresh root, so the one row that appears is the call's own.
        want = EXPECTED["calls"][call_key]
        request_id = call_key.split("/")[1]
        for path in ROOT.rglob("*.jsonl"):
            lines = [ln for ln in path.read_text().splitlines() if f'"requestId": "{request_id}"' in ln]
            if not lines:
                continue
            dest = tmp_path / path.relative_to(ROOT)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text("\n".join(lines) + "\n")
            meta = path.with_name(path.stem + ".meta.json")
            if meta.exists():
                shutil.copy(meta, dest.with_name(meta.name))
        ledger = build(tmp_path)
        assert len(ledger["sessions"]) == 1
        s = ledger["sessions"][0]
        assert (s["project"], s["session_id"]) == (want["project"], want["session"])
        assert s["calls"] == 1
        assert len(s["agents"]) == 1
        a = s["agents"][0]
        assert (a["agent_id"], a["calls"]) == (want["agent_id"], 1)
        # A lone call has no sibling to infer a type from: it matches the oracle
        # whenever the meta file or attribution identifies it, else "unknown".
        assert a["agent_type"] == want["agent_type"]


# ---------------------------------------------------------------------------
# L2 windows
# ---------------------------------------------------------------------------
class TestWindow:
    def test_default_window_is_the_calendar_month_of_today(self) -> None:
        ledger = cost_ledger.build_ledger(ROOT, today=date(2026, 2, 14))
        assert ledger["window"] == {"since": "2026-02-01", "until": "2026-02-28"}
        assert ledger["totals"]["calls"] == 0

    def test_default_window_picks_up_the_month(self) -> None:
        ledger = cost_ledger.build_ledger(ROOT, today=TODAY)
        assert ledger["window"] == {"since": "2026-11-01", "until": "2026-11-30"}
        # adds m1, m4 and b2 (all in November) to the 11 windowed calls
        assert ledger["totals"]["calls"] == 14

    def test_one_flag_alone_leaves_the_other_end_open(self) -> None:
        since_only = build(since="2026-11-12", until=None)
        assert since_only["window"] == {"since": "2026-11-12", "until": None}
        assert since_only["totals"]["calls"] == 3  # m3, s4, m4
        until_only = build(since=None, until="2026-11-01")
        assert until_only["window"] == {"since": None, "until": "2026-11-01"}
        assert until_only["totals"]["calls"] == 1  # b2

    def test_empty_window_is_all_zero(self) -> None:
        ledger = build(since="2030-01-01", until="2030-01-02")
        assert ledger["sessions"] == []
        assert ledger["totals"]["calls"] == 0
        assert ledger["totals"]["usd"] == 0
        assert ledger["unpriced"] == []


# ---------------------------------------------------------------------------
# L7 prices
# ---------------------------------------------------------------------------
class TestPrices:
    def test_uses_budget_burn_table(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import budget_burn

        table = {k: dict(v) for k, v in budget_burn.MODEL_PRICES.items()}
        table["claude-opus-4-8"] = {**table["claude-opus-4-8"], "input": 50}
        monkeypatch.setattr(budget_burn, "MODEL_PRICES", table)
        got = build()["totals"]["usd_breakdown"]["input"]
        assert got > EXPECTED["totals"]["usd_breakdown"]["input"]


# ---------------------------------------------------------------------------
# L8 JSON
# ---------------------------------------------------------------------------
class TestJson:
    def run(self, tmp_path: Path, name: str = "out.json") -> Path:
        out = tmp_path / name
        proc = run_cli("--since", "2026-11-10", "--until", "2026-11-12",
                       "--projects-root", str(ROOT), "--json", str(out))
        assert proc.returncode == 0, proc.stderr
        return out

    def test_shape_and_formatting(self, tmp_path: Path) -> None:
        out = self.run(tmp_path)
        text = out.read_text()
        assert text.endswith("}\n") and not text.endswith("\n\n")
        obj = json.loads(text)
        assert text == json.dumps(obj, sort_keys=True, indent=2) + "\n"
        assert set(obj) == {
            "schema_version", "window", "totals", "coverage", "unpriced", "sessions",
            "skills", "unattributed", "meter", "recorded_cost",
        }
        assert obj["schema_version"] == 3
        assert obj["window"] == {"since": "2026-11-10", "until": "2026-11-12"}
        assert obj["totals"]["usd"] == EXPECTED["totals"]["usd"]
        assert obj["totals"]["main_usd"] == EXPECTED["totals"]["main_usd"]
        assert obj["coverage"] == EXPECTED["coverage"]

    def test_no_paths_or_host_in_output(self, tmp_path: Path) -> None:
        text = self.run(tmp_path).read_text()
        assert str(ROOT) not in text
        assert str(FIXTURES) not in text
        assert "/Users" not in text

    def test_two_runs_are_byte_identical(self, tmp_path: Path) -> None:
        a = self.run(tmp_path, "a.json").read_bytes()
        b = self.run(tmp_path, "b.json").read_bytes()
        assert a == b

    def test_dollars_rounded_to_six_places_at_output_only(self, tmp_path: Path) -> None:
        # 1 token of input at $5 per million is 5e-06; 1/3 of a cent style values
        # must round to six places in the file.
        d = tmp_path / "root" / "-p" / "s1.jsonl"
        d.parent.mkdir(parents=True)
        rec = {"type": "assistant", "requestId": "r", "timestamp": "2026-11-11T00:00:00Z",
               "message": {"id": "m", "model": "claude-opus-4-8", "usage": {"input_tokens": 1, "output_tokens": 1}}}
        d.write_text(json.dumps(rec) + "\n")
        out = tmp_path / "o.json"
        proc = run_cli("--since", "2026-11-11", "--until", "2026-11-11",
                       "--projects-root", str(tmp_path / "root"), "--json", str(out))
        assert proc.returncode == 0
        obj = json.loads(out.read_text())
        assert obj["totals"]["usd"] == 3e-05  # 5e-06 + 25e-06
        assert obj["totals"]["usd_breakdown"]["input"] == 5e-06


# ---------------------------------------------------------------------------
# L9 report and L10 CLI
# ---------------------------------------------------------------------------
class TestReport:
    def report(self) -> str:
        proc = run_cli("--since", "2026-11-10", "--until", "2026-11-12", "--projects-root", str(ROOT))
        assert proc.returncode == 0, proc.stderr
        return proc.stdout

    def test_report_sections(self) -> None:
        out = self.report()
        assert "2026-11-10" in out and "2026-11-12" in out
        assert "$25.09" in out  # window total, 25.09375
        assert "$7.75" in out and "$17.34" in out  # main versus subagent
        assert "31%" in out and "69%" in out
        assert "reviewer" in out and "explorer" in out and "scout" in out
        assert "claude-opus-4-8" in out and "claude-opus-4-7" in out
        assert "-proj-alpha" in out and "-proj-beta" in out
        assert "claude-unlisted-9" in out
        assert "undated" in out

    def test_report_by_model_uses_each_calls_own_model(self) -> None:
        # Subagent aa1 is "mixed" but its calls bill under their own models.
        out = self.report()
        assert "mixed" not in out

    def test_unpriced_section_absent_when_empty(self, tmp_path: Path) -> None:
        proc = run_cli("--since", "2030-01-01", "--until", "2030-01-02", "--projects-root", str(ROOT))
        assert proc.returncode == 0
        assert "claude-unlisted-9" not in proc.stdout
        assert "$0.00" in proc.stdout
        assert "0%" in proc.stdout

    def test_top_sessions_ordered_by_dollars(self) -> None:
        out = self.report()
        assert out.index("-proj-alpha") < out.index("-proj-beta", out.index("-proj-alpha"))

    def test_report_is_printed_with_json(self, tmp_path: Path) -> None:
        proc = run_cli("--since", "2026-11-10", "--until", "2026-11-12",
                       "--projects-root", str(ROOT), "--json", str(tmp_path / "x.json"))
        assert "$25.09" in proc.stdout


class TestCli:
    @pytest.mark.parametrize(
        "args",
        [
            ["--since", "2026-13-01"],
            ["--until", "yesterday"],
            ["--since", "20261110"],
            ["--since", "2026-11-12", "--until", "2026-11-10"],
        ],
    )
    def test_bad_window_exits_2_with_one_line_and_no_json(self, args: list[str], tmp_path: Path) -> None:
        out = tmp_path / "never.json"
        proc = run_cli(*args, "--projects-root", str(ROOT), "--json", str(out))
        assert proc.returncode == 2
        assert proc.stdout == ""
        assert len(proc.stderr.strip().splitlines()) == 1
        assert not out.exists()

    def test_default_run_with_no_flags_succeeds(self, tmp_path: Path) -> None:
        proc = run_cli("--projects-root", str(tmp_path))
        assert proc.returncode == 0, proc.stderr


# ---------------------------------------------------------------------------
# Review round: ordering, rounding, UTC window, CLI refusals, subagent rows
# ---------------------------------------------------------------------------
def put_call(
    root: Path,
    project: str,
    session: str,
    rid: str,
    ts: object = "2026-11-11T00:00:00Z",
    model: str = "claude-opus-4-8",
    **usage: int,
) -> None:
    """Append one assistant call to ``root/project/session.jsonl``."""
    path = root / project / f"{session}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "type": "assistant",
        "requestId": rid,
        "timestamp": ts,
        "message": {"id": f"m_{rid}", "model": model, "usage": usage or {"input_tokens": 1}},
    }
    with path.open("a") as fh:
        fh.write(json.dumps(rec) + "\n")


class TestOrderingAndRounding:
    def test_sessions_sorted_by_project_then_session_id(self, tmp_path: Path) -> None:
        # The reader walks sorted paths, so the calls arrive as
        # (-pa, s-x), (-pa, s), (-pb, r): "s-x.jsonl" sorts before "s.jsonl".
        # Sorted by session id alone they would read s, s-x, r.
        for project, session in [("-pb", "r"), ("-pa", "s"), ("-pa", "s-x")]:
            put_call(tmp_path, project, session, f"{project}{session}")
        keys = [(s["project"], s["session_id"]) for s in build(tmp_path)["sessions"]]
        assert keys == [("-pa", "s"), ("-pa", "s-x"), ("-pb", "r")]

    def test_dollars_sum_unrounded_then_round_once(self, tmp_path: Path) -> None:
        # Ten calls of one cache-read token on haiku (0.1 per million): each call
        # is 1e-07, so rounding per call gives 0, while the sum is 1e-06.
        for i in range(10):
            put_call(tmp_path, "-p", "s1", f"r{i}", model="claude-haiku-4-5", cache_read_input_tokens=1)
        ledger = build(tmp_path)
        session = ledger["sessions"][0]
        assert session["usd"] == 1e-06
        assert session["agents"][0]["usd"] == 1e-06
        assert session["usd_breakdown"]["cache_read"] == 1e-06
        assert ledger["totals"]["usd"] == 1e-06


class TestUtcWindow:
    OFFSET = "2026-11-12T23:30:00-05:00"  # 2026-11-13T04:30:00Z

    def test_offset_timestamp_is_windowed_by_its_utc_date(self, tmp_path: Path) -> None:
        put_call(tmp_path, "-p", "s1", "r1", ts=self.OFFSET)
        assert build(tmp_path, since="2026-11-10", until="2026-11-12")["totals"]["calls"] == 0
        assert build(tmp_path, since="2026-11-13", until="2026-11-13")["totals"]["calls"] == 1
        assert build(tmp_path, since="2026-11-10", until="2026-11-13")["totals"]["calls"] == 1

    def test_unparsable_timestamp_is_undated(self, tmp_path: Path) -> None:
        put_call(tmp_path, "-p", "s1", "r1", ts="2026-11-11 not a time")
        put_call(tmp_path, "-p", "s1", "r2", ts="2026-11-11T00:00:00Z")
        ledger = build(tmp_path)
        assert ledger["coverage"]["undated_calls"] == 1
        assert ledger["totals"]["calls"] == 1

    def test_helper_accepts_z_and_offsets(self) -> None:
        assert cost_ledger.utc_day("2026-11-12T23:59:59Z") == "2026-11-12"
        assert cost_ledger.utc_day(self.OFFSET) == "2026-11-13"
        assert cost_ledger.utc_day("2026-11-13T01:00:00+05:30") == "2026-11-12"
        assert cost_ledger.utc_day(None) is None
        assert cost_ledger.utc_day(12345) is None
        assert cost_ledger.utc_day("nonsense") is None

    def test_first_and_last_timestamp_are_extremes_by_instant_as_raw_strings(self, tmp_path: Path) -> None:
        late_by_instant = self.OFFSET  # 04:30Z on the 13th
        early_by_instant = "2026-11-13T01:00:00Z"  # later as a string
        put_call(tmp_path, "-p", "s1", "r1", ts=late_by_instant)
        put_call(tmp_path, "-p", "s1", "r2", ts=early_by_instant)
        row = build(tmp_path, since="2026-11-13", until="2026-11-13")["sessions"][0]
        assert row["first_timestamp"] == early_by_instant
        assert row["last_timestamp"] == late_by_instant


class TestCliRefusals:
    def test_json_into_missing_directory_exits_2_cleanly(self, tmp_path: Path) -> None:
        out = tmp_path / "no-such-dir" / "out.json"
        proc = run_cli("--since", "2026-11-10", "--until", "2026-11-12",
                       "--projects-root", str(ROOT), "--json", str(out))
        assert proc.returncode == 2
        assert "Traceback" not in proc.stderr
        assert len(proc.stderr.strip().splitlines()) == 1
        assert not out.parent.exists()

    def test_nonexistent_projects_root_exits_2_and_writes_no_json(self, tmp_path: Path) -> None:
        out = tmp_path / "never.json"
        proc = run_cli("--projects-root", str(tmp_path / "nope"), "--json", str(out))
        assert proc.returncode == 2
        assert proc.stdout == ""
        assert len(proc.stderr.strip().splitlines()) == 1
        assert not out.exists()

    def test_projects_root_that_is_a_file_exits_2(self, tmp_path: Path) -> None:
        a_file = tmp_path / "file.txt"
        a_file.write_text("x")
        proc = run_cli("--projects-root", str(a_file))
        assert proc.returncode == 2
        assert len(proc.stderr.strip().splitlines()) == 1

    def test_existing_empty_root_reports_zeros(self, tmp_path: Path) -> None:
        out = tmp_path / "o.json"
        proc = run_cli("--projects-root", str(tmp_path), "--json", str(out))
        assert proc.returncode == 0, proc.stderr
        assert json.loads(out.read_text())["totals"]["calls"] == 0


class TestAgentRowsMatchOracle:
    @pytest.mark.parametrize("key", sorted(EXPECTED["agent_rows"]))
    def test_subagent_row_calls_and_usd(self, key: str) -> None:
        project, session, agent_id = key.split("/")
        row = agent_row(build(), project, session, agent_id)
        want = EXPECTED["agent_rows"][key]
        assert (row["calls"], row["usd"]) == (want["calls"], want["usd"])
