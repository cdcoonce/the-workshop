#!/usr/bin/env python3
"""Drift, link, mode, and landing-bar checker for repo-docs.

Reads the provenance footer that repo-docs stamps into every doc and into the
root README:

    <!-- repo-docs: mode=<mode> baseline=<sha> covers=<comma,separated,paths> -->

Docs stamped by the retired ``repo-reference-docs`` and ``readme-generator``
skills carry those names and no mode. Both are accepted as equivalent markers,
so an already-stamped doc is never mistaken for an unstamped one; a legacy doc
is re-stamped with a mode on its next rewrite, not failed here.

Findings, computed from the repo alone (no machine-local state) so the check
runs in CI and on any clone:

  * missing-path    a covered path no longer exists (moved or deleted)
  * changed-source  covered paths changed since the baseline commit
                    (best-effort; skipped when git or the baseline is absent)
  * broken-link     a relative Markdown link whose target file does not exist
  * mode-mismatch   a doc's declared mode disagrees with the directory it lives
                    in, or a non-README claims to be a landing page
  * readme-length   the README is longer than the landing-page bar

Process directories under docs/ (plans, archive, reviews, dev-cycle) are not
documentation in the Diátaxis sense and are skipped entirely; ``--exempt`` adds
more. Links inside fenced code blocks are ignored: a fence is the author saying
"this is an example, not a link".

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
from urllib.parse import unquote

MODES = ("tutorial", "how-to", "reference", "explanation")
LANDING = "landing"
# Directory name under docs/ -> the one mode its files may declare.
MODE_DIRS = {
    "tutorials": "tutorial",
    "how-to": "how-to",
    "reference": "reference",
    "explanation": "explanation",
}
DIR_FOR_MODE = {mode: folder for folder, mode in MODE_DIRS.items()}
DEFAULT_EXEMPT = frozenset(
    {
        "plans",
        "archive",
        "code_reviews",
        "code-reviews",
        "security-reviews",
        "security_reviews",
        "review",
        "reviews",
        "mr-reviews",
        "dev-cycle",
    }
)
DEFAULT_README_MAX_LINES = 150

_PROVENANCE = re.compile(
    r"<!--\s*(?:repo-docs|repo-reference-docs|readme-generator):\s*"
    r"(?:mode=(?P<mode>[A-Za-z-]+)\s+)?"
    r"baseline=(?P<baseline>\S+)\s+covers=(?P<covers>[^\s>]+)\s*-->"
)
# Inline links and images: [text](target), ![alt](target), with an optional
# "title" and optional <angle brackets> around the target.
_LINK = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
_FENCE = re.compile(r"^\s*(```|~~~)")
_SKIP_SCHEMES = ("mailto:", "tel:", "#")


@dataclass(frozen=True)
class Finding:
    """One signal against a single doc; ``doc`` is the path relative to the repo root."""

    doc: str
    kind: str
    detail: str


@dataclass(frozen=True)
class Provenance:
    mode: str | None
    baseline: str | None
    covers: tuple[str, ...]


def _provenance(text: str) -> Provenance | None:
    """The doc's own footer: the last stamp outside any code fence.

    Templates quote example footers inside fences; those are illustrations, not
    provenance, and must never make a reference file read as a stamped doc.
    """
    matches = list(_PROVENANCE.finditer(_outside_fences(text)))
    if not matches:
        return None
    match = matches[-1]
    covers = tuple(p.strip() for p in match.group("covers").split(",") if p.strip())
    return Provenance(match.group("mode"), match.group("baseline"), covers)


def _outside_fences(text: str) -> str:
    """Drop every line inside a ``` or ~~~ fence; templates carry example links."""
    kept: list[str] = []
    fence: str | None = None
    for line in text.splitlines():
        marker = _FENCE.match(line)
        if marker:
            token = marker.group(1)
            if fence is None:
                fence = token
            elif token == fence:
                fence = None
            continue
        if fence is None:
            kept.append(line)
    return "\n".join(kept)


def _relative_targets(text: str) -> list[str]:
    targets: list[str] = []
    for raw in _LINK.findall(_outside_fences(text)):
        if "://" in raw or raw.startswith(_SKIP_SCHEMES):
            continue
        target = unquote(raw.split("#", 1)[0])
        if target:
            targets.append(target)
    return targets


def _changed_since(baseline: str, paths: tuple[str, ...], repo_root: Path) -> list[str]:
    """Covered paths with commits after ``baseline``; empty on any git failure."""
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


def _mode_finding(doc: Path, mode: str | None, *, label: str, docs_root: Path) -> Finding | None:
    if mode is None:
        return None
    if mode == LANDING:
        if doc.name == "README.md":
            return None
        return Finding(label, "mode-mismatch", "mode=landing is only valid on a README.md")
    if mode not in MODES:
        return Finding(
            label, "mode-mismatch", f"unknown mode '{mode}'; expected one of {', '.join(MODES)}"
        )
    expected = f"docs/{DIR_FOR_MODE[mode]}/"
    try:
        rel = doc.resolve().relative_to(docs_root.resolve())
    except ValueError:
        return Finding(label, "mode-mismatch", f"declares mode={mode} but lives outside {expected}")
    folder = rel.parts[0] if len(rel.parts) > 1 else None
    if folder is None or MODE_DIRS.get(folder) != mode:
        where = f"docs/{folder}/" if folder else "docs/"
        return Finding(
            label, "mode-mismatch", f"declares mode={mode} but lives in {where}; expected {expected}"
        )
    return None


def _check_one(
    doc: Path,
    *,
    repo_root: Path,
    docs_root: Path,
    readme_max_lines: int | None = None,
) -> list[Finding]:
    """Every finding for a single Markdown file."""
    text = doc.read_text(encoding="utf-8")
    try:
        label = doc.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        label = doc.name
    findings: list[Finding] = []

    provenance = _provenance(text)
    if provenance is not None:
        findings.extend(
            Finding(label, "missing-path", f"{rel} (covered but not found)")
            for rel in provenance.covers
            if not (repo_root / rel).exists()
        )
        if provenance.baseline:
            findings.extend(
                Finding(label, "changed-source", f"{rel} changed since {provenance.baseline}")
                for rel in _changed_since(provenance.baseline, provenance.covers, repo_root)
            )
        mismatch = _mode_finding(doc, provenance.mode, label=label, docs_root=docs_root)
        if mismatch is not None:
            findings.append(mismatch)

    for target in _relative_targets(text):
        resolved = (repo_root / target.lstrip("/")) if target.startswith("/") else (doc.parent / target)
        if not resolved.exists():
            findings.append(Finding(label, "broken-link", f"{target} (linked but not found)"))

    if readme_max_lines:
        lines = len(text.splitlines())
        if lines > readme_max_lines:
            findings.append(
                Finding(
                    label, "readme-length", f"{lines} lines; landing-page bar is {readme_max_lines}"
                )
            )
    return findings


def check_docs(
    docs_dir: Path,
    *,
    repo_root: Path,
    readme: Path | None = None,
    readme_max_lines: int = DEFAULT_README_MAX_LINES,
    exempt: tuple[str, ...] | list[str] = (),
) -> list[Finding]:
    """Return every finding for the root README and every doc under ``docs_dir``.

    ``docs_dir`` is normally ``docs``; a mode directory such as ``docs/reference``
    is accepted and its parent is used to resolve modes.
    """
    exempt_set = DEFAULT_EXEMPT | frozenset(exempt)
    docs_root = docs_dir.parent if docs_dir.name in MODE_DIRS else docs_dir
    findings: list[Finding] = []
    if readme is not None and readme.is_file():
        findings.extend(
            _check_one(
                readme, repo_root=repo_root, docs_root=docs_root, readme_max_lines=readme_max_lines
            )
        )
    if docs_dir.is_dir():
        for doc in sorted(docs_dir.rglob("*.md")):
            rel = doc.relative_to(docs_dir)
            if any(part in exempt_set for part in rel.parts[:-1]):
                continue
            findings.extend(_check_one(doc, repo_root=repo_root, docs_root=docs_root))
    return findings


def _parse_exempt(values: list[str] | None) -> tuple[str, ...]:
    names: list[str] = []
    for value in values or []:
        names.extend(v.strip() for v in value.split(",") if v.strip())
    return tuple(names)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check repo-docs freshness, links, and modes.")
    parser.add_argument("--docs-dir", default="docs", help="Documentation root (default: docs).")
    parser.add_argument("--repo-root", default=".", help="Repository root.")
    parser.add_argument("--readme", default="README.md", help="Path to the root README.")
    parser.add_argument(
        "--readme-max-lines",
        type=int,
        default=DEFAULT_README_MAX_LINES,
        help="Landing-page bar for the README; 0 disables the check.",
    )
    parser.add_argument(
        "--exempt",
        action="append",
        help="Extra docs/ subdirectory names to skip (comma-separated, repeatable).",
    )
    args = parser.parse_args(argv)

    try:
        repo_root = Path(args.repo_root)
        docs_dir = Path(args.docs_dir)
        readme = Path(args.readme)
        # Relative paths are relative to the repo, not to wherever the script was
        # launched: the skill runs it from its own base directory.
        if not docs_dir.is_absolute():
            docs_dir = repo_root / docs_dir
        if not readme.is_absolute():
            readme = repo_root / readme
        if not docs_dir.is_dir() and not readme.is_file():
            print(f"repo-docs: no README at {readme} and no docs at {docs_dir}; nothing to check.")
            return 0
        findings = check_docs(
            docs_dir,
            repo_root=repo_root,
            readme=readme,
            readme_max_lines=args.readme_max_lines,
            exempt=_parse_exempt(args.exempt),
        )
    except Exception as error:  # noqa: BLE001 -- fail open, never block on our own bug
        print(f"repo-docs: checker error, skipping: {error}", file=sys.stderr)
        return 0

    if not findings:
        print("repo-docs: README and docs are consistent with the source.")
        return 0

    print(f"repo-docs: {len(findings)} finding(s):")
    for finding in findings:
        print(f"  [{finding.kind}] {finding.doc}: {finding.detail}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
