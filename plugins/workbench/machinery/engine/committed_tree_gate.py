#!/usr/bin/env python3
"""Run the vault health gate on the tree the next commit will record.

/wrap-up stages only reviewed work and leaves foreign changes behind, so the
working tree is not what gets committed. On 2026-10-15 the gate passed on the
working tree while the commit failed it: a staged Key Decisions entry linked
to a note that was still untracked. This gate judges the staged index instead.

A copy of the index is written to a tree object (``git write-tree``; the real
index is never written) and extracted with ``git archive`` into a throwaway directory,
the same choice ``wrap_up_audit._build_base_orphans`` makes over
``git worktree add``: no worktree registration, nothing to restore. The gate
that runs is the staged tree's own ``ci/vault_health.py``, so the committed
policy and scope config judge the committed notes.

Exit codes: 0 pass (or the staged tree has no gate script), 1 the gate failed,
2 the gate could not run. Callers treat anything but 0 as "do not commit".

Usage:
    python3 committed_tree_gate.py [--vault PATH]
"""

from __future__ import annotations

import argparse
import io
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

GATE = Path("ci") / "vault_health.py"
TIMEOUT_S = 300


def _git(vault: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", "-C", str(vault), *args], capture_output=True, timeout=60, env=env)


def _staged_tree(vault: Path, scratch: Path) -> subprocess.CompletedProcess[bytes]:
    """``git write-tree`` against a copy of the index.

    ``write-tree`` stores a cache-tree extension back into whatever index it
    reads, and the real one may belong to a live session mid-staging.
    """
    index = _git(vault, "rev-parse", "--path-format=absolute", "--git-path", "index")
    if index.returncode != 0:
        return index
    copy = scratch / "index"
    real = Path(index.stdout.decode().strip())
    if real.is_file():  # a repo that has never staged anything has no index yet
        shutil.copyfile(real, copy)
    return _git(vault, "write-tree", env={**os.environ, "GIT_INDEX_FILE": str(copy)})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--vault", type=Path, default=Path.cwd(), help="vault checkout (default: cwd)")
    args = parser.parse_args(argv)

    tmp_dir = Path(tempfile.mkdtemp(prefix="committed_tree_gate_"))
    try:
        tree = _staged_tree(args.vault, tmp_dir)
        if tree.returncode != 0:
            print(f"cannot read the staged tree: {tree.stderr.decode().strip()}", file=sys.stderr)
            return 2
        tree_id = tree.stdout.decode().strip()
        (tmp_dir / "index").unlink(missing_ok=True)

        archive = _git(args.vault, "archive", tree_id)
        if archive.returncode != 0:
            print(f"git archive {tree_id} failed: {archive.stderr.decode().strip()}", file=sys.stderr)
            return 2

        with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tf:
            tf.extractall(tmp_dir, filter="data")
        script = tmp_dir / GATE
        if not script.is_file():
            print(f"no {GATE.as_posix()} in the staged tree; nothing to gate")
            return 0
        print(f"gating staged tree {tree_id[:12]}", flush=True)
        try:
            result = subprocess.run(
                ["uv", "run", "--script", str(script)], cwd=tmp_dir, timeout=TIMEOUT_S, check=False,
            )
        except subprocess.TimeoutExpired:
            print(f"vault health gate timed out after {TIMEOUT_S}s", file=sys.stderr)
            return 2
        except OSError as exc:
            print(f"vault health gate could not run: {exc}", file=sys.stderr)
            return 2
        return 0 if result.returncode == 0 else 1
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
