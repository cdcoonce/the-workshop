# Graphmark runtime dependency alignment

Date: 2026-10-03

The standalone graph CLI, machinery project, primary machinery test gate, and
three detector commands previously required `graphmark>=0.6,<0.7`. Ragmark's
runtime requires `graphmark>=0.9,<1.0`, so updating only the standalone script
would leave the machinery environment incompatible. Align all those primary
surfaces to the latter range and lock graphmark 0.9.1. Keep the separate 0.7
wrap-up and cold-read parity legs: they still represent the owner's Vault CI.

This is dependency preparation for the #94/#95 cutover work, not activation of
Ragmark or a claim that its note scope and ranking match the legacy APIs. It
does not change config or gate contracts, embeddings, live registration,
installed environments, or the corpus oracle. Versions and rendered source
stamps belong to the combined change's final gate.

## Implementation and checks

- Add dependency guards before changing declarations: four failures identified
  the three primary 0.6 declarations and the old lock; both 0.7 parity controls
  passed. Add guards for detector commands separately: six failures identified
  the three specs' test and collection pins. All guards now pass.
- Update `graph_cli.py`'s PEP 723 requirement, machinery `pyproject.toml`, the
  primary Make recipe, and the six detector command strings. Mutation anchors
  and the two owner-CI parity recipes remain unchanged.
- Resolve graphmark 0.9.1 offline using copied cached metadata in a temporary
  directory. Keep only its resolver-produced package record and project
  requirement in `uv.lock`; verify every unrelated package record matches the
  original lock. `uv lock --check --offline` passes with 102 packages.

Tests used existing interpreters and an explicit cached graphmark package on
`PYTHONPATH`; its imported path and distribution version were checked. No
environment was installed or synced, and tests used temporary fixtures without
real model calls or live index writes.

| Check | Result |
| --- | --- |
| Dependency guards plus existing gate/hook guard tests | 35 passed |
| Graph CLI alias/root resolution and wrap-up/cold-read suites, graphmark 0.9.1 | 279 passed |
| Full machinery suite, graphmark 0.9.1 | 1,274 passed; one concurrent gardener failure |
| Retained wrap-up/cold-read parity suites, graphmark 0.7.2 | 266 passed |
| Ruff check/format for new guard tests; diff whitespace check | Passed |
| Offline lock consistency | Passed |

The full-suite failure was
`test_failed_worker_launch_releases_only_own_reservation_and_retries_later`:
the retry lacked the expected `current` reservation. The gardener agent was
editing that separate code concurrently; this slice did not modify it. The
parent owns the final combined gate after gardener and adapter edits freeze.

`graph_cli.py` was handed back after its dependency-only edit for the parent's
public API adapter work. These results establish the tested 0.9.1 runtime;
they do not certify every future release allowed by the dependency range.

## Coordinated Ragmark source verification

The primary Make target now accepts `MACHINERY_TEST_PYTHON`, defaulting to its
existing `uv run` dependency command plus `ragmark[mcp]>=0.1,<1.0`. Passing an
existing interpreter explicitly lets the same gate use reviewed source on
`PYTHONPATH` without installing or syncing an environment. The other gates,
including the separate graphmark 0.7 parity recipes, are unchanged.

Normal-import capability tests require the three owner-scope configuration
fields, `compat.note_results`, `compat.status`, and `search.similar_notes`.
They do not construct models, indexes, or servers. The older source fails
collection for missing `ragmark.compat`, rather than skipping the suite.
The broad version range alone does not establish these capabilities.

TDD observed two failures before the Make change: the missing default Ragmark
dependency and the ignored interpreter override. The override test first
checks a dry run, then executes a temporary capture script to verify the
working directory and exact pytest arguments; it cannot accidentally run uv
while testing a broken override. After the change, 37 root dependency/gate/hook
tests and 21 focused runtime/adapter/graph-root tests passed. Ruff check,
format check, and diff whitespace checks passed.

Focused machinery validation used Python 3.13.5 from the existing Ragmark
environment (graphmark 0.9.1, pytest 9.1.1, FastMCP 3.4.5, fastembed 0.8.0,
NumPy 2.5.1, PyYAML 6.0.3) with the explicit
`ragmark-integration-current/src` tree and individual cached Hypothesis
6.165.3/sortedcontainers 2.4.0 directories on `PYTHONPATH`. No shared
environment, model cache, or live Vault index was changed. The parent owns
the full aggregate gate using this explicit source selection.

### Pending runtime packaging

The task-local `workshop-ragmark-optional-deps.patch` proposes replacing the
machinery embeddings extra with `ragmark>=0.1,<1.0` and the MCP extra with
`ragmark[mcp]>=0.1,<1.0`. Ragmark owns its embedding dependency and optional
MCP server dependency; keeping these under extras preserves the lightweight
default hook environment. This patch is deliberately not applied.

The capable scope/compatibility build is not yet represented by a published
version or reviewed source pin in this checkout. There is no cached Ragmark
registry artifact/metadata to resolve offline; the installed 0.1.0 distribution
is an editable local checkout. Apply the runtime metadata patch only with a
known capable release/version (tighten the minimum then) or an explicitly
reviewed source pin, and regenerate/verify the real lock. Do not invent a
registry artifact or hash. The current graph-only lock remains coherent;
successful source tests do not establish production packaging readiness.
