"""Tests for the cost ledger's fixed-weight estimator (slice 7, #1334).

The oracle is ``fixtures/cost_ledger_fixed/EXPECTED.json``, derived by hand from the
spec and the price table before the code. Cases the main fixture does not cover are
built in ``tmp_path`` with ``CHARS_PER_TOKEN`` set to 1.0, so a size in characters is
a size in tokens and every figure is exact.
"""

from __future__ import annotations

import atexit
import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

ENGINE = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(ENGINE))

import cost_ledger
import fixed_weight

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures" / "cost_ledger_fixed"
ROOT = FIXTURE / "projects"
WANT = json.loads((FIXTURE / "EXPECTED.json").read_text())
TODAY = date(2026, 11, 14)
WINDOW = ("--since", "2026-11-10", "--until", "2026-11-12")
MODEL = "claude-opus-4-8"  # input 5, output 25, write 6.25 (5m) and 10 (1h), read 0.5


def build(root: Path = ROOT, since: str = "2026-11-10", until: str = "2026-11-12", **kw) -> dict:
    return cost_ledger.build_ledger(root, since=since, until=until, today=TODAY, **kw)


# Subprocess runs get an empty home, so no test reads or writes the real ~/.workshop.
SCRATCH_HOME = tempfile.mkdtemp(prefix="cost-ledger-home-")
atexit.register(shutil.rmtree, SCRATCH_HOME, ignore_errors=True)


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ENGINE / "cost_ledger.py"), *args], capture_output=True, text=True,
        env={**os.environ, "HOME": SCRATCH_HOME},
    )


def run_default(home: Path, *args: str, chars_per_token: float | None = None) -> SimpleNamespace:
    """Run ``cost_ledger.main`` in-process with ``HOME`` pointed at ``home`` (the default calibration path)."""
    out, err = io.StringIO(), io.StringIO()
    ratio = fixed_weight.CHARS_PER_TOKEN if chars_per_token is None else chars_per_token
    with mock.patch.dict(os.environ, {"HOME": str(home)}), \
            mock.patch.object(fixed_weight, "CHARS_PER_TOKEN", ratio), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = cost_ledger.main(list(args))
    return SimpleNamespace(returncode=rc, stdout=out.getvalue(), stderr=err.getvalue())


def components(fw: dict) -> dict[str, dict]:
    return {c["component"]: c for c in fw["components"]}


# ---------------------------------------------------------------------------
# builders for tmp scenarios (one character is one token)
# ---------------------------------------------------------------------------
def att(subtype: str, size: int | None = None, **extra: object) -> dict:
    rec: dict = {"type": "attachment", "attachment": {"type": subtype, **extra},
                 "timestamp": "2026-11-10T00:00:00Z"}
    if size is not None:
        rec["rendered"] = [{"content": "x" * size}]
    return rec


def call(n: int, ts: str = "2026-11-11T01:00:00Z", model: str = MODEL, out: int = 0,
         inp: int = 0, cr: int = 0, w5: int = 0, w1: int = 0) -> dict:
    return {
        "type": "assistant", "uuid": f"zf-u{n}", "requestId": f"zf-r{n}",
        "message": {"id": f"zf-m{n}", "model": model, "usage": {
            "input_tokens": inp, "output_tokens": out, "cache_read_input_tokens": cr,
            "cache_creation_input_tokens": w5 + w1,
            "cache_creation": {"ephemeral_5m_input_tokens": w5, "ephemeral_1h_input_tokens": w1}}},
        "timestamp": ts,
    }


def session(tmp_path: Path, records: list[dict], name: str = "sess-zf1",
            subagent: list[dict] | None = None) -> Path:
    root = tmp_path / "projects"
    path = root / "-zf-proj" / f"{name}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    if subagent is not None:
        sub = root / "-zf-proj" / name / "subagents" / "agent-zfa1.jsonl"
        sub.parent.mkdir(parents=True, exist_ok=True)
        sub.write_text("".join(json.dumps(r) + "\n" for r in subagent))
    return root


