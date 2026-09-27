"""Shared types for the eval harness guard runner.

Every guard module under ``evals/_harness/guards/`` implements the contract
``check(ctx: GuardContext) -> list[Result]``. The runner
(``evals._harness.guards.__main__``) auto-discovers those modules, builds one
``GuardContext``, and passes it to each.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class GuardContext:
    """Shared input every guard's ``check`` receives.

    Attributes
    ----------
    base : str
        The ``--base`` ref passed to the guard runner.
    repo_root : Path
        The git work tree to inspect — the repo root under ``make test``, or
        a temporary git repo built by a guard's own test.
    """

    base: str
    repo_root: Path


@dataclass(frozen=True)
class Result:
    """One finding from a guard's ``check``.

    Attributes
    ----------
    level : Literal["fail", "warn"]
        ``"fail"`` makes the guard runner exit non-zero; ``"warn"`` is
        reported but does not fail the run.
    guard : str
        Name of the guard that produced this result.
    message : str
        Human-readable description of the finding.
    """

    level: Literal["fail", "warn"]
    guard: str
    message: str
