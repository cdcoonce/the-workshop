#!/usr/bin/env python3
"""SessionStart hook: pulls from remote and injects vault context.

Thin entry point. The implementation is ``machinery/engine/session-start.py``, which is
shared with the vault's own tooling and must stay importable there; this file
exists so ``scripts/stamp.py`` can read a wiring declaration off the filesystem
and so ``run-vault-hook.sh`` has a stable name to dispatch.

Nothing here runs outside a vault: ``run-vault-hook.sh`` checks for
``.vault/vault.json`` and exits before starting an interpreter (#667).
"""

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


def _session_marker() -> str:
    """Identify this session: the harness session id, else a UTC timestamp.

    Reads the hook payload from stdin and puts it back so the engine, which
    parses the same stream, still sees it.
    """
    raw = ""
    if not sys.stdin.isatty():
        raw = sys.stdin.read()
        sys.stdin = io.StringIO(raw)
    try:
        payload = json.loads(raw)
    except ValueError:
        payload = None
    session_id = payload.get("session_id") if isinstance(payload, dict) else None
    if isinstance(session_id, str) and session_id:
        return session_id
    return datetime.now(timezone.utc).isoformat()


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
    state that never syncs.
    """
    vault_root = Path(os.environ["CLAUDE_PROJECT_DIR"])
    root = Path(__file__).resolve().parents[2]
    manifest = root / ".claude-plugin" / "plugin.json"
    platform = _platform_for(root)
    payload = {
        "root": str(root),
        "version": json.loads(manifest.read_text())["version"],
        "platform": platform,
        "session": _session_marker(),
    }
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    state_dir = vault_root / ".vault"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / f"plugin-state.{platform}.json").write_text(rendered)
    (state_dir / "plugin-state.json").write_text(rendered)


run_engine_script("session-start.py", before=_write_breadcrumb)
