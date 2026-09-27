"""Conjunctive review matching and ordering predicates over a parsed transcript.

Public contract
----------------
``review_match(finding, *, file_suffix, regex, line_window) -> bool``
    A gated review item requires BOTH its location (a line window, or a
    file-suffix-only match when there is no window) AND its regex to hit. A
    match on only one never credits the item — this retires the disjunctive
    ``in_window or regex.search(...)`` rule from the terse-lens-contract A/B
    experiment's ``score_arm.py``.

``extract_findings(final_text) -> (findings, ok)``
    Pulls the ``findings`` list out of the first JSON object in the agent's
    final reply that has one. ``ok`` is ``False`` (with an empty list) when
    no such object parses.

``count_unmatched(findings, items) -> int``
    Trend count of findings that credit no item; never gates a verdict.

``precedes(events, first, then) -> bool``
    Generic ordering predicate: ``True`` iff some event satisfying ``first``
    has an ordinal strictly below the first event satisfying ``then``.
    Hard-codes no event kind.

``test_failed_before_first_source_edit(events) -> bool``
    Ordering predicate instance: a test failed before the first source-file
    edit.

``skill_triggered_first(transcript, skill) -> bool``
    Triggering predicate: the rostered skill's ``Skill`` call precedes every
    other tool call (except ``Skill``/``ToolSearch`` calls) and the final
    assistant text block.
"""

from __future__ import annotations

import json
import re
from typing import Callable

from evals._harness.transcript import ToolCallEvent, Transcript

_FENCED_JSON = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_SOURCE_EDIT_TOOLS = ("Edit", "Write", "NotebookEdit")
_TRIGGERING_EXEMPT_TOOLS = ("Skill", "ToolSearch")


def review_match(
    finding: dict,
    *,
    file_suffix: str,
    regex: str,
    line_window: list[int] | None,
) -> bool:
    """Decide whether a finding credits a gated review item.

    Parameters
    ----------
    finding : dict
        A parsed finding with ``file``, ``line``, and ``description`` keys.
    file_suffix : str
        The item's file, matched with ``str.endswith``.
    regex : str
        Pattern matched (case-insensitively) against the finding's
        description.
    line_window : list[int] | None
        ``[start, end]`` inclusive line range for a line-level item; ``None``
        for a file-level item, where location is satisfied by the file
        suffix alone.

    Returns
    -------
    bool
        ``True`` only when both the location and the regex hit.
    """
    file_str = str(finding.get("file", ""))
    description = str(finding.get("description", ""))
    regex_hit = bool(re.search(regex, description, re.IGNORECASE))

    if line_window is None:
        location_hit = file_str.endswith(file_suffix)
    elif not file_str.endswith(file_suffix):
        location_hit = False
    else:
        line = finding.get("line")
        location_hit = isinstance(line, (int, float)) and not isinstance(line, bool) and (
            line_window[0] <= line <= line_window[1]
        )

    return location_hit and regex_hit


def extract_findings(final_text: str) -> tuple[list[dict], bool]:
    """Pull the ``findings`` list from the first JSON object in ``final_text``.

    Tries a fenced ```json block first, then the span from the first ``{``
    to the last ``}``.

    Parameters
    ----------
    final_text : str
        The agent's final reply text.

    Returns
    -------
    tuple[list[dict], bool]
        ``(findings, True)`` for the first candidate that parses and holds a
        ``findings`` list; ``([], False)`` when none does.
    """
    candidates = list(_FENCED_JSON.findall(final_text))
    brace_start = final_text.find("{")
    if brace_start != -1:
        candidates.append(final_text[brace_start : final_text.rfind("}") + 1])

    for candidate in candidates:
        try:
            envelope = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(envelope, dict):
            continue
        findings = envelope.get("findings")
        if isinstance(findings, list):
            return [f for f in findings if isinstance(f, dict)], True
    return [], False


def count_unmatched(findings: list[dict], items: list[dict]) -> int:
    """Count findings that credit no item (a trend field; never gates).

    Parameters
    ----------
    findings : list[dict]
        Findings extracted by ``extract_findings``.
    items : list[dict]
        Item specs, each with ``file_suffix``, ``regex``, and
        ``line_window`` keys matching ``review_match``'s parameters.

    Returns
    -------
    int
        How many findings match no item.
    """
    unmatched = 0
    for finding in findings:
        if not any(
            review_match(
                finding,
                file_suffix=item["file_suffix"],
                regex=item["regex"],
                line_window=item.get("line_window"),
            )
            for item in items
        ):
            unmatched += 1
    return unmatched


