"""Note lifecycle — deterministic, no-LLM status transitions for vault notes.

The only status transition safe to automate is one whose trigger is *already
encoded in frontmatter*. Meeting-prep notes qualify: a prep note's ``date`` is
the meeting date, so once it has passed the prep is objectively done. Every other
transition (incident active→resolved, project active→paused, decision
proposed→decided) reflects a real-world change only a human knows about, so it is
deliberately NOT handled here.

Triggered by ``/standup`` (the same seam as the weekly task rollover). Idempotent:
re-running the same day is a no-op. See ``work/CLAUDE.md`` → "Stale prep sweep".

Public API:
    sweep_stale_prep(vault_root, today?) -> dict
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

_FM_DELIM = "---"
_DATE_RE = re.compile(r"^date:\s*(\d{4}-\d{2}-\d{2})\s*$")
_STATUS_ACTIVE_RE = re.compile(r"^status:\s*active\s*$")
_PREP_TAG_RE = re.compile(r"^\s*-\s*meeting-prep\s*$")


def _frontmatter_end(lines: list[str]) -> int | None:
    """Return the index of the closing ``---`` of the leading frontmatter block."""
    if not lines or lines[0].rstrip("\n") != _FM_DELIM:
        return None
    for i in range(1, len(lines)):
        if lines[i].rstrip("\n") == _FM_DELIM:
            return i
    return None


def sweep_stale_prep(vault_root: Path, today: date | None = None) -> dict:
    """Flip ``meeting-prep`` notes whose meeting date has passed to ``completed``.

    A note is flipped only when all three hold: it carries the ``meeting-prep``
    tag, its ``status`` is ``active``, and its ``date`` is strictly before
    ``today``. Only the status line is rewritten — the rest of the file is left
    byte-for-byte intact — so the change is safe and reversible.

    Args:
        vault_root: Vault root directory.
        today: Reference date (defaults to ``date.today()``); injectable for tests.

    Returns:
        dict with ``flipped`` (list of vault-relative paths changed this run) and
        ``count``.
    """
    today = today or date.today()
    vault_root = Path(vault_root)
    work_dir = vault_root / "work"
    flipped: list[str] = []
    if not work_dir.exists():
        return {"flipped": [], "count": 0}

    for path in sorted(work_dir.rglob("*.md")):
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        end = _frontmatter_end(lines)
        if end is None:
            continue
        fm = lines[1:end]

        if not any(_PREP_TAG_RE.match(line.rstrip("\n")) for line in fm):
            continue
        status_idx = next(
            (i for i, line in enumerate(fm) if _STATUS_ACTIVE_RE.match(line.rstrip("\n"))),
            None,
        )
        if status_idx is None:
            continue
        meeting_date = next(
            (m.group(1) for line in fm if (m := _DATE_RE.match(line.rstrip("\n")))),
            None,
        )
        if meeting_date is None or date.fromisoformat(meeting_date) >= today:
            continue

        newline = "\n" if fm[status_idx].endswith("\n") else ""
        fm[status_idx] = f"status: completed{newline}"
        path.write_text("".join([lines[0], *fm, *lines[end:]]), encoding="utf-8")
        flipped.append(str(path.relative_to(vault_root)))

    return {"flipped": flipped, "count": len(flipped)}
