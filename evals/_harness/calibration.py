"""Computes calibration records: the admission rule for candidate items.

A ``gate-candidate`` item is admitted only when all four hold: its skill arm
hits at least 5 of 6 executions; its no-skill arm (same fixture and prompt,
skill-naming clause removed) hits at most 1 of 3; its mechanical hit count
equals the manually audited hit count; and its matcher credits no finding
that audits as belonging to a sibling item. A ``triggering`` item calibrates
on the skill arm alone (still 6 executions, still 5-of-6, still the audited
and cross-match checks) and never has a no-skill arm. A ``trend`` item is
never admitted; its record is filled in but no bar is applied.

This module never runs a calibration attempt or invokes a model — every
count and audit entry is supplied by the caller (the conductor and the
hand-run audit, #995 and #989 respectively). It only decides admission from
those already-collected counts, and computes the two content hashes
(``compute_input_hash``, ``fixture_fingerprint``) that guard modules compare
against, delegating all tree/output hashing to ``deps.tree_hash`` and
``fingerprint.builder_output_fingerprint`` rather than reimplementing either.

Public contract
----------------
``compute_no_skill_arm(attempts) -> dict | str``
    Applies the 2-replacement contamination cap to an ordered sequence of
    no-skill attempts.

``compute_calibration_record(...) -> dict``
    Computes one item's calibration record, deciding gate admission.

``write_calibration_records(case_dir, records) -> Path``
    Writes a case's records to ``<case_dir>/calibration.json``.

``compute_input_hash(case_dir) -> str``
    Hashes every calibrated input for a case: its prompt, its fixture or
    builder, its items, and its predicates.

``fixture_fingerprint(case_dir) -> str``
    Hashes a case's fixture alone (builder output, or committed ``fixture/``).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

import jsonschema

from evals._harness.deps import tree_hash
from evals._harness.fingerprint import builder_output_fingerprint

_SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "calibration-record.schema.json"
_VALID_KINDS = {"gate-candidate", "triggering", "trend"}


def compute_no_skill_arm(attempts: list[dict]) -> dict | str:
    """Process a no-skill arm's ordered attempts under the contamination cap.

    Parameters
    ----------
    attempts : list[dict]
        Ordered ``{"contaminated": bool, "hit": bool}`` records, one per
        no-skill attempt drawn, including any replacement draws already
        appended in the order they were run.

    Returns
    -------
    dict | str
        ``{"n", "hits", "replacements"}`` counting only non-contaminated
        attempts, or the literal string ``"baseline-void"`` when a third
        contaminated attempt occurs (at most 2 replacements are drawn).
    """
    replacements = 0
    counted_n = 0
    counted_hits = 0
    for attempt in attempts:
        if attempt["contaminated"]:
            if replacements >= 2:
                return "baseline-void"
            replacements += 1
            continue
        counted_n += 1
        if attempt["hit"]:
            counted_hits += 1
    return {"n": counted_n, "hits": counted_hits, "replacements": replacements}


def _cross_match_result(item_id: str, audit: list[dict]) -> str:
    for entry in audit:
        if entry["credited_item"] != item_id:
            continue
        if entry["audited_item"] != item_id:
            return "fail"
    return "pass"


def compute_calibration_record(
    *,
    item_id: str,
    kind: str,
    skill_hits: int,
    skill_n: int,
    no_skill_attempts: list[dict] | None,
    audited_hits: int,
    audit: list[dict],
    input_hash: str,
) -> dict:
    """Compute one item's calibration record, deciding gate admission.

    Parameters
    ----------
    item_id : str
        The item being scored.
    kind : str
        ``"gate-candidate"``, ``"triggering"``, or ``"trend"``.
    skill_hits : int
        Hits on the skill arm.
    skill_n : int
        Executions on the skill arm (6, for both admissible kinds).
    no_skill_attempts : list[dict] | None
        Ordered no-skill attempts in ``compute_no_skill_arm``'s shape, or
        ``None`` when no no-skill arm was run. Ignored for ``"triggering"``.
    audited_hits : int
        The manually audited hit count on the calibration raws.
    audit : list[dict]
        ``{"raw", "finding", "credited_item", "audited_item"}`` entries, in
        #993's calibration-record schema shape. Stored verbatim.
    input_hash : str
        This case's ``compute_input_hash`` result.

    Returns
    -------
    dict
        A record matching ``schemas/calibration-record.schema.json``.

    Raises
    ------
    ValueError
        If ``kind`` is not one of ``"gate-candidate"``, ``"triggering"``, or
        ``"trend"``.
    """
    if kind not in _VALID_KINDS:
        raise ValueError(f"unknown item kind: {kind!r}")

    cross_match_result = _cross_match_result(item_id, audit)

    if kind == "trend":
        no_skill_arm_result = (
            compute_no_skill_arm(no_skill_attempts) if no_skill_attempts is not None else None
        )
        return {
            "n": skill_n,
            "hits": skill_hits,
            "audited_hits": audited_hits,
            "cross_match_result": cross_match_result,
            "no_skill_arm_result": no_skill_arm_result,
            "gate_or_trend_status": "trend",
            "input_hash": input_hash,
            "audit": list(audit),
        }

    rate_matches = skill_hits == audited_hits
    skill_arm_passes = skill_n == 6 and skill_hits >= 5

    if kind == "triggering":
        admitted = skill_arm_passes and rate_matches and cross_match_result == "pass"
        return {
            "n": skill_n,
            "hits": skill_hits,
            "audited_hits": audited_hits,
            "cross_match_result": cross_match_result,
            "no_skill_arm_result": None,
            "gate_or_trend_status": "gate" if admitted else "trend",
            "input_hash": input_hash,
            "audit": list(audit),
        }

    # kind == "gate-candidate"
    if no_skill_attempts is None:
        no_skill_arm_result = None
        no_skill_passes = False
    else:
        no_skill_arm_result = compute_no_skill_arm(no_skill_attempts)
        if no_skill_arm_result == "baseline-void":
            no_skill_passes = False
        else:
            no_skill_passes = no_skill_arm_result["n"] == 3 and no_skill_arm_result["hits"] <= 1

    admitted = skill_arm_passes and no_skill_passes and rate_matches and cross_match_result == "pass"
    return {
        "n": skill_n,
        "hits": skill_hits,
        "audited_hits": audited_hits,
        "cross_match_result": cross_match_result,
        "no_skill_arm_result": no_skill_arm_result,
        "gate_or_trend_status": "gate" if admitted else "trend",
        "input_hash": input_hash,
        "audit": list(audit),
    }


def write_calibration_records(case_dir: Path, records: dict[str, dict]) -> Path:
    """Write a case's calibration records to ``<case_dir>/calibration.json``.

    Validates every record against ``schemas/calibration-record.schema.json``
    before writing. Writes nothing else: never a file outside *case_dir*,
    never a file named ``tests.md``.

    Parameters
    ----------
    case_dir : Path
        The case's ``evals/<skill>/<case>/`` directory.
    records : dict[str, dict]
        Item id -> calibration record.

    Returns
    -------
    Path
        The written ``calibration.json`` path.

    Raises
    ------
    ValueError
        If *case_dir* is not shaped ``evals/<skill>/<case>``, or its
        ``calibration.json`` is a symlink.
    jsonschema.ValidationError
        If any record fails schema validation.
    """
    if case_dir.resolve().parent.parent.name != "evals":
        raise ValueError(f"case_dir must be an evals/<skill>/<case> directory, got {case_dir}")

    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    for record in records.values():
        jsonschema.validate(record, schema)

    dest = case_dir / "calibration.json"
    if dest.is_symlink():
        raise ValueError(f"refusing to write through a symlinked destination: {dest}")
    dest.write_text(json.dumps(records, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return dest


def _resolve_repo_root(case_dir: Path) -> Path:
    result = subprocess.run(
        ["git", "-C", str(case_dir), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(result.stdout.strip())


def _relpath(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _load_case_toml(case_dir: Path) -> dict:
    return tomllib.loads((case_dir / "case.toml").read_text(encoding="utf-8"))


def _resolve_builder(case_dir: Path, repo_root: Path, case_toml: dict) -> Path | None:
    builder_key = case_toml.get("builder")
    if builder_key:
        return (repo_root / builder_key).resolve()
    local_builder = case_dir / "build_fixture.py"
    if local_builder.exists():
        return local_builder.resolve()
    return None


def _run_builder(builder_path: Path, dest: Path, repo_root: Path) -> None:
    subprocess.run(
        [sys.executable, str(builder_path), str(dest)],
        check=True,
        cwd=str(repo_root),
    )


def _canonical_items(items: list[dict]) -> list[dict]:
    return [
        {
            "id": item["id"],
            "kind": item["kind"],
            "scorer": item["scorer"],
            "params": item.get("params", {}),
        }
        for item in items
    ]


def _no_fixture_or_builder_error(case_dir: Path) -> ValueError:
    return ValueError(f"case {case_dir} supplies neither a committed fixture nor a builder")


def _fixture_component(case_dir: Path, repo_root: Path, case_toml: dict) -> str | list:
    builder_path = _resolve_builder(case_dir, repo_root, case_toml)
    fixture_dir = case_dir / "fixture"
    has_fixture = fixture_dir.is_dir()
    if builder_path is None and not has_fixture:
        raise _no_fixture_or_builder_error(case_dir)

    if builder_path is None:
        return tree_hash([_relpath(fixture_dir, repo_root)], repo=repo_root)

    fixture_tree_hash_or_null = (
        tree_hash([_relpath(fixture_dir, repo_root)], repo=repo_root) if has_fixture else None
    )
    builder_hash = tree_hash([_relpath(builder_path, repo_root)], repo=repo_root)
    with tempfile.TemporaryDirectory() as tmp_dir:
        dest = Path(tmp_dir) / "build"
        _run_builder(builder_path, dest, repo_root)
        output_fingerprint = builder_output_fingerprint(dest)
    return [fixture_tree_hash_or_null, builder_hash, output_fingerprint]


def compute_input_hash(case_dir: Path) -> str:
    """Hash every calibrated input for a case.

    A sha256 hex digest over the canonical JSON array ``[prompt_text,
    fixture_component, items, predicates_hash]``. ``prompt_text`` is the full
    content of the file ``case.toml``'s ``prompt`` key names. ``items`` is
    the case's ``[[items]]`` tables (ids, kinds, scorer names and params).
    ``predicates_hash`` is the sha256 of the case's ``predicates.py`` bytes,
    ``None`` if absent.

    Parameters
    ----------
    case_dir : Path
        The case's ``evals/<skill>/<case>/`` directory.

    Returns
    -------
    str
        A sha256 hex digest.

    Raises
    ------
    ValueError
        If the case supplies neither a committed ``fixture/`` nor a builder.
    """
    repo_root = _resolve_repo_root(case_dir)
    case_toml = _load_case_toml(case_dir)

    prompt_path = case_dir / case_toml["prompt"]
    prompt_text = prompt_path.read_text(encoding="utf-8")

    fixture_component = _fixture_component(case_dir, repo_root, case_toml)
    items = _canonical_items(case_toml.get("items", []))

    predicates_path = case_dir / "predicates.py"
    predicates_hash = (
        hashlib.sha256(predicates_path.read_bytes()).hexdigest()
        if predicates_path.exists()
        else None
    )

    payload = json.dumps(
        [prompt_text, fixture_component, items, predicates_hash],
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def fixture_fingerprint(case_dir: Path) -> str:
    """Hash a case's fixture alone.

    Parameters
    ----------
    case_dir : Path
        The case's ``evals/<skill>/<case>/`` directory.

    Returns
    -------
    str
        ``builder_output_fingerprint`` of a fresh build into a temporary
        directory, for a case with a builder; otherwise the ``deps.tree_hash``
        of its committed ``fixture/``.

    Raises
    ------
    ValueError
        If the case supplies neither a committed ``fixture/`` nor a builder.
    """
    repo_root = _resolve_repo_root(case_dir)
    case_toml = _load_case_toml(case_dir)
    builder_path = _resolve_builder(case_dir, repo_root, case_toml)

    if builder_path is not None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            dest = Path(tmp_dir) / "build"
            _run_builder(builder_path, dest, repo_root)
            return builder_output_fingerprint(dest)

    fixture_dir = case_dir / "fixture"
    if fixture_dir.is_dir():
        return tree_hash([_relpath(fixture_dir, repo_root)], repo=repo_root)

    raise _no_fixture_or_builder_error(case_dir)
