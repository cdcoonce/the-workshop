"""The scorer for the ``commit/C-trig`` triggering fixture.

``C-trig`` (``kind = "triggering"``, ``triggered_first``)
    Met when the rostered skill's ``Skill`` call precedes every other tool call
    except ``Skill``/``ToolSearch`` calls and precedes the final assistant text.
    The ordering is #992's ``matchers.skill_triggered_first``, imported and called
    as is; nothing here reimplements it.

The case is ``mode = "subagent"``, so an attempt carries exactly one transcript. An
attempt with none, or with more than one, is a miss rather than a guess at which
transcript was meant. Nothing here runs a model.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from evals._harness.matchers import skill_triggered_first

if TYPE_CHECKING:
    from evals._harness.dispatch import Evidence


def triggered_first(evidence: Evidence, *, skill: str) -> bool:
    """Score the triggering item.

    Parameters
    ----------
    evidence : Evidence
        The attempt's evidence; only its single transcript is read.
    skill : str
        The rostered skill's name, from the item's ``params``.

    Returns
    -------
    bool
        ``True`` only when ``skill_triggered_first`` holds for the attempt's one
        transcript; ``False`` for any other number of transcripts.
    """
    if len(evidence.transcripts) != 1:
        return False
    return skill_triggered_first(evidence.transcripts[0], skill)
