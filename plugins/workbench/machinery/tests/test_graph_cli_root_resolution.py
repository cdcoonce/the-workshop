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


def test_claude_md_alone_is_not_a_vault(tmp_path, monkeypatch, capsys):
    (tmp_path / "CLAUDE.md").write_text("# not a vault")
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.chdir(tmp_path)

    assert gc.main([]) == 1
    assert "vault root not found" in capsys.readouterr().err


def test_claude_project_dir_without_signature_is_not_a_vault(tmp_path, monkeypatch, capsys):
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
    import json

    import numpy as np

    (tmp_path / "CLAUDE.md").write_text("# vault")
    (tmp_path / "brain").mkdir()
    (tmp_path / "perf").mkdir()
    (tmp_path / ".vault").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".vault" / "vault.json").write_text('{"vault": "test"}\n')
    index_dir = tmp_path / ".claude" / "data" / "semantic"
    index_dir.mkdir(parents=True)
    np.save(
        str(index_dir / "vectors.npy"),
        np.array([[1.0, 0.0], [0.9, 0.1]], dtype=np.float32),
    )
    (index_dir / "meta.json").write_text(
        json.dumps(
            [
                {"note_path": "brain/a.md", "snippet": ""},
                {"note_path": "brain/b.md", "snippet": ""},
            ]
        )
    )
    (index_dir / "manifest.json").write_text("{}")
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
