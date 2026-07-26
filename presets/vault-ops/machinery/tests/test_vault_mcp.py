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
    active_context,
    note_context,
    read_note,
    resolve_note,
    search_notes,
    visible_in_context,
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


def test_search_delegates_to_the_injected_fn(vault: Path) -> None:
    calls: list[tuple[str, int]] = []

    def fake_search(query: str, k: int = 8) -> list[dict]:
        calls.append((query, k))
        return [{"note_path": "reference/alpha.md", "score": 0.9, "snippet": "x"}]

    results = search_notes("alpha", 3, search_fn=fake_search, vault_root=vault)

    assert [q for q, _ in calls] == ["alpha"]
    assert results[0]["note_path"] == "reference/alpha.md"


def test_search_caps_returned_results(vault: Path) -> None:
    """An unbounded k would let one call haul the whole index over MCP.

    Asserted on what the caller receives rather than on the internal fetch
    size, so the over-fetch factor stays an implementation detail.
    """

    def fake_search(query: str, k: int = 8) -> list[dict]:
        return [
            {"note_path": f"reference/n{i}.md", "score": 0.5, "snippet": ""}
            for i in range(k)
        ]

    results = search_notes("alpha", 10_000, search_fn=fake_search, vault_root=vault)

    assert len(results) == MAX_RESULTS


def test_search_rejects_nonpositive_k(vault: Path) -> None:
    def fake_search(query: str, k: int = 8) -> list[dict]:  # pragma: no cover
        raise AssertionError("must not be called")

    with pytest.raises(ValueError):
        search_notes("alpha", 0, search_fn=fake_search, vault_root=vault)


def test_search_rejects_blank_query(vault: Path) -> None:
    def fake_search(query: str, k: int = 8) -> list[dict]:  # pragma: no cover
        raise AssertionError("must not be called")

    with pytest.raises(ValueError):
        search_notes("   ", 5, search_fn=fake_search, vault_root=vault)


# ---------------------------------------------------------------------------
# Context scoping
# ---------------------------------------------------------------------------


@pytest.fixture
def scoped_vault(tmp_path: Path) -> Path:
    """A vault holding one note in each of the three scopes."""
    root = tmp_path / "vault"
    for folder in ("work", "personal", "reference"):
        (root / folder).mkdir(parents=True)
    (root / "work" / "roadmap.md").write_text("# Roadmap\n")
    (root / "personal" / "diary.md").write_text("# Diary\n")
    (root / "reference" / "shared.md").write_text("# Shared\n")
    return root


class TestNoteContext:
    """Which context owns a note is decided by its top-level directory."""

    def test_work_dir_is_work_scoped(self) -> None:
        assert note_context("work/roadmap.md") == "work"

    def test_personal_dir_is_personal_scoped(self) -> None:
        assert note_context("personal/diary.md") == "personal"

    def test_everything_else_is_shared(self) -> None:
        """brain/, reference/, org/, perf/, thinking/ belong to both machines."""
        for rel in (
            "reference/shared.md",
            "brain/Patterns.md",
            "org/people/x.md",
            "perf/review.md",
            "thinking/idea.md",
        ):
            assert note_context(rel) is None, rel


class TestVisibleInContext:
    def test_matching_context_sees_its_own_notes(self) -> None:
        assert visible_in_context("work/roadmap.md", "work")
        assert visible_in_context("personal/diary.md", "personal")

    def test_work_machine_never_surfaces_personal_notes(self) -> None:
        """The exposure that matters: personal material on an employer machine."""
        assert not visible_in_context("personal/diary.md", "work")

    def test_personal_machine_also_sees_work_notes(self) -> None:
        """Deliberately asymmetric.

        The vault is one repo synced to both machines, so work/ notes are
        already on the personal machine's disk. Hiding them from search would
        cost reach without protecting anything.
        """
        assert visible_in_context("work/roadmap.md", "personal")

    def test_shared_notes_are_visible_everywhere(self) -> None:
        for ctx in ("work", "personal", "unknown"):
            assert visible_in_context("reference/shared.md", ctx), ctx

    def test_unknown_context_sees_only_shared(self) -> None:
        """Fail closed: an unidentified machine gets the intersection, not the union.

        `read_vault_context` returns "unknown" when the marker is missing, which
        is precisely when we know least about where we are running.
        """
        assert not visible_in_context("work/roadmap.md", "unknown")
        assert not visible_in_context("personal/diary.md", "unknown")


