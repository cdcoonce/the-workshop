"""Legacy semantic-index API and CLI delegated to ragmark (#94).

The machine-local index is now <explicit-vault-root>/.ragmark. This adapter
requires the coordinated scope/compatibility API; current older packages fail
loudly. No legacy index is read, converted, deleted, or silently reused.
"""

# /// script
# requires-python = ">=3.11"
# dependencies = ["ragmark @ https://github.com/cdcoonce/ragmark/releases/download/v0.2.0/ragmark-0.2.0-py3-none-any.whl"]
# ///

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import numpy as np

from ragmark_adapter import CAPABILITY_REMEDIATION, config_for_vault
from vault_utils import find_vault_root_from_env

SNIPPET_LEN = 200


def iter_vault_notes(vault_root: Path) -> list[Path]:
    """Return ragmark's corpus notes for the explicit owner policy.

    Parameters
    ----------
    vault_root : Path
        Vault root whose policy and note inventory are requested.

    Returns
    -------
    list[Path]
        Sorted corpus paths; machine-context gating belongs to retrieval.
    """
    config = config_for_vault(vault_root)
    from ragmark import index

    walk = getattr(index, "_walk_notes", None)
    if not callable(walk):
        raise RuntimeError(CAPABILITY_REMEDIATION)
    return sorted(walk(config))


def chunk_note(path: Path, raw: str, vault_root: Path) -> list[dict[str, Any]]:
    """Adapt ragmark's tokenizer-aware chunks to the legacy helper shape.

    Parameters
    ----------
    path : Path
        Note path under vault_root.
    raw : str
        Markdown including optional YAML frontmatter.
    vault_root : Path
        Root used to form the vault-relative note path.

    Returns
    -------
    list[dict]
        text/snippet/note_path records. Empty input follows core chunking.
    """
    from ragmark import chunk, parse
    from ragmark.embed import FastembedEmbedder
    from ragmark.model import NoteMeta

    rel = path.relative_to(vault_root).as_posix()
    try:
        meta, body = parse.parse_note(raw)
    except parse.FrontmatterError:
        meta, body = NoteMeta(None, (), ()), raw
    chunks = chunk.chunk_note(rel, body, meta, FastembedEmbedder().count_tokens)
    return [
        {
            "text": item.text,
            "snippet": item.text.strip()[:SNIPPET_LEN].replace("\n", " "),
            "note_path": item.note_path,
        }
        for item in chunks
    ]


