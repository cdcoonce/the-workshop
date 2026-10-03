"""Actual Workshop shims over ragmark, with fixture notes and a stub model only."""

from pathlib import Path

import numpy as np
import pytest

from ragmark.embed import Embedder
from ragmark.model import ModelIdentity

import semantic_index


class StubEmbedder(Embedder):
    def identity(self) -> ModelIdentity:
        return ModelIdentity("fixture", 2, "1")

    def count_tokens(self, text: str) -> int:
        return max(1, len(text.split()))

    def embed(self, texts) -> np.ndarray:
        return np.array([[1.0, 0.5] for _ in texts], dtype=np.float32)


@pytest.fixture(autouse=True)
def stub_embedder(monkeypatch):
    import ragmark.embed
    import ragmark.mcp

    monkeypatch.setattr(ragmark.embed, "FastembedEmbedder", StubEmbedder)
    monkeypatch.setattr(ragmark.mcp, "FastembedEmbedder", StubEmbedder)


def write_note(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_search_refreshes_real_fixture_index_and_preserves_low_fused_scores(
    tmp_path,
) -> None:
    write_note(tmp_path, "reference/a.md", "# Alpha\n\nUnique alpha phrase.\n")

    results = semantic_index.search("alpha", vault_root=tmp_path)

    assert results[0]["note_path"] == "reference/a.md"
    assert set(results[0]) == {"note_path", "score", "snippet"}
    assert 0 < results[0]["score"] < 0.2
    assert (tmp_path / ".ragmark" / "ragmark.db").exists()
    assert not (tmp_path / ".claude" / "data" / "semantic").exists()


def test_status_reports_added_changed_deleted_without_refreshing(tmp_path) -> None:
    changed = write_note(tmp_path, "reference/changed.md", "# Before\n")
    deleted = write_note(tmp_path, "reference/deleted.md", "# Deleted\n")
    semantic_index.search("before", vault_root=tmp_path)
    changed.write_text("# After\n")
    deleted.unlink()
    write_note(tmp_path, "reference/added.md", "# Added\n")
    index_files = list((tmp_path / ".ragmark").iterdir())
    before = {
        path: (path.read_bytes(), path.stat().st_mtime_ns) for path in index_files
    }

    report = semantic_index.status(tmp_path)

    assert report["state"] == "stale"
    assert report["ready"] is False
    assert (
        report["added_notes"],
        report["changed_notes"],
        report["deleted_notes"],
    ) == (1, 1, 1)
    assert report["stale_notes"] == 3
    assert report["index_built_at"] is None
    assert report["root_provenance"] == "not_recorded"
    assert {
        path: (path.read_bytes(), path.stat().st_mtime_ns) for path in index_files
    } == before


def test_build_stats_report_actual_changes_removals_and_parse_defects(
    tmp_path, monkeypatch
) -> None:
    # The predecessor must also remain model-free during this regression's red run.
    monkeypatch.setattr(semantic_index, "embed_texts", StubEmbedder().embed)
    removed = write_note(tmp_path, "reference/removed.md", "# Remove\n")
    changed = write_note(tmp_path, "reference/changed.md", "# Before\n")
    write_note(tmp_path, "reference/kept.md", "# Keep\n")
    semantic_index.build_index(tmp_path)
    removed.unlink()
    changed.write_text("# After\n")
    write_note(tmp_path, "reference/added.md", "---\ntags: [broken\n---\n# Added\n")

    report = semantic_index.build_index(tmp_path)

    assert (report["indexed"], report["skipped"], report["removed"]) == (2, 1, 1)
    assert len(report["defects"]) == 1
    assert "reference/added.md" in report["defects"][0]
    # Malformed frontmatter is retained as a separate chunk, not discarded.
    assert report["total_chunks"] == 4
    assert report["elapsed"] >= 0
    assert semantic_index.status(tmp_path)["ready"] is True


def test_chunk_helper_keeps_dict_shape_and_uses_real_yaml(tmp_path) -> None:
    raw = "---\ndescription: |\n  First line\n  Second line\n---\n# Heading\n\nBody.\n"

    chunks = semantic_index.chunk_note(tmp_path / "reference/a.md", raw, tmp_path)

    assert chunks[0]["text"].splitlines() == ["First line", "Second line"]
    assert all(set(chunk) == {"text", "snippet", "note_path"} for chunk in chunks)
    assert all(chunk["note_path"] == "reference/a.md" for chunk in chunks)


def test_actual_mcp_shim_exposes_packaged_four_tool_contract(tmp_path) -> None:
    import asyncio

    from fastmcp import Client
    import vault_mcp

    expected = {
        "vault_search": {"query", "k"},
        "vault_read": {"path"},
        "vault_neighbors": {"path", "depth", "token_budget"},
        "recent_activity": {"days", "limit"},
    }
    server = vault_mcp.build_server(tmp_path)

    async def list_tools():
        async with Client(server) as client:
            return await client.list_tools()

    tools = {tool.name: tool for tool in asyncio.run(list_tools())}
    assert server.name == "vault"
    assert set(tools) == set(expected)
    for name, tool in tools.items():
        assert set(tool.inputSchema["properties"]) == expected[name]
        assert tool.annotations.readOnlyHint is True
        assert tool.annotations.destructiveHint is False
        assert tool.annotations.idempotentHint is True
        assert tool.annotations.openWorldHint is False


def test_legacy_read_helper_uses_explicit_owner_scope(tmp_path, owner_scope) -> None:
    import vault_mcp

    owner_scope(GRAPH_NOTE_DIRS=("ambient",))
    target = tmp_path / "target"
    write_note(
        target, ".vault/config/vault_scope.py", "OPERATING_FILENAMES = {'manual.md'}\n"
    )
    write_note(target, "reference/manual.md", "owner-excluded content")

    with pytest.raises(vault_mcp.VaultAccessError):
        vault_mcp.read_note("reference/manual.md", target)


def test_actual_shims_share_owner_scope_and_machine_context(
    tmp_path, owner_scope
) -> None:
    import asyncio

    from fastmcp import Client
    import vault_mcp

    owner_scope(GRAPH_NOTE_DIRS=("ambient",))
    root = tmp_path / "target"
    write_note(
        root,
        ".vault/config/vault_scope.py",
        "GRAPH_NOTE_DIRS = ('reference', 'work', 'personal', 'school')\n"
        "TRANSIENT_PREFIXES = ('reference/transient', 'personal/tasks/')\n",
    )
    write_note(root, ".vault-context", "work\n")
    expected = {
        "reference/shared.md",
        "reference/README.md",
        "work/job.md",
        "school/course.md",
    }
    hidden = {
        "personal/diary.md",
        "personal/tasks/week.md",
        "reference/AGENTS.md",
        "reference/transient.md",
        "docs/omitted.md",
        "root-note.md",
    }
    for rel in expected | hidden:
        write_note(root, rel, f"# Fixture\n\nTopic content for {rel}\n")

    assert {
        hit["note_path"] for hit in semantic_index.search("topic", vault_root=root)
    } == expected

    async def use_tools():
        async with Client(vault_mcp.build_server(root)) as client:
            found = await client.call_tool("vault_search", {"query": "topic"})
            read = await client.call_tool("vault_read", {"path": "school/course.md"})
            for rel in hidden:
                with pytest.raises(Exception, match="not available"):
                    await client.call_tool("vault_read", {"path": rel})
            return found.structured_content["result"], read.structured_content["result"]

    hits, body = asyncio.run(use_tools())
    assert {hit["note_path"] for hit in hits} == expected
    assert all(
        set(hit) == {"chunk_id", "note_path", "heading", "score", "snippet"}
        for hit in hits
    )
    assert "school/course.md" in body
    (root / ".vault-context").unlink()
    assert {
        hit["note_path"] for hit in semantic_index.search("topic", vault_root=root)
    } == (expected - {"work/job.md"})


def test_query_refreshes_edits_additions_and_deletions_without_explicit_reindex(
    tmp_path,
) -> None:
    changed = write_note(tmp_path, "reference/changed.md", "# Old topic\n")
    deleted = write_note(tmp_path, "reference/deleted.md", "# Old topic\n")
    semantic_index.search("topic", vault_root=tmp_path)
    changed.write_text("# Fresh topic\n")
    deleted.unlink()
    write_note(tmp_path, "reference/new.md", "# Fresh topic\n")

    hits = semantic_index.search("fresh", vault_root=tmp_path)

    assert {hit["note_path"] for hit in hits} == {
        "reference/changed.md",
        "reference/new.md",
    }
    assert all("Fresh" in hit["snippet"] for hit in hits)
    assert semantic_index.status(tmp_path)["state"] == "ready"


def test_missing_status_creates_nothing_and_cli_errors_stay_json(
    tmp_path, monkeypatch, capsys
) -> None:
    import json

    root = tmp_path / "empty"
    root.mkdir()
    assert semantic_index.status(root)["state"] == "missing"
    assert list(root.iterdir()) == []

    write_note(root, ".vault/vault.json", "{}")
    write_note(
        root, ".vault/config/vault_scope.py", "raise RuntimeError('broken scope')"
    )
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    with pytest.raises(SystemExit) as error:
        semantic_index.main(["status"])
    assert error.value.code == 1
    report = json.loads(capsys.readouterr().out)
    assert "vault scope could not load" in report["error"]
    assert report["remediation"]
    assert not (root / ".ragmark").exists()


def test_search_calls_core_once_at_its_chunk_cap_then_presents_notes(
    tmp_path, monkeypatch
) -> None:
    from ragmark import search
    from ragmark.model import SearchHit

    calls = []

    def core_search(query, k, *, config, store, embedder):
        calls.append((query, k, config.vault_root, store.index_dir))
        return [
            SearchHit("reference/a.md#2", "reference/a.md", None, 0.03, "First"),
            SearchHit("reference/a.md#0", "reference/a.md", None, 0.02, "Duplicate"),
            SearchHit("reference/b.md#0", "reference/b.md", None, 0.01, "Second"),
        ]

    monkeypatch.setattr(search, "search", core_search)
    hits = semantic_index.search("fixture", 2, vault_root=tmp_path)

    assert calls == [
        ("fixture", search.MAX_RESULTS, tmp_path.resolve(), tmp_path / ".ragmark")
    ]
    assert hits == [
        {"note_path": "reference/a.md", "score": 0.03, "snippet": "First"},
        {"note_path": "reference/b.md", "score": 0.01, "snippet": "Second"},
    ]
