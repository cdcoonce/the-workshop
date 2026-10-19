"""Direct tests for the SubagentStart baseline hook's own edge cases.

``test_subagent_evidence_hooks.py`` covers the start/stop pair end to end; this
file pins the start half's failure paths: a non-git cwd writes nothing, a normal
run writes the expected baseline fields, and an unwritable state directory fails
open instead of crashing.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

START_HOOK = (
    Path(__file__).resolve().parents[1]
    / "plugins"
    / "workbench"
    / "hooks"
    / "scripts"
    / "snapshot-subagent-start.py"
)


def _state_key(raw: str) -> str:
    import importlib.util

    spec = importlib.util.spec_from_file_location("_git_baseline", START_HOOK.parent / "_git_baseline.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.state_key(raw)


def _run(payload: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(START_HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
    )


def _init_repo(path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    return path / ".git"


def test_non_git_cwd_exits_silently_and_writes_no_state(tmp_path: Path) -> None:
    result = _run({"cwd": str(tmp_path), "agent_id": "a1"})

    assert result.returncode == 0
    assert result.stderr == ""
    assert not any(tmp_path.rglob("the-workshop-subagent-gate"))


def test_normal_run_writes_baseline_head_and_signature_lines(tmp_path: Path) -> None:
    git_dir = _init_repo(tmp_path)

    result = _run({"cwd": str(tmp_path), "agent_id": "a1"})

    assert result.returncode == 0
    state = git_dir / "the-workshop-subagent-gate" / f"{_state_key('a1')}.txt"
    lines = state.read_text().split("\n")
    # No commits yet: HEAD is unresolvable and must be normalized to "", never
    # the literal "None". The signature line is a non-empty hex digest.
    assert lines[0] == ""
    assert len(lines[1]) == 64 and all(c in "0123456789abcdef" for c in lines[1])
    assert lines[2:] == [""]


def test_unwritable_state_dir_fails_open_without_traceback(tmp_path: Path) -> None:
    git_dir = _init_repo(tmp_path)
    # A regular file where the state directory belongs makes mkdir raise OSError.
    (git_dir / "the-workshop-subagent-gate").write_text("blocker")

    result = _run({"cwd": str(tmp_path), "agent_id": "a1"})

    assert result.returncode == 0
    assert "Traceback" not in result.stderr
    assert (git_dir / "the-workshop-subagent-gate").read_text() == "blocker"
