"""Tests for vault_mcp — the read-only MCP surface over the vault.

Covers the pure core: path resolution, note reads, and search delegation.
The FastMCP wiring is a thin shell over these functions and is deliberately
not exercised here — importing fastmcp would pull a server dependency into
the unit suite for no added signal.

The path-resolution tests carry most of the weight. This module is the first
surface that lets an agent *outside* the vault repo read vault files, so the
question "which paths can a caller reach?" is the security boundary, not a
detail. Every rejection case below is a path a caller could plausibly ask
for, either by accident or on purpose.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(SCRIPTS_DIR))

from vault_mcp import (  # noqa: E402
    MAX_RESULTS,
    VaultAccessError,
    read_note,
    resolve_note,
    search_notes,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    """A minimal vault: one real note, one excluded file, one non-note."""
    root = tmp_path / "vault"
    (root / "reference").mkdir(parents=True)
    (root / "reference" / "alpha.md").write_text("# Alpha\n\nbody text\n")
    (root / ".claude").mkdir()
    (root / ".claude" / "settings.json").write_text('{"secret": true}')
    (root / "reference" / "data.csv").write_text("a,b\n1,2\n")
    (root / ".env").write_text("TOKEN=shhh\n")
    return root


# ---------------------------------------------------------------------------
# resolve_note — the security boundary
# ---------------------------------------------------------------------------


def test_resolves_a_note_inside_the_graph(vault: Path) -> None:
    resolved = resolve_note("reference/alpha.md", vault)

    assert resolved == (vault / "reference" / "alpha.md").resolve()


def test_rejects_parent_traversal(vault: Path) -> None:
    """`../` must not escape the vault, even though the target exists."""
    outside = vault.parent / "outside.md"
    outside.write_text("not yours\n")

    with pytest.raises(VaultAccessError):
        resolve_note("reference/../../outside.md", vault)


def test_rejects_absolute_path_outside_vault(vault: Path, tmp_path: Path) -> None:
    """An absolute path must be refused rather than silently honored."""
    stray = tmp_path / "stray.md"
    stray.write_text("elsewhere\n")

    with pytest.raises(VaultAccessError):
        resolve_note(str(stray), vault)


def test_rejects_symlink_escaping_the_vault(vault: Path, tmp_path: Path) -> None:
    """A symlink inside the vault pointing out of it must not be followed.

    This is the case a naive `vault_root in path.parents` check passes and a
    resolve()-then-check gets right, so it is worth pinning explicitly.
    """
    secret = tmp_path / "secret.md"
    secret.write_text("exfiltrate me\n")
    (vault / "reference" / "link.md").symlink_to(secret)

    with pytest.raises(VaultAccessError):
        resolve_note("reference/link.md", vault)


def test_rejects_excluded_directory(vault: Path) -> None:
    """`.claude/` is not graph content — settings must be unreachable."""
    with pytest.raises(VaultAccessError):
        resolve_note(".claude/settings.json", vault)


def test_rejects_dotfile_at_vault_root(vault: Path) -> None:
    """`.env` sits inside the vault but is not a note; it must be refused."""
    with pytest.raises(VaultAccessError):
        resolve_note(".env", vault)


def test_rejects_non_markdown_inside_a_graph_dir(vault: Path) -> None:
    """Living under reference/ is not sufficient — it must be a note."""
    with pytest.raises(VaultAccessError):
        resolve_note("reference/data.csv", vault)


def test_rejects_missing_note(vault: Path) -> None:
    with pytest.raises(VaultAccessError):
        resolve_note("reference/nope.md", vault)


# ---------------------------------------------------------------------------
# read_note
# ---------------------------------------------------------------------------


def test_read_note_returns_contents(vault: Path) -> None:
    assert read_note("reference/alpha.md", vault) == "# Alpha\n\nbody text\n"


def test_read_note_refuses_what_resolve_refuses(vault: Path) -> None:
    """read_note must not have a second, weaker path check."""
    with pytest.raises(VaultAccessError):
        read_note(".claude/settings.json", vault)


# ---------------------------------------------------------------------------
# search_notes
# ---------------------------------------------------------------------------


def test_search_delegates_to_the_injected_fn() -> None:
    calls: list[tuple[str, int]] = []

    def fake_search(query: str, k: int = 8) -> list[dict]:
        calls.append((query, k))
        return [{"note_path": "reference/alpha.md", "score": 0.9, "snippet": "x"}]

    results = search_notes("alpha", 3, search_fn=fake_search)

    assert calls == [("alpha", 3)]
    assert results[0]["note_path"] == "reference/alpha.md"


def test_search_clamps_k_to_the_cap() -> None:
    """An unbounded k would let one call haul the whole index over MCP."""
    seen: list[int] = []

    def fake_search(query: str, k: int = 8) -> list[dict]:
        seen.append(k)
        return []

    search_notes("alpha", 10_000, search_fn=fake_search)

    assert seen == [MAX_RESULTS]


def test_search_rejects_nonpositive_k() -> None:
    def fake_search(query: str, k: int = 8) -> list[dict]:  # pragma: no cover
        raise AssertionError("must not be called")

    with pytest.raises(ValueError):
        search_notes("alpha", 0, search_fn=fake_search)


def test_search_rejects_blank_query() -> None:
    def fake_search(query: str, k: int = 8) -> list[dict]:  # pragma: no cover
        raise AssertionError("must not be called")

    with pytest.raises(ValueError):
        search_notes("   ", 5, search_fn=fake_search)
