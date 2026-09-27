"""Guard runner: ``uv run python -m evals._harness.guards --base <ref>``.

Auto-discovers every module under ``evals/_harness/guards/`` that exposes a
``check(ctx) -> list[Result]`` function, runs each against one shared
``GuardContext``, prints every result it collects, and exits 1 if any result
is level ``"fail"``, else exits 0. A run with no guard modules present passes
(exits 0, prints nothing) rather than treating an absent check as a failure.
"""

from __future__ import annotations

import argparse
import importlib
import pkgutil
import sys
from pathlib import Path
from typing import Callable

from evals._harness.guards import GuardContext, Result

# `__name__` is `"__main__"` when this runs as `python -m evals._harness.guards`
# (a package's `__main__` submodule always executes under that name), but
# `__package__` still names the containing package correctly either way.
_PACKAGE = __package__

CheckFn = Callable[[GuardContext], list[Result]]


def discover_checks() -> list[tuple[str, CheckFn]]:
    """Return every ``(module name, check function)`` pair in this package.

    Sorted by module name so a run's guard order is deterministic. The
    runner module itself is excluded, and a module with no ``check``
    attribute is skipped rather than treated as an error — the contract is
    opt-in per module. Reads the package's own ``__path__`` (rather than
    deriving a directory from ``__file__``) so a test can extend it with a
    planted module without touching the filesystem this package ships from.

    Returns
    -------
    list[tuple[str, CheckFn]]
        Every discovered guard's name and callable.
    """
    package = sys.modules[_PACKAGE]
    found: list[tuple[str, CheckFn]] = []
    for module_info in sorted(pkgutil.iter_modules(package.__path__), key=lambda m: m.name):
        if module_info.name == "__main__":
            continue
        module = importlib.import_module(f"{_PACKAGE}.{module_info.name}")
        check = getattr(module, "check", None)
        if callable(check):
            found.append((module_info.name, check))
    return found


def run_checks(ctx: GuardContext) -> list[Result]:
    """Run every discovered guard module's ``check`` against *ctx*.

    Parameters
    ----------
    ctx : GuardContext
        The shared context passed to every guard.

    Returns
    -------
    list[Result]
        Every result from every guard, in discovery order.
    """
    results: list[Result] = []
    for _name, check in discover_checks():
        results.extend(check(ctx))
    return results


def report(results: list[Result]) -> int:
    """Print every result and return the process exit code.

    Parameters
    ----------
    results : list[Result]
        Every result collected from every guard module.

    Returns
    -------
    int
        1 if any result is level ``"fail"``, else 0.
    """
    for result in results:
        print(f"[{result.level}] {result.guard}: {result.message}")
    return 1 if any(result.level == "fail" for result in results) else 0


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``python -m evals._harness.guards``.

    Parameters
    ----------
    argv : list[str] | None
        Arguments to parse in place of ``sys.argv[1:]``.

    Returns
    -------
    int
        The process exit code from `report`.
    """
    parser = argparse.ArgumentParser(prog="evals._harness.guards")
    parser.add_argument("--base", required=True, help="ref to compare against")
    args = parser.parse_args(argv)

    ctx = GuardContext(base=args.base, repo_root=Path.cwd())
    return report(run_checks(ctx))


if __name__ == "__main__":
    sys.exit(main())
