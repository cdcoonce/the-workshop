"""Semantic vault search engine — fastembed/ONNX embeddings, plain-numpy index.

Provides incremental indexing and cosine-similarity search over the vault's
markdown notes. Designed to be called as a subprocess by the /find skill;
all output is JSON on stdout so the conductor can parse it without needing
to read raw vector data.

CLI:
    uv run python semantic_index.py search "<query>" [--k N]
    uv run python semantic_index.py reindex [--force]
    uv run python semantic_index.py status

Exit codes:
    0 — success (result JSON on stdout)
    1 — operational error (error JSON on stdout + detail on stderr)
"""

# /// script
# requires-python = ">=3.10"
# dependencies = ["fastembed", "numpy"]
# ///

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from vault_scope_resolved import is_graph_markdown_note, iter_graph_markdown_notes
from vault_utils import find_vault_root_from_env

# ---------------------------------------------------------------------------
# Paths — the vault root is resolved from the environment, never from this
# file's location. The engine ships inside the plugin cache (issue #677):
# deriving the root positionally pointed every index path into the cache,
# where the index is never found and a reindex would be wiped on update.
# ``main()`` resolves once via ``find_vault_root_from_env()`` (which enforces
# the brain/ + perf/ + CLAUDE.md signature) and threads the root through.
# ---------------------------------------------------------------------------


def _index_dir(vault_root: Path) -> Path:
    """The on-disk index directory inside *vault_root*."""
    return vault_root / ".claude" / "data" / "semantic"

# Embedding model
MODEL_NAME = "BAAI/bge-small-en-v1.5"

# Chunking config (~300-token window; rough token ≈ word × 1.3)
CHUNK_TARGET_TOKENS = 300
WORDS_PER_TOKEN = 1 / 1.3  # words per token estimate
CHUNK_TARGET_WORDS = int(CHUNK_TARGET_TOKENS * WORDS_PER_TOKEN)  # ≈230 words

# Hard per-chunk ceiling in characters. The embedding model silently truncates
# input past 512 tokens; at a conservative ~4 chars/token that cliff sits near
# 2000 chars, so 1600 keeps a safety margin for token-dense text (code, URLs).
# Any chunk beyond this cap loses its tail to search entirely.
CHUNK_MAX_CHARS = 1600

SNIPPET_LEN = 200  # characters kept as the display snippet


# ---------------------------------------------------------------------------
# Helpers — file enumeration
# ---------------------------------------------------------------------------


def _is_excluded(path: Path, vault_root: Path) -> bool:
    """Return True if *path* falls under any excluded subtree."""
    return not is_graph_markdown_note(path, vault_root)


def iter_vault_notes(vault_root: Path) -> list[Path]:
    """Yield every in-scope .md file, exclusions applied."""
    return iter_graph_markdown_notes(vault_root)


# ---------------------------------------------------------------------------
# Helpers — content processing
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_HEADING_RE = re.compile(r"^#{1,6}\s+", re.MULTILINE)


