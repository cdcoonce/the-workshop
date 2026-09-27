"""Parses a Claude Code transcript JSONL file into ordered tool-call events.

A transcript is the JSONL file ``<session>/subagents/agent-<id>.jsonl`` (for a
subagent) or the equivalent main-session transcript file, read in file line
order. Each line is one JSON object with a top-level ``type`` field
(``"user"``, ``"assistant"``, ``"attachment"``, or another envelope kind). A
tool call is a ``tool_use`` block inside an ``assistant`` line's
``message.content[]``; its result is a matching ``tool_result`` block
(``tool_use_id`` equal to the call's ``id``) inside a later ``user`` line's
``message.content[]``. Assistant prose is a ``text`` block in an
``assistant`` line's ``message.content[]``. The model ID for a line is read
from ``message.model`` on that line — never from the transcript's own prose.

Public contract
----------------
``parse_transcript(path) -> Transcript``
    Never raises on a bad file; reports parse failure through
    ``Transcript.status`` instead.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

Status = Literal["missing", "truncated", "api_error", "complete"]

_SYNTHETIC_MODEL = "<synthetic>"


@dataclass(frozen=True)
class ToolResult:
    """The matched ``tool_result`` block for one tool-call event.

    Attributes
    ----------
    content : Any
        The result's ``content`` — a string or a list of content blocks.
    is_error : bool
        Whether the tool call errored.
    """

    content: Any
    is_error: bool


@dataclass(frozen=True)
class ToolCallEvent:
    """One ``tool_use`` block, matched with its result if one arrived later.

    Attributes
    ----------
    name : str
        The tool name, e.g. ``"Edit"``, ``"Bash"``, ``"Skill"``.
    input : dict
        The tool's input object.
    result : ToolResult | None
        The matched ``tool_result``, or ``None`` if no result arrived.
    ordinal : int
        This event's position among every content block in the transcript,
        in file line order and left-to-right within a line's
        ``message.content[]``. Strictly increasing in file order.
    timestamp : str | None
        The envelope line's top-level ``timestamp``, ``None`` when absent.
    """

    name: str
    input: dict
    result: ToolResult | None
    ordinal: int
    timestamp: str | None


@dataclass(frozen=True)
class Transcript:
    """One parsed transcript.

    Attributes
    ----------
    status : Status
        ``"missing"`` (no file), ``"truncated"`` (a line was not valid JSON
        or lacked the ``type``/``message`` structure), ``"api_error"`` (an
        ``assistant`` line carried ``"isApiErrorMessage": true``), else
        ``"complete"``.
    events : list[ToolCallEvent]
        Every tool-call event, in file order.
    model_ids : list[str]
        Distinct ``message.model`` values from ``assistant`` lines, in
        first-seen order, excluding ``"<synthetic>"``.
    final_text : str
        The last ``text`` block of the last ``assistant`` line that has one,
        ``""`` if none.
    final_text_ordinal : int | None
        The ordinal position of that block, ``None`` if ``final_text`` is
        ``""``. Lets a caller (e.g. ``matchers.skill_triggered_first``)
        order a tool-call event against the final assistant prose.
    """

    status: Status
    events: list[ToolCallEvent]
    model_ids: list[str]
    final_text: str
    final_text_ordinal: int | None = None


def parse_transcript(path: Path) -> Transcript:
    """Parse a transcript JSONL file into an ordered sequence of tool-call events.

    Never raises on a bad file — a missing file, an invalid-JSON line, or a
    line lacking the ``type``/``message`` structure is reported through the
    returned ``status`` rather than an exception.

    Parameters
    ----------
    path : Path
        Path to the transcript JSONL file.

    Returns
    -------
    Transcript
        The parsed transcript.
    """
    if not path.exists():
        return Transcript(status="missing", events=[], model_ids=[], final_text="")
    try:
        raw_bytes = path.read_bytes()
    except OSError:
        return Transcript(status="truncated", events=[], model_ids=[], final_text="")

    truncated = False
    api_error = False
    ordinal = 0
    order: list[str | None] = []
    pending: dict[str, dict[str, Any]] = {}
    anonymous_events: list[dict[str, Any]] = []
    model_ids: list[str] = []
    seen_models: set[str] = set()
    final_text = ""
    final_text_ordinal: int | None = None

    for raw_line in raw_bytes.splitlines():
        try:
            line = raw_line.decode("utf-8").strip()
        except UnicodeDecodeError:
            truncated = True
            continue
        if not line:
            continue
        try:
            envelope = json.loads(line)
        except json.JSONDecodeError:
            truncated = True
            continue
        if not isinstance(envelope, dict) or "type" not in envelope:
            truncated = True
            continue

        line_type = envelope.get("type")
        timestamp = envelope.get("timestamp")

        if line_type not in ("assistant", "user"):
            continue

        message = envelope.get("message")
        if not isinstance(message, dict):
            truncated = True
            continue

        content = message.get("content")
        if not isinstance(content, list):
            content = []

        if line_type == "assistant":
            if envelope.get("isApiErrorMessage") is True:
                api_error = True
            model = message.get("model")
            if isinstance(model, str) and model != _SYNTHETIC_MODEL and model not in seen_models:
                seen_models.add(model)
                model_ids.append(model)

            line_last_text: tuple[str, int] | None = None
            for block in content:
                position = ordinal
                ordinal += 1
                if not isinstance(block, dict):
                    continue
                block_type = block.get("type")
                if block_type == "tool_use":
                    event_id = block.get("id")
                    event = {
                        "name": block.get("name"),
                        "input": block.get("input") or {},
                        "result": None,
                        "ordinal": position,
                        "timestamp": timestamp,
                    }
                    if isinstance(event_id, str):
                        pending[event_id] = event
                        order.append(event_id)
                    else:
                        anonymous_events.append(event)
                        order.append(None)
                elif block_type == "text":
                    line_last_text = (block.get("text", ""), position)
            if line_last_text is not None:
                final_text, final_text_ordinal = line_last_text
        else:
            for block in content:
                position = ordinal
                ordinal += 1
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_result":
                    tool_use_id = block.get("tool_use_id")
                    target = pending.get(tool_use_id) if isinstance(tool_use_id, str) else None
                    if target is not None:
                        target["result"] = ToolResult(
                            content=block.get("content"),
                            is_error=bool(block.get("is_error", False)),
                        )

    if truncated:
        status: Status = "truncated"
    elif api_error:
        status = "api_error"
    else:
        status = "complete"

    anonymous_iter = iter(anonymous_events)
    events = [
        ToolCallEvent(**(pending[event_id] if event_id is not None else next(anonymous_iter)))
        for event_id in order
    ]

    return Transcript(
        status=status,
        events=events,
        model_ids=model_ids,
        final_text=final_text,
        final_text_ordinal=final_text_ordinal,
    )
