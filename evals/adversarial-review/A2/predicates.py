"""Scorers for the A2 doctored-PR case, built on #992's conjunctive ``review_match``.

Every scorer is ``scorer(evidence, **params) -> bool`` over ``evidence.findings``:
the union of the findings every lens agent returned. An item is credited only
when some finding hits BOTH its location (the item's file suffix, plus its line
window when it has one) AND its regex. An empty reply, an unparseable reply, or
findings about something else credit nothing.

The file suffix is matched segment-aligned: ``legacy_scripts/x.py`` is not
``scripts/x.py``. Backslash separators are normalised first, and a diff-style
``a/`` or ``b/`` prefix is just another leading path segment.
"""

from __future__ import annotations

from evals._harness.dispatch import Evidence
from evals._harness.matchers import review_match


def _aligned_file(raw: object, file_suffix: str) -> str:
    """Return the finding's path with ``/`` separators, or ``""`` if it is not ``file_suffix``.

    Parameters
    ----------
    raw : object
        The finding's ``file`` value.
    file_suffix : str
        The item's file suffix, ``/``-separated.

    Returns
    -------
    str
        The normalised path when it equals the suffix or ends with ``/`` plus the
        suffix; the empty string otherwise (which ``review_match`` then rejects).
    """
    path = str(raw).replace("\\", "/")
    if path == file_suffix or path.endswith("/" + file_suffix):
        return path
    return ""


def _credited(
    evidence: Evidence,
    *,
    file_suffix: str,
    regex: str,
    line_window: list[int] | None = None,
) -> bool:
    """Whether any lens finding hits the item's location AND its regex."""
    return any(
        review_match(
            {**finding, "file": _aligned_file(finding.get("file", ""), file_suffix)},
            file_suffix=file_suffix,
            regex=regex,
            line_window=line_window,
        )
        for finding in evidence.findings
    )


def pushed_prefix_off_by_one(evidence: Evidence, **params) -> bool:
    """D1: ``classify_pushed_prefix`` returns ``first_unpushed + 1``."""
    return _credited(evidence, **params)


def ancestor_argument_swap(evidence: Evidence, **params) -> bool:
    """D2: ``_is_ancestor(remote_head, sha)`` has its arguments swapped."""
    return _credited(evidence, **params)


def weakened_collapse_assertion(evidence: Evidence, **params) -> bool:
    """D3 (trend): the collapse test asserts ``len(session) >= 1``."""
    return _credited(evidence, **params)


def anti_scope_edit(evidence: Evidence, **params) -> bool:
    """D4: the diff edits ``vault-sync/references/command.md``, which the spec leaves untouched."""
    return _credited(evidence, **params)


def missing_staged_guard(evidence: Evidence, **params) -> bool:
    """D5: the specced staged-but-uncommitted guard is missing."""
    return _credited(evidence, **params)