def _extract_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Strip YAML frontmatter and return (fields dict, body)."""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text

    body = text[m.end():]
    fields: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            fields[key.strip()] = val.strip().strip('"').strip("'")
    return fields, body


def _word_count(s: str) -> int:
    return len(s.split())


def _snippet(text: str) -> str:
    """First SNIPPET_LEN chars of *text*, stripped."""
    return text.strip()[:SNIPPET_LEN].replace("\n", " ")


_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n")
_LINE_SPLIT_RE = re.compile(r"\n")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _fits_window(text: str) -> bool:
    """True if *text* fits one packing window under both chunk limits."""
    return _word_count(text) <= CHUNK_TARGET_WORDS and len(text) <= CHUNK_MAX_CHARS


def _pack_units(units: list[str], joiner: str) -> list[str]:
    """Greedily pack *units* into windows under the word and char limits.

    A unit that alone exceeds a limit becomes its own window; callers split
    such windows further.
    """
    windows: list[str] = []
    parts: list[str] = []
    words = 0
    chars = 0
    for unit in units:
        w = _word_count(unit)
        c = len(unit)
        if parts and (
            words + w > CHUNK_TARGET_WORDS
            or chars + len(joiner) + c > CHUNK_MAX_CHARS
        ):
            windows.append(joiner.join(parts))
            parts = []
            words = 0
            chars = 0
        parts.append(unit)
        words += w
        chars += c if len(parts) == 1 else len(joiner) + c
    if parts:
        windows.append(joiner.join(parts))
    return windows


def _word_slices(text: str) -> list[str]:
    """Last-resort split for text with no structural boundaries.

    Accumulates whitespace-separated words up to the chunk limits, hard-slicing
    any single word longer than the char ceiling (e.g. a minified blob).
    """
    slices: list[str] = []
    parts: list[str] = []
    chars = 0
    for word in text.split():
        while len(word) > CHUNK_MAX_CHARS:
            if parts:
                slices.append(" ".join(parts))
                parts = []
                chars = 0
            slices.append(word[:CHUNK_MAX_CHARS])
            word = word[CHUNK_MAX_CHARS:]
        if not word:
            continue
        if parts and (
            len(parts) >= CHUNK_TARGET_WORDS or chars + 1 + len(word) > CHUNK_MAX_CHARS
        ):
            slices.append(" ".join(parts))
            parts = []
            chars = 0
        parts.append(word)
        chars += len(word) if len(parts) == 1 else 1 + len(word)
    if parts:
        slices.append(" ".join(parts))
    return slices


def _split_oversize(text: str) -> list[str]:
    """Split one oversize section into consecutive window-sized pieces.

    Tries progressively finer boundaries — blank-line paragraphs, then single
    lines, then sentences — packing each level back into windows, and falls
    back to word-level slicing when a run has no boundaries at all. Every
    returned piece fits under CHUNK_TARGET_WORDS and CHUNK_MAX_CHARS, so
    nothing is lost to the embedding model's silent 512-token truncation.
    """
    if _fits_window(text):
        return [text]
    for splitter, joiner in (
        (_PARAGRAPH_SPLIT_RE, "\n\n"),
        (_LINE_SPLIT_RE, "\n"),
        (_SENTENCE_SPLIT_RE, " "),
    ):
        units = [u.strip() for u in splitter.split(text) if u.strip()]
        if len(units) <= 1:
            continue
        pieces: list[str] = []
        for window in _pack_units(units, joiner):
            if _fits_window(window):
                pieces.append(window)
            else:
                # Only a single-unit window can overflow; recursing descends
                # to the next finer boundary, so this terminates.
                pieces.extend(_split_oversize(window))
        return pieces
    return _word_slices(text)


def chunk_note(path: Path, raw: str, vault_root: Path) -> list[dict[str, Any]]:
    """Split a note into embeddable chunks.

    Strategy:
    1. Strip frontmatter; if a `description` field exists, emit it as a
       standalone high-signal chunk.
    2. Split body on markdown headings, then pack consecutive sections
       into ~300-token windows (overflow always starts a new chunk). A
       single section larger than a window is split at paragraph, line, or
       sentence boundaries into consecutive windows — never emitted whole,
       because the embedding model silently truncates past ~512 tokens
       (CHUNK_MAX_CHARS enforces that cap on every body chunk).
    3. Each chunk carries a short snippet for display.
    """
    fields, body = _extract_frontmatter(raw)
    chunks: list[dict[str, Any]] = []

    rel = str(path.relative_to(vault_root))

    # Description chunk — high-signal summary written by the human
    if desc := fields.get("description", "").strip():
        chunks.append({"text": desc, "snippet": desc[:SNIPPET_LEN], "note_path": rel})

    # Split body on heading lines, preserving the heading text
    sections: list[str] = []
    current_parts: list[str] = []
    for line in body.splitlines(keepends=True):
        if _HEADING_RE.match(line) and current_parts:
            sections.append("".join(current_parts).strip())
            current_parts = [line]
        else:
            current_parts.append(line)
    if current_parts:
        sections.append("".join(current_parts).strip())
    sections = [s for s in sections if s]

    # Pack sections into ~300-token windows
    window_parts: list[str] = []
    window_words = 0
    window_chars = 0

    def flush_window() -> None:
        if not window_parts:
            return
        text = "\n\n".join(window_parts).strip()
        if text:
            chunks.append(
                {"text": text, "snippet": _snippet(text), "note_path": rel}
            )

    for section in sections:
        w = _word_count(section)
        c = len(section)
        # A single section beyond the window cannot be embedded whole — the
        # model truncates past ~512 tokens — so split it into consecutive
        # window-sized pieces instead of emitting it unbounded.
        if w > CHUNK_TARGET_WORDS or c > CHUNK_MAX_CHARS:
            flush_window()
            window_parts = []
            window_words = 0
            window_chars = 0
            for piece in _split_oversize(section):
                chunks.append(
                    {"text": piece, "snippet": _snippet(piece), "note_path": rel}
                )
            continue

        if window_parts and (
            window_words + w > CHUNK_TARGET_WORDS
            or window_chars + 2 + c > CHUNK_MAX_CHARS
        ):
            flush_window()
            window_parts = []
            window_words = 0
            window_chars = 0

        window_parts.append(section)
        window_words += w
        window_chars += c if len(window_parts) == 1 else 2 + c

    flush_window()

    # Always emit at least one chunk so the note appears in the manifest
    if not chunks:
        text = body.strip() or raw.strip()
        chunks.append(
            {"text": text or rel, "snippet": _snippet(text or rel), "note_path": rel}
        )

    return chunks


# ---------------------------------------------------------------------------
# Helpers — hashing
# ---------------------------------------------------------------------------


def file_hash(path: Path) -> str:
    """SHA-256 hex digest of raw file bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Helpers — index I/O
