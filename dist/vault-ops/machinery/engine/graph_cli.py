# /// script
# requires-python = ">=3.11"
# dependencies = ["graphmark>=0.5,<0.6", "fastembed", "numpy"]
# ///
"""Vault graph CLI — the reintegration seam.

Invoke with ``uv run .claude/scripts/graph_cli.py ...`` so uv honors this
file's inline script dependencies. Running it through plain ``python`` or
``uv run python`` skips those dependencies and can fail to import graphmark.

Delegates the graph algorithm to the published **graphmark** package (extracted and hardened
from the former `.claude/scripts/brain_map.py`), while keeping the vault-specific pieces here:
the scope (`vault_scope.py`), the embedding-backed `similar_fn` (from semantic_index), and
alias resolution (``AliasResolver``). graphmark owns the deterministic algorithm; the vault
injects its own naming and similarity policy.

Surface used by /connect and /garden: `--gaps [--near-bridges] [--top N] [...]` and `--dismiss A B`.
Structural queries (--stats/--orphans/...) are also supported for parity with the old CLI.

Config mirrors brain_map exactly, so output is byte-identical (verified by a live-vault diff).

The gaps banding policy (threshold / max-score / k / hub-degree) is sourced from graphmark's
published ``GAPS_DEFAULT_*`` constants rather than restated here, so the validated band has a
single definition.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import graphmark
from graphmark import (
    GAPS_DEFAULT_HUB_DEGREE,
    GAPS_DEFAULT_K,
    GAPS_DEFAULT_MAX_SCORE,
    GAPS_DEFAULT_THRESHOLD,
    Document,
    NormalizeResolver,
    VaultConfig,
    VaultGraph,
    build_catalog,
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


_ALIAS_LIST_HEADER = re.compile(r"^aliases:\s*$")
_ALIAS_INLINE = re.compile(r"^aliases:\s*\[(.*)\]\s*$")
_ALIAS_ITEM = re.compile(r"^\s+-\s*(.+?)\s*$")


def frontmatter_aliases(path: Path) -> list[str]:
    """Aliases declared in a note's frontmatter, block or inline form.

    Deliberately a targeted scan rather than a YAML parse: this runs inside a
    session hook over every note in the vault, and a note someone is mid-edit
    must not take the graph down. Anything unparseable yields no aliases.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    if not text.startswith("---"):
        return []
    end = text.find("\n---", 3)
    block = text[3:end] if end != -1 else text[3:]

    found: list[str] = []
    in_list = False
    for line in block.splitlines():
        inline = _ALIAS_INLINE.match(line)
        if inline:
            found += [s.strip().strip("\"'") for s in inline.group(1).split(",")]
            in_list = False
            continue
        if _ALIAS_LIST_HEADER.match(line):
            in_list = True
            continue
        if in_list:
            item = _ALIAS_ITEM.match(line)
            if item:
                found.append(item.group(1).strip("\"'"))
            else:
                in_list = False
    return [a for a in found if a]


def _strip_display(display: str) -> str:
    """`Note|shown`, `Note#Anchor` and `Note.md` all name the same note."""
    display = display.split("|", 1)[0].split("#", 1)[0].strip()
    return display[:-3] if display.lower().endswith(".md") else display


def _catalog_key(name: str) -> str | None:
    """The catalog key graphmark would compute for a note named ``name``.

    Derived by handing graphmark its own ``build_catalog`` a synthetic document
    rather than restating its normalization here, so alias keys and note keys
    can never drift apart.
    """
    if not name or "/" in name:
        return None
    keys = list(build_catalog([Document(rel_path=f"{name}.md", text="", frontmatter={})]))
    return keys[0] if keys else None


class AliasResolver:
    """graphmark's resolver, plus the vault's frontmatter ``aliases:`` convention.

    graphmark resolves a wikilink by normalized basename with a path-suffix
    fallback; it never reads frontmatter. The vault, meanwhile, treats
    ``aliases:`` as a real name for a note — so a correct ``[[Mood Tracker]]``
    pointing at a note that declares exactly that alias was reported broken,
    and the convention was write-only. Naming policy belongs to the seam, so
    the fallback lives here rather than in the graph algorithm.

    Two rules keep this conservative:

    - the base resolver runs first, so an actual note named X always beats an
      alias X — otherwise renaming a note could silently hijack live links;
    - an alias claimed by two notes, or one that collides with any real note
      name, resolves to nothing. That is the same refusal graphmark applies to
      colliding basenames: ambiguity stays ambiguous.
    """

    def __init__(self, vault_root: Path) -> None:
        self._root = vault_root
        self._base = NormalizeResolver()
        self._indexed_catalog: int | None = None
        self._aliases: dict[str, str] = {}

    def _index(self, catalog: dict[str, list[str]]) -> None:
        # The catalog is invariant for one build() and already names exactly the
        # documents graphmark scanned, so it is also the note list — no second
        # walk to drift from the first.
        if self._indexed_catalog == id(catalog):
            return
        self._indexed_catalog = id(catalog)
        claims: dict[str, set[str]] = {}
        for rel_path in (p for paths in catalog.values() for p in paths):
            for alias in frontmatter_aliases(self._root / rel_path):
                key = _catalog_key(alias)
                if key is not None and key not in catalog:
                    claims.setdefault(key, set()).add(rel_path)
        self._aliases = {k: v.pop() for k, v in claims.items() if len(v) == 1}

    def resolve(self, display: str, catalog: dict[str, list[str]]) -> str | None:
        resolved = self._base.resolve(display, catalog)
        if resolved is not None:
            return resolved
        self._index(catalog)
        key = _catalog_key(_strip_display(display))
        return self._aliases.get(key) if key is not None else None


def build(vault_root: Path) -> tuple[VaultGraph, VaultConfig]:
    cfg = VaultConfig(
        root=vault_root,
        scoped_folders=list(GRAPH_NOTE_DIRS),
        excluded_dirs=list(GRAPH_EXCLUDED_DIRS),
        rules_files=list(OPERATING_FILENAMES),
        transient_prefixes=TRANSIENT_PREFIXES,
    )
    # graphmark.build() defaults the wikilink extractor; the resolver is the
    # vault's, so frontmatter aliases resolve like the names they are.
    return graphmark.build(cfg, resolver=AliasResolver(vault_root)), cfg


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
    p.add_argument("--max", type=float, default=GAPS_DEFAULT_MAX_SCORE, dest="max_score")
    p.add_argument("-k", type=int, default=GAPS_DEFAULT_K)
    p.add_argument("--top", type=int, default=10)
    p.add_argument("--hub-degree", type=int, default=GAPS_DEFAULT_HUB_DEGREE, dest="hub_degree")
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
    elif args.unresolved:
        _emit(dict(sorted(graph.unresolved.items())))
    elif args.diagnose_broken:
        _emit(
            {
                note: [_broken_entry(graph, display, args.suggest) for display in displays]
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
