#!/usr/bin/env python3
"""Stop hook: commits and syncs the vault.

Thin entry point. The implementation is ``machinery/engine/session-stop.py``, which is
shared with the vault's own tooling and must stay importable there; this file
exists so ``scripts/stamp.py`` can read a wiring declaration off the filesystem
and so ``run-vault-hook.sh`` has a stable name to dispatch.

Nothing here runs outside a vault: ``run-vault-hook.sh`` checks for
``.vault/vault.json`` and exits before starting an interpreter (#667).
"""

WORKSHOP_HOOK = {"event": "Stop", "runner": "vault"}

import runpy  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

_ENGINE = Path(__file__).resolve().parents[2] / "machinery" / "engine"
_TARGET = _ENGINE / "session-stop.py"

# Fail open, like every hook in this repo: a missing or broken engine must not
# block the tool path. The guard already proved we are in a vault, so a failure
# here is a real defect worth seeing on stderr -- but not worth blocking on.
try:
    sys.path.insert(0, str(_ENGINE))
    sys.argv = [str(_TARGET), "--explicit-sync"]
    runpy.run_path(str(_TARGET), run_name="__main__")
except SystemExit:
    raise
except Exception as exc:  # noqa: BLE001 - fail-open is the contract
    print(f"vault hook {_TARGET.name} failed: {exc}", file=sys.stderr)
    sys.exit(0)
