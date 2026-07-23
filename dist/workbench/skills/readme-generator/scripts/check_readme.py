#!/usr/bin/env python3
"""Staleness / consistency checker for a README maintained by readme-generator.

Reads the provenance footer readme-generator stamps into the README:

    <!-- readme-generator: baseline=<sha> covers=<comma,separated,paths> -->

where `covers` is the README's front-door anchors (dependency manifests, env
templates, CI configs, entry points). Reports two drift signals using only the
repo, so it runs in CI and on any clone:

  * missing-path   -- an anchor no longer exists (moved or deleted)
  * changed-source -- anchors changed since the baseline commit
                      (best-effort; skipped when git or the baseline is absent)

Exits non-zero when anything is reported. Standard library only; fails open
(prints a warning, exits 0) on its own error.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_PROVENANCE = re.compile(
    r"<!--\s*readme-generator:\s*baseline=(?P<baseline>\S+)\s+"
    r"covers=(?P<covers>[^\s>]+)\s*-->"
)


@dataclass(frozen=True)
class Finding:
    """One drift signal against the README."""

    kind: str
    detail: str


def _covered(text: str) -> tuple[str | None, list[str]]:
    match = _PROVENANCE.search(text)
    if match is None:
        return None, []
    covers = [p.strip() for p in match.group("covers").split(",") if p.strip()]
    return match.group("baseline"), covers


def _changed_since(baseline: str, paths: list[str], repo_root: Path) -> list[str]:
    """Anchors with commits after `baseline`; empty on any git failure."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "diff", "--name-only", f"{baseline}..HEAD", "--", *paths],
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, ValueError):
        return []
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def check_readme(readme_path: Path, *, repo_root: Path) -> list[Finding]:
    """Return drift findings for a single README file."""
    if not readme_path.is_file():
        return []
    baseline, covers = _covered(readme_path.read_text(encoding="utf-8"))
    if not covers:
        return []
    findings: list[Finding] = [
        Finding("missing-path", f"{rel} (anchor not found)")
        for rel in covers
        if not (repo_root / rel).exists()
    ]
    if baseline:
        findings.extend(
            Finding("changed-source", f"{rel} changed since {baseline}")
            for rel in _changed_since(baseline, covers, repo_root)
        )
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check README freshness.")
    parser.add_argument("--readme", default="README.md", help="Path to the README.")
    parser.add_argument("--repo-root", default=".", help="Repository root.")
    args = parser.parse_args(argv)

    try:
        readme = Path(args.readme)
        if not readme.is_file():
            print(f"readme-generator: no README at {readme}; nothing to check.")
            return 0
        findings = check_readme(readme, repo_root=Path(args.repo_root))
    except Exception as error:  # noqa: BLE001 -- fail open, never block on our own bug
        print(f"readme-generator: checker error, skipping: {error}", file=sys.stderr)
        return 0

    if not findings:
        print("readme-generator: README is consistent with its front-door anchors.")
        return 0

    print(f"readme-generator: {len(findings)} drift finding(s):")
    for finding in findings:
        print(f"  [{finding.kind}] {finding.detail}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
