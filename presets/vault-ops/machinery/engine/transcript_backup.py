"""Transcript backup + retention — importable core of the PreCompact hook.

Extracted from pre-compact.py so the destructive retention logic and the
backup naming convention are unit-testable (the hook file is hyphenated and
therefore not importable).

Public interface:
    enforce_retention(log_dir, max_backups) -> None
    backup_transcript(source, log_dir, trigger, timestamp) -> Path | None

The retention glob (``session_*.jsonl``) and the filename produced by
``backup_transcript`` are intentionally coupled: every backup this module
creates must be matched by the retention glob.
"""

from __future__ import annotations

import shutil
import traceback
from pathlib import Path

DEFAULT_MAX_BACKUPS = 10

# Glob used to enumerate existing backups for retention. Must match the names
# produced by backup_transcript().
RETENTION_GLOB = "session_*.jsonl"


def enforce_retention(log_dir: Path, max_backups: int = DEFAULT_MAX_BACKUPS) -> None:
    """Keep only the most recent ``max_backups`` session logs.

    Deletes the oldest files (by mtime) beyond the cap. Missing directories
    and individual unlink failures are tolerated silently — retention must
    never crash the hook.
    """
    if not log_dir.is_dir():
        return

    logs = sorted(log_dir.glob(RETENTION_GLOB), key=lambda p: p.stat().st_mtime)
    while len(logs) > max_backups:
        oldest = logs.pop(0)
        try:
            oldest.unlink()
        except OSError:
            pass


def backup_transcript(
    source: Path, log_dir: Path, trigger: str, timestamp: str
) -> Path | None:
    """Copy ``source`` transcript into ``log_dir`` as ``session_<trigger>_<timestamp>.jsonl``.

    Returns the destination path on success, or None if the source is missing
    or the copy fails. Creates ``log_dir`` if needed.
    """
    if not source.exists():
        return None

    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        traceback.print_exc()
        return None

    dest = log_dir / f"session_{trigger}_{timestamp}.jsonl"
    try:
        shutil.copy2(str(source), str(dest))
    except (OSError, shutil.Error):
        traceback.print_exc()
        return None

    return dest
