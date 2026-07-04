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
