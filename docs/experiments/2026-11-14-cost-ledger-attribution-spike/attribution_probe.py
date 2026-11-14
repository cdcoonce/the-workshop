#!/usr/bin/env python3
"""Structural probe of Claude Code transcripts: attribution fields, subagent linkage,
api-request records, attachments, compaction. Read-only. Prints a JSON summary of counts.
No prompt text, paths, project names or session ids are ever emitted.

Usage: python3 -I attribution_probe.py <projects_dir> [--min-version 2.1.293]
           [--max-main 60] [--max-sub 120] [--fixtures]
           [--exclude-session SESSION_ID ...]

--exclude-session may be repeated; any file whose path contains an excluded
session id is skipped (use it to leave out the session that runs the probe).
"""
import json
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

LIVE_SECS = 30 * 60
MAX_BYTES = 80_000_000


def vtuple(v):
    try:
        return tuple(int(x) for x in str(v).split("."))
    except Exception:
        return (0,)


def load(path):
    recs = []
    with path.open(errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            if isinstance(r, dict):
                recs.append(r)
    return recs


def modal_version(recs):
    c = Counter(r.get("version") for r in recs if r.get("version"))
    return c.most_common(1)[0][0] if c else None


def blocks(r):
    m = r.get("message")
    if isinstance(m, dict) and isinstance(m.get("content"), list):
        return [b for b in m["content"] if isinstance(b, dict)]
    return []


def tool_uses(r, name=None):
    if r.get("type") != "assistant":
        return []
    return [b for b in blocks(r) if b.get("type") == "tool_use" and (name is None or b.get("name") in name)]


def is_real_user_prompt(r):
    if r.get("type") != "user" or r.get("isMeta") or r.get("isCompactSummary"):
        return False
    m = r.get("message") or {}
    c = m.get("content")
    if isinstance(c, str):
        return True
    if isinstance(c, list):
        return any(isinstance(b, dict) and b.get("type") == "text" for b in c) and not any(
            isinstance(b, dict) and b.get("type") == "tool_result" for b in c
        )
    return False


def is_compaction(r):
    if r.get("type") == "system" and "compact" in str(r.get("subtype", "")):
        return True
    return bool(r.get("isCompactSummary"))


def api_calls(recs):
    """Dedup assistant records into API calls by (message.id, requestId)."""
    calls, index = [], {}
    for i, r in enumerate(recs):
        if r.get("type") != "assistant":
            continue
        m = r.get("message") or {}
        key = (m.get("id"), r.get("requestId"))
        if key not in index:
            index[key] = len(calls)
            calls.append({"first": i, "last": i, "recs": [i], "skills": [], "plugins": [], "tools": [],
                          "servers": [], "has_skill_use": False, "usage": [], "model": m.get("model")})
        c = calls[index[key]]
        c["last"] = i
        c["recs"].append(i)
        for k, store in (("attributionSkill", "skills"), ("attributionPlugin", "plugins"),
                         ("attributionMcpTool", "tools"), ("attributionMcpServer", "servers")):
            if k in r:
                c[store].append(r[k])
        if tool_uses(r, {"Skill"}):
            c["has_skill_use"] = True
        if isinstance(m.get("usage"), dict):
            c["usage"].append(m["usage"])
    for c in calls:
        c["attr"] = c["skills"][0] if c["skills"] else None
        c["attr_consistent"] = len(set(map(str, c["skills"]))) <= 1
    return calls


def norm_match(attr, skill):
    if attr is None or skill is None:
        return None
    if attr == skill:
        return "exact"
    if isinstance(attr, str) and isinstance(skill, str):
        if attr.endswith(":" + skill) or skill.endswith(":" + attr):
            return "qualified_vs_bare"
    return None


def dist(xs):
    if not xs:
        return None
    return {"n": len(xs), "min": min(xs), "median": statistics.median(xs), "max": max(xs),
            "mean": round(statistics.mean(xs), 2)}


def skeleton(v, depth=0):
    """Redacted structure: keys and value types only."""
    if isinstance(v, dict):
        if depth > 3:
            return "<dict>"
        return {("<tool_use_id>" if isinstance(k, str) and k.startswith("toolu_") else k): skeleton(x, depth + 1)
                for k, x in v.items()}
    if isinstance(v, list):
        return [skeleton(v[0], depth + 1), "...(%d items)" % len(v)] if v else []
    if isinstance(v, bool):
        return "<bool>"
    if isinstance(v, int):
        return "<int>"
    if isinstance(v, float):
        return "<float>"
    if v is None:
        return None
    return "<str>"


def walk_attr_keys(o, path, out, depth=0):
    if depth > 6:
        return
    if isinstance(o, dict):
        for k, v in o.items():
            if isinstance(k, str) and k.startswith("attribution"):
                out[path + "." + k] += 1
            walk_attr_keys(v, path + "." + k if depth < 2 else path + ".*", out, depth + 1)
    elif isinstance(o, list):
        for v in o[:50]:
            walk_attr_keys(v, path + "[]", out, depth + 1)


def main():
    args = sys.argv[1:]
    if not args or "-h" in args or "--help" in args:
        print(__doc__)
        sys.exit(0 if args else 1)
    excluded = []
    while "--exclude-session" in args:
        i = args.index("--exclude-session")
        excluded.append(args[i + 1])
        del args[i : i + 2]
    root = Path(args[0]).expanduser()
    opt = {"--min-version": "2.1.293", "--max-main": "60", "--max-sub": "120"}
    fixtures = "--fixtures" in args
    for k in opt:
        if k in args:
            opt[k] = args[args.index(k) + 1]
    min_v = vtuple(opt["--min-version"])
    max_main, max_sub = int(opt["--max-main"]), int(opt["--max-sub"])
    now = time.time()

    def ok(p):
        try:
            st = p.stat()
        except OSError:
            return False
        return not any(e in str(p) for e in excluded) and now - st.st_mtime > LIVE_SECS and st.st_size < MAX_BYTES

    main_files = sorted((p for p in root.glob("*/*.jsonl") if ok(p)), key=lambda p: -p.stat().st_mtime)
    sub_files = sorted((p for p in root.glob("*/*/subagents/*.jsonl") if ok(p)), key=lambda p: -p.stat().st_mtime)
    out = {"population": {"main_files": len(main_files), "subagent_files": len(sub_files)}}

    # ---------- corpus-wide Q4 (attribution key counts by main/sub, on parsed records) ----------
    corpus = {"main": defaultdict(Counter), "sub": defaultdict(Counter)}
    ver_table = defaultdict(lambda: Counter())
    for kind, files in (("main", main_files), ("sub", sub_files)):
        for p in files:
            try:
                raw = p.read_text(errors="replace")
            except OSError:
                continue
            has_attr_text = "attribution" in raw  # file prefilter only; detection below is by parsed key
            for line in raw.splitlines():
                if kind == "main" and not has_attr_text:
                    # still need version table totals cheaply
                    pass
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if not isinstance(r, dict) or r.get("type") != "assistant":
                    continue
                v = r.get("version")
                ver_table[v]["assistant_records"] += 1
                for k in ("attributionSkill", "attributionPlugin", "attributionMcpTool", "attributionMcpServer",
                          "attributionAgent"):
                    if k in r:
                        ver_table[v][k] += 1
                        corpus[kind][k]["records"] += 1
                        val = r[k]
                        corpus[kind][k]["type_" + type(val).__name__] += 1
                        if isinstance(val, str):
                            if k == "attributionSkill":
                                corpus[kind][k]["qualified" if ":" in val else "bare"] += 1
                            if k == "attributionMcpTool":
                                corpus[kind][k]["prefixed_mcp__" if val.startswith("mcp__") else "no_mcp_prefix"] += 1
                            if k == "attributionPlugin":
                                corpus[kind][k]["val:" + val] += 1
    out["Q4_corpus_attribution_by_file_kind"] = {k: {kk: dict(vv) for kk, vv in v.items()} for k, v in corpus.items()}
    out["version_table_attribution_records"] = {
        str(v): dict(c) for v, c in sorted(ver_table.items(), key=lambda kv: vtuple(kv[0]))
        if c.get("attributionSkill") or c.get("attributionPlugin") or c.get("attributionMcpTool")}
    out["min_version_family_used"] = opt["--min-version"]

    # ---------- main sample ----------
    sample, sessions_scanned = [], 0
    for p in main_files:
        if len(sample) >= max_main:
            break
        try:
            raw = p.read_text(errors="replace")
        except OSError:
            continue
        if '"name":"Skill"' not in raw:  # selection prefilter only
            continue
        sessions_scanned += 1
        recs = []
        for line in raw.splitlines():
            try:
                r = json.loads(line)
            except Exception:
                continue
            if isinstance(r, dict):
                recs.append(r)
        v = modal_version(recs)
        if v is None or vtuple(v) < min_v:
            continue
        if not any(tool_uses(r, {"Skill"}) for r in recs):
            continue
        sample.append((p, recs, v))
    out["main_sample"] = {"sessions": len(sample), "versions": dict(Counter(v for _, _, v in sample))}

    runs_len, run_end, runs_user_prompts, invoker_attr = [], Counter(), [], Counter()
    skill_total, followed, fmt, match_kind, first_call_attr = 0, 0, Counter(), Counter(), Counter()
    any_within3 = 0
    skill_errors = 0
    second_skill = Counter()
    unprec = Counter()
    attributed_runs = 0
    sessions_with_zero_attr = 0
    skill_args_types = Counter()
    skill_by_ver = defaultdict(lambda: [0, 0])
    record_types_with_attr = Counter()
    attr_paths = Counter()
    attr_consistency = Counter()
    sessions_two_plus = 0
    for p, recs, ver in sample:
        calls = api_calls(recs)
        for c in calls:
            attr_consistency["consistent" if c["attr_consistent"] else "inconsistent_within_call"] += 1
        for r in recs:
            walk_attr_keys(r, r.get("type", "?"), attr_paths)
        # tool_result error lookup
        err_ids = set()
        for r in recs:
            if r.get("type") == "user":
                for b in blocks(r):
                    if b.get("type") == "tool_result" and b.get("is_error"):
                        err_ids.add(b.get("tool_use_id"))
        any_attr = any(c["attr"] for c in calls)
        if not any_attr:
            sessions_with_zero_attr += 1
        # skill calls
        skill_calls = []
        for ci, c in enumerate(calls):
            for ri in c["recs"]:
                for b in tool_uses(recs[ri], {"Skill"}):
                    inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                    skill_calls.append({"ci": ci, "id": b.get("id"), "skill": inp.get("skill"),
                                        "args_t": type(inp.get("args")).__name__, "ri": ri})
        for sc in skill_calls:
            skill_args_types[sc["args_t"]] += 1
            skill_total += 1
            ci = sc["ci"]
            cur = calls[ci]
            invoker_attr["invoking_call_attr_equals_skill" if norm_match(cur["attr"], sc["skill"]) else
                         ("invoking_call_attr_other" if cur["attr"] else "invoking_call_unattributed")] += 1
            if sc["id"] in err_ids:
                skill_errors += 1
            nxt = calls[ci + 1] if ci + 1 < len(calls) else None
            m = norm_match(nxt["attr"], sc["skill"]) if nxt else None
            first_call_attr["first_following_call_matches" if m else "first_following_call_no_match"] += 1
            if any(norm_match(calls[j]["attr"], sc["skill"]) for j in range(ci + 1, min(ci + 4, len(calls)))):
                any_within3 += 1
            if not m:
                skill_by_ver[ver][1] += 1
                continue
            skill_by_ver[ver][0] += 1
            followed += 1
            match_kind[m] += 1
            fmt["qualified" if ":" in nxt["attr"] else "bare"] += 1
            target = nxt["attr"]
            j, run = ci + 1, 0
            while j < len(calls) and calls[j]["attr"] == target:
                run += 1
                j += 1
            runs_len.append(run)
            lo = calls[j - 1]["last"] + 1
            hi = calls[j]["first"] if j < len(calls) else len(recs)
            between = recs[lo:hi]
            if j >= len(calls):
                ev = "end_of_session_or_no_later_call"
            elif any(is_compaction(x) for x in between):
                ev = "compaction"
            elif any(is_real_user_prompt(x) for x in between):
                ev = "next_real_user_prompt"
            elif calls[j - 1]["has_skill_use"] or any(tool_uses(x, {"Skill"}) for x in between):
                ev = "next_skill_call" if calls[j]["attr"] else "after_skill_call_then_unattributed"
            elif any(x.get("type") == "system" and x.get("subtype") == "stop_hook_summary" for x in between) or any(
                    x.get("type") == "user" and x.get("isMeta") for x in between):
                ev = "turn_boundary_stop_hook_and_or_queued_meta_user" if not calls[j]["attr"] else "turn_boundary_then_other_attr"
            elif calls[j]["attr"]:
                ev = "other_attr_change"
            else:
                ev = "vanished_no_visible_event"
            run_end[ev] += 1
            inside = recs[calls[ci + 1]["first"]:calls[j - 1]["last"] + 1]
            runs_user_prompts.append(sum(1 for x in inside if is_real_user_prompt(x)))
        # Q2: second skill
        if len(skill_calls) >= 2:
            sessions_two_plus += 1
            for a, b in zip(skill_calls, skill_calls[1:]):
                if a["skill"] == b["skill"]:
                    second_skill["same_skill_reinvoked"] += 1
                    continue
                nxt = calls[b["ci"] + 1] if b["ci"] + 1 < len(calls) else None
                if nxt is None or nxt["attr"] is None:
                    second_skill["next_call_unattributed"] += 1
                elif norm_match(nxt["attr"], b["skill"]):
                    second_skill["replaced_by_second"] += 1
                elif norm_match(nxt["attr"], a["skill"]):
                    second_skill["first_persists_second_ignored"] += 1
                else:
                    second_skill["other_value"] += 1
        # attributed runs w/o a preceding Skill tool call
        prev_skills = []
        for ci, c in enumerate(calls):
            for ri in c["recs"]:
                for b in tool_uses(recs[ri], {"Skill"}):
                    prev_skills.append((ci, (b.get("input") or {}).get("skill")))
            a = c["attr"]
            if a is not None and (ci == 0 or calls[ci - 1]["attr"] != a):
                attributed_runs += 1
                if any(cj < ci and norm_match(a, s) for cj, s in prev_skills):
                    unprec["run_has_preceding_Skill_call"] += 1
                else:
                    # look at records just before run start for slash command user record / invoked_skills attachment
                    back = recs[max(0, c["first"] - 40):c["first"]]
                    kind = "no_trigger_found"
                    if ci == 0 or all(calls[cj]["attr"] is None for cj in range(ci)):
                        kind = "no_trigger_found(first_attributed_in_file)"
                    for x in back:
                        if x.get("type") == "attachment" and (x.get("attachment") or {}).get("type") == "invoked_skills":
                            kind = "invoked_skills_attachment"
                        if x.get("type") == "user":
                            cc = (x.get("message") or {}).get("content")
                            txt = cc if isinstance(cc, str) else " ".join(
                                b.get("text", "") for b in blocks(x) if b.get("type") == "text")
                            if txt.lstrip().startswith("<command-name>") or "<command-message>" in txt[:200]:
                                kind = "slash_command_user_record"
                            elif x.get("isMeta") and kind.startswith("no_trigger"):
                                kind = "meta_user_skill_body_without_cmd_record_nearby"
                    unprec["run_WITHOUT_preceding_Skill_call:" + kind] += 1
        for r in recs:
            if r.get("type") == "assistant":
                for k in ("attributionSkill", "attributionPlugin", "attributionMcpTool", "attributionMcpServer"):
                    if k in r:
                        record_types_with_attr[("assistant", k)] += 1

    out["Q1_Q3_main_sample"] = {
        "skill_calls": skill_total,
        "sessions_with_zero_attributed_records": sessions_with_zero_attr,
        "attr_paths_structural": dict(attr_paths),
        "attr_call_consistency": dict(attr_consistency),
        "invoking_call_attribution": dict(invoker_attr),
        "first_following_call": dict(first_call_attr),
        "any_of_next_3_calls_matches": any_within3,
        "followed_by_attributed_call": followed,
        "followed_share": round(followed / skill_total, 3) if skill_total else None,
        "value_format_when_followed": dict(fmt),
        "match_vs_skill_input": dict(match_kind),
        "skill_tool_result_errors": skill_errors,
        "skill_input_args_type": dict(skill_args_types),
        "followed_by_version": {k: {"followed": v[0], "not": v[1]} for k, v in sorted(skill_by_ver.items(), key=lambda kv: vtuple(kv[0]))},
        "run_length_calls_after_invoking_call": dist(runs_len),
        "run_length_histogram_capped": dict(Counter(min(x, 20) for x in runs_len)),
        "run_end_event": dict(run_end),
        "real_user_prompts_inside_runs": dist(runs_user_prompts),
        "runs_spanning_>=1_user_prompt": sum(1 for x in runs_user_prompts if x > 0),
        "Q2_sessions_with_2plus_skill_calls": sessions_two_plus,
        "Q2_second_skill_outcome": dict(second_skill),
        "attributed_runs_total": attributed_runs,
        "attributed_runs_trigger": dict(unprec),
    }

    # ---------- Q4 within sample, recursive ----------
    # (attr_paths above)

    # ---------- subagents ----------
    def first_version(p):
        try:
            with p.open(errors="replace") as fh:
                for line in fh:
                    r = json.loads(line)
                    if r.get("version"):
                        return r["version"]
        except Exception:
            pass
        return None
    elig_subs = [p for p in sub_files if vtuple(first_version(p)) >= min_v]
    out["population"]["subagent_files_in_version_family"] = len(elig_subs)
    stride = max(1, len(elig_subs) // max_sub)
    cand = elig_subs[::stride]
    parent_cache = {}
    sub_stats = Counter()
    meta_keys = Counter()
    meta_types = defaultdict(Counter)
    link = Counter()
    model_cmp = Counter()
    type_cmp = Counter()
    sub_models = Counter()
    req_models = Counter()
    meta_models = Counter()
    sub_attr = Counter()
    agent_attr_vals = Counter()
    agent_attr_vs_meta = Counter()
    sub_skill_attr_without_call = 0
    model_mix = Counter()
    sub_user_prompts = []
    sub_finished = Counter()
    sub_query_src = Counter()
    sub_skill_calls = 0
    sub_first_keys = Counter()
    sub_parent_null_count = []
    sub_prefix_exists = 0
    sub_sample = 0
    spawn_depth = Counter()
    parent_two_types = None
    parent_agent_children = defaultdict(list)
    sub_att = Counter()
    sub_api = Counter()
    for sp in cand:
        recs = load(sp)
        if not recs:
            continue
        v = modal_version(recs)
        if v is None or vtuple(v) < min_v:
            continue
        sub_sample += 1
        sub_stats["sampled"] += 1
        meta_p = sp.with_suffix(".meta.json")
        meta = None
        if meta_p.exists():
            try:
                meta = json.loads(meta_p.read_text())
            except Exception:
                meta = None
        if meta is None:
            sub_stats["no_meta"] += 1
        else:
            meta_keys.update(meta.keys())
            for k, val in meta.items():
                meta_types[k][type(val).__name__] += 1
            if "model" in meta:
                meta_models[str(meta["model"])] += 1
            if "spawnDepth" in meta:
                spawn_depth[meta["spawnDepth"]] += 1
        if sp.with_suffix(".prefix.json").exists():
            sub_prefix_exists += 1
        sub_first_keys.update(recs[0].keys())
        sub_user_prompts.append(sum(1 for r in recs if is_real_user_prompt(r)))
        if meta is not None:
            sub_finished[str(meta.get("finished"))] += 1
        ag_vals = {r["attributionAgent"] for r in recs if r.get("type") == "assistant" and "attributionAgent" in r}
        for av in ag_vals:
            agent_attr_vals[av] += 1
        if meta and ag_vals:
            agent_attr_vs_meta["attributionAgent==meta.agentType" if ag_vals == {meta.get("agentType")} else
                               "attributionAgent_differs_from_meta.agentType"] += 1
        models_here = {str((r.get("message") or {}).get("model")) for r in recs if r.get("type") == "assistant"}
        model_mix["single_model" if len(models_here) == 1 else "mixed_models_in_one_subagent_file"] += 1
        has_skill_call = any(tool_uses(r, {"Skill"}) for r in recs)
        if any("attributionSkill" in r for r in recs) and not has_skill_call:
            sub_skill_attr_without_call += 1
        for r in recs:
            if str(r.get("type", "")).startswith("api-request") and r.get("querySource"):
                sub_query_src[str(r.get("querySource"))] += 1
        nulls = sum(1 for r in recs if r.get("parentUuid") is None and r.get("type") in ("user", "assistant"))
        sub_parent_null_count.append(nulls)
        agent_ids = {r.get("agentId") for r in recs if r.get("agentId")}
        link["agentId_on_records_single_value" if len(agent_ids) == 1 else "agentId_other:%d" % len(agent_ids)] += 1
        link["isSidechain_all_true" if all(r.get("isSidechain") for r in recs if r.get("type") in ("user", "assistant")) else "isSidechain_mixed"] += 1
        for r in recs:
            if r.get("type") == "assistant":
                m = r.get("message") or {}
                sub_models[str(m.get("model"))] += 1
                for k in ("attributionSkill", "attributionPlugin", "attributionMcpTool", "attributionMcpServer", "attributionAgent"):
                    if k in r:
                        sub_attr[k] += 1
                sub_skill_calls += len(tool_uses(r, {"Skill"}))
            elif r.get("type") == "attachment":
                sub_att[(r.get("attachment") or {}).get("type")] += 1
            elif str(r.get("type", "")).startswith("api-request"):
                sub_api[r["type"]] += 1
            for k in r:
                if "source" in k.lower() or "parent" in k.lower() or k in ("toolUseId", "toolUseID"):
                    link["subagent_record_key:" + k] += 1
        # parent
        sid_dir = sp.parent.parent
        parent_path = sid_dir.parent / (sid_dir.name + ".jsonl")
        sub_agent_id = next(iter(agent_ids), None)
        if not parent_path.exists():
            link["parent_file_missing"] += 1
            continue
        if parent_path not in parent_cache:
            precs = load(parent_path)
            agent_calls = {}
            results = {}
            for i, r in enumerate(precs):
                for b in tool_uses(r, {"Agent", "Task"}):
                    agent_calls[b.get("id")] = {"input": b.get("input") if isinstance(b.get("input"), dict) else {},
                                                "uuid": r.get("uuid"), "rec_i": i}
                if r.get("type") == "user":
                    tur = r.get("toolUseResult")
                    for b in blocks(r):
                        if b.get("type") == "tool_result":
                            results[b.get("tool_use_id")] = {
                                "tur_type": type(tur).__name__,
                                "tur_keys": sorted(tur.keys()) if isinstance(tur, dict) else None,
                                "tur_agentId": tur.get("agentId") if isinstance(tur, dict) else None,
                                "src_assistant_uuid": r.get("sourceToolAssistantUUID"),
                                "parent_uuid": r.get("parentUuid"),
                            }
            parent_cache[parent_path] = (agent_calls, results)
        agent_calls, results = parent_cache[parent_path]
        tuid = meta.get("toolUseId") if meta else None
        if tuid and tuid in agent_calls:
            link["RESOLVED_meta.toolUseId==parent Agent tool_use.id"] += 1
            ac = agent_calls[tuid]
            inp = ac["input"]
            link["agent_call_input_keys:" + ",".join(sorted(inp.keys()))] += 0
            for k in inp:
                link["agent_input_key:" + k] += 1
            parent_agent_children[parent_path].append((meta.get("agentType"), tuid))
            res = results.get(tuid)
            if res:
                link["parent_tool_result_found"] += 1
                if res["tur_keys"] is not None:
                    for k in res["tur_keys"]:
                        link["toolUseResult_key:" + k] += 1
                if res["tur_agentId"] and res["tur_agentId"] == sub_agent_id:
                    link["toolUseResult.agentId==subagent agentId"] += 1
                if res["src_assistant_uuid"] == ac["uuid"]:
                    link["tool_result.sourceToolAssistantUUID==Agent assistant uuid"] += 1
            # type & model comparisons
            req_type = inp.get("subagent_type")
            type_cmp["meta.agentType==input.subagent_type" if meta.get("agentType") == req_type else
                     "type_differs_or_input_missing(%s)" % ("input_missing" if req_type is None else "differs")] += 1
            rm = inp.get("model")
            req_models[str(rm)] += 1
            actual = Counter(str((r.get("message") or {}).get("model")) for r in recs if r.get("type") == "assistant")
            top = actual.most_common(1)[0][0] if actual else None
            if rm is None:
                model_cmp["no_model_requested_in_call"] += 1
            elif top and str(rm).lower() in top.lower():
                model_cmp["requested_alias_is_substring_of_top_actual_model"] += 1
                if len(actual) > 1:
                    model_cmp["...but_file_also_has_other_models"] += 1
            else:
                model_cmp["requested_model_not_in_actual(%s->%s)" % (rm, top)] += 1
            if meta.get("model") and top:
                model_cmp["meta.model_alias_in_actual" if str(meta["model"]).lower() in top.lower() else "meta.model_alias_NOT_in_actual"] += 1
        else:
            link["unresolved_by_meta.toolUseId"] += 1
            # fallback: any parent tool_result carrying agentId
            hit = [t for t, res in results.items() if res["tur_agentId"] and res["tur_agentId"] == sub_agent_id]
            link["fallback_resolved_by_toolUseResult.agentId" if hit else "fallback_unresolved"] += 1

    out["Q5_subagents"] = {
        "sampled": sub_sample,
        "stats": dict(sub_stats),
        "meta_keys": dict(meta_keys),
        "meta_value_types": {k: dict(v) for k, v in meta_types.items()},
        "meta_model_values": dict(meta_models),
        "spawnDepth_values": dict(spawn_depth),
        "prefix_json_present": sub_prefix_exists,
        "link": {k: v for k, v in link.items() if v},
        "type_comparison": dict(type_cmp),
        "model_comparison": dict(model_cmp),
        "requested_model_values": dict(req_models),
        "actual_models_on_subagent_assistant_records": dict(sub_models),
        "subagent_first_record_keys": dict(sub_first_keys),
        "records_with_null_parentUuid_per_file": dist(sub_parent_null_count),
        "attribution_keys_in_subagent_files_sample": dict(sub_attr),
        "attributionAgent_values_files": dict(agent_attr_vals),
        "attributionAgent_vs_meta": dict(agent_attr_vs_meta),
        "subagent_files_with_attributionSkill_but_no_Skill_call": sub_skill_attr_without_call,
        "model_mix_per_file": dict(model_mix),
        "real_user_prompts_per_subagent_file": dist(sub_user_prompts),
        "meta_finished_values": dict(sub_finished),
        "api_request_querySource_in_subagents": dict(sub_query_src),
        "skill_calls_in_subagents_sample": sub_skill_calls,
        "attachment_subtypes_in_subagents_sample": dict(sub_att),
        "api_request_types_in_subagents_sample": dict(sub_api),
    }
    out["Q5_parents_with_multiple_subagent_types"] = sum(
        1 for ch in parent_agent_children.values() if len({t for t, _ in ch}) >= 2)

    # ---------- Q6 / Q7 / Q8 over a broader sample ----------
    q6 = Counter()
    q6_keys = defaultdict(Counter)
    q6_sizes = defaultdict(list)
    query_sources = Counter()
    shape_sys_len, shape_tools_len = [], []
    api_id_match = Counter()
    att_types, att_sizes, att_primary = Counter(), defaultdict(list), defaultdict(Counter)
    att_main_sub = {"main": Counter(), "sub": Counter()}
    sys_sub = Counter()
    rec_keys_sub = Counter()
    resume = Counter()
    usage_keys, usage_dup = Counter(), Counter()
    cost_state_n = 0
    cost_state_keys = Counter()
    first_sid_mismatch = 0
    files_scanned = 0
    last_prompt_n = 0
    top_types = {"main": Counter(), "sub": Counter()}
    broad = [(p, "main") for p in [s[0] for s in sample]] + [(p, "sub") for p in cand[:max_sub]]
    seen_uuid = defaultdict(set)
    dup_uuid_across = 0
    for p, kind in broad:
        recs = load(p)
        files_scanned += 1
        if not recs:
            continue
        if kind == "main":
            sids = {r.get("sessionId") for r in recs if r.get("sessionId")}
            if len(sids) > 1:
                resume["main_file_with_multiple_sessionIds"] += 1
            if sids and p.stem not in sids:
                first_sid_mismatch += 1
            for r in recs:
                u = r.get("uuid")
                if u:
                    if u in seen_uuid and False:
                        pass
        reqids = {r.get("requestId") for r in recs if r.get("type") == "assistant"}
        msgids = {(r.get("message") or {}).get("id") for r in recs if r.get("type") == "assistant"}
        uuids = {r.get("uuid") for r in recs}
        for r in recs:
            t = r.get("type")
            top_types[kind][t] += 1
            if t in ("api-request", "api-request-shape", "api-request-blob"):
                q6[(kind, t)] += 1
                q6_keys[t].update(r.keys())
                if t == "api-request":
                    query_sources[str(r.get("querySource"))] += 1
                    api_id_match["id_in_assistant_requestIds" if r.get("id") in reqids else "id_not_in_requestIds"] += 1
                    api_id_match["id_in_assistant_message_ids" if r.get("id") in msgids else "id_not_in_message_ids"] += 1
                    api_id_match["id_in_record_uuids" if r.get("id") in uuids else "id_not_in_uuids"] += 1
                    q6_keys["api-request.params"].update((r.get("params") or {}).keys())
                    for k in r:
                        if isinstance(r[k], (int, float)) and not isinstance(r[k], bool):
                            q6_keys["api-request.numeric_fields"][k] += 1
                if t == "api-request-shape":
                    sh = r.get("shape") or {}
                    if isinstance(sh.get("system"), list):
                        shape_sys_len.append(len(json.dumps(sh["system"])))
                    if isinstance(sh.get("tools"), list):
                        shape_tools_len.append(len(json.dumps(sh["tools"])))
                    q6_keys["shape.system_block_keys"].update(k for b in sh.get("system", []) if isinstance(b, dict) for k in b)
                    q6_keys["shape.tool_item_keys"].update(k for b in sh.get("tools", []) if isinstance(b, dict) for k in b)
                if t == "api-request-blob":
                    q6_sizes["blob_chars"].append(len(json.dumps(r.get("message"))))
            elif t == "attachment":
                a = r.get("attachment") or {}
                st = a.get("type")
                att_types[st] += 1
                att_main_sub[kind][st] += 1
                sizes = {k: (len(v) if isinstance(v, str) else len(json.dumps(v))) for k, v in a.items() if k != "type"}
                tot = sum(sizes.values())
                att_sizes[st].append(tot)
                if sizes:
                    att_primary[st][max(sizes, key=sizes.get)] += 1
            elif t == "system":
                sys_sub[(kind, r.get("subtype"))] += 1
            if t == "assistant":
                u = (r.get("message") or {}).get("usage")
                if isinstance(u, dict):
                    usage_keys.update(u.keys())
            if t == "cost-state":
                cost_state_n += 1
                cost_state_keys.update(r.keys())
            if t == "last-prompt":
                last_prompt_n += 1
            if r.get("isCompactSummary"):
                resume["user_record_isCompactSummary"] += 1
            if r.get("type") == "user" and r.get("isSidechain") and kind == "main":
                resume["main_file_isSidechain_true_records"] += 1
            if r.get("isApiErrorMessage"):
                resume["isApiErrorMessage"] += 1
            if r.get("isVisibleInTranscriptOnly"):
                resume["isVisibleInTranscriptOnly"] += 1
        # usage variation within calls
        for c in api_calls(recs):
            if len(c["usage"]) > 1:
                usage_dup["calls_with_multiple_records"] += 1
                outs = [u.get("output_tokens") for u in c["usage"]]
                if len({json.dumps(u, sort_keys=True) for u in c["usage"]}) == 1:
                    usage_dup["usage_identical_across_records"] += 1
                elif outs[-1] == max(x for x in outs if isinstance(x, int)):
                    usage_dup["last_record_has_max_output_tokens"] += 1
                else:
                    usage_dup["usage_differs_last_not_max"] += 1
            else:
                usage_dup["single_record_calls"] += 1

    out["Q6_api_request_records"] = {
        "counts_by_kind_type": {"%s:%s" % k: v for k, v in q6.items()},
        "top_level_keys": {t: dict(c) for t, c in q6_keys.items()},
        "querySource_values": dict(query_sources),
        "api_request_id_vs_assistant_requestId": dict(api_id_match),
        "shape_system_chars_serialized": dist(shape_sys_len),
        "shape_tools_chars_serialized": dist(shape_tools_len),
        "blob_chars_serialized": dist(q6_sizes["blob_chars"]),
        "note": "no per-request size fields; sizes must be derived by serializing shape/blobs",
    }
    out["Q7_attachments"] = {
        "subtype_field": "attachment.type",
        "counts": dict(att_types.most_common()),
        "main_vs_sub": {k: dict(v) for k, v in att_main_sub.items()},
        "median_chars_non_type_fields": {k: statistics.median(v) for k, v in att_sizes.items()},
        "primary_content_field": {k: dict(v) for k, v in att_primary.items()},
    }
    out["Q8_misc"] = {
        "files_scanned_broad": files_scanned,
        "top_level_types": {k: dict(v) for k, v in top_types.items()},
        "system_subtypes": {"%s:%s" % k: v for k, v in sys_sub.items()},
        "resume_flags": dict(resume),
        "main_filename_not_in_sessionIds": first_sid_mismatch,
        "usage_keys": dict(usage_keys),
        "usage_across_records_of_one_call": dict(usage_dup),
        "cost_state_records": cost_state_n,
        "cost_state_keys": dict(cost_state_keys),
        "last_prompt_records": last_prompt_n,
    }

    # ---------- compaction analysis (all main files in version family containing a compact_boundary) ----------
    comp = Counter()
    comp_sys_keys = Counter()
    for p in main_files:
        try:
            raw = p.read_text(errors="replace")
        except OSError:
            continue
        if "compact_boundary" not in raw:  # selection prefilter only
            continue
        recs = []
        for line in raw.splitlines():
            try:
                r = json.loads(line)
            except Exception:
                continue
            if isinstance(r, dict):
                recs.append(r)
        v = modal_version(recs)
        if v is None or vtuple(v) < min_v:
            continue
        calls = api_calls(recs)
        for bi, r in enumerate(recs):
            if r.get("type") == "system" and r.get("subtype") == "compact_boundary":
                comp["boundaries"] += 1
                comp_sys_keys.update(r.keys())
                before = [c for c in calls if c["last"] < bi]
                after = [c for c in calls if c["first"] > bi]
                if before and after:
                    b, a = before[-1]["attr"], after[0]["attr"]
                    comp["before_attributed" if b else "before_unattributed"] += 1
                    comp["after_attributed" if a else "after_unattributed"] += 1
                    if b and a:
                        comp["same_skill_before_and_after" if a == b else "different_skill_after"] += 1
                    if b and not a:
                        comp["attribution_dropped_across_compaction"] += 1
                    if a and not b:
                        comp["attribution_appears_after_compaction"] += 1
                near = recs[bi:bi + 40]
                if any(x.get("type") == "attachment" and (x.get("attachment") or {}).get("type") == "invoked_skills" for x in near):
                    comp["invoked_skills_attachment_within_40_records_after"] += 1
                if any(x.get("isCompactSummary") for x in near):
                    comp["isCompactSummary_user_record_follows"] += 1
    out["Q8_compaction"] = dict(comp)
    out["Q8_compact_boundary_keys"] = dict(comp_sys_keys)

    # resume / fork: do main files in the same project share uuids?
    uu = defaultdict(list)
    for p, recs, v in sample:
        for r in recs:
            if r.get("uuid") and r.get("type") in ("user", "assistant"):
                uu[r["uuid"]].append(p)
    callfiles = defaultdict(set)
    for p, recs, v in sample:
        for r in recs:
            if r.get("type") == "assistant":
                callfiles[((r.get("message") or {}).get("id"), r.get("requestId"))].add(p)
    out["Q8_api_calls_sampled_main"] = {"distinct": len(callfiles),
                                         "present_in_2plus_files": sum(1 for ps in callfiles.values() if len(ps) > 1)}
    out["Q8_uuid_shared_across_sampled_main_files"] = sum(1 for ps in uu.values() if len(set(ps)) > 1)

    # ---------- fixture skeletons (redacted) ----------
    if fixtures:
        fx = {}
        SKIP = ("last-prompt", "custom-title", "queue-operation", "agent-name", "bridge-session", "atis-latch",
                "pr-link", "mode", "file-history-snapshot", "api-request", "api-request-blob", "api-request-shape",
                "relocated", "cost-state")

        def seq(recs, lo, hi, labels):
            """Compact redacted event sequence: types, block kinds, relabelled attribution and call ids."""
            res, callno = [], {}
            for r in recs[lo:hi + 1]:
                t = r.get("type")
                if t in SKIP:
                    continue
                e = {"type": t}
                if t == "attachment":
                    e["attachment.type"] = (r.get("attachment") or {}).get("type")
                if t == "system":
                    e["subtype"] = r.get("subtype")
                if r.get("isMeta"):
                    e["isMeta"] = True
                if t == "assistant":
                    m = r.get("message") or {}
                    k = (m.get("id"), r.get("requestId"))
                    e["call"] = callno.setdefault(k, "call%d" % (len(callno) + 1))
                    e["blocks"] = [("tool_use:%s" % b.get("name") if b.get("type") == "tool_use" else b.get("type")) for b in blocks(r)]
                    for ak in ("attributionSkill", "attributionPlugin"):
                        if ak in r:
                            e[ak] = "<skill:%s>" % labels.setdefault(r[ak], "S%d" % (len(labels) + 1)) if ak == "attributionSkill" else "<plugin>"
                    if tool_uses(r, {"Skill"}):
                        e["Skill.input.skill"] = "<skill:%s>" % labels.setdefault(tool_uses(r, {"Skill"})[0]["input"].get("skill"), "S%d" % (len(labels) + 1))
                if t == "user":
                    c = (r.get("message") or {}).get("content")
                    e["content"] = "<str>" if isinstance(c, str) else [b.get("type") for b in blocks(r)]
                res.append(e)
            return res
        full = {}
        best_a = best_b = None
        for p, recs, v in sample:
            calls = api_calls(recs)
            sk = [(ci, (b.get("input") or {}).get("skill")) for ci, c in enumerate(calls)
                  for ri in c["recs"] for b in tool_uses(recs[ri], {"Skill"})]
            if not sk:
                continue
            ci = sk[0][0]
            if best_a is None and ci + 1 < len(calls) and calls[ci + 1]["attr"]:
                end = next((j for j in range(ci + 1, len(calls)) if calls[j]["attr"] is None), None)
                if end and end - ci <= 4:
                    best_a = (recs, calls[ci]["first"], calls[end]["last"])
                    for r in recs[calls[ci + 1]["first"]:calls[end]["first"]]:
                        if r.get("type") == "assistant" and "attributionSkill" in r and "attributed_assistant" not in full:
                            full["attributed_assistant"] = skeleton(r)
                        if r.get("type") == "user" and isinstance(((r.get("message") or {}).get("content")), list) and "tool_result_user" not in full:
                            full["tool_result_user"] = skeleton(r)
                        if r.get("type") == "user" and r.get("isMeta") and "meta_user" not in full:
                            full["meta_user"] = skeleton(r)
            if best_b is None:
                for (c1, s1), (c2, s2) in zip(sk, sk[1:]):
                    if s1 != s2 and c2 - c1 <= 8 and c2 + 1 < len(calls):
                        best_b = (recs, calls[c1]["first"], calls[c2 + 1]["last"])
                        break
        fx["full_record_skeletons"] = full
        fx["a_skill_then_attributed_then_unattributed"] = seq(*best_a, {}) if best_a else None
        fx["b_two_skills"] = seq(*best_b, {}) if best_b else None
        # (c)
        for pp, ch in parent_agent_children.items():
            if len({t for t, _ in ch}) >= 2:
                agent_calls, results = parent_cache[pp]
                tus = []
                seen_t = set()
                for t, tuid in ch:
                    if t not in seen_t:
                        seen_t.add(t)
                        tus.append(tuid)
                    if len(tus) == 2:
                        break
                subs = []
                for tuid in tus:
                    for sp in cand:
                        mp = sp.with_suffix(".meta.json")
                        if mp.exists() and sp.parent.parent == pp.parent / pp.stem:
                            try:
                                md = json.loads(mp.read_text())
                            except Exception:
                                continue
                            if md.get("toolUseId") == tuid:
                                srecs = load(sp)
                                subs.append({"meta.json": skeleton(md),
                                             "first_records": [skeleton({k: v for k, v in r.items() if k != "message"})
                                                               for r in srecs[:2]]})
                                break
                precs = load(pp)
                parent_recs = []
                for r in precs:
                    for b in tool_uses(r, {"Agent", "Task"}):
                        if b.get("id") in tus:
                            parent_recs.append({"assistant_record": skeleton({k: v for k, v in r.items() if k != "message"}),
                                                "tool_use": {"type": "tool_use", "id": "<str>", "name": b.get("name"),
                                                             "input": skeleton(b.get("input"))}})
                    if r.get("type") == "user":
                        for b in blocks(r):
                            if b.get("type") == "tool_result" and b.get("tool_use_id") in tus:
                                parent_recs.append({"user_record": skeleton({k: v for k, v in r.items() if k != "message"}),
                                                    "toolUseResult_keys": sorted((r.get("toolUseResult") or {}).keys())
                                                    if isinstance(r.get("toolUseResult"), dict) else None})
                fx["c_parent_two_subagent_types"] = {"parent_records": parent_recs[:4], "subagent_files": subs}
                break
        out["fixtures"] = fx

    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
