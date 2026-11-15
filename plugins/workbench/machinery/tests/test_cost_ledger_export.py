"""Tests for the cost ledger's meter check, recorded-cost check and aggregates-only export (slice 6, #1333).

The oracle is ``fixtures/cost_ledger_export/EXPECTED.json``, derived by hand from the
spec before the code: every call is 62500 tokens of one kind on a model priced at
5 or 25 dollars per million, so each figure is exact in binary floating point.
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

import cost_ledger

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures" / "cost_ledger_export"
ROOT = FIXTURE / "projects"
WANT = json.loads((FIXTURE / "EXPECTED.json").read_text())
TODAY = date(2026, 11, 14)
WINDOW = ("--since", "2026-11-10", "--until", "2026-11-12")


def build(root: Path = ROOT, since: str = "2026-11-10", until: str = "2026-11-12") -> dict:
    return cost_ledger.build_ledger(root, since=since, until=until, today=TODAY)


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ENGINE / "cost_ledger.py"), *args], capture_output=True, text=True
    )


def tiny_root(tmp_path: Path, input_tokens: int) -> Path:
    """One main session with one in-window call of ``input_tokens`` (5 dollars per million)."""
    path = tmp_path / "projects" / "-zq-tiny" / "sess-zt1.jsonl"
    path.parent.mkdir(parents=True)
    rec = {
        "type": "assistant", "uuid": "zq-t1", "requestId": "zq-tr1",
        "message": {"id": "zq-tm1", "model": "claude-opus-4-8",
                    "usage": {"input_tokens": input_tokens, "output_tokens": 0}},
        "timestamp": "2026-11-11T01:00:00Z",
    }
    path.write_text(json.dumps(rec) + "\n")
    return tmp_path / "projects"


# ---------------------------------------------------------------------------
# recorded-cost check (X1-X3)
# ---------------------------------------------------------------------------
class TestRecordedCost:
    ledger = build()

    def test_matches_the_oracle(self) -> None:
        want = {k: v for k, v in WANT["recorded_cost"].items() if not k.startswith("_")}
        assert self.ledger["recorded_cost"] == want

    def test_exact_key_set(self) -> None:
        assert set(self.ledger["recorded_cost"]) == {
            "sessions_in_window", "sessions_comparable", "ledger_usd", "recorded_usd",
            "difference_usd", "gap_percent", "flagged_unknown_sessions",
            "flagged_ledger_usd", "flagged_recorded_usd",
        }

    def test_flagged_sessions_are_not_in_the_comparable_sums(self) -> None:
        rc = self.ledger["recorded_cost"]
        assert rc["ledger_usd"] == 7.5 and rc["recorded_usd"] == 8.0

    def test_gap_percent_is_null_when_nothing_is_comparable(self) -> None:
        ledger = build(since="2030-01-01", until="2030-01-02")
        rc = ledger["recorded_cost"]
        assert rc["sessions_in_window"] == 0 and rc["sessions_comparable"] == 0
        assert rc["recorded_usd"] == 0 and rc["gap_percent"] is None
        assert rc["difference_usd"] == 0

    def test_open_window_session_with_every_call_in_range_is_comparable(self) -> None:
        # With no upper bound the 11-13 subagent call of sess-zx4 is inside the window.
        ledger = cost_ledger.build_ledger(ROOT, since="2026-11-10", until=None, today=TODAY)
        rc = ledger["recorded_cost"]
        assert rc["sessions_comparable"] == 4
        assert rc["ledger_usd"] == 7.5 + 0.625 and rc["recorded_usd"] == 9.0

    def test_report_prints_comparable_and_flagged_lines_without_a_warning(self) -> None:
        proc = run_cli(*WINDOW, "--projects-root", str(ROOT))
        assert proc.returncode == 0, proc.stderr
        lines = [l for l in proc.stdout.splitlines() if "Recorded-cost" in l]
        assert len(lines) == 2
        assert "3 of 9" in lines[0] and "$7.50" in lines[0] and "$8.00" in lines[0] and "6.2%" in lines[0]
        assert "not comparable" in lines[1] and "$1.88" in lines[1] and "$3.00" in lines[1]
        assert "WARN" not in proc.stdout.upper() and "METER" not in proc.stdout

    def test_no_flagged_line_when_none_flagged(self, tmp_path: Path) -> None:
        proc = run_cli(*WINDOW, "--projects-root", str(tiny_root(tmp_path, 2_200_000)))
        assert len([l for l in proc.stdout.splitlines() if "Recorded-cost" in l]) == 1

    def test_exit_code_unchanged_by_a_large_gap(self) -> None:
        assert run_cli(*WINDOW, "--projects-root", str(ROOT)).returncode == 0


# ---------------------------------------------------------------------------
# meter (M1-M4)
# ---------------------------------------------------------------------------
class TestTiedCostStates:
    @pytest.mark.parametrize("flags", [(False, True), (True, False), (False, False), (True, True)])
    def test_tie_is_comparable_only_when_every_tied_record_is_false(self, tmp_path: Path, flags) -> None:
        root = tiny_root(tmp_path, 1_000_000)
        path = root / "-zq-tiny" / "sess-zt1.jsonl"
        recs = [json.dumps({"type": "cost-state", "totalCostUSD": 5.0, "hasUnknownModelCost": f}) for f in flags]
        path.write_text(path.read_text() + "\n".join(recs) + "\n")
        rc = build(root)["recorded_cost"]
        comparable = flags == (False, False)
        assert rc["sessions_comparable"] == int(comparable)
        assert rc["flagged_unknown_sessions"] == int(not comparable)


class TestMeterFigures:
    @pytest.mark.parametrize(
        "ledger_usd, meter, flag",
        [
            (11.0, 10.01, False),   # ledger above, just below 10 percent
            (11.0, 10.0, False),    # ledger above, exactly 10 percent
            (11.0, 9.99, True),     # ledger above, just above
            (9.0, 9.99, False),     # ledger below, just below
            (9.0, 10.0, False),     # ledger below, exactly 10 percent
            (9.0, 10.01, True),     # ledger below, just above
        ],
    )
    def test_threshold_is_strictly_above_ten_percent(self, ledger_usd, meter, flag) -> None:
        got = cost_ledger.meter_check(ledger_usd, meter)
        assert got["gap_flag"] is flag
        assert got["difference_usd"] == round(ledger_usd - meter, 6)
        assert got["gap_percent"] == pytest.approx(abs(ledger_usd - meter) / meter * 100, abs=1e-6)
        assert set(got) == {"meter_usd", "ledger_usd", "difference_usd", "gap_percent", "gap_flag"}

    @pytest.mark.parametrize(
        "ledger_usd, meter, flag",
        [
            (0.33, 0.3, False), (0.27, 0.3, False),
            (1.1, 1.0, False), (0.9, 1.0, False),
            (3.3, 3.0, False), (2.7, 3.0, False),
            (77.0, 70.0, False), (63.0, 70.0, False),
            (11.01, 10.0, True), (8.99, 10.0, True),
        ],
    )
    def test_decimal_ten_percent_does_not_flag(self, ledger_usd, meter, flag) -> None:
        # the gap printed is 10.0 for the first eight rows; the flag must agree with it
        got = cost_ledger.meter_check(ledger_usd, meter)
        assert got["gap_flag"] is flag
        assert (got["gap_percent"] > 10) is flag

    def test_exact_figures(self) -> None:
        got = cost_ledger.meter_check(12.1875, 12.5)
        assert got == {"meter_usd": 12.5, "ledger_usd": 12.1875, "difference_usd": -0.3125,
                       "gap_percent": 2.5, "gap_flag": False}


class TestMeterCli:
    def test_json_meter_is_null_without_the_flag(self, tmp_path: Path) -> None:
        out = tmp_path / "o.json"
        assert run_cli(*WINDOW, "--projects-root", str(ROOT), "--json", str(out)).returncode == 0
        assert json.loads(out.read_text())["meter"] is None

    def test_json_meter_block(self, tmp_path: Path) -> None:
        out = tmp_path / "o.json"
        proc = run_cli(*WINDOW, "--projects-root", str(ROOT), "--meter-usd", "12.5", "--json", str(out))
        assert proc.returncode == 0, proc.stderr
        assert json.loads(out.read_text())["meter"] == {
            "meter_usd": 12.5, "ledger_usd": 12.1875, "difference_usd": -0.3125,
            "gap_percent": 2.5, "gap_flag": False,
        }

    def test_no_meter_block_and_no_warning_without_the_flag(self) -> None:
        out = run_cli(*WINDOW, "--projects-root", str(ROOT)).stdout
        assert "METER" not in out and "Meter" not in out
        assert out.startswith("Cost ledger")

    def test_block_leads_the_report_when_within_ten_percent(self) -> None:
        out = run_cli(*WINDOW, "--projects-root", str(ROOT), "--meter-usd", "12.5").stdout
        lines = out.splitlines()
        assert lines[0].startswith("Meter check")
        assert "$12.19" in lines[1] and "$12.50" in lines[2]
        assert "-$0.31" in lines[3] and "2.5%" in lines[4]
        assert lines[5].startswith("Cost ledger")
        assert "METER GAP" not in out

    def test_gap_line_is_above_everything_including_the_block(self) -> None:
        out = run_cli(*WINDOW, "--projects-root", str(ROOT), "--meter-usd", "6.09375").stdout
        lines = out.splitlines()
        assert lines[0].startswith("METER GAP")
        assert lines[1].startswith("Meter check")
        assert "+$6.09" in out and "100.0%" in out
        assert sum(l.startswith("METER GAP") for l in lines) == 1

    @pytest.mark.parametrize(
        "tokens, meter, flagged",
        [(2_200_000, "10.01", False), (2_200_000, "10", False), (2_200_000, "9.99", True),
         (1_800_000, "9.99", False), (1_800_000, "10", False), (1_800_000, "10.01", True)],
    )
    def test_threshold_through_the_cli(self, tmp_path, tokens, meter, flagged) -> None:
        proc = run_cli(*WINDOW, "--projects-root", str(tiny_root(tmp_path, tokens)), "--meter-usd", meter)
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.startswith("METER GAP") is flagged
        assert ("METER GAP" in proc.stdout) is flagged

    @pytest.mark.parametrize(
        "tokens, meter, flagged",
        [(66_000, "0.3", False), (54_000, "0.3", False),
         (220_000, "1", False), (180_000, "1", False),
         (660_000, "3", False), (540_000, "3", False),
         (15_400_000, "70", False), (12_600_000, "70", False),
         (2_202_000, "10", True), (1_798_000, "10", True)],
    )
    def test_decimal_threshold_through_the_cli(self, tmp_path, tokens, meter, flagged) -> None:
        proc = run_cli(*WINDOW, "--projects-root", str(tiny_root(tmp_path, tokens)), "--meter-usd", meter)
        assert proc.returncode == 0, proc.stderr
        assert ("METER GAP" in proc.stdout) is flagged

    @pytest.mark.parametrize("bad", ["0", "-1", "-0.5", "abc", "", "nan", "inf", "-inf", "1e999"])
    def test_invalid_meter_exits_2_with_one_line_and_writes_nothing(self, tmp_path, bad) -> None:
        out, agg = tmp_path / "o.json", tmp_path / "a.json"
        proc = run_cli(*WINDOW, "--projects-root", str(ROOT), f"--meter-usd={bad}",
                       "--json", str(out), "--export-aggregates", str(agg))
        assert proc.returncode == 2
        assert len(proc.stderr.strip().splitlines()) == 1 and "meter" in proc.stderr
        assert proc.stdout == "" and not out.exists() and not agg.exists()


# ---------------------------------------------------------------------------
# aggregates-only export (E1-E5)
# ---------------------------------------------------------------------------
def export_text(tmp_path: Path, *extra: str) -> str:
    agg = tmp_path / "agg.json"
    proc = run_cli(*WINDOW, "--projects-root", str(ROOT), "--export-aggregates", str(agg), *extra)
    assert proc.returncode == 0, proc.stderr
    return agg.read_text()


class TestExport:
    def test_file_format_and_determinism(self, tmp_path: Path) -> None:
        a = export_text(tmp_path)
        obj = json.loads(a)
        assert a == json.dumps(obj, sort_keys=True, indent=2) + "\n"
        (tmp_path / "again").mkdir()
        assert export_text(tmp_path / "again") == a

    def test_exact_top_level_keys(self, tmp_path: Path) -> None:
        obj = json.loads(export_text(tmp_path))
        assert set(obj) == {
            "aggregates_version", "window", "totals", "subagent_by_agent_type", "by_model",
            "skills", "unattributed", "session_count", "session_usd_distribution", "coverage",
            "unpriced", "meter", "recorded_cost",
        }
        assert obj["aggregates_version"] == 1 and isinstance(obj["aggregates_version"], int)
        assert obj["window"] == {"since": "2026-11-10", "until": "2026-11-12"}
        assert set(obj["totals"]) == {"calls", "unpriced_calls", "usd", "tokens", "usd_breakdown",
                                      "main_usd", "subagent_usd"}
        assert obj["meter"] is None

    def test_content_matches_the_oracle(self, tmp_path: Path) -> None:
        obj = json.loads(export_text(tmp_path, "--meter-usd", "12.5"))
        assert obj["totals"] == WANT["totals"]
        assert obj["session_count"] == WANT["session_count"] == 9
        assert obj["session_usd_distribution"] == WANT["session_usd_distribution"]
        assert obj["by_model"] == WANT["by_model"]
        assert obj["subagent_by_agent_type"] == WANT["subagent_by_agent_type"]
        assert obj["skills"] == WANT["skills"]
        assert obj["unattributed"] == WANT["unattributed"]
        assert obj["coverage"] == WANT["coverage"]
        assert obj["recorded_cost"] == {k: v for k, v in WANT["recorded_cost"].items() if not k.startswith("_")}
        assert obj["meter"]["meter_usd"] == 12.5 and obj["meter"]["gap_flag"] is False
        (unpriced,) = obj["unpriced"]
        want = WANT["unpriced"][0]
        assert {k: unpriced[k] for k in want} == want
        assert set(unpriced) == {"model", "reason", "calls", "tokens"}

    def test_totals_equal_the_full_ledger(self, tmp_path: Path) -> None:
        ledger = build()
        obj = json.loads(export_text(tmp_path))
        assert obj["totals"] == ledger["totals"]
        assert obj["session_count"] == len(ledger["sessions"])

    def test_session_sums_match_the_oracle_rows(self) -> None:
        got = {f"{s['project']}/{s['session_id']}": s["usd"] for s in build()["sessions"]}
        assert got == WANT["session_usd"]

    def test_distribution_is_linear_interpolation_and_null_when_empty(self) -> None:
        assert cost_ledger.distribution([1.0, 2.0, 3.0, 4.0]) == {
            "min": 1.0, "p25": 1.75, "median": 2.5, "p75": 3.25, "max": 4.0}
        assert cost_ledger.distribution([5.0]) == {k: 5.0 for k in ("min", "p25", "median", "p75", "max")}
        assert cost_ledger.distribution([4.0, 1.0, 3.0, 2.0]) == {
            "min": 1.0, "p25": 1.75, "median": 2.5, "p75": 3.25, "max": 4.0}
        assert cost_ledger.distribution([]) == {k: None for k in ("min", "p25", "median", "p75", "max")}

    def test_distribution_median_is_not_the_mean(self) -> None:
        assert cost_ledger.distribution([1.0, 2.0, 9.0])["median"] == 2.0

    def test_agent_type_table_covers_subagent_rows_only(self) -> None:
        ledger = build()
        table = cost_ledger.build_aggregates(ledger)["subagent_by_agent_type"]
        sub_calls = sum(a["calls"] for s in ledger["sessions"] for a in s["agents"] if a["agent_id"] != "main")
        assert sum(v["calls"] for v in table.values()) == sub_calls
        assert sum(v["usd"] for v in table.values()) == pytest.approx(ledger["totals"]["subagent_usd"], abs=1e-6)
        assert "main" not in table

    def test_export_carries_the_meter_block(self) -> None:
        ledger = cost_ledger.apply_meter(build(), 6.09375)
        got = cost_ledger.build_aggregates(ledger)["meter"]
        assert got is not None and got["meter_usd"] == 6.09375 and got["gap_flag"] is True

    def test_empty_window_exports_nulls(self, tmp_path: Path) -> None:
        agg = tmp_path / "a.json"
        proc = run_cli("--since", "2030-01-01", "--until", "2030-01-02",
                       "--projects-root", str(ROOT), "--export-aggregates", str(agg))
        assert proc.returncode == 0
        obj = json.loads(agg.read_text())
        assert obj["session_count"] == 0 and obj["skills"] == [] and obj["by_model"] == {}
        assert set(obj["session_usd_distribution"].values()) == {None}

    def test_unwritable_path_exits_2_with_one_line(self, tmp_path: Path) -> None:
        bad = tmp_path / "missing-dir" / "a.json"
        proc = run_cli(*WINDOW, "--projects-root", str(ROOT), "--export-aggregates", str(bad))
        assert proc.returncode == 2
        assert len(proc.stderr.strip().splitlines()) == 1

    @pytest.mark.parametrize("bad_first", [True, False])
    def test_either_destination_unwritable_writes_neither(self, tmp_path: Path, bad_first: bool) -> None:
        good = tmp_path / "good.json"
        good.write_text("keep me")
        bad = tmp_path / "missing-dir" / "bad.json"
        j, a = (bad, good) if bad_first else (good, bad)
        proc = run_cli(*WINDOW, "--projects-root", str(ROOT), "--json", str(j), "--export-aggregates", str(a))
        assert proc.returncode == 2
        assert len(proc.stderr.strip().splitlines()) == 1 and proc.stdout == ""
        assert good.read_text() == "keep me" and not bad.exists()
        assert sorted(p.name for p in tmp_path.iterdir()) == ["good.json"]

    @pytest.mark.parametrize("bad_first", [True, False])
    def test_directory_destination_writes_neither(self, tmp_path: Path, bad_first: bool) -> None:
        good = tmp_path / "good.json"
        bad = tmp_path / "adir"
        bad.mkdir()
        j, a = (bad, good) if bad_first else (good, bad)
        proc = run_cli(*WINDOW, "--projects-root", str(ROOT), "--json", str(j), "--export-aggregates", str(a))
        assert proc.returncode == 2
        assert len(proc.stderr.strip().splitlines()) == 1
        assert not good.exists()

    def test_rounded_to_six_places(self, tmp_path: Path) -> None:
        # 1 token of input at 5 per million is 0.000005; 3 tokens at 5/M = 0.000015: six places.
        root = tiny_root(tmp_path, 3)
        agg = tmp_path / "a.json"
        assert run_cli(*WINDOW, "--projects-root", str(root), "--export-aggregates", str(agg)).returncode == 0
        obj = json.loads(agg.read_text())
        assert obj["totals"]["usd"] == 0.000015
        assert obj["session_usd_distribution"]["median"] == 0.000015


def _strings(node: object) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [s for v in node.values() for s in _strings(v)]
    if isinstance(node, list):
        return [s for v in node for s in _strings(v)]
    return []


class TestRedaction:
    def identifying_strings(self) -> set[str]:
        found: set[str] = set(part for part in ROOT.parts if part != ROOT.anchor)
        for proj in ROOT.iterdir():
            found.add(proj.name)
        for path in ROOT.rglob("*.jsonl"):
            found.add(path.stem)
            found.add(path.name)
            found.add(str(path))
            if path.parent.name == "subagents":
                found.add(path.parent.parent.name)
                found.add(path.stem.removeprefix("agent-"))
            for line in path.read_text().splitlines():
                rec = json.loads(line)
                if rec.get("type") == "cost-state":
                    continue
                for key in ("uuid", "requestId", "timestamp"):
                    if isinstance(rec.get(key), str):
                        found.add(rec[key])
                msg = rec.get("message", {})
                if isinstance(msg.get("id"), str):
                    found.add(msg["id"])
                found.update(s for s in _strings(msg.get("content")) if s.startswith(("zq-", "placeholder")))
                if isinstance(msg.get("content"), str):
                    found.add(msg["content"])
        return found

    def test_the_fixture_ids_are_distinctive(self) -> None:
        allowed = {"claude-opus-4-8", "claude-zq-unpriced-model", "zq-skill-a", "zq-skill-b", "zq-agent-reviewer"}
        for needle in self.identifying_strings():
            assert not any(needle in name for name in allowed), needle
        assert len(self.identifying_strings()) > 40

    def test_no_identifying_string_occurs_in_the_export(self, tmp_path: Path) -> None:
        text = export_text(tmp_path, "--meter-usd", "6.09375")
        needles = self.identifying_strings()
        assert any(n.startswith("zq-prompt-text") for n in needles)
        assert any(n == "-zq-ember" for n in needles) and any(n == "sess-zx2" for n in needles)
        assert any(n == "azx2" for n in needles) and any(n.endswith("T01:00:00Z") for n in needles)
        leaked = sorted(n for n in needles if n and n in text)
        assert not leaked, leaked

    def test_names_that_are_allowed_do_appear_as_written(self, tmp_path: Path) -> None:
        text = export_text(tmp_path)
        for name in ("zq-skill-a", "zq-skill-b", "zq-agent-reviewer", "claude-opus-4-8"):
            assert name in text

    def test_export_has_no_session_or_agent_rows(self, tmp_path: Path) -> None:
        obj = json.loads(export_text(tmp_path))
        assert "sessions" not in obj and "agents" not in obj and "project" not in json.dumps(obj)

