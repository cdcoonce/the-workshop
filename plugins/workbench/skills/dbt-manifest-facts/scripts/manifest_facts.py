#!/usr/bin/env python3
"""Answer structural questions about a dbt project from its parsed manifest.

The manifest is the only artifact that knows what a dbt project actually
declares. Model comments describe intent, READMEs describe a past state, and
memory describes neither — so every count, key, and edge reported here is read
out of `target/manifest.json` rather than inferred.

Stdlib only, on purpose: this runs against any dbt project without installing
anything into it, and without a warehouse connection.

Subcommands
-----------
summary   resource counts, materializations, and tests broken out by type
orphans   seeds, models, and sources that no model consumes
keys      the uniqueness tests a model actually declares
lineage   the real parents and children of one node

Exit codes: 0 clean, 1 findings (orphans), 2 usage or unreadable manifest.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

# Resource types that represent a consumer. A seed whose only children are
# tests is not consumed by anything — that is the orphan case worth reporting,
# and testing a seed nothing reads is exactly how it stays invisible.
CONSUMER_TYPES = frozenset({"model", "snapshot", "analysis", "operation"})

# Source files whose mtime should be compared against the manifest. A manifest
# older than any of these describes a project that has since moved on.
SOURCE_GLOBS = ("**/*.sql", "**/*.yml", "**/*.yaml", "**/*.csv")

# Directories that hold build output or vendored packages rather than source.
IGNORED_DIRS = frozenset({"target", "dbt_packages", "dbt_modules", ".git", "logs"})


class ManifestError(Exception):
    """Raised when the manifest cannot be located, read, or understood."""


# ---------------------------------------------------------------------------
# Loading and staleness
# ---------------------------------------------------------------------------


def load_manifest(path: Path) -> dict:
    """Read and minimally validate a manifest, failing loudly on a bad one."""
    if not path.is_file():
        raise ManifestError(
            f"no manifest at {path}\n"
            "Build one with:  dbt parse --project-dir <dir> --profiles-dir <dir>\n"
            "`dbt parse` needs no warehouse connection when the profile's "
            "env_var() calls carry defaults."
        )
    try:
        manifest = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ManifestError(f"{path} is not valid JSON: {exc}") from exc
    if "nodes" not in manifest:
        raise ManifestError(
            f"{path} has no 'nodes' key — this does not look like a dbt manifest"
        )
    return manifest


def stale_sources(manifest_path: Path, project_dir: Path) -> list[Path]:
    """Return project files modified after the manifest was written.

    A stale manifest is worse than a missing one: it answers every question
    confidently, about a project that no longer exists. Callers surface this
    rather than silently reporting yesterday's structure.
    """
    if not manifest_path.is_file():
        return []
    cutoff = manifest_path.stat().st_mtime
    newer: list[Path] = []
    for pattern in SOURCE_GLOBS:
        for candidate in project_dir.glob(pattern):
            if IGNORED_DIRS & set(candidate.parts):
                continue
            if candidate.is_file() and candidate.stat().st_mtime > cutoff:
                newer.append(candidate)
    return sorted(set(newer))


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


def _nodes(manifest: dict) -> dict:
    return manifest.get("nodes", {})


def _name_of(manifest: dict, uid: str) -> str:
    for bucket in ("nodes", "sources", "exposures", "metrics"):
        entry = manifest.get(bucket, {}).get(uid)
        if entry:
            return entry.get("name", uid)
    return uid


def summary(manifest: dict) -> dict:
    """Counts that documentation most often gets wrong."""
    nodes = _nodes(manifest)
    by_type = Counter(n["resource_type"] for n in nodes.values())
    by_type["source"] = len(manifest.get("sources", {}))

    materializations = Counter(
        n.get("config", {}).get("materialized", "unknown")
        for n in nodes.values()
        if n["resource_type"] == "model"
    )

    tests: Counter = Counter()
    for node in nodes.values():
        if node["resource_type"] != "test":
            continue
        tests[node.get("test_metadata", {}).get("name", "singular")] += 1

    return {
        "resources": dict(sorted(by_type.items())),
        "materializations": dict(sorted(materializations.items())),
        "tests": dict(sorted(tests.items(), key=lambda kv: (-kv[1], kv[0]))),
        "total_tests": sum(tests.values()),
    }


def orphans(manifest: dict) -> list[dict]:
    """Seeds, models, and sources that no model consumes.

    dbt does not treat an unreferenced seed as an error, so one can be fully
    typed, documented, and tested while feeding nothing at all.
    """
    child_map = manifest.get("child_map", {})
    found: list[dict] = []

    candidates = [
        (uid, node)
        for uid, node in _nodes(manifest).items()
        if node["resource_type"] in {"seed", "model"}
    ]
    candidates += [(uid, node) for uid, node in manifest.get("sources", {}).items()]

    for uid, node in candidates:
        consumers = [
            child
            for child in child_map.get(uid, [])
            if _nodes(manifest).get(child, {}).get("resource_type") in CONSUMER_TYPES
        ]
        if consumers:
            continue
        test_count = sum(
            1
            for child in child_map.get(uid, [])
            if _nodes(manifest).get(child, {}).get("resource_type") == "test"
        )
        found.append(
            {
                "name": node.get("name", uid),
                "resource_type": node.get("resource_type", "source"),
                "path": node.get("original_file_path", ""),
                "tests": test_count,
            }
        )
    return sorted(found, key=lambda f: (f["resource_type"], f["name"]))


def keys(manifest: dict, model: str | None = None) -> list[dict]:
    """The uniqueness a model actually declares, per model.

    A `unique` on a surrogate key says nothing about the grain a consumer
    joins on, so both the single-column and combination forms are reported.
    """
    nodes = _nodes(manifest)
    declared: dict[str, dict] = {}

    for node in nodes.values():
        if node["resource_type"] not in {"model", "seed", "snapshot"}:
            continue
        if model and node["name"] != model:
            continue
        declared[node["unique_id"]] = {
            "name": node["name"],
            "resource_type": node["resource_type"],
            "unique": [],
            "unique_combination": [],
            "not_null": 0,
        }

    for node in nodes.values():
        if node["resource_type"] != "test":
            continue
        meta = node.get("test_metadata", {})
        kind = meta.get("name")
        for parent in node.get("depends_on", {}).get("nodes", []):
            entry = declared.get(parent)
            if entry is None:
                continue
            if kind == "unique":
                entry["unique"].append(meta.get("kwargs", {}).get("column_name", "?"))
            elif kind == "unique_combination_of_columns":
                combo = meta.get("kwargs", {}).get("combination_of_columns", [])
                entry["unique_combination"].append(list(combo))
            elif kind == "not_null":
                entry["not_null"] += 1

    results = list(declared.values())
    if model and not results:
        raise ManifestError(f"no model, seed, or snapshot named {model!r} in the manifest")
    return sorted(results, key=lambda r: r["name"])


def lineage(manifest: dict, node_name: str) -> dict:
    """The real parents and children of one node."""
    matches = [
        uid
        for uid, node in {**_nodes(manifest), **manifest.get("sources", {})}.items()
        if node.get("name") == node_name
    ]
    if not matches:
        raise ManifestError(f"no node named {node_name!r} in the manifest")
    uid = matches[0]
    entry = {**_nodes(manifest), **manifest.get("sources", {})}[uid]

    parents = [_name_of(manifest, p) for p in entry.get("depends_on", {}).get("nodes", [])]
    children = manifest.get("child_map", {}).get(uid, [])
    models = [
        _name_of(manifest, c)
        for c in children
        if _nodes(manifest).get(c, {}).get("resource_type") in CONSUMER_TYPES
    ]
    tests = sum(1 for c in children if _nodes(manifest).get(c, {}).get("resource_type") == "test")

    return {
        "name": node_name,
        "resource_type": entry.get("resource_type", "source"),
        "materialized": entry.get("config", {}).get("materialized"),
        "parents": sorted(parents),
        "children": sorted(models),
        "tests": tests,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _render(result, command: str) -> str:
    if command == "summary":
        lines = ["resources:"]
        lines += [f"  {k:16s} {v}" for k, v in result["resources"].items()]
        lines.append("materializations:")
        lines += [f"  {k:16s} {v}" for k, v in result["materializations"].items()]
        lines.append(f"tests ({result['total_tests']} total):")
        lines += [f"  {k:32s} {v}" for k, v in result["tests"].items()]
        return "\n".join(lines)

    if command == "orphans":
        if not result:
            return "no orphans: every seed, model, and source feeds at least one model"
        lines = [f"{len(result)} unreferenced resource(s) — no model consumes these:"]
        for row in result:
            note = f"  ({row['tests']} tests declared)" if row["tests"] else ""
            lines.append(f"  {row['resource_type']:6s} {row['name']}{note}")
            if row["path"]:
                lines.append(f"         {row['path']}")
        return "\n".join(lines)

    if command == "keys":
        lines = []
        for row in result:
            parts = []
            if row["unique"]:
                parts.append("unique=" + ",".join(sorted(row["unique"])))
            if row["unique_combination"]:
                combos = "; ".join("(" + ", ".join(c) + ")" for c in row["unique_combination"])
                parts.append(f"combination={combos}")
            if not parts:
                parts.append("NO UNIQUENESS DECLARED")
            lines.append(f"{row['name']:44s} {' | '.join(parts)}  [not_null x{row['not_null']}]")
        return "\n".join(lines) or "no models found"

    parents = ", ".join(result["parents"]) or "(none)"
    children = ", ".join(result["children"]) or "(none — nothing consumes this)"
    return (
        f"{result['name']}  [{result['resource_type']}"
        f"{'/' + result['materialized'] if result['materialized'] else ''}]\n"
        f"  parents : {parents}\n"
        f"  children: {children}\n"
        f"  tests   : {result['tests']}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="manifest_facts",
        description="Read structural facts out of a dbt manifest.",
    )
    parser.add_argument("command", choices=["summary", "orphans", "keys", "lineage"])
    parser.add_argument("target", nargs="?", help="model name (keys) or node name (lineage)")
    parser.add_argument("--project-dir", default=".", help="dbt project root (default: .)")
    parser.add_argument("--manifest", help="explicit manifest path (default: <project>/target/manifest.json)")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    parser.add_argument(
        "--allow-stale",
        action="store_true",
        help="report anyway when the manifest predates project sources",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    project_dir = Path(args.project_dir).resolve()
    manifest_path = (
        Path(args.manifest).resolve() if args.manifest else project_dir / "target" / "manifest.json"
    )

    try:
        manifest = load_manifest(manifest_path)
    except ManifestError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    newer = stale_sources(manifest_path, project_dir)
    if newer:
        head = ", ".join(str(p.relative_to(project_dir)) for p in newer[:3])
        more = f" (+{len(newer) - 3} more)" if len(newer) > 3 else ""
        message = (
            f"manifest is STALE — {len(newer)} project file(s) changed since it was built: "
            f"{head}{more}\nRe-run `dbt parse` before trusting these numbers."
        )
        if not args.allow_stale:
            print(f"error: {message}", file=sys.stderr)
            return 2
        print(f"warning: {message}", file=sys.stderr)

    try:
        if args.command == "summary":
            result = summary(manifest)
        elif args.command == "orphans":
            result = orphans(manifest)
        elif args.command == "keys":
            result = keys(manifest, args.target)
        else:
            if not args.target:
                print("error: lineage requires a node name", file=sys.stderr)
                return 2
            result = lineage(manifest, args.target)
    except ManifestError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(result, indent=2) if args.json else _render(result, args.command))
    return 1 if args.command == "orphans" and result else 0


if __name__ == "__main__":
    raise SystemExit(main())
