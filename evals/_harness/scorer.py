"""Pure scoring rules for one eval fixture's attempts.

This module is pure: no dispatch, no I/O beyond its arguments, and it never
executes a fixture, dispatches a subagent, or calls a model. Running a
fixture and driving the retry loop belongs to the conductor (#995); this
module only classifies the results it is handed.

Public contract
----------------
``classify_attempt(transcript_status, envelope_parsed, item_hits) -> Attempt``
    Classifies one attempt of one fixture. Returns a hit/miss/indeterminate
    verdict for every gated item passed in ``item_hits``. Harness breakage —
    a dispatch error, a missing/truncated transcript, or an API-error
    transcript entry (any ``transcript_status`` other than ``"complete"``) —
    is classified indeterminate for every item in that attempt. A complete
    transcript whose envelope failed to parse (``envelope_parsed`` is
    ``False``) is scored a miss for every item in that attempt and sets
    ``parse_error`` on the returned ``Attempt``.

``should_retry(item_states, counted_attempts, reserve_used) -> bool``
    Returns ``True`` while any gated item's union-across-attempts state (from
    ``item_states``) is still unmet. Returns ``False`` once ``counted_attempts``
    reaches 3, or once ``counted_attempts + reserve_used`` reaches the
    fixture's execution cap of 5, whichever comes first. Indeterminate
    attempts never increment ``counted_attempts``; they are drawn from a
    reserve of 2 attempts per fixture, and ``reserve_used`` tracks how many of
    that reserve have been drawn.

``compute_verdict(items) -> "green" | "red" | "void"``
    Green only when every gated item's union-across-attempts state is a hit;
    red when any gated item missed all 3 counted attempts; void when any
    gated item is still indeterminate after the reserve of 2 is exhausted —
    the void threshold is zero, so exactly one such item is enough to void
    the run. A trend item ending indeterminate never voids the run.
    Precedence: if any gated item is red, the run is red, even when another
    gated item is void; otherwise the run is void if any gated item is void;
    otherwise it is green.

Data shapes
-----------
``transcript_status`` is one of ``"complete"``, ``"dispatch_error"``,
``"missing"``, ``"truncated"``, ``"api_error"`` — every value but
``"complete"`` is harness breakage.

``item_hits`` (an input to ``classify_attempt``) maps item id -> bool.

``Attempt`` is a frozen dataclass with ``classification`` (``"counted"`` or
``"indeterminate"``), ``item_hits: dict[str, str]`` (item id ->
``"hit"``, ``"miss"``, or ``"indeterminate"``), and ``parse_error: bool``.

``should_retry``'s ``item_states`` maps each gated item id -> ``True`` once
any counted attempt hit it.

``compute_verdict``'s ``items`` maps item id -> ``(gated: bool, outcomes:
list[str])``, one ``"hit"``/``"miss"``/``"indeterminate"`` per execution of
its fixture. Gated versus trend is never this module's call: every item
arrives with a caller-supplied ``gated`` flag (the conductor derives it from
the skill's ``checks.manifest``), and ``compute_verdict`` applies green/red/
void to gated items only. This module never reads ``checks.manifest`` or
``case.toml``, and ``envelope_parsed`` is likewise supplied by the caller —
this module never parses an envelope itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

TranscriptStatus = Literal["complete", "dispatch_error", "missing", "truncated", "api_error"]
Classification = Literal["counted", "indeterminate"]
ItemOutcome = Literal["hit", "miss", "indeterminate"]
Verdict = Literal["green", "red", "void"]

_COUNTED_ATTEMPT_CAP = 3
_EXECUTION_CAP = 5


@dataclass(frozen=True)
class Attempt:
    """The scored result of one fixture attempt."""

    classification: Classification
    item_hits: dict[str, ItemOutcome]
    parse_error: bool = False


def classify_attempt(
    transcript_status: TranscriptStatus,
    envelope_parsed: bool,
    item_hits: dict[str, bool],
) -> Attempt:
    """Classify one attempt of one fixture.

    Parameters
    ----------
    transcript_status : TranscriptStatus
        The state of this attempt's transcript. Any value other than
        ``"complete"`` is harness breakage.
    envelope_parsed : bool
        Whether the caller (#995's ``dispatch.score_attempt``) successfully
        parsed a findings envelope out of the transcript. Ignored when
        ``transcript_status`` is not ``"complete"``.
    item_hits : dict[str, bool]
        Item id -> whether that item was caught, as extracted by the caller.
        Ignored when the attempt did not reach a parsed envelope.

    Returns
    -------
    Attempt
        The classified attempt.
    """
    if transcript_status != "complete":
        return Attempt(
            classification="indeterminate",
            item_hits={item_id: "indeterminate" for item_id in item_hits},
            parse_error=False,
        )
    if not envelope_parsed:
        return Attempt(
            classification="counted",
            item_hits={item_id: "miss" for item_id in item_hits},
            parse_error=True,
        )
    return Attempt(
        classification="counted",
        item_hits={item_id: ("hit" if hit else "miss") for item_id, hit in item_hits.items()},
        parse_error=False,
    )


def should_retry(
    item_states: dict[str, bool],
    counted_attempts: int,
    reserve_used: int,
) -> bool:
    """Decide whether another attempt should be dispatched for this fixture.

    Parameters
    ----------
    item_states : dict[str, bool]
        Gated item id -> whether any counted attempt has hit it so far.
    counted_attempts : int
        How many attempts so far were classified ``"counted"``.
    reserve_used : int
        How many of the fixture's 2-attempt indeterminate reserve have been
        drawn so far.

    Returns
    -------
    bool
        ``True`` if any gated item is still unmet and neither cap has been
        reached; ``False`` otherwise.
    """
    if all(item_states.values()):
        return False
    if counted_attempts >= _COUNTED_ATTEMPT_CAP:
        return False
    if counted_attempts + reserve_used >= _EXECUTION_CAP:
        return False
    return True


def _item_verdict(outcomes: list[str]) -> Literal["hit", "red", "void"]:
    """Reduce one gated item's per-attempt outcomes to its run-level state.

    A ``"miss"`` entry corresponds to one counted attempt that missed this
    item — every item in a given attempt is classified the same way, so
    counting ``"miss"`` strings directly answers "how many counted attempts
    missed this item". Never hit and fewer than 3 misses means the run ended
    while this item was still indeterminate — the reserve of 2 exhausted
    without a resolving hit or a third miss.
    """
    if "hit" in outcomes:
        return "hit"
    if outcomes.count("miss") >= _COUNTED_ATTEMPT_CAP:
        return "red"
    return "void"


def compute_verdict(items: dict[str, tuple[bool, list[str]]]) -> Verdict:
    """Compute the fixture-level verdict from every item's outcomes.

    Parameters
    ----------
    items : dict[str, tuple[bool, list[str]]]
        Item id -> ``(gated, outcomes)``, where ``outcomes`` is one
        ``"hit"``/``"miss"``/``"indeterminate"`` per execution of the
        fixture. Trend items (``gated`` is ``False``) never affect the
        verdict.

    Returns
    -------
    Verdict
        ``"green"``, ``"red"``, or ``"void"``.
    """
    gated_states = [_item_verdict(outcomes) for gated, outcomes in items.values() if gated]
    if "red" in gated_states:
        return "red"
    if "void" in gated_states:
        return "void"
    return "green"