# ---------------------------------------------------------------------------


def _load_index(
    vault_root: Path,
) -> tuple[np.ndarray | None, list[dict], dict[str, str]]:
    """Load vectors, meta, manifest from disk.  Returns Nones on any failure."""
    index_dir = _index_dir(vault_root)
    vectors_file = index_dir / "vectors.npy"
    meta_file = index_dir / "meta.json"
    manifest_file = index_dir / "manifest.json"
    try:
        vectors = np.load(str(vectors_file)) if vectors_file.exists() else None
        meta = json.loads(meta_file.read_text()) if meta_file.exists() else []
        manifest = json.loads(manifest_file.read_text()) if manifest_file.exists() else {}
        return vectors, meta, manifest
    except Exception:
        return None, [], {}


def _save_index(
    vault_root: Path, vectors: np.ndarray, meta: list[dict], manifest: dict[str, str]
) -> None:
    """Persist the index files atomically-ish (write then rename)."""
    index_dir = _index_dir(vault_root)
    index_dir.mkdir(parents=True, exist_ok=True)
    np.save(str(index_dir / "vectors.npy"), vectors.astype(np.float32))
    (index_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    (index_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))


# ---------------------------------------------------------------------------
# Embedding — lazy singleton
# ---------------------------------------------------------------------------

_model: Any = None  # fastembed.TextEmbedding


def _get_model() -> Any:
    """Return a cached fastembed TextEmbedding instance."""
    global _model
    if _model is None:
        from fastembed import TextEmbedding  # type: ignore[import]

        _model = TextEmbedding(model_name=MODEL_NAME)
    return _model


def embed_texts(texts: list[str]) -> np.ndarray:
    """Embed a list of texts → float32 matrix (n × dim)."""
    model = _get_model()
    vecs = list(model.embed(texts))
    return np.array(vecs, dtype=np.float32)


# ---------------------------------------------------------------------------
# Core — build_index
# ---------------------------------------------------------------------------


