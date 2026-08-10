"""Term Tracker — Frequency counting and promote/demote for Quick-Reference.

Public interface:
    load_frequencies(vault_root) -> dict
    save_frequencies(vault_root, data) -> None
    record_terms(vault_root, terms) -> None
    get_promotions(vault_root, quick_ref_names) -> list[str]
    get_demotions(vault_root, quick_ref_names) -> list[str]
    PROMOTE_THRESHOLD  (int) — sessions needed to promote to Quick-Reference
    DEMOTE_THRESHOLD   (int) — sessions at or below this flag for removal
"""

from __future__ import annotations

import json
from pathlib import Path

PROMOTE_THRESHOLD: int = 5
DEMOTE_THRESHOLD: int = 0

_FREQ_REL_PATH = Path(".claude") / "data" / "term-frequency.json"


def _freq_path(vault_root: Path) -> Path:
    return vault_root / _FREQ_REL_PATH


def load_frequencies(vault_root: Path) -> dict:
    """Load term-frequency.json. Returns {} if file missing or corrupt."""
    path = _freq_path(vault_root)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        return {}


def save_frequencies(vault_root: Path, data: dict) -> None:
    """Write term-frequency.json with indent=2. Creates parent dirs."""
    path = _freq_path(vault_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def record_terms(vault_root: Path, terms: list[str]) -> None:
    """Record that these terms appeared in the current session.

    Called once per session with every occurrence of each term — the input
    list MAY contain duplicates, one element per occurrence. The two fields
    carry distinct meanings:

    - ``count``    — total occurrences seen across all time. Increments by the
                     number of times the term appears in this call.
    - ``sessions`` — number of distinct sessions the term appeared in.
                     Increments by exactly 1 per distinct term per call.
    """
    data = load_frequencies(vault_root)
    occurrences: dict[str, int] = {}
    for term in terms:  # count occurrences, preserve first-seen order
        occurrences[term] = occurrences.get(term, 0) + 1
    for term, n in occurrences.items():
        if term in data:
            data[term]["count"] += n
            data[term]["sessions"] += 1
        else:
            data[term] = {"count": n, "sessions": 1}
    save_frequencies(vault_root, data)


def get_promotions(vault_root: Path, quick_ref_names: set[str] | list[str]) -> list[str]:
    """Return terms with sessions >= PROMOTE_THRESHOLD that are NOT in quick_ref_names.

    Comparison is case-insensitive to handle casing differences between
    frequency data keys and Quick-Reference entry names.
    """
    data = load_frequencies(vault_root)
    ref_lower = {n.lower() for n in quick_ref_names}
    return [
        term
        for term, info in data.items()
        if info.get("sessions", 0) >= PROMOTE_THRESHOLD
        and term.lower() not in ref_lower
    ]


def get_demotions(vault_root: Path, quick_ref_names: set[str] | list[str]) -> list[str]:
    """Return quick_ref names with sessions <= DEMOTE_THRESHOLD or absent from data.

    Comparison is case-insensitive.
    """
    data = load_frequencies(vault_root)
    data_lower = {k.lower(): v for k, v in data.items()}
    return [
        name
        for name in quick_ref_names
        if name.lower() not in data_lower
        or data_lower[name.lower()].get("sessions", 0) <= DEMOTE_THRESHOLD
    ]
