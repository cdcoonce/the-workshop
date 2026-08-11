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

import os  # noqa: E402
import runpy  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

_ENGINE = Path(__file__).resolve().parents[2] / "machinery" / "engine"
_TARGET = _ENGINE / "session-start.py"


def _write_breadcrumb() -> None:
    """Record which plugin served this session, for the vault's presence check.

    The vault can see that its hooks stopped firing only if something writes
    proof that they did. This is that proof: `.vault/plugin-state.json`, naming
    the plugin root and version that ran.

    Write-if-changed, deliberately. Rewriting an identical file every session
    would churn mtime, and the vault auto-commits on Stop -- so a byte-identical
    rewrite would manufacture a commit per session. The payload carries no
    timestamp for the same reason: freshness is judged by the vault counting
    sessions since it last saw a breadcrumb, not by this file's mtime.
    """
    import json

    vault_root = Path(os.environ["CLAUDE_PROJECT_DIR"])
    manifest = Path(__file__).resolve().parents[2] / ".claude-plugin" / "plugin.json"
    payload = {
        "root": str(Path(__file__).resolve().parents[2]),
        "version": json.loads(manifest.read_text())["version"],
        "platform": "claude-code" if os.environ.get("CLAUDE_PLUGIN_ROOT") else "other",
    }
    target = vault_root / ".vault" / "plugin-state.json"
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if target.exists() and target.read_text() == rendered:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(rendered)

# Fail open, like every hook in this repo: a missing or broken engine must not
# block the tool path. The guard already proved we are in a vault, so a failure
# here is a real defect worth seeing on stderr -- but not worth blocking on.
try:
    _write_breadcrumb()
    sys.path.insert(0, str(_ENGINE))
    sys.argv = [str(_TARGET)]
    runpy.run_path(str(_TARGET), run_name="__main__")
except SystemExit:
    raise
except Exception as exc:  # noqa: BLE001 - fail-open is the contract
    print(f"vault hook {_TARGET.name} failed: {exc}", file=sys.stderr)
    sys.exit(0)
