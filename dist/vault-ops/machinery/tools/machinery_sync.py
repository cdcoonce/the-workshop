"""Vendor CLI for the vault machinery payload (W3): adopt + dumb upgrade.

Verbs
-----
``adopt --target <repo> --source <machinery dir>``
    First-run migration. Compares every vendor-map entry's source bytes to
    the target file. If ALL managed files are byte-identical it writes the
    lockfile (``.vault/machinery.lock.json``) and exits 0. Any diff prints a
    per-file summary and refuses (exit 1): adopt must be a provable no-op.

``upgrade --target <repo> --source <machinery dir>``
    Dumb re-vendor. DRY-RUN BY DEFAULT — prints the per-file planned action
    (copy / skip-identical / keep-local / REFUSE local-edit); ``--apply``
    performs it. Refuses to overwrite any file whose current hash differs
    from the lock (a local edit) unless ``--keep-local <path>`` (skips the
    file and records ``"keep_local": true`` on its lock entry — the flag is
    sticky on later upgrades) or ``--force``. A plan containing any refusal
    applies NOTHING (atomic): resolve each refusal, then re-run. After a
    successful apply the lockfile is rewritten.

Structural safety
-----------------
The only paths this tool may ever write inside the target are (a) exact
vendor-map target paths and (b) ``.vault/machinery.lock.json``. That is
enforced in code by a write gate built from the validated vendor map — a
map entry whose target escapes the target root (``../..``, absolute paths)
or whose source escapes the machinery dir aborts the run before any write.

Lockfile schema (``schema: 1``)::

    {
      "schema": 1,
      "source": {"repo": ..., "preset": ..., "version": ..., "ref": ...},
      "generated_at": "<ISO-8601 UTC>",
      "files": {"<target path>": {"tier": "managed", "sha256": "..."}}
    }

``version``/``preset`` come from the manifest beside the machinery dir
(``manifest.json`` in a source checkout, ``.claude-plugin/plugin.json`` in a
built dist tree); ``ref`` is the workshop checkout's git sha when resolvable,
else null — this tool may shell out to git for that one value but degrades
gracefully without it.

Scope: this is W3 of the vault-machinery consolidation — lockfile format
plus adopt/check/dumb-upgrade. The scaffolding interview, an ``init`` verb
for fresh vaults, and an ``upstream`` comparison verb are deliberately
deferred to the later wiring-generator (W4) and vault-init/upgrade-skill
(W5) chunks; this tool intentionally knows nothing about them.

Exit codes: 0 = success (or an executable dry-run plan); 1 = refusal
(adopt diff, upgrade over a local edit); 2 = environment/config error
(missing lockfile for upgrade, unreadable vendor map, hostile map path).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

LOCKFILE_RELPATH = ".vault/machinery.lock.json"
SOURCE_REPO_NAME = "the-workshop"

ACTION_COPY = "copy"
ACTION_SKIP = "skip-identical"
ACTION_KEEP_LOCAL = "keep-local"
ACTION_REFUSE = "REFUSE local-edit"

ADOPT_IDENTICAL = "identical"
ADOPT_DIFFERS = "differs"
ADOPT_MISSING = "missing"


class VendorMapError(Exception):
    """Raised when the vendor map is unreadable or names an unsafe path."""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _resolve_inside(root: Path, relative: str, *, label: str) -> Path:
    """Resolve ``relative`` against ``root`` and require containment.

    Parameters
    ----------
    root
        Directory the resolved path must stay inside.
    relative
        Path string from the vendor map (untrusted input).
    label
        Which map field is being validated, for the error message.

    Returns
    -------
    Path
        The resolved absolute path.

    Raises
    ------
    VendorMapError
        When the path is absolute, empty, or escapes ``root``.
    """
    if not relative or Path(relative).is_absolute():
        raise VendorMapError(
            f"vendor-map {label} path {relative!r} must be relative"
        )
    resolved = (root / relative).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise VendorMapError(
            f"vendor-map {label} path {relative!r} escapes {root}"
        )
    return resolved


class VendorMap:
    """The validated managed set: (source relpath, target relpath) pairs."""

    def __init__(self, source_dir: Path, entries: list[dict]):
        self.source_dir = source_dir
        self.entries: list[tuple[str, str]] = []
        for entry in entries:
            if entry.get("kind") != "file":
                # Forward compatibility: schema 1 readers only understand
                # "file" entries; anything else is a hard error rather than a
                # silent skip, so a future-kind map is not half-applied.
                raise VendorMapError(
                    f"unsupported vendor-map entry kind: {entry.get('kind')!r}"
                )
            source_rel = entry.get("source", "")
            target_rel = entry.get("target", "")
            _resolve_inside(source_dir, source_rel, label="source")
            self.entries.append((source_rel, target_rel))

    @classmethod
    def load(cls, source_dir: Path) -> "VendorMap":
        map_path = source_dir / "vendor-map.json"
        if not map_path.is_file():
            raise VendorMapError(f"no vendor map at {map_path}")
        try:
            data = json.loads(map_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise VendorMapError(f"vendor map at {map_path} is not valid JSON: {exc}")
        if data.get("schema") != 1:
            raise VendorMapError(
                f"vendor map schema {data.get('schema')!r} is not supported "
                "(this reader understands schema 1)"
            )
        return cls(source_dir, data.get("entries", []))


class TargetWriter:
    """Write gate: the ONLY component allowed to mutate the target repo.

    Built from the validated vendor map, its allowlist is exactly the map's
    target paths plus the lockfile. Every write resolves through
    :func:`_resolve_inside`, so a hostile map path fails at construction
    time — before any write — rather than being caught by convention.
    """

    def __init__(self, target_root: Path, vendor_map: VendorMap):
        self._root = target_root
        self._allowed: dict[str, Path] = {}
        for _, target_rel in vendor_map.entries:
            self._allowed[target_rel] = _resolve_inside(
                target_root, target_rel, label="target"
            )
        self._allowed[LOCKFILE_RELPATH] = _resolve_inside(
            target_root, LOCKFILE_RELPATH, label="lockfile"
        )

    def write_bytes(self, target_rel: str, data: bytes) -> None:
        try:
            destination = self._allowed[target_rel]
        except KeyError:
            raise VendorMapError(
                f"refusing to write {target_rel!r}: not an allowlisted path"
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)


def resolve_source_meta(source_dir: Path) -> tuple[str | None, str | None]:
    """Preset name and version for the lockfile's ``source`` block.

    Looks for ``manifest.json`` beside the machinery dir (a source checkout),
    then ``.claude-plugin/plugin.json`` (a built dist tree). Returns
    ``(None, None)`` when neither is readable — the lockfile degrades rather
    than the sync failing.
    """
    for relative in ("manifest.json", ".claude-plugin/plugin.json"):
        candidate = source_dir.parent / relative
        if not candidate.is_file():
            continue
        try:
            manifest = json.loads(candidate.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        return manifest.get("name"), manifest.get("version")
    return None, None


def resolve_git_ref(source_dir: Path) -> str | None:
    """The workshop checkout's HEAD sha, or None when git cannot resolve it."""
    try:
        result = subprocess.run(
            ["git", "-C", str(source_dir), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    sha = result.stdout.strip()
    return sha or None


def _build_lockfile(
    source_dir: Path, files: dict[str, dict]
) -> dict:
    preset, version = resolve_source_meta(source_dir)
    return {
        "schema": 1,
        "source": {
            "repo": SOURCE_REPO_NAME,
            "preset": preset,
            "version": version,
            "ref": resolve_git_ref(source_dir),
        },
        "generated_at": datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "files": files,
    }


def _load_lock(target: Path) -> dict | None:
    lock_path = target / LOCKFILE_RELPATH
    if not lock_path.is_file():
        return None
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(lock.get("files"), dict):
        return None
    return lock


def _write_lock(writer: TargetWriter, lock: dict) -> None:
    payload = (json.dumps(lock, indent=2) + "\n").encode("utf-8")
    writer.write_bytes(LOCKFILE_RELPATH, payload)


# ---------------------------------------------------------------------------
# adopt
# ---------------------------------------------------------------------------


def run_adopt(target: Path, source_dir: Path, *, as_json: bool) -> int:
    vendor_map = VendorMap.load(source_dir)
    writer = TargetWriter(target, vendor_map)

    statuses: list[dict] = []
    lock_files: dict[str, dict] = {}
    for source_rel, target_rel in vendor_map.entries:
        source_bytes = (source_dir / source_rel).read_bytes()
        candidate = target / target_rel
        if not candidate.is_file():
            status = ADOPT_MISSING
        elif candidate.read_bytes() == source_bytes:
            status = ADOPT_IDENTICAL
            lock_files[target_rel] = {
                "tier": "managed",
                "sha256": _sha256_bytes(source_bytes),
            }
        else:
            status = ADOPT_DIFFERS
        statuses.append({"target": target_rel, "status": status})

    ok = all(record["status"] == ADOPT_IDENTICAL for record in statuses)
    if ok:
        _write_lock(writer, _build_lockfile(source_dir, lock_files))

    if as_json:
        print(
            json.dumps(
                {
                    "verb": "adopt",
                    "target": str(target),
                    "source": str(source_dir),
                    "files": statuses,
                    "ok": ok,
                    "lockfile_written": ok,
                },
                indent=2,
            )
        )
    else:
        print(f"adopt: {source_dir} -> {target}")
        for record in statuses:
            print(f"  {record['status']:<9}  {record['target']}")
        if ok:
            print(f"all files byte-identical; wrote {LOCKFILE_RELPATH}")
        else:
            print(
                "REFUSED: adopt must be a provable no-op — every managed file "
                "must be byte-identical to its source. Reconcile the files "
                "above first."
            )
    return 0 if ok else 1


# ---------------------------------------------------------------------------
# upgrade
# ---------------------------------------------------------------------------


def _plan_upgrade(
    vendor_map: VendorMap,
    target: Path,
    lock: dict,
    keep_local: set[str],
    force: bool,
) -> list[dict]:
    """Per-file planned actions for a dumb re-vendor.

    Decision order per managed file: identical to source -> skip; missing on
    disk -> copy (restore); unmodified since lock -> copy; locally edited ->
    keep-local (flagged now or recorded in the lock) or REFUSE, with
    ``--force`` downgrading every refusal to a copy.
    """
    locked_files: dict[str, dict] = lock["files"]
    plan: list[dict] = []
    for source_rel, target_rel in vendor_map.entries:
        source_bytes = (vendor_map.source_dir / source_rel).read_bytes()
        candidate = target / target_rel
        entry = locked_files.get(target_rel)
        sticky_keep = bool(entry.get("keep_local")) if entry else False
        wants_keep = target_rel in keep_local or sticky_keep

        if candidate.is_file() and candidate.read_bytes() == source_bytes:
            action, reason = ACTION_SKIP, "already matches source"
        elif not candidate.is_file():
            action, reason = ACTION_COPY, "missing on disk; restoring"
        elif wants_keep:
            # Checked before the lock-hash comparison: a kept file's lock
            # entry records its LOCAL sha, so "unmodified since lock" would
            # otherwise reclassify an intact kept edit as safely copyable.
            action, reason = ACTION_KEEP_LOCAL, "local edit kept"
        else:
            current_sha = _sha256_file(candidate)
            locked_sha = entry.get("sha256") if entry else None
            if current_sha == locked_sha:
                action, reason = ACTION_COPY, "unmodified since lock"
            elif force:
                action, reason = ACTION_COPY, "local edit overwritten (--force)"
            elif entry is None:
                action, reason = ACTION_REFUSE, "exists but is not in the lock"
            else:
                action, reason = ACTION_REFUSE, "hash differs from lock"
        plan.append(
            {
                "target": target_rel,
                "source": source_rel,
                "action": action,
                "reason": reason,
            }
        )
    return plan


def run_upgrade(
    target: Path,
    source_dir: Path,
    *,
    apply: bool,
    keep_local: set[str],
    force: bool,
    as_json: bool,
) -> int:
    vendor_map = VendorMap.load(source_dir)
    writer = TargetWriter(target, vendor_map)

    lock = _load_lock(target)
    if lock is None:
        message = (
            f"no usable lockfile at {target / LOCKFILE_RELPATH}; "
            "run adopt first"
        )
        if as_json:
            print(json.dumps({"error": message}, indent=2))
        else:
            print(f"ERROR: {message}", file=sys.stderr)
        return 2

    plan = _plan_upgrade(vendor_map, target, lock, keep_local, force)
    refusals = [record for record in plan if record["action"] == ACTION_REFUSE]
    applied = False

    if apply and not refusals:
        lock_files: dict[str, dict] = {}
        for record in plan:
            target_rel = record["target"]
            if record["action"] == ACTION_KEEP_LOCAL:
                lock_files[target_rel] = {
                    "tier": "managed",
                    "sha256": _sha256_file(target / target_rel),
                    "keep_local": True,
                }
                continue
            source_bytes = (source_dir / record["source"]).read_bytes()
            if record["action"] == ACTION_COPY:
                writer.write_bytes(target_rel, source_bytes)
            lock_files[target_rel] = {
                "tier": "managed",
                "sha256": _sha256_bytes(source_bytes),
            }
        _write_lock(writer, _build_lockfile(source_dir, lock_files))
        applied = True

    if as_json:
        print(
            json.dumps(
                {
                    "verb": "upgrade",
                    "target": str(target),
                    "source": str(source_dir),
                    "apply": apply,
                    "files": plan,
                    "refusals": len(refusals),
                    "applied": applied,
                    "lockfile_written": applied,
                },
                indent=2,
            )
        )
    else:
        mode = "apply" if apply else "dry-run (pass --apply to perform)"
        print(f"upgrade [{mode}]: {source_dir} -> {target}")
        width = max(len(record["action"]) for record in plan)
        for record in plan:
            print(
                f"  {record['action']:<{width}}  {record['target']}"
                f"  ({record['reason']})"
            )
        if refusals:
            print(
                f"REFUSED: {len(refusals)} local edit(s) block this upgrade; "
                "nothing was applied. Re-run with --keep-local <path> to keep "
                "a file, or --force to overwrite."
            )
        elif applied:
            print(f"applied; rewrote {LOCKFILE_RELPATH}")

    return 1 if refusals else 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--target",
        default=".",
        help="target repo root (default: current directory)",
    )
    parser.add_argument(
        "--source",
        default=str(Path(__file__).resolve().parent.parent),
        help="machinery dir holding vendor-map.json and engine/ "
        "(default: this tool's own machinery dir)",
    )
    parser.add_argument(
        "--json", action="store_true", help="machine-readable JSON output"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="machinery_sync",
        description="Vendor the vault machinery payload into a target repo.",
    )
    subparsers = parser.add_subparsers(dest="verb", required=True)

    adopt = subparsers.add_parser(
        "adopt", help="first-run migration: lock an already-identical target"
    )
    _add_common_arguments(adopt)

    upgrade = subparsers.add_parser(
        "upgrade", help="dumb re-vendor (dry-run by default; --apply to perform)"
    )
    _add_common_arguments(upgrade)
    upgrade.add_argument(
        "--apply",
        action="store_true",
        help="perform the plan (default is dry-run)",
    )
    upgrade.add_argument(
        "--keep-local",
        action="append",
        default=[],
        metavar="PATH",
        help="target path whose local edit is kept and recorded "
        "(repeatable; sticky on later upgrades)",
    )
    upgrade.add_argument(
        "--force",
        action="store_true",
        help="overwrite local edits instead of refusing",
    )

    args = parser.parse_args(argv)
    target = Path(args.target)
    source_dir = Path(args.source)

    try:
        if args.verb == "adopt":
            return run_adopt(target, source_dir, as_json=args.json)
        return run_upgrade(
            target,
            source_dir,
            apply=args.apply,
            keep_local=set(args.keep_local),
            force=args.force,
            as_json=args.json,
        )
    except VendorMapError as exc:
        if args.json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
