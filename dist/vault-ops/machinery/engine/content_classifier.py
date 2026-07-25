"""Content Classifier — classifies raw text into vault note categories.

Public interface:
    classify(text) → ClassificationResult
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

@dataclass
class ClassificationResult:
    """Result of classifying raw text."""
    category: str
    routing_hint: str
    suggested_folder: str
    suggested_template: str
    confidence: float  # 0.0 to 1.0


# ---------------------------------------------------------------------------
# Category definitions — ordered by priority (most specific first)
# Per CEO Review decision 5A:
#   incident > 1-1 > decision > win > project-update >
#   person-context > learning > side-project > project-idea > task > thought
# ---------------------------------------------------------------------------

@dataclass
class _CategoryDef:
    name: str
    patterns: list[re.Pattern[str]]
    folder: str
    template: str
    routing_hint: str


def _phrase(phrase: str) -> re.Pattern[str]:
    """Create a case-insensitive word-boundary pattern for a word or phrase."""
    return re.compile(rf"\b{re.escape(phrase)}\b", re.IGNORECASE)


CATEGORIES: list[_CategoryDef] = [
    _CategoryDef(
        name="incident",
        patterns=[
            _phrase("incident"), _phrase("outage"), _phrase("postmortem"), _phrase("post-mortem"),
            _phrase("root cause"), _phrase("downtime"), _phrase("severity"),
            _phrase("on-call"), _phrase("oncall"), _phrase("pager"), _phrase("alert"),
            _phrase("service degradation"), _phrase("data loss"),
        ],
        folder="work/incidents",
        template="Incident",
        routing_hint="Consider creating an incident report in work/incidents/",
    ),
    _CategoryDef(
        name="1-1",
        patterns=[
            _phrase("1:1"), _phrase("1-1"), _phrase("one on one"),
            _phrase("1 on 1"), _phrase("one-on-one"),
            _phrase("met with"), _phrase("meeting with"),
            _phrase("sync with"), _phrase("caught up with"),
            _phrase("check-in with"), _phrase("check in with"),
        ],
        folder="work/1-1",
        template="1-1 Note",
        routing_hint="Consider creating a 1:1 note in work/1-1/",
    ),
    _CategoryDef(
        name="decision",
        patterns=[
            _phrase("decided"), _phrase("decision"), _phrase("we chose"),
            _phrase("going with"), _phrase("opted for"),
            _phrase("trade-off"), _phrase("tradeoff"),
            _phrase("pros and cons"), _phrase("decided to"),
            _phrase("agreed to"), _phrase("settled on"),
        ],
        folder="work/decisions",
        template="Decision Record",
        routing_hint="Consider creating a decision record in work/decisions/",
    ),
    _CategoryDef(
        name="win",
        patterns=[
            _phrase("shipped"), _phrase("launched"), _phrase("completed"),
            _phrase("accomplished"), _phrase("delivered"),
            _phrase("great feedback"), _phrase("positive feedback"),
            _phrase("promoted"), _phrase("recognized"),
            _phrase("saved time"), _phrase("reduced cost"),
            _phrase("improved"), _phrase("milestone"),
            _phrase("shout-out"), _phrase("shoutout"), _phrase("kudos"),
        ],
        folder="perf",
        template="Work Note",
        routing_hint="Consider updating the Brag Doc and creating evidence in perf/",
    ),
    _CategoryDef(
        name="project-update",
        patterns=[
            _phrase("project update"), _phrase("status update"),
            _phrase("progress on"), _phrase("working on"),
            _phrase("sprint"), _phrase("blocker"),
            _phrase("next steps"), _phrase("roadmap"),
            _phrase("backlog"), _phrase("pipeline"),
            _phrase("deployed"), _phrase("merged"),
        ],
        folder="work/active/ad-hoc",
        template="Work Note",
        routing_hint="Prefer updating an existing project note (work/active/<cluster>/ or work/active/); if none fits, capture it in work/active/ad-hoc/ for later triage — it's a temporary inbox, not a permanent home.",
    ),
    _CategoryDef(
        name="person-context",
        patterns=[
            _phrase("works on"), _phrase("reports to"),
            _phrase("responsible for"), _phrase("their role"),
            _phrase("team lead"), _phrase("manager"),
            _phrase("cross-functional"), _phrase("stakeholder"),
            _phrase("new hire"), _phrase("joined the team"),
        ],
        folder="org/people",
        template="Person",
        routing_hint="Consider creating or updating a person profile in org/people/",
    ),
    _CategoryDef(
        name="learning",
        patterns=[
            _phrase("learned"), _phrase("learning"),
            _phrase("tutorial"), _phrase("course"),
            _phrase("studying"), _phrase("reading about"),
            _phrase("TIL"), _phrase("today I learned"),
            _phrase("documentation"), _phrase("how to"),
            _phrase("figured out"), _phrase("concept"),
        ],
        folder="personal/learning",
        template="Learning Note",
        routing_hint="Consider creating a learning note in personal/learning/",
    ),
    _CategoryDef(
        name="side-project",
        patterns=[
            _phrase("side project"), _phrase("personal project"),
            _phrase("hobby project"), _phrase("building"),
            _phrase("my app"), _phrase("my tool"),
            _phrase("weekend project"), _phrase("pet project"),
        ],
        folder="personal/projects",
        template="Side Project",
        routing_hint="Consider creating a side project note in personal/projects/",
    ),
    _CategoryDef(
        name="project-idea",
        patterns=[
            _phrase("what if"), _phrase("idea for"),
            _phrase("could build"), _phrase("might be cool"),
            _phrase("brainstorm"), _phrase("concept for"),
            _phrase("wouldn't it be"), _phrase("imagine"),
            _phrase("pitch"), _phrase("prototype"),
        ],
        folder="personal/ideas",
        template="Idea",
        routing_hint="Consider capturing this idea in personal/ideas/",
    ),
    _CategoryDef(
        name="task",
        patterns=[
            _phrase("need to"), _phrase("reminder"), _phrase("todo"),
            _phrase("to-do"), _phrase("pick up"), _phrase("buy"),
            _phrase("schedule"), _phrase("appointment"), _phrase("errand"),
            _phrase("don't forget"), _phrase("remember to"),
            _phrase("grocery"), _phrase("chore"),
        ],
        folder="personal/tasks",
        template="Task",
        routing_hint="Consider adding this as a task in personal/tasks/",
    ),
]

# Default fallback
DEFAULT_RESULT = ClassificationResult(
    category="thought",
    routing_hint="Consider saving this as a thinking note in thinking/",
    suggested_folder="thinking",
    suggested_template="Thinking Note",
    confidence=0.0,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify(text: str) -> ClassificationResult:
    """Classify raw text into a vault note category.

    Uses word-boundary regex matching with a priority-ordered category list.
    Most specific categories (incident, 1-1) are checked first.

    Args:
        text: Raw text to classify.

    Returns:
        ClassificationResult with category, routing hint, folder, and template.
    """
    if not text or not text.strip():
        return DEFAULT_RESULT

    best_category: _CategoryDef | None = None
    best_score = 0

    for cat_def in CATEGORIES:
        score = sum(1 for p in cat_def.patterns if p.search(text))
        # Strictly-greater comparison means ties keep the earlier (higher-priority)
        # category, since CATEGORIES is ordered most-specific-first.
        if score > 0 and (best_category is None or score > best_score):
            best_category = cat_def
            best_score = score

    if best_category is None:
        return DEFAULT_RESULT

    # Confidence: fixed-denominator so it's comparable ACROSS categories (#42).
    # Dividing by the category's own pattern count penalized keyword-rich
    # categories (a clear incident scored ~8%). K=3 means one keyword hit reads
    # as a tentative 33%, two as 67%, three+ as a confident 100% — the same scale
    # for every category, independent of its vocabulary size.
    CONFIDENCE_DENOM = 3
    confidence = min(best_score / CONFIDENCE_DENOM, 1.0)

    return ClassificationResult(
        category=best_category.name,
        routing_hint=best_category.routing_hint,
        suggested_folder=best_category.folder,
        suggested_template=best_category.template,
        confidence=confidence,
    )


def routing_hook_output(result: ClassificationResult) -> dict:
    """Build the contract-correct UserPromptSubmit hook payload for a classification.

    Claude Code's UserPromptSubmit hook expects ``hookSpecificOutput`` to be an
    OBJECT with ``hookEventName`` + ``additionalContext`` (the latter injected into
    the session's context). The previous classify-message.py emitted
    ``{"hookSpecificOutput": json.dumps({...})}`` — a JSON *string*, the wrong
    shape, so the routing hint was silently dropped (#81). This returns the right
    shape with a readable routing hint the session can act on.
    """
    summary = (
        f"[dump-router] This looks like a '{result.category}' note "
        f"({result.confidence:.0%} confidence). {result.routing_hint} "
        f"(folder: {result.suggested_folder}, template: {result.suggested_template})"
    )
    return {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": summary,
        }
    }
