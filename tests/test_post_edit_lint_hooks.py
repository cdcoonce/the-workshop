"""Tests for the post-edit-lint hooks' npx invocations.

The hooks shell out to `npx <tool> ...` for Prettier/ESLint/Stylelint. Without
`--no-install`, npx silently downloads missing tools from the network on every
file edit. These tests drive each hook as a real subprocess with a fake `npx`
placed first on PATH that records its argv and exits with a controllable code,
confirming `--no-install` is always passed and that the run() helper's
success/failure contract still holds.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

HOOK_PATHS = {
    "full-stack": REPO_ROOT / "presets" / "full-stack" / "hooks" / "post-edit-lint.py",
    "claude-tooling": REPO_ROOT
    / "presets"
    / "claude-tooling"
    / "hooks"
    / "post-edit-lint.py",
}

# Every preset's post-edit-lint hook — all five must fail-open on bad stdin (#125).
ALL_POST_EDIT_HOOKS = {
    name: REPO_ROOT / "presets" / name / "hooks" / "post-edit-lint.py"
    for name in (
        "analysis",
        "python-api",
        "data-pipeline",
        "claude-tooling",
        "full-stack",
    )
}


def _run_hook_stdin(hook_path: Path, raw_stdin: str) -> subprocess.CompletedProcess[str]:
    """Invoke a hook as a subprocess, feeding raw (possibly non-JSON) stdin."""
    return subprocess.run(
        [sys.executable, str(hook_path)],
        input=raw_stdin,
        capture_output=True,
        text=True,
    )


def _write_fake_npx(bin_dir: Path, record_path: Path, exit_code: int) -> None:
    """Install a fake `npx` on PATH that records its argv and exits with exit_code."""
    fake_npx = bin_dir / "npx"
    fake_npx.write_text(f'#!/bin/sh\necho "$@" >> "{record_path}"\nexit {exit_code}\n')
    mode = fake_npx.stat().st_mode
    fake_npx.chmod(mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def run_hook(
    hook_path: Path, file_path: str, bin_dir: Path
) -> subprocess.CompletedProcess[str]:
    """Invoke a hook as a subprocess, feeding a tool_input payload as JSON on stdin."""
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    return subprocess.run(
        [sys.executable, str(hook_path)],
        input=json.dumps({"tool_input": {"file_path": file_path}}),
        capture_output=True,
        text=True,
        env=env,
    )


@pytest.mark.parametrize("preset", ["full-stack", "claude-tooling"])
def test_npx_calls_include_no_install(tmp_path: Path, preset: str) -> None:
    record_path = tmp_path / "npx-calls.log"
    _write_fake_npx(tmp_path, record_path, exit_code=0)

    run_hook(HOOK_PATHS[preset], "example.md", tmp_path)

    assert record_path.exists()
    lines = record_path.read_text().splitlines()
    assert lines
    for line in lines:
        assert line.split()[0] == "--no-install"


def test_full_stack_every_npx_tool_passes_no_install(tmp_path: Path) -> None:
    record_path = tmp_path / "npx-calls.log"
    _write_fake_npx(tmp_path, record_path, exit_code=0)

    run_hook(HOOK_PATHS["full-stack"], "example.css", tmp_path)  # prettier + stylelint
    run_hook(HOOK_PATHS["full-stack"], "example.ts", tmp_path)  # prettier + eslint

    lines = record_path.read_text().splitlines()
    assert len(lines) == 4
    for line in lines:
        assert line.split()[0] == "--no-install"


def test_missing_tool_records_no_action(tmp_path: Path) -> None:
    record_path = tmp_path / "npx-calls.log"
    _write_fake_npx(
        tmp_path, record_path, exit_code=1
    )  # simulates --no-install failure

    result = run_hook(HOOK_PATHS["full-stack"], "example.md", tmp_path)

    assert result.returncode == 0
    assert result.stderr == ""


def test_installed_tool_reports_action_on_stderr(tmp_path: Path) -> None:
    record_path = tmp_path / "npx-calls.log"
    _write_fake_npx(tmp_path, record_path, exit_code=0)

    result = run_hook(HOOK_PATHS["full-stack"], "example.md", tmp_path)

    assert "prettier" in result.stderr
    assert "example.md" in result.stderr


class TestPostEditLintFailOpen:
    """A malformed/empty stdin payload must no-op (exit 0), not traceback (#125)."""

    @pytest.mark.parametrize("preset", sorted(ALL_POST_EDIT_HOOKS))
    @pytest.mark.parametrize(
        "payload", ["", "   ", "\n", "not json", "{ broken", "[1, 2,"]
    )
    def test_malformed_stdin_fails_open(self, preset: str, payload: str) -> None:
        result = _run_hook_stdin(ALL_POST_EDIT_HOOKS[preset], payload)

        assert result.returncode == 0, (
            f"{preset} hook must fail-open on malformed stdin, exited "
            f"{result.returncode}: {result.stderr}"
        )
        assert "Traceback" not in result.stderr
        assert "JSONDecodeError" not in result.stderr

    @pytest.mark.parametrize("preset", sorted(ALL_POST_EDIT_HOOKS))
    def test_well_formed_payload_still_exits_clean(self, preset: str) -> None:
        # Valid JSON with an empty file_path takes the normal early-exit path;
        # the guard must not disturb well-formed behavior.
        result = _run_hook_stdin(
            ALL_POST_EDIT_HOOKS[preset],
            json.dumps({"tool_input": {"file_path": ""}}),
        )

        assert result.returncode == 0
        assert "Traceback" not in result.stderr
