"""Tests for the protect-files pre-edit hook.

The hook is a stdin/exit-code gate, not an importable function: it reads a JSON
payload from stdin, then exits 0 (allow) or exits 2 with a stderr reason (block).
Driving it as a subprocess exercises that real contract end to end.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOK_PATH = Path(__file__).resolve().parents[1] / "core" / "hooks" / "protect-files.py"


def run_hook(payload: dict) -> subprocess.CompletedProcess[str]:
    """Invoke the hook as a subprocess, feeding ``payload`` as JSON on stdin."""
    return subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize(
    "file_path, pattern",
    [
        (".env", ".env"),
        ("project/.env.local", ".env"),
        ("uv.lock", "uv.lock"),
        ("package-lock.json", "package-lock.json"),
        ("node_modules/foo/index.js", "node_modules/"),
        (".git/config", ".git/"),
    ],
)
def test_protected_path_blocks_with_reason(file_path: str, pattern: str) -> None:
    result = run_hook({"tool_input": {"file_path": file_path}})

    assert result.returncode == 2
    assert pattern in result.stderr
    assert file_path in result.stderr


@pytest.mark.parametrize(
    "file_path, pattern",
    [
        (".env.staging", ".env"),
        (".env.production", ".env"),
    ],
)
def test_env_variant_blocks_with_reason(file_path: str, pattern: str) -> None:
    result = run_hook({"tool_input": {"file_path": file_path}})

    assert result.returncode == 2
    assert pattern in result.stderr
    assert file_path in result.stderr


@pytest.mark.parametrize(
    "file_path",
    [
        ".env.example",
        ".env.sample",
        ".env.template",
        ".env.dist",
        "project/.env.example",
    ],
)
def test_env_template_suffix_allows(file_path: str) -> None:
    result = run_hook({"tool_input": {"file_path": file_path}})

    assert result.returncode == 0
    assert result.stderr == ""


def test_non_protected_path_allows_silently() -> None:
    result = run_hook({"tool_input": {"file_path": "scripts/build_preset.py"}})

    assert result.returncode == 0
    assert result.stderr == ""


@pytest.mark.parametrize(
    "file_path",
    [
        "src/client.environment.ts",
        "scripts/prevented.py",
        "src/uv.locksmith.py",
        "config/package-lock.json.bak",
        "src/my_node_modules/file.js",
        "project.git/repo_notes.py",
    ],
)
def test_substring_embedded_pattern_allows(file_path: str) -> None:
    result = run_hook({"tool_input": {"file_path": file_path}})

    assert result.returncode == 0
    assert result.stderr == ""


def test_empty_file_path_allows() -> None:
    result = run_hook({"tool_input": {"file_path": ""}})

    assert result.returncode == 0


def test_missing_file_path_allows() -> None:
    result = run_hook({"tool_input": {}})

    assert result.returncode == 0


def test_missing_tool_input_allows() -> None:
    result = run_hook({})

    assert result.returncode == 0
