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
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.chdir(tmp_path)

    assert gc.main([]) == 0
