"""Guard: every gated case has a calibration record whose input hash is still current.

A gated case is one with at least one item whose id its skill's
``checks.manifest`` lists (i.e. an item admitted under #994's rule). For every
such item this requires:

- a record for the item in the case's ``calibration.json`` — a gated case with
  no calibration record at all fails; and
- that record's stored ``input_hash`` to equal a freshly recomputed
  ``evals._harness.calibration.compute_input_hash(case_dir)`` of the case's
  current inputs (prompt, fixture tree or builder script, builder output
  fingerprint, item ids/kinds/scorer params, ``predicates.py``). A builder case
  runs its builder at gate time. A mismatch means the record is stale.

A case with no item in the manifest is never checked. This guard never reads a
run file's ``fixture_fingerprint`` (``fingerprint_match`` owns fixture drift)
and fails independently of ``direct_tier``, which never reads calibration
records: under ``make test`` a direct-tier change whose case has a stale record
is still blocked here even when ``direct_tier`` is satisfied by a green run
file. It inspects the state at HEAD, so ``ctx.base`` is not used.
"""

from __future__ import annotations

import json
import subprocess
import tomllib
from pathlib import Path

from evals._harness.activation import parse_checks_manifest
from evals._harness.calibration import compute_input_hash
from evals._harness.dispatch import discover_skill_dirs
from evals._harness.guards import GuardContext, Result

_GUARD_NAME = "calibration_staleness"


def _fail(message: str) -> Result:
    return Result(level="fail", guard=_GUARD_NAME, message=message)


def _gated_ids(skill_dir: Path) -> set[str]:
    manifest = skill_dir / "checks.manifest"
    if not manifest.is_file():
        return set()
    return set(parse_checks_manifest(manifest.read_text(encoding="utf-8")))


def _item_ids(case_dir: Path) -> list[str]:
    case_toml = tomllib.loads((case_dir / "case.toml").read_text(encoding="utf-8"))
    return [
        item["id"]
        for item in case_toml.get("items", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    ]


def _load_records(case_dir: Path) -> dict | str | None:
    """Return the case's records map, ``None`` when there is no file, else a reason string."""
    path = case_dir / "calibration.json"
    if not path.is_file():
        return None
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return f"calibration.json cannot be read ({exc})"
    if not isinstance(records, dict):
        return "calibration.json is not a JSON object mapping item id to record"
    return records


def _check_case(skill: str, case_dir: Path, gated_items: list[str]) -> list[Result]:
    label = f"{skill}/{case_dir.name}"
    records = _load_records(case_dir)
    if isinstance(records, str):
        return [_fail(f"{label}: {records}")]

    results: list[Result] = []
    stored: dict[str, object] = {}
    for item in gated_items:
        record = (records or {}).get(item)
        if record is None:
            results.append(_fail(f"{label}: gated item {item!r} has no calibration record"))
        else:
            stored[item] = record.get("input_hash") if isinstance(record, dict) else None
    if not stored:
        return results

    try:
        current = compute_input_hash(case_dir)
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError) as exc:
        results.append(
            _fail(
                f"{label}: the case's input hash cannot be recomputed "
                f"({type(exc).__name__}: {exc}), so its calibration record cannot be checked"
            )
        )
        return results

    for item, stored_hash in stored.items():
        if stored_hash != current:
            results.append(
                _fail(
                    f"{label}: the calibration record for gated item {item!r} is stale "
                    f"(stored input_hash {stored_hash}, current {current}); recalibrate the case"
                )
            )
    return results


def check(ctx: GuardContext) -> list[Result]:
    """Fail every gated case with no calibration record or a stale one.

    Parameters
    ----------
    ctx : GuardContext
        ``ctx.repo_root`` is the work tree, checked out at HEAD, whose
        ``evals/`` directory is inspected. ``ctx.base`` is unused.

    Returns
    -------
    list[Result]
        One ``fail`` per gated item with no record, per gated item whose
        stored ``input_hash`` differs from the case's recomputed one, and per
        case whose ``calibration.json``, ``case.toml`` or inputs cannot be
        read. Empty when every gated case is freshly calibrated.
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
                gated_items = [item for item in _item_ids(case_dir) if item in gated]
            except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
                results.append(
                    _fail(f"{skill_dir.name}/{case_dir.name}: case.toml cannot be read ({exc})")
                )
                continue
            if gated_items:
                results.extend(_check_case(skill_dir.name, case_dir, gated_items))
    return results
