#!/usr/bin/env python3
"""PostToolUse hook: validates frontmatter on vault note writes.

Thin entry point. The implementation is ``machinery/engine/validate-write.py``, which is
shared with the vault's own tooling and must stay importable there; this file
exists so ``scripts/stamp.py`` can read a wiring declaration off the filesystem
and so ``run-vault-hook.sh`` has a stable name to dispatch.

Nothing here runs outside a vault: ``run-vault-hook.sh`` checks for
``.vault/vault.json`` and exits before starting an interpreter (#667).
"""

WORKSHOP_HOOK = {"event": "PostToolUse", "runner": "vault", "matcher": "write|edit|multiedit|multi_edit|Write|Edit|MultiEdit"}

import sys  # noqa: E402
from pathlib import Path  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _vault_engine_dispatch import run_engine_script  # noqa: E402

run_engine_script("validate-write.py")
