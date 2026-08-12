"""Shared fixtures for the vault machinery suite.

The owner-scope fixtures here exist because of #691. Tests used to install an
owner's ``vault_scope`` by writing a module object into ``sys.modules`` and
letting the resolver's bare ``import vault_scope`` pick it up. That exercised a
lookup production never performed: in a real vault the engine directory sits
ahead of the owner's config directory on ``sys.path``, so the name always
resolved to the engine's own copy and every override was silently discarded.
The tests passed the whole time, because their input could not tell the two
outcomes apart.

So these fixtures install a real file in a real vault and let the resolver find
it the way it does in production — by anchoring on the vault root.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ENGINE_DIR = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(ENGINE_DIR))


def _clear_owner_scope_cache() -> None:
    """Reset the resolver's cache if it has one, without requiring that it does.

    Deliberately tolerant. If this reached into the resolver unconditionally, a
    resolver that had lost its vault-root anchoring would blow up every test in
    this suite with a fixture error about a missing attribute — nine red
    ERRORs that say nothing about scope resolution. Degrading here instead
    means the assertions run and fail on what they actually assert, which is
    the difference between a detector and a tripwire.
    """
    import vault_scope_resolved

    unset = getattr(vault_scope_resolved, "_UNSET", None)
    if unset is not None and hasattr(vault_scope_resolved, "_owner_config"):
        vault_scope_resolved._owner_config = unset


@pytest.fixture(autouse=True)
def _reset_owner_scope_cache():
    """Drop the resolver's owner-config cache around every test.

    The resolver caches per process so that attribute access does not re-stat
    and re-execute the owner's file on every lookup. Tests share a process, so
    without this a vault installed by one test would leak into the next.
    Reset on both sides: a test that never touches scope still must not inherit
    a cached module from the one before it.
    """
    _clear_owner_scope_cache()
    yield
    _clear_owner_scope_cache()


@pytest.fixture
def owner_scope(monkeypatch, tmp_path):
    """Install a real owner ``vault_scope.py`` in a real vault.

    Writes ``<vault>/.vault/config/vault_scope.py`` defining exactly the names
    passed as keyword arguments, drops the vault marker beside it, and points
    ``CLAUDE_PROJECT_DIR`` at the root — the arrangement ``run-vault-hook.sh``
    produces. A name omitted here is a name the owner's config does not define,
    which is how a stale config is modelled: it must fall back per name to the
    shipped default rather than wholesale.

    Returns
    -------
    callable
        ``_install(**names) -> Path`` — the vault root.
    """
    def _install(**names) -> Path:
        vault = tmp_path / "owner-vault"
        config_dir = vault / ".vault" / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        (vault / ".vault" / "vault.json").write_text(
            '{"vault": "test", "plugin": "workbench"}\n', encoding="utf-8"
        )
        body = "".join(f"{key} = {value!r}\n" for key, value in names.items())
        (config_dir / "vault_scope.py").write_text(body, encoding="utf-8")
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(vault))
        _clear_owner_scope_cache()
        return vault

    return _install


@pytest.fixture
def no_owner_scope(monkeypatch, tmp_path):
    """Resolve from outside any vault: every name serves the shipped default."""
    elsewhere = tmp_path / "not-a-vault"
    elsewhere.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(elsewhere))
    _clear_owner_scope_cache()
    return elsewhere
