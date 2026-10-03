# /find — Hybrid Vault Search

Search the vault by meaning and exact terms using ragmark's local vector and lexical retrieval. The model runs on-device; note access follows the vault's owner scope and machine context.

**Explicit-invoke only.** This is a search verb you type deliberately; it does not auto-fire on general questions. When `reference/` notes are the likely target, prefer `/find` over grep. When a known title or exact phrase is sufficient, use scoped keyword retrieval directly.

## Usage

```
/find <natural-language query>   # hybrid search + answer
/find --reindex                  # explicitly rebuild this vault's derived index
/find --status                   # read-only index health and freshness
```

## Runtime prerequisite

Use the machinery project environment with its `embeddings` extra. The compatibility shim requires the coordinated ragmark scope and compatibility APIs from ragmark#94/#95. A package version in the declared range alone is insufficient: older packages fail with an explicit capability error. Use the reviewed source environment during coordinated development; deploy only after the required package release is available. Do not silently substitute an unrestricted ragmark config.

## Process

### `/find <query>`

1. **Search once.** Run `uv run --project "<engine>/.." --extra embeddings python "<engine>/semantic_index.py" search "<query>"`. Ragmark checks freshness and incrementally updates changed/new/deleted notes on the query path. No separate pre-search reindex is needed.

2. **Present ranked hits.** The JSON list contains `{note_path, score, snippet}`. Each note uses its highest-ranked supplied chunk. Scores are fused ranking values, not cosine similarity or confidence; retain low scores and never apply the old 0.2 cutoff. The shim requests at most 25 core chunk hits once, then presents up to 8 distinct notes by default. Fewer distinct notes yield a shorter list without refill.

3. **Read and answer.** Read the top 2–3 full notes through the scoped vault reader before answering. Check dates and later evidence when the question concerns current status. Synthesize across notes and link the supporting notes with `[[wikilinks]]`. Note-level dictionaries omit chunk IDs; use the packaged MCP `vault_search` hits when exact chunk citations are required.

### `/find --reindex`

Run `uv run --project "<engine>/.." --extra embeddings python "<engine>/semantic_index.py" reindex --force`. This explicitly rebuilds the requested vault's `.ragmark` index. Report `{indexed, skipped, removed, defects, total_chunks, elapsed}`. `indexed` counts added plus updated notes, `skipped` counts unchanged notes, and parse defects remain visible. A forced rebuild starts fresh, so its removal count does not describe the discarded prior snapshot.

### `/find --status`

Run `uv run --project "<engine>/.." --extra embeddings python "<engine>/semantic_index.py" status`. This inspects the index without creating or refreshing it. Report the named `vault_root`, `index_dir`, `state`, `ready`, note/chunk counts, and added/changed/deleted counts. Preserve unknown values as unknown. `index_built_at` is unavailable (`null`); do not invent a timestamp. `root_provenance: not_recorded` means the format does not prove which root originally built a copied index.

For `stale`, the next query normally refreshes it. For corruption, identity mismatch, or unavailable inspection, surface the returned error/remediation. A missing or unbuilt index is not ready.

## Index Scope and Storage

Owner scope comes from this explicit vault's `.vault/config/vault_scope.py`, with shipped defaults for names absent from a valid config. It controls allowed top-level folders, excluded directories, operating filenames, and transient prefixes. A present broken owner config fails closed. Machine context is read from this same vault's `.vault-context`; an unknown context sees shared notes only.

The derived index lives in `<vault>/.ragmark/`, machine-local and regenerable. The shim does not read, convert, or delete the old `.claude/data/semantic/` index. A first query or explicit rebuild creates the new index only in the requested vault.

## Model Cache

Ragmark manages its pinned local model. Its cache defaults to `~/.cache/ragmark/fastembed`, with `RAGMARK_FASTEMBED_CACHE` as an override. A first model use may download model assets; status reads identity metadata without loading the model. Do not promise a download size or duration.

## Failure Handling

- **Missing capability or dependency:** surface the structured error and remediation. Do not retry with broader scope or the old engine. A keyword fallback must honor the same owner scope and machine context and be labelled `(hybrid unavailable — keyword results)`.
- **Missing index:** the query path initializes it. **Corrupt or model-mismatched index:** surface the error; an explicit `--reindex` is the recovery path, after the reported cause is understood.
- **Empty or short results:** report what was returned. This does not establish that the vault contains no relevant evidence. Do not infer quality from the absolute score scale.
- **CLI failures:** parse `{error, remediation}` from stdout and surface them clearly; stderr holds diagnostic details.

## Constraints

- Retrieval complements keyword search and wikilink traversal. Always read source notes before asserting a claim.
- Ranking does not establish factual correctness or currentness. Preserve unresolved or historical status explicitly.
- Use vault-relative paths or short titles in response `[[wikilinks]]`.
- Call the engine or packaged MCP surface; do not manipulate vectors directly.
