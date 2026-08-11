"""In-repo stand-in for the scaffold-rendered vault_scope module.

In a vault, ``vault_scope.py`` is scaffold-owned: rendered once at init from
``scaffold/vault_scope.py.tmpl`` and never touched by upgrade. In this repo,
engine code and tests resolve ``import vault_scope`` here instead; the real
surface lives in ``vault_scope_defaults`` (managed), which this re-exports.
Engine code must import scope names through ``vault_scope_resolved`` — never
hard-require a name from ``vault_scope`` itself.
"""

from __future__ import annotations

from vault_scope_defaults import *  # noqa: F401,F403
