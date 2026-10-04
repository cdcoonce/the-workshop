"""Explicit-root policy shared by the Workshop's ragmark compatibility shims.

Requires the coordinated ragmark#94 scope API, not merely a matching package
version. Older packages fail closed; no default broad-corpus fallback exists.
"""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path
from typing import TYPE_CHECKING

import vault_scope_resolved

if TYPE_CHECKING:
    from ragmark.config import RagmarkConfig

_SCOPE_FIELDS = {"scoped_folders", "excluded_filenames", "excluded_path_prefixes"}
CAPABILITY_REMEDIATION = (
    "Install the coordinated ragmark scope/compatibility release (ragmark#94/#95), "
    "or use its reviewed source environment; the older published package is insufficient."
)


def config_for_vault(vault_root: Path) -> RagmarkConfig:
    """Build an explicit-root ragmark config from this vault's owner policy.

    Parameters
    ----------
    vault_root : Path
        Vault whose notes and machine-local `.ragmark` index are requested.

    Returns
    -------
    RagmarkConfig
        Owner corpus policy with ragmark's existing machine-context policy.

    Raises
    ------
    RuntimeError
        Required scope capabilities or a valid owner policy are unavailable.
    """
    try:
        from ragmark.config import RagmarkConfig
    except ImportError as exc:
        raise RuntimeError(CAPABILITY_REMEDIATION) from exc
    if not _SCOPE_FIELDS.issubset({field.name for field in fields(RagmarkConfig)}):
        raise RuntimeError(CAPABILITY_REMEDIATION)
    root = Path(vault_root).resolve()
    policy = vault_scope_resolved.for_vault(root)
    for name in (
        "GRAPH_NOTE_DIRS",
        "GRAPH_EXCLUDED_DIRS",
        "OPERATING_FILENAMES",
        "TRANSIENT_PREFIXES",
    ):
        value = getattr(policy, name)
        if not isinstance(value, (list, tuple, set, frozenset)) or not all(
            isinstance(item, str) for item in value
        ):
            raise ValueError(f"vault scope {name} must be a collection of strings")
    if not policy.GRAPH_NOTE_DIRS:
        # Ragmark's empty folder set means unrestricted; the owner's empty
        # allowlist means no notes. Refuse rather than reverse that policy.
        raise ValueError("vault scope GRAPH_NOTE_DIRS cannot be empty for this adapter")
    return RagmarkConfig(
        vault_root=root,
        index_dir=root / ".ragmark",
        scoped_folders=policy.GRAPH_NOTE_DIRS,
        excluded_dirs=frozenset(policy.GRAPH_EXCLUDED_DIRS),
        excluded_filenames=policy.OPERATING_FILENAMES,
        excluded_path_prefixes=policy.TRANSIENT_PREFIXES,
    )