@pytest.fixture(autouse=True)
def one_char_per_token(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    if request.cls is None or request.cls.__name__ != "TestOracle":
        monkeypatch.setattr(fixed_weight, "CHARS_PER_TOKEN", 1.0)


def fw_of(root: Path, **kw) -> dict:
    ledger = build(root, fixed_weight=True, **kw)
    assert ledger["fixed_weight"] is not None
    return ledger["fixed_weight"]


# ---------------------------------------------------------------------------
# the main fixture against the hand oracle
# ---------------------------------------------------------------------------
class TestOracle:
    ledger = build(fixed_weight=True)
    fw = ledger["fixed_weight"]
    want = WANT["fixed_weight"]

    def test_window_totals_are_the_inputs_of_the_oracle(self) -> None:
        assert self.ledger["totals"]["usd"] == WANT["totals_usd"]
        assert self.ledger["totals"]["main_usd"] == WANT["main_usd"]
        assert self.ledger["totals"]["subagent_usd"] == WANT["subagent_usd"]

    def test_scalars(self) -> None:
        for key in ("calibrated", "calibration_factor", "chars_per_token", "files_estimated",
                    "files_without_snapshot", "write_calls", "read_calls", "capped_calls",
                    "unpriced_calls", "total_usd", "share_of_total", "subagent_usd",
                    "subagent_share"):
            assert self.fw[key] == self.want[key], key

    def test_groups_and_mcp(self) -> None:
        assert self.fw["groups"] == self.want["groups"]
        assert self.fw["mcp"] == self.want["mcp"]

    def test_components_in_fixed_order_with_exact_dollars(self) -> None:
        got = self.fw["components"]
        assert [c["component"] for c in got] == [c["component"] for c in self.want["components"]]
        for g, w in zip(got, self.want["components"]):
            for key in ("component", "group", "files", "usd", "write_usd", "read_usd"):
                assert g[key] == w[key], (g["component"], key)
            for stat in ("min", "median", "max"):
                assert g["tokens_per_file"][stat] == pytest.approx(w["tokens_per_file"][stat]), (
                    g["component"], stat)

    def test_component_and_group_dollars_sum_to_total(self) -> None:
        total = self.fw["total_usd"]
        assert sum(c["usd"] for c in self.fw["components"]) == pytest.approx(total, abs=1e-9)
        assert sum(g["usd"] for g in self.fw["groups"].values()) == pytest.approx(total, abs=1e-9)
        for c in self.fw["components"]:
            assert c["write_usd"] + c["read_usd"] == pytest.approx(c["usd"], abs=1e-9)

    def test_never_above_the_window_total(self) -> None:
        assert self.fw["total_usd"] <= self.ledger["totals"]["usd"]

    def test_attachment_after_first_call_is_ignored(self) -> None:
        # a 3700 character skill listing follows the first call; skill_listing stays 200 tokens
        assert components(self.fw)["skill_listing"]["tokens_per_file"]["max"] == pytest.approx(200)

    def test_a_record_without_rendered_or_with_a_malformed_one_adds_nothing(self) -> None:
        # todo_reminder (no rendered) and queued_command (rendered not a list) are 0
        assert components(self.fw)["other"]["tokens_per_file"]["max"] == pytest.approx(20)

    def test_mcp_and_builtin_tools_are_split(self) -> None:
        c = components(self.fw)
        assert c["mcp_tool_schemas"]["tokens_per_file"]["max"] == pytest.approx(160)
        assert c["builtin_tool_schemas"]["tokens_per_file"]["max"] == pytest.approx(200)

    def test_deferred_tools_delta_splits_by_name_share(self) -> None:
        c = components(self.fw)
        assert c["mcp_tool_listing"]["tokens_per_file"]["max"] == pytest.approx(60)
        assert c["builtin_tool_listing"]["tokens_per_file"]["max"] == pytest.approx(60)

    def test_subagent_is_estimated_on_its_own(self) -> None:
        # instructions: parent 100 tokens, subagent 200 tokens, two files
        instr = components(self.fw)["instructions"]
        assert instr["files"] == 2
        assert instr["tokens_per_file"]["min"] == pytest.approx(100)
        assert instr["tokens_per_file"]["max"] == pytest.approx(200)
        assert self.fw["subagent_usd"] == 0.0054

    def test_out_of_window_call_is_not_charged(self) -> None:
        # the 11-20 call writes 5000 tokens; if it were charged write_calls would be 4
        assert self.fw["write_calls"] == 3
        wide = build(since="2026-11-10", until="2026-11-30", fixed_weight=True)["fixed_weight"]
        assert wide["write_calls"] == 4

    def test_unpriced_call_is_counted_not_charged(self) -> None:
        assert self.fw["unpriced_calls"] == 1

    def test_first_call_that_only_reads_is_charged_a_read(self) -> None:
        # beta's first call: skill_listing 80 tokens x 0.5 per million = 0.00004 read
        assert components(self.fw)["skill_listing"]["read_usd"] == 0.000372

    def test_call_that_triggers_the_cap(self) -> None:
        assert self.fw["capped_calls"] == 1

    def test_file_without_snapshot_still_estimates_attachments(self) -> None:
        assert self.fw["files_without_snapshot"] == 1
        assert components(self.fw)["skill_listing"]["files"] == 2

    def test_unpriced_ledger_tally_is_not_doubled(self) -> None:
        unpriced = self.ledger["unpriced"]
        assert [(u["model"], u["calls"]) for u in unpriced] == [("claude-zzz-9", 1)]


# ---------------------------------------------------------------------------
# the rule per call (F6, F7)
# ---------------------------------------------------------------------------
class TestCostingRule:
    def test_cache_write_at_least_t_is_charged_a_write_at_the_boundary(self, tmp_path: Path) -> None:
        root = session(tmp_path, [att("instructions", 1000), call(1, w5=1000), call(2, w5=999, ts="2026-11-11T02:00:00Z")])
        fw = fw_of(root)
        # call 1 writes exactly T: 1000 x 6.25 / 1e6; call 2 writes 999 < T: 1000 x 0.5 / 1e6
        assert fw["write_calls"] == 1 and fw["read_calls"] == 1
        c = components(fw)["instructions"]
        assert c["write_usd"] == 0.00625 and c["read_usd"] == 0.0005

    def test_a_rebuild_is_a_write_and_the_same_file_without_it_is_a_read(self, tmp_path: Path) -> None:
        with_rebuild = session(tmp_path / "a", [att("instructions", 1000), call(1, cr=5000),
                                                call(2, ts="2026-11-11T02:00:00Z", w5=3000)])
        without = session(tmp_path / "b", [att("instructions", 1000), call(1, cr=5000),
                                           call(2, ts="2026-11-11T02:00:00Z", cr=3000)])
        a, b = fw_of(with_rebuild), fw_of(without)
        assert (a["write_calls"], a["read_calls"]) == (1, 1)
        assert (b["write_calls"], b["read_calls"]) == (0, 2)
        assert a["total_usd"] == 0.00675 and b["total_usd"] == 0.001

    def test_one_hour_write_uses_the_one_hour_rate(self, tmp_path: Path) -> None:
        root = session(tmp_path, [att("instructions", 1000), call(1, w1=1000)])
        c = components(fw_of(root))["instructions"]
        assert c["write_usd"] == 0.01  # 1000 x 10 / 1e6, not 6.25

    def test_split_where_only_the_total_reaches_t_uses_the_five_minute_rate(self, tmp_path: Path) -> None:
        root = session(tmp_path, [att("instructions", 1000), call(1, w5=500, w1=600)])
        fw = fw_of(root)
        assert fw["write_calls"] == 1
        assert components(fw)["instructions"]["write_usd"] == 0.00625

    def test_rates_follow_the_calls_own_model(self, tmp_path: Path) -> None:
        # claude-sonnet-4-6 reads at 0.3 per million
        root = session(tmp_path, [att("instructions", 1000), call(1, model="claude-sonnet-4-6", cr=5000)])
        assert components(fw_of(root))["instructions"]["read_usd"] == 0.0003

    def test_each_call_in_a_mixed_model_file_is_priced_at_its_own_models_rate(self, tmp_path: Path) -> None:
        # one file, T = 1000: an opus-4-8 read (0.5 per million) then a sonnet-4-6 read (0.3)
        root = session(tmp_path, [
            att("instructions", 1000),
            call(1, cr=5000),
            call(2, ts="2026-11-11T02:00:00Z", model="claude-sonnet-4-6", cr=5000),
        ])
        fw = fw_of(root)
        c = components(fw)["instructions"]
        assert fw["read_calls"] == 2
        assert c["read_usd"] == 0.0008  # 1000 x 0.5 / 1e6 + 1000 x 0.3 / 1e6, not 2 x 0.0005
        assert c["usd"] == 0.0008

    def test_fast_multiplier_applies_through_the_applied_rates(self, tmp_path: Path) -> None:
        rec = call(1, cr=5000)
        rec["message"]["usage"]["speed"] = "fast"
        root = session(tmp_path, [att("instructions", 1000), rec])
        assert components(fw_of(root))["instructions"]["read_usd"] == 0.001  # 0.5 x 2

    def test_cap_scales_every_component_by_the_same_ratio(self, tmp_path: Path) -> None:
        # T = 1000 (instructions 600, skill_listing 400); the call's own dollars are 0.0002
        # (400 cache-read tokens), the fixed read charge 0.0005: ratio 0.4
        root = session(tmp_path, [att("instructions", 600), att("skill_listing", 400), call(1, cr=400)])
        fw = fw_of(root)
        assert fw["capped_calls"] == 1
        assert fw["total_usd"] == 0.0002
        c = components(fw)
        assert c["instructions"]["usd"] == 0.00012 and c["skill_listing"]["usd"] == 0.00008
        assert fw["share_of_total"] == 1.0

    def test_unpriced_call_is_charged_nothing_and_counted(self, tmp_path: Path) -> None:
        root = session(tmp_path, [att("instructions", 1000), call(1, model="claude-zzz-9", cr=5000)])
        fw = fw_of(root)
        assert fw["unpriced_calls"] == 1 and fw["total_usd"] == 0 and fw["files_estimated"] == 0

    def test_undated_call_is_not_charged(self, tmp_path: Path) -> None:
        rec = call(1, cr=5000)
        rec["timestamp"] = "not a time"
        root = session(tmp_path, [att("instructions", 1000), rec])
        assert fw_of(root)["total_usd"] == 0

    def test_zero_token_call_is_neither_charged_nor_counted(self, tmp_path: Path) -> None:
        root = session(tmp_path, [att("instructions", 1000), call(1)])
        fw = fw_of(root)
        assert fw["total_usd"] == 0 and fw["unpriced_calls"] == 0 and fw["read_calls"] == 0


# ---------------------------------------------------------------------------
# sizes (F2, F3, F5)
# ---------------------------------------------------------------------------
class TestSizes:
    def test_no_attachments_and_no_snapshot_is_exactly_zero(self, tmp_path: Path) -> None:
        root = session(tmp_path, [call(1, cr=5000), call(2, ts="2026-11-11T02:00:00Z", w5=3000)])
        fw = fw_of(root)
        assert fw["total_usd"] == 0 and fw["share_of_total"] == 0
        assert all(c["usd"] == 0 and c["files"] == 0 for c in fw["components"])
        assert fw["files_estimated"] == 0 and fw["files_without_snapshot"] == 1

    def test_large_attachments_give_a_large_share(self, tmp_path: Path) -> None:
        root = session(tmp_path, [att("skill_listing", 100_000), call(1, cr=200_000)])
        fw = fw_of(root)
        assert fw["total_usd"] == 0.05 and fw["share_of_total"] == 0.5

    def test_attachment_after_the_first_usable_call_is_ignored_but_one_after_unusable_counts(
        self, tmp_path: Path
    ) -> None:
        no_usage = {"type": "assistant", "uuid": "zf-x", "message": {"id": "zf-mx", "usage": {}},
                    "timestamp": "2026-11-10T00:00:00Z"}
        root = session(tmp_path, [att("instructions", 100), no_usage, att("skill_listing", 50),
                                  call(1, cr=5000), att("agent_listing_delta", 900)])
        c = components(fw_of(root))
        assert c["instructions"]["usd"] > 0 and c["skill_listing"]["usd"] > 0
        assert c["agent_listing"]["usd"] == 0

    def test_prompt_snapshot_sizes_come_from_the_first_snapshot_with_each(self, tmp_path: Path) -> None:
        def tool(name: str, schema: object) -> dict:
            return {"name": name, "schema": schema}

        s1 = att("prompt_snapshot", systemPrompt=["a" * 100, 7, "b" * 100])
        s2 = att("prompt_snapshot", systemPrompt="z" * 999, tools=[
            tool("Read", {"k": "v" * 91}),
            tool("mcp__zf__t", {"k": "w" * 47}),
            tool("Bad", None), {"name": 3, "schema": {"k": "q"}}, {"schema": {"k": "q"}},
        ])
        s3 = att("prompt_snapshot", tools=[tool("Read", {"k": "v" * 900})])
        root = session(tmp_path, [s1, call(1, cr=5000), s2, s3])
        c = components(fw_of(root))
        read_len = len(json.dumps({"k": "v" * 91}, separators=(",", ":")))
        mcp_len = len(json.dumps({"k": "w" * 47}, separators=(",", ":")))
        assert c["system_prompt"]["tokens_per_file"]["max"] == 200
        assert c["builtin_tool_schemas"]["tokens_per_file"]["max"] == read_len
        assert c["mcp_tool_schemas"]["tokens_per_file"]["max"] == mcp_len

    def test_tool_size_is_compact_json_without_ascii_escaping(self, tmp_path: Path) -> None:
        schema = {"k": "é" * 10}
        s = att("prompt_snapshot", tools=[{"name": "Read", "schema": schema}])
        root = session(tmp_path, [s, call(1, cr=5000)])
        want = len(json.dumps(schema, separators=(",", ":"), ensure_ascii=False))
        assert components(fw_of(root))["builtin_tool_schemas"]["tokens_per_file"]["max"] == want

    def test_deferred_tools_delta_with_no_usable_names_is_all_builtin(self, tmp_path: Path) -> None:
        root = session(tmp_path, [att("deferred_tools_delta", 100), call(1, cr=5000)])
        c = components(fw_of(root))
        assert c["builtin_tool_listing"]["tokens_per_file"]["max"] == 100
        assert c["mcp_tool_listing"]["files"] == 0

    def test_deferred_tools_delta_ignores_non_string_names(self, tmp_path: Path) -> None:
        root = session(tmp_path, [att("deferred_tools_delta", 100, addedNames=[7, "mcp__zf__a", "", None]),
                                  call(1, cr=5000)])
        c = components(fw_of(root))
        assert c["mcp_tool_listing"]["tokens_per_file"]["max"] == 100
        assert c["builtin_tool_listing"]["files"] == 0

    def test_rendered_sums_string_contents_only(self, tmp_path: Path) -> None:
        rec = att("instructions")
        rec["rendered"] = [{"content": "a" * 30}, {"content": 5}, {"nope": "b" * 99}, "c" * 77, {"content": "d" * 20}]
        root = session(tmp_path, [rec, call(1, cr=5000)])
        assert components(fw_of(root))["instructions"]["tokens_per_file"]["max"] == 50

    def test_unknown_subtype_is_other(self, tmp_path: Path) -> None:
        root = session(tmp_path, [att("brand_new_kind", 40), att(None, 10), call(1, cr=5000)])  # type: ignore[arg-type]
        assert components(fw_of(root))["other"]["tokens_per_file"]["max"] == 50

    def test_subagent_file_is_estimated_separately_from_its_parent(self, tmp_path: Path) -> None:
        root = session(
            tmp_path,
            [att("instructions", 1000), call(1, cr=5000)],
            subagent=[att("instructions", 300), call(2, cr=5000)],
        )
        fw = fw_of(root)
        assert fw["files_estimated"] == 2
        instr = components(fw)["instructions"]
        assert instr["tokens_per_file"] == {"min": 300, "median": 650, "max": 1000}
        assert fw["subagent_usd"] == 0.00015 and fw["subagent_share"] == pytest.approx(0.230769, abs=1e-6)

    def test_snapshot_in_a_file_with_no_calls_in_window_charges_nothing(self, tmp_path: Path) -> None:
        root = session(tmp_path, [att("instructions", 1000), call(1, ts="2026-12-30T00:00:00Z", cr=5000)])
        fw = fw_of(root)
        assert fw["total_usd"] == 0 and fw["files_estimated"] == 0 and fw["files_without_snapshot"] == 0


# ---------------------------------------------------------------------------
# calibration (F8)
# ---------------------------------------------------------------------------
class TestCalibration:
    def test_factor_scales_tokens(self, tmp_path: Path) -> None:
        root = session(tmp_path, [att("instructions", 1000), call(1, cr=10_000)])
        base = fw_of(root)
        scaled = build(root, fixed_weight=True,
                       calibration=fixed_weight.Calibration(2.0, True))["fixed_weight"]
        assert base["calibrated"] is False and base["calibration_factor"] == 1.0
        assert scaled["calibrated"] is True and scaled["calibration_factor"] == 2.0
        assert components(base)["instructions"]["usd"] == 0.0005
        assert components(scaled)["instructions"]["usd"] == 0.001
        assert components(scaled)["instructions"]["tokens_per_file"]["max"] == 2000

    def test_load_without_a_file_is_uncalibrated(self, tmp_path: Path) -> None:
        got = fixed_weight.load_calibration(tmp_path / "absent.json")
        assert got == fixed_weight.Calibration(1.0, False)

    def test_load_reads_the_factor_and_ignores_other_keys(self, tmp_path: Path) -> None:
        path = tmp_path / "c.json"
        path.write_text(json.dumps({"factor": 1.25, "note": "x", "measured": "2026-11-14"}))
        assert fixed_weight.load_calibration(path) == fixed_weight.Calibration(1.25, True)

    @pytest.mark.parametrize(
        "text",
        ["", "not json", "[1.2]", "7", "{}", '{"factor": 0}', '{"factor": -1}', '{"factor": "1.2"}',
         '{"factor": null}', '{"factor": true}', '{"factor": NaN}', '{"factor": Infinity}'],
    )
    def test_load_refuses_a_bad_file(self, tmp_path: Path, text: str) -> None:
        path = tmp_path / "c.json"
        path.write_text(text)
        with pytest.raises(fixed_weight.CalibrationError):
            fixed_weight.load_calibration(path)

    def test_load_refuses_a_directory(self, tmp_path: Path) -> None:
        with pytest.raises(fixed_weight.CalibrationError):
            fixed_weight.load_calibration(tmp_path)

    def test_load_refuses_bytes_that_are_not_text(self, tmp_path: Path) -> None:
        path = tmp_path / "c.json"
        path.write_bytes(b"\xff\xfe\x00\x00")
        with pytest.raises(fixed_weight.CalibrationError):
            fixed_weight.load_calibration(path)


# ---------------------------------------------------------------------------
# the flag and the output (F9, F10, F11)
# ---------------------------------------------------------------------------
class TestFlag:
    def test_without_the_flag_the_key_is_null_and_nothing_is_estimated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(*a: object, **k: object) -> None:
            raise AssertionError("estimation ran without --fixed-weight")

        monkeypatch.setattr(fixed_weight, "estimate", boom)
        monkeypatch.setattr(fixed_weight, "Collector", boom)
        ledger = build()
        assert ledger["fixed_weight"] is None

    def test_other_figures_are_identical_with_and_without_the_flag(self) -> None:
        a, b = build(), build(fixed_weight=True)
        b["fixed_weight"] = None
        assert a == b

    def test_cli_without_the_flag_has_null_and_no_section(self, tmp_path: Path) -> None:
        out = tmp_path / "o.json"
        proc = run_cli(*WINDOW, "--projects-root", str(ROOT), "--json", str(out))
        assert proc.returncode == 0, proc.stderr
        assert json.loads(out.read_text())["fixed_weight"] is None
        assert "FIXED WEIGHT" not in proc.stdout and "UNCALIBRATED" not in proc.stdout

    def test_cli_calibration_without_the_flag_is_ignored(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("not json")
        proc = run_cli(*WINDOW, "--projects-root", str(ROOT), "--calibration", str(bad))
        assert proc.returncode == 0 and "FIXED WEIGHT" not in proc.stdout

    def test_empty_window_prints_the_section_with_null_shares_and_divides_by_nothing(self, tmp_path: Path) -> None:
        out = tmp_path / "o.json"
        proc = run_cli("--since", "2030-01-01", "--until", "2030-01-02", "--projects-root", str(ROOT),
                       "--fixed-weight", "--json", str(out))
        assert proc.returncode == 0, proc.stderr
        fw = json.loads(out.read_text())["fixed_weight"]
        assert fw["total_usd"] == 0 and fw["share_of_total"] is None and fw["subagent_share"] is None
        assert fw["groups"]["setup"]["share_of_total"] is None and fw["mcp"]["share_of_total"] is None
        assert all(c["tokens_per_file"] == {"min": None, "median": None, "max": None} for c in fw["components"])
        assert "FIXED WEIGHT" in proc.stdout and "n/a" in proc.stdout

    def test_json_is_deterministic_and_matches_the_library(self, tmp_path: Path) -> None:
        a, b = tmp_path / "a.json", tmp_path / "b.json"
        for out in (a, b):
            proc = run_cli(*WINDOW, "--projects-root", str(ROOT), "--fixed-weight", "--json", str(out))
            assert proc.returncode == 0, proc.stderr
        assert a.read_bytes() == b.read_bytes()
        obj = json.loads(a.read_text())
        assert obj["schema_version"] == 7
        assert obj["fixed_weight"]["total_usd"] == WANT["fixed_weight"]["total_usd"]
        assert a.read_text() == cost_ledger.dumps(obj)

    def test_aggregates_export_carries_fixed_weight_unchanged(self, tmp_path: Path) -> None:
        full, agg = tmp_path / "f.json", tmp_path / "a.json"
        proc = run_cli(*WINDOW, "--projects-root", str(ROOT), "--fixed-weight",
                       "--json", str(full), "--export-aggregates", str(agg))
        assert proc.returncode == 0, proc.stderr
        assert json.loads(agg.read_text())["fixed_weight"] == json.loads(full.read_text())["fixed_weight"]

    def test_aggregates_export_has_null_without_the_flag(self, tmp_path: Path) -> None:
        agg = tmp_path / "a.json"
        proc = run_cli(*WINDOW, "--projects-root", str(ROOT), "--export-aggregates", str(agg))
        assert proc.returncode == 0, proc.stderr
        assert json.loads(agg.read_text())["fixed_weight"] is None

    def test_export_holds_no_identifier(self, tmp_path: Path) -> None:
        agg = tmp_path / "a.json"
        run_cli(*WINDOW, "--projects-root", str(ROOT), "--fixed-weight", "--export-aggregates", str(agg))
        text = agg.read_text()
        for needle in ("fx-alpha", "fa1", "fb1", "agent-", "mcp__fx", "/Users"):
            assert needle not in text


class TestReport:
    def report(self, *extra: str) -> list[str]:
        proc = run_cli(*WINDOW, "--projects-root", str(ROOT), "--fixed-weight", *extra)
        assert proc.returncode == 0, proc.stderr
        return proc.stdout.splitlines()

    def report_default(self, home: Path) -> list[str]:
        """The report with no --calibration flag and no file under ``home`` (the default path)."""
        proc = run_default(home, *WINDOW, "--projects-root", str(ROOT), "--fixed-weight",
                           chars_per_token=3.7)
        assert proc.returncode == 0, proc.stderr
        return proc.stdout.splitlines()

    def test_header_and_uncalibrated_line_without_a_file(self, tmp_path: Path) -> None:
        lines = self.report_default(tmp_path)
        i = lines.index("FIXED WEIGHT")
        assert lines[i + 1] == "UNCALIBRATED ESTIMATE"

    def test_no_uncalibrated_line_with_a_file(self, tmp_path: Path) -> None:
        cal = tmp_path / "c.json"
        cal.write_text('{"factor": 0.5}')
        lines = self.report("--calibration", str(cal))
        assert "FIXED WEIGHT" in lines
        assert "UNCALIBRATED ESTIMATE" not in lines
        assert not any("UNCALIBRATED" in line for line in lines)

    def test_calibration_file_scales_the_cli_result(self, tmp_path: Path) -> None:
        cal = tmp_path / "c.json"
        cal.write_text('{"factor": 0.5}')
        out = tmp_path / "o.json"
        proc = run_cli(*WINDOW, "--projects-root", str(ROOT), "--fixed-weight",
                       "--calibration", str(cal), "--json", str(out))
        assert proc.returncode == 0, proc.stderr
        fw = json.loads(out.read_text())["fixed_weight"]
        assert fw["calibrated"] is True and fw["calibration_factor"] == 0.5
        assert components(fw)["system_prompt"]["tokens_per_file"]["max"] == pytest.approx(500)

    def test_sections_come_in_the_specified_order(self, tmp_path: Path) -> None:
        text = "\n".join(self.report_default(tmp_path))
        order = [
            "FIXED WEIGHT", "UNCALIBRATED ESTIMATE", "upper bound", "MCP", "present regardless",
            "skill_listing", "Subagent share of fixed-weight dollars", "Fixed-weight coverage", "capped",
        ]
        positions = [text.index(marker, text.index("FIXED WEIGHT")) for marker in order]
        assert positions == sorted(positions)

    def test_figures_in_the_section(self, tmp_path: Path) -> None:
        text = "\n".join(self.report_default(tmp_path))
        assert "17.5% of window spend" in text          # setup 0.012782 of 0.073215
        assert "36.6% of window spend" in text          # claude_code
        assert "5.8% of window spend" in text           # mcp
        assert "13.6%" in text                          # subagent share
        assert "3 files estimated" in text and "1 without a snapshot" in text
        assert "3 write calls" in text and "6 read calls" in text
        assert "capped on 1 call" in text

    def test_component_table_is_dollars_descending_with_median_and_range(self, tmp_path: Path) -> None:
        lines = self.report_default(tmp_path)
        rows = [ln for ln in lines if ln.startswith("    ") and any(
            ln.split()[0] == c["component"] for c in WANT["fixed_weight"]["components"]
        )]
        names = [r.split()[0] for r in rows]
        assert len(names) == 11
        want = sorted(WANT["fixed_weight"]["components"], key=lambda c: -c["usd"])
        assert names[0] == want[0]["component"] == "system_prompt"
        assert names.index("builtin_tool_schemas") < names.index("skill_listing") < names.index("other")
        system = next(r for r in rows if r.split()[0] == "system_prompt")
        assert "750" in system and "500" in system and "1,000" in system

    def test_no_cap_line_when_nothing_was_capped(self, tmp_path: Path) -> None:
        root = session(tmp_path, [att("instructions", 1000), call(1, cr=100_000)])
        proc = run_default(tmp_path, *WINDOW, "--projects-root", str(root), "--fixed-weight")
        assert proc.returncode == 0, proc.stderr
        assert "capped" not in proc.stdout.lower()

    def test_no_recommendation_is_stated(self, tmp_path: Path) -> None:
        # Slice 9 added the verdict block, so the word "verdict" is now expected.
        text = "\n".join(self.report_default(tmp_path)).lower()
        for word in ("recommend", "should remove"):
            assert word not in text


class TestCliCalibrationRefusals:
    @pytest.mark.parametrize("text", ["", "{", "[]", "{}", '{"factor": 0}', '{"factor": "x"}'])
    def test_bad_file_exits_2_with_one_line_and_writes_nothing(self, tmp_path: Path, text: str) -> None:
        cal = tmp_path / "c.json"
        cal.write_text(text)
        out = tmp_path / "o.json"
        proc = run_cli(*WINDOW, "--projects-root", str(ROOT), "--fixed-weight",
                       "--calibration", str(cal), "--json", str(out))
        assert proc.returncode == 2
        assert proc.stdout == ""
        assert len(proc.stderr.strip().splitlines()) == 1 and "calibration" in proc.stderr
        assert not out.exists()

    def test_directory_as_calibration_exits_2(self, tmp_path: Path) -> None:
        proc = run_cli(*WINDOW, "--projects-root", str(ROOT), "--fixed-weight",
                       "--calibration", str(tmp_path))
        assert proc.returncode == 2 and len(proc.stderr.strip().splitlines()) == 1

    def test_default_path_is_under_home_and_read_at_call_time(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        assert cost_ledger.default_calibration_path() == (
            tmp_path / ".workshop" / "cost-ledger" / "cost_ledger_calibration.json"
        )
        other = tmp_path / "other"
        monkeypatch.setenv("HOME", str(other))
        assert cost_ledger.default_calibration_path().is_relative_to(other)

    def test_file_at_the_default_path_is_read_with_no_flag(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        target = cost_ledger.default_calibration_path()
        target.parent.mkdir(parents=True)
        target.write_text('{"factor": 3}')
        rc = cost_ledger.main([*WINDOW, "--projects-root", str(ROOT), "--fixed-weight"])
        out = capsys.readouterr().out
        assert rc == 0 and "FIXED WEIGHT" in out and "UNCALIBRATED" not in out

    def test_default_path_with_a_bad_file_exits_2(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        target = cost_ledger.default_calibration_path()
        target.parent.mkdir(parents=True)
        target.write_text("nope")
        rc = cost_ledger.main([*WINDOW, "--projects-root", str(ROOT), "--fixed-weight"])
        assert rc == 2 and len(capsys.readouterr().err.strip().splitlines()) == 1

    def test_files_beside_the_engine_and_a_budget_burn_config_are_ignored(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        import budget_burn

        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        cfg = tmp_path / "cfg"
        cfg.mkdir()
        (cfg / fixed_weight.CALIBRATION_FILE).write_text('{"factor": 3}')
        fake = SimpleNamespace(__file__=str(cfg / "_config.py"))
        monkeypatch.setattr(budget_burn, "_config", fake, raising=False)
        fake_engine = tmp_path / "engine"
        fake_engine.mkdir()
        (fake_engine / fixed_weight.CALIBRATION_FILE).write_text('{"factor": 3}')
        monkeypatch.setattr(cost_ledger, "__file__", str(fake_engine / "cost_ledger.py"))
        rc = cost_ledger.main([*WINDOW, "--projects-root", str(ROOT), "--fixed-weight"])
        assert rc == 0 and "UNCALIBRATED ESTIMATE" in capsys.readouterr().out

    def test_calibration_flag_wins_over_a_file_at_the_default_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        target = cost_ledger.default_calibration_path()
        target.parent.mkdir(parents=True)
        target.write_text('{"factor": 3}')
        other = tmp_path / "other.json"
        other.write_text('{"factor": 2}')
        out = tmp_path / "o.json"
        rc = cost_ledger.main([*WINDOW, "--projects-root", str(ROOT), "--fixed-weight",
                               "--calibration", str(other), "--json", str(out)])
        capsys.readouterr()
        fw = json.loads(out.read_text())["fixed_weight"]
        assert rc == 0 and fw["calibrated"] is True and fw["calibration_factor"] == 2.0

    def test_help_shows_the_literal_tilde_default(self) -> None:
        proc = run_cli("--help")
        assert proc.returncode == 0
        flat = "".join(proc.stdout.split())  # argparse may wrap at the hyphens
        assert "~/.workshop/cost-ledger/cost_ledger_calibration.json" in flat


# ---------------------------------------------------------------------------
# shares come from unrounded dollars (review: a share above 1 at sub-cent size)
# ---------------------------------------------------------------------------
def _all_shares(fw: dict) -> list[float]:
    shares = [fw["share_of_total"], fw["subagent_share"], fw["mcp"]["share_of_total"]]
    shares += [g["share_of_total"] for g in fw["groups"].values()]
    return [s for s in shares if s is not None]


class TestSharesFromUnroundedDollars:
    SUBCENT = [  # (input, output, cache read) tokens of four capped calls, 148.5 micro-dollars
        (0, 1, 2), (0, 3, 2), (2, 1, 1), (2, 0, 2),
    ]

    def _records(self, calls: list[tuple[int, int, int]], extra: list[dict] | None = None) -> list[dict]:
        recs = [att("instructions", 3700), *(extra or [])]
        for n, (i, o, r) in enumerate(calls, 1):
            recs.append(call(n, ts=f"2026-11-11T0{n}:00:00Z", inp=i, out=o, cr=r))
        return recs

    def test_share_of_total_never_exceeds_one_after_rounding(self, tmp_path: Path) -> None:
        root = session(tmp_path, self._records(self.SUBCENT))
        ledger = build(root, fixed_weight=True)
        fw = ledger["fixed_weight"]
        assert fw["capped_calls"] == 4
        # rounded: 0.000149 against totals.usd 0.000148 would be a share of 1.0034
        assert fw["total_usd"] <= ledger["totals"]["usd"]
        assert fw["share_of_total"] == 1.0
        assert fw["groups"]["setup"]["share_of_total"] == 1.0

    def test_a_window_that_rounds_up_still_gives_a_share_of_exactly_one(self, tmp_path: Path) -> None:
        # one capped sonnet-4-6 call of 9 cache-read tokens costs 2.7e-06, which rounds up to 3e-06;
        # the share is of the unrounded 2.7e-06 (a rounded denominator would give 0.9, a
        # rounded numerator 1.111)
        root = session(tmp_path, [att("instructions", 3700),
                                  call(1, model="claude-sonnet-4-6", cr=9)])
        ledger = build(root, fixed_weight=True)
        fw = ledger["fixed_weight"]
        assert ledger["totals"]["usd"] == 3e-06 and fw["total_usd"] == 3e-06
        assert fw["share_of_total"] == 1.0 and fw["groups"]["setup"]["share_of_total"] == 1.0
        assert all(s <= 1.0 for s in _all_shares(fw))

    SMALL = [
        [(0, 1, 2)],
        [(0, 1, 2), (0, 3, 2)],
        [(1, 1, 1), (0, 0, 3), (2, 0, 2)],
        [(0, 1, 1), (0, 1, 1), (0, 1, 1), (0, 1, 1), (0, 1, 1), (0, 1, 1), (0, 1, 1)],
        [(3, 3, 3), (1, 0, 0), (0, 0, 1)],
    ]

    @pytest.mark.parametrize("calls", SMALL)
    @pytest.mark.parametrize("size", [50, 3700, 9999])
    def test_no_share_exceeds_one_and_fixed_never_above_window(
        self, tmp_path: Path, calls: list[tuple[int, int, int]], size: int
    ) -> None:
        extra = [att("skill_listing", size), att("mcp_instructions_delta", size // 2)]
        root = session(tmp_path, self._records(calls, extra),
                       subagent=[att("instructions", size), call(9, inp=1, out=1, cr=1)])
        ledger = build(root, fixed_weight=True)
        fw = ledger["fixed_weight"]
        assert fw["total_usd"] <= ledger["totals"]["usd"]
        assert all(s <= 1.0 for s in _all_shares(fw)), fw

    def test_subagent_share_is_zero_when_no_dollars_are_in_subagent_files(self, tmp_path: Path) -> None:
        root = session(tmp_path, [att("instructions", 1000), call(1, cr=5000)])
        fw = fw_of(root)
        assert fw["total_usd"] > 0 and fw["subagent_usd"] == 0 and fw["subagent_share"] == 0.0


class TestTokensPerFileRounding:
    def test_min_median_and_max_are_rounded_to_three_places(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(fixed_weight, "CHARS_PER_TOKEN", 3.0)
        root = session(tmp_path, [att("instructions", 10), call(1, cr=5000)],
                       subagent=[att("instructions", 20), call(9, cr=5000)])
        ledger = build(root, fixed_weight=True)
        t = components(ledger["fixed_weight"])["instructions"]["tokens_per_file"]
        assert t == {"min": 3.333, "median": 5.0, "max": 6.667}
        exported = cost_ledger.build_aggregates(ledger)["fixed_weight"]
        assert components(exported)["instructions"]["tokens_per_file"] == t


# ---------------------------------------------------------------------------
# an explicit --calibration path that does not exist is a refusal
# ---------------------------------------------------------------------------
class TestCliMissingCalibration:
    def test_explicit_missing_path_exits_2_with_one_line_and_writes_nothing(self, tmp_path: Path) -> None:
        out = tmp_path / "o.json"
        missing = tmp_path / "nope.json"
        proc = run_cli(*WINDOW, "--projects-root", str(ROOT), "--fixed-weight",
                       "--calibration", str(missing), "--json", str(out))
        assert proc.returncode == 2
        assert proc.stdout == ""
        assert len(proc.stderr.strip().splitlines()) == 1 and "calibration" in proc.stderr
        assert str(missing) in proc.stderr
        assert not out.exists()

    def test_default_path_absent_is_factor_one_and_uncalibrated(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        rc = cost_ledger.main([*WINDOW, "--projects-root", str(ROOT), "--fixed-weight"])
        out = capsys.readouterr().out
        assert rc == 0 and "UNCALIBRATED ESTIMATE" in out


# ---------------------------------------------------------------------------
# slice 8 (#1335): calibration bounds, comparison runs, report lines
# ---------------------------------------------------------------------------
POINT_KEYS = {
    "calibration_factor", "total_usd", "share_of_total", "setup_usd",
    "setup_share_of_total", "mcp_usd", "mcp_share_of_total",
}


def cal_file(tmp_path: Path, body: dict, name: str = "c.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(body))
    return path


def cli_fw(tmp_path: Path, cal: Path, name: str = "o.json") -> dict:
    out = tmp_path / name
    proc = run_cli(*WINDOW, "--projects-root", str(ROOT), "--fixed-weight",
                   "--calibration", str(cal), "--json", str(out))
    assert proc.returncode == 0, proc.stderr
    return json.loads(out.read_text())["fixed_weight"]


def point_of(fw: dict) -> dict:
    return {
        "calibration_factor": fw["calibration_factor"],
        "total_usd": fw["total_usd"],
        "share_of_total": fw["share_of_total"],
        "setup_usd": fw["groups"]["setup"]["usd"],
        "setup_share_of_total": fw["groups"]["setup"]["share_of_total"],
        "mcp_usd": fw["mcp"]["usd"],
        "mcp_share_of_total": fw["mcp"]["share_of_total"],
    }


class TestCalibrationBounds:
    def test_bounds_and_provenance_are_loaded(self, tmp_path: Path) -> None:
        path = cal_file(tmp_path, {"factor": 1.5, "low": 1.0, "high": 2.0, "date": "2026-11-14",
                                   "claude_code_version": "9.9.9", "runs_per_arm": 5})
        assert fixed_weight.load_calibration(path) == fixed_weight.Calibration(
            1.5, True, 1.0, 2.0, "2026-11-14", "9.9.9", 5)

    def test_factor_only_stays_valid_with_no_range(self, tmp_path: Path) -> None:
        got = fixed_weight.load_calibration(cal_file(tmp_path, {"factor": 1.5}))
        assert (got.low, got.high, got.date, got.claude_code_version, got.runs_per_arm) == (
            None, None, None, None, None)

    def test_bounds_equal_to_the_factor_are_valid(self, tmp_path: Path) -> None:
        got = fixed_weight.load_calibration(cal_file(tmp_path, {"factor": 1.5, "low": 1.5, "high": 1.5}))
        assert (got.low, got.high) == (1.5, 1.5)

    @pytest.mark.parametrize(
        "body",
        [
            {"factor": 1.5, "low": 1.0},
            {"factor": 1.5, "high": 2.0},
            {"factor": 1.5, "low": 1.6, "high": 2.0},
            {"factor": 1.5, "low": 1.0, "high": 1.4},
            {"factor": 1.5, "low": 2.0, "high": 1.0},
            {"factor": 1.5, "low": 0, "high": 2.0},
            {"factor": 1.5, "low": -1.0, "high": 2.0},
            {"factor": 1.5, "low": 1.0, "high": 0},
            {"factor": 1.5, "low": "1.0", "high": 2.0},
            {"factor": 1.5, "low": None, "high": 2.0},
            {"factor": 1.5, "low": 1.0, "high": None},
            {"factor": 1.5, "low": True, "high": 2.0},
        ],
    )
    def test_invalid_bounds_are_refused(self, tmp_path: Path, body: dict) -> None:
        path = cal_file(tmp_path, body)
        with pytest.raises(fixed_weight.CalibrationError):
            fixed_weight.load_calibration(path)
        out = tmp_path / "o.json"
        proc = run_cli(*WINDOW, "--projects-root", str(ROOT), "--fixed-weight",
                       "--calibration", str(path), "--json", str(out))
        assert proc.returncode == 2 and not out.exists()
        assert len(proc.stderr.strip().splitlines()) == 1

    @pytest.mark.parametrize("text", ['{"factor": 1.5, "low": NaN, "high": 2}',
                                      '{"factor": 1.5, "low": 1, "high": Infinity}'])
    def test_non_finite_bounds_are_refused(self, tmp_path: Path, text: str) -> None:
        path = tmp_path / "c.json"
        path.write_text(text)
        with pytest.raises(fixed_weight.CalibrationError):
            fixed_weight.load_calibration(path)

    def test_provenance_of_the_wrong_type_reads_as_absent(self, tmp_path: Path) -> None:
        path = cal_file(tmp_path, {"factor": 1, "date": 20261114, "claude_code_version": 9,
                                   "runs_per_arm": "5"})
        got = fixed_weight.load_calibration(path)
        assert (got.date, got.claude_code_version, got.runs_per_arm) == (None, None, None)
        path = cal_file(tmp_path, {"factor": 1, "date": "someone's note", "claude_code_version": "a b/c",
                                   "runs_per_arm": True})
        got = fixed_weight.load_calibration(path)
        assert (got.date, got.claude_code_version, got.runs_per_arm) == (None, None, None)


class TestComparison:
    BODY = {"factor": 2.0, "low": 0.25, "high": 3.0, "date": "2026-11-14",
            "claude_code_version": "9.9.9", "runs_per_arm": 5}

    def test_each_comparison_equals_a_factor_only_run_at_that_factor(self, tmp_path: Path) -> None:
        fw = cli_fw(tmp_path, cal_file(tmp_path, self.BODY))
        assert set(fw["comparison"]) == {"uncalibrated", "low", "high"}
        for name, factor in (("uncalibrated", 1.0), ("low", 0.25), ("high", 3.0)):
            alone = cli_fw(tmp_path, cal_file(tmp_path, {"factor": factor}, f"f{name}.json"), f"{name}.json")
            assert fw["comparison"][name] == point_of(alone), name
            assert set(fw["comparison"][name]) == POINT_KEYS

    def test_the_points_differ_because_the_rule_is_rerun_not_rescaled(self, tmp_path: Path) -> None:
        fw = cli_fw(tmp_path, cal_file(tmp_path, self.BODY))
        totals = {fw["comparison"][k]["total_usd"] for k in ("uncalibrated", "low", "high")}
        assert len(totals) == 3
        rescaled = fw["comparison"]["uncalibrated"]["total_usd"] * 3.0
        assert fw["comparison"]["high"]["total_usd"] != pytest.approx(rescaled, rel=1e-3)

    def test_existing_fields_are_the_estimate_at_the_files_factor(self, tmp_path: Path) -> None:
        fw = cli_fw(tmp_path, cal_file(tmp_path, self.BODY))
        alone = cli_fw(tmp_path, cal_file(tmp_path, {"factor": 2.0}, "alone.json"), "alone.json")
        for key in alone:
            if key not in ("comparison", "calibration", "verdict"):
                assert fw[key] == alone[key], key

    def test_low_and_high_are_null_without_bounds(self, tmp_path: Path) -> None:
        fw = cli_fw(tmp_path, cal_file(tmp_path, {"factor": 2.0}))
        assert fw["comparison"]["low"] is None and fw["comparison"]["high"] is None
        assert fw["comparison"]["uncalibrated"]["calibration_factor"] == 1.0

    def test_calibration_object(self, tmp_path: Path) -> None:
        fw = cli_fw(tmp_path, cal_file(tmp_path, self.BODY))
        assert fw["calibration"] == {"date": "2026-11-14", "claude_code_version": "9.9.9", "runs_per_arm": 5}
        bare = cli_fw(tmp_path, cal_file(tmp_path, {"factor": 2.0}, "b.json"), "b.json")
        assert bare["calibration"] == {"date": None, "claude_code_version": None, "runs_per_arm": None}

    def test_uncalibrated_has_null_comparison_and_calibration(self) -> None:
        fw = fw_of(ROOT)
        assert fw["comparison"] is None and fw["calibration"] is None

    def test_extra_estimates_are_computed_only_when_calibrated(self, tmp_path: Path) -> None:
        real = fixed_weight.estimate
        for cal, runs in ((None, 1), (fixed_weight.Calibration(2.0, True), 2),
                          (fixed_weight.Calibration(2.0, True, 0.25, 3.0), 4)):
            with mock.patch.object(fixed_weight, "estimate", wraps=real) as spy:
                build(ROOT, fixed_weight=True, calibration=cal)
            assert spy.call_count == runs, cal

    def test_not_run_without_the_flag(self) -> None:
        with mock.patch.object(fixed_weight, "estimate") as spy:
            build(ROOT, calibration=fixed_weight.Calibration(2.0, True, 0.25, 3.0))
        assert spy.call_count == 0

    def test_export_carries_the_new_fields(self, tmp_path: Path) -> None:
        cal = cal_file(tmp_path, self.BODY)
        full, agg = tmp_path / "f.json", tmp_path / "a.json"
        proc = run_cli(*WINDOW, "--projects-root", str(ROOT), "--fixed-weight", "--calibration", str(cal),
                       "--json", str(full), "--export-aggregates", str(agg))
        assert proc.returncode == 0, proc.stderr
        exported = json.loads(agg.read_text())["fixed_weight"]
        assert exported == json.loads(full.read_text())["fixed_weight"]
        assert exported["comparison"]["high"]["calibration_factor"] == 3.0
        assert exported["calibration"]["claude_code_version"] == "9.9.9"


class TestCalibratedReport:
    BODY = TestComparison.BODY

    def lines(self, tmp_path: Path, body: dict) -> list[str]:
        proc = run_cli(*WINDOW, "--projects-root", str(ROOT), "--fixed-weight",
                       "--calibration", str(cal_file(tmp_path, body)))
        assert proc.returncode == 0, proc.stderr
        return proc.stdout.splitlines()

    def test_lines_appear_after_the_setup_line(self, tmp_path: Path) -> None:
        lines = self.lines(tmp_path, self.BODY)
        fw = cli_fw(tmp_path, cal_file(tmp_path, self.BODY))
        un = fw["comparison"]["uncalibrated"]["setup_share_of_total"]
        cal = fw["groups"]["setup"]["share_of_total"]
        low = fw["comparison"]["low"]["setup_share_of_total"]
        high = fw["comparison"]["high"]["setup_share_of_total"]
        pct = lambda x: f"{x * 100:.1f}%"  # noqa: E731
        setup = next(i for i, ln in enumerate(lines) if ln.startswith("  Setup (what your setup adds)"))
        side = next(i for i, ln in enumerate(lines) if "uncalibrated" in ln and "calibrated (factor 2)" in ln)
        assert pct(un) in lines[side] and pct(cal) in lines[side]
        rng = next(i for i, ln in enumerate(lines) if "calibration range" in ln)
        assert pct(low) in lines[rng] and pct(high) in lines[rng]
        prov = next(i for i, ln in enumerate(lines) if ln.startswith("  Calibration:"))
        assert "2026-11-14" in lines[prov] and "5 runs per arm" in lines[prov] and "9.9.9" in lines[prov]
        assert setup < side and setup < rng and setup < prov
        assert not any("UNCALIBRATED" in ln for ln in lines)

    def test_no_range_line_without_bounds(self, tmp_path: Path) -> None:
        lines = self.lines(tmp_path, {"factor": 2.0})
        assert not any("calibration range" in ln for ln in lines)
        assert any("calibrated (factor 2)" in ln for ln in lines)
        prov = next(ln for ln in lines if ln.startswith("  Calibration:"))
        assert "unknown" in prov

    def test_lines_absent_when_not_calibrated(self, tmp_path: Path) -> None:
        proc = run_default(tmp_path, *WINDOW, "--projects-root", str(ROOT), "--fixed-weight",
                           chars_per_token=3.7)
        text = proc.stdout
        assert "UNCALIBRATED ESTIMATE" in text
        assert "calibration range" not in text and "  Calibration:" not in text
        assert "calibrated (factor" not in text
