"""Bump a plugin's version in the one hand-written file, then stamp the rest.

`plugins/<name>/.claude-plugin/plugin.json` is the only hand-written declaration
of a plugin's version. The codex and cortex manifests, both marketplaces, the
README and `docs/reference/plugins.md` are stamper output, so hand-editing them
is redundant, and a missed edit is silent (#1114). This writes the one file and
runs the stamper, which regenerates every copy.

The new version is computed from the version *released at the base ref*, not the
working tree, so running it twice does not bump twice: a manifest already at or
past the target is left alone. The level defaults to what the version-bump gate
would demand for the change (`check_version_bumps.required_level`).
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from scripts import check_version_bumps as gate
from scripts.stamp import StampError, stamp

_VERSION_LINE = re.compile(r'("version"\s*:\s*")([^"]*)(")')
_SEMVER = re.compile(r"\d+\.\d+\.\d+")


class BumpError(Exception):
    """A refusal that names its own cause; nothing is written when raised."""


@dataclass(frozen=True)
class BumpResult:
    plugin: str
    released: str
    new: str
    level: str
    changed: bool


def _parse(version: str | None) -> tuple[int, int, int]:
    if not version or not _SEMVER.fullmatch(version):
        raise BumpError(f"version {version!r} is not plain semver (X.Y.Z)")
    major, minor, patch = (int(c) for c in version.split("."))
    return major, minor, patch


def next_version(released: str, level: str) -> str:
    if level not in gate.LEVELS:
        raise BumpError(f"unknown level {level!r}; want one of {', '.join(gate.LEVELS)}")
    major, minor, patch = _parse(released)
    # Pre-1.0 the minor position is the breaking signal (see actual_level), so a
    # `major` bump lands on the next minor rather than forcing 1.0.0.
    if level == "major" and major == 0:
        level = "minor"
    if level == "major":
        return f"{major + 1}.0.0"
    if level == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def bump(repo: Path, plugin: str, base: str, level: str | None = None) -> BumpResult:
    if plugin not in gate.shipped_plugins(repo):
        raise BumpError(f"no plugin named {plugin!r} under {repo / 'plugins'}")
    try:
        base_sha = gate.resolve_base(repo, base)
    except LookupError as error:
        raise BumpError(str(error)) from error
    released = gate.manifest_version(repo, plugin, base_sha)
    if released is None:
        raise BumpError(f"{plugin} is not released at {base}; there is no version to bump from")

    chosen = level or gate.required_level(repo, plugin, base_sha)
    target = next_version(released, chosen)

    path = repo / "plugins" / plugin / ".claude-plugin" / "plugin.json"
    text = path.read_text(encoding="utf-8")
    if len(_VERSION_LINE.findall(text)) != 1:
        raise BumpError(f'{path} must hold exactly one "version" field to replace')
    current = _parse(gate.manifest_version(repo, plugin))

    changed = current < _parse(target)
    if changed:
        path.write_text(_VERSION_LINE.sub(rf"\g<1>{target}\g<3>", text), encoding="utf-8")
    # Always stamp: it regenerates every derived copy, including ones a hand edit
    # left stale, and is a no-op on an already-consistent tree.
    stamp(repo)
    new = target if changed else gate.manifest_version(repo, plugin)
    return BumpResult(plugin, released, new, chosen, changed)


def _changed_files(repo: Path) -> list[str]:
    out = gate.run_git(repo, "status", "--porcelain", "--untracked-files=no").stdout
    return sorted(line[3:] for line in out.splitlines())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plugin")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--base", default=gate.DEFAULT_BASE)
    parser.add_argument("--level", choices=gate.LEVELS)
    args = parser.parse_args(argv)

    repo = Path(args.repo)
    try:
        result = bump(repo, args.plugin, args.base, args.level)
    except (BumpError, StampError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    if result.changed:
        print(f"{result.plugin}: {result.released} -> {result.new} ({result.level} against {args.base})")
    else:
        print(f"{result.plugin}: already at {result.new}, past the {result.level} bump from {result.released}; nothing to do")
    for name in _changed_files(repo):
        print(f"  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
