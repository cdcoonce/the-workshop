#!/usr/bin/env python3
"""context_spend — where Claude Code spend goes, by context size and trigger.

Companion to ``budget_burn`` (which answers *how much* was spent this month).
This answers *why*: how much of the cost comes from calls that carry a large
context, which turn triggers drive it, what compaction does, and what a lower
auto-compact ceiling would have saved. It exists so a settings change such as
``autoCompactWindow`` can be judged with the same parser before and after.

It reads the per-message ``usage`` blocks in every transcript under
``~/.claude/projects`` (main sessions and subagent files) over a date window
taken from each *message's* timestamp, never the file's mtime. It reports:

1. cost by model and by token category
2. main-session vs subagent share
3. per-call context distribution for main sessions, and cost share above
   200k / 500k
4. cost share by turn trigger (human-typed, task-notification,
   meta/system-injected, programmatic, hook)
5. compaction events (``compact_boundary`` system entries): count, auto vs
   manual, ``preTokens`` distribution, context on the first call after each
6. ``Read`` calls in the 20 calls after each compaction that target a path
   already read before it (count and bytes)
7. large-context cache rewrites: ``cache_creation_input_tokens`` over 50% of
   context while context is above 100k, with cost share and preceding idle gap
8. a ceiling simulation: what the main sessions would have cost had context
   been reset to a small resume size whenever it crossed a threshold

Rules that differ from ``budget_burn`` are behind explicit options (defaults
are the instrument's own rules, so an old baseline stays comparable):

* ``--dedupe message-request`` (default) keeps, per ``(message.id,
  requestId)``, the line with the largest ``output_tokens``;
  ``--dedupe request`` is budget_burn's first-seen-per-request rule.
* ``--model-rule real`` (default) drops calls with no model or a ``<...>``
  synthetic model and prices any other model id at the top tier;
  ``--model-rule billable`` is budget_burn's rule (only fable/opus/sonnet/haiku).
* ``--pricing relative`` (default) uses unit weights (input 1, output 5, cache
  write 1.25, cache read 0.1) times a tier factor (opus/fable/unknown 5,
  sonnet 1, haiku 0.27); ``--pricing usd`` reuses budget_burn's price table.

Usage:
    python3 context_spend.py --since 2026-10-13 --until 2026-11-12
    python3 context_spend.py --since 2026-10-13 --json --ceiling 200k,300k
"""

from __future__ import annotations

import argparse
import collections
import datetime
import json
import statistics
import sys
from pathlib import Path

import budget_burn
import transcript_reader

# Token categories, in the order costs are indexed everywhere below.
CATS = ("in", "out", "cw", "cr")
# Relative weights: input 1, output 5, cache write 1.25, cache read 0.1.
REL_WEIGHTS = (1.0, 5.0, 1.25, 0.1)
TRIGGERS = (
    "human-typed",
    "task-notification",
    "meta/system-injected",
    "programmatic",
    "hook",
)
CONTEXT_THRESHOLDS = (200_000, 500_000)
REREAD_WINDOW_CALLS = 20
REWRITE_MIN_CONTEXT = 100_000
REWRITE_CACHE_WRITE_SHARE = 0.5
RESET_DROP = 0.5  # a >50% context drop between consecutive calls is a reset


# ---------------------------------------------------------------------------
# pricing
# ---------------------------------------------------------------------------
def _rel_tier(model: str) -> float:
    m = (model or "").lower()
    if "haiku" in m:
        return 0.27
    if "sonnet" in m:
        return 1.0
    return 5.0  # opus / fable / unknown = top tier


def rates_for(model: str, pricing: str) -> tuple[float, float, float, float]:
    """Per-token (in, out, cache-write, cache-read) rates for ``model``."""
    if pricing == "usd":
        tier = budget_burn._tier(model) or "opus"
        rate_in, rate_out = budget_burn.RATES[tier]
        return (
            rate_in / 1e6,
            rate_out / 1e6,
            rate_in * 1.25 / 1e6,
            rate_in * 0.1 / 1e6,
        )
    t = _rel_tier(model)
    return tuple(t * w / 1e6 for w in REL_WEIGHTS)  # type: ignore[return-value]


