"""Guard: every run file and calibration record the diff touches matches its schema.

Diffs ``$(VERSION_BASE)...HEAD`` (the ``ctx.base`` ref the runner passes) with
``--no-renames`` and validates every file the diff adds, modifies or type-changes (a symlink swapped
in is read through, and fails loudly if it dangles):

- a run file — a ``.json`` file directly under ``evals/<skill>/runs/`` (its
  deeper files are raws, never run files) — against
  ``schemas/run-file.schema.json``;
- a ``calibration.json`` directly under ``evals/<skill>/<case>/`` — a map of
  item id to record — each record against
  ``schemas/calibration-record.schema.json``.

The schemas (owned by #993) are loaded from the harness's own ``schemas/``
directory, never redefined here. A file that is not valid JSON fails too, and
a file the diff only deletes is skipped (``runs_immutable`` owns deletions).
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import jsonschema

from evals._harness.guards import GuardContext, Result

_GUARD_NAME = "schema_validate"
_SCHEMAS = Path(__file__).resolve().parents[1] / "schemas"
_RUN_FILE = re.compile(r"^evals/[^/]+/runs/[^/]+\.json$")
_CALIBRATION_FILE = re.compile(r"^evals/[^/]+/[^/]+/calibration\.json$")


def _load_schema(name: str) -> dict:
    return json.loads((_SCHEMAS / name).read_text(encoding="utf-8"))


def _added_or_modified(repo_root: Path, base: str) -> list[str]:
    output = subprocess.run(
        [
            "git", "-C", str(repo_root), "diff", "--no-renames", "--diff-filter=AMT",
            "--name-only", "-z", f"{base}...HEAD",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [path for path in output.split("\0") if path]


def _validation_message(exc: jsonschema.ValidationError) -> str:
    location = "/".join(str(part) for part in exc.absolute_path) or "<root>"
    return f"{exc.message} (at {location})"


def _fail(message: str) -> Result:
    return Result(level="fail", guard=_GUARD_NAME, message=message)


def _check_run_file(path: Path, rel_path: str, schema: dict) -> list[Result]:
    try:
        run = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [_fail(f"{rel_path}: not readable as JSON ({exc})")]
    try:
        jsonschema.validate(run, schema)
    except jsonschema.ValidationError as exc:
        return [_fail(f"{rel_path}: violates run-file.schema.json: {_validation_message(exc)}")]
    return []


def _check_calibration_file(path: Path, rel_path: str, schema: dict) -> list[Result]:
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [_fail(f"{rel_path}: not readable as JSON ({exc})")]
    if not isinstance(records, dict):
        return [_fail(f"{rel_path}: must be a JSON object mapping item id to record")]
    results: list[Result] = []
    for item_id, record in records.items():
        try:
            jsonschema.validate(record, schema)
        except jsonschema.ValidationError as exc:
            results.append(
                _fail(
                    f"{rel_path}: record {item_id!r} violates "
                    f"calibration-record.schema.json: {_validation_message(exc)}"
                )
            )
    return results


def check(ctx: GuardContext) -> list[Result]:
    """Fail every changed or added run file or calibration record that breaks its schema.

    Parameters
    ----------
    ctx : GuardContext
        ``ctx.base`` is the ref to diff against; ``ctx.repo_root`` is the
        work tree, checked out at HEAD, whose files are validated.

    Returns
    -------
    list[Result]
        One ``fail`` per invalid run file, and one per invalid record of a
        ``calibration.json`` (or one for a ``calibration.json`` that is not a
        map at all). Empty when every touched file validates.
    """
    run_schema = _load_schema("run-file.schema.json")
    calibration_schema = _load_schema("calibration-record.schema.json")
    results: list[Result] = []
    for rel_path in _added_or_modified(ctx.repo_root, ctx.base):
        path = ctx.repo_root / rel_path
        if _RUN_FILE.match(rel_path):
            results.extend(_check_run_file(path, rel_path, run_schema))
        elif _CALIBRATION_FILE.match(rel_path):
            results.extend(_check_calibration_file(path, rel_path, calibration_schema))
    return results
