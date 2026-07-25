"""Offline drift detector for vendored vault machinery (W3).

Reads a target repo's machinery lockfile (``.vault/machinery.lock.json``)
and reports, per managed file:

- ``OK``         — the file's sha256 matches its lock entry
- ``LOCAL-EDIT`` — the file exists but its hash differs from the lock
- ``MISSING``    — the file is in the lock but not on disk
- ``UNTRACKED``  — a file under a managed scan root that is not in the lock

A lock entry with ``kind: "json-key"`` (W4: the vault's settings.json
``hooks`` key) is verified semantically: its sha256 is the canonical-JSON
hash (sorted keys, no whitespace) of that ONE key's value, so reformatting
the file or reordering sibling keys stays ``OK`` while changing the key's
value is a ``LOCAL-EDIT``. A file that no longer parses, or has lost the
key, is a ``LOCAL-EDIT`` too.

A lock entry with ``tier: "scaffold"`` (W5: init-scaffolded, owner-owned
files under a managed scan root, e.g. the taxonomy-parameterized
``vault_scope.py``) carries no hash: the owner may edit it freely, so it is
``OK`` whenever it exists and ``MISSING`` only when deleted. Its lock
record exists chiefly so the UNTRACKED scan does not flag it.

The UNTRACKED scan covers every managed root — ``.claude/scripts``,
``.claude/agents``, ``.codex/agents``, ``.claude/skills``, and
``.codex/skills`` — with the usual runtime-junk exclusions.

Human-readable report by default; ``--json`` for machines; ``--strict``
exits 1 on any non-OK status. ``--target`` selects the repo (default: cwd).

Exit codes: 0 = report produced (and clean, under ``--strict``);
1 = ``--strict`` and at least one non-OK file; 2 = no usable lockfile.

Scope: W3 shipped the lockfile format plus adopt/check/dumb-upgrade; W4
added the json-key entries; W5 added the scaffold tier (and machinery_sync
grew the ``init`` verb). An ``upstream`` comparison verb remains
deliberately deferred; this tool intentionally knows nothing about it.

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
MANAGED_SCAN_ROOTS = (
    ".claude/scripts",
    ".claude/agents",
    ".codex/agents",
    ".claude/skills",
    ".codex/skills",
)

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


def _json_key_status(candidate: Path, entry: dict) -> str:
    """Drift status of a ``kind: "json-key"`` lock entry.

    The lock's sha256 is the canonical-JSON hash of one key's value, so the
    comparison survives file reformatting and sibling-key changes.
    """
    if not candidate.is_file():
        return STATUS_MISSING
    try:
        document = json.loads(candidate.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return STATUS_LOCAL_EDIT
    key = entry.get("key")
    if not isinstance(document, dict) or key not in document:
        return STATUS_LOCAL_EDIT
    canonical = json.dumps(document[key], sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return STATUS_OK if digest == entry.get("sha256") else STATUS_LOCAL_EDIT


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
        if entry.get("tier") == "scaffold":
            # Scaffold files are owner-owned: no hash to drift from, only
            # presence matters (and suppressing the UNTRACKED scan).
            status = STATUS_OK if candidate.is_file() else STATUS_MISSING
        elif entry.get("kind") == "json-key":
            status = _json_key_status(candidate, entry)
        elif not candidate.is_file():
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
    for scan_relative in MANAGED_SCAN_ROOTS:
        scan_root = target / scan_relative
        if not scan_root.is_dir():
            continue
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
