#!/usr/bin/env python3
"""Stop hook — dispatch the background notebook distiller.

Rides the same per-turn Stop cadence as the auto-commit hook. It:
  1. Synchronously ensures a notebook stub exists for this session (so that
     a /clear → SessionStart can always find the file — the detached distill
     is too slow to win that race).
  2. Spawns ``notebook-distill.py`` DETACHED to do the full Haiku distill and
     overwrite the stub with enriched content.

Always exits 0 — a memory helper must never break the session.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from notebook_core import NOTEBOOK_SKELETON  # noqa: E402
from vault_utils import find_vault_root_from_env, read_vault_context  # noqa: E402


def ensure_stub(vault_root: Path, context: str, session_id: str) -> None:
    """Synchronously ensure a notebook file exists for this session.

    If the file already exists, leave it untouched (the existing content is
    more useful than a blank skeleton).  If it doesn't exist yet, write a
    minimal skeleton so that a /clear → SessionStart always finds a file
    before the slower detached distill finishes.
    """
    brain_dir = vault_root / ".brain"
    brain_dir.mkdir(parents=True, exist_ok=True)
    notebook = brain_dir / f"notebook-{context}-{session_id}.md"
    if notebook.exists():
        return  # already has content — leave it alone
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    sid = session_id[:8] if session_id else "unknown"
    notebook.write_text(
        NOTEBOOK_SKELETON.format(
            context_title=context.title(), stamp=stamp, sid=sid
        ),
        encoding="utf-8",
    )


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    transcript_path = event.get("transcript_path")
    session_id = event.get("session_id", "")
    if not transcript_path or not Path(transcript_path).exists():
        return 0

    vault_root = find_vault_root_from_env()
    if vault_root is None:
        return 0

    # Read vault context for the notebook path (canonical reader; 'unknown' if absent).
    context = read_vault_context(vault_root)

    # Step 1 — synchronous stub so /clear → SessionStart always finds the file.
    try:
        ensure_stub(vault_root, context, session_id)
    except OSError:
        pass  # fail-soft

    worker = SCRIPTS_DIR / "notebook-distill.py"
    if not worker.exists():
        return 0

    # Step 2 — detached full distill overwrites the stub with real content.
    popen_kwargs: dict = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "stdin": subprocess.DEVNULL,
    }
    if hasattr(os, "setsid"):
        popen_kwargs["start_new_session"] = True

    try:
        subprocess.Popen(
            [sys.executable, str(worker), str(transcript_path), str(session_id), str(vault_root)],
            **popen_kwargs,
        )
    except OSError:
        return 0

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # never break the session
