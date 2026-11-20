"""Structural tests for the cost-ledger attribution fixtures.

The fixtures under ``fixtures/cost_ledger/`` are hand-built, synthetic Claude
Code transcript sets (invented ids, placeholder text). They are the oracle for
the cost ledger's attribution rules, recorded in
``docs/experiments/2026-11-14-cost-ledger-attribution-spike/README.md``. These
tests assert the structural facts those rules rely on, with plain ``json`` and
no engine code, so a fixture that stops looking like a real transcript fails
here before a ledger test trusts it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent / "fixtures" / "cost_ledger"
EXPECTED = json.loads((ROOT / "EXPECTED.json").read_text())["fixtures"]
NAMES = ["skill_then_unattributed", "two_skills", "two_subagents"]
ATTRIBUTION_KEYS = (
    "attributionSkill",
    "attributionPlugin",
    "attributionAgent",
    "attributionMcpServer",
    "attributionMcpTool",
)


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def load(name: str) -> dict:
    """Return ``{"main": {session: records}, "subs": [(meta, records, path)]}``."""
    base = ROOT / name
    projects = [p for p in base.iterdir() if p.is_dir()]
    assert len(projects) == 1 and projects[0].name.startswith("-")
    project = projects[0]
    main = {p.stem: read_jsonl(p) for p in sorted(project.glob("*.jsonl"))}
    subs = []
    for jsonl in sorted(project.glob("*/subagents/agent-*.jsonl")):
        meta_path = jsonl.with_name(jsonl.stem + ".meta.json")
        subs.append((json.loads(meta_path.read_text()), read_jsonl(jsonl), jsonl))
    return {"main": main, "subs": subs, "project": project}


def all_records(fx: dict) -> list[dict]:
    recs = [r for rs in fx["main"].values() for r in rs]
    recs += [r for _, rs, _ in fx["subs"] for r in rs]
    return recs


def assistants(records: list[dict]) -> list[dict]:
    return [r for r in records if r.get("type") == "assistant"]


def call_key(r: dict) -> tuple[str, str]:
    return (r["message"]["id"], r["requestId"])


def group_calls(records: list[dict]) -> dict[tuple[str, str], list[dict]]:
    out: dict[tuple[str, str], list[dict]] = {}
    for r in assistants(records):
        out.setdefault(call_key(r), []).append(r)
    return out


def blocks(r: dict) -> list[dict]:
    c = r.get("message", {}).get("content")
    return [b for b in c if isinstance(b, dict)] if isinstance(c, list) else []


def skill_of(r: dict):
    return r.get("attributionSkill")


def invoked_skill(rs: list[dict]):
    """Skill name a call invokes through a Skill tool_use, else None."""
    for r in rs:
        for b in blocks(r):
            if b.get("type") == "tool_use" and b.get("name") == "Skill":
                return b["input"]["skill"]
    return None


def is_real_prompt(r: dict) -> bool:
    return (
        r.get("type") == "user"
        and not r.get("isMeta")
        and isinstance(r["message"]["content"], str)
    )


def ordered_calls(records: list[dict]) -> list[tuple[tuple[str, str], list[dict]]]:
    """Calls in file order of their first record."""
    groups = group_calls(records)
    seen, out = set(), []
    for r in assistants(records):
        k = call_key(r)
        if k not in seen:
            seen.add(k)
            out.append((k, groups[k]))
    return out


def prompts_before(records: list[dict], call_first_record: dict) -> int:
    n = 0
    for r in records:
        if r is call_first_record:
            return n
        if is_real_prompt(r):
            n += 1
    raise AssertionError("record not found")


def dedupe(fx: dict) -> dict[str, dict]:
    """Rule 6: one entry per (message.id, requestId), largest output_tokens."""
    kept: dict[tuple[str, str], dict] = {}
    for r in assistants(all_records(fx)):
        k = call_key(r)
        if k not in kept or (
            r["message"]["usage"]["output_tokens"]
            > kept[k]["message"]["usage"]["output_tokens"]
        ):
            kept[k] = r
    out = {}
    for (_, req), r in kept.items():
        agent = (
            "main"
            if "agentId" not in r
            else {"agentId": r["agentId"], "agentType": r.get("attributionAgent")}
        )
        out[req] = {
            "session": r["sessionId"],
            "agent": agent,
            "skill": skill_of(r),
            "output_tokens": r["message"]["usage"]["output_tokens"],
        }
    return out


# --------------------------------------------------------------------- shape


def test_fixture_layout_matches_claude_code_on_disk():
    for name in NAMES:
        fx = load(name)
        assert fx["main"], name
        for meta, recs, path in fx["subs"]:
            assert path.parent.name == "subagents"
            assert path.parent.parent.name in fx["main"]
            agent_id = path.stem[len("agent-") :]
            assert {r["agentId"] for r in recs} == {agent_id}


@pytest.mark.parametrize("name", NAMES)
def test_every_assistant_record_has_usage_model_timestamp_version(name):
    recs = assistants(all_records(load(name)))
    assert recs
    for r in recs:
        u = r["message"]["usage"]
        for k in ("input_tokens", "output_tokens"):
            assert isinstance(u[k], int)
        cc = u["cache_creation"]
        assert set(cc) == {"ephemeral_5m_input_tokens", "ephemeral_1h_input_tokens"}
        assert all(isinstance(v, int) for v in cc.values())
        assert r["message"]["model"]
        assert r["timestamp"]
        assert r["version"] == "2.1.293"


@pytest.mark.parametrize("name", NAMES)
def test_some_call_spans_two_records(name):
    groups = group_calls(all_records(load(name)))
    assert any(len(rs) >= 2 for rs in groups.values())


# --------------------------------------------------------------- attribution


@pytest.mark.parametrize("name", NAMES)
def test_attribution_fields_are_top_level_on_assistant_records_only(name):
    for r in all_records(load(name)):
        msg = r.get("message")
        for k in ATTRIBUTION_KEYS:
            if k in r:
                assert r["type"] == "assistant", (k, r["type"])
                assert isinstance(r[k], str)
            if isinstance(msg, dict):
                assert k not in msg


def test_attribution_skill_appears_somewhere():
    assert any(
        "attributionSkill" in r for n in NAMES for r in all_records(load(n))
    )


@pytest.mark.parametrize("name", NAMES)
def test_records_of_one_call_agree_on_attribution(name):
    for key, rs in group_calls(all_records(load(name))).items():
        for field in ATTRIBUTION_KEYS:
            assert len({r.get(field) for r in rs}) == 1, (key, field)


def test_a_invoking_call_is_unattributed_next_call_is_attributed_prompt_resets():
    recs = load("skill_then_unattributed")["main"]["sess-a"]
    calls = ordered_calls(recs)
    invoking = [(k, rs) for k, rs in calls if invoked_skill(rs)]
    assert len(invoking) == 1
    (k_inv, rs_inv), = invoking
    skill = invoked_skill(rs_inv)
    assert all(skill_of(r) is None for r in rs_inv)
    idx = [k for k, _ in calls].index(k_inv)
    nxt = calls[idx + 1][1]
    assert {skill_of(r) for r in nxt} == {skill}
    # every call between the invocation and the real prompt keeps the skill
    for k, rs in calls[idx + 1 :]:
        n = prompts_before(recs, rs[0]) - prompts_before(recs, rs_inv[0])
        if n == 0:
            assert {skill_of(r) for r in rs} == {skill}
    # the first call after the real user prompt is unattributed
    after = [
        rs for k, rs in calls if prompts_before(recs, rs[0]) > prompts_before(recs, rs_inv[0])
    ]
    assert after and all(skill_of(r) is None for r in after[0])
    assert sum(is_real_prompt(r) for r in recs) >= 1


def test_b_attribution_is_a_replaced_single_string():
    recs = load("two_skills")["main"]["sess-b"]
    calls = ordered_calls(recs)
    values = [skill_of(rs[0]) for _, rs in calls]
    assert all(v is None or isinstance(v, str) for v in values)
    # skill-one, a real prompt, then skill-two replaces it: both appear, never together
    assert "plugin-p:skill-one" in values and "skill-two" in values
    for _, rs in calls:
        assert not isinstance(skill_of(rs[0]), list)
    # bare and qualified names are reported as observed
    assert any(v and ":" not in v for v in values)
    assert any(v and ":" in v for v in values)


def test_b_same_turn_invoking_call_carries_the_previous_skill():
    recs = load("two_skills")["main"]["sess-b"]
    calls = ordered_calls(recs)
    same_turn = 0
    for i, (_, rs) in enumerate(calls):
        inv, cur = invoked_skill(rs), skill_of(rs[0])
        if inv and cur and cur != inv:
            same_turn += 1
            assert prompts_before(recs, rs[0]) == prompts_before(recs, calls[i - 1][1][0])
            assert skill_of(calls[i - 1][1][0]) == cur
            assert skill_of(calls[i + 1][1][0]) == inv
    assert same_turn == 1


def test_b_replacement_across_a_real_prompt_leaves_invoking_call_unattributed():
    recs = load("two_skills")["main"]["sess-b"]
    calls = ordered_calls(recs)
    found = False
    for i, (_, rs) in enumerate(calls):
        if invoked_skill(rs) == "skill-two" and skill_of(rs[0]) is None:
            found = True
            assert prompts_before(recs, rs[0]) > prompts_before(recs, calls[i - 1][1][0])
            assert skill_of(calls[i + 1][1][0]) == "skill-two"
    assert found


# ----------------------------------------------------------------- subagents


def agent_tool_uses(records: list[dict]) -> list[tuple[dict, dict]]:
    out = []
    for r in assistants(records):
        for b in blocks(r):
            if b.get("type") == "tool_use" and b.get("name") == "Agent":
                out.append((r, b))
    return out


def test_c_subagents_link_to_exactly_one_parent_agent_tool_use():
    fx = load("two_subagents")
    parent = fx["main"]["sess-c"]
    uses = agent_tool_uses(parent)
    assert len(fx["subs"]) == 2 and len(uses) == 2
    for meta, recs, _ in fx["subs"]:
        matches = [(r, b) for r, b in uses if b["id"] == meta["toolUseId"]]
        assert len(matches) == 1
        holder, use = matches[0]
        results = [
            r
            for r in parent
            if r.get("type") == "user"
            and isinstance(r["message"]["content"], list)
            and any(
                b.get("type") == "tool_result" and b["tool_use_id"] == use["id"]
                for b in r["message"]["content"]
            )
        ]
        assert len(results) == 1
        res = results[0]
        assert res["toolUseResult"]["agentId"] == recs[0]["agentId"]
        assert res["sourceToolAssistantUUID"] == holder["uuid"]
        assert use["input"]["subagent_type"] == meta["agentType"]


def test_c_agent_type_model_and_record_shape():
    fx = load("two_subagents")
    parent_recs = fx["main"]["sess-c"]
    types, models = set(), set()
    for meta, recs, _ in fx["subs"]:
        assert meta["spawnDepth"] == 1
        assert recs[0]["parentUuid"] is None
        assert all(r["agentId"] == recs[0]["agentId"] for r in recs)
        assert all(r["isSidechain"] is True for r in recs)
        for r in assistants(recs):
            assert r["attributionAgent"] == meta["agentType"]
            assert meta["model"] in r["message"]["model"]
        assert len({r["message"]["model"] for r in assistants(recs)}) == 1
        types.add(meta["agentType"])
        models.add(assistants(recs)[0]["message"]["model"])
    assert len(types) == 2 and len(models) == 2
    for r in parent_recs:
        assert "attributionAgent" not in r
        assert "agentId" not in r


def test_c_one_subagent_carries_skill_attribution_without_a_skill_call():
    fx = load("two_subagents")
    flagged = []
    for meta, recs, _ in fx["subs"]:
        if any("attributionSkill" in r for r in recs):
            assert invoked_skill(assistants(recs)) is None
            flagged.append(meta["agentType"])
    assert len(flagged) == 1


# --------------------------------------------------------------- oracle/dedup


@pytest.mark.parametrize("name", NAMES)
def test_dedup_matches_expected_json(name):
    got = dedupe(load(name))
    want = EXPECTED[name]
    assert len(got) == want["call_count"]
    assert got == want["calls"]


# ------------------------------------------------------------------- hygiene


def test_no_fixture_file_contains_a_home_path():
    files = [p for p in ROOT.rglob("*") if p.is_file()]
    assert files
    for p in files:
        assert "/Users/" not in p.read_text(), p
