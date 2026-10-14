#!/usr/bin/env python3
"""SessionStart hook: pulls from remote and injects vault context.

Thin entry point. The implementation is ``machinery/engine/session-start.py``, which is
shared with the vault's own tooling and must stay importable there; this file
exists so ``scripts/stamp.py`` can read a wiring declaration off the filesystem
and so ``run-vault-hook.sh`` has a stable name to dispatch.

Nothing here runs outside a vault: ``run-vault-hook.sh`` checks for
``.vault/vault.json`` and exits before starting an interpreter (#667).
"""

from __future__ import annotations

WORKSHOP_HOOK = {"event": "SessionStart", "runner": "vault"}

import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _vault_engine_dispatch import run_engine_script  # noqa: E402

# Where each platform's plugin manager keeps its cache, relative to $HOME. The
# platform is decided by which of these the running copy lives under -- never
# by an environment variable, which can disagree with the path (a Codex cache
# copy launched with CLAUDE_PLUGIN_ROOT set is still a Codex copy).
_PLATFORM_CACHES = (
    ("claude-code", (".claude", "plugins", "cache")),
    ("codex", (".codex", "plugins", "cache")),
    ("cortex", (".snowflake", "cortex", "plugins")),
)


def _platform_for(root: Path) -> str:
    """Name the platform whose plugin cache contains ``root``, else ``other``."""
    home = Path.home().resolve()
    for name, parts in _PLATFORM_CACHES:
        if root.is_relative_to(home.joinpath(*parts)):
            return name
    return "other"


def _read_payload() -> dict | None:
    """The hook payload from stdin as a dict, or ``None`` when there is none.

    Reads stdin once and puts it back so the engine, which parses the same
    stream, still sees it. Anything that is not a JSON object -- empty stdin
    (Codex sends no payload), malformed text, a list -- counts as no payload.
    """
    raw = ""
    if sys.stdin is not None and not sys.stdin.isatty():
        raw = sys.stdin.read()
        sys.stdin = io.StringIO(raw)
    try:
        payload = json.loads(raw)
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def _session_marker(payload: dict | None) -> str:
    """Identify this session: the harness session id, else a UTC timestamp."""
    session_id = payload.get("session_id") if payload else None
    if isinstance(session_id, str) and session_id:
        return session_id
    return datetime.now(timezone.utc).isoformat()


def _vault_root_containing(path: Path) -> Path | None:
    """The nearest directory at or above ``path`` holding ``.vault/vault.json``.

    The same marker ``run-vault-hook.sh`` and ``vault_utils.find_vault_root``
    walk up for, so all three agree on what counts as a vault.
    """
    for candidate in (path, *path.parents):
        if (candidate / ".vault" / "vault.json").is_file():
            return candidate
    return None


def _breadcrumb_roots(payload: dict | None) -> list[Path]:
    """Every vault root this session leaves a breadcrumb in.

    ``CLAUDE_PROJECT_DIR`` is the project the session was launched in, and for
    an ordinary checkout it is the only root. In a linked worktree session it
    names the MAIN checkout, not the worktree the session runs in -- so the
    worktree's own gitignored breadcrumb was never refreshed, kept naming a
    plugin root long since pruned from the cache, and the vault's local gate
    (``tests/test_vault_gate.py``, which resolves its root from its own file)
    failed from inside the worktree while the main checkout's copy was fresh.
    The payload's ``cwd`` is where the session actually runs; the vault
    enclosing it gets a breadcrumb too when it is a different directory. The
    main checkout keeps its breadcrumb as well: ``check-plugin.sh`` reads it
    through ``CLAUDE_PROJECT_DIR`` for every session, worktree or not.
    """
    project_root = Path(os.environ["CLAUDE_PROJECT_DIR"])
    roots = [project_root]
    cwd = payload.get("cwd") if payload else None
    if isinstance(cwd, str) and cwd:
        session_root = _vault_root_containing(Path(cwd))
        if session_root is not None and session_root.resolve() != project_root.resolve():
            roots.append(session_root)
    return roots


def _write_breadcrumb() -> None:
    """Record which plugin copy served this session, for the vault's presence check.

    The vault can see that its hooks stopped firing only if something writes
    proof that they did. This writes ``.vault/plugin-state.<platform>.json`` for
    the platform whose cache this copy runs from, so two platforms sharing one
    vault each keep their own record instead of overwriting each other. The
    legacy ``.vault/plugin-state.json`` is written alongside for one release so
    an un-updated reader (``check-plugin.sh``) is unaffected.

    The payload is per-platform and per-session: ``root`` names the copy that
    executed (the datum a reader's supersession check consumes), and ``session``
    changes every session so a reader can tell "ran and confirmed" from "did not
    run". Every session rewrites the files; they are gitignored machine-local
    state that never syncs. A linked worktree session writes them into the
    worktree as well as the main checkout (see ``_breadcrumb_roots``).
    """
    payload = _read_payload()
    root = Path(__file__).resolve().parents[2]
    manifest = root / ".claude-plugin" / "plugin.json"
    platform = _platform_for(root)
    record = {
        "root": str(root),
        "version": json.loads(manifest.read_text())["version"],
        "platform": platform,
        "session": _session_marker(payload),
    }
    rendered = json.dumps(record, indent=2, sort_keys=True) + "\n"
    for vault_root in _breadcrumb_roots(payload):
        state_dir = vault_root / ".vault"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / f"plugin-state.{platform}.json").write_text(rendered)
        (state_dir / "plugin-state.json").write_text(rendered)


run_engine_script("session-start.py", before=_write_breadcrumb)