def _cost(rates: tuple[float, ...], i: int, o: int, cw: int, cr: int) -> float:
    return i * rates[0] + o * rates[1] + cw * rates[2] + cr * rates[3]


# ---------------------------------------------------------------------------
# small stats helpers
# ---------------------------------------------------------------------------
def _pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    v = sorted(values)
    return v[min(len(v) - 1, int(p * len(v)))]


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def _stats(values: list[float]) -> dict:
    return {
        "n": len(values),
        "median": _median(values),
        "p90": _pct(values, 0.9),
        "max": max(values) if values else None,
    }


def _share(part: float, whole: float) -> float:
    return part / whole if whole else 0.0


# ---------------------------------------------------------------------------
# transcript parsing
# ---------------------------------------------------------------------------
def classify_trigger(entry: dict) -> str:
    """Turn trigger of a (non tool-result) ``user`` transcript entry."""
    msg = entry.get("message") or {}
    content = msg.get("content")
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        text = " ".join(
            b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
        )
    else:
        text = ""
    origin = entry.get("origin") or {}
    kind = origin.get("kind") if isinstance(origin, dict) else None
    if text.startswith("<task-notification>") or kind == "task-notification":
        return "task-notification"
    if text.startswith("Stop hook feedback") or "hook" in text[:40].lower():
        return "hook"
    if kind == "human":
        return "human-typed"
    if entry.get("isMeta"):
        return "meta/system-injected"
    return "programmatic"


def _epoch(ts: object) -> float | None:
    if not isinstance(ts, str) or not ts:
        return None
    try:
        return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _result_bytes(content: object) -> int:
    if isinstance(content, str):
        return len(content.encode("utf-8", "replace"))
    if isinstance(content, list):
        return sum(
            len(str(x.get("text", "")).encode("utf-8", "replace"))
            for x in content
            if isinstance(x, dict)
        )
    return 0


def _in_window(ts: object, since: str | None, until: str | None) -> bool:
    if since is None and until is None:
        return True
    if not isinstance(ts, str) or len(ts) < 10:
        return False  # cannot be placed in a window
    day = ts[:10]
    return (since is None or day >= since) and (until is None or day <= until)


class _Scan:
    """Everything one pass over the transcripts collects."""

    def __init__(self) -> None:
        self.calls: dict[tuple, dict] = {}
        self.files = 0
        self.assistant_lines = 0
        self.boundaries: dict[str, list[dict]] = collections.defaultdict(list)
        self.reads: dict[str, list[tuple[float, str, str]]] = collections.defaultdict(list)
        self.result_bytes: dict[str, int] = {}
        self._seen_reads: set[str] = set()
        self._seen_results: set[str] = set()


