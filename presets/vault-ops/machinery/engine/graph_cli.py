# /// script
# requires-python = ">=3.11"
# dependencies = ["graphmark>=0.1.1,<0.2", "fastembed", "numpy"]
# ///
"""Vault graph CLI — the reintegration seam.

Invoke with ``uv run .claude/scripts/graph_cli.py ...`` so uv honors this
file's inline script dependencies. Running it through plain ``python`` or
``uv run python`` skips those dependencies and can fail to import graphmark.

Delegates the graph algorithm to the published **graphmark** package (extracted and hardened
from the former `.claude/scripts/brain_map.py`), while keeping the vault-specific pieces here:
the scope (`vault_scope.py`) and the embedding-backed `similar_fn`
(from semantic_index). graphmark owns the deterministic algorithm; the vault injects similarity.

Surface used by /connect and /garden: `--gaps [--near-bridges] [--top N] [...]` and `--dismiss A B`.
Structural queries (--stats/--orphans/...) are also supported for parity with the old CLI.

Config mirrors brain_map exactly, so output is byte-identical (verified by a live-vault diff).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from graphmark.config import VaultConfig
from graphmark.dismiss import active_dismissed_sigs, record_dismissal, weaklink_sig
from graphmark.graph import NormalizeResolver, VaultGraph
from graphmark.metrics import (
    bridges,
    clusters,
    gaps,
    hubs,
    neighborhood,
    orphans,
    siloed_notes,
    stats,
)
from graphmark.parse import WikilinkExtractor

# Vault scope — shared with validation, semantic search, and graph gardener.
from vault_scope import (  # noqa: E402
    GRAPH_EXCLUDED_DIRS,
    GRAPH_NOTE_DIRS,
    OPERATING_FILENAMES,
    TRANSIENT_PREFIXES,
)


def find_vault_root() -> Path | None:
    import os

    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env).resolve()
    cur = Path.cwd().resolve()
    for p in (cur, *cur.parents):
        if (p / ".vault-context").exists() or (p / "CLAUDE.md").exists():
            return p
    return None


def build(vault_root: Path) -> VaultGraph:
    cfg = VaultConfig(
        root=vault_root,
        scoped_folders=list(GRAPH_NOTE_DIRS),
        excluded_dirs=list(GRAPH_EXCLUDED_DIRS),
        rules_files=list(OPERATING_FILENAMES),
        transient_prefixes=TRANSIENT_PREFIXES,
    )
    return VaultGraph.build(cfg, WikilinkExtractor(), NormalizeResolver()), cfg


def vector_similar_fn(vault_root: Path):
    """Note-level mean-pooled cosine similarity from semantic_index (no re-embedding).

    Ported verbatim from brain_map's _vector_similar_fn — the vault-side embedding source that
    graphmark's gaps() consumes as an injected dependency. Returns an empty fn if the index is absent.
    """
    import numpy as np  # noqa: PLC0415
    import semantic_index as si  # noqa: PLC0415

    vectors, meta, _ = si._load_index()
    if vectors is None or not len(meta):
        return lambda rel, k: []

    acc: dict[str, list] = {}
    for i, m in enumerate(meta):
        acc.setdefault(m["note_path"], []).append(vectors[i])
    rels = list(acc.keys())
    mat = np.array([np.mean(acc[r], axis=0) for r in rels])
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    matn = mat / np.where(norms == 0, 1.0, norms)
    idx = {r: i for i, r in enumerate(rels)}

    def fn(rel: str, k: int) -> list[tuple[str, float]]:
        if rel not in idx:
            return []
        scores = matn @ matn[idx[rel]]
        out: list[tuple[str, float]] = []
        for j in np.argsort(-scores):
            r = rels[j]
            if r == rel:
                continue
            out.append((r, float(scores[j])))
            if len(out) >= k:
                break
        return out

    return fn


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
    p.add_argument("--neighborhood", metavar="NOTE")
    p.add_argument("--depth", type=int, default=1)
    p.add_argument("--gaps", action="store_true")
    p.add_argument("--note")
    p.add_argument("--near-bridges", action="store_true", dest="near_bridges")
    p.add_argument("--dismiss", nargs=2, metavar=("A", "B"))
    p.add_argument("--threshold", type=float, default=0.6)
    p.add_argument("--max", type=float, default=0.92, dest="max_score")
    p.add_argument("-k", type=int, default=8)
    p.add_argument("--top", type=int, default=10)
    p.add_argument("--hub-degree", type=int, default=40, dest="hub_degree")
    args = p.parse_args(argv)

    vault_root = Path(args.vault_root).resolve() if args.vault_root else find_vault_root()
    if vault_root is None:
        print("ERROR: vault root not found. Use --vault-root or run inside the vault.", file=sys.stderr)
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
