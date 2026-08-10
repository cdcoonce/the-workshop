#!/usr/bin/env python3
"""PreCompact hook — backs up session transcript before context compaction.

Reads hook event JSON from stdin (includes transcript_path and trigger).
Copies transcript to thinking/session-logs/ with retention of 10 files.

Exit codes:
    0 — backup successful (or gracefully skipped)
"""

from __future__ import annotations

import json
import sys
import traceback
from datetime import datetime
from pathlib import Path


# Add scripts dir to path
SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from transcript_backup import DEFAULT_MAX_BACKUPS, backup_transcript, enforce_retention
from vault_utils import find_vault_root_from_env

MAX_BACKUPS = DEFAULT_MAX_BACKUPS


def main() -> int:
    vault_root = find_vault_root_from_env()
    if vault_root is None:
        return 0

    # Read event from stdin
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return 0
        event = json.loads(raw)
    except Exception:
        return 0

    transcript_path = event.get("transcript_path", "")
    trigger = event.get("trigger", "unknown")

    if not transcript_path:
        return 0

    source = Path(transcript_path)
    if not source.exists():
        return 0

    # Create backup
    log_dir = vault_root / "thinking" / "session-logs"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    dest = backup_transcript(source, log_dir, trigger, timestamp)
    if dest is None:
        return 0

    # Enforce retention
    enforce_retention(log_dir, MAX_BACKUPS)

    # PreCompact has no hookSpecificOutput variant — systemMessage is the
    # only schema-valid user-visible channel for this event.
    print(json.dumps({
        "systemMessage": (
            f"✓ Session transcript backed up to {dest.name}\n"
            "↪ Before this compaction takes effect, refresh the rolling handoff so "
            "post-compaction context resumes cleanly: run /handoff (it rewrites "
            ".brain/handoff-<context>.md as a lean digest — where we are, what's "
            "running, open threads, next steps, mode — overwriting in place)."
        )
    }))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc(file=sys.stderr)
        sys.exit(0)  # Don't block on backup failure
