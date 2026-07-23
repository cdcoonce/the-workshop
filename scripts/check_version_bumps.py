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


# --------------------------------------------------------------------------
# Bump level
#
# A removed skill and a corrected typo are not the same event to an owner: a
# removal changes the trigger surface, so their invocations silently stop
# matching. Only the mechanically visible part of that judgement is enforced
# here — the component inventory a preset ships. Behavioural breaks (a hook that
# now blocks where it did not) still need a human call; the policy in CLAUDE.md
# says so rather than pretending this covers them.
# --------------------------------------------------------------------------

LEVELS = ("patch", "minor", "major")


def _components_at(repo: Path, preset: str, ref: str | None) -> set[str]:
    """Skills, agents, and hook scripts a preset ships — its owner-facing surface.

    Underscore-prefixed hook files are shared library modules, not capabilities
    (see `core/hooks/_git_baseline.py`), and are excluded for the same reason
    hook discovery and the fail-open scan exclude them.
    """
    prefix = f"dist/{preset}/"
    if ref is None:
        base = repo / "dist" / preset
        paths = (
            [str(p.relative_to(repo)) for p in base.rglob("*")] if base.is_dir() else []
        )
    else:
        result = run_git(repo, "ls-tree", "-r", "--name-only", ref, "--", prefix)
        paths = result.stdout.splitlines() if result.returncode == 0 else []

    components = set()
    for path in paths:
        parts = Path(path).relative_to(f"dist/{preset}").parts if path.startswith(prefix) else ()
        if len(parts) >= 2 and parts[0] in ("skills", "agents"):
            components.add(f"{parts[0]}/{parts[1]}")
        elif len(parts) == 3 and parts[0] == "hooks" and parts[1] == "scripts":
            if not parts[2].startswith("_"):
                components.add(f"hooks/{parts[2]}")
    return components


def required_level(repo: Path, preset: str, base_sha: str) -> str:
    before = _components_at(repo, preset, base_sha)
    after = _components_at(repo, preset, None)
    if before - after:
        return "major"
    if after - before:
        return "minor"
    return "patch"


def _parts(version: str | None) -> tuple[int, int, int] | None:
    if not version:
        return None
    chunks = version.split(".")
    if len(chunks) != 3 or not all(c.isdigit() for c in chunks):
        return None
    major, minor, patch = (int(c) for c in chunks)
    return major, minor, patch


def actual_level(released: str | None, current: str | None) -> str | None:
    """Which component moved, or None when the version did not advance.

    Pre-1.0, a minor bump IS the breaking signal — `0.1.3 -> 0.2.0` — so it
    satisfies a `major` requirement. Demanding `1.0.0` to drop a skill from a
    0.x preset would force a release meaning nobody intends.
    """
    before, after = _parts(released), _parts(current)
    if before is None or after is None or after <= before:
        return None
    if after[0] != before[0]:
        return "major"
    if after[1] != before[1]:
        return "major" if before[0] == 0 else "minor"
    return "patch"


def find_level_violations(
    repo: Path, base: str = DEFAULT_BASE
) -> list[tuple[str, str, str]]:
    """(preset, required, actual) where the bump is too small for the change."""
    base_sha = resolve_base(repo, base)
    violations = []
    for preset in shipped_presets(repo):
        if not output_changed(repo, base_sha, preset):
            continue
        released = manifest_version(repo, preset, base_sha)
        current = manifest_version(repo, preset)
        if released is None or current is None:
            continue
        actual = actual_level(released, current)
        if actual is None:
            continue  # no bump at all — find_missing_bumps owns that message
        required = required_level(repo, preset, base_sha)
        if LEVELS.index(actual) < LEVELS.index(required):
            violations.append((preset, required, actual))
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--base", default=DEFAULT_BASE)
    args = parser.parse_args(argv)

    repo = Path(args.repo)
    try:
        missing = find_missing_bumps(repo, args.base)
        levels = find_level_violations(repo, args.base)
    except LookupError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    if not missing and not levels:
        print(f"version-bump gate: no unbumped presets against {args.base}.")
        return 0

    if levels:
        print(
            "ERROR: these presets changed their component surface by more than "
            "their version bump claims:",
            file=sys.stderr,
        )
        for preset, required, actual in levels:
            print(
                f"  {preset}: needs a {required} bump, got {actual} "
                f"({manifest_version(repo, preset)})",
                file=sys.stderr,
            )
        print(
            "\nA removed skill, agent, or hook changes what an owner can invoke; "
            "an added one is new capability. See Preset Versioning in CLAUDE.md.",
            file=sys.stderr,
        )
        if not missing:
            return 1
        print("", file=sys.stderr)

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
