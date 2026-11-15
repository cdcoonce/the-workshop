#!/usr/bin/env python3
"""fixed_weight — an uncalibrated estimate of what the fixed context costs.

Every call of a session re-sends the same fixed context: the system prompt, the
tool schemas, and what the user's setup injects (skill and agent listings,
instructions, hook context, MCP servers). The transcript records the text of that
context but not its token count, so this module sizes it in characters, turns
characters into tokens with ``CHARS_PER_TOKEN`` (times a calibration factor), and
prices it per call at the rate that call actually paid: the cache-write rate when
the call wrote at least that much to the cache, else the cache-read rate.

It is fed by ``transcript_reader.read(on_record=Collector())`` so there is one
pass over the files, and it never opens a transcript itself. Each transcript file
(a main session or one subagent) is estimated on its own, because a subagent pays
for its own copy of the fixed context.

The estimate is capped per call at that call's own dollars, so fixed-weight
dollars can never exceed the window total.

Stdlib only; imports ``pricing`` and ``transcript_reader`` from the engine.
"""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import pricing
import transcript_reader

CHARS_PER_TOKEN = 3.7
CALIBRATION_FILE = "cost_ledger_calibration.json"
_PER = 1_000_000
_CAP_SLACK = 1e-9  # relative; float noise must not count as a cap

SETUP = "setup"
CLAUDE_CODE = "claude_code"

# (component, group) in the fixed output order.
COMPONENTS: tuple[tuple[str, str], ...] = (
    ("skill_listing", SETUP),
    ("instructions", SETUP),
    ("hook_context", SETUP),
    ("agent_listing", SETUP),
    ("mcp_instructions", SETUP),
    ("mcp_tool_schemas", SETUP),
    ("mcp_tool_listing", SETUP),
    ("system_prompt", CLAUDE_CODE),
    ("builtin_tool_schemas", CLAUDE_CODE),
    ("builtin_tool_listing", CLAUDE_CODE),
    ("other", CLAUDE_CODE),
)
MCP_COMPONENTS = ("mcp_instructions", "mcp_tool_schemas", "mcp_tool_listing")

# Attachment subtype -> component, for the subtypes that map one to one.
_SUBTYPE_COMPONENT = {
    "skill_listing": "skill_listing",
    "instructions": "instructions",
    "hook_additional_context": "hook_context",
    "agent_listing_delta": "agent_listing",
    "mcp_instructions_delta": "mcp_instructions",
}
_MCP_PREFIX = "mcp__"


# ---------------------------------------------------------------------------
# calibration
# ---------------------------------------------------------------------------
class CalibrationError(ValueError):
    """A calibration file exists but cannot be used."""


@dataclass(frozen=True)
class Calibration:
    factor: float = 1.0
    calibrated: bool = False


def load_calibration(path: Path) -> Calibration:
    """The factor in the JSON file at ``path``; no file means factor 1.0, uncalibrated.

    A file that exists but is unreadable, is not a JSON object, or has a missing or
    invalid ``factor`` (a finite number greater than 0) raises ``CalibrationError``.
    Other keys are ignored.
    """
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return Calibration()
    except (OSError, ValueError) as exc:
        reason = getattr(exc, "strerror", None) or str(exc)
        raise CalibrationError(f"calibration file {path} is unreadable: {reason}") from None
    try:
        data = json.loads(text)
    except ValueError:
        raise CalibrationError(f"calibration file {path} is not valid JSON") from None
    if not isinstance(data, dict):
        raise CalibrationError(f"calibration file {path} is not a JSON object")
    factor = data.get("factor")
    if (
        isinstance(factor, bool)
        or not isinstance(factor, (int, float))
        or not math.isfinite(factor)
        or factor <= 0
    ):
        raise CalibrationError(
            f"calibration file {path} needs a finite number greater than 0 as \"factor\""
        )
    return Calibration(float(factor), True)


# ---------------------------------------------------------------------------
# collection
# ---------------------------------------------------------------------------
FileKey = tuple[str, str, bool, "str | None"]


