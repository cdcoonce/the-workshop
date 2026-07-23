"""Fail when a preset's shipped output changed without a version bump.

The rest of the gate proves a change is correct. This proves it will actually
be delivered: `claude plugin update` decides there is something to offer by
comparing the manifest version, so a preset whose content changed without a
bump merges green, promotes green, and silently reaches nobody.

Compares `dist/<preset>` — the real shipped artifact, already tracked in this
repo — rather than inferring which sources feed which preset. That inference is
exactly what goes stale: `workbench` bundles every core skill, so a change three
directories away is still a change to what its owners receive.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

DEFAULT_BASE = "origin/main"


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True, check=False
    )


def resolve_base(repo: Path, base: str) -> str:
    """Full sha for `base`, or raise — never silently skip.

    A gate that quietly does nothing when it cannot find its baseline is worse
    than no gate: it reports success having compared nothing.
    """
    result = run_git(repo, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}")
    sha = result.stdout.strip()
    if not sha:
        raise LookupError(
            f"base ref {base!r} not found. CI must check out enough history to "
            f"resolve it (actions/checkout defaults to depth 1); locally, fetch it."
        )
    return sha


def shipped_presets(repo: Path) -> list[str]:
    dist = repo / "dist"
    if not dist.is_dir():
        return []
    return sorted(d.name for d in dist.iterdir() if d.is_dir())


def output_changed(repo: Path, base: str, preset: str) -> bool:
    return run_git(repo, "diff", "--quiet", base, "--", f"dist/{preset}").returncode != 0


def manifest_version(repo: Path, preset: str, ref: str | None = None) -> str | None:
    """Declared version at `ref` (or the working tree when ref is None)."""
    relative = f"presets/{preset}/manifest.json"
    if ref is None:
        path = repo / relative
        if not path.is_file():
            return None
        text = path.read_text(encoding="utf-8")
    else:
        result = run_git(repo, "show", f"{ref}:{relative}")
        if result.returncode != 0:
            return None
        text = result.stdout
    try:
        return json.loads(text).get("version")
    except (json.JSONDecodeError, AttributeError):
        return None


def find_missing_bumps(repo: Path, base: str = DEFAULT_BASE) -> list[str]:
    """Presets whose shipped output changed since `base` without a version bump.

    A preset absent from `base` is new — there is no prior version to bump from.
    A preset absent from the working tree was deleted, and a deleted preset
    needs no bump either.
    """
    base_sha = resolve_base(repo, base)
    missing = []
    for preset in shipped_presets(repo):
        if not output_changed(repo, base_sha, preset):
            continue
        released = manifest_version(repo, preset, base_sha)
        if released is None:
            continue  # new preset
        current = manifest_version(repo, preset)
        if current is None:
            continue  # being removed
        if current == released:
            missing.append(preset)
    return missing


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--base", default=DEFAULT_BASE)
    args = parser.parse_args(argv)

    try:
        missing = find_missing_bumps(Path(args.repo), args.base)
    except LookupError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    if not missing:
        print(f"version-bump gate: no unbumped presets against {args.base}.")
        return 0

    print(
        "ERROR: these presets ship changed content but declare the same version "
        f"as {args.base}:",
        file=sys.stderr,
    )
    for preset in missing:
        version = manifest_version(Path(args.repo), preset)
        print(f"  {preset} (still {version})", file=sys.stderr)
    print(
        "\nBump each preset's manifest.json version and rebuild, or the change "
        "merges green and never reaches anyone who has it installed.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
