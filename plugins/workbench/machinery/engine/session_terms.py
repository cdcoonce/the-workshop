"""Helpers for session-stop term tracking.

Extracted from the hyphenated (non-importable) ``session-stop.py`` hook so the
"which files did this session actually change" logic is unit-testable — mirrors how
``transcript_backup.py`` was extracted from ``pre-compact.py``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def changed_files_since(vault_root: Path, pre_sha: str, timeout: int = 10) -> list[str]:
    """Vault-relative paths changed by commits made since ``pre_sha`` (i.e. this session).

    Returns ``[]`` when ``HEAD == pre_sha`` (no commit happened this session) — so an idle/no-op
    session records NO term frequency, instead of re-counting a prior commit's files. The old
    ``git diff HEAD~1 HEAD`` ran unconditionally and counted the previous commit on no-op sessions,
    drifting terms toward spurious promotion. Diffing ``pre_sha..HEAD`` is also correct across
    multi-commit sessions. Fail-soft: ``[]`` on any error.
    """
    if not pre_sha:
        return []
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=vault_root,
            capture_output=True, text=True, check=False, timeout=timeout,
        ).stdout.strip()
        if not head or head == pre_sha:
            return []
        diff = subprocess.run(
            ["git", "diff", "--name-only", f"{pre_sha}..{head}"], cwd=vault_root,
            capture_output=True, text=True, check=False, timeout=timeout,
        )
        if diff.returncode != 0:
            return []
        return [f for f in diff.stdout.splitlines() if f.strip()]
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return []
