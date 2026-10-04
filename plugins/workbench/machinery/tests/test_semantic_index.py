"""Legacy helper shapes over ragmark; core parsing/chunk/store tests live upstream.

The retired private parser, packing, NumPy I/O, and temporary-cache tests are
mapped to their authoritative core suites in docs/plans/2026-10-03-ragmark-shims.md.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest

import semantic_index
from test_ragmark_shims import StubEmbedder


@pytest.fixture(autouse=True)
def stub_embedder(monkeypatch) -> None:
    import ragmark.embed

    monkeypatch.setattr(ragmark.embed, "FastembedEmbedder", StubEmbedder)


def test_chunk_note_retains_legacy_keys_and_relative_path(tmp_path: Path) -> None:
    chunks = semantic_index.chunk_note(
        tmp_path / "reference/a.md", "# Heading\nBody", tmp_path
    )

    assert chunks == [
        {
            "text": "Heading\nBody",
            "snippet": "Heading Body",
            "note_path": "reference/a.md",
        }
    ]


def test_helper_snippet_is_short_while_full_text_remains(tmp_path: Path) -> None:
    text = "word " * 90
    chunks = semantic_index.chunk_note(tmp_path / "reference/a.md", text, tmp_path)

    assert "".join(chunk["text"] for chunk in chunks) == text
    assert all(len(chunk["snippet"]) <= semantic_index.SNIPPET_LEN for chunk in chunks)


def test_empty_helper_input_follows_core_without_fabricating_note_text(
    tmp_path: Path,
) -> None:
    assert semantic_index.chunk_note(tmp_path / "reference/a.md", "", tmp_path) == []


def test_file_hash_uses_raw_bytes(tmp_path: Path) -> None:
    path = tmp_path / "bytes.md"
    path.write_bytes(b"A\r\nB\n")
    assert semantic_index.file_hash(path) == hashlib.sha256(b"A\r\nB\n").hexdigest()


def test_embed_texts_delegates_to_core_embedder() -> None:
    vectors = semantic_index.embed_texts(["first", "second"])
    np.testing.assert_array_equal(
        vectors, np.array([[1.0, 0.5], [1.0, 0.5]], dtype=np.float32)
    )


def test_iter_vault_notes_uses_explicit_owner_policy(tmp_path: Path) -> None:
    config = tmp_path / ".vault" / "config"
    config.mkdir(parents=True)
    (config / "vault_scope.py").write_text("GRAPH_NOTE_DIRS = ('custom',)\n")
    for rel in ("custom/kept.md", "reference/omitted.md", "custom/AGENTS.md"):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Fixture\n")

    assert semantic_index.iter_vault_notes(tmp_path) == [tmp_path / "custom/kept.md"]


def test_search_root_remains_keyword_only(tmp_path: Path) -> None:
    with pytest.raises(TypeError):
        semantic_index.search("query", 3, tmp_path)
