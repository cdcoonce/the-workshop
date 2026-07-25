"""Per-name resolution of vault scope names: scaffold override, shipped default.

Managed tier: upgrade owns this file. The vault's ``vault_scope.py`` is
scaffold-owned — rendered once at init, never touched by upgrade — so engine
code must not hard-require a name from it. Import scope names from this
module instead: a name the scaffold defines wins; anything it predates falls
back to the shipped default, so a stale scaffold degrades instead of
breaking the engine on import.
"""

from __future__ import annotations


def __getattr__(name: str):
    if name.startswith("_"):
        raise AttributeError(name)
    try:
        import vault_scope as _scope
    except ImportError:
        _scope = None
    if _scope is not None:
        try:
            return getattr(_scope, name)
        except AttributeError:
            pass
    import vault_scope_defaults as _defaults

    try:
        return getattr(_defaults, name)
    except AttributeError:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        ) from None
