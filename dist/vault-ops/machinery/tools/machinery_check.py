"""Offline drift detector for vendored vault machinery (W3).

Reads a target repo's machinery lockfile (``.vault/machinery.lock.json``)
and reports, per managed file:

- ``OK``         — the file's sha256 matches its lock entry
- ``LOCAL-EDIT`` — the file exists but its hash differs from the lock
- ``MISSING``    — the file is in the lock but not on disk
- ``UNTRACKED``  — a file under ``.claude/scripts/`` that is not in the lock

Human-readable report by default; ``--json`` for machines; ``--strict``
exits 1 on any non-OK status. ``--target`` selects the repo (default: cwd).

Exit codes: 0 = report produced (and clean, under ``--strict``);
1 = ``--strict`` and at least one non-OK file; 2 = no usable lockfile.

Scope: this is W3 of the vault-machinery consolidation — lockfile format
plus adopt/check/dumb-upgrade. The scaffolding interview, an ``init`` verb,
and an ``upstream`` comparison verb are deliberately deferred to the later
wiring-generator (W4) and vault-init/upgrade-skill (W5) chunks; this tool
intentionally knows nothing about them.

Hard constraints (kept on purpose, enforced by the workshop's test suite):
Python stdlib only — this file is vendored into the vault and must run from
hooks and afk Docker slices — it never touches the network, and it does not
require git.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

LOCKFILE_RELPATH = ".vault/machinery.lock.json"
MANAGED_SCAN_ROOT = ".claude/scripts"

STATUS_OK = "OK"
STATUS_LOCAL_EDIT = "LOCAL-EDIT"
STATUS_MISSING = "MISSING"
STATUS_UNTRACKED = "UNTRACKED"

# Regenerable runtime junk that must not be reported as UNTRACKED: a vault
# that has merely run its hooks would otherwise never scan clean.
_JUNK_DIR_NAMES = frozenset(
    {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"}
)
_JUNK_FILE_NAMES = frozenset({".DS_Store"})
_JUNK_SUFFIXES = (".pyc",)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_junk(relative_parts: tuple[str, ...]) -> bool:
    if _JUNK_DIR_NAMES & set(relative_parts[:-1]):
        return True
    name = relative_parts[-1]
    return name in _JUNK_FILE_NAMES or name.endswith(_JUNK_SUFFIXES)


def load_lockfile(target: Path) -> dict:
    """Parse the target's lockfile.

    Parameters
    ----------
    target
        Root of the repo being checked.

    Returns
    -------
    dict
        The parsed lockfile.

    Raises
    ------
    FileNotFoundError
        When no lockfile exists at ``.vault/machinery.lock.json``.
    ValueError
        When the lockfile is not valid JSON or lacks a ``files`` mapping.
    """
    lock_path = target / LOCKFILE_RELPATH
    if not lock_path.is_file():
        raise FileNotFoundError(f"no lockfile at {lock_path}")
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"lockfile at {lock_path} is not valid JSON: {exc}") from exc
    if not isinstance(lock.get("files"), dict):
        raise ValueError(f"lockfile at {lock_path} has no 'files' mapping")
    return lock


def collect_statuses(target: Path, lock: dict) -> list[dict]:
    """Compute the per-file drift status list for a target repo.

    Parameters
    ----------
    target
        Root of the repo being checked.
    lock
        Parsed lockfile (see :func:`load_lockfile`).

    Returns
    -------
    list[dict]
        One record per file: ``{"path", "status", "keep_local"}``, locked
        files first (in lock order), then UNTRACKED files sorted by path.
    """
    records: list[dict] = []
    for relative, entry in lock["files"].items():
        candidate = target / relative
        if not candidate.is_file():
            status = STATUS_MISSING
        elif _sha256(candidate) == entry.get("sha256"):
            status = STATUS_OK
        else:
            status = STATUS_LOCAL_EDIT
        records.append(
            {
                "path": relative,
                "status": status,
                "keep_local": bool(entry.get("keep_local", False)),
            }
        )

    locked_paths = set(lock["files"])
    scan_root = target / MANAGED_SCAN_ROOT
    if scan_root.is_dir():
        for candidate in sorted(scan_root.rglob("*")):
            if not candidate.is_file():
                continue
            relative_parts = candidate.relative_to(target).parts
            if _is_junk(relative_parts):
                continue
            relative = "/".join(relative_parts)
            if relative in locked_paths:
                continue
            records.append(
                {"path": relative, "status": STATUS_UNTRACKED, "keep_local": False}
            )
    return records


def _summarize(records: list[dict]) -> dict:
    summary = {status: 0 for status in
               (STATUS_OK, STATUS_LOCAL_EDIT, STATUS_MISSING, STATUS_UNTRACKED)}
    for record in records:
        summary[record["status"]] += 1
    return summary


def _print_human(target: Path, records: list[dict], summary: dict) -> None:
    print(f"machinery check: {target}")
    width = max((len(r["status"]) for r in records), default=2)
    for record in records:
        marker = "  (keep-local)" if record["keep_local"] else ""
        print(f"  {record['status']:<{width}}  {record['path']}{marker}")
    parts = ", ".join(f"{count} {status}" for status, count in summary.items())
    print(f"summary: {parts}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="machinery_check",
        description="Report drift between a repo's vendored machinery and its lockfile.",
    )
    parser.add_argument(
        "--target",
        default=".",
        help="target repo root (default: current directory)",
    )
    parser.add_argument(
        "--json", action="store_true", help="machine-readable JSON report"
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 when any file is not OK",
    )
    args = parser.parse_args(argv)

    target = Path(args.target)
    try:
        lock = load_lockfile(target)
    except (FileNotFoundError, ValueError) as exc:
        if args.json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    records = collect_statuses(target, lock)
    summary = _summarize(records)
    clean = all(record["status"] == STATUS_OK for record in records)

    if args.json:
        print(
            json.dumps(
                {
                    "target": str(target),
                    "lockfile": LOCKFILE_RELPATH,
                    "files": records,
                    "summary": summary,
                    "clean": clean,
                },
                indent=2,
            )
        )
    else:
        _print_human(target, records, summary)

    if args.strict and not clean:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
