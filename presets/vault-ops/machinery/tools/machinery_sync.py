"""Vendor CLI for the vault machinery payload (W3/W5): adopt, upgrade, init.

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

``init --target <dir> [--vault-name <name>] [--note-dirs a,b,c]
[--contexts x,y]``
    Scaffold a brand-new vault, non-interactively parameterized (W5).
    Refuses a non-empty target (``.git`` alone does not count; pass
    ``--force-empty-check`` to skip the check), renders every scaffold
    template from ``<machinery>/scaffold/`` with the parameters, vendors the
    full managed tier through the same copy path upgrade uses, writes the
    lockfile, runs ``git init`` + an initial commit when the target is not
    already a git repo, and prints the post-init checklist
    (``.vault-context``, ``include.path``, optional plugin install, the
    Codex hook-trust approval note).

Scaffold tier
-------------
Scaffold outputs are written ONCE by init and never touched by upgrade —
they are the owner's files (``AGENTS.md``, ``.gitconfig``, the note
``templates/`` tree, and the taxonomy-parameterized
``.claude/scripts/vault_scope.py``). The two tiers can never overlap: a
scaffold target that collides with a managed vendor-map target aborts at
map-validation time, before any write. Scaffold outputs that live under a
managed scan root are recorded in the lockfile as ``tier: "scaffold"`` (no
hash — local edits are the owner's business) so the drift check's UNTRACKED
scan stays clean; upgrade re-records them on every lock rewrite.

Structural safety
-----------------
The only paths this tool may ever write inside the target are (a) exact
vendor-map target paths, (b) declared scaffold output paths (init only),
and (c) ``.vault/machinery.lock.json``. That is enforced in code by a write
gate built from the validated maps — a map entry whose target escapes the
target root (``../..``, absolute paths) or whose source escapes the
machinery dir aborts the run before any write.

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

Vendor-map schemas
------------------
Schema 1 (W3): ``kind: "file"`` entries with machinery-relative sources.
Schema 2 (W4) adds two constructs, and this reader accepts both schemas:

- ``source_root: "preset"`` on a file entry resolves the source against the
  machinery dir's PARENT (the preset root) — how the sibling ``skills/``
  trees are vendored. Containment is enforced against that root.
- ``kind: "json-key"`` vendors ONE key of a JSON file (the vault's
  ``.claude/settings.json`` ``hooks`` key) instead of the whole file.
  Comparison is semantic: the canonical JSON (sorted keys, no whitespace)
  of the live key against the rendered source value. Adopt records the
  canonical hash (plus ``kind``/``key``) in the lock entry; upgrade rewrites
  only that key, preserving every sibling key, and reformats the file with
  ``indent=2``. A target file that is not valid JSON refuses even under
  ``--force`` — a key rewrite cannot preserve siblings it cannot parse.

A stale schema-1 reader hard-errors on a schema-2 map ("schema 2 is not
supported") — deliberate: a stale vendored tool must refuse a newer map
loudly rather than half-apply it.

Scope: W3 shipped lockfile format plus adopt/check/dumb-upgrade; W4 added
the schema-2 constructs above; W5 adds ``init`` and the scaffold tier. The
scaffolding interview lives in the vault-init skill (it interviews, then
calls this verb), and an ``upstream`` comparison verb remains deliberately
deferred; this tool intentionally knows nothing about it.

Exit codes: 0 = success (or an executable dry-run plan); 1 = refusal
(adopt diff, upgrade over a local edit, init on a non-empty target);
2 = environment/config error (missing lockfile for upgrade, unreadable
vendor or scaffold map, hostile map path, tier collision).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import string
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

LOCKFILE_RELPATH = ".vault/machinery.lock.json"
SOURCE_REPO_NAME = "the-workshop"

# Mirror of machinery_check.MANAGED_SCAN_ROOTS (the two tools are vendored
# together; tests pin them equal). Scaffold outputs under one of these roots
# are lock-recorded as tier "scaffold" so the UNTRACKED scan stays clean.
MANAGED_SCAN_ROOTS = (
    ".claude/scripts",
    ".claude/agents",
    ".codex/agents",
    ".claude/skills",
    ".codex/skills",
)

DEFAULT_NOTE_DIRS = "brain,work,personal,org,perf,reference"
DEFAULT_CONTEXTS = "personal,work"

# note-dir / context tokens become directory names and Python tuple items;
# anything fancier than this is hostile input, not a taxonomy.
_TAXONOMY_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\Z")

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


def canonical_json_sha256(value) -> str:
    """Content hash of a JSON value, independent of formatting/key order."""
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return _sha256_bytes(canonical.encode("utf-8"))


# Sentinel distinguishing "key absent / file unreadable" from any JSON value
# (None is a legitimate JSON value).
_ABSENT = object()


def _read_json_key(path: Path, key: str):
    """The value of ``key`` in the JSON file at ``path``.

    Returns
    -------
    Any
        The key's value; ``_ABSENT`` when the file is missing, the document
        is not a JSON object, or the key is not present.

    Raises
    ------
    ValueError
        When the file exists but is not valid JSON — callers treat that as
        an unresolvable local state, never as absence.
    """
    if not path.is_file():
        return _ABSENT
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}")
    if not isinstance(document, dict) or key not in document:
        return _ABSENT
    return document[key]


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


class MapEntry:
    """One validated vendor-map entry."""

    __slots__ = ("kind", "source", "target", "source_root", "key")

    def __init__(
        self,
        kind: str,
        source: str,
        target: str,
        source_root: str,
        key: str | None,
    ):
        self.kind = kind
        self.source = source
        self.target = target
        self.source_root = source_root
        self.key = key


class VendorMap:
    """The validated managed set of map entries."""

    def __init__(self, source_dir: Path, entries: list[dict], schema: int):
        self.source_dir = source_dir
        self.schema = schema
        self.entries: list[MapEntry] = []
        # Schema 1 readers only understood machinery-relative file entries;
        # a schema-1 map smuggling schema-2 constructs is a hard error rather
        # than a silent skip, so a mislabeled map is never half-applied.
        allowed_kinds = ("file",) if schema == 1 else ("file", "json-key")
        allowed_roots = ("machinery",) if schema == 1 else ("machinery", "preset")
        seen_targets: set[str] = set()
        for entry in entries:
            kind = entry.get("kind")
            if kind not in allowed_kinds:
                raise VendorMapError(
                    f"unsupported vendor-map entry kind for schema "
                    f"{schema}: {kind!r}"
                )
            source_root = entry.get("source_root", "machinery")
            if source_root not in allowed_roots:
                raise VendorMapError(
                    f"unsupported vendor-map source_root for schema "
                    f"{schema}: {source_root!r}"
                )
            key = entry.get("key")
            if kind == "json-key" and not key:
                raise VendorMapError(
                    f"json-key vendor-map entry needs a 'key': {entry}"
                )
            source_rel = entry.get("source", "")
            target_rel = entry.get("target", "")
            _resolve_inside(
                self._root_dir(source_root), source_rel, label="source"
            )
            if target_rel in seen_targets:
                raise VendorMapError(
                    f"duplicate vendor-map target: {target_rel!r}"
                )
            seen_targets.add(target_rel)
            self.entries.append(
                MapEntry(kind, source_rel, target_rel, source_root, key)
            )

    def _root_dir(self, source_root: str) -> Path:
        # "preset" sources live beside the machinery dir (the sibling
        # skills/ tree) in both a source checkout and a built dist tree.
        return self.source_dir.parent if source_root == "preset" else self.source_dir

    def source_path(self, entry: MapEntry) -> Path:
        return self._root_dir(entry.source_root) / entry.source

    @classmethod
    def load(cls, source_dir: Path) -> "VendorMap":
        map_path = source_dir / "vendor-map.json"
        if not map_path.is_file():
            raise VendorMapError(f"no vendor map at {map_path}")
        try:
            data = json.loads(map_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise VendorMapError(f"vendor map at {map_path} is not valid JSON: {exc}")
        schema = data.get("schema")
        if schema not in (1, 2):
            raise VendorMapError(
                f"vendor map schema {schema!r} is not supported "
                "(this reader understands schemas 1 and 2)"
            )
        return cls(source_dir, data.get("entries", []), schema)


class ScaffoldMap:
    """The validated scaffold payload: templates init renders exactly once.

    Loaded from ``<machinery>/scaffold/scaffold-map.json`` (schema 1):
    ``entries`` are ``{"template": <path>.tmpl, "target": <vault path>}``
    pairs rendered with :class:`string.Template`; ``trees`` are
    ``{"source": <dir>, "target": <dir>}`` pairs copied verbatim (the note
    ``templates/`` defaults). Template paths are containment-checked against
    the scaffold dir the same way vendor-map sources are.
    """

    def __init__(self, scaffold_dir: Path, data: dict):
        schema = data.get("schema")
        if schema != 1:
            raise VendorMapError(
                f"scaffold map schema {schema!r} is not supported "
                "(this reader understands schema 1)"
            )
        self.scaffold_dir = scaffold_dir
        self.entries: list[dict] = []
        self.trees: list[dict] = []
        seen_targets: set[str] = set()
        for entry in data.get("entries", []):
            template = entry.get("template", "")
            target = entry.get("target", "")
            _resolve_inside(scaffold_dir, template, label="scaffold template")
            if not target or Path(target).is_absolute():
                raise VendorMapError(
                    f"scaffold target path {target!r} must be relative"
                )
            if target in seen_targets:
                raise VendorMapError(f"duplicate scaffold target: {target!r}")
            seen_targets.add(target)
            self.entries.append({"template": template, "target": target})
        for tree in data.get("trees", []):
            source = tree.get("source", "")
            target = tree.get("target", "")
            _resolve_inside(scaffold_dir, source, label="scaffold tree")
            if not target or Path(target).is_absolute():
                raise VendorMapError(
                    f"scaffold tree target path {target!r} must be relative"
                )
            self.trees.append({"source": source, "target": target})

    def tree_files(self) -> list[tuple[Path, str]]:
        """(source file, target relpath) pairs for every verbatim tree file."""
        pairs: list[tuple[Path, str]] = []
        for tree in self.trees:
            root = self.scaffold_dir / tree["source"]
            if not root.is_dir():
                continue
            for path in sorted(root.rglob("*")):
                if not path.is_file():
                    continue
                relative = path.relative_to(root).as_posix()
                pairs.append((path, f"{tree['target']}/{relative}"))
        return pairs

    def output_targets(self) -> list[str]:
        """Every vault-relative path the scaffold tier owns."""
        return [entry["target"] for entry in self.entries] + [
            target for _, target in self.tree_files()
        ]

    @classmethod
    def load(cls, source_dir: Path) -> "ScaffoldMap | None":
        """The machinery dir's scaffold map, or None when it ships none."""
        map_path = source_dir / "scaffold" / "scaffold-map.json"
        if not map_path.is_file():
            return None
        try:
            data = json.loads(map_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise VendorMapError(
                f"scaffold map at {map_path} is not valid JSON: {exc}"
            )
        return cls(source_dir / "scaffold", data)


def _ensure_tiers_disjoint(
    vendor_map: VendorMap, scaffold_map: ScaffoldMap | None
) -> None:
    """Abort when a scaffold output collides with a managed target.

    The scaffold tier is written once by init and never upgraded; the
    managed tier is owned by upgrade. A path claimed by both would flip
    between owners depending on which verb ran last, so the overlap is a
    hard map-validation error rather than a runtime surprise.
    """
    if scaffold_map is None:
        return
    managed_targets = {entry.target for entry in vendor_map.entries}
    colliding = sorted(
        set(scaffold_map.output_targets()) & managed_targets
    )
    if colliding:
        raise VendorMapError(
            "scaffold outputs collide with managed vendor-map targets: "
            + ", ".join(colliding)
        )


def _scaffold_lock_entries(
    scaffold_map: ScaffoldMap | None,
    target: Path,
    previous_files: dict[str, dict] | None,
) -> dict[str, dict]:
    """Lock records for scaffold outputs under the managed scan roots.

    Only scan-root scaffold outputs are recorded (as ``tier: "scaffold"``,
    hashless — the owner may edit them freely): the record exists to keep
    the drift check's UNTRACKED scan clean, and to keep MISSING loud for a
    load-bearing file like ``vault_scope.py``. A path is recorded when the
    file exists, or when the previous lock knew it under any tier — which is
    also how upgrade migrates a formerly managed scaffold-owned file.
    """
    if scaffold_map is None:
        return {}
    prefixes = tuple(f"{root}/" for root in MANAGED_SCAN_ROOTS)
    entries: dict[str, dict] = {}
    for relative in scaffold_map.output_targets():
        if not relative.startswith(prefixes):
            continue
        known_before = bool(previous_files) and relative in previous_files
        if (target / relative).is_file() or known_before:
            entries[relative] = {"tier": "scaffold"}
    return entries


class TargetWriter:
    """Write gate: the ONLY component allowed to mutate the target repo.

    Built from the validated vendor map, its allowlist is exactly the map's
    target paths, any declared scaffold output paths (init), plus the
    lockfile. Every write resolves through :func:`_resolve_inside`, so a
    hostile map path fails at construction time — before any write — rather
    than being caught by convention.
    """

    def __init__(
        self,
        target_root: Path,
        vendor_map: VendorMap,
        extra_targets: list[str] | None = None,
    ):
        self._root = target_root
        self._allowed: dict[str, Path] = {}
        for entry in vendor_map.entries:
            self._allowed[entry.target] = _resolve_inside(
                target_root, entry.target, label="target"
            )
        for relative in extra_targets or []:
            self._allowed[relative] = _resolve_inside(
                target_root, relative, label="scaffold target"
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


def _lock_entry_for_source(vendor_map: VendorMap, entry: MapEntry) -> dict:
    """The lock record a target synced to ``entry``'s source would carry."""
    if entry.kind == "json-key":
        source_value = json.loads(
            vendor_map.source_path(entry).read_text(encoding="utf-8")
        )
        return {
            "tier": "managed",
            "kind": "json-key",
            "key": entry.key,
            "sha256": canonical_json_sha256(source_value),
        }
    return {
        "tier": "managed",
        "sha256": _sha256_file(vendor_map.source_path(entry)),
    }


def _adopt_status(vendor_map: VendorMap, entry: MapEntry, target: Path) -> str:
    candidate = target / entry.target
    if entry.kind == "json-key":
        source_value = json.loads(
            vendor_map.source_path(entry).read_text(encoding="utf-8")
        )
        try:
            live_value = _read_json_key(candidate, entry.key)
        except ValueError:
            return ADOPT_DIFFERS
        if live_value is _ABSENT:
            return ADOPT_MISSING
        if canonical_json_sha256(live_value) == canonical_json_sha256(
            source_value
        ):
            return ADOPT_IDENTICAL
        return ADOPT_DIFFERS
    if not candidate.is_file():
        return ADOPT_MISSING
    if candidate.read_bytes() == vendor_map.source_path(entry).read_bytes():
        return ADOPT_IDENTICAL
    return ADOPT_DIFFERS


def run_adopt(target: Path, source_dir: Path, *, as_json: bool) -> int:
    vendor_map = VendorMap.load(source_dir)
    scaffold_map = ScaffoldMap.load(source_dir)
    _ensure_tiers_disjoint(vendor_map, scaffold_map)
    writer = TargetWriter(target, vendor_map)

    statuses: list[dict] = []
    lock_files: dict[str, dict] = {}
    for entry in vendor_map.entries:
        status = _adopt_status(vendor_map, entry, target)
        if status == ADOPT_IDENTICAL:
            lock_files[entry.target] = _lock_entry_for_source(vendor_map, entry)
        statuses.append({"target": entry.target, "status": status})

    ok = all(record["status"] == ADOPT_IDENTICAL for record in statuses)
    if ok:
        previous = _load_lock(target)
        lock_files.update(
            _scaffold_lock_entries(
                scaffold_map, target, previous["files"] if previous else None
            )
        )
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


def _plan_file_entry(
    vendor_map: VendorMap,
    entry: MapEntry,
    target: Path,
    locked: dict | None,
    wants_keep: bool,
    force: bool,
) -> tuple[str, str]:
    source_bytes = vendor_map.source_path(entry).read_bytes()
    candidate = target / entry.target
    if candidate.is_file() and candidate.read_bytes() == source_bytes:
        return ACTION_SKIP, "already matches source"
    if not candidate.is_file():
        return ACTION_COPY, "missing on disk; restoring"
    if wants_keep:
        # Checked before the lock-hash comparison: a kept file's lock
        # entry records its LOCAL sha, so "unmodified since lock" would
        # otherwise reclassify an intact kept edit as safely copyable.
        return ACTION_KEEP_LOCAL, "local edit kept"
    current_sha = _sha256_file(candidate)
    locked_sha = locked.get("sha256") if locked else None
    if current_sha == locked_sha:
        return ACTION_COPY, "unmodified since lock"
    if force:
        return ACTION_COPY, "local edit overwritten (--force)"
    if locked is None:
        return ACTION_REFUSE, "exists but is not in the lock"
    return ACTION_REFUSE, "hash differs from lock"


def _plan_json_key_entry(
    vendor_map: VendorMap,
    entry: MapEntry,
    target: Path,
    locked: dict | None,
    wants_keep: bool,
    force: bool,
) -> tuple[str, str]:
    source_value = json.loads(
        vendor_map.source_path(entry).read_text(encoding="utf-8")
    )
    try:
        live_value = _read_json_key(target / entry.target, entry.key)
    except ValueError:
        # Not downgraded by --force: rewriting one key cannot preserve
        # sibling keys the file no longer parses well enough to read.
        return ACTION_REFUSE, "target is not valid JSON"
    if live_value is not _ABSENT and canonical_json_sha256(
        live_value
    ) == canonical_json_sha256(source_value):
        return ACTION_SKIP, "already matches source"
    if live_value is _ABSENT:
        return ACTION_COPY, "key missing on disk; restoring"
    if wants_keep:
        return ACTION_KEEP_LOCAL, "local edit kept"
    current_sha = canonical_json_sha256(live_value)
    locked_sha = locked.get("sha256") if locked else None
    if current_sha == locked_sha:
        return ACTION_COPY, "unmodified since lock"
    if force:
        return ACTION_COPY, "local edit overwritten (--force)"
    if locked is None:
        return ACTION_REFUSE, "exists but is not in the lock"
    return ACTION_REFUSE, "hash differs from lock"


def _plan_upgrade(
    vendor_map: VendorMap,
    target: Path,
    lock: dict,
    keep_local: set[str],
    force: bool,
) -> list[dict]:
    """Per-file planned actions for a dumb re-vendor.

    Decision order per managed entry: identical to source -> skip; missing on
    disk -> copy (restore); unmodified since lock -> copy; locally edited ->
    keep-local (flagged now or recorded in the lock) or REFUSE, with
    ``--force`` downgrading every refusal to a copy — except a json-key
    target that is no longer valid JSON, which always refuses.
    """
    locked_files: dict[str, dict] = lock["files"]
    plan: list[dict] = []
    for entry in vendor_map.entries:
        locked = locked_files.get(entry.target)
        sticky_keep = bool(locked.get("keep_local")) if locked else False
        wants_keep = entry.target in keep_local or sticky_keep
        planner = (
            _plan_json_key_entry if entry.kind == "json-key" else _plan_file_entry
        )
        action, reason = planner(
            vendor_map, entry, target, locked, wants_keep, force
        )
        plan.append(
            {
                "target": entry.target,
                "source": entry.source,
                "action": action,
                "reason": reason,
            }
        )
    return plan


def _apply_json_key_copy(
    vendor_map: VendorMap, entry: MapEntry, target: Path, writer: TargetWriter
) -> None:
    """Rewrite only ``entry.key`` in the target JSON file.

    Sibling keys and their order are preserved; the file is reformatted with
    ``indent=2`` and a trailing newline. A missing or non-object target
    becomes ``{<key>: <value>}``.
    """
    source_value = json.loads(
        vendor_map.source_path(entry).read_text(encoding="utf-8")
    )
    candidate = target / entry.target
    document = {}
    if candidate.is_file():
        loaded = json.loads(candidate.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            document = loaded
    document[entry.key] = source_value
    payload = (json.dumps(document, indent=2) + "\n").encode("utf-8")
    writer.write_bytes(entry.target, payload)


def _keep_local_lock_entry(entry: MapEntry, target: Path) -> dict:
    """Lock record for a kept local edit: its LOCAL content hash, sticky."""
    if entry.kind == "json-key":
        live_value = _read_json_key(target / entry.target, entry.key)
        return {
            "tier": "managed",
            "kind": "json-key",
            "key": entry.key,
            "sha256": canonical_json_sha256(live_value),
            "keep_local": True,
        }
    return {
        "tier": "managed",
        "sha256": _sha256_file(target / entry.target),
        "keep_local": True,
    }


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
    scaffold_map = ScaffoldMap.load(source_dir)
    _ensure_tiers_disjoint(vendor_map, scaffold_map)
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
        entries_by_target = {entry.target: entry for entry in vendor_map.entries}
        lock_files: dict[str, dict] = {}
        for record in plan:
            entry = entries_by_target[record["target"]]
            if record["action"] == ACTION_KEEP_LOCAL:
                lock_files[entry.target] = _keep_local_lock_entry(entry, target)
                continue
            if record["action"] == ACTION_COPY:
                if entry.kind == "json-key":
                    _apply_json_key_copy(vendor_map, entry, target, writer)
                else:
                    writer.write_bytes(
                        entry.target, vendor_map.source_path(entry).read_bytes()
                    )
            lock_files[entry.target] = _lock_entry_for_source(vendor_map, entry)
        lock_files.update(
            _scaffold_lock_entries(scaffold_map, target, lock["files"])
        )
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
# init
# ---------------------------------------------------------------------------


def _parse_taxonomy(raw: str, *, label: str) -> list[str]:
    """Validated, de-blanked comma-separated taxonomy tokens.

    Raises
    ------
    VendorMapError
        When no token survives, or a token is not a plain directory-safe
        name (tokens become directory names and Python tuple items).
    """
    tokens = [token.strip() for token in raw.split(",") if token.strip()]
    if not tokens:
        raise VendorMapError(f"--{label} needs at least one name")
    for token in tokens:
        if not _TAXONOMY_TOKEN.match(token):
            raise VendorMapError(
                f"--{label} token {token!r} is not a plain directory name"
            )
    return tokens


def build_scaffold_params(
    vault_name: str, note_dirs: list[str], contexts: list[str]
) -> dict[str, str]:
    """The substitution dict every scaffold template is rendered with."""
    slug = re.sub(r"[^a-z0-9]+", "-", vault_name.lower()).strip("-") or "vault"
    return {
        "vault_name": vault_name,
        "vault_slug": slug,
        "note_dirs_csv": ", ".join(note_dirs),
        "note_dirs_bullets": "\n".join(
            f"- `{name}/` — describe what lives here" for name in note_dirs
        ),
        "governed_note_dirs": "".join(f'"{name}", ' for name in note_dirs).rstrip(" "),
        "contexts_csv": ", ".join(contexts),
        "context_values": " or ".join(f"`{name}`" for name in contexts),
        "primary_context": contexts[0],
    }


def _post_init_checklist(contexts: list[str]) -> list[str]:
    context_values = " or ".join(f"`{name}`" for name in contexts)
    return [
        f'Write .vault-context (gitignored, one per machine): echo "{contexts[0]}" '
        f"> .vault-context — valid values: {context_values}",
        "Wire git conventions: git config --local --add include.path "
        "'../.gitconfig'",
        "Verify the vendored machinery: python3 "
        ".claude/scripts/machinery_check.py --strict",
        "Optional: install the vault-ops plugin from the-workshop marketplace "
        "for cross-repo use of the vault skills",
        "Codex only, once per machine: approve hook trust interactively "
        "(hooks are silently skipped until trusted; automation may use "
        "codex exec --dangerously-bypass-hook-trust)",
        "Open an agent session in the new vault and confirm the hooks fire",
    ]


def _git_init_and_commit(target: Path, message: str) -> tuple[bool, str | None]:
    """``git init`` + stage everything + initial commit. Fail-soft.

    Returns
    -------
    tuple[bool, str | None]
        (committed, error). A missing git binary or unconfigured identity
        degrades to a warning — the vault is fully scaffolded either way.
    """
    for step in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", message]):
        try:
            result = subprocess.run(
                ["git", "-C", str(target), *step],
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return False, str(exc)
        if result.returncode != 0:
            return False, result.stderr.strip() or f"git {step[0]} failed"
    return True, None


def run_init(
    target: Path,
    source_dir: Path,
    *,
    vault_name: str | None,
    note_dirs_raw: str,
    contexts_raw: str,
    force_empty_check: bool,
    as_json: bool,
) -> int:
    vendor_map = VendorMap.load(source_dir)
    scaffold_map = ScaffoldMap.load(source_dir)
    if scaffold_map is None:
        raise VendorMapError(
            f"no scaffold payload at {source_dir / 'scaffold'}; "
            "init needs scaffold/scaffold-map.json"
        )
    _ensure_tiers_disjoint(vendor_map, scaffold_map)
    note_dirs = _parse_taxonomy(note_dirs_raw, label="note-dirs")
    contexts = _parse_taxonomy(contexts_raw, label="contexts")

    resolved_name = vault_name or target.resolve().name
    params = build_scaffold_params(resolved_name, note_dirs, contexts)

    if target.exists():
        # A bare `git init`'d dir still counts as empty: only real content
        # is worth refusing over.
        occupied = [p.name for p in target.iterdir() if p.name != ".git"]
        if occupied and not force_empty_check:
            message = (
                f"target {target} is not empty ({len(occupied)} entries, e.g. "
                f"{sorted(occupied)[0]!r}); init scaffolds NEW vaults only. "
                "Pass --force-empty-check to proceed anyway."
            )
            if as_json:
                print(json.dumps({"verb": "init", "ok": False, "error": message}, indent=2))
            else:
                print(f"REFUSED: {message}", file=sys.stderr)
            return 1
    else:
        target.mkdir(parents=True)

    scaffold_targets = scaffold_map.output_targets()
    writer = TargetWriter(target, vendor_map, extra_targets=scaffold_targets)

    # 1. Render every scaffold template.
    written_scaffold: list[str] = []
    for entry in scaffold_map.entries:
        template_text = (scaffold_map.scaffold_dir / entry["template"]).read_text(
            encoding="utf-8"
        )
        try:
            rendered = string.Template(template_text).substitute(params)
        except (KeyError, ValueError) as exc:
            raise VendorMapError(
                f"scaffold template {entry['template']} references an unknown "
                f"placeholder: {exc}"
            )
        writer.write_bytes(entry["target"], rendered.encode("utf-8"))
        written_scaffold.append(entry["target"])

    # 2. Copy the verbatim scaffold trees (note templates).
    for source_path, target_rel in scaffold_map.tree_files():
        writer.write_bytes(target_rel, source_path.read_bytes())
        written_scaffold.append(target_rel)

    # 3. Vendor the full managed tier — the same copy path upgrade applies.
    lock_files: dict[str, dict] = {}
    written_managed: list[str] = []
    for entry in vendor_map.entries:
        if entry.kind == "json-key":
            _apply_json_key_copy(vendor_map, entry, target, writer)
        else:
            writer.write_bytes(
                entry.target, vendor_map.source_path(entry).read_bytes()
            )
        lock_files[entry.target] = _lock_entry_for_source(vendor_map, entry)
        written_managed.append(entry.target)

    # 4. Lock: managed hashes plus hashless scaffold records for scan roots.
    lock_files.update(_scaffold_lock_entries(scaffold_map, target, None))
    _write_lock(writer, _build_lockfile(source_dir, lock_files))

    # 5. git init + initial commit, unless the target is already a repo.
    _, version = resolve_source_meta(source_dir)
    git_initialized = False
    git_error: str | None = None
    if not (target / ".git").exists():
        git_initialized, git_error = _git_init_and_commit(
            target,
            f"chore: initialize {resolved_name} vault "
            f"(the-workshop vault-ops {version or 'unknown'})",
        )

    checklist = _post_init_checklist(contexts)

    if as_json:
        print(
            json.dumps(
                {
                    "verb": "init",
                    "target": str(target),
                    "source": str(source_dir),
                    "vault_name": resolved_name,
                    "note_dirs": note_dirs,
                    "contexts": contexts,
                    "scaffold": written_scaffold,
                    "managed": written_managed,
                    "lockfile_written": True,
                    "git_initialized": git_initialized,
                    "git_error": git_error,
                    "checklist": checklist,
                    "ok": True,
                },
                indent=2,
            )
        )
    else:
        print(f"init: {source_dir} -> {target}")
        print(
            f"  scaffolded {len(written_scaffold)} file(s), vendored "
            f"{len(written_managed)} managed file(s), wrote {LOCKFILE_RELPATH}"
        )
        if git_initialized:
            print("  initialized git repo with an initial commit")
        elif git_error:
            print(
                f"  WARNING: git initialization skipped ({git_error}); "
                "run git init + commit manually"
            )
        else:
            print("  target is already a git repo; left git alone")
        print("Post-init checklist:")
        for number, step in enumerate(checklist, start=1):
            print(f"  {number}. {step}")
    return 0


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

    init = subparsers.add_parser(
        "init", help="scaffold a brand-new vault into an empty target"
    )
    _add_common_arguments(init)
    init.add_argument(
        "--vault-name",
        default=None,
        help="human name for the vault (default: the target directory name)",
    )
    init.add_argument(
        "--note-dirs",
        default=DEFAULT_NOTE_DIRS,
        metavar="A,B,C",
        help=f"governed note directories (default: {DEFAULT_NOTE_DIRS})",
    )
    init.add_argument(
        "--contexts",
        default=DEFAULT_CONTEXTS,
        metavar="X,Y",
        help=f"machine contexts for .vault-context (default: {DEFAULT_CONTEXTS})",
    )
    init.add_argument(
        "--force-empty-check",
        action="store_true",
        help="scaffold into a non-empty target instead of refusing",
    )

    args = parser.parse_args(argv)
    target = Path(args.target)
    source_dir = Path(args.source)

    try:
        if args.verb == "adopt":
            return run_adopt(target, source_dir, as_json=args.json)
        if args.verb == "init":
            return run_init(
                target,
                source_dir,
                vault_name=args.vault_name,
                note_dirs_raw=args.note_dirs,
                contexts_raw=args.contexts,
                force_empty_check=args.force_empty_check,
                as_json=args.json,
            )
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
