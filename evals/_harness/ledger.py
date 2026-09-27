"""Writes one write-once run file per eval run, plus its verbatim raws.

Treats #991's ``scorer.py`` output as read-only input and never edits
``scorer.py``; raws come from the conductor, not from the scorer. Validates
every write against ``schemas/run-file.schema.json``.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import jsonschema

from evals._harness.transcript import parse_transcript

_HOME = str(Path.home())
_HOME_PLACEHOLDER = "<HOME>"
_SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "run-file.schema.json"


def _scrub_text(text: str) -> str:
    return text.replace(_HOME, _HOME_PLACEHOLDER)


def _scrub_value(value):
    if isinstance(value, str):
        return _scrub_text(value)
    if isinstance(value, list):
        return [_scrub_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _scrub_value(item) for key, item in value.items()}
    return value


def _fingerprint_short(fingerprint: dict) -> str:
    payload = json.dumps(fingerprint, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:8]


def _validate_path_segment(value, label: str) -> str:
    """Return *value* as a safe single path segment, or raise ``ValueError``.

    A safe segment is non-empty, contains no ``/`` or ``\\``, is not ``.`` or
    ``..``, and is not itself absolute — so it can never be used to write
    outside the directory it is joined under.
    """
    text = str(value)
    if not text or text in (".", "..") or "/" in text or "\\" in text or Path(text).is_absolute():
        raise ValueError(f"unsafe {label}: {value!r}")
    return text


def _model_ids_for_case(case: dict, raw_sources: dict[str, Path]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for attempt in case["attempts"]:
        source = raw_sources[attempt["raw"]]
        for jsonl_path in sorted(source.glob("*.jsonl")):
            transcript = parse_transcript(jsonl_path)
            for model_id in transcript.model_ids:
                if model_id not in seen:
                    seen.add(model_id)
                    ordered.append(model_id)
    return ordered


def _source_files(source: Path) -> list[Path]:
    return [path for path in sorted(source.rglob("*")) if path.is_file()]


def write_run(
    runs_dir: Path,
    run: dict,
    raw_sources: dict[str, Path],
    *,
    now: datetime | None = None,
) -> Path:
    """Write one run file plus its verbatim raws under *runs_dir*.

    Parameters
    ----------
    runs_dir : Path
        The skill's ``evals/<skill>/runs/`` directory.
    run : dict
        The run-file object. Each case's ``attempts[i]["raw"]`` is only a key
        into *raw_sources*: it is never written verbatim into the run file.
        ``write_run`` owns the destination layout and overwrites each
        attempt's ``raw`` with ``f"{stem}/{case}/attempt-{n}/"``, where
        ``stem`` is the run file's own stem, ``case`` is that attempt's
        case id, and ``n`` its attempt number — so a caller can never predict
        or collide with another run's raw paths. Each case's ``model_ids`` is
        likewise overwritten by this function from that case's raw
        transcripts.
    raw_sources : dict[str, Path]
        Maps each attempt's original (caller-supplied) ``raw`` value to the
        directory the conductor collected for that attempt.
    now : datetime | None
        The UTC instant to timestamp the run file with. Defaults to the
        current time; a caller passes a fixed value for a deterministic
        filename.

    Returns
    -------
    Path
        The written run file's path.

    Raises
    ------
    FileExistsError
        If the run-file path, or any raw file's destination path, already
        exists.
    ValueError
        If a case id or attempt number is not a safe single path segment
        (empty, containing ``/`` or ``\\``, equal to ``.`` or ``..``, or
        absolute).
    """
    run = _scrub_value(json.loads(json.dumps(run)))
    for case in run["cases"]:
        case["model_ids"] = _model_ids_for_case(case, raw_sources)

    instant = now if now is not None else datetime.now(timezone.utc)
    timestamp = instant.strftime("%Y%m%dT%H%M%SZ")
    stem = f"{timestamp}-{_fingerprint_short(run['fingerprint'])}"
    run_file_path = runs_dir / f"{stem}.json"
    if run_file_path.exists():
        raise FileExistsError(f"run file already exists: {run_file_path}")

    # write_run owns the raw destination layout: `<stem>/<case>/attempt-<n>/`.
    # The caller's `raw` value is only the lookup key into `raw_sources`; it
    # is replaced here before anything is written or validated.
    raw_copy_sources: dict[str, Path] = {}
    for case in run["cases"]:
        case_id = _validate_path_segment(case["case"], "case id")
        for attempt in case["attempts"]:
            attempt_segment = _validate_path_segment(
                f"attempt-{attempt['attempt']}", "attempt number"
            )
            source = raw_sources[attempt["raw"]]
            new_raw = f"{stem}/{case_id}/{attempt_segment}/"
            attempt["raw"] = new_raw
            raw_copy_sources[new_raw] = source

    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(run, schema)

    copy_plan: list[tuple[Path, Path]] = []
    for raw, source in raw_copy_sources.items():
        dest_root = runs_dir / raw
        for src_path in _source_files(source):
            dest_path = dest_root / src_path.relative_to(source)
            if dest_path.exists():
                raise FileExistsError(f"raw file already exists: {dest_path}")
            copy_plan.append((src_path, dest_path))

    for src_path, dest_path in copy_plan:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            text = src_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            shutil.copyfile(src_path, dest_path)
            continue
        dest_path.write_text(_scrub_text(text), encoding="utf-8")

    runs_dir.mkdir(parents=True, exist_ok=True)
    run_file_path.write_text(json.dumps(run, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return run_file_path