def build_index(vault_root: Path, force: bool = False) -> dict:
    """Rebuild (incremental or full) the on-disk vector index.

    Args:
        vault_root: The vault the index describes and lives inside.
        force: If True, re-embed every note regardless of content hash.

    Returns:
        Dict with keys: indexed, skipped, total_chunks, elapsed.
    """
    t0 = time.monotonic()

    existing_vectors, existing_meta, manifest = _load_index(vault_root)
    if force or existing_vectors is None:
        existing_vectors = None
        existing_meta = []
        manifest = {}

    notes = iter_vault_notes(vault_root)
    note_paths = {str(p.relative_to(vault_root)): p for p in notes}

    # Drop chunks belonging to deleted notes
    if existing_meta:
        live_rels = set(note_paths.keys())
        kept_meta = [m for m in existing_meta if m["note_path"] in live_rels]
        kept_indices = [i for i, m in enumerate(existing_meta) if m["note_path"] in live_rels]
        if existing_vectors is not None and len(kept_indices) < len(existing_meta):
            existing_vectors = existing_vectors[kept_indices]
        existing_meta = kept_meta

    # Remove manifest entries for deleted notes
    manifest = {k: v for k, v in manifest.items() if k in note_paths}

    new_texts: list[str] = []
    new_meta: list[dict] = []
    indexed = 0
    skipped = 0

    for rel, path in note_paths.items():
        h = file_hash(path)
        if not force and manifest.get(rel) == h:
            skipped += 1
            continue
        # Changed or new — drop its existing chunks first
        if not force and existing_meta:
            keep_mask = [m["note_path"] != rel for m in existing_meta]
            existing_meta = [m for m, k in zip(existing_meta, keep_mask) if k]
            if existing_vectors is not None:
                keep_arr = np.array(keep_mask, dtype=bool)
                existing_vectors = existing_vectors[keep_arr]

        raw = path.read_text(encoding="utf-8", errors="replace")
        chunks = chunk_note(path, raw, vault_root)
        for idx, chunk in enumerate(chunks):
            chunk["chunk_index"] = idx
            chunk["note_hash"] = h
            new_texts.append(chunk["text"])
            new_meta.append(chunk)

        manifest[rel] = h
        indexed += 1

    # Embed newly added/changed chunks
    new_vectors: np.ndarray | None = None
    if new_texts:
        new_vectors = embed_texts(new_texts)

    # Combine with surviving existing vectors
    if existing_vectors is not None and new_vectors is not None:
        all_vectors = np.vstack([existing_vectors, new_vectors])
        all_meta = existing_meta + new_meta
    elif new_vectors is not None:
        all_vectors = new_vectors
        all_meta = new_meta
    elif existing_vectors is not None:
        all_vectors = existing_vectors
        all_meta = existing_meta
    else:
        # No notes at all (empty vault) — write empty index
        all_vectors = np.zeros((0, 384), dtype=np.float32)
        all_meta = []

    _save_index(vault_root, all_vectors, all_meta, manifest)

    elapsed = round(time.monotonic() - t0, 2)
    return {
        "indexed": indexed,
        "skipped": skipped,
        "total_chunks": len(all_meta),
        "elapsed": elapsed,
    }


# ---------------------------------------------------------------------------
# Core — search
# ---------------------------------------------------------------------------


def search(query: str, k: int = 8, *, vault_root: Path) -> list[dict]:
    """Semantic search over the index.

    Returns up to *k* results deduplicated to note level (best-scoring chunk
    per note), sorted descending by cosine similarity. ``vault_root`` is
    keyword-only on purpose: a stale positional caller from the pre-#677
    signature fails loudly with a TypeError instead of searching the wrong
    tree.
    """
    vectors, meta, _ = _load_index(vault_root)

    if vectors is None or len(meta) == 0:
        return []

    # Embed query
    q_vec = embed_texts([query])[0]  # shape (dim,)

    # Cosine similarity: normalise both sides then dot product
    v_norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    v_norms = np.where(v_norms == 0, 1.0, v_norms)
    normed = vectors / v_norms

    q_norm = np.linalg.norm(q_vec)
    q_norm = q_norm if q_norm != 0 else 1.0
    q_normed = q_vec / q_norm

    scores = normed @ q_normed  # shape (n,)

    # Dedupe to note level — keep max score per note
    best: dict[str, tuple[float, dict]] = {}
    for i, m in enumerate(meta):
        rel = m["note_path"]
        s = float(scores[i])
        if rel not in best or s > best[rel][0]:
            best[rel] = (s, m)

    ranked = sorted(best.values(), key=lambda t: t[0], reverse=True)
    return [
        {
            "note_path": m["note_path"],
            "score": round(s, 4),
            "snippet": m.get("snippet", ""),
        }
        for s, m in ranked[:k]
    ]


# ---------------------------------------------------------------------------
# Core — status
# ---------------------------------------------------------------------------