def file_key(obj: object) -> FileKey:
    """The transcript file a ``FileInfo`` or a ``Call`` belongs to."""
    return (obj.project, obj.session_id, obj.is_subagent, obj.agent_id)  # type: ignore[attr-defined]


@dataclass
class FileSizes:
    """What one transcript file sent as fixed context, in characters."""

    chars: dict[str, float] = field(default_factory=dict)
    has_snapshot: bool = False
    called: bool = False  # a usable assistant record has been seen
    has_system_prompt: bool = False
    has_tools: bool = False

    def add(self, component: str, size: float) -> None:
        if size:
            self.chars[component] = self.chars.get(component, 0.0) + size


def _rendered_size(rec: dict) -> int:
    rendered = rec.get("rendered")
    if not isinstance(rendered, list):
        return 0
    total = 0
    for block in rendered:
        if isinstance(block, dict) and isinstance(block.get("content"), str):
            total += len(block["content"])
    return total


def _string_length(value: object) -> int:
    if isinstance(value, str):
        return len(value)
    if isinstance(value, list):
        return sum(len(v) for v in value if isinstance(v, str))
    return 0


def _usable_call(info: transcript_reader.FileInfo, rec: dict) -> bool:
    """True when ``rec`` is an assistant record with usable usage (a fresh collector keeps it)."""
    return transcript_reader.CallCollector().add(info, rec) is not None


class Collector:
    """The ``on_record`` hook: sizes the fixed context of every file it is shown."""

    def __init__(self) -> None:
        self.files: dict[FileKey, FileSizes] = {}

    def __call__(self, info: transcript_reader.FileInfo, rec: dict) -> None:
        state = self.files.setdefault(file_key(info), FileSizes())
        if rec.get("type") == "attachment":
            att = rec.get("attachment")
            if isinstance(att, dict):
                self._attachment(state, att, rec)
        elif not state.called and _usable_call(info, rec):
            state.called = True

    @staticmethod
    def _attachment(state: FileSizes, att: dict, rec: dict) -> None:
        subtype = att.get("type") if isinstance(att.get("type"), str) else None
        if subtype == "prompt_snapshot":
            state.has_snapshot = True
            if not state.has_system_prompt and "systemPrompt" in att:
                prompt = att["systemPrompt"]
                if isinstance(prompt, (str, list)):
                    state.has_system_prompt = True
                    state.add("system_prompt", _string_length(prompt))
            tools = att.get("tools")
            if not state.has_tools and isinstance(tools, list):
                state.has_tools = True
                for tool in tools:
                    if not isinstance(tool, dict) or not isinstance(tool.get("name"), str):
                        continue
                    schema = tool.get("schema")
                    if not isinstance(schema, dict):
                        continue
                    try:
                        size = len(json.dumps(schema, separators=(",", ":"), ensure_ascii=False))
                    except (TypeError, ValueError):
                        continue
                    mcp = tool["name"].startswith(_MCP_PREFIX)
                    state.add("mcp_tool_schemas" if mcp else "builtin_tool_schemas", size)
            return
        if state.called:
            return
        size = _rendered_size(rec)
        if subtype == "deferred_tools_delta":
            names = att.get("addedNames")
            usable = [n for n in names if isinstance(n, str) and n] if isinstance(names, list) else []
            share = sum(n.startswith(_MCP_PREFIX) for n in usable) / len(usable) if usable else 0.0
            state.add("mcp_tool_listing", size * share)
            state.add("builtin_tool_listing", size * (1.0 - share))
            return
        state.add(_SUBTYPE_COMPONENT.get(subtype, "other"), size)


# ---------------------------------------------------------------------------
# estimate
# ---------------------------------------------------------------------------
def _r(x: float) -> float:
    return round(x, 6)


def _share(part: float, whole: float) -> float | None:
    return _r(part / whole) if whole else None


