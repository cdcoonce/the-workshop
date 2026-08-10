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

# The consolidated `workbench` package ships one superset post-edit-lint hook
# (Ruff + Prettier + ESLint + Stylelint), replacing the old per-preset variants.
WORKBENCH_HOOK = REPO_ROOT / "presets" / "workbench" / "hooks" / "post-edit-lint.py"

HOOK_PATHS = {"workbench": WORKBENCH_HOOK}

# The post-edit-lint hook must fail-open on bad stdin (#125).
ALL_POST_EDIT_HOOKS = {"workbench": WORKBENCH_HOOK}


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


@pytest.mark.parametrize("preset", ["workbench"])
def test_npx_calls_include_no_install(tmp_path: Path, preset: str) -> None:
    record_path = tmp_path / "npx-calls.log"
    _write_fake_npx(tmp_path, record_path, exit_code=0)

    run_hook(HOOK_PATHS[preset], "example.md", tmp_path)

    assert record_path.exists()
    lines = record_path.read_text().splitlines()
    assert lines
    for line in lines:
        assert line.split()[0] == "--no-install"


def test_workbench_every_npx_tool_passes_no_install(tmp_path: Path) -> None:
    record_path = tmp_path / "npx-calls.log"
    _write_fake_npx(tmp_path, record_path, exit_code=0)

    run_hook(HOOK_PATHS["workbench"], "example.css", tmp_path)  # prettier + stylelint
    run_hook(HOOK_PATHS["workbench"], "example.ts", tmp_path)  # prettier + eslint

    lines = record_path.read_text().splitlines()
    assert len(lines) == 4
    for line in lines:
        assert line.split()[0] == "--no-install"


def test_missing_tool_records_no_action(tmp_path: Path) -> None:
    record_path = tmp_path / "npx-calls.log"
    _write_fake_npx(
        tmp_path, record_path, exit_code=1
    )  # simulates --no-install failure

    result = run_hook(HOOK_PATHS["workbench"], "example.md", tmp_path)

    assert result.returncode == 0
    assert result.stderr == ""


def test_installed_tool_reports_action_on_stderr(tmp_path: Path) -> None:
    record_path = tmp_path / "npx-calls.log"
    _write_fake_npx(tmp_path, record_path, exit_code=0)

    result = run_hook(HOOK_PATHS["workbench"], "example.md", tmp_path)

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


# --- Prettier requires a project config -------------------------------------
#
# Prettier is the only tool this hook runs that acts on a project which never
# asked for it. Ruff is guarded by shutil.which; ESLint and Stylelint need a
# config to do anything. Prettier formats happily with built-in defaults, and
# `npx --no-install` resolves it from the machine-wide npx cache — so an
# unguarded `--write` rewrote Markdown and JSON in every repo on the machine,
# including repos whose own gate checks neither, where the change is unreviewed
# and uncaught.


def _write_prettier_config(directory: Path, name: str = ".prettierrc") -> None:
    (directory / name).write_text("{}\n")


def _md_in(directory: Path) -> str:
    target = directory / "example.md"
    target.write_text("# hi\n")
    return str(target)


def test_prettier_skipped_when_project_declares_no_config(tmp_path: Path) -> None:
    record_path = tmp_path / "npx-calls.log"
    _write_fake_npx(tmp_path, record_path, exit_code=0)
    project = tmp_path / "project"
    project.mkdir()

    result = run_hook(HOOK_PATHS["workbench"], _md_in(project), tmp_path)

    assert result.returncode == 0
    assert not record_path.exists(), (
        "prettier must not run in a project that declares no prettier config"
    )


