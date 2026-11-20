"""Tests for the cost ledger's skill rows, unattributed bucket and schema document (slice 5, #1332).

Two oracles, both derived from the spec and the attribution rule before the code
existed: ``fixtures/cost_ledger/EXPECTED.json`` (slice 1, per request id: session,
agent, skill, kept output tokens; never edited) and
``fixtures/cost_ledger_skills/EXPECTED.json`` (exact dollars; every token count is a
multiple of 62500 so the figures are exact in binary floating point).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from unittest import mock
from datetime import date
from pathlib import Path

import pytest

ENGINE = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(ENGINE))

import cost_ledger
import fixed_weight

HERE = Path(__file__).resolve().parent
SLICE1 = HERE / "fixtures" / "cost_ledger"
SLICE1_EXPECTED = json.loads((SLICE1 / "EXPECTED.json").read_text())["fixtures"]
SKILLS_FIXTURES = HERE / "fixtures" / "cost_ledger_skills"
SKILLS_EXPECTED = json.loads((SKILLS_FIXTURES / "EXPECTED.json").read_text())
SCHEMA_DOC = (
    HERE.parent.parent / "skills" / "vault-budget" / "references" / "cost-ledger-schema.md"
)
TODAY = date(2026, 11, 14)
KINDS = ("input", "output", "cache_read", "write_5m", "write_1h")


def build(root: Path, since: str = "2026-11-10", until: str = "2026-11-12") -> dict:
    return cost_ledger.build_ledger(root, since=since, until=until, today=TODAY)


def skills_by_name(ledger: dict) -> dict[str, dict]:
    return {r["skill"]: r for r in ledger["skills"]}


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ENGINE / "cost_ledger.py"), *args], capture_output=True, text=True
    )


def assert_conserved(ledger: dict, exact: bool = True) -> None:
    """S5: skill rows plus unattributed equal totals, kind by kind.

    Rows are rounded to six places one by one, so on dollars that are not exact in
    six places the sum of rows may differ from the rounded total by a rounding step
    per row (``exact=False``).
    """
    parts = [*ledger["skills"], ledger["unattributed"]]
    slack = 0 if exact else 1e-6 * (len(parts) + 1)

    def same(a: float, b: float) -> bool:
        return round(a, 6) == b if exact else abs(a - b) <= slack

    t = ledger["totals"]
    assert sum(p["calls"] for p in parts) == t["calls"]
    assert sum(p["unpriced_calls"] for p in parts) == t["unpriced_calls"]
    assert same(sum(p["usd"] for p in parts), t["usd"])
    for k in KINDS:
        assert sum(p["tokens"][k] for p in parts) == t["tokens"][k]
        assert same(sum(p["usd_breakdown"][k] for p in parts), t["usd_breakdown"][k])


# ---------------------------------------------------------------------------
# slice 1 fixtures as the oracle (S1, S2, S5)
# ---------------------------------------------------------------------------
def expected_split(name: str) -> tuple[dict[str, dict], dict]:
    skills: dict[str, dict] = {}
    unattributed = {"calls": 0, "output": 0}
    for call in SLICE1_EXPECTED[name]["calls"].values():
        row = unattributed if call["skill"] is None else skills.setdefault(
            call["skill"], {"calls": 0, "output": 0}
        )
        row["calls"] += 1
        row["output"] += call["output_tokens"]
    return skills, unattributed


class TestSlice1Fixtures:
    @pytest.mark.parametrize("name", sorted(SLICE1_EXPECTED))
    def test_skill_rows_and_unattributed_match_the_oracle(self, name: str) -> None:
        ledger = build(SLICE1 / name, since="2026-11-14", until="2026-11-14")
        want_skills, want_un = expected_split(name)
        got = skills_by_name(ledger)
        assert sorted(got) == sorted(want_skills)
        for skill, want in want_skills.items():
            assert got[skill]["calls"] == want["calls"], skill
            assert got[skill]["tokens"]["output"] == want["output"], skill
        un = ledger["unattributed"]
        assert (un["calls"], un["tokens"]["output"]) == (want_un["calls"], want_un["output"])
        assert ledger["totals"]["calls"] == SLICE1_EXPECTED[name]["call_count"]

    @pytest.mark.parametrize("name", sorted(SLICE1_EXPECTED))
    def test_conserved_and_priced(self, name: str) -> None:
        ledger = build(SLICE1 / name, since="2026-11-14", until="2026-11-14")
        assert_conserved(ledger, exact=False)
        # claude-sonnet-5-5 is in the price table: no call is unpriced, dollars are real.
        assert ledger["totals"]["unpriced_calls"] == 0
        assert ledger["totals"]["usd"] > 0

    def test_skills_sorted_by_name(self) -> None:
        names = [r["skill"] for r in build(SLICE1 / "two_skills", since="2026-11-14", until="2026-11-14")["skills"]]
        assert names == ["plugin-p:skill-one", "skill-two"]

    def test_subagent_calls_follow_their_own_records(self) -> None:
        ledger = build(SLICE1 / "two_subagents", since="2026-11-14", until="2026-11-14")
        # req-b1 is a subagent call carrying a skill; the other five are unattributed.
        assert skills_by_name(ledger)["plugin-q:skill-x"]["calls"] == 1
        assert ledger["unattributed"]["calls"] == 5


# ---------------------------------------------------------------------------
# exact dollars and the S1 edge cases
# ---------------------------------------------------------------------------
class TestSkillRows:
    ledger = build(SKILLS_FIXTURES / "projects")
    want = SKILLS_EXPECTED["projects"]

    def test_skill_names_are_taken_exactly_and_sorted(self) -> None:
        # bare vs qualified are two skills, case and a trailing space are kept, a skill
        # literally named unattributed is an ordinary row; empty and non-string skills
        # and a plugin-only record make no row; out-of-window and undated calls make none.
        assert [r["skill"] for r in self.ledger["skills"]] == sorted(self.want["skills"])
        assert [r["skill"] for r in self.ledger["skills"]] == [
            "Commit ", "commit", "unattributed", "workbench:commit",
        ]

    @pytest.mark.parametrize("skill", sorted(want["skills"]))
    def test_row_matches_oracle(self, skill: str) -> None:
        row = skills_by_name(self.ledger)[skill]
        want = self.want["skills"][skill]
        assert row["calls"] == want["calls"]
        assert row["unpriced_calls"] == want["unpriced_calls"]
        assert row["usd"] == want["usd"]
        assert row["tokens"]["input"] == want["input"]
        assert row["tokens"]["output"] == want["output"]
        assert row["sessions"] == want["sessions"]
        if "usd_breakdown" in want:
            assert row["usd_breakdown"] == want["usd_breakdown"]

    def test_row_fields(self) -> None:
        for row in self.ledger["skills"]:
            assert set(row) == {
                "skill", "calls", "unpriced_calls", "usd", "tokens", "usd_breakdown", "sessions",
            }
            assert set(row["tokens"]) == set(KINDS)
            assert set(row["usd_breakdown"]) == set(KINDS)

    def test_unpriced_call_counts_calls_and_tokens_but_adds_no_dollars(self) -> None:
        row = skills_by_name(self.ledger)["commit"]
        assert row["unpriced_calls"] == 1
        # c9 (unlisted model) carries 1 unit of input and 1 of output on top of the priced calls.
        assert row["tokens"]["input"] == 4 * 62500 and row["tokens"]["output"] == 5 * 62500
        assert row["usd"] == 7.1875

    def test_sessions_count_distinct_project_session_pairs(self) -> None:
        # commit has calls in (-p1, s1), (-p1, s2; main and subagent) and (-p2, s1).
        assert skills_by_name(self.ledger)["commit"]["sessions"] == 3

    def test_subagent_call_with_a_skill_lands_in_that_skill(self) -> None:
        # d1 (main, 1 unit input) + d2 (subagent, 1 unit output) are both "commit" in s2.
        only = build(SKILLS_FIXTURES / "projects", since="2026-11-11", until="2026-11-11")
        assert skills_by_name(only)["commit"]["calls"] == 6

    def test_unattributed_matches_oracle(self) -> None:
        un = self.ledger["unattributed"]
        want = self.want["unattributed"]
        assert "skill" not in un
        assert set(un) == {"calls", "unpriced_calls", "usd", "tokens", "usd_breakdown", "sessions"}
        assert (un["calls"], un["unpriced_calls"], un["usd"], un["sessions"]) == (
            want["calls"], want["unpriced_calls"], want["usd"], want["sessions"],
        )
        assert un["tokens"]["input"] == want["input"] and un["tokens"]["output"] == want["output"]
        assert un["usd_breakdown"] == want["usd_breakdown"]

    def test_conserved_and_matches_totals_oracle(self) -> None:
        assert_conserved(self.ledger)
        t = self.ledger["totals"]
        want = self.want["totals"]
        assert (t["calls"], t["unpriced_calls"], t["usd"]) == (want["calls"], want["unpriced_calls"], want["usd"])
        assert t["usd_breakdown"] == want["usd_breakdown"]

    def test_session_and_agent_rows_unchanged_in_shape(self) -> None:
        s = self.ledger["sessions"][0]
        assert set(s) == {
            "project", "session_id", "first_timestamp", "last_timestamp", "calls",
            "unpriced_calls", "usd", "tokens", "usd_breakdown", "agents", "shape",
        }

    def test_nothing_inferred_from_plugin_or_skill_tool_calls(self, tmp_path: Path) -> None:
        # A plugin-only record and a Skill tool_use content block do not attribute a call.
        path = tmp_path / "-p" / "s1.jsonl"
        path.parent.mkdir(parents=True)
        recs = [
            {"type": "assistant", "requestId": "r1", "timestamp": "2026-11-11T00:00:00Z",
             "attributionPlugin": "plug",
             "message": {"id": "m1", "model": "claude-opus-4-8", "usage": {"input_tokens": 1},
                         "content": [{"type": "tool_use", "name": "Skill", "input": {"skill": "x"}}]}},
            {"type": "assistant", "requestId": "r2", "timestamp": "2026-11-11T00:00:01Z",
             "attributionSkill": None,
             "message": {"id": "m2", "model": "claude-opus-4-8", "usage": {"input_tokens": 1}}},
        ]
        path.write_text("".join(json.dumps(r) + "\n" for r in recs))
        ledger = build(tmp_path)
        assert ledger["skills"] == []
        assert ledger["unattributed"]["calls"] == 2


class TestNoUnattributedCall:
    ledger = build(SKILLS_FIXTURES / "many_skills" / "projects")

    def test_unattributed_is_present_with_zeros(self) -> None:
        un = self.ledger["unattributed"]
        assert un["calls"] == 0 and un["unpriced_calls"] == 0 and un["usd"] == 0
        assert un["sessions"] == 0
        assert all(un["tokens"][k] == 0 and un["usd_breakdown"][k] == 0 for k in KINDS)
        assert_conserved(self.ledger)

    def test_empty_window_has_empty_skills_and_zero_unattributed(self) -> None:
        ledger = build(SKILLS_FIXTURES / "projects", since="2030-01-01", until="2030-01-02")
        assert ledger["skills"] == []
        assert ledger["unattributed"]["calls"] == 0 and ledger["unattributed"]["sessions"] == 0
        assert_conserved(ledger)


class TestJsonFile:
    def test_schema_version_7_and_top_level_keys(self, tmp_path: Path) -> None:
        out = tmp_path / "o.json"
        proc = run_cli("--since", "2026-11-10", "--until", "2026-11-12",
                       "--projects-root", str(SKILLS_FIXTURES / "projects"), "--json", str(out))
        assert proc.returncode == 0, proc.stderr
        text = out.read_text()
        obj = json.loads(text)
        assert text == json.dumps(obj, sort_keys=True, indent=2) + "\n"
        assert obj["schema_version"] == 7
        assert set(obj) == {
            "schema_version", "window", "totals", "coverage", "unpriced", "sessions",
            "skills", "unattributed", "meter", "recorded_cost", "fixed_weight",
            "triggers", "long_context_tokens",
        }


# ---------------------------------------------------------------------------
# S7 report
# ---------------------------------------------------------------------------
class TestReport:
    def many(self) -> str:
        proc = run_cli("--since", "2026-11-10", "--until", "2026-11-12",
                       "--projects-root", str(SKILLS_FIXTURES / "many_skills" / "projects"))
        assert proc.returncode == 0, proc.stderr
        return proc.stdout

    def test_top_15_by_dollars_ties_by_name_then_one_rest_line(self) -> None:
        out = self.many()
        want = SKILLS_EXPECTED["many_skills"]
        positions = [out.index(name) for name in want["shown"]]
        assert positions == sorted(positions)
        # skill-15, 16, 17 tie; only the first by name is shown.
        assert "skill-16" not in out and "skill-17" not in out
        assert f"{want['rest']['count']} more skills" in out
        rest_line = next(ln for ln in out.splitlines() if "more skills" in ln)
        assert "$1.25" in rest_line

    def test_rest_line_says_one_more_skill_for_one_and_n_more_skills_otherwise(
        self, tmp_path: Path
    ) -> None:
        src = SKILLS_FIXTURES / "many_skills" / "projects" / "-p3" / "s1.jsonl"
        kept = [ln for ln in src.read_text().splitlines() if '"skill-17"' not in ln]
        proj = tmp_path / "projects" / "-p3"
        proj.mkdir(parents=True)
        (proj / "s1.jsonl").write_text("\n".join(kept) + "\n")
        proc = run_cli("--since", "2026-11-10", "--until", "2026-11-12",
                       "--projects-root", str(tmp_path / "projects"))
        assert proc.returncode == 0, proc.stderr
        one = [ln.strip() for ln in proc.stdout.splitlines() if "more skill" in ln]
        assert len(one) == 1 and one[0].startswith("1 more skill ")
        assert "1 more skills" not in proc.stdout
        out = self.many()
        many = [ln.strip() for ln in out.splitlines() if "more skill" in ln]
        assert len(many) == 1 and many[0].startswith("2 more skills ")

    def test_no_rest_line_with_15_or_fewer_skills(self) -> None:
        proc = run_cli("--since", "2026-11-10", "--until", "2026-11-12",
                       "--projects-root", str(SKILLS_FIXTURES / "projects"))
        assert "more skills" not in proc.stdout
        assert "workbench:commit" in proc.stdout

    def test_skill_named_unattributed_does_not_collide_with_the_bucket_label(self) -> None:
        proc = run_cli("--since", "2026-11-10", "--until", "2026-11-12",
                       "--projects-root", str(SKILLS_FIXTURES / "projects"))
        lines = [ln.strip() for ln in proc.stdout.splitlines()]
        skill_lines = [ln for ln in lines if ln.startswith("unattributed")]
        bucket_lines = [ln for ln in lines if ln.startswith("(unattributed)")]
        assert len(skill_lines) == 1 and len(bucket_lines) == 1
        assert skill_lines[0] != bucket_lines[0]
        assert "%" not in skill_lines[0] and "%" in bucket_lines[0]

    def test_unattributed_row_always_printed_with_share(self) -> None:
        out = self.many()
        row = next(ln for ln in out.splitlines() if ln.strip().startswith("(unattributed)"))
        assert "$0.00" in row and "0%" in row
        proc = run_cli("--since", "2026-11-10", "--until", "2026-11-12",
                       "--projects-root", str(SKILLS_FIXTURES / "projects"))
        row = next(ln for ln in proc.stdout.splitlines() if ln.strip().startswith("(unattributed)") and "%" in ln)
        assert "$4.38" in row or "$4.37" in row  # 4.375 over a 12.8125 window total
        assert "34%" in row

    def test_lower_bound_line(self) -> None:
        out = self.many()
        line = next(ln for ln in out.splitlines() if "lower bound" in ln)
        assert "invoking call" in line and "later-turn" in line

    def test_empty_window_prints_without_dividing_by_zero(self) -> None:
        proc = run_cli("--since", "2030-01-01", "--until", "2030-01-02",
                       "--projects-root", str(SKILLS_FIXTURES / "projects"))
        assert proc.returncode == 0, proc.stderr
        assert "Traceback" not in proc.stderr
        row = next(ln for ln in proc.stdout.splitlines() if ln.strip().startswith("(unattributed)"))
        assert "$0.00" in row and "0%" in row
        assert "lower bound" in proc.stdout


# ---------------------------------------------------------------------------
# S8, S9 schema document
# ---------------------------------------------------------------------------
def flatten(node: object, prefix: str = "") -> set[str]:
    """Dotted paths of every field in ``node``: ``[]`` for list elements and ``<model>``
    for the keys of a ``by_model`` map (the one dynamic-key map the ledger emits)."""
    paths: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            name = "<model>" if prefix.endswith("by_model") else key
            path = f"{prefix}.{name}" if prefix else name
            paths.add(path)
            paths |= flatten(value, path)
    elif isinstance(node, list):
        for item in node:
            path = f"{prefix}[]"
            paths.add(path)
            paths |= flatten(item, path)
    return paths


def documented_paths() -> set[str]:
    """The backticked path in the first cell of each field-table row of the document."""
    found: set[str] = set()
    for line in SCHEMA_DOC.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\|\s*`([^`]+)`\s*\|", line)
        if m:
            found.add(m.group(1))
    return found


class TestSchemaDocument:
    @staticmethod
    def emitted() -> set[str]:
        # The slice 6 fixture exercises everything the slice 5 one does, plus a
        # recorded cost and (with a meter applied) a meter block.
        # Slice 7 adds the fixed-weight estimate, which the document covers too.
        ledger = cost_ledger.build_ledger(
            HERE / "fixtures" / "cost_ledger_export" / "projects",
            since="2026-11-10", until="2026-11-12", today=TODAY, fixed_weight=True,
        )
        cost_ledger.apply_meter(ledger, 12.5)
        # Slice 8 adds the comparison and calibration objects, filled only when calibrated.
        calibrated = cost_ledger.build_ledger(
            HERE / "fixtures" / "cost_ledger_export" / "projects",
            since="2026-11-10", until="2026-11-12", today=TODAY, fixed_weight=True,
            calibration=fixed_weight.Calibration(1.5, True, 1.0, 2.0, "2026-11-14", "9.9.9", 5),
        )
        # Slice 9 adds the verdict; its component list is filled only when CUTTABLE.
        with mock.patch.object(fixed_weight, "VERDICT_BAR", 0.05):
            cuttable = cost_ledger.build_ledger(
                HERE / "fixtures" / "cost_ledger_fixed" / "projects",
                since="2026-11-10", until="2026-11-12", today=TODAY, fixed_weight=True,
            )
        assert cuttable["fixed_weight"]["verdict"]["components"], "fixture must reach CUTTABLE"
        assert ledger["unpriced"], "fixture must exercise an unpriced-model entry"
        assert ledger["recorded_cost"]["sessions_comparable"] > 0
        assert any(a["by_model"] for s in ledger["sessions"] for a in s["agents"])
        assert any(a["agent_id"] != "main" for s in ledger["sessions"] for a in s["agents"])
        return flatten(ledger) | flatten(calibrated) | flatten(cuttable)

    def test_every_emitted_path_is_documented(self) -> None:
        missing = sorted(self.emitted() - documented_paths())
        assert not missing, f"emitted but not in {SCHEMA_DOC.name}: {missing}"

    def test_every_documented_path_is_emitted(self) -> None:
        extra = sorted(documented_paths() - self.emitted())
        assert not extra, f"in {SCHEMA_DOC.name} but never emitted: {extra}"

    def test_flatten_names_dynamic_and_list_paths(self) -> None:
        paths = self.emitted()
        assert "sessions[].agents[].by_model.<model>.usd" in paths
        assert "skills[].usd_breakdown.cache_read" in paths
        assert "unattributed.sessions" in paths

    def test_document_states_version_history_and_caveat(self) -> None:
        text = SCHEMA_DOC.read_text(encoding="utf-8")
        assert "lower bound" in text
        assert "as observed" in text
        assert re.search(r"\b1\b.*sessions and agents", text)
        assert re.search(r"\b2\b.*skills and unattributed", text)
        assert re.search(r"\b3\b.*meter.*recorded", text)

    def test_command_document_links_the_schema(self) -> None:
        command = (SCHEMA_DOC.parent / "command.md").read_text(encoding="utf-8")
        assert "cost-ledger-schema.md" in command
