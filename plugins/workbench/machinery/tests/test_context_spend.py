"""Tests for context_spend — the context-size / spend instrument.

Every fixture here is a small synthetic JSONL transcript written into a tmp
projects root. No real transcript content (and no real first-message text) is
used anywhere. The numbers asserted are computed by hand from the weights
input 1 / output 5 / cache-write 1.25 / cache-read 0.1 times the tier
(opus/fable 5, sonnet 1, haiku 0.27).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(SCRIPTS_DIR))

import budget_burn
import context_spend as cs

SONNET = "claude-sonnet-5-5"
OPUS = "claude-opus-5-5"
HAIKU = "claude-haiku-5-5"


def T(day: int, minute: int = 0, hour: int = 10) -> str:
    return f"2026-11-{day:02d}T{hour:02d}:{minute:02d}:00.000Z"


def asst(
    msg_id,
    req,
    ts,
    model=SONNET,
    i=0,
    o=0,
    cw=0,
    cr=0,
    side=False,
    tools=(),
):
    content = [
        {"type": "tool_use", "id": tid, "name": name, "input": inp}
        for tid, name, inp in tools
    ]
    line = {
        "type": "assistant",
        "uuid": f"u-{msg_id}-{req}-{o}",
        "requestId": req,
        "timestamp": ts,
        "message": {
            "id": msg_id,
            "model": model,
            "content": content,
            "usage": {
                "input_tokens": i,
                "output_tokens": o,
                "cache_creation_input_tokens": cw,
                "cache_read_input_tokens": cr,
            },
        },
    }
    if side:
        line["isSidechain"] = True
    return line


def user(text, ts, origin=None, meta=False):
    line = {"type": "user", "timestamp": ts, "message": {"content": text}}
    if origin:
        line["origin"] = {"kind": origin}
    if meta:
        line["isMeta"] = True
    return line


def tool_result(tid, text, ts):
    return {
        "type": "user",
        "timestamp": ts,
        "message": {
            "content": [{"type": "tool_result", "tool_use_id": tid, "content": text}]
        },
    }


def compact(ts, trigger="auto", pre=300_000, post=20_000):
    return {
        "type": "system",
        "subtype": "compact_boundary",
        "timestamp": ts,
        "compactMetadata": {"trigger": trigger, "preTokens": pre, "postTokens": post},
    }


def write(path: Path, lines) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    return path


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "projects"


def run(root: Path, **kw) -> dict:
    return cs.analyze(root, **kw)


# ---------------------------------------------------------------------------
# dedupe
# ---------------------------------------------------------------------------
class TestDedupe:
    def lines(self):
        return [
            asst("m1", "r1", T(1, 0), o=5, cr=1000),
            asst("m1", "r1", T(1, 1), o=20, cr=1000),  # same call, bigger output
            asst("m1", "r1", T(1, 2), o=7, cr=1000),  # later, smaller: ignored
            asst("m1", "r2", T(1, 3), o=1, cr=1000),  # same msg id, new request
        ]

    def test_keeps_max_output_line_per_message_request(self, root):
        write(root / "p" / "s1.jsonl", self.lines())
        r = run(root)
        assert r["calls"] == 2
        assert r["by_model"][SONNET]["out"] == 21  # 20 + 1

    def test_request_rule_keeps_first_seen_per_request(self, root):
        # budget_burn's rule: one count per requestId, first line wins.
        write(root / "p" / "s1.jsonl", self.lines())
        r = run(root, dedupe="request")
        assert r["calls"] == 2
        assert r["by_model"][SONNET]["out"] == 5 + 1

    def test_dedupes_across_files(self, root):
        write(root / "p" / "s1.jsonl", [asst("m1", "r1", T(1), o=5, cr=10)])
        write(root / "p" / "s2.jsonl", [asst("m1", "r1", T(1), o=9, cr=10)])
        assert run(root)["calls"] == 1

    def test_no_ids_falls_back_to_uuid(self, root):
        a, b = asst(None, None, T(1), o=1), asst(None, None, T(1, 1), o=2)
        a["message"].pop("id")
        b["message"].pop("id")
        a.pop("requestId")
        b.pop("requestId")
        write(root / "p" / "s1.jsonl", [a, b])
        assert run(root)["calls"] == 2


class TestModelRule:
    def lines(self):
        return [
            asst("m1", "r1", T(1), model=SONNET, i=10),
            asst("m2", "r2", T(1, 1), model="<synthetic>", i=10),
            asst("m3", "r3", T(1, 2), model=None, i=10),
            asst("m4", "r4", T(1, 3), model="mystery-9", i=10),
        ]

    def test_default_drops_missing_and_synthetic_models(self, root):
        write(root / "p" / "s.jsonl", self.lines())
        r = run(root)
        assert r["calls"] == 2  # sonnet + mystery
        assert r["dropped_no_model"] == 2
        assert "mystery-9" in r["by_model"]

    def test_unknown_model_priced_at_top_tier(self, root):
        write(root / "p" / "s.jsonl", self.lines())
        r = run(root)
        assert r["by_model"]["mystery-9"]["cost"] == pytest.approx(10 * 5 / 1e6)

    def test_billable_rule_drops_unknown_tiers_like_budget_burn(self, root):
        write(root / "p" / "s.jsonl", self.lines())
        r = run(root, model_rule="billable")
        assert r["calls"] == 1
        assert list(r["by_model"]) == [SONNET]


# ---------------------------------------------------------------------------
# pricing
# ---------------------------------------------------------------------------
class TestPricing:
    def test_relative_weights_by_tier(self, root):
        usage = dict(i=1_000_000, o=1_000_000, cw=1_000_000, cr=1_000_000)
        write(
            root / "p" / "s.jsonl",
            [
                asst("a", "a", T(1), model=OPUS, **usage),
                asst("b", "b", T(1), model=SONNET, **usage),
                asst("c", "c", T(1), model=HAIKU, **usage),
            ],
        )
        r = run(root)
        unit = 1 + 5 + 1.25 + 0.1
        assert r["by_model"][OPUS]["cost"] == pytest.approx(5 * unit)
        assert r["by_model"][SONNET]["cost"] == pytest.approx(1 * unit)
        assert r["by_model"][HAIKU]["cost"] == pytest.approx(0.27 * unit)
        cat = r["by_category"]["cost"]
        assert cat["out"] == pytest.approx((5 + 1 + 0.27) * 5)
        assert cat["cr"] == pytest.approx((5 + 1 + 0.27) * 0.1)

    def test_fable_is_top_tier(self, root):
        write(root / "p" / "s.jsonl", [asst("a", "a", T(1), model="claude-fable-5-2", i=1_000_000)])
        assert run(root)["total_cost"] == pytest.approx(5.0)

    def test_dollar_pricing_reuses_budget_burn(self, root):
        write(
            root / "p" / "s.jsonl",
            [asst("a", "a", T(1), model=OPUS, i=1000, o=2000, cw=3000, cr=4000)],
        )
        r = run(root, pricing="usd")
        expected = budget_burn._record_cost(
            {
                "input_tokens": 1000,
                "output_tokens": 2000,
                "cache_creation_input_tokens": 3000,
                "cache_read_input_tokens": 4000,
            },
            "opus",
        )
        assert r["unit"] == "usd"
        assert r["total_cost"] == pytest.approx(expected)


# ---------------------------------------------------------------------------
# subagent rule
# ---------------------------------------------------------------------------
class TestSubagent:
    def test_subagent_file_and_sidechain_flag(self, root):
        write(
            root / "p" / "s1.jsonl",
            [
                asst("m1", "r1", T(1), cr=1_000_000),  # main: 0.1
                asst("m2", "r2", T(1, 1), cr=1_000_000, side=True),  # sidechain in main file
            ],
        )
        write(
            root / "p" / "s1" / "subagents" / "agent-1.jsonl",
            [asst("m3", "r3", T(1, 2), cr=1_000_000 * 2)],  # no flag: path rule
        )
        r = run(root)
        mv = r["main_vs_subagent"]
        assert mv["main"]["calls"] == 1
        assert mv["subagent"]["calls"] == 2
        assert mv["main"]["cost"] == pytest.approx(0.1)
        assert mv["subagent"]["share"] == pytest.approx(0.3 / 0.4)

    def test_subagent_calls_excluded_from_main_context(self, root):
        write(root / "p" / "s1.jsonl", [asst("m1", "r1", T(1), cr=1000)])
        write(
            root / "p" / "s1" / "subagents" / "a.jsonl",
            [asst("m2", "r2", T(1), cr=900_000)],
        )
        assert run(root)["main_context"]["max"] == 1000


# ---------------------------------------------------------------------------
# trigger classification
# ---------------------------------------------------------------------------
class TestTriggers:
    @pytest.mark.parametrize(
        "entry,expected",
        [
            (user("<task-notification>x</task-notification>", T(1)), "task-notification"),
            (user("hi", T(1), origin="task-notification"), "task-notification"),
            (user("Stop hook feedback: nope", T(1)), "hook"),
            (user("typed words", T(1), origin="human"), "human-typed"),
            (user("injected", T(1), meta=True), "meta/system-injected"),
            (user("something else", T(1)), "programmatic"),
        ],
    )
    def test_classify(self, entry, expected):
        assert cs.classify_trigger(entry) == expected

    def test_task_notification_beats_human_origin(self):
        e = user("<task-notification>", T(1), origin="human")
        assert cs.classify_trigger(e) == "task-notification"

    def test_calls_take_last_non_tool_result_user_entry(self, root):
        write(
            root / "p" / "s.jsonl",
            [
                user("go", T(1, 0), origin="human"),
                asst("a", "a", T(1, 1), cr=1_000_000, tools=[("t1", "Bash", {})]),
                tool_result("t1", "ok", T(1, 2)),  # must NOT reset the trigger
                asst("b", "b", T(1, 3), cr=1_000_000),
                user("<task-notification>done</task-notification>", T(1, 4)),
                asst("c", "c", T(1, 5), cr=2_000_000),
            ],
        )
        r = run(root)["triggers"]
        assert r["human-typed"]["calls"] == 2
        assert r["task-notification"]["calls"] == 1
        assert r["human-typed"]["share_of_main"] == pytest.approx(0.2 / 0.4)
        assert r["task-notification"]["share_of_main"] == pytest.approx(0.2 / 0.4)

    def test_trigger_resets_per_file(self, root):
        write(root / "p" / "s1.jsonl", [user("x", T(1), origin="human"), asst("a", "a", T(1, 1), cr=1)])
        write(root / "p" / "s2.jsonl", [asst("b", "b", T(1, 2), cr=1)])
        r = run(root)["triggers"]
        assert r["human-typed"]["calls"] == 1
        assert r["none"]["calls"] == 1


# ---------------------------------------------------------------------------
# compaction events
# ---------------------------------------------------------------------------
class TestCompaction:
    def lines(self):
        return [
            asst("a", "a", T(1, 0), cr=290_000),
            asst("b", "b", T(1, 1), cr=300_000),
            compact(T(1, 2), "auto", pre=300_000),
            asst("c", "c", T(1, 3), cw=25_000, cr=0),
            asst("d", "d", T(1, 4), cr=30_000),
            compact(T(1, 5), "manual", pre=100_000),
            asst("e", "e", T(1, 6), cr=15_000),
            {"type": "system", "subtype": "other", "timestamp": T(1, 7)},
        ]

    def test_counts_split_and_pretokens(self, root):
        write(root / "p" / "s.jsonl", self.lines())
        c = run(root)["compactions"]
        assert c["count"] == 2
        assert c["by_trigger"] == {"auto": 1, "manual": 1}
        assert c["pre_tokens"]["max"] == 300_000
        assert c["pre_tokens"]["median"] == 200_000

    def test_first_call_after_each(self, root):
        write(root / "p" / "s.jsonl", self.lines())
        c = run(root)["compactions"]
        assert c["first_call_context"]["n"] == 2
        assert c["first_call_context"]["max"] == 25_000
        assert c["first_call_context"]["median"] == 20_000  # (25k+15k)/2

    def test_subagent_boundaries_ignored(self, root):
        write(
            root / "p" / "s" / "subagents" / "a.jsonl",
            [asst("a", "a", T(1), cr=1), compact(T(1, 1))],
        )
        assert run(root)["compactions"]["count"] == 0

    def test_boundary_outside_window_not_counted(self, root):
        write(root / "p" / "s.jsonl", [asst("a", "a", T(1), cr=1), compact(T(2)), asst("b", "b", T(3), cr=1)])
        assert run(root, since="2026-11-03")["compactions"]["count"] == 0
        assert run(root)["compactions"]["count"] == 1


class TestRereads:
    def lines(self, extra_calls=0):
        ls = [
            asst("a", "a", T(1, 0), cr=1000, tools=[("r1", "Read", {"file_path": "/x/a.txt"})]),
            tool_result("r1", "A" * 100, T(1, 0)),
            asst("b", "b", T(1, 1), cr=1000, tools=[("r2", "Read", {"file_path": "/x/b.txt"})]),
            tool_result("r2", "B" * 50, T(1, 1)),
            compact(T(1, 2)),
            asst("c", "c", T(1, 3), cr=500, tools=[
                ("r3", "Read", {"file_path": "/x/a.txt"}),  # re-read
                ("r4", "Read", {"file_path": "/x/new.txt"}),  # first read
            ]),
            tool_result("r3", "A" * 100, T(1, 3)),
            tool_result("r4", "N" * 9, T(1, 3)),
        ]
        for n in range(extra_calls):
            ls.append(asst(f"x{n}", f"x{n}", T(1, 10 + n), cr=600))
        ls.append(asst("late", "late", T(1, 50), cr=600, tools=[("r5", "Read", {"file_path": "/x/b.txt"})]))
        ls.append(tool_result("r5", "B" * 50, T(1, 50)))
        return ls

    def test_counts_rereads_of_pre_compaction_paths(self, root):
        # Fewer than 20 calls follow, so the late re-read of b.txt is in window.
        write(root / "p" / "s.jsonl", self.lines())
        r = run(root)["post_compaction_rereads"]
        assert r["compactions_analysed"] == 1
        assert r["reads_in_window"] == 3
        assert r["rereads"] == 2
        assert r["reread_bytes"] == 150

    def test_window_is_twenty_calls(self, root):
        # c + 19 extras = 20 calls after the boundary; "late" is the 21st.
        write(root / "p" / "s.jsonl", self.lines(extra_calls=19))
        r = run(root)["post_compaction_rereads"]
        assert r["rereads"] == 1
        assert r["reread_bytes"] == 100
        assert r["compactions_with_reread"] == 1


# ---------------------------------------------------------------------------
# window filter
# ---------------------------------------------------------------------------
class TestWindow:
    def test_filters_by_message_timestamp_not_file_mtime(self, root):
        p = write(
            root / "p" / "s.jsonl",
            [
                asst("a", "a", T(1), cr=100),
                asst("b", "b", T(5), cr=200),
                asst("c", "c", T(9), cr=400),
            ],
        )
        os.utime(p, None)  # mtime = now; must not matter
        r = run(root, since="2026-11-02", until="2026-11-08")
        assert r["calls"] == 1
        assert r["main_context"]["max"] == 200

    def test_until_is_inclusive_and_since_is_inclusive(self, root):
        write(
            root / "p" / "s.jsonl",
            [asst("a", "a", T(2, 0, 0), cr=1), asst("b", "b", T(8, 23, 23), cr=1), asst("c", "c", T(9), cr=1)],
        )
        assert run(root, since="2026-11-02", until="2026-11-08")["calls"] == 2

    def test_old_file_mtime_does_not_hide_in_window_messages(self, root):
        # A file whose mtime is old cannot hold newer messages, but one whose
        # mtime is newer than `since` is always read. Check the safe direction.
        p = write(root / "p" / "s.jsonl", [asst("a", "a", T(5), cr=1)])
        old = 1_700_000_000
        os.utime(p, (old, old))
        assert run(root, since="2026-11-01")["calls"] == 0  # mtime 2023 < since

    def test_message_without_timestamp_is_dropped_when_windowed(self, root):
        line = asst("a", "a", T(5), cr=1)
        line.pop("timestamp")
        write(root / "p" / "s.jsonl", [line])
        assert run(root, since="2026-11-01")["calls"] == 0
        assert run(root)["calls"] == 1


# ---------------------------------------------------------------------------
# context distribution, cache rewrites, ceiling
# ---------------------------------------------------------------------------
class TestContextDistribution:
    def test_percentiles_and_threshold_shares(self, root):
        ctxs = [100_000, 150_000, 250_000, 600_000]
        write(
            root / "p" / "s.jsonl",
            [asst(f"m{k}", f"r{k}", T(1, k), cr=c) for k, c in enumerate(ctxs)],
        )
        m = run(root)["main_context"]
        assert m["calls"] == 4
        assert m["median"] == 200_000
        assert m["max"] == 600_000
        assert m["p90"] == 600_000  # sorted[int(.9*4)]
        total = sum(ctxs) * 0.1 / 1e6
        a200 = m["above"]["200000"]
        assert a200["call_share"] == pytest.approx(0.5)
        assert a200["main_cost_share"] == pytest.approx((250_000 + 600_000) * 0.1 / 1e6 / total)
        assert m["above"]["500000"]["call_share"] == pytest.approx(0.25)


class TestCacheRewrites:
    def test_flags_large_context_cache_writes_with_gap(self, root):
        write(
            root / "p" / "s.jsonl",
            [
                asst("a", "a", T(1, 0), cr=200_000),  # not a rewrite
                asst("b", "b", T(1, 10), cw=180_000, cr=20_000),  # 90% write, gap 10 min
                asst("c", "c", T(1, 11), cw=60_000, cr=40_000),  # ctx 100k: not >100k
                asst("d", "d", T(3, 0), cw=150_000, cr=50_000),  # gap > 60 min
                asst("e", "e", T(3, 1), cw=10_000, cr=10_000),  # small ctx
            ],
        )
        w = run(root)["cache_rewrites"]
        assert w["count"] == 2
        assert w["gaps_available"] == 2
        assert w["gap_over_5min"] == 2
        assert w["gap_over_60min"] == 1
        # b: 10 min after a; d: 2 days minus 11 min after c.
        assert w["median_gap_min"] == pytest.approx((10 + 2 * 24 * 60 - 11) / 2)
        cost = (180_000 * 1.25 + 20_000 * 0.1 + 150_000 * 1.25 + 50_000 * 0.1) / 1e6
        assert w["cost"] == pytest.approx(cost)

    def test_first_call_has_no_gap(self, root):
        write(root / "p" / "s.jsonl", [asst("a", "a", T(1), cw=150_000, cr=10_000)])
        w = run(root)["cache_rewrites"]
        assert w["count"] == 1
        assert w["gaps_available"] == 0


class TestCeiling:
    def lines(self):
        return [
            asst("a", "a", T(1, 0), cr=150_000),
            asst("b", "b", T(1, 1), cr=250_000),
            asst("c", "c", T(1, 2), cr=260_000),
        ]

    def test_hand_computed_simulation(self, root):
        write(root / "p" / "s.jsonl", self.lines())
        r = run(root, ceilings=[200_000], resume_sizes=[50_000])
        row = next(x for x in r["ceiling"] if x["resume_tokens"] == 50_000)
        # 150k read; reset at 250k (resume 50k @ 1.25 + 3000 digest out @ 5);
        # 260k - 200k offset = 60k read.
        sim = (150_000 * 0.1 + 50_000 * 0.1 + 60_000 * 0.1 + 50_000 * 1.25 + 3000 * 5) / 1e6
        assert row["sim_cost"] == pytest.approx(sim)
        assert row["resets"] == 1
        assert row["affected_session_share"] == pytest.approx(1.0)
        actual = (150_000 + 250_000 + 260_000) * 0.1 / 1e6
        assert row["actual_main_cost"] == pytest.approx(actual)
        assert row["saved_share_of_main"] == pytest.approx((actual - sim) / actual)

    def test_natural_drop_resets_offset(self, root):
        write(
            root / "p" / "s.jsonl",
            [
                asst("a", "a", T(1, 0), cr=250_000),
                asst("b", "b", T(1, 1), cr=20_000),  # >50% drop: real reset
                asst("c", "c", T(1, 2), cr=30_000),
            ],
        )
        r = run(root, ceilings=[300_000], resume_sizes=[10_000])
        row = r["ceiling"][0]
        assert row["resets"] == 0
        assert row["sim_cost"] == pytest.approx(row["actual_main_cost"])

    def test_observed_resume_size_row_added(self, root):
        write(
            root / "p" / "s.jsonl",
            [asst("a", "a", T(1, 0), cr=250_000), asst("b", "b", T(1, 1), cr=20_000)],
        )
        r = run(root, ceilings=[200_000], resume_sizes=[30_000])
        assert {x["resume_tokens"] for x in r["ceiling"]} == {30_000, 20_000}

    def test_no_ceilings_no_rows(self, root):
        write(root / "p" / "s.jsonl", self.lines())
        assert run(root)["ceiling"] == []


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
class TestCli:
    def setup_root(self, root):
        write(
            root / "p" / "s.jsonl",
            [
                user("go", T(1, 0), origin="human"),
                asst("a", "a", T(1, 1), model=OPUS, cr=250_000),
                compact(T(1, 2)),
                asst("b", "b", T(1, 3), cr=10_000),
            ],
        )

    def test_json_output(self, root, capsys):
        self.setup_root(root)
        rc = cs.main(["--projects-root", str(root), "--json", "--since", "2026-11-01", "--until", "2026-11-30", "--ceiling", "200000,300000"])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["window"] == {"since": "2026-11-01", "until": "2026-11-30"}
        assert out["calls"] == 2
        assert {x["threshold"] for x in out["ceiling"]} == {200_000, 300_000}

    def test_text_output_has_every_section(self, root, capsys):
        self.setup_root(root)
        assert cs.main(["--projects-root", str(root)]) == 0
        out = capsys.readouterr().out
        for h in (
            "Cost by model",
            "Cost by token category",
            "Main vs subagent",
            "Main-session context",
            "Cost by turn trigger",
            "Compactions",
            "Re-reads after compaction",
            "Cache rewrites",
        ):
            assert h in out

    def test_bad_date_rejected(self, root):
        with pytest.raises(SystemExit):
            cs.main(["--projects-root", str(root), "--since", "yesterday"])

    def test_empty_root_reports_zero(self, root):
        root.mkdir()
        r = run(root)
        assert r["calls"] == 0
        assert r["total_cost"] == 0
