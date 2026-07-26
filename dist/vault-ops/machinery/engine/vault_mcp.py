#!/usr/bin/env -S uv run --script
"""vault_mcp — a read-only MCP surface over the vault.

Today the vault is shared memory only for a session standing *inside* it.
Sessions in other repos (afk, the-workshop, work projects) and other agents
(Codex, Cortex, Copilot) cannot query it, so conventions get restated by hand
and handoffs are push-not-pull. This server closes that gap by exposing the
existing semantic index and note bodies over MCP.

Two deliberate constraints, both inherited rather than invented here:

- **Read + search only.** An open write surface reachable by arbitrary agents
  widens the prompt-injection surface the containment analysis already flags
  (the vault's own instruction files are a poisoning vector). If writes are
  ever wanted they belong in a single append-only `capture` tool routing
  through a `/dump`-shaped inbox — never direct note edits.
- **Serve from the derived layer.** The semantic index stays outside the
  notes and regenerable; this server is stateless over vault files + index.

Structure: the pure core (`resolve_note`, `read_note`, `search_notes`) holds
all the policy and is unit-tested without a server; `build_server` is a thin
FastMCP shell over it, and imports fastmcp lazily so the core stays cheap to
import and to test.

# /// script
# requires-python = ">=3.11"
# dependencies = ["fastmcp", "fastembed", "numpy"]
# ///
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any, Callable

from vault_scope_resolved import is_graph_markdown_note
from vault_utils import read_vault_context

# One call must not be able to haul the whole index across the wire. The cap is
# on the server side because the caller is the untrusted party here.
MAX_RESULTS = 25

DEFAULT_RESULTS = 8

# Top-level directory -> the machine context that owns it. Everything not listed
# (brain/, org/, perf/, reference/, thinking/) is shared by both machines.
CONTEXT_DIRS = {"work": "work", "personal": "personal"}

# Which owned scopes each machine context may see. Deliberately ASYMMETRIC.
#
# The vault is one repo synced to both machines, so work/ notes are already on
# the personal machine's disk — hiding them from search costs reach and
# protects nothing. The exposure that actually matters runs the other way:
# personal material surfacing inside an agent session on an employer-managed
# machine. So the work context is the restricted one, and a context absent
# from this map (notably "unknown") sees shared notes only.
VISIBLE_SCOPES = {
    "personal": frozenset({"personal", "work"}),
    "work": frozenset({"work"}),
}

# Context filtering happens after the index returns its ranked hits, so asking
# for exactly k would under-deliver whenever the top k are out of context.
# Over-fetch, filter, then truncate.
OVERFETCH = 4


class VaultAccessError(Exception):
    """Raised when a requested path is not a readable vault note.

    Deliberately does not distinguish "outside the vault" from "not a note"
    from "missing" from "out of context": a caller probing the boundary learns
    only that the path is unavailable, not the shape of the filesystem behind
    it — nor whether a note it may not see exists at all.
    """


def note_context(rel_path: str) -> str | None:
    """Return the machine context owning *rel_path*, or None when shared."""
    parts = PurePosixPath(str(rel_path)).parts
    return CONTEXT_DIRS.get(parts[0]) if parts else None


def visible_in_context(rel_path: str, context: str) -> bool:
    """True when a note in *rel_path* may be surfaced on a *context* machine.

    Shared notes are visible everywhere. Owned notes follow `VISIBLE_SCOPES`:
    the personal machine sees both scopes, the work machine sees only work.

    An ``unknown`` context — what ``read_vault_context`` returns when the
    marker is missing — is absent from the map and so sees shared notes only.
    That is the fail-closed direction: the moment we are least sure where we
    are running is the moment to reveal least.
    """
    owner = note_context(rel_path)
    if owner is None:
        return True
    return owner in VISIBLE_SCOPES.get(context, frozenset())


def active_context(vault_root: Path) -> str:
    """Read the machine context from the vault this server is rooted at.

    Server-side by construction. The context is never a parameter the caller
    supplies, because the caller is the untrusted party — a work machine that
    could ask for "personal" would defeat the whole boundary.
    """
    return read_vault_context(Path(vault_root))


def resolve_note(rel_path: str, vault_root: Path) -> Path:
    """Resolve *rel_path* to a readable note inside *vault_root*.

    The order matters. ``resolve()`` runs FIRST so that symlinks and ``..``
    segments are collapsed before the containment check — a check written
    against the *unresolved* path passes for a symlink pointing out of the
    vault, which is precisely the exfiltration case. Only then is the result
    tested for being graph content, so ``.claude/``, ``.git/``, ``.env`` and
    other non-note files inside the vault stay unreachable.
    """
    root = Path(vault_root).resolve()
    # `root / rel_path` yields rel_path itself when it is absolute, so an
    # absolute argument is not silently honored — it fails containment below.
    resolved = (root / rel_path).resolve()

    if not resolved.is_relative_to(root):
        raise VaultAccessError(f"path is not available: {rel_path}")
    if not resolved.is_file():
        raise VaultAccessError(f"path is not available: {rel_path}")
    if not is_graph_markdown_note(resolved, root):
        raise VaultAccessError(f"path is not available: {rel_path}")
    if not visible_in_context(
        resolved.relative_to(root).as_posix(), active_context(root)
    ):
        raise VaultAccessError(f"path is not available: {rel_path}")
    return resolved


def read_note(rel_path: str, vault_root: Path) -> str:
    """Return the text of one vault note.

    Routes through `resolve_note` rather than repeating the checks, so there
    is exactly one implementation of the access boundary to get right.
    """
    return resolve_note(rel_path, vault_root).read_text(encoding="utf-8")


def _default_search(query: str, k: int) -> list[dict]:
    """Delegate to the existing semantic index.

    Imported lazily: `semantic_index` pulls numpy at import and fastembed on
    first embed, which the unit tests should not pay for.
    """
    import semantic_index

    return semantic_index.search(query, k)


def search_notes(
    query: str,
    k: int = DEFAULT_RESULTS,
    *,
    vault_root: Path,
    search_fn: Callable[[str, int], list[dict]] | None = None,
) -> list[dict]:
    """Semantic search across the vault, returning context-visible hits.

    `vault_root` is required rather than optional: it is what the machine
    context is read from, and an optional scoping argument would default to
    returning everything — fail-open, in the one place that must fail closed.

    `search_fn` is injectable so the policy here (validation, clamping,
    context filtering) is testable without building an index or downloading
    an embedding model.
    """
    if not query.strip():
        raise ValueError("query must not be blank")
    if k <= 0:
        raise ValueError("k must be positive")

    k = min(k, MAX_RESULTS)
    fn = _default_search if search_fn is None else search_fn
    hits = fn(query, k * OVERFETCH)

    context = active_context(vault_root)
    visible = [h for h in hits if visible_in_context(h.get("note_path", ""), context)]
    return visible[:k]


def build_server(vault_root: Path) -> Any:
    """Build the FastMCP server exposing the read-only vault tools.

    fastmcp is imported here rather than at module scope so the core above
    stays importable — and testable — without the server dependency.
    """
    from fastmcp import FastMCP

    mcp: Any = FastMCP("vault")

    @mcp.tool()
    def vault_search(query: str, k: int = DEFAULT_RESULTS) -> list[dict]:
        """Search the vault semantically. Returns note paths, scores, snippets."""
        return search_notes(query, k, vault_root=vault_root)

    @mcp.tool()
    def vault_read(path: str) -> str:
        """Read one vault note by its vault-relative path (e.g. 'reference/x.md')."""
        return read_note(path, vault_root)

    return mcp


def main() -> None:
    """Serve over stdio, rooted at the vault this script was vendored into."""
    vault_root = Path(__file__).resolve().parents[2]
    build_server(vault_root).run()


if __name__ == "__main__":
    main()
