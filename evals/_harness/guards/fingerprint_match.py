"""Guard: a gated case's fixture still matches the one its newest recorded run used.

For every gated case — a case with at least one item whose id its skill's
``checks.manifest`` lists — this takes the newest run file of that skill (by
filename timestamp) that records the case, and compares that run file's
per-case ``fixture_fingerprint`` to the fixture's current fingerprint at HEAD,
computed by ``evals._harness.calibration.fixture_fingerprint`` (the fixture
tree hash, or, for a builder case, the builder-output fingerprint — the
builder runs at gate time). A mismatch means the fixture no longer matches the
one the recorded run used, and fails.

A gated case that no run file records is not checked. This guard reads fixture
drift only and never a calibration record's ``input_hash``: staleness of the
calibrated inputs (prompt, scorer params, predicates, builder script) is
``calibration_staleness``'s separate concern. It inspects the state at HEAD, so
``ctx.base`` is not used.
"""

from __future__ import annotations

import json
import subprocess
import tomllib
from pathlib import Path

from evals._harness.activation import parse_checks_manifest
from evals._harness.calibration import fixture_fingerprint
from evals._harness.dispatch import discover_skill_dirs
from evals._harness.guards import GuardContext, Result

_GUARD_NAME = "fingerprint_match"


def _fail(message: str) -> Result:
    return Result(level="fail", guard=_GUARD_NAME, message=message)


def _gated_ids(skill_dir: Path) -> set[str]:
    manifest = skill_dir / "checks.manifest"
    if not manifest.is_file():
        return set()
    return set(parse_checks_manifest(manifest.read_text(encoding="utf-8")))


def _item_ids(case_dir: Path) -> set[str]:
    case_toml = tomllib.loads((case_dir / "case.toml").read_text(encoding="utf-8"))
    return {
        item["id"]
        for item in case_toml.get("items", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }


def _recorded_fingerprint(skill_dir: Path, case: str) -> tuple[Path, object] | None:
    """Return ``(run_file, fixture_fingerprint)`` from the newest run recording *case*.

    Run files are the ``.json`` files directly under ``runs/`` (a raw lives
    deeper); newest is by filename, whose leading UTC timestamp sorts. A run
    file that cannot be read as a JSON object is skipped — ``schema_validate``
    owns malformed run files.
    """
    runs_dir = skill_dir / "runs"
    if not runs_dir.is_dir():
        return None
    for run_path in sorted(runs_dir.glob("*.json"), key=lambda path: path.name, reverse=True):
        try:
            run = json.loads(run_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        cases = run.get("cases") if isinstance(run, dict) else None
        if not isinstance(cases, list):
            continue
        for recorded in cases:
            if isinstance(recorded, dict) and recorded.get("case") == case:
                return run_path, recorded.get("fixture_fingerprint")
    return None


def check(ctx: GuardContext) -> list[Result]:
    """Fail every gated case whose fixture drifted from its newest recorded run.

    Parameters
    ----------
    ctx : GuardContext
        ``ctx.repo_root`` is the work tree, checked out at HEAD, whose
        ``evals/`` directory is inspected. ``ctx.base`` is unused.

    Returns
    -------
    list[Result]
        One ``fail`` per gated case whose current fixture fingerprint differs
        from the newest run file's record of it, or that cannot be
        fingerprinted or read at all. Empty when every recorded gated case
        still matches, or none is recorded.
    """
    results: list[Result] = []
    evals_root = ctx.repo_root / "evals"
    if not evals_root.is_dir():
        return results

    for skill_dir in discover_skill_dirs(evals_root):
        gated = _gated_ids(skill_dir)
        if not gated:
            continue
        for case_toml in sorted(skill_dir.glob("*/case.toml")):
            case_dir = case_toml.parent
            try:
                is_gated = bool(_item_ids(case_dir) & gated)
            except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
                results.append(
                    _fail(f"{skill_dir.name}/{case_dir.name}: case.toml cannot be read ({exc})")
                )
                continue
            if not is_gated:
                continue
            recorded = _recorded_fingerprint(skill_dir, case_dir.name)
            if recorded is None:
                continue
            run_path, recorded_fingerprint = recorded
            try:
                current = fixture_fingerprint(case_dir)
            except (ValueError, OSError, subprocess.CalledProcessError) as exc:
                # No fixture or builder (ValueError), or a builder that crashes: fail closed.
                results.append(
                    _fail(
                        f"{skill_dir.name}/{case_dir.name}: the fixture cannot be fingerprinted "
                        f"({type(exc).__name__}: {exc}), so it cannot be compared with {run_path.name}"
                    )
                )
                continue
            if current != recorded_fingerprint:
                results.append(
                    _fail(
                        f"{skill_dir.name}/{case_dir.name}: the fixture no longer matches the one "
                        f"recorded in {run_path.name} (recorded {recorded_fingerprint}, "
                        f"current {current})"
                    )
                )
    return results
