"""Shared pytest configuration for the evals harness test suite.

Owned solely by this child (#991): no sibling may add or edit fixtures here,
even one that also drops a test file under ``evals/_harness/tests/`` — a
sibling that needs a fixture defines it in its own test module instead, so
this file's contract to #991 cannot be changed out from under it.

Puts this directory on ``sys.path`` so a sibling module here (e.g.
``no_model_calls_check.py``) can be imported bare, the same way
``plugins/workbench/machinery/tests/conftest.py`` imports its engine
siblings — ``evals/_harness/tests`` has no ``__init__.py`` (the Makefile's
``--import-mode=importlib`` needs none for pytest's own collection), so it is
not a dotted-importable package on its own.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