def _scan(root: Path, since: str | None, until: str | None, dedupe: str) -> _Scan:
    out = _Scan()
    collector = transcript_reader.CallCollector(dedupe)
    coverage = transcript_reader.Coverage()
    meta: dict[tuple, tuple[bool, str]] = {}  # call key -> (side, trigger) at the kept line
    trig_by_file: dict[Path, str] = {}
    for info, d in transcript_reader.iter_records(root, since=since, coverage=coverage):
        sub = info.is_subagent
        sid = info.session_id
        trig = trig_by_file.get(info.path, "none")
        kind = d.get("type")
        side = sub or bool(d.get("isSidechain"))
        if kind == "user":
            msg = d.get("message") or {}
            c = msg.get("content")
            if isinstance(c, list) and any(
                isinstance(b, dict) and b.get("type") == "tool_result" for b in c
            ):
                if not side:
                    for b in c:
                        if not isinstance(b, dict) or b.get("type") != "tool_result":
                            continue
                        tid = b.get("tool_use_id")
                        if tid and tid not in out._seen_results:
                            out._seen_results.add(tid)
                            out.result_bytes[tid] = _result_bytes(b.get("content"))
                continue
            trig_by_file[info.path] = classify_trigger(d)
        elif kind == "system":
            if (
                d.get("subtype") == "compact_boundary"
                and not side
                and _in_window(d.get("timestamp"), since, until)
            ):
                cmeta = d.get("compactMetadata") or {}
                out.boundaries[sid].append(
                    {
                        "ts": _epoch(d.get("timestamp")) or 0.0,
                        "trigger": cmeta.get("trigger"),
                        "pre": cmeta.get("preTokens"),
                        "post": cmeta.get("postTokens"),
                    }
                )
        elif kind == "assistant":
            out.assistant_lines += 1
            msg = d.get("message") or {}
            content = msg.get("content")
            if isinstance(content, list) and not side:
                for b in content:
                    if (
                        isinstance(b, dict)
                        and b.get("type") == "tool_use"
                        and b.get("name") == "Read"
                        and isinstance(b.get("input"), dict)
                        and b["input"].get("file_path")
                        and b.get("id") not in out._seen_reads
                    ):
                        out._seen_reads.add(b["id"])
                        out.reads[sid].append(
                            (_epoch(d.get("timestamp")) or 0.0, b["input"]["file_path"], b["id"])
                        )
            if not _in_window(d.get("timestamp"), since, until):
                continue
            kept = collector.add(info, d)
            if kept is not None:
                meta[kept.key] = (side, trig)
    out.files = coverage.files_read
    for call in collector.calls:
        side, trig = meta[call.key]
        out.calls[call.key] = {
            "model": call.model,
            "i": call.input_tokens,
            "o": call.output_tokens,
            "cw": call.cache_write_tokens,
            "cr": call.cache_read_tokens,
            "side": side,
            "sid": call.session_id,
            "trig": trig,
            "ts": _epoch(call.timestamp) or 0.0,
        }
    return out


# ---------------------------------------------------------------------------
# analysis
# ---------------------------------------------------------------------------
def _ceiling_sim(
    sessions: dict[str, list[dict]], threshold: int, resume: int, digest: int
) -> tuple[float, collections.Counter]:
    total = 0.0
    resets: collections.Counter = collections.Counter()
    for sid, calls in sessions.items():
        offset = 0
        prev = None
        for r in calls:
            if prev is not None and r["ctx"] < RESET_DROP * prev:
                offset = 0  # a real reset (compaction, /clear) already happened
            prev = r["ctx"]
            sc = r["ctx"] - offset
            extra = 0.0
            if sc > threshold:
                offset = r["ctx"] - resume
                sc = resume
                resets[sid] += 1
                extra = resume * r["rates"][2] + digest * r["rates"][1]
            cr = max(0, sc - r["i"] - r["cw"])
            total += _cost(r["rates"], r["i"], r["o"], r["cw"], cr) + extra
    return total, resets


