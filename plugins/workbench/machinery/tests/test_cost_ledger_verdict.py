"""Tests for the cost ledger's verdict against the 20% bar (slice 9, #1336).

The rule is driven through ``fixed_weight.verdict`` with small hand-built estimates;
report, JSON and export presence go through the CLI on the fixed-weight fixture.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
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
ROOT = HERE / "fixtures" / "cost_ledger_fixed" / "projects"
SKILL_REFS = HERE.parent.parent / "skills" / "vault-budget" / "references"
WINDOW = ("--since", "2026-11-10", "--until", "2026-11-12")
KEYS = {"bar", "bar_set", "share", "low", "high", "verdict", "provisional", "runs_per_arm", "components"}


def est(share, low=None, high=None, *, calibrated=True, runs=None, rows=None, setup_usd=1.0) -> dict:
    """A minimal estimate: ``low``/``high`` set means a comparison with those setup shares."""
    comparison = None
    if low is not None or high is not None:
        comparison = {
            "uncalibrated": {"setup_share_of_total": share},
            "low": {"setup_share_of_total": low},
            "high": {"setup_share_of_total": high},
        }
    return {
        "calibrated": calibrated,
        "groups": {"setup": {"usd": setup_usd, "share_of_total": share},
                   "claude_code": {"usd": 9.0, "share_of_total": 0.9}},
        "calibration": {"runs_per_arm": runs} if calibrated else None,
        "comparison": comparison if calibrated else None,
        "components": rows if rows is not None else [],
    }


def row(name: str, group: str, usd: float) -> dict:
    return {"component": name, "group": group, "usd": usd}


def run_main(*args: str, home: Path, bar: float | None = None) -> SimpleNamespace:
    out, err = io.StringIO(), io.StringIO()
    patches = [mock.patch.dict(os.environ, {"HOME": str(home)})]
    if bar is not None:
        patches.append(mock.patch.object(fixed_weight, "VERDICT_BAR", bar))
    with contextlib.ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        stack.enter_context(contextlib.redirect_stdout(out))
        stack.enter_context(contextlib.redirect_stderr(err))
        rc = cost_ledger.main(list(args))
    return SimpleNamespace(returncode=rc, stdout=out.getvalue(), stderr=err.getvalue())


def cal(tmp_path: Path, body: dict) -> Path:
    path = tmp_path / "cal.json"
    path.write_text(json.dumps(body))
    return path


# ---------------------------------------------------------------------------
# V1, V3 to V6, V8, V9: the rule
# ---------------------------------------------------------------------------
class TestRule:
    def test_constants(self) -> None:
        assert fixed_weight.VERDICT_BAR == 0.20
        assert fixed_weight.VERDICT_BAR_SET == "2026-11-14"

    @pytest.mark.parametrize("share,word", [(0.199, "CANNOT FIT"), (0.200, "CUTTABLE"), (0.201, "CUTTABLE")])
    def test_zero_spread_around_the_bar(self, share: float, word: str) -> None:
        v = fixed_weight.verdict(est(share))
        assert v["verdict"] == word
        assert v["low"] == v["high"] == v["share"] == share

    def test_exact_key_set_and_constants(self) -> None:
        v = fixed_weight.verdict(est(0.1))
        assert set(v) == KEYS
        assert v["bar"] == fixed_weight.VERDICT_BAR and v["bar_set"] == fixed_weight.VERDICT_BAR_SET

    def test_straddle_is_undecided_and_carries_runs(self) -> None:
        v = fixed_weight.verdict(est(0.20, 0.15, 0.25, runs=7))
        assert v["verdict"] == "UNDECIDED" and v["runs_per_arm"] == 7

    def test_high_exactly_at_the_bar_with_low_below_is_undecided(self) -> None:
        assert fixed_weight.verdict(est(0.15, 0.10, 0.20))["verdict"] == "UNDECIDED"

    def test_high_below_the_bar_cannot_fit(self) -> None:
        assert fixed_weight.verdict(est(0.15, 0.10, 0.199))["verdict"] == "CANNOT FIT"

    def test_low_at_the_bar_is_cuttable(self) -> None:
        assert fixed_weight.verdict(est(0.25, 0.20, 0.30))["verdict"] == "CUTTABLE"

    def test_low_and_high_are_min_and_max_of_three_points(self) -> None:
        # the low-factor point is the larger one (cap and clamp make share non-monotone)
        v = fixed_weight.verdict(est(0.18, 0.30, 0.10))
        assert (v["low"], v["high"]) == (0.10, 0.30)
        v = fixed_weight.verdict(est(0.50, 0.30, 0.10))
        assert (v["low"], v["high"]) == (0.10, 0.50)

    def test_calibration_without_bounds_collapses_to_share(self) -> None:
        e = est(0.25, runs=4)
        e["comparison"] = {"uncalibrated": {"setup_share_of_total": 0.1}, "low": None, "high": None}
        v = fixed_weight.verdict(e)
        assert v["low"] == v["high"] == 0.25 and v["verdict"] == "CUTTABLE"
        assert v["provisional"] is False and v["runs_per_arm"] == 4

    def test_provisional_only_when_uncalibrated(self) -> None:
        assert fixed_weight.verdict(est(0.1, calibrated=False))["provisional"] is True
        assert fixed_weight.verdict(est(0.1, calibrated=True))["provisional"] is False

    def test_runs_per_arm_null_without_calibration_or_record(self) -> None:
        assert fixed_weight.verdict(est(0.1, calibrated=False))["runs_per_arm"] is None
        assert fixed_weight.verdict(est(0.1, calibrated=True, runs=None))["runs_per_arm"] is None

    def test_null_share_is_no_data(self) -> None:
        v = fixed_weight.verdict(est(None, setup_usd=0.0))
        assert v["verdict"] == "NO DATA" and v["share"] is None and v["low"] is None and v["high"] is None
        assert v["components"] == []

    def test_pure(self) -> None:
        e = est(0.3, 0.2, 0.4, runs=3, rows=[row("skill_listing", "setup", 1.0)])
        before = json.dumps(e, sort_keys=True)
        fixed_weight.verdict(e)
        assert json.dumps(e, sort_keys=True) == before


# ---------------------------------------------------------------------------
# V7: components
# ---------------------------------------------------------------------------
class TestComponents:
    def test_sorted_by_usd_desc_then_name_and_setup_only(self) -> None:
        rows = [
            row("instructions", "setup", 0.25),
            row("system_prompt", "claude_code", 8.0),
            row("skill_listing", "setup", 0.5),
            row("agent_listing", "setup", 0.25),
            row("builtin_tool_schemas", "claude_code", 1.0),
        ]
        v = fixed_weight.verdict(est(0.3, rows=rows, setup_usd=1.0))
        assert [c["name"] for c in v["components"]] == ["skill_listing", "agent_listing", "instructions"]
        assert all(set(c) == {"name", "usd", "share_of_total"} for c in v["components"])
        assert [c["share_of_total"] for c in v["components"]] == [0.15, 0.075, 0.075]
        assert [c["usd"] for c in v["components"]] == [0.5, 0.25, 0.25]

    def test_claude_code_components_never_listed(self) -> None:
        rows = [row("system_prompt", "claude_code", 8.0), row("skill_listing", "setup", 1.0)]
        names = [c["name"] for c in fixed_weight.verdict(est(0.3, rows=rows))["components"]]
        assert names == ["skill_listing"]

    @pytest.mark.parametrize("e", [est(0.1), est(0.2, 0.1, 0.3), est(None, setup_usd=0.0)])
    def test_empty_unless_cuttable(self, e: dict) -> None:
        e["components"] = [row("skill_listing", "setup", 1.0)]
        assert fixed_weight.verdict(e)["components"] == []


# ---------------------------------------------------------------------------
# V2, V10: the estimate carries it; the report prints it
# ---------------------------------------------------------------------------
class TestCli:
    def test_estimate_with_calibration_attaches_verdict(self, tmp_path: Path) -> None:
        ledger = cost_ledger.build_ledger(ROOT, since="2026-11-10", until="2026-11-12",
                                          fixed_weight=True, today=date(2026, 11, 14))
        v = ledger["fixed_weight"]["verdict"]
        assert set(v) == KEYS and v["provisional"] is True
        assert v["share"] == ledger["fixed_weight"]["groups"]["setup"]["share_of_total"]
        assert v == fixed_weight.verdict(ledger["fixed_weight"] | {"verdict": None})

    def test_json_and_export_carry_the_same_block(self, tmp_path: Path) -> None:
        full, agg = tmp_path / "f.json", tmp_path / "a.json"
        proc = run_main(*WINDOW, "--projects-root", str(ROOT), "--fixed-weight",
                        "--json", str(full), "--export-aggregates", str(agg), home=tmp_path)
        assert proc.returncode == 0, proc.stderr
        obj = json.loads(full.read_text())
        assert obj["schema_version"] == 7
        assert set(obj["fixed_weight"]["verdict"]) == KEYS
        assert json.loads(agg.read_text())["fixed_weight"]["verdict"] == obj["fixed_weight"]["verdict"]

    def test_absent_without_the_flag(self, tmp_path: Path) -> None:
        full, agg = tmp_path / "f.json", tmp_path / "a.json"
        proc = run_main(*WINDOW, "--projects-root", str(ROOT), "--json", str(full),
                        "--export-aggregates", str(agg), home=tmp_path)
        assert proc.returncode == 0, proc.stderr
        assert json.loads(full.read_text())["fixed_weight"] is None
        assert json.loads(agg.read_text())["fixed_weight"] is None
        assert "Verdict (" not in proc.stdout

    def test_report_cannot_fit_provisional_prints_constants(self, tmp_path: Path) -> None:
        proc = run_main(*WINDOW, "--projects-root", str(ROOT), "--fixed-weight", home=tmp_path)
        lines = proc.stdout.splitlines()
        i = lines.index("Verdict (bar 20% of window spend, set 2026-11-14)")
        assert re.fullmatch(r"  Removable setup share: 17\.\d\d% \(low 17\.\d\d%, high 17\.\d\d%\)", lines[i + 1])
        assert lines[i + 2] == "  PROVISIONAL CANNOT FIT"
        assert i + 3 == len(lines)

    def test_report_heading_follows_the_constants(self, tmp_path: Path) -> None:
        with mock.patch.object(fixed_weight, "VERDICT_BAR", 0.05), \
                mock.patch.object(fixed_weight, "VERDICT_BAR_SET", "2030-01-02"):
            proc = run_main(*WINDOW, "--projects-root", str(ROOT), "--fixed-weight", home=tmp_path)
        assert "Verdict (bar 5% of window spend, set 2030-01-02)" in proc.stdout

    def test_report_cuttable_lists_components(self, tmp_path: Path) -> None:
        proc = run_main(*WINDOW, "--projects-root", str(ROOT), "--fixed-weight", home=tmp_path, bar=0.10)
        lines = proc.stdout.splitlines()
        i = next(n for n, line in enumerate(lines) if line.startswith("Verdict ("))
        assert lines[i + 2] == "  PROVISIONAL CUTTABLE"
        comp = lines[i + 3:]
        assert comp and all(re.fullmatch(r"    [a-z_]+  \$\d[\d,]*\.\d\d  \d+\.\d\d%", c) for c in comp)
        assert "system_prompt" not in " ".join(comp)

    def test_report_undecided_names_runs_per_arm(self, tmp_path: Path) -> None:
        path = cal(tmp_path, {"factor": 1.0, "low": 0.5, "high": 1.0, "runs_per_arm": 6})
        with mock.patch.object(fixed_weight, "VERDICT_BAR", 0.15):
            proc = run_main(*WINDOW, "--projects-root", str(ROOT), "--fixed-weight",
                            "--calibration", str(path), home=tmp_path)
        assert "  UNDECIDED: calibration spread too wide (runs per arm recorded: 6)" in proc.stdout
        assert "PROVISIONAL" not in proc.stdout

    def test_report_undecided_unknown_runs(self, tmp_path: Path) -> None:
        path = cal(tmp_path, {"factor": 1.0, "low": 0.5, "high": 1.0})
        with mock.patch.object(fixed_weight, "VERDICT_BAR", 0.15):
            proc = run_main(*WINDOW, "--projects-root", str(ROOT), "--fixed-weight",
                            "--calibration", str(path), home=tmp_path)
        assert "(runs per arm recorded: unknown)" in proc.stdout

    def test_report_no_data(self, tmp_path: Path) -> None:
        proc = run_main("--since", "2030-01-01", "--until", "2030-01-02", "--projects-root", str(ROOT),
                        "--fixed-weight", home=tmp_path)
        lines = proc.stdout.splitlines()
        i = next(n for n, line in enumerate(lines) if line.startswith("Verdict ("))
        assert lines[i + 1:] == ["  NO DATA: window spend is zero"]


# ---------------------------------------------------------------------------
# V11: documents
# ---------------------------------------------------------------------------
class TestDocuments:
    schema = (SKILL_REFS / "cost-ledger-schema.md").read_text(encoding="utf-8")
    command = (SKILL_REFS / "command.md").read_text(encoding="utf-8")

    def test_schema_states_version_7_everywhere(self) -> None:
        assert "Current `schema_version`: 7." in self.schema
        assert "Schema version of this file: `7`." in self.schema
        assert cost_ledger.SCHEMA_VERSION == 7
        assert "Schema version of this file: `4`" not in self.schema
        assert "Current `schema_version`: 5" not in self.schema

    def test_schema_documents_the_verdict_block_and_history(self) -> None:
        for key in KEYS:
            assert f"`fixed_weight.verdict.{key}`" in self.schema
        assert re.search(r"- 6:.*verdict.*`schema_version` is 6", self.schema)

    def test_command_no_longer_denies_a_verdict(self) -> None:
        assert "states no verdict" not in self.command
        for word in ("CUTTABLE", "CANNOT FIT", "UNDECIDED", "NO DATA"):
            assert word in self.command