def precedes(
    events: list[ToolCallEvent],
    first: Callable[[ToolCallEvent], bool],
    then: Callable[[ToolCallEvent], bool],
) -> bool:
    """Generic ordering predicate over tool-call events.

    Parameters
    ----------
    events : list[ToolCallEvent]
        The events to search.
    first : Callable[[ToolCallEvent], bool]
        Matcher for the event that must come first.
    then : Callable[[ToolCallEvent], bool]
        Matcher for the event that must come after.

    Returns
    -------
    bool
        ``True`` iff some event satisfying ``first`` has an ordinal strictly
        below the first event satisfying ``then``. ``False`` if either never
        occurs.
    """
    first_ordinals = [event.ordinal for event in events if first(event)]
    then_ordinals = [event.ordinal for event in events if then(event)]
    if not first_ordinals or not then_ordinals:
        return False
    return min(first_ordinals) < min(then_ordinals)


def _is_test_path(file_path: str) -> bool:
    parts = file_path.split("/")
    name = parts[-1] if parts else file_path
    if name == "conftest.py":
        return True
    if name.startswith("test_") and name.endswith(".py"):
        return True
    if name.endswith("_test.py"):
        return True
    return "tests" in parts


def _is_source_edit(event: ToolCallEvent) -> bool:
    if event.name not in _SOURCE_EDIT_TOOLS:
        return False
    file_path = event.input.get("file_path", "") if isinstance(event.input, dict) else ""
    return not _is_test_path(str(file_path))


def _result_text(event: ToolCallEvent) -> str:
    if event.result is None:
        return ""
    content = event.result.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                parts.append(str(block.get("text", "")))
            else:
                parts.append(str(block))
        return "".join(parts)
    return "" if content is None else str(content)


def _is_test_failure(event: ToolCallEvent) -> bool:
    if event.name != "Bash":
        return False
    text = _result_text(event)
    if "error during collection" in text:
        return True
    return any(line.startswith("FAILED ") or line.startswith("ERROR ") for line in text.splitlines())


def test_failed_before_first_source_edit(events: list[ToolCallEvent]) -> bool:
    """Ordering predicate: a new/changed test failed before the first source edit.

    A source-edit event is an ``Edit``/``Write``/``NotebookEdit`` call whose
    ``input.file_path`` is not a test-file path (``test_*.py``, ``*_test.py``,
    ``conftest.py``, or any path with a ``tests/`` segment). A test-failure
    event is a ``Bash`` call whose matched result content contains a pytest
    failure marker (a line starting ``FAILED `` or ``ERROR ``, or the
    substring ``error during collection``).

    Parameters
    ----------
    events : list[ToolCallEvent]
        The transcript's tool-call events.

    Returns
    -------
    bool
        ``True`` only when a test-failure event's ordinal is strictly below
        the first source-edit event's ordinal. ``False`` (not indeterminate)
        when either kind never occurs — indeterminate is reserved for
        harness breakage, decided by the caller from ``Transcript.status``.
    """
    return precedes(events, _is_test_failure, _is_source_edit)


def skill_triggered_first(transcript: Transcript, skill: str) -> bool:
    """Triggering predicate: the rostered skill's ``Skill`` call ran first.

    Met when a ``Skill`` tool-call event naming ``skill`` has an ordinal
    position earlier than every other tool-call event in the transcript
    EXCEPT ``Skill``/``ToolSearch`` calls (the exemption applies to every
    such call, not only the rostered skill's own), and earlier than the
    ordinal position of the final assistant text block.

    Parameters
    ----------
    transcript : Transcript
        The parsed transcript.
    skill : str
        The rostered skill's name, matched against the ``Skill`` call's
        ``input["skill"]``.

    Returns
    -------
    bool
        ``True`` when met; ``False`` (unmet, not indeterminate) when no such
        ``Skill`` call occurs at all, or when it is preceded by a
        non-exempt tool call or by the final assistant text block.
    """
    skill_ordinals = [
        event.ordinal
        for event in transcript.events
        if event.name == "Skill"
        and isinstance(event.input, dict)
        and event.input.get("skill") == skill
    ]
    if not skill_ordinals:
        return False
    trigger_ordinal = min(skill_ordinals)

    other_ordinals = [
        event.ordinal for event in transcript.events if event.name not in _TRIGGERING_EXEMPT_TOOLS
    ]
    if other_ordinals and trigger_ordinal >= min(other_ordinals):
        return False

    if transcript.final_text_ordinal is not None and trigger_ordinal >= transcript.final_text_ordinal:
        return False

    return True
