"""Shared vault utilities used across hook scripts and tools.

Centralizes common operations to avoid DRY violations.
"""

from __future__ import annotations

import os
import re
from datetime import date
from pathlib import Path

# Wikilink patterns — shared across frontmatter_engine, task_manager, etc.
WIKILINK_RE = re.compile(r"\[\[.+?\]\]")
WIKILINK_CAPTURE_RE = re.compile(r"\[\[(.+?)\]\]")

# Fallback used only when the scaffold-owned config predates ``BATCH_MODEL``
# (a vault rendered before #431 has no such attribute); see read_batch_model.
DEFAULT_BATCH_MODEL = "claude-haiku-4-5"


def iso_week_string(d: date) -> str:
    """Format a date as an ISO week string (``YYYY-W##``).

    Uses ISO calendar semantics, so the year/week can straddle the Gregorian
    year boundary (e.g. 2025-12-29 → ``2026-W01``). The week is zero-padded to
    two digits. Shared by ``task_manager`` and ``work_task_manager``.
    """
    iso_year, iso_week, _ = d.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def find_vault_root(start: Path | None = None) -> Path | None:
    """Find the brain vault root by walking up from *start*.

    The vault is identified by its signature workspaces (``brain/`` + ``perf/``)
    alongside ``CLAUDE.md`` — NOT by ``CLAUDE.md`` alone. Many project repos
    (e.g. am-external-reporting-tools) carry their own ``CLAUDE.md``; matching on
    that alone let the session-stop auto-commit run inside whatever repo the
    shell had ``cd``'d into, committing/pushing a non-vault repo. The signature
    check keeps every hook vault-only.

    Args:
        start: Starting directory. Defaults to cwd.

    Returns:
        Path to vault root, or None if not found.
    """
    if start is None:
        start = Path.cwd()
    for path in [start, *start.parents]:
        if (
            (path / "CLAUDE.md").exists()
            and (path / "brain").is_dir()
            and (path / "perf").is_dir()
        ):
            return path
    return None


def find_vault_root_from_env() -> Path | None:
    """Resolve the vault root from ``CLAUDE_PROJECT_DIR``, falling back to cwd.

    Centralizes the env+fallback idiom shared by the Stop/PreCompact hooks and
    the graph gardener: anchor to the project Claude Code launched in (the
    vault) when that env var is set, otherwise walk up from the current working
    directory. The ``find_vault_root`` signature check still applies, so a
    non-vault ``CLAUDE_PROJECT_DIR`` resolves to ``None``.

    Returns:
        Path to vault root, or None if not found.
    """
    proj = os.environ.get("CLAUDE_PROJECT_DIR")
    return find_vault_root(Path(proj)) if proj else find_vault_root()


def read_vault_context(vault_root: Path, default: str = "unknown") -> str:
    """Read ``.vault-context`` (``work``|``personal``) from the vault root.

    Returns the lowercased value when it is exactly ``"work"`` or ``"personal"``;
    otherwise (file missing, empty, or any other value) returns *default*.

    The canonical single reader (#50): every hook/script that needs the machine
    context — session-start, graph_gardener, notebook-distill, context_loader —
    reads through here, so the missing-file fallback is reconciled in ONE place.
    The default is ``"unknown"`` (a missing marker genuinely means the machine is
    unidentified). Callers that build per-context filenames stay mutually
    consistent precisely because they share this one default.
    """
    ctx_file = vault_root / ".vault-context"
    try:
        val = ctx_file.read_text(encoding="utf-8").strip().lower()
    except OSError:
        return default
    return val if val in ("work", "personal") else default


def read_batch_model(default: str = DEFAULT_BATCH_MODEL) -> str:
    """Read ``BATCH_MODEL`` from the scaffold-owned ``vault_scope`` config.

    The canonical single reader for the headless batch model: notebook-distill
    and graph_gardener Lane B both resolve their ``claude -p --model`` argument
    here, so a deprecation or tiering change is a scaffold edit rather than an
    engine release. ``vault_scope.py`` is scaffold-tier — init renders it once
    and upgrade never touches it — which is why the id lives there and not in
    the managed engine payload.

    A vault whose ``vault_scope.py`` was rendered before the value existed (or
    a context where the module is not importable) falls back to *default*, so
    an absent config preserves the previous behaviour exactly.
    """
    try:
        import vault_scope
    except ImportError:
        return default
    value = getattr(vault_scope, "BATCH_MODEL", None)
    return value if isinstance(value, str) and value else default
