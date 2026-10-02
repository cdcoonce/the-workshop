"""Scorers for the A1 settlement-review case.

Each scorer is ``scorer(evidence, **params) -> bool`` over #995's ``Evidence``.

``coverage_bound`` is the gate candidate: the case-agent's reply must hold a
``## Could not verify`` section that names a surface from ``surfaces.toml``.
Its location is that section (up to the next ``## `` heading) and its regex is
the surface pattern, so it credits only when the section exists AND a surface
is named inside it — #992's location-AND-regex conjunction, with a section in
place of a line window.

The three ``defect_*`` scorers are trend items. The reply is prose, not a JSON
envelope, so each splits the final reply into paragraph and list-item segments
and applies #992's ``review_match`` to each segment: the segment's file token
supplies the location and the segment's text is the described defect.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from evals._harness.dispatch import Evidence
from evals._harness.matchers import review_match

_SURFACES_PATH = Path(__file__).resolve().parent / "surfaces.toml"

_SECTION_HEADING = re.compile(r"^## Could not verify[ \t]*$", re.IGNORECASE | re.MULTILINE)
_NEXT_LEVEL_TWO_HEADING = re.compile(r"^## ", re.MULTILINE)
_LIST_ITEM_START = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")
_PY_PATH = re.compile(r"[\w./-]+\.py")


def _final_replies(evidence: Evidence) -> list[str]:
    return [transcript.final_text for transcript in evidence.transcripts]


def _could_not_verify_sections(text: str) -> list[str]:
    """Return the text under each ``## Could not verify`` heading in *text*.

    A section runs from the line after its heading up to the next line that
    starts with ``## `` (a ``### `` subheading does not end it), or the end of
    the text. A heading that is not at a line start is not a section.
    """
    sections: list[str] = []
    for heading in _SECTION_HEADING.finditer(text):
        rest = text[heading.end() :]
        following = _NEXT_LEVEL_TWO_HEADING.search(rest)
        sections.append(rest[: following.start()] if following else rest)
    return sections


def _surface_patterns() -> list[re.Pattern[str]]:
    """Compile one regex per listed file plus the production-data phrase class."""
    surfaces = tomllib.loads(_SURFACES_PATH.read_text(encoding="utf-8"))
    patterns = [
        # Any directory prefix is accepted, but the basename must stand alone:
        # `test_invoice.py` and `x.invoice.py` never name `invoice.py`.
        re.compile(rf"(?<![\w.-])(?:[\w.-]+/)*{re.escape(path.rsplit('/', 1)[-1])}(?!\w)", re.IGNORECASE)
        for path in surfaces["files"]
    ]
    patterns.extend(re.compile(phrase, re.IGNORECASE) for phrase in surfaces["phrase_class"])
    return patterns


def coverage_bound(evidence: Evidence) -> bool:
    """Credit a ``## Could not verify`` section that names a listed surface.

    Parameters
    ----------
    evidence : Evidence
        The attempt's evidence; only each transcript's final reply is read.

    Returns
    -------
    bool
        ``True`` only when some reply has the section (location) AND a
        ``surfaces.toml`` surface regex hits inside it. A missing or empty
        section, or a surface named only outside it, is a miss.
    """
    patterns = _surface_patterns()
    for reply in _final_replies(evidence):
        for section in _could_not_verify_sections(reply):
            if any(pattern.search(section) for pattern in patterns):
                return True
    return False


def _segments(text: str) -> list[str]:
    """Split *text* into blank-line-separated paragraphs, one per list item."""
    segments: list[str] = []
    for block in re.split(r"\n\s*\n", text):
        current: list[str] = []
        for line in block.splitlines():
            if _LIST_ITEM_START.match(line) and current:
                segments.append("\n".join(current))
                current = []
            current.append(line)
        if current:
            segments.append("\n".join(current))
    return [segment for segment in segments if segment.strip()]


def _defect_named(evidence: Evidence, *, file_suffix: str, regex: str) -> bool:
    """Whether one segment names the defect's file AND matches its regex.

    A file token such as ``invoice.py::line_total`` or ``src/settlement/rounding.py``
    is matched against *file_suffix* with a leading ``/`` so a bare basename
    still counts, and ``test_rounding.py`` is never taken for ``rounding.py``.
    """
    for reply in _final_replies(evidence):
        for segment in _segments(reply):
            for path in _PY_PATH.findall(segment):
                finding = {"file": "/" + path.lstrip("/"), "description": segment}
                if review_match(finding, file_suffix=file_suffix, regex=regex, line_window=None):
                    return True
    return False


def defect_decimal_from_float(evidence: Evidence, *, file_suffix: str, regex: str) -> bool:
    """Trend: the fix builds ``Decimal`` from a float, so it is a no-op for ``1.005``."""
    return _defect_named(evidence, file_suffix=file_suffix, regex=regex)


def defect_tests_no_teeth(evidence: Evidence, *, file_suffix: str, regex: str) -> bool:
    """Trend: the new tests stay green against ``main``'s implementation."""
    return _defect_named(evidence, file_suffix=file_suffix, regex=regex)


def defect_missed_call_site(evidence: Evidence, *, file_suffix: str, regex: str) -> bool:
    """Trend: ``invoice.py::line_total`` still calls bare ``round``."""
    return _defect_named(evidence, file_suffix=file_suffix, regex=regex)