class TestActiveContextIsServerSide:
    """Context is read from the vault the server is rooted at, never from the caller.

    A caller-supplied context would be trivially spoofable — the remote agent
    is the untrusted party here, so it must not get a vote.
    """

    def test_reads_the_marker_from_the_vault(self, scoped_vault: Path) -> None:
        (scoped_vault / ".vault-context").write_text("work\n")

        assert active_context(scoped_vault) == "work"

    def test_missing_marker_is_unknown(self, scoped_vault: Path) -> None:
        assert active_context(scoped_vault) == "unknown"


class TestResolveNoteHonorsContext:
    def test_refuses_a_note_from_the_other_context(self, scoped_vault: Path) -> None:
        (scoped_vault / ".vault-context").write_text("work\n")

        with pytest.raises(VaultAccessError):
            resolve_note("personal/diary.md", scoped_vault)

    def test_allows_a_note_from_the_active_context(self, scoped_vault: Path) -> None:
        (scoped_vault / ".vault-context").write_text("work\n")

        assert resolve_note("work/roadmap.md", scoped_vault).name == "roadmap.md"

    def test_allows_shared_notes(self, scoped_vault: Path) -> None:
        (scoped_vault / ".vault-context").write_text("work\n")

        assert resolve_note("reference/shared.md", scoped_vault).name == "shared.md"

    def test_read_note_inherits_the_same_refusal(self, scoped_vault: Path) -> None:
        (scoped_vault / ".vault-context").write_text("work\n")

        with pytest.raises(VaultAccessError):
            read_note("personal/diary.md", scoped_vault)


class TestSearchHonorsContext:
    def test_filters_out_of_context_hits(self, scoped_vault: Path) -> None:
        (scoped_vault / ".vault-context").write_text("work\n")

        def fake_search(query: str, k: int = 8) -> list[dict]:
            return [
                {"note_path": "personal/diary.md", "score": 0.99, "snippet": ""},
                {"note_path": "work/roadmap.md", "score": 0.80, "snippet": ""},
                {"note_path": "reference/shared.md", "score": 0.70, "snippet": ""},
            ]

        hits = search_notes("x", 5, search_fn=fake_search, vault_root=scoped_vault)

        assert [h["note_path"] for h in hits] == [
            "work/roadmap.md",
            "reference/shared.md",
        ]

    def test_overfetches_so_filtering_does_not_starve_results(
        self, scoped_vault: Path
    ) -> None:
        """Filtering AFTER a k-truncated search would silently return too few.

        If the top k hits are all out-of-context, a naive implementation returns
        an empty list even though in-context matches exist further down. The
        server must ask the index for more than k and truncate after filtering.
        """
        (scoped_vault / ".vault-context").write_text("work\n")
        asked: list[int] = []

        def fake_search(query: str, k: int = 8) -> list[dict]:
            asked.append(k)
            noise = [
                {"note_path": f"personal/n{i}.md", "score": 0.9, "snippet": ""}
                for i in range(10)
            ]
            wanted = [
                {"note_path": f"work/w{i}.md", "score": 0.5, "snippet": ""}
                for i in range(3)
            ]
            return noise + wanted

        hits = search_notes("x", 3, search_fn=fake_search, vault_root=scoped_vault)

        assert asked and asked[0] > 3, "must over-fetch beyond the requested k"
        assert len(hits) == 3
        assert all(h["note_path"].startswith("work/") for h in hits)

    def test_still_truncates_to_k_after_filtering(self, scoped_vault: Path) -> None:
        (scoped_vault / ".vault-context").write_text("work\n")

        def fake_search(query: str, k: int = 8) -> list[dict]:
            return [
                {"note_path": f"work/w{i}.md", "score": 0.5, "snippet": ""}
                for i in range(20)
            ]

        assert len(search_notes("x", 4, search_fn=fake_search, vault_root=scoped_vault)) == 4
