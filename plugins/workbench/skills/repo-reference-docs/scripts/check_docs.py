#!/usr/bin/env python3
"""Staleness / consistency checker for repo-reference-docs.

Reads the provenance footer that repo-reference-docs stamps into each doc and
into the root README:

    <!-- repo-reference-docs: baseline=<sha> covers=<comma,separated,paths> -->

READMEs written before this skill absorbed `readme-generator` carry that skill's
`<!-- readme-generator: ... -->` footer; it is accepted as an equivalent marker
so an already-stamped README is never mistaken for an unstamped one.

It reports two drift signals, using only the repo itself (no machine-local
state), so it runs in CI and on any teammate's clone:

  * missing-path   -- a covered path no longer exists (moved or deleted)
  * changed-source -- covered paths changed since the baseline commit
                      (best-effort; skipped when git or the baseline is absent)

Exit code is non-zero when any finding is reported, so CI can gate on it.
Standard library only; fails open (prints a warning, exits 0) on its own error.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_PROVENANCE = re.compile(
    r"<!--\s*(?:repo-reference-docs|readme-generator):\s*baseline=(?P<baseline>\S+)\s+"
    r"covers=(?P<covers>[^\s>]+)\s*-->"
)


@dataclass(frozen=True)
class Finding:
    """One drift signal against a single reference doc."""

    doc: str
    kind: str
    detail: str


def _covered_paths(text: str) -> tuple[str | None, list[str]]:
    match = _PROVENANCE.search(text)
    if match is None:
        return None, []
    covers = [p.strip() for p in match.group("covers").split(",") if p.strip()]
    return match.group("baseline"), covers


def _changed_since(baseline: str, paths: list[str], repo_root: Path) -> list[str]:
    """Covered paths with commits after `baseline`; empty on any git failure."""
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


def _check_one(doc: Path, *, label: str, repo_root: Path) -> list[Finding]:
    """Return drift findings for a single stamped Markdown file."""
    baseline, covers = _covered_paths(doc.read_text(encoding="utf-8"))
    if not covers:
        return []
    findings = [
        Finding(label, "missing-path", f"{rel} (covered but not found)")
        for rel in covers
        if not (repo_root / rel).exists()
    ]
    if baseline:
        findings.extend(
            Finding(label, "changed-source", f"{rel} changed since {baseline}")
            for rel in _changed_since(baseline, covers, repo_root)
        )
    return findings


def check_docs(
    docs_dir: Path, *, repo_root: Path, readme: Path | None = None
) -> list[Finding]:
    """Return drift findings for the root README and every doc under `docs_dir`."""
    findings: list[Finding] = []
    if readme is not None and readme.is_file():
        findings.extend(_check_one(readme, label=readme.name, repo_root=repo_root))
    if docs_dir.is_dir():
        for doc in sorted(docs_dir.rglob("*.md")):
            findings.extend(_check_one(doc, label=doc.name, repo_root=repo_root))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check repo-reference-docs freshness.")
    parser.add_argument("--docs-dir", default="docs/reference", help="Reference docs directory.")
    parser.add_argument("--repo-root", default=".", help="Repository root.")
    parser.add_argument("--readme", default="README.md", help="Path to the root README.")
    args = parser.parse_args(argv)

    try:
        docs_dir = Path(args.docs_dir)
        repo_root = Path(args.repo_root)
        readme = Path(args.readme)
        if not docs_dir.is_dir() and not readme.is_file():
            print(
                f"repo-reference-docs: no README at {readme} and no docs at {docs_dir}; "
                "nothing to check."
            )
            return 0
        findings = check_docs(docs_dir, repo_root=repo_root, readme=readme)
    except Exception as error:  # noqa: BLE001 -- fail open, never block on our own bug
        print(f"repo-reference-docs: checker error, skipping: {error}", file=sys.stderr)
        return 0

    if not findings:
        print("repo-reference-docs: README and reference docs are consistent with the source.")
        return 0

    print(f"repo-reference-docs: {len(findings)} drift finding(s):")
    for finding in findings:
        print(f"  [{finding.kind}] {finding.doc}: {finding.detail}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
