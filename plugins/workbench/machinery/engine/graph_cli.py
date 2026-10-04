# /// script
# requires-python = ">=3.11"
# dependencies = ["graphmark>=0.10,<0.11", "ragmark @ https://github.com/cdcoonce/ragmark/releases/download/v0.2.0/ragmark-0.2.0-py3-none-any.whl"]
# ///
"""Vault graph CLI — the reintegration seam.

Invoke with ``uv run <engine>/graph_cli.py ...`` so uv honors this file's
inline script dependencies. Running it through plain ``python`` or ``uv run
python`` skips those dependencies and can fail to import graphmark. Skills
resolve ``<engine>`` from their announced base directory; see
``shared/vault-operating-principles.md``.

Delegates the graph algorithm to the published **graphmark** package (extracted and hardened
from the former `.claude/scripts/brain_map.py`), while keeping the vault-specific pieces here:
the scope (`vault_scope.py`) and the embedding-backed `similar_fn` (from ragmark).
graphmark owns the deterministic algorithm — including frontmatter ``aliases:`` resolution as
of 0.6 — and the vault injects its own scope and similarity policy.

Surface used by /connect and /garden: `--gaps [--near-bridges] [--top N] [...]` and `--dismiss A B`.
Structural queries (--stats/--orphans/...) are also supported for parity with the old CLI.

Structural configuration follows the owner scope. Similarity reads the selected
vault's Ragmark index through the public, context-gated note similarity API.

The gaps banding policy (threshold / max-score / k / hub-degree) is sourced from graphmark's
published ``GAPS_DEFAULT_*`` constants rather than restated here, so the validated band has a
single definition.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
import json
import sys
from pathlib import Path

import graphmark
from graphmark import (
    GAPS_DEFAULT_HUB_DEGREE,
    GAPS_DEFAULT_K,
    GAPS_DEFAULT_MAX_SCORE,
    GAPS_DEFAULT_THRESHOLD,
    VaultConfig,
    VaultGraph,
    active_dismissed_sigs,
    bridges,
    clusters,
    diagnose,
    gaps,
    hubs,
    neighborhood,
    orphans,
    record_dismissal,
    siloed_notes,
    stats,
    weaklink_sig,
)

# Vault scope — shared with validation, semantic search, and graph gardener.
from vault_scope_resolved import (  # noqa: E402
    GRAPH_EXCLUDED_DIRS,
    GRAPH_NOTE_DIRS,
    OPERATING_FILENAMES,
    TRANSIENT_PREFIXES,
)
import vault_utils  # noqa: E402


def build(vault_root: Path) -> tuple[VaultGraph, VaultConfig]:
    cfg = VaultConfig(
        root=vault_root,
        scoped_folders=list(GRAPH_NOTE_DIRS),
        excluded_dirs=list(GRAPH_EXCLUDED_DIRS),
        rules_files=list(OPERATING_FILENAMES),
        transient_prefixes=TRANSIENT_PREFIXES,
    )
    # No extractor or resolver injected: graphmark.build() defaults both, and its
    # resolver reads frontmatter ``aliases:`` natively as of 0.6.
    return graphmark.build(cfg), cfg


def vector_similar_fn(
    vault_root: Path,
) -> Callable[[str, int], list[tuple[str, float]]]:
    """Return a read-only, verified Ragmark cosine reader for this vault.

    Missing indexes yield a loud empty reader. Corrupt or unavailable indexes
    fail before ranking. Coherent stale indexes are allowed: this view never
    refreshes, embeds, or loads a model. Core retains all ranking and gating.
    """
    import sqlite3

    from ragmark import compat, gate, search
    from ragmark.embed import FastembedEmbedder
    from ragmark.store import IndexCorruptionError, IndexStore
    from ragmark_adapter import config_for_vault

    class ReadOnlyStore(IndexStore):
        def __init__(self, index_dir: Path) -> None:
            super().__init__(index_dir)
            self.connections: list[sqlite3.Connection] = []

        def connect(self) -> sqlite3.Connection:
            uri = self.db_path.resolve().as_uri() + "?mode=ro&immutable=1"
            conn = sqlite3.connect(uri, uri=True)
            conn.execute("PRAGMA query_only = ON")
            self.connections.append(conn)
            return conn

        def close(self) -> None:
            for conn in self.connections:
                conn.close()
            self.connections.clear()

    config = config_for_vault(vault_root)
    store = ReadOnlyStore(config.index_dir)

    def snapshot() -> tuple:
        paths = {store.db_path, store.vectors_path}
        for database in {store.db_path, store.db_path.resolve()}:
            paths.update(
                Path(str(database) + suffix) for suffix in ("-wal", "-shm", "-journal")
            )
        stamps = []
        for path in sorted(paths):
            try:
                stat = path.stat()
            except FileNotFoundError:
                stamps.append(None)
                continue
            stamps.append(
                (
                    str(path.resolve()),
                    stat.st_dev,
                    stat.st_ino,
                    stat.st_mode,
                    stat.st_size,
                    stat.st_mtime_ns,
                    stat.st_ctime_ns,
                )
            )
        return tuple(stamps)

    before = snapshot()
    # identity() reads package model metadata; it does not load/embed the model.
    report = compat.status(config, store, FastembedEmbedder().identity())
    if snapshot() != before:
        raise IndexCorruptionError(
            "Ragmark index changed during preflight; retry with writers idle"
        )
    if report["state"] == "missing":
        print(
            f"Ragmark semantic index not found under {config.index_dir} — "
            "gaps will be empty; run semantic_index.py reindex",
            file=sys.stderr,
        )
        return lambda rel, k: []
    if report["state"] not in {"ready", "stale"}:
        raise IndexCorruptionError(
            f"Ragmark similarity index is {report['state']}: "
            f"{report.get('error', 'index is not built')}; "
            f"{report.get('remediation', 'ragmark index --force')}"
        )

    def fn(rel: str, k: int) -> list[tuple[str, float]]:
        if snapshot() != before:
            raise IndexCorruptionError(
                "Ragmark index changed after preflight; retry with writers idle"
            )
        try:
            result = search.similar_notes(rel, k, config=config, store=store)
        except gate.VaultAccessError:
            return []
        finally:
            store.close()
        if snapshot() != before:
            raise IndexCorruptionError(
                "Ragmark index changed during similarity read; retry with writers idle"
            )
        return result

    return fn


def _broken_entry(graph, display: str, suggest: int) -> dict:
    """One broken link, described well enough for a consumer to act without re-resolving.

    graphmark separates the two failures the old ``--unresolved`` list conflated: an *ambiguous*
    link names several notes and needs disambiguating against them, a *missing* one names none and
    needs its target created — opposite repairs. ``candidates`` carries the notes in play for the
    first and the near-miss suggestions for the second.
    """
    d = diagnose(graph, display, suggest=suggest)
    return {"display": display, "reason": d.reason, "candidates": list(d.candidates)}


def _emit(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Vault graph queries (graphmark-backed).")
    p.add_argument("--vault-root")
    p.add_argument("--stats", action="store_true")
    p.add_argument("--orphans", action="store_true")
    p.add_argument("--hubs", type=int, nargs="?", const=10, metavar="N")
    p.add_argument("--clusters", action="store_true")
    p.add_argument("--bridges", action="store_true")
    p.add_argument(
        "--unresolved",
        action="store_true",
        help="Broken wikilinks: {note: [displays]}. Same-note [[#anchor]] links are not broken.",
    )
    p.add_argument(
        "--diagnose-broken",
        action="store_true",
        dest="diagnose_broken",
        help=(
            "Broken wikilinks WITH the reason each one failed and the notes in play: "
            "{note: [{display, reason, candidates}]}. reason is 'ambiguous' (candidates are the "
            "colliding notes) or 'missing' (candidates are near-miss suggestions)."
        ),
    )
    p.add_argument(
        "--suggest",
        type=int,
        default=5,
        help="Max near-miss suggestions per missing link (--diagnose-broken only); 0 disables.",
    )
    p.add_argument("--neighborhood", metavar="NOTE")
    p.add_argument("--depth", type=int, default=1)
    p.add_argument("--gaps", action="store_true")
    p.add_argument("--note")
    p.add_argument("--near-bridges", action="store_true", dest="near_bridges")
    p.add_argument("--dismiss", nargs=2, metavar=("A", "B"))
    # The gaps band comes from graphmark's published constants, so the validated policy has
    # one definition instead of literals copied into this argparse block.
    p.add_argument("--threshold", type=float, default=GAPS_DEFAULT_THRESHOLD)
    p.add_argument(
        "--max", type=float, default=GAPS_DEFAULT_MAX_SCORE, dest="max_score"
    )
    p.add_argument("-k", type=int, default=GAPS_DEFAULT_K)
    p.add_argument("--top", type=int, default=10)
    p.add_argument(
        "--hub-degree", type=int, default=GAPS_DEFAULT_HUB_DEGREE, dest="hub_degree"
    )
    args = p.parse_args(argv)

    vault_root = (
        Path(args.vault_root).resolve()
        if args.vault_root
        else vault_utils.find_vault_root_from_env()
    )
    if vault_root is None:
        print(
            "ERROR: vault root not found. Use --vault-root or run inside the vault.",
            file=sys.stderr,
        )
        return 1

    if args.dismiss:
        record_dismissal(vault_root, args.dismiss[0], args.dismiss[1])
        _emit({"dismissed": weaklink_sig(args.dismiss[0], args.dismiss[1])})
        return 0

    graph, cfg = build(vault_root)

    if args.orphans:
        _emit(orphans(graph, cfg))
    elif args.hubs is not None:
        _emit(hubs(graph, args.hubs))
    elif args.clusters:
        _emit(clusters(graph))
    elif args.bridges:
        _emit(bridges(graph))
    elif args.unresolved:
        _emit(dict(sorted(graph.unresolved.items())))
    elif args.diagnose_broken:
        _emit(
            {
                note: [
                    _broken_entry(graph, display, args.suggest) for display in displays
                ]
                for note, displays in sorted(graph.unresolved.items())
            }
        )
    elif args.neighborhood:
        _emit(neighborhood(graph, args.neighborhood, args.depth))
    elif args.gaps:
        targets = siloed_notes(graph) if args.near_bridges else None
        result = gaps(
            graph,
            vector_similar_fn(vault_root),
            threshold=args.threshold,
            k=args.k,
            note=args.note,
            dismissed=active_dismissed_sigs(vault_root),
            exclude_prefixes=TRANSIENT_PREFIXES,
            max_score=args.max_score,
            hub_degree=args.hub_degree,
            targets=targets,
        )
        _emit(result[: args.top])
    else:
        _emit(stats(graph))
    return 0


if __name__ == "__main__":
    sys.exit(main())
