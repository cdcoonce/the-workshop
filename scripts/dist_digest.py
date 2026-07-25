"""Stable content digest of the generated output tree (dist/ + marketplaces).

`make verify-generated` snapshots this digest before and after a fresh rebuild:
if the rebuild changes nothing, the generated output matches its sources —
regardless of what is or isn't committed. (The previous gate compared dist/
against HEAD via `git status --porcelain`, which false-positived on any
legitimately uncommitted dist/ change — e.g. an afk slice whose deliverable is
an uncommitted diff that syncs shared core/ files into every preset copy.)
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

GENERATED_ROOTS = (
    Path("dist"),
    Path(".claude-plugin/marketplace.json"),
    Path(".agents/plugins/marketplace.json"),
    # Committed-generated machinery output rebuilt in the SOURCE tree by
    # build_preset (W4): the rendered wiring adapters and the vendor map.
    # Digesting them here makes verify-generated catch a hand-edited or
    # stale copy the same way it catches a stale dist/.
    Path("presets/vault-ops/machinery/rendered"),
    Path("presets/vault-ops/machinery/vendor-map.json"),
)


def tree_digest(repo_root: Path, roots: tuple[Path, ...] = GENERATED_ROOTS) -> str:
    """Return a stable SHA-256 over every file under the generated roots.

    Files are hashed as (posix relpath, content) pairs in sorted order, so the
    digest is independent of filesystem walk order and platform separators.
    Missing roots contribute nothing: a checkout with no dist/ digests the same
    as one with an empty dist/.
    """
    digest = hashlib.sha256()
    for root in roots:
        base = repo_root / root
        if base.is_file():
            files = [base]
        elif base.is_dir():
            files = sorted(p for p in base.rglob("*") if p.is_file())
        else:
            continue
        for path in files:
            rel = path.relative_to(repo_root).as_posix()
            digest.update(rel.encode())
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
    return digest.hexdigest()


def main() -> int:
    print(tree_digest(Path.cwd()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
