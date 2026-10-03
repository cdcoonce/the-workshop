"""Fixtures shared by the A1 case tests.

Lives beside the tests it serves (``A1/case_tests/``), never in
``evals/_harness/tests/conftest.py``, which #991 owns.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from evals._harness.dispatch import Evidence
from evals._harness.transcript import Transcript

# A1/case_tests/conftest.py -> case_tests -> A1 -> adversarial-review -> evals -> repo root.
_CASE_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = Path(__file__).resolve().parents[4]


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
def predicates(case_dir: Path):
    """A1's ``predicates.py``, loaded by file path with bytecode caching off."""
    spec = importlib.util.spec_from_file_location("_a1_predicates_under_test", case_dir / "predicates.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


@pytest.fixture
def evidence_for():
    """Build the ``Evidence`` a scorer sees for a case-agent whose final reply is *text*."""

    def make(text: str) -> Evidence:
        transcript = Transcript(
            status="complete", events=[], model_ids=["claude-test"], final_text=text, final_text_ordinal=0
        )
        return Evidence(transcripts=[transcript], findings=[], workdir=None, end_state={})

    return make


@pytest.fixture
def build_fixture(case_toml: dict, repo_root: Path):
    """Run the case's ``builder`` as a subprocess into a not-yet-existing ``dest``."""
    builder = repo_root / case_toml["builder"]

    def build(dest: Path) -> Path:
        assert not dest.exists()
        subprocess.run([sys.executable, str(builder), str(dest)], check=True, capture_output=True, text=True)
        return dest

    return build
