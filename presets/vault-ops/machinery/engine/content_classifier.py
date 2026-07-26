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


from content_routing_defaults import CATEGORIES as _DEFAULT_CATEGORIES
from content_routing_defaults import DEFAULT_CATEGORY as _DEFAULT_DEFAULT_CATEGORY

try:  # Scaffold-owned config; absent in a vault vendored before it existed.
    from content_routing import CATEGORIES as _RAW_CATEGORIES
    from content_routing import DEFAULT_CATEGORY as _RAW_DEFAULT_CATEGORY
except ImportError:
    _RAW_CATEGORIES = _DEFAULT_CATEGORIES
    _RAW_DEFAULT_CATEGORY = _DEFAULT_DEFAULT_CATEGORY


def _compile_category(raw: dict) -> _CategoryDef:
    """Compile one config category (plain dict, phrase strings) for matching."""
    return _CategoryDef(
        name=raw["name"],
        patterns=[_phrase(p) for p in raw["phrases"]],
        folder=raw["folder"],
        template=raw["template"],
        routing_hint=raw["routing_hint"],
    )


# Priority-ordered routing table, sourced from the scaffolded config when
# present, shipped defaults otherwise (content_routing_defaults documents the
# ordering contract).
CATEGORIES: list[_CategoryDef] = [_compile_category(c) for c in _RAW_CATEGORIES]

# Default fallback when nothing scores above zero.
DEFAULT_RESULT = ClassificationResult(
    category=_RAW_DEFAULT_CATEGORY["name"],
    routing_hint=_RAW_DEFAULT_CATEGORY["routing_hint"],
    suggested_folder=_RAW_DEFAULT_CATEGORY["folder"],
    suggested_template=_RAW_DEFAULT_CATEGORY["template"],
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
