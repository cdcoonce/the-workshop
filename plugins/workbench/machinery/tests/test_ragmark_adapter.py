"""Explicit-root owner policy at the Workshop/ragmark boundary."""

from pathlib import Path
import sys

import pytest

import vault_scope_resolved


def write_scope(root: Path, source: str) -> None:
    config = root / ".vault" / "config"
    config.mkdir(parents=True)
    (root / ".vault" / "vault.json").write_text("{}")
    (config / "vault_scope.py").write_text(source)


def test_explicit_scope_ignores_ambient_root_and_cache(tmp_path, owner_scope) -> None:
    first = owner_scope(GRAPH_NOTE_DIRS=("alpha",))
    second = tmp_path / "second"
    write_scope(second, "GRAPH_NOTE_DIRS = ('beta',)\n")
    assert vault_scope_resolved.GRAPH_NOTE_DIRS == ("alpha",)
    cached_owner = sys.modules.get("vault_scope")

    assert vault_scope_resolved.for_vault(second).GRAPH_NOTE_DIRS == ("beta",)
    assert vault_scope_resolved.for_vault(first).GRAPH_NOTE_DIRS == ("alpha",)
    assert vault_scope_resolved.GRAPH_NOTE_DIRS == ("alpha",)
    assert sys.modules.get("vault_scope") is cached_owner


def test_explicit_scope_keeps_defaults_for_absent_names(tmp_path) -> None:
    import vault_scope_defaults

    write_scope(tmp_path, "GRAPH_NOTE_DIRS = ('custom',)\n")
    policy = vault_scope_resolved.for_vault(tmp_path)

    assert policy.GRAPH_NOTE_DIRS == ("custom",)
    assert policy.OPERATING_FILENAMES == vault_scope_defaults.OPERATING_FILENAMES


@pytest.mark.parametrize(
    "source", ["raise RuntimeError('broken')", "this is invalid python !"]
)
def test_explicit_scope_refuses_broken_owner_config(tmp_path, source) -> None:
    write_scope(tmp_path, source)
    with pytest.raises(RuntimeError, match="vault scope could not load"):
        vault_scope_resolved.for_vault(tmp_path)


def test_config_uses_explicit_root_and_owner_scope(tmp_path, owner_scope) -> None:
    from ragmark_adapter import config_for_vault

    owner_scope(GRAPH_NOTE_DIRS=("ambient",))
    root = tmp_path / "target"
    write_scope(
        root,
        "GRAPH_NOTE_DIRS = ('school', 'reference')\n"
        "GRAPH_EXCLUDED_DIRS = {'private'}\n"
        "OPERATING_FILENAMES = {'AGENTS.md', 'manual.md'}\n"
        "TRANSIENT_PREFIXES = ('school/drafts/',)\n",
    )

    config = config_for_vault(root)

    assert config.vault_root == root.resolve()
    assert config.index_dir == root.resolve() / ".ragmark"
    assert config.scoped_folders == frozenset({"school", "reference"})
    assert config.excluded_dirs == frozenset({"private"})
    assert config.excluded_filenames == frozenset({"AGENTS.md", "manual.md"})
    assert config.excluded_path_prefixes == ("school/drafts/",)


def test_old_ragmark_without_scope_fields_fails_closed(tmp_path, monkeypatch) -> None:
    from dataclasses import make_dataclass

    import ragmark.config
    from ragmark_adapter import config_for_vault

    old_config = make_dataclass(
        "OldConfig", [("vault_root", Path), ("index_dir", Path)]
    )
    monkeypatch.setattr(ragmark.config, "RagmarkConfig", old_config)

    with pytest.raises(RuntimeError, match="coordinated ragmark"):
        config_for_vault(tmp_path)


@pytest.mark.parametrize(
    "source", ["GRAPH_NOTE_DIRS = ()\n", "GRAPH_EXCLUDED_DIRS = 'private'\n"]
)
def test_unrepresentable_policy_never_becomes_broad_scope(tmp_path, source) -> None:
    from ragmark_adapter import config_for_vault

    write_scope(tmp_path, source)
    with pytest.raises(ValueError, match="scope"):
        config_for_vault(tmp_path)