def analyze(
    root: Path,
    *,
    since: str | None = None,
    until: str | None = None,
    dedupe: str = "message-request",
    model_rule: str = "real",
    pricing: str = "relative",
    ceilings: list[int] | None = None,
    resume_sizes: list[int] | None = None,
    digest_tokens: int = 3000,
) -> dict:
    """Run every analysis over ``root`` for the (inclusive) date window."""
    ceilings = ceilings or []
    resume_sizes = resume_sizes if resume_sizes is not None else [30_000, 80_000]
    scan = _scan(root, since, until, dedupe)

    calls: list[dict] = []
    dropped = 0
    for rec in scan.calls.values():
        model = rec["model"]
        if not model or str(model).startswith("<"):
            dropped += 1
            continue
        if model_rule == "billable" and budget_burn._tier(model) is None:
            dropped += 1
            continue
        rec["rates"] = rates_for(model, pricing)
        rec["ctx"] = rec["i"] + rec["cw"] + rec["cr"]
        rec["cost"] = _cost(rec["rates"], rec["i"], rec["o"], rec["cw"], rec["cr"])
        calls.append(rec)
    total = sum(r["cost"] for r in calls)

    result: dict = {
        "window": {"since": since, "until": until},
        "options": {
            "dedupe": dedupe,
            "model_rule": model_rule,
            "pricing": pricing,
            "digest_tokens": digest_tokens,
        },
        "unit": "usd" if pricing == "usd" else "relative",
        "files": scan.files,
        "assistant_lines": scan.assistant_lines,
        "calls": len(calls),
        "dropped_no_model": dropped,
        "total_cost": total,
    }

    # 1. by model / category
    by_model: dict[str, dict] = {}
    cat_tokens = {k: 0 for k in CATS}
    cat_cost = {k: 0.0 for k in CATS}
    for r in calls:
        m = by_model.setdefault(
            r["model"], {"calls": 0, "in": 0, "out": 0, "cw": 0, "cr": 0, "cost": 0.0}
        )
        m["calls"] += 1
        m["cost"] += r["cost"]
        for k, rate in zip(CATS, r["rates"]):
            tokens = r[{"in": "i", "out": "o", "cw": "cw", "cr": "cr"}[k]]
            m[k] += tokens
            cat_tokens[k] += tokens
            cat_cost[k] += tokens * rate
    for m in by_model.values():
        m["share"] = _share(m["cost"], total)
    result["by_model"] = dict(sorted(by_model.items(), key=lambda kv: -kv[1]["cost"]))
    result["by_category"] = {
        "tokens": cat_tokens,
        "cost": cat_cost,
        "cost_share": {k: _share(v, total) for k, v in cat_cost.items()},
    }

    # 2. main vs subagent
    main = [r for r in calls if not r["side"]]
    sub = [r for r in calls if r["side"]]
    main_cost = sum(r["cost"] for r in main)
    result["main_vs_subagent"] = {
        "main": {"calls": len(main), "cost": main_cost, "share": _share(main_cost, total)},
        "subagent": {
            "calls": len(sub),
            "cost": total - main_cost,
            "share": _share(total - main_cost, total),
        },
    }

    # 3. main context distribution
    ctxs = [r["ctx"] for r in main]
    above = {}
    for th in CONTEXT_THRESHOLDS:
        big = [r for r in main if r["ctx"] > th]
        c = sum(r["cost"] for r in big)
        above[str(th)] = {
            "calls": len(big),
            "call_share": _share(len(big), len(main)),
            "cost": c,
            "main_cost_share": _share(c, main_cost),
            "total_cost_share": _share(c, total),
        }
    result["main_context"] = {"calls": len(main), **_stats(ctxs), "above": above}

    # 4. triggers (main calls only)
    trig: dict[str, dict] = {}
    for r in main:
        t = trig.setdefault(r["trig"], {"calls": 0, "cost": 0.0})
        t["calls"] += 1
        t["cost"] += r["cost"]
    for t in trig.values():
        t["share_of_main"] = _share(t["cost"], main_cost)
    result["triggers"] = dict(sorted(trig.items(), key=lambda kv: -kv[1]["cost"]))

    # per-session main call lists, time ordered
    sessions: dict[str, list[dict]] = collections.defaultdict(list)
    for r in main:
        sessions[r["sid"]].append(r)
    for v in sessions.values():
        v.sort(key=lambda r: r["ts"])

    drops: list[tuple[str, int]] = []
    for sid, v in sessions.items():
        for k in range(1, len(v)):
            if v[k]["ctx"] < RESET_DROP * v[k - 1]["ctx"]:
                drops.append((sid, k))
    drop_post = [sessions[s][k]["ctx"] for s, k in drops]
    result["context_drops"] = {"count": len(drops), "post_median": _median(drop_post)}

    # 5. compactions
    bounds = [(sid, b) for sid, bs in scan.boundaries.items() for b in bs]
    by_trig = collections.Counter(str(b["trigger"]) for _, b in bounds)
    first_ctx: list[float] = []
    for sid, b in bounds:
        nxt = next((r for r in sessions.get(sid, []) if r["ts"] > b["ts"]), None)
        if nxt is not None:
            first_ctx.append(nxt["ctx"])
    pre = [b["pre"] for _, b in bounds if isinstance(b["pre"], (int, float))]
    result["compactions"] = {
        "count": len(bounds),
        "by_trigger": dict(by_trig),
        "pre_tokens": _stats(pre),
        "first_call_context": _stats(first_ctx),
    }

    # 6. re-reads after compaction
    analysed = reads_in = rereads = reread_bytes = with_reread = 0
    for sid, b in bounds:
        v = sessions.get(sid, [])
        idx = next((k for k, r in enumerate(v) if r["ts"] > b["ts"]), None)
        if idx is None:
            continue
        analysed += 1
        end = v[idx + REREAD_WINDOW_CALLS]["ts"] if idx + REREAD_WINDOW_CALLS < len(v) else float("inf")
        session_reads = scan.reads.get(sid, [])
        before = {p for t, p, _ in session_reads if t < b["ts"]}
        after = [(p, tid) for t, p, tid in session_reads if b["ts"] <= t < end]
        again = [(p, tid) for p, tid in after if p in before]
        reads_in += len(after)
        rereads += len(again)
        reread_bytes += sum(scan.result_bytes.get(tid, 0) for _, tid in again)
        with_reread += bool(again)
    result["post_compaction_rereads"] = {
        "window_calls": REREAD_WINDOW_CALLS,
        "compactions_analysed": analysed,
        "reads_in_window": reads_in,
        "rereads": rereads,
        "reread_bytes": reread_bytes,
        "compactions_with_reread": with_reread,
    }

    # 7. cache rewrites at large context
    hits: list[dict] = []
    gaps: list[float] = []
    after_drop = 0
    drop_set = set(drops)
    for sid, v in sessions.items():
        for k, r in enumerate(v):
            if r["ctx"] > REWRITE_MIN_CONTEXT and r["cw"] > REWRITE_CACHE_WRITE_SHARE * r["ctx"]:
                hits.append(r)
                if k > 0:
                    gaps.append((r["ts"] - v[k - 1]["ts"]) / 60)
                after_drop += (sid, k) in drop_set
    hit_cost = sum(r["cost"] for r in hits)
    result["cache_rewrites"] = {
        "count": len(hits),
        "of_main_calls": len(main),
        "cost": hit_cost,
        "share_of_main": _share(hit_cost, main_cost),
        "gaps_available": len(gaps),
        "median_gap_min": _median(gaps),
        "p25_gap_min": _pct(gaps, 0.25),
        "p75_gap_min": _pct(gaps, 0.75),
        "gap_over_5min": sum(g > 5 for g in gaps),
        "gap_over_60min": sum(g > 60 for g in gaps),
        "gap_5min_or_less": sum(g <= 5 for g in gaps),
        "first_call_after_drop": after_drop,
    }

    # 8. ceiling simulation
    rows: list[dict] = []
    if ceilings and main:
        resumes = set(resume_sizes)
        observed = int(result["context_drops"]["post_median"]) if drops else None
        if observed is not None:
            resumes.add(observed)
        over200 = {s for s, v in sessions.items() if max(r["ctx"] for r in v) > 200_000}
        for th in sorted(ceilings):
            for rs in sorted(resumes):
                sim, resets = _ceiling_sim(sessions, th, rs, digest_tokens)
                rows.append(
                    {
                        "threshold": th,
                        "resume_tokens": rs,
                        "resume_is_observed": rs == observed,
                        "sim_cost": sim,
                        "actual_main_cost": main_cost,
                        "saved_share_of_main": _share(main_cost - sim, main_cost),
                        "saved_share_of_all": _share(main_cost - sim, total),
                        "resets": sum(resets.values()),
                        "median_resets_per_affected_session": _median(list(resets.values())),
                        "affected_session_share": _share(len(resets), len(sessions)),
                        "affected_share_of_over_200k_sessions": _share(
                            sum(1 for s in resets if s in over200), len(over200)
                        ),
                    }
                )
    result["ceiling"] = rows
    return result


