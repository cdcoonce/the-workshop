"""Guard: a static fixture may not keep an answer-key-named file public (#1130).

For every committed case whose fixture is a static ``fixture/`` tree (no
``builder`` key in ``case.toml`` and no case-local ``build_fixture.py``), a
file under ``fixture/`` whose name suggests an answer key must be covered by
the case's ``fixture_private`` list, which ``evals._harness.fixture_copy``
honours when the conductor copies the fixture for a dispatched agent.

The name heuristic (case-insensitive, on the file name): ``defects.json``, or
``answer*``, ``ground_truth*``, ``expected*``, ``*key*.json``. It is a tripwire
for the known shapes, not a proof: a key under any other name must still be
declared by hand. A malformed or stale ``fixture_private`` declaration fails
here too, so a declaration that protects nothing cannot sit green.

Checks state at HEAD: ``ctx.base`` is unused.
"""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path

from evals._harness.fixture_copy import FixtureCopyError, has_builder, private_fixture_paths
from evals._harness.guards import GuardContext, Result

_GUARD_NAME = "answer_key_private"
_PATTERNS = ("defects.json", "answer*", "ground_truth*", "expected*", "*key*.json")


def looks_like_answer_key(name: str) -> bool:
    """Whether a file name suggests an answer key."""
    lowered = name.casefold()
    return any(fnmatch.fnmatchcase(lowered, pattern) for pattern in _PATTERNS)


def _is_static_fixture_case(case_dir: Path) -> bool:
    return (case_dir / "fixture").is_dir() and not has_builder(case_dir)


def _fail(message: str) -> Result:
    return Result(level="fail", guard=_GUARD_NAME, message=message)


def check(ctx: GuardContext) -> list[Result]:
    """Fail each static-fixture case that leaves an answer-key-named file public.

    Returns
    -------
    list[Result]
        One ``fail`` per case with an uncovered answer-key-named file (naming
        every such file) or with a bad ``fixture_private`` declaration.
    """
    evals_root = ctx.repo_root / "evals"
    if not evals_root.is_dir():
        return []
    results: list[Result] = []
    for skill_dir in sorted(p for p in evals_root.iterdir() if p.is_dir() and not p.name.startswith(("_", "."))):
        for case_dir in sorted(p for p in skill_dir.iterdir() if p.is_dir() and (p / "case.toml").is_file()):
            if not _is_static_fixture_case(case_dir):
                continue
            label = f"{skill_dir.name}/{case_dir.name}"
            try:
                private = private_fixture_paths(case_dir)
            except FixtureCopyError as exc:
                results.append(_fail(f"{label}: {exc}"))
                continue
            fixture = case_dir / "fixture"
            exposed: list[str] = []
            for root, _dirs, files in os.walk(fixture):
                for name in files:
                    rel = (Path(root) / name).relative_to(fixture).as_posix()
                    covered = any(rel == entry or rel.startswith(entry + "/") for entry in private)
                    if looks_like_answer_key(name) and not covered:
                        exposed.append(rel)
            if exposed:
                results.append(
                    _fail(
                        f"{label}: fixture/ keeps {', '.join(sorted(exposed))} without listing it in "
                        "case.toml's fixture_private, so a default fixture copy hands it to the agent"
                    )
                )
    return results
