"""Shared fail-open dispatcher for the `vault-*.py` hook wrappers.

Not a hook. The leading underscore keeps it out of hook discovery -- the stamper
treats a script without a `WORKSHOP_HOOK` declaration as a library module.

Each vault hook is a thin entry point: it keeps its own top-level
``WORKSHOP_HOOK`` literal (read statically by ``scripts/stamp.py``) and hands the
real work to a script under ``machinery/engine/``, which is shared with the
vault's own tooling and must stay importable there. Nothing here runs outside a
vault: ``run-vault-hook.sh`` checks for ``.vault/vault.json`` and exits before
starting an interpreter (#667).
"""

from __future__ import annotations

import runpy
import sys
from collections.abc import Callable
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parents[2] / "machinery" / "engine"


def run_engine_script(
    engine_filename: str,
    extra_argv: list[str] | None = None,
    before: Callable[[], None] | None = None,
) -> None:
    """Run ``machinery/engine/<engine_filename>`` as ``__main__``, failing open.

    A missing or broken engine must not block the tool path. The runner guard
    already proved we are in a vault, so a failure here is a real defect worth
    seeing on stderr -- but not worth blocking on.

    Parameters
    ----------
    engine_filename
        File name of the engine script inside ``machinery/engine/``.
    extra_argv
        Arguments placed after the script path in ``sys.argv``.
    before
        Optional callable run first, under the same fail-open guard.

    Raises
    ------
    SystemExit
        Re-raised from the engine script unchanged; exit code 0 on any other
        failure.
    """
    target = ENGINE_DIR / engine_filename
    try:
        if before is not None:
            before()
        sys.path.insert(0, str(ENGINE_DIR))
        sys.argv = [str(target), *(extra_argv or [])]
        runpy.run_path(str(target), run_name="__main__")
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - fail-open is the contract
        print(f"vault hook {target.name} failed: {exc}", file=sys.stderr)
        sys.exit(0)