def estimate(
    files: dict[FileKey, FileSizes],
    calls: Iterable[transcript_reader.Call],
    pricer: pricing.Pricer,
    *,
    factor: float = 1.0,
    window_usd: float,
    calibrated: bool = False,
    chars_per_token: float | None = None,
) -> dict:
    """The ``fixed_weight`` object for ``calls`` (in-window, dated) given the collected sizes.

    ``window_usd`` is the window total the shares are taken of. Calls are priced
    here with the pricer's table but without touching its unpriced tally.
    """
    cpt = CHARS_PER_TOKEN if chars_per_token is None else chars_per_token
    names = [name for name, _ in COMPONENTS]
    tokens: dict[FileKey, dict[str, float]] = {}
    for key, state in files.items():
        tokens[key] = {c: chars / cpt * factor for c, chars in state.chars.items() if chars > 0}

    usd = {c: {"write": 0.0, "read": 0.0} for c in names}
    charged_files: set[FileKey] = set()
    seen_files: set[FileKey] = set()
    subagent_usd = 0.0
    write_calls = read_calls = capped = unpriced = 0

    for call in calls:
        key = file_key(call)
        seen_files.add(key)
        sizes = tokens.get(key, {})
        total_tokens = sum(sizes.values())
        if total_tokens <= 0:
            continue
        priced = pricing.price_call(call, pricer.table)
        if not priced.priced:
            unpriced += 1
            continue
        if priced.rates is None:  # a call of zero tokens costs nothing
            continue
        if call.cache_write_tokens >= total_tokens:
            kind = "write"
            rate = (
                priced.rates["write_1h"]
                if call.cache_write_1h_tokens >= total_tokens
                else priced.rates["write_5m"]
            )
        else:
            kind = "read"
            rate = priced.rates["cache_read"]
        charge = {c: t * rate / _PER for c, t in sizes.items()}
        fixed = sum(charge.values())
        if fixed > priced.total_usd * (1 + _CAP_SLACK):
            ratio = priced.total_usd / fixed
            charge = {c: v * ratio for c, v in charge.items()}
            capped += 1
        for c, v in charge.items():
            usd[c][kind] += v
        if kind == "write":
            write_calls += 1
        else:
            read_calls += 1
        charged_files.add(key)
        if call.is_subagent:
            subagent_usd += sum(charge.values())

    rows = []
    for name, group in COMPONENTS:
        per_file = [tokens[k][name] for k in charged_files if name in tokens.get(k, {})]
        rows.append(
            {
                "component": name,
                "group": group,
                "files": len(per_file),
                "tokens_per_file": {
                    "min": min(per_file) if per_file else None,
                    "median": statistics.median(per_file) if per_file else None,
                    "max": max(per_file) if per_file else None,
                },
                "usd": _r(usd[name]["write"] + usd[name]["read"]),
                "write_usd": _r(usd[name]["write"]),
                "read_usd": _r(usd[name]["read"]),
            }
        )

    def total_of(members: Iterable[str]) -> float:
        return sum(usd[c]["write"] + usd[c]["read"] for c in members)

    total = total_of(names)

    def block(members: Iterable[str]) -> dict:
        part = total_of(members)
        return {"usd": _r(part), "share_of_total": _share(part, window_usd)}

    return {
        "calibrated": calibrated,
        "calibration_factor": factor,
        "chars_per_token": cpt,
        "files_estimated": len(charged_files),
        "files_without_snapshot": sum(1 for k in seen_files if not _has_snapshot(files, k)),
        "write_calls": write_calls,
        "read_calls": read_calls,
        "capped_calls": capped,
        "unpriced_calls": unpriced,
        "total_usd": _r(total),
        "share_of_total": _share(total, window_usd),
        "subagent_usd": _r(subagent_usd),
        "subagent_share": _share(subagent_usd, total),
        "groups": {
            SETUP: block(n for n, g in COMPONENTS if g == SETUP),
            CLAUDE_CODE: block(n for n, g in COMPONENTS if g == CLAUDE_CODE),
        },
        "mcp": block(MCP_COMPONENTS),
        "components": rows,
    }


def _has_snapshot(files: dict[FileKey, FileSizes], key: FileKey) -> bool:
    state = files.get(key)
    return state is not None and state.has_snapshot