# ---------------------------------------------------------------------------
# text report
# ---------------------------------------------------------------------------
def _n(v: float | None, fmt: str = "{:,.0f}") -> str:
    return "n/a" if v is None else fmt.format(v)


def _pc(v: float) -> str:
    return f"{100 * v:.1f}%"


def render_text(r: dict) -> str:
    w = r["window"]
    unit = "USD" if r["unit"] == "usd" else "relative units (input=1, tiered)"
    o = r["options"]
    L = [
        f"Context spend — {w['since'] or 'beginning'} .. {w['until'] or 'now'} (by message timestamp)",
        f"  rules: dedupe={o['dedupe']} model-rule={o['model_rule']} pricing={o['pricing']}",
        f"  files={r['files']} assistant lines={r['assistant_lines']} unique calls={r['calls']} "
        f"dropped (no/synthetic model)={r['dropped_no_model']}",
        f"  total cost: {r['total_cost']:,.2f} {unit}",
        "",
        "1. Cost by model",
    ]
    for m, v in r["by_model"].items():
        L.append(
            f"  {m:28s} calls={v['calls']:7d} in={v['in'] / 1e6:8.2f}M out={v['out'] / 1e6:7.2f}M "
            f"cw={v['cw'] / 1e6:8.1f}M cr={v['cr'] / 1e6:9.1f}M cost={v['cost']:10.1f} ({_pc(v['share'])})"
        )
    c = r["by_category"]
    L += [
        "",
        "   Cost by token category",
        "  tokens (M): " + "  ".join(f"{k}={c['tokens'][k] / 1e6:.1f}" for k in CATS),
        "  cost share: " + "  ".join(f"{k}={_pc(c['cost_share'][k])}" for k in CATS),
        "",
        "2. Main vs subagent",
    ]
    for k in ("main", "subagent"):
        v = r["main_vs_subagent"][k]
        L.append(f"  {k:9s} calls={v['calls']:7d} cost={v['cost']:10.1f} share={_pc(v['share'])}")
    mc = r["main_context"]
    L += [
        "",
        "3. Main-session context per call",
        f"  calls={mc['calls']} median={_n(mc['median'])} p90={_n(mc['p90'])} max={_n(mc['max'])}",
    ]
    for th, v in mc["above"].items():
        L.append(
            f"  > {int(th):>7,}: {_pc(v['call_share'])} of calls; {_pc(v['main_cost_share'])} of main cost, "
            f"{_pc(v['total_cost_share'])} of total"
        )
    L += ["", "4. Cost by turn trigger (main calls)"]
    for k, v in r["triggers"].items():
        L.append(f"  {k:24s} calls={v['calls']:7d} share of main={_pc(v['share_of_main'])}")
    cp = r["compactions"]
    L += [
        "",
        "5. Compactions",
        f"  count={cp['count']} by trigger={cp['by_trigger']}",
        "  preTokens: median={} p90={} max={}".format(
            _n(cp["pre_tokens"]["median"]), _n(cp["pre_tokens"]["p90"]), _n(cp["pre_tokens"]["max"])
        ),
        "  context on first call after: n={} median={} p90={} max={}".format(
            cp["first_call_context"]["n"],
            _n(cp["first_call_context"]["median"]),
            _n(cp["first_call_context"]["p90"]),
            _n(cp["first_call_context"]["max"]),
        ),
    ]
    rr = r["post_compaction_rereads"]
    L += [
        "",
        f"6. Re-reads after compaction (Read calls in the next {rr['window_calls']} calls on an already-read path)",
        f"  compactions analysed={rr['compactions_analysed']} Reads in window={rr['reads_in_window']} "
        f"re-reads={rr['rereads']} ({rr['reread_bytes']:,} result bytes); "
        f"compactions with >=1 re-read={rr['compactions_with_reread']}",
    ]
    cr = r["cache_rewrites"]
    L += [
        "",
        "7. Cache rewrites (cache write >50% of context, context >100k)",
        f"  count={cr['count']} of {cr['of_main_calls']} main calls; cost share of main={_pc(cr['share_of_main'])}; "
        f"first call after a context drop={cr['first_call_after_drop']}",
        f"  idle gap before (min): n={cr['gaps_available']} median={_n(cr['median_gap_min'], '{:.1f}')} "
        f"p25={_n(cr['p25_gap_min'], '{:.1f}')} p75={_n(cr['p75_gap_min'], '{:.1f}')}; "
        f">5min={cr['gap_over_5min']} >60min={cr['gap_over_60min']} <=5min={cr['gap_5min_or_less']}",
    ]
    if r["ceiling"]:
        L += [
            "",
            "8. Ceiling simulation (main sessions; reset to resume size when context crosses threshold)",
            "  threshold  resume    sim cost  saved/main saved/all  resets  affected  of >200k sessions",
        ]
        for x in r["ceiling"]:
            tag = "*" if x["resume_is_observed"] else " "
            L.append(
                f"  {x['threshold'] / 1000:7.0f}k {x['resume_tokens'] / 1000:6.0f}k{tag} {x['sim_cost']:10.1f} "
                f"{_pc(x['saved_share_of_main']):>10s} {_pc(x['saved_share_of_all']):>8s} {x['resets']:7d} "
                f"{_pc(x['affected_session_share']):>8s} {_pc(x['affected_share_of_over_200k_sessions']):>10s}"
            )
        L.append("  (* = median context of the first call after an observed >50% drop)")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _date(s: str) -> str:
    try:
        return datetime.date.fromisoformat(s).isoformat()
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a YYYY-MM-DD date: {s!r}") from None