@pytest.mark.parametrize(
    "config_name",
    [
        ".prettierrc",
        ".prettierrc.json",
        ".prettierrc.yaml",
        ".prettierrc.toml",
        "prettier.config.js",
        "prettier.config.mjs",
    ],
)
def test_prettier_runs_for_each_config_filename(
    tmp_path: Path, config_name: str
) -> None:
    record_path = tmp_path / "npx-calls.log"
    _write_fake_npx(tmp_path, record_path, exit_code=0)
    project = tmp_path / "project"
    project.mkdir()
    _write_prettier_config(project, config_name)

    run_hook(HOOK_PATHS["workbench"], _md_in(project), tmp_path)

    assert record_path.exists(), f"{config_name} must count as opting in"
    assert "prettier" in record_path.read_text()


def test_prettier_config_is_found_in_an_ancestor_directory(tmp_path: Path) -> None:
    """Mirrors Prettier's own upward search — a repo-root config governs a file
    nested arbitrarily deep, which is the normal layout."""
    record_path = tmp_path / "npx-calls.log"
    _write_fake_npx(tmp_path, record_path, exit_code=0)
    project = tmp_path / "project"
    nested = project / "docs" / "reference"
    nested.mkdir(parents=True)
    _write_prettier_config(project)

    run_hook(HOOK_PATHS["workbench"], _md_in(nested), tmp_path)

    assert record_path.exists()
    assert "prettier" in record_path.read_text()


def test_package_json_prettier_key_counts_as_config(tmp_path: Path) -> None:
    record_path = tmp_path / "npx-calls.log"
    _write_fake_npx(tmp_path, record_path, exit_code=0)
    project = tmp_path / "project"
    project.mkdir()
    (project / "package.json").write_text(json.dumps({"prettier": {"semi": False}}))

    run_hook(HOOK_PATHS["workbench"], _md_in(project), tmp_path)

    assert record_path.exists()
    assert "prettier" in record_path.read_text()


def test_package_json_without_a_prettier_key_is_not_opting_in(tmp_path: Path) -> None:
    """A package.json alone means "this is a Node project", not "format my
    Markdown" — most repos with one have never configured Prettier."""
    record_path = tmp_path / "npx-calls.log"
    _write_fake_npx(tmp_path, record_path, exit_code=0)
    project = tmp_path / "project"
    project.mkdir()
    (project / "package.json").write_text(json.dumps({"name": "x", "version": "1.0.0"}))

    run_hook(HOOK_PATHS["workbench"], _md_in(project), tmp_path)

    assert not record_path.exists()


def test_malformed_package_json_does_not_crash_the_hook(tmp_path: Path) -> None:
    record_path = tmp_path / "npx-calls.log"
    _write_fake_npx(tmp_path, record_path, exit_code=0)
    project = tmp_path / "project"
    project.mkdir()
    (project / "package.json").write_text("{ not json")

    result = run_hook(HOOK_PATHS["workbench"], _md_in(project), tmp_path)

    assert result.returncode == 0
    assert "Traceback" not in result.stderr


def test_editorconfig_alone_does_not_opt_in(tmp_path: Path) -> None:
    """Prettier reads .editorconfig for a few options, but its presence says
    nothing about wanting Prettier — plenty of repos have one and no Prettier."""
    record_path = tmp_path / "npx-calls.log"
    _write_fake_npx(tmp_path, record_path, exit_code=0)
    project = tmp_path / "project"
    project.mkdir()
    (project / ".editorconfig").write_text("root = true\n")

    run_hook(HOOK_PATHS["workbench"], _md_in(project), tmp_path)

    assert not record_path.exists()


def test_eslint_still_runs_without_a_prettier_config(tmp_path: Path) -> None:
    """The gate is scoped to Prettier. ESLint and Stylelint need their own
    config to do anything, so they were never the problem and must not regress."""
    record_path = tmp_path / "npx-calls.log"
    _write_fake_npx(tmp_path, record_path, exit_code=0)
    project = tmp_path / "project"
    project.mkdir()
    target = project / "example.ts"
    target.write_text("export const x = 1;\n")

    run_hook(HOOK_PATHS["workbench"], str(target), tmp_path)

    calls = record_path.read_text()
    assert "eslint" in calls
    assert "prettier" not in calls
