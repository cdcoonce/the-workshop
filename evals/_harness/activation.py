"""Parses a rostered eval skill's activation state from its checks.manifest and retired.md.

A rostered skill is one of the three this epic (#988) covers —
``adversarial-review``, ``tdd``, ``commit`` — fixed by the epic's own scope,
not derived from the filesystem: a directory under ``evals/`` is only a
rostered skill once its scaffolding lands, never inferred from what happens
to exist on disk.

A rostered skill is *active* once its ``checks.manifest`` lists at least one
gated ID, or its ``retired.md`` holds at least one entry; otherwise it is
*inactive*. Guards elsewhere in this package (``#997``, ``#1009``) gate
tier-change and staleness checks on this state, and parse both file formats
against a base revision as well as HEAD — hence the parsers below take file
text rather than a path.
"""

from __future__ import annotations

import re
from pathlib import Path

ROSTERED_SKILLS = ("adversarial-review", "tdd", "commit")

_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def parse_checks_manifest(text: str) -> list[str]:
    """Parse a ``checks.manifest`` file's text into its gated IDs.

    Parameters
    ----------
    text : str
        The ``checks.manifest`` file's contents.

    Returns
    -------
    list[str]
        Every gated ID, in file order. Blank lines and ``#``-comment lines
        are ignored; a non-comment line whose leading token does not match
        the ID grammar (``^[A-Za-z0-9][A-Za-z0-9._-]*$``) is skipped too.
    """
    ids: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        candidate = stripped.split(maxsplit=1)[0]
        if _ID_PATTERN.match(candidate):
            ids.append(candidate)
    return ids


def parse_retired_entries(text: str) -> list[dict[str, str]]:
    """Parse a ``retired.md`` file's text into its entries.

    Parameters
    ----------
    text : str
        The ``retired.md`` file's contents.

    Returns
    -------
    list[dict[str, str]]
        One dict per ``## <id>`` block, in file order, with an ``id`` key
        plus one key per ``- key: value`` line found inside that block
        (typically ``date``, ``reason``, ``evidence``).
    """
    entries: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            if current is not None:
                entries.append(current)
            current = {"id": stripped[3:].strip()}
        elif current is not None and stripped.startswith("- "):
            key, sep, value = stripped[2:].partition(":")
            if sep:
                current[key.strip()] = value.strip()
    if current is not None:
        entries.append(current)
    return entries


def is_active(skill_dir: Path) -> bool:
    """Return whether a rostered skill's eval directory is active.

    Parameters
    ----------
    skill_dir : Path
        A rostered skill's eval directory (e.g. ``evals/commit``).

    Returns
    -------
    bool
        ``True`` if ``<skill_dir>/checks.manifest`` lists at least one
        gated ID, or ``<skill_dir>/retired.md`` holds at least one
        ``## <id>`` block; ``False`` otherwise, including when either file
        is absent.
    """
    manifest_path = skill_dir / "checks.manifest"
    manifest_text = manifest_path.read_text(encoding="utf-8") if manifest_path.exists() else ""
    if parse_checks_manifest(manifest_text):
        return True

    retired_path = skill_dir / "retired.md"
    retired_text = retired_path.read_text(encoding="utf-8") if retired_path.exists() else ""
    return bool(parse_retired_entries(retired_text))
