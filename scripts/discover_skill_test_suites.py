"""Discover and run every skill-script test suite in its own rootdir.

Skill scripts (e.g. ``core/skills/daa-code-review/scripts``) keep their tests in
a sibling ``tests`` package with bare imports (``from models import ...``), so
they cannot share the root pytest collection — a ``tests`` package-name
collision. They must each run as a separate pytest invocation from their own
``scripts`` directory.

This module finds those suites automatically instead of relying on a
hand-maintained Makefile list, so a new skill's tests can never silently fall
out of the gate. ``find_suites`` is the discovery; ``main`` runs each suite and
returns non-zero if any fails.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Directories whose ``*/scripts/tests`` subtrees hold skill-script test suites.
_SEARCH_ROOTS = ("core/skills", "presets")


def find_suites(repo_root: Path) -> list[Path]:
    """Return each ``.../scripts`` dir with at least one ``tests/test_*.py``.

    Empty ``scripts/tests`` scaffolding (no ``test_*.py``) is skipped so it does
    not read as an empty, failing suite.
    """
    suites: set[Path] = set()
    for base in _SEARCH_ROOTS:
        base_dir = repo_root / base
        if not base_dir.is_dir():
            continue
        for tests_dir in base_dir.rglob("scripts/tests"):
            if any(tests_dir.glob("test_*.py")):
                suites.add(tests_dir.parent)
    return sorted(suites)


def main(argv: list[str] | None = None) -> int:
    repo_root = Path(argv[0]) if argv else Path(__file__).resolve().parents[1]
    suites = find_suites(repo_root)
    if not suites:
        print("no skill-script test suites found.")
        return 0

    failures: list[str] = []
    for scripts_dir in suites:
        rel = scripts_dir.relative_to(repo_root)
        print(f"== {rel}/tests ==")
        result = subprocess.run(
            ["uv", "run", "--with", "pytest", "--with", "ruff", "python", "-m", "pytest", "-q", "tests"],
            cwd=scripts_dir,
            check=False,
        )
        if result.returncode != 0:
            failures.append(str(rel))

    if failures:
        print(f"\nskill-script suites failed: {', '.join(failures)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