def _tokens(s: str) -> int:
    s = s.strip().lower()
    try:
        return int(float(s[:-1]) * 1000) if s.endswith("k") else int(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a token count: {s!r}") from None


def _token_list(s: str) -> list[int]:
    return [_tokens(x) for x in s.split(",") if x.strip()]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Context-size spend instrument.")
    ap.add_argument("--projects-root", default=str(Path.home() / ".claude" / "projects"))
    ap.add_argument("--since", type=_date, help="first day, inclusive (UTC, by message timestamp)")
    ap.add_argument("--until", type=_date, help="last day, inclusive")
    ap.add_argument("--json", action="store_true")
    ap.add_argument(
        "--ceiling",
        type=_token_list,
        default=[],
        help="comma list of thresholds for the ceiling simulation, e.g. 200k,300k",
    )
    ap.add_argument(
        "--resume-tokens",
        type=_token_list,
        default=[30_000, 80_000],
        help="comma list of post-reset context sizes (default 30k,80k; observed is added)",
    )
    ap.add_argument("--digest-tokens", type=_tokens, default=3000)
    ap.add_argument("--dedupe", choices=("message-request", "request"), default="message-request")
    ap.add_argument("--model-rule", choices=("real", "billable"), default="real")
    ap.add_argument("--pricing", choices=("relative", "usd"), default="relative")
    args = ap.parse_args(argv)

    result = analyze(
        Path(args.projects_root),
        since=args.since,
        until=args.until,
        dedupe=args.dedupe,
        model_rule=args.model_rule,
        pricing=args.pricing,
        ceilings=args.ceiling,
        resume_sizes=args.resume_tokens,
        digest_tokens=args.digest_tokens,
    )
    if args.json:
        json.dump(result, sys.stdout, indent=2)
        print()
    else:
        print(render_text(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
