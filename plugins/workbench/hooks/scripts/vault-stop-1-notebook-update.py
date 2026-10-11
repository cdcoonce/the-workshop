#!/usr/bin/env python3
"""Stop hook: updates the session notebook.

Thin entry point. The implementation is ``machinery/engine/notebook-update.py``, which is
shared with the vault's own tooling and must stay importable there; this file
exists so ``scripts/stamp.py`` can read a wiring declaration off the filesystem
and so ``run-vault-hook.sh`` has a stable name to dispatch.

Nothing here runs outside a vault: ``run-vault-hook.sh`` checks for
``.vault/vault.json`` and exits before starting an interpreter (#667).
"""

WORKSHOP_HOOK = {"event": "Stop", "runner": "vault"}

import sys  # noqa: E402
from pathlib import Path  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _vault_engine_dispatch import run_engine_script  # noqa: E402

run_engine_script("notebook-update.py")
