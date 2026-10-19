"""A non-string `cwd` in a hook payload must fail open, not crash (#1063).

`Path(5)` raises TypeError before any surrounding try/except runs, so each hook
that resolves `cwd` from the payload guards the value itself. One test per hook
site: the value is replaced by a non-string and the hook must exit 0 with no
traceback, as it does for a missing `cwd`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "plugins" / "workbench" / "hooks" / "scripts"

# Minimal well-formed payload per hook, so the run reaches the cwd line and
# keeps going past it (an early exit would hide a missing guard).
SITES = {
    "audit-config-change.py": {"file_path": "settings.json", "config_source": "user_settings"},
    "snapshot-subagent-start.py": {"agent_id": "a1"},
    "verify-subagent-evidence.py": {"agent_id": "a1", "last_assistant_message": "I fixed it."},
    "verify-tests-before-stop.py": {},
    "warn-off-trunk.py": {},
}

BAD_CWDS = {"int": 5, "list": ["x"], "dict": {"a": 1}, "bool": True, "float": 1.5}


@pytest.mark.parametrize("label", sorted(BAD_CWDS))
@pytest.mark.parametrize("hook", sorted(SITES))
def test_non_string_cwd_fails_open(hook: str, label: str, tmp_path: Path) -> None:
    payload = {**SITES[hook], "cwd": BAD_CWDS[label]}
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / hook)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=60,
        cwd=tmp_path,
        env=os.environ | {"CLAUDE_PROJECT_DIR": str(tmp_path)},
    )
    assert result.returncode == 0, f"{hook}: {result.stderr[-400:]}"
    assert "Traceback" not in result.stderr
