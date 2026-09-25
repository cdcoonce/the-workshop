#!/usr/bin/env python3
"""Deterministic checks run before a GitLab merge request is opened.

``sweep`` finds identifiers the diff between ``--base`` and ``--head`` renamed
and reports every reference to the old name that survives at head. Exit codes:
0 clean, 1 surviving references, 2 setup error.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from reference_sweep import sweep  # noqa: E402
from rename_detector import detect_renames  # noqa: E402

CLEAN = 0
HITS = 1
SETUP_ERROR = 2


def _git(repo: Path, *args: str) -> str:
    # Bytes, decoded by hand: `text=True` applies universal newlines, turning
    # a `\r` inside a diffed line into a line break that splits it in two.
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True)
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(stderr or f"git {' '.join(args)} failed")
    return result.stdout.decode("utf-8", "replace")


def run_sweep(base: str, head: str) -> int:
    try:
        # `git grep <tree>` searches only the cwd's subtree, so run from the
        # top: a leftover at the repo root counts wherever this was invoked.
        repo = Path(_git(Path.cwd(), "rev-parse", "--show-toplevel").strip())
        diff_text = _git(repo, "diff", "-U0", "--no-color", "--no-ext-diff", base, head)
        hits = sweep(repo, head, detect_renames(diff_text))
    except RuntimeError as error:
        print(f"mr-preflight: {error}", file=sys.stderr)
        return SETUP_ERROR

    for hit in hits:
        print(f"{hit.path}:{hit.line}: {hit.rename.old} (renamed to {hit.rename.new} in {hit.rename.path})")
    if hits:
        print(f"mr-preflight: {len(hits)} surviving reference(s) to renamed identifiers.")
        return HITS
    return CLEAN


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    sweep_cmd = commands.add_parser("sweep", help="report surviving references to renamed identifiers")
    sweep_cmd.add_argument("--base", required=True, help="commit-ish the diff starts from")
    sweep_cmd.add_argument("--head", default="HEAD", help="commit-ish whose tree is searched")
    args = parser.parse_args()
    return run_sweep(args.base, args.head)


if __name__ == "__main__":
    sys.exit(main())
