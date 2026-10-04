"""graph_cli previously carried a private ``find_vault_root()`` that trusted
``CLAUDE_PROJECT_DIR`` unvalidated and matched on ``CLAUDE.md`` alone —
bypassing the ``brain/`` + ``perf/`` signature check ``vault_utils.find_vault_root``
enforces (see its docstring: a project repo carrying its own ``CLAUDE.md`` must
not resolve as the vault). ``graph_cli`` now delegates entirely to
``vault_utils.find_vault_root_from_env()`` at its ``main()`` call site.

These tests drive ``main()`` itself, not ``vault_utils`` in isolation, so a
regression that reintroduces the private walk-up (and rewires the call site
back to it) turns them red rather than passing vacuously.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

graphmark = pytest.importorskip("graphmark")

ENGINE = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(ENGINE))

_spec = importlib.util.spec_from_file_location("graph_cli", ENGINE / "graph_cli.py")
gc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gc)


@pytest.fixture(autouse=True)
def metadata_only_embedder(monkeypatch):
    import ragmark.embed
    from ragmark.model import ModelIdentity

    class MetadataOnly:
        def identity(self):
            return ModelIdentity("fixture", 2, "1")

        def embed(self, texts):
            pytest.fail("graph similarity must not embed")

        def count_tokens(self, text):
            pytest.fail("graph similarity must not load a tokenizer")

    monkeypatch.setattr(ragmark.embed, "FastembedEmbedder", MetadataOnly)


def test_claude_md_alone_is_not_a_vault(tmp_path, monkeypatch, capsys):
    (tmp_path / "CLAUDE.md").write_text("# not a vault")
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.chdir(tmp_path)

    assert gc.main([]) == 1
    assert "vault root not found" in capsys.readouterr().err


def test_claude_project_dir_without_signature_is_not_a_vault(
    tmp_path, monkeypatch, capsys
):
    (tmp_path / "CLAUDE.md").write_text("# not a vault")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))

    assert gc.main([]) == 1
    assert "vault root not found" in capsys.readouterr().err


def test_full_signature_resolves_and_runs(tmp_path, monkeypatch):
    (tmp_path / "CLAUDE.md").write_text("# vault")
    (tmp_path / "brain").mkdir()
    (tmp_path / "perf").mkdir()
    (tmp_path / ".vault").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".vault" / "vault.json").write_text('{"vault": "test"}\n')
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.chdir(tmp_path)

    assert gc.main([]) == 0


# ---------------------------------------------------------------------------
# vector_similar_fn — the similarity source must honor the resolved root
# (issue #677: it accepted vault_root and ignored it, reading semantic_index's
# module-level paths instead, so a wrong root degraded silently to no-op)
# ---------------------------------------------------------------------------


def _make_vault_with_index(tmp_path: Path) -> Path:
    import hashlib
    import numpy as np
    from ragmark.model import Chunk, ModelIdentity
    from ragmark.store import IndexStore

    (tmp_path / "CLAUDE.md").write_text("# vault")
    (tmp_path / "brain").mkdir()
    (tmp_path / "perf").mkdir()
    (tmp_path / ".vault").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".vault" / "vault.json").write_text('{"vault": "test"}\n')
    store = IndexStore(tmp_path / ".ragmark")
    conn = store.connect()
    store.write_identity(conn, ModelIdentity("fixture", 2, "1"))
    for name in ("a", "b"):
        rel = f"brain/{name}.md"
        path = tmp_path / rel
        path.write_text(f"# {name}\n")
        store.write_note(
            conn,
            rel,
            hashlib.sha256(path.read_bytes()).hexdigest(),
            path.stat().st_mtime_ns,
        )
        store.replace_chunks(
            conn, rel, [Chunk(f"{rel}#0", rel, 0, None, None, name, 1)]
        )
    store.assign_vector_rows(conn, {"brain/a.md#0": 0, "brain/b.md#0": 1})
    store.save_vectors(np.array([[1.0, 0.0], [0.9, 0.1]], dtype=np.float32))
    conn.close()
    return tmp_path


def test_vector_similar_fn_reads_the_index_under_vault_root(tmp_path):
    np = pytest.importorskip("numpy")  # noqa: F841
    vault = _make_vault_with_index(tmp_path)

    fn = gc.vector_similar_fn(vault)
    hits = fn("brain/a.md", 1)

    assert hits, "seeded index under vault_root must be visible"
    assert hits[0][0] == "brain/b.md"


def test_vector_similar_fn_missing_index_is_loud(tmp_path, capsys):
    pytest.importorskip("numpy")
    (tmp_path / "CLAUDE.md").write_text("# vault")
    (tmp_path / "brain").mkdir()
    (tmp_path / "perf").mkdir()
    (tmp_path / ".vault").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".vault" / "vault.json").write_text('{"vault": "test"}\n')

    fn = gc.vector_similar_fn(tmp_path)

    assert fn("brain/a.md", 3) == []
    err = capsys.readouterr().err
    assert "semantic index" in err and "reindex" in err
    assert not (tmp_path / ".ragmark").exists()


def test_vector_similar_fn_uses_public_ragmark_api(tmp_path, monkeypatch):
    from ragmark import search

    vault = _make_vault_with_index(tmp_path)
    calls = []

    def similar(note_path, k, *, config, store):
        calls.append((note_path, k, config.vault_root, store.index_dir))
        return [("brain/b.md", 0.75)]

    monkeypatch.setattr(search, "similar_notes", similar)
    assert gc.vector_similar_fn(vault)("brain/a.md", 3) == [("brain/b.md", 0.75)]
    assert calls == [("brain/a.md", 3, vault, vault / ".ragmark")]


def test_vector_similar_fn_refuses_gated_or_missing_origin(tmp_path):
    vault = _make_vault_with_index(tmp_path)
    (vault / "personal").mkdir()
    (vault / "personal/private.md").write_text("private")
    (vault / ".vault-context").write_text("work")
    similar = gc.vector_similar_fn(vault)
    assert similar("personal/private.md", 2) == []
    assert similar("brain/missing.md", 2) == []


def test_vector_similarity_refuses_empty_database_without_repairing_it(tmp_path):
    import numpy as np
    from ragmark.store import IndexCorruptionError

    (tmp_path / "brain").mkdir()
    (tmp_path / "brain/a.md").write_text("# A\n")
    index_dir = tmp_path / ".ragmark"
    index_dir.mkdir()
    database = index_dir / "ragmark.db"
    database.write_bytes(b"")
    np.save(index_dir / "vectors.npy", np.array([[1.0, 0.0]], dtype=np.float32))
    before = {path.name: path.read_bytes() for path in index_dir.iterdir()}

    with pytest.raises(IndexCorruptionError):
        gc.vector_similar_fn(tmp_path)("brain/a.md", 3)

    assert {path.name: path.read_bytes() for path in index_dir.iterdir()} == before


def test_vector_similarity_refuses_chunk_vector_count_mismatch(tmp_path):
    import numpy as np
    from ragmark.store import IndexCorruptionError

    vault = _make_vault_with_index(tmp_path)
    np.save(vault / ".ragmark/vectors.npy", np.array([[1.0, 0.0]], dtype=np.float32))

    with pytest.raises(IndexCorruptionError, match="vector"):
        gc.vector_similar_fn(vault)("brain/a.md", 3)


def test_vector_similarity_refuses_index_changed_after_preflight(tmp_path):
    import numpy as np
    from ragmark.store import IndexCorruptionError

    vault = _make_vault_with_index(tmp_path)
    similar = gc.vector_similar_fn(vault)
    np.save(vault / ".ragmark/vectors.npy", np.array([[1.0, 0.0]], dtype=np.float32))

    with pytest.raises(IndexCorruptionError, match="changed"):
        similar("brain/a.md", 3)


def test_stale_cosine_reader_changes_no_index_files(tmp_path):
    vault = _make_vault_with_index(tmp_path)
    (vault / "brain/a.md").write_text("# Changed after indexing\n")
    index_dir = vault / ".ragmark"
    before = {
        path.name: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in index_dir.iterdir()
    }

    hits = gc.vector_similar_fn(vault)("brain/a.md", 3)

    assert hits == [("brain/b.md", pytest.approx(0.9 / (0.9**2 + 0.1**2) ** 0.5))]
    assert {
        path.name: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in index_dir.iterdir()
    } == before


def test_delegated_core_receives_a_query_only_connection(tmp_path, monkeypatch):
    import sqlite3
    from ragmark import search

    vault = _make_vault_with_index(tmp_path)

    def attempt_write(note_path, k, *, config, store):
        conn = store.connect()
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("DELETE FROM chunks")
        return [("brain/b.md", 0.75)]

    monkeypatch.setattr(search, "similar_notes", attempt_write)
    assert gc.vector_similar_fn(vault)("brain/a.md", 3) == [("brain/b.md", 0.75)]
