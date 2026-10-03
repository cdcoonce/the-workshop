"""Fixtures shared by the A2 case tests.

Lives beside the tests it serves (``A2/case_tests/``), never in
``evals/_harness/tests/conftest.py``, which #991 owns.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

# A2/case_tests/conftest.py -> case_tests -> A2 -> adversarial-review -> evals -> repo root.
_CASE_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = Path(__file__).resolve().parents[4]

SYNC_SCRIPT = "plugins/workbench/skills/vault-wrap-up/scripts/sync_boundary_squash.py"
SYNC_TESTS = "plugins/workbench/skills/vault-wrap-up/scripts/tests/test_sync_boundary_squash.py"
VAULT_SYNC_COMMAND = "plugins/workbench/skills/vault-sync/references/command.md"


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return _REPO_ROOT


@pytest.fixture(scope="session")
def case_dir() -> Path:
    return _CASE_DIR


@pytest.fixture(scope="session")
def case_toml(case_dir: Path) -> dict:
    return tomllib.loads((case_dir / "case.toml").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def items(case_toml: dict) -> dict[str, dict]:
    """The case's ``[[items]]`` keyed by id."""
    return {item["id"]: item for item in case_toml["items"]}


@pytest.fixture(scope="session")
def defects(case_dir: Path) -> dict[str, dict]:
    """The experiment's ground truth (``fixture/defects.json``) keyed by D-number."""
    loaded = json.loads((case_dir / "fixture" / "defects.json").read_text(encoding="utf-8"))
    return {defect["id"]: defect for defect in loaded["defects"]}


@pytest.fixture(scope="session")
def predicates(case_dir: Path):
    """A2's ``predicates.py``, loaded by file path with bytecode caching off."""
    spec = importlib.util.spec_from_file_location("_a2_predicates_under_test", case_dir / "predicates.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


@pytest.fixture(scope="session")
def git(repo_root: Path):
    """``git(*args) -> stdout`` run in the repo; a failure raises with git's own message."""

    def run(*args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(repo_root), *args], capture_output=True, text=True, check=False
        )
        assert result.returncode == 0, f"git {' '.join(args)} failed: {result.stderr.strip()}"
        return result.stdout

    return run
