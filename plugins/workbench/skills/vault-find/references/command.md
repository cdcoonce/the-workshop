# /find — Semantic Vault Search

Search the vault by **meaning**, not keywords. Uses local fastembed embeddings (bge-small-en-v1.5, ONNX, fully on-device) to find notes that match a concept even when the exact words don't appear. Designed for the retrieval pain `reference/` exposes: "I remember the idea but searched the wrong words."

**Explicit-invoke only.** This is a search verb you type deliberately; it does not auto-fire on general questions. When `reference/` notes are the likely target, prefer `/find` over grep. When keyword retrieval is clearly sufficient (known title, exact phrase), use grep directly.

## Usage

```
/find <natural-language query>   # semantic search + answer
/find --reindex                  # force full rebuild of the vector index
/find --status                   # report index health (notes, chunks, freshness)
```

## Process

### `/find <query>`

1. **Incremental reindex.** Run `uv run --script .claude/scripts/semantic_index.py reindex` (no `--force`). The engine checks a sha256 manifest and re-embeds only changed or new notes — near-instant when nothing has changed.

2. **Search.** Run `uv run --script .claude/scripts/semantic_index.py search "<query>"`. The engine returns a JSON list of `{note_path, score, snippet}`, deduplicated to note level (best-scoring chunk per note), sorted descending.

3. **Present ranked hits.** Show the user the top results: note path as a `[[wikilink]]`, cosine score, and the matching snippet. Briefly explain why each result matched (what concept or phrase made it relevant).

4. **Read and answer.** Read the top 2–3 full notes to actually answer the user's question — do not stop at snippets. Synthesize across those notes; quote directly when exact wording matters. Link all referenced notes as `[[wikilinks]]` in your response.

### `/find --reindex`

Run `uv run --script .claude/scripts/semantic_index.py reindex --force`. Forces a full rebuild — re-embeds every in-scope note from scratch. Use when the index seems stale, after a large vault reorganization, or when the user wants to confirm the index is fresh. Report the returned stats: `{indexed, skipped, total_chunks, elapsed}`.

### `/find --status`

Run `uv run --script .claude/scripts/semantic_index.py status`. Report the returned `{notes, chunks, stale_notes, index_built_at, model, ready}` dict in readable form. Flag if `stale_notes > 0` and suggest running `/find --reindex` if the staleness is high.

## Index Scope

The engine indexes: `brain/` · `work/` · `personal/` · `org/` · `perf/` · `reference/` · `thinking/`

Excluded: `thinking/session-logs/` · `.brain/` · `templates/` · `.claude/` · non-`.md` files.

The index lives in `.claude/data/semantic/` (gitignored, machine-local). Each machine builds its own; it is never synced.

## Cold-Start Behavior

On the first ever run, fastembed downloads the bge-small-en-v1.5 ONNX model (~130MB) to `~/.cache/fastembed`. The engine emits a one-time notice to stderr during that download. Tell the user: "This first index build may take 30–60 seconds while the model downloads — subsequent runs are instant."

## Failure Handling (fail loud)

- **fastembed missing or import error** — the engine returns `{"error": "...", "remediation": "..."}`. Surface the remediation verbatim (it will say `uv add fastembed`), then fall back to a keyword grep over the scoped folders. Always emit a clear `(semantic unavailable — keyword results)` banner so the user knows they're getting fallback results.
- **Index missing or corrupt** — the engine rebuilds automatically on search if no vectors exist. If rebuild itself fails, surface the error JSON and ask the user to run `/find --reindex` manually after resolving the issue.
- **Empty results** — if semantic search returns no hits or all scores are below 0.2, say so explicitly and offer a keyword fallback. Never imply an empty result means the vault has nothing relevant.
- **Errors always appear as `{"error": "...", "remediation": "..."}` JSON on stdout** — parse and surface them; never let a raw Python traceback reach the user.

## Constraints

- Semantic is **additive** — it complements keyword search and wikilink traversal; it does not replace them. When results feel weak, say so and try grep.
- Never claim a vector hit is the definitive truth. Scores reflect embedding similarity, not factual correctness; always read the full note before asserting a claim.
- All wikilinks in responses must use the note's vault-relative path or short title in `[[double brackets]]`.
- The conductor never touches the vectors directly — the engine is always called as a subprocess returning JSON.
