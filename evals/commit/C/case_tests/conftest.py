"""Pytest fixtures for the commit/C case tests.

Puts this directory on ``sys.path`` so the tests can import ``commit_c_support``
bare (``case_tests`` has no ``__init__.py``; the Makefile's
``--import-mode=importlib`` needs none), the same way ``evals/_harness/tests``
imports its siblings. The helper module has a case-specific name so a sibling
case's tests can never collide with it.
"""

from __future__ import annotations

import shutil
import sys
import tomllib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from commit_c_support import CASE_DIR, build, load_module  # noqa: E402


@pytest.fixture(scope="session")
def case_dir() -> Path:
    return CASE_DIR


@pytest.fixture(scope="session")
def case_toml() -> dict:
    return tomllib.loads((CASE_DIR / "case.toml").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def predicates():
    return load_module(CASE_DIR / "predicates.py", "commit_c_predicates")


@pytest.fixture(scope="session")
def _built_once(tmp_path_factory) -> Path:
    dest = tmp_path_factory.mktemp("built") / "repo"
    build(CASE_DIR, dest)
    return dest


@pytest.fixture
def built_repo(_built_once, tmp_path) -> Path:
    """A private, writable copy of one build of the fixture (tests may commit in it)."""
    dest = tmp_path / "repo"
    shutil.copytree(_built_once, dest, symlinks=True)
    return dest
