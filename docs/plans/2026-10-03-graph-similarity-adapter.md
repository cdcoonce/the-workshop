# Graph similarity through Ragmark's public API

The graph CLI previously read `semantic_index._load_index` and pooled legacy
vectors itself. That would break when the semantic compatibility shim removes
the duplicate index implementation. It now calls `ragmark.search.similar_notes`
using the shared explicit-root owner-policy factory and the `.ragmark` store.

The public view preserves arithmetic-mean pooling and cosine similarity, so the
existing graph gaps band is retained. A missing index produces the existing
loud empty-reader behavior without creating a directory or database. Incomplete,
corrupt, unbuilt, mismatched, or unavailable indexes fail explicitly; coherent
stale indexes remain readable without refresh. Unavailable origins return no
candidates. The adapter does not refresh, embed, or convert the old index format.

TDD: moving the fixture to the new SQLite/vector format and asserting public API
delegation produced two failures against the old reader. After the adapter,
the root-resolution and alias suites passed: **15 tests**. Tests use temporary
databases and synthetic vectors, not models or the live Vault index.

## Read-only correction (2026-10-03)

Independent review found that the public similarity implementation calls
`IndexStore.connect()`, which can create schema. An empty existing database grew
from 0 to 32,768 bytes on a nominal read, and a two-chunk/one-vector index silently
returned an empty list. Both fixtures failed before this correction.

The Workshop adapter now preflights with `ragmark.compat.status`, using the
default embedder's identity metadata without loading its model. Only `ready` and
`stale` states proceed. A private `IndexStore` subclass supplies immutable,
query-only SQLite connections and closes them after each delegated call. Index
and SQLite-sidecar fingerprints must remain stable across preflight and every
similarity read. Core `similar_notes` still owns all pooling, cosine scores,
ranking, and context gating; no Ragmark core or structural graph-builder change
is included.

Focused follow-up validation: **12 tests pass**, including both corruption
regressions, post-preflight replacement refusal, numeric cosine preservation,
coherent-stale access, unchanged index bytes/mtimes/file inventory, and a denied
write through the connection passed to core. Fixture embedders expose identity
metadata only and fail if asked to embed or load a tokenizer. Ruff lint/format
and diff checks pass. The parent owns the aggregate gate.

This does not implement Ragmark's `gaps()` seam or alter issue #149's contract.
The graph CLI's structural graph-construction path remains separate from this
similarity adapter. Source integration and the required coordinated Ragmark
release must be verified before activation.
