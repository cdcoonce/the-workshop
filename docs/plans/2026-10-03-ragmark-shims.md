# Ragmark compatibility shims

Date: 2026-10-03
Status: local coordinated implementation; no deployment or live index rebuild

Authority: ragmark#94 explicitly permits `ragmark.compat`; the owner's approved
scope extension is recorded at
https://github.com/cdcoonce/ragmark/issues/94#issuecomment-5973972945.
The delegated #94/#95 cutover preserves legacy Python/CLI signatures while
using the approved core for retrieval and the packaged four-tool MCP face.

## Boundaries

`ragmark_adapter.config_for_vault(vault_root)` is shared by the semantic, MCP,
and graph shims. It uses explicit `<root>/.ragmark` storage, owner folder and
exclusion constants, and the core's existing machine-context defaults. The new
`vault_scope_resolved.for_vault(root)` resolves each explicit root independently
of ambient cwd/environment/cache and does not register an owner module in
`sys.modules`. Absent names retain shipped defaults; a present broken config
fails closed. Existing ambient hook exports retain their fail-soft behavior.
An empty owner folder allowlist is rejected because ragmark's empty folder set
means unrestricted scope; silently translating it would reverse the policy.
Root-only exclusions are already covered by the nonempty top-level folder
allowlist; their basenames are not globally excluded (a nested README can be
a legitimate note).

`semantic_index` retains `iter_vault_notes`, `chunk_note`, `file_hash`,
`embed_texts`, `build_index`, keyword-only-root `search`, `status`, CLI handlers,
and `main`. Parsing, tokenizer-aware chunking, embedding, storage, refresh, and
ranking now belong to ragmark. Helper chunks keep text/snippet/note_path keys;
empty content follows core chunking instead of fabricating path text. A search
calls core once for up to 25 chunks, then `compat.note_results` preserves first
chunk per note, ordering, scores, and truthful shorter results. There is no
cosine threshold, legacy vector reader, or second over-fetch/refill loop.

Build statistics map added+updated to indexed and unchanged to skipped, expose
removed and parse defects, and count actual stored chunks. Forced rebuild
statistics describe the new pass, not a diff against the discarded snapshot.
Status forwards `compat.status` unchanged, including unknown values and failure
states. It does not refresh, create an index, or invent build time. Recorded
index-root provenance is unavailable and explicitly reported as such.

`vault_mcp.build_server` delegates directly to packaged `ragmark.mcp.build_server`.
The four tools, argument shapes, read-only annotations, and chunk-ID search
shape remain the packaged contract. Retained Python read/gate helpers delegate
to core; the optional injected-search seam also gates returned paths. No extra
legacy over-fetch applies. CLI root discovery remains environment-based and
refuses an unrecognized vault.

## Dependency and release coordination

The new source API is not assumed to exist in the current published package.
The config factory checks `scoped_folders`, `excluded_filenames`, and
`excluded_path_prefixes` before constructing any retrieval configuration.
Missing APIs fail loudly with coordinated-release/source remediation; there
is no broader config fallback. The retained inventory helper delegates to
core `index._walk_notes` and checks that capability too; it is a deliberate
private seam that must be rechecked when upgrading the package.

The inline script dependencies become `ragmark>=0.1,<1` and
`ragmark[mcp]>=0.1,<1`; that version range alone does not satisfy capability
requirements. The dependency owner updates machinery extras and test runner
configuration. `/find` uses the machinery `embeddings` environment, so source
or release selection is centralized. Tests use the existing Ragmark Python
environment with `PYTHONPATH` pointing to the combined reviewed source, without
installation, cache migration, model download, or an active vault index build.

## Retired tests and replacement ownership

This is an improve-during-cutover migration, not a predecessor parity oracle.
No protected golden data was changed. Legacy tests that pin retired internals
are replaced by public shim behavior tests and these authoritative core suites:

| Retired assertions | Core contract / retained shim evidence |
| --- | --- |
| `_extract_frontmatter` line parser, quote stripping | `tests/test_parse.py`: real YAML, metadata, malformed input, CRLF; shim multiline-description fixture |
| Word/character packing, `CHUNK_MAX_CHARS`, `_split_oversize` | `tests/test_chunk.py`: tokenizer ceiling and conservation, description chunk, heading/parent refs; `tests/test_index.py::test_token_count_is_bound_to_the_injected_embedders_ruler` |
| Fabricated empty-note chunks and heading-window packing | Core chunk contract; shim tests explicitly require no invented empty-note text while retaining dictionary keys and relative paths |
| `_save_index`/`_load_index` JSON+NumPy persistence | `tests/test_store.py`: identity, atomic writes, vectors; `tests/test_index.py`: incremental changes, corruption, conservation; shim root-resolution tests build/read real fixture indexes |
| Temporary fastembed cache location | `tests/test_embed.py`: durable ragmark cache and override precedence; shim `embed_texts` uses stub core embedder |
| Legacy MCP over-fetch factor | Core `tests/test_search.py` and gating suite own retrieval; shim regression requires one bounded call, and actual MCP fixtures pin four tools/annotations/scope |

## Validation

TDD reds were observed for missing explicit-root resolution/factory, invalid
scope translation, old search returning no fresh-index hits, missing freshness
states, omitted removal/defect statistics, naive multiline YAML parsing,
two-tool MCP registration, redundant over-fetch, and ignored owner exclusions.
Each corresponding change was followed by a passing focused check.

Fixture coverage includes conflicting ambient/explicit roots, capability
refusal, malformed owner policy, context-restricted and unknown-context
retrieval, excluded note categories, actual MCP search/read calls with chunk
IDs, added/changed/deleted query refresh, read-only missing/stale status,
truthful build statistics, helper shapes, keyword-only root arguments, and
JSON CLI error handling. All embedding calls use a stub; the parent's combined
repository gates remain required before publication.
