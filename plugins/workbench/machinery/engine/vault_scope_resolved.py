"""Per-name resolution of vault scope names: owner config, then shipped default.

Managed tier: upgrade owns this file. The vault's ``vault_scope.py`` is
owner-owned — rendered once at init, never touched by upgrade — so engine code
must not hard-require a name from it. Import scope names from this module
instead: a name the owner defines wins; anything their config predates falls
back to the shipped default, so a stale config degrades instead of breaking the
engine on import.

Resolution is anchored on the **vault root**, never on a bare ``import
vault_scope``. That distinction is the fix for #691. Every vault hook entry
point prepends the engine directory to ``sys.path``, which puts it ahead of the
``PYTHONPATH`` entry ``run-vault-hook.sh`` sets for the owner's config
directory. While the engine also shipped a module named ``vault_scope``, a
name-based lookup could therefore only ever find the engine's own copy — so
every override an owner wrote was discarded, silently, on every vault. Loading
the owner's file by explicit location removes the dependency on path ordering
altogether: it no longer matters what else is importable or in what order.

The fallback is silent **by design** for the two states that are legitimate —
no vault, and a vault with no owner config. It is deliberately *not* silent for
the third: a config that exists but cannot be loaded is a defect in the owner's
own file, only the owner can fix it, and it must not be indistinguishable from
having written no config at all.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType

# `.vault/vault.json` is the vault marker, matching `run-vault-hook.sh` exactly.
# A note-directory signature (the `CLAUDE.md` + `brain/` + `perf/` check used
# elsewhere) would be circular here: which directories a vault governs is the
# very thing this module resolves, and it must work for a taxonomy that shares
# no directory name with this one's.
_VAULT_MARKER = (".vault", "vault.json")
_OWNER_CONFIG = (".vault", "config", "vault_scope.py")

_UNSET = object()
_owner_config: ModuleType | None | object = _UNSET


def _find_vault_root() -> Path | None:
    """Walk up for the vault marker, from ``CLAUDE_PROJECT_DIR`` or cwd.

    Returns
    -------
    Path or None
        The vault root, or None when the search starts outside any vault.
    """
    try:
        # os.getcwd() itself raises when the working directory has been
        # deleted out from under the process, so it belongs inside the guard:
        # this module is imported at engine startup and must never be the
        # reason a hook dies.
        raw = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
        start = Path(raw).resolve()
    except OSError:
        return None
    for candidate in (start, *start.parents):
        if candidate.joinpath(*_VAULT_MARKER).is_file():
            return candidate
    return None


def _report(path: Path, detail: str) -> None:
    """Announce an owner config that exists but did not load.

    Written to stderr rather than raised: hooks fail open by contract, and a
    typo in the owner's config must not take their session down. The point is
    only that the condition stops being invisible.
    """
    print(
        f"vault_scope: owner config at {path} did not load ({detail}); "
        "falling back to shipped defaults",
        file=sys.stderr,
    )


def _load_owner_config() -> ModuleType | None:
    """Load the owner's ``vault_scope`` by file location, or return None."""
    root = _find_vault_root()
    if root is None:
        return None
    path = root.joinpath(*_OWNER_CONFIG)
    if not path.is_file():
        # A vault with no overrides. Legitimate, and silent by design.
        return None

    spec = importlib.util.spec_from_file_location("vault_scope", path)
    if spec is None or spec.loader is None:
        _report(path, "no import spec")
        return None

    module = importlib.util.module_from_spec(spec)
    # Registered before execution so a config that reaches its own module by
    # name resolves to this instance rather than re-entering the loader.
    sys.modules["vault_scope"] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 - fail open; the owner's file can break in any way
        sys.modules.pop("vault_scope", None)
        _report(path, f"{type(exc).__name__}: {exc}")
        return None
    return module


def _owner_scope() -> ModuleType | None:
    """The owner's config module, resolved once per process.

    The cache is set to ``None`` *before* the load rather than after it, so a
    re-entrant lookup during ``exec_module`` sees "no owner config" and falls
    through to the shipped defaults. Without that, an owner file that reached
    this module while executing — directly, or through anything it imports —
    would find the cache still unset, start the load again, and recurse until
    the interpreter gave out.
    """
    global _owner_config
    if _owner_config is _UNSET:
        _owner_config = None
        _owner_config = _load_owner_config()
    return _owner_config  # type: ignore[return-value]


def __getattr__(name: str):
    if name.startswith("_"):
        raise AttributeError(name)
    scope = _owner_scope()
    if scope is not None:
        try:
            return getattr(scope, name)
        except AttributeError:
            pass
    import vault_scope_defaults as _defaults

    try:
        return getattr(_defaults, name)
    except AttributeError:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        ) from None
