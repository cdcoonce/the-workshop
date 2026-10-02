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
_PATH_TOKEN = re.compile(r"[\w./-]+")


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


def names_listed_file(text: str, files: list[str]) -> bool:
    """Whether *text* names one of the listed *files*, by path token.

    Backslashes are read as ``/`` first. A path token (a run of word
    characters, ``.``, ``/`` and ``-``) names a
    listed file when it is:

    - a trailing, segment-aligned suffix of the listed path (``src/settlement/invoice.py``,
      ``settlement/invoice.py``), with an optional leading ``./``;
    - the bare basename, only when exactly one listed file has that basename;
    - an absolute path that ends in the listed path in full.

    A directory the listed path does not have in that position
    (``legacy/invoice.py``, ``tests/__init__.py``) never names it, and neither
    does a stem without its extension (``invoice``, ``pytest``).
    """
    listed = [path.casefold() for path in files]
    basenames = [path.rsplit("/", 1)[-1] for path in listed]
    for raw in _PATH_TOKEN.findall(text.replace("\\", "/")):
        token = raw.casefold().rstrip(".-")
        token = token.removeprefix("./")
        for path, basename in zip(listed, basenames):
            if token.startswith("/"):
                if token.endswith("/" + path):
                    return True
                continue
            segments = path.split("/")
            for start in range(len(segments)):
                suffix = "/".join(segments[start:])
                is_bare = start == len(segments) - 1 and len(segments) > 1
                bare_and_ambiguous = is_bare and basenames.count(basename) > 1
                if token == suffix and not bare_and_ambiguous:
                    return True
    return False


def _surface_hit(section: str) -> bool:
    """Whether *section* names a listed file or matches the production-data phrase class."""
    surfaces = tomllib.loads(_SURFACES_PATH.read_text(encoding="utf-8"))
    if names_listed_file(section, surfaces["files"]):
        return True
    return any(re.search(phrase, section, re.IGNORECASE) for phrase in surfaces["phrase_class"])


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
        ``surfaces.toml`` surface (a listed file, or the production-data phrase
        class) is named inside it. A missing or empty
        section, or a surface named only outside it, is a miss.
    """
    for reply in _final_replies(evidence):
        for section in _could_not_verify_sections(reply):
            if _surface_hit(section):
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