def status(vault_root: Path) -> dict:
    """Report index health without modifying anything.

    Always names the resolved ``vault_root`` and ``index_dir`` in the output:
    the #677 failure mode was a wrong root masquerading as an empty vault, and
    a status report that shows *where* it looked makes that visible.
    """
    vectors, meta, manifest = _load_index(vault_root)
    base = {
        "vault_root": str(vault_root),
        "index_dir": str(_index_dir(vault_root)),
        "model": MODEL_NAME,
    }

    if vectors is None:
        return base | {
            "notes": 0,
            "chunks": 0,
            "stale_notes": 0,
            "index_built_at": None,
            "ready": False,
        }

    live_notes = iter_vault_notes(vault_root)
    live_rels = {str(p.relative_to(vault_root)) for p in live_notes}

    stale = 0
    for rel in live_rels:
        path = vault_root / rel
        h = file_hash(path)
        if manifest.get(rel) != h:
            stale += 1

    built_at = None
    manifest_file = _index_dir(vault_root) / "manifest.json"
    if manifest_file.exists():
        mtime = manifest_file.stat().st_mtime
        built_at = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()

    note_set = {m["note_path"] for m in meta}

    return base | {
        "notes": len(note_set),
        "chunks": len(meta),
        "stale_notes": stale,
        "index_built_at": built_at,
        "ready": True,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _emit(obj: Any) -> None:
    """Write *obj* as JSON to stdout."""
    print(json.dumps(obj))


def _error(message: str, remediation: str = "") -> None:
    """Emit a structured error and exit with code 1."""
    _emit({"error": message, "remediation": remediation})
    sys.exit(1)


def _fastembed_cache_dir() -> Path:
    """The directory fastembed actually caches models in.

    fastembed resolves $FASTEMBED_CACHE_PATH first, then falls back to
    <system tempdir>/fastembed_cache — not ~/.cache/fastembed. Probing the
    wrong path made the first-run notice fire on every reindex.
    """
    import os
    import tempfile

    override = os.environ.get("FASTEMBED_CACHE_PATH")
    if override:
        return Path(override)
    return Path(tempfile.gettempdir()) / "fastembed_cache"


def _check_first_run() -> None:
    """Warn (to stderr) if the model cache is absent — the next run downloads the model."""
    try:
        import fastembed  # noqa: F401 — presence check only

        cache_root = _fastembed_cache_dir()
        if not cache_root.exists():
            print(
                json.dumps({
                    "notice": (
                        "First run: fastembed will download the bge-small-en-v1.5 ONNX model "
                        f"(~65MB) to {cache_root}. Subsequent runs reuse the cache. "
                        "Indexing may take 30–60 seconds."
                    )
                }),
                file=sys.stderr,
            )
    except Exception:
        pass


def cmd_reindex(args: argparse.Namespace, vault_root: Path) -> None:
    """Handler for `reindex [--force]`."""
    _check_first_run()
    try:
        result = build_index(vault_root, force=args.force)
        _emit(result)
    except ImportError as exc:
        _error(
            f"fastembed not available: {exc}",
            "Run: uv add fastembed  or  pip install fastembed",
        )
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        _error(str(exc), "Check stderr for details; try --force to rebuild from scratch.")


def cmd_search(args: argparse.Namespace, vault_root: Path) -> None:
    """Handler for `search "<query>" [--k N]`."""
    # Ensure index exists before searching
    vectors, meta, _ = _load_index(vault_root)
    if vectors is None or len(meta) == 0:
        _check_first_run()
        try:
            build_index(vault_root, force=False)
        except ImportError as exc:
            _error(
                f"fastembed not available: {exc}",
                "Run: uv add fastembed  or  pip install fastembed",
            )
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            _error(str(exc), "Try: uv run python semantic_index.py reindex --force")

    try:
        results = search(args.query, k=args.k, vault_root=vault_root)
        _emit(results)
    except ImportError as exc:
        _error(
            f"fastembed not available: {exc}",
            "Run: uv add fastembed  or  pip install fastembed",
        )
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        _error(str(exc), "Try reindexing first: uv run python semantic_index.py reindex")


def cmd_status(args: argparse.Namespace, vault_root: Path) -> None:  # noqa: ARG001
    """Handler for `status`."""
    try:
        _emit(status(vault_root))
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        _error(str(exc), "Check stderr for details.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Semantic vault search engine (fastembed / bge-small-en-v1.5)."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # search
    p_search = sub.add_parser("search", help="Search the index.")
    p_search.add_argument("query", help="Natural-language query string.")
    p_search.add_argument("--k", type=int, default=8, help="Number of results (default 8).")
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
        print(json.dumps({"error": str(exc), "remediation": "Check stderr for details."}))
        sys.exit(1)
