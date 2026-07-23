"""Tests for the snapshot-subagent-start / verify-subagent-evidence hook pair.

Drives both hooks as real subprocesses against a scratch git repo: the start
hook records a baseline, the stop hook compares against it.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
START_HOOK = REPO_ROOT / "core" / "hooks" / "snapshot-subagent-start.py"
STOP_HOOK = REPO_ROOT / "core" / "hooks" / "verify-subagent-evidence.py"


def run(hook_path: Path, payload) -> subprocess.CompletedProcess[str]:
    stdin = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run(
        [sys.executable, str(hook_path)],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)


def start(cwd: Path, agent_id: str) -> None:
    result = run(START_HOOK, {"cwd": str(cwd), "agent_id": agent_id})
    assert result.returncode == 0


@pytest.mark.parametrize("payload", ["", "not json", "{ broken"])
def test_start_hook_fails_open_on_malformed_stdin(payload: str) -> None:
    result = run(START_HOOK, payload)
    assert result.returncode == 0
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("payload", ["", "not json", "{ broken"])
def test_stop_hook_fails_open_on_malformed_stdin(payload: str) -> None:
    result = run(STOP_HOOK, payload)
    assert result.returncode == 0
    assert "Traceback" not in result.stderr


def test_no_completion_claim_never_checks_git(tmp_path: Path) -> None:
    # No git repo at all — if the hook tried to shell out to git it would
    # still fail open, but this also proves the message-gate short-circuits.
    result = run(
        STOP_HOOK,
        {
            "cwd": str(tmp_path),
            "agent_id": "a1",
            "last_assistant_message": "Here's what I found during exploration.",
        },
    )
    assert result.returncode == 0
    assert result.stdout == ""


def test_no_baseline_snapshot_fails_open(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    # No start hook ran for this agent_id — nothing to compare against.
    result = run(
        STOP_HOOK,
        {
            "cwd": str(tmp_path),
            "agent_id": "never-started",
            "last_assistant_message": "I've implemented the fix.",
        },
    )
    assert result.returncode == 0
    assert result.stdout == ""


def test_claim_with_no_git_change_is_blocked(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    (tmp_path / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)

    start(tmp_path, "agent-1")

    result = run(
        STOP_HOOK,
        {
            "cwd": str(tmp_path),
            "agent_id": "agent-1",
            "last_assistant_message": "I've fixed the bug and all tests pass.",
        },
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["decision"] == "block"
    assert "reason" in payload


def test_claim_with_real_working_tree_change_is_not_blocked(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    (tmp_path / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)

    start(tmp_path, "agent-2")
    (tmp_path / "fix.py").write_text("def fixed(): return True\n")

    result = run(
        STOP_HOOK,
        {
            "cwd": str(tmp_path),
            "agent_id": "agent-2",
            "last_assistant_message": "I've implemented the fix.",
        },
    )

    assert result.returncode == 0
    assert result.stdout == ""


def test_claim_with_new_commit_is_not_blocked(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    (tmp_path / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)

    start(tmp_path, "agent-3")
    (tmp_path / "fix.py").write_text("def fixed(): return True\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "fix"], cwd=tmp_path, check=True)

    result = run(
        STOP_HOOK,
        {
            "cwd": str(tmp_path),
            "agent_id": "agent-3",
            "last_assistant_message": "I've committed the fix.",
        },
    )

    assert result.returncode == 0
    assert result.stdout == ""


def test_state_file_is_consumed_after_stop_check(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    (tmp_path / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)

    start(tmp_path, "agent-4")
    state_file = tmp_path / ".git" / "the-workshop-subagent-gate" / "agent-4.txt"
    assert state_file.exists()

    run(
        STOP_HOOK,
        {
            "cwd": str(tmp_path),
            "agent_id": "agent-4",
            "last_assistant_message": "I've fixed the bug.",
        },
    )

    assert not state_file.exists()


def test_mention_of_verb_without_first_person_claim_not_blocked(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    (tmp_path / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)

    start(tmp_path, "agent-5")

    result = run(
        STOP_HOOK,
        {
            "cwd": str(tmp_path),
            "agent_id": "agent-5",
            "last_assistant_message": "No fix needed — the existing behavior is correct.",
        },
    )

    assert result.returncode == 0
    assert result.stdout == ""


def test_snapshot_serializes_empty_strings_not_none(tmp_path: Path) -> None:
    """The pair must agree on how a failed git read is written to disk.

    The helpers return None on failure; the start hook writes those values into
    a state file and the stop hook reads them back as strings and compares. If
    None ever reached the file as the literal "None", the comparison could never
    match and the evidence check would silently stop blocking.
    """
    _init_git_repo(tmp_path)
    start(tmp_path, "agent-none")

    state_file = tmp_path / ".git" / "the-workshop-subagent-gate" / "agent-none.txt"
    assert "None" not in state_file.read_text()


def test_hooks_fail_open_when_the_shared_helper_is_missing(tmp_path: Path) -> None:
    """A stale or partial install must no-op, not crash the user's tool path.

    The helper ships alongside every hook, so this should never happen — but a
    hook that raises ImportError on a real event surfaces an error on unrelated
    work, which is exactly what fail-open exists to prevent.
    """
    _init_git_repo(tmp_path)
    isolated = tmp_path / "hooks"
    isolated.mkdir()
    for hook in (START_HOOK, STOP_HOOK):
        shutil.copy2(hook, isolated / hook.name)  # deliberately without _git_baseline.py

    result = run(
        isolated / STOP_HOOK.name,
        {"cwd": str(tmp_path), "agent_id": "a1", "message": "Done. I fixed it."},
    )

    assert result.returncode == 0
    assert result.stdout.strip() == ""
