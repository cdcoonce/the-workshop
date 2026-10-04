#!/usr/bin/env -S uv run --script
"""Legacy entry point delegated to ragmark's pinned four-tool MCP face (#95).

Root discovery stays with the Workshop; scope, gating, chunk citations, and
server registration stay with the packaged core. Python helper signatures are
retained for existing callers, without a second retrieval over-fetch layer.
"""

# /// script
# requires-python = ">=3.11"
# dependencies = ["ragmark[mcp] @ https://github.com/cdcoonce/ragmark/releases/download/v0.2.0/ragmark-0.2.0-py3-none-any.whl"]
# ///

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ragmark import gate
from ragmark.config import DEFAULT_CONTEXT_DIRS, DEFAULT_VISIBLE_SCOPES, RagmarkConfig
from ragmark.gate import VaultAccessError as VaultAccessError
from ragmark.search import DEFAULT_RESULTS, MAX_RESULTS

from ragmark_adapter import config_for_vault
from vault_utils import find_vault_root_from_env

CONTEXT_DIRS = DEFAULT_CONTEXT_DIRS
VISIBLE_SCOPES = DEFAULT_VISIBLE_SCOPES
_CONTEXT_CONFIG = RagmarkConfig(vault_root=Path("."), index_dir=Path(".ragmark"))


def note_context(rel_path: str) -> str | None:
    """Return the core policy's owning context.

    Parameters
    ----------
    rel_path : str
        Vault-relative note path.

    Returns
    -------
    str or None
        Owning context, or None for shared content.
    """
    return gate.note_context(rel_path, _CONTEXT_CONFIG)


def visible_in_context(rel_path: str, context: str) -> bool:
    """Return whether the core policy permits this note's owning context.

    Parameters
    ----------
    rel_path : str
        Vault-relative note path.
    context : str
        Machine context to evaluate.

    Returns
    -------
    bool
        Whether the owner scope is visible in that context.
    """
    return gate.visible_in_context(rel_path, context, _CONTEXT_CONFIG)


def active_context(vault_root: Path) -> str:
    """Read the server-side context from the explicit vault root.

    Parameters
    ----------
    vault_root : Path
        Vault whose machine context is requested.

    Returns
    -------
    str
        Context marker, or unknown when absent.
    """
    return gate.active_context(config_for_vault(vault_root))


def resolve_note(rel_path: str, vault_root: Path) -> Path:
    """Resolve a note through the core containment, corpus, and context gate.

    Parameters
    ----------
    rel_path : str
        Requested vault-relative note path.
    vault_root : Path
        Explicit vault root.

    Returns
    -------
    Path
        Resolved, permitted note path.
    """
    return gate.resolve_note(rel_path, config_for_vault(vault_root))


def read_note(rel_path: str, vault_root: Path) -> str:
    """Return a note through the core's single read boundary.

    Parameters
    ----------
    rel_path : str
        Requested vault-relative note path.
    vault_root : Path
        Explicit vault root.

    Returns
    -------
    str
        Bare note text.
    """
    return gate.read_note(rel_path, config_for_vault(vault_root))


def _default_search(query: str, k: int, vault_root: Path) -> list[dict]:
    import semantic_index

    return semantic_index.search(query, k, vault_root=vault_root)


def search_notes(
    query: str,
    k: int = DEFAULT_RESULTS,
    *,
    vault_root: Path,
    search_fn: Callable[[str, int], list[dict]] | None = None,
) -> list[dict]:
    """Preserve the legacy Python helper without another over-fetch layer.

    Parameters
    ----------
    query : str
        Nonblank query.
    k : int
        Positive result limit, capped by the core maximum.
    vault_root : Path
        Required keyword-only policy and context root.
    search_fn : callable, optional
        Legacy injection seam. Its dictionaries still pass the core gate.

    Returns
    -------
    list[dict]
        At most k visible note records. The MCP server uses packaged tools.
    """
    if not query.strip():
        raise ValueError("query must not be blank")
    if k <= 0:
        raise ValueError("k must be positive")
    k = min(k, MAX_RESULTS)
    if search_fn is None:
        return _default_search(query, k, vault_root)
    config = config_for_vault(vault_root)
    hits = search_fn(query, k)
    allowed = set(
        gate.filter_visible([hit.get("note_path", "") for hit in hits], config)
    )
    return [hit for hit in hits if hit.get("note_path", "") in allowed][:k]


def build_server(vault_root: Path) -> Any:
    """Build ragmark's pinned four-tool, read-only server for this vault.

    Parameters
    ----------
    vault_root : Path
        Explicit root whose owner scope and machine context are enforced.

    Returns
    -------
    Any
        Packaged FastMCP server registered as ``vault``.
    """
    from ragmark.mcp import build_server as packaged_server

    return packaged_server(config_for_vault(vault_root))


def main() -> None:
    """Serve over stdio, rooted at the environment-resolved vault.

    The module ships inside the plugin cache (issue #677), so its own file
    position says nothing about where the vault is. Refusing to serve without
    a signature vault beats serving the wrong subtree: every tool this server
    exposes would otherwise read from — and report on — the plugin cache.
    """
    vault_root = find_vault_root_from_env()
    if vault_root is None:
        print(
            "vault root not found (no brain/ + perf/ + CLAUDE.md signature at "
            "CLAUDE_PROJECT_DIR or above the working directory)",
            file=sys.stderr,
        )
        sys.exit(1)
    build_server(vault_root).run()


if __name__ == "__main__":
    main()