def file_hash(path: Path) -> str:
    """Return the SHA-256 digest of raw bytes.

    Parameters
    ----------
    path : Path
        File to hash without normalization.

    Returns
    -------
    str
        Hexadecimal SHA-256 digest.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def embed_texts(texts: list[str]) -> np.ndarray:
    """Embed through ragmark's configured local model.

    Parameters
    ----------
    texts : list[str]
        Already-chunked text to embed.

    Returns
    -------
    numpy.ndarray
        Core embedder's float32 matrix.
    """
    from ragmark.embed import FastembedEmbedder

    return FastembedEmbedder().embed(texts)


def build_index(vault_root: Path, force: bool = False) -> dict:
    """Refresh or rebuild ragmark's derived index and report actual work.

    Parameters
    ----------
    vault_root : Path
        Explicit vault root.
    force : bool
        Use ragmark's full rebuild rather than incremental refresh.

    Returns
    -------
    dict
        Legacy indexed/skipped/total_chunks/elapsed plus removed and defects.
    """
    from contextlib import closing

    from ragmark import index
    from ragmark.embed import FastembedEmbedder
    from ragmark.store import IndexStore

    started = time.monotonic()
    config = config_for_vault(vault_root)
    store = IndexStore(config.index_dir)
    refresh = index.reindex if force else index.refresh
    report = refresh(config, store, FastembedEmbedder())
    with closing(store.connect()) as conn:
        total_chunks = store.chunk_count(conn)
    return {
        "indexed": report.added + report.updated,
        "skipped": report.unchanged,
        "removed": report.removed,
        "defects": list(report.defects),
        "total_chunks": total_chunks,
        "elapsed": round(time.monotonic() - started, 2),
    }


# ---------------------------------------------------------------------------
# Core — search
# ---------------------------------------------------------------------------


def search(query: str, k: int = 8, *, vault_root: Path) -> list[dict]:
    """Return ranked note dictionaries through ragmark's scoped query path.

    Parameters
    ----------
    query : str
        Natural-language or lexical query.
    k : int
        Maximum distinct notes (default 8, capped at 25).
    vault_root : Path
        Explicit keyword-only root; no plugin-cache or ambient-root fallback.

    Returns
    -------
    list[dict]
        Legacy note_path/score/snippet dictionaries with unmodified fused scores.
    """
    from ragmark import search as core_search
    from ragmark.compat import note_results
    from ragmark.embed import FastembedEmbedder
    from ragmark.store import IndexStore

    config = config_for_vault(vault_root)
    if k <= 0:
        return []
    hits = core_search.search(
        query,
        core_search.MAX_RESULTS,
        config=config,
        store=IndexStore(config.index_dir),
        embedder=FastembedEmbedder(),
    )
    return note_results(hits, k)


# ---------------------------------------------------------------------------
# Core — status
# ---------------------------------------------------------------------------


def status(vault_root: Path) -> dict:
    """Report ragmark health without initializing or refreshing the index.

    Parameters
    ----------
    vault_root : Path
        Explicit root whose `.ragmark` index is inspected.

    Returns
    -------
    dict
        Read-only health report; unknown values stay None, including build time.
    """
    from ragmark.compat import status as inspect_status
    from ragmark.embed import FastembedEmbedder
    from ragmark.store import IndexStore

    config = config_for_vault(vault_root)
    return inspect_status(
        config, IndexStore(config.index_dir), FastembedEmbedder().identity()
    )


def _emit(obj: Any) -> None:
    print(json.dumps(obj))


def _error(message: str, remediation: str = "") -> None:
    _emit({"error": message, "remediation": remediation})
    sys.exit(1)


def cmd_reindex(args: argparse.Namespace, vault_root: Path) -> None:
    """Handle the legacy reindex command.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed arguments including force.
    vault_root : Path
        Explicit target vault.
    """
    try:
        _emit(build_index(vault_root, force=args.force))
    except ImportError as exc:
        _error(str(exc), CAPABILITY_REMEDIATION)
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        _error(
            str(exc),
            "Check stderr and package capabilities; --force rebuilds only this vault's .ragmark index.",
        )


def cmd_search(args: argparse.Namespace, vault_root: Path) -> None:
    """Handle search once; core owns refresh and over-fetch.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed query and result limit.
    vault_root : Path
        Explicit target vault.
    """
    try:
        _emit(search(args.query, k=args.k, vault_root=vault_root))
    except ImportError as exc:
        _error(str(exc), CAPABILITY_REMEDIATION)
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        _error(
            str(exc),
            "Check package capabilities; corrupt or mismatched indexes require reindex --force.",
        )


def cmd_status(args: argparse.Namespace, vault_root: Path) -> None:
    """Handle read-only status without initializing an index.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed status arguments, retained for the CLI handler signature.
    vault_root : Path
        Explicit target vault.
    """
    try:
        _emit(status(vault_root))
    except ImportError as exc:
        _error(str(exc), CAPABILITY_REMEDIATION)
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        _error(str(exc), "Check stderr and package capabilities.")


def main(argv: list[str] | None = None) -> int:
    """Run one CLI command against the environment-resolved vault.

    Parameters
    ----------
    argv : list[str], optional
        CLI arguments; defaults to the process arguments.

    Returns
    -------
    int
        Zero on success; failures emit JSON and exit with code one.
    """
    parser = argparse.ArgumentParser(
        description="Vault search compatibility shim (ragmark hybrid retrieval)."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # search
    p_search = sub.add_parser("search", help="Search the index.")
    p_search.add_argument("query", help="Natural-language query string.")
    p_search.add_argument(
        "--k", type=int, default=8, help="Number of results (default 8)."
    )
    p_search.set_defaults(func=cmd_search)

    # reindex
    p_reindex = sub.add_parser("reindex", help="Rebuild the vector index.")
    p_reindex.add_argument(
        "--force", action="store_true", help="Re-embed all notes regardless of cache."
    )
    p_reindex.set_defaults(func=cmd_reindex)

    # status
    p_status = sub.add_parser("status", help="Report index health.")
    p_status.set_defaults(func=cmd_status)

    args = parser.parse_args(argv)

    vault_root = find_vault_root_from_env()
    if vault_root is None:
        _error(
            "vault root not found (no brain/ + perf/ + CLAUDE.md signature at "
            "CLAUDE_PROJECT_DIR or above the working directory)",
            "Run from inside the vault, or set CLAUDE_PROJECT_DIR to it.",
        )

    args.func(args, vault_root)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        print(
            json.dumps({"error": str(exc), "remediation": "Check stderr for details."})
        )
        sys.exit(1)
