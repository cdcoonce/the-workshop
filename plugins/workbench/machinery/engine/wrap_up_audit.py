#!/usr/bin/env python3
"""Deterministic collector for /wrap-up — a VERDICT, not raw data to re-derive.

`/wrap-up` steps 2-4 (validate each note, index sync, orphans) and the "which
handoff sections did this session touch" evidence for step 9 are mechanical:
they read frontmatter, wikilinks, index files, and a git diff, and compare
against fixed rules. This script runs those checks once, deterministically,
and returns a compact verdict (CLEAN / FINDINGS / INCOMPLETE) so the model
stops re-deriving them by hand every run.

Read-only. Never writes to the vault. Import graphmark lazily (inside
``_run_graph_checks``) so the frontmatter/wikilink/index checks still run
when graphmark is not importable — the graph checks alone degrade to
``not_run`` rather than the whole script failing.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from frontmatter_engine import validate as fm_validate  # noqa: E402
from vault_audit import (  # noqa: E402
    PERSONAL_INDEX_PREFIXES,
    WORK_INDEX_PREFIXES,
    _body,
    _index_links,
    _indexed,
    _is_transient,
    _links,
)
from vault_scope_resolved import (  # noqa: E402
    is_governed_markdown_note,
    is_graph_markdown_note,
    is_operating_file,
)
from vault_utils import find_vault_root, read_vault_context  # noqa: E402

HEADING_RE = re.compile(r"^## (.+?)\s*$")
HUNK_RE = re.compile(r"^@@ -(?:\d+)(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
PREAMBLE = "(preamble)"

CHECK_NAMES = (
    "frontmatter",
    "no_wikilinks",
    "unresolved_links",
    "orphans",
    "index_membership",
)


# ---------------------------------------------------------------------------
# git helpers
# ---------------------------------------------------------------------------

def _git(vault_root: Path, args: list[str]) -> str | None:
    """Run a git command in *vault_root*; None on any failure (never raises)."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=vault_root,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def _parse_porcelain(text: str) -> set[str]:
    paths: set[str] = set()
    for line in text.splitlines():
        if not line:
            continue
        rest = line[3:] if len(line) >= 3 else line.lstrip()
        if " -> " in rest:
            rest = rest.split(" -> ", 1)[1]
        rest = rest.strip()
        if rest.startswith('"') and rest.endswith('"'):
            rest = rest[1:-1]
        if rest:
            paths.add(rest)
    return paths


def _git_evidence_paths(vault_root: Path, base: str) -> tuple[set[str], bool, list[str]]:
    """Union of dirty (status) and base-diff paths. (paths, ok, warnings).

    ``ok`` is False only when BOTH git invocations fail outright (git missing,
    or this isn't a git repo at all) — a partial failure (e.g. a bad --base
    ref) still yields the evidence the other command produced, with a warning.
    """
    status_out = _git(vault_root, ["status", "--porcelain"])
    diff_out = _git(vault_root, ["diff", "--name-only", base])
    warnings: list[str] = []
    if status_out is None and diff_out is None:
        return set(), False, ["git status and git diff both failed"]

    paths: set[str] = set()
    if status_out is not None:
        paths |= _parse_porcelain(status_out)
    else:
        warnings.append("git status --porcelain failed")
    if diff_out is not None:
        paths |= {line.strip() for line in diff_out.splitlines() if line.strip()}
    else:
        warnings.append(f"git diff --name-only {base} failed (bad --base ref?)")
    return paths, True, warnings


# ---------------------------------------------------------------------------
# scope
# ---------------------------------------------------------------------------

@dataclass
class ScopeResult:
    claimed: list[str] = field(default_factory=list)
    source: str = "explicit"
    warnings: list[str] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)
    unclaimed_dirty: list[str] = field(default_factory=list)
    git_ok: bool = True


def _to_rel(raw: str, vault_root: Path) -> str | None:
    p = Path(raw)
    if p.is_absolute():
        try:
            return p.relative_to(vault_root).as_posix()
        except ValueError:
            pass
        try:
            return p.resolve().relative_to(vault_root.resolve()).as_posix()
        except ValueError:
            return None
    return p.as_posix()


def _classify_candidates(candidates: list[str], vault_root: Path) -> tuple[list[str], list[dict[str, str]]]:
    claimed: list[str] = []
    skipped: list[dict[str, str]] = []
    seen: set[str] = set()
    for rel in candidates:
        if rel in seen:
            continue
        seen.add(rel)
        full = vault_root / rel
        if not full.exists():
            skipped.append({"file": rel, "reason": "does not exist (deleted?)"})
            continue
        if full.suffix.lower() != ".md":
            skipped.append({"file": rel, "reason": "not a markdown note"})
            continue
        if is_operating_file(full):
            skipped.append({"file": rel, "reason": "operating file"})
            continue
        claimed.append(rel)
    return sorted(claimed), skipped


def _compute_scope(vault_root: Path, files: list[str] | None, base: str) -> ScopeResult:
    git_paths, git_ok, git_warnings = _git_evidence_paths(vault_root, base)

    warnings: list[str] = []
    if files is not None:
        source = "explicit"
        candidates: list[str] = []
        for raw in files:
            rel = _to_rel(raw, vault_root)
            if rel is None:
                warnings.append(f"--files entry outside vault root ignored: {raw}")
                continue
            candidates.append(rel)
    else:
        source = "git"
        if git_ok:
            candidates = sorted(git_paths)
            warnings.append(
                "scope_source is git: no --files was given, so scope is git status/diff "
                "evidence, which may include edits unrelated to this session"
            )
            warnings.extend(git_warnings)
        else:
            candidates = []
            warnings.append("git evidence unavailable; scope could not be determined")
            warnings.extend(git_warnings)

    claimed, skipped = _classify_candidates(candidates, vault_root)

    unclaimed_dirty: list[str] = []
    if git_ok:
        claimed_set = set(claimed)
        for rel in sorted(git_paths):
            if rel in claimed_set:
                continue
            full = vault_root / rel
            if not full.exists():
                continue
            if is_graph_markdown_note(full, vault_root):
                unclaimed_dirty.append(rel)

    return ScopeResult(
        claimed=claimed,
        source=source,
        warnings=warnings,
        skipped=skipped,
        unclaimed_dirty=unclaimed_dirty,
        git_ok=git_ok,
    )


# ---------------------------------------------------------------------------
# checks 1, 2, 5 — frontmatter, no_wikilinks, index_membership (scope-bound)
# ---------------------------------------------------------------------------

def _scoped_checks(vault_root: Path, claimed: list[str]) -> dict[str, list[dict[str, Any]]]:
    frontmatter: list[dict[str, Any]] = []
    no_wikilinks: list[dict[str, Any]] = []
    index_membership: list[dict[str, Any]] = []

    work_index_links = _index_links(vault_root / "work" / "Index.md")
    personal_index_links = _index_links(vault_root / "personal" / "Index.md")

    for rel in claimed:
        full = vault_root / rel
        governed = is_governed_markdown_note(full, vault_root)
        graph_note = is_graph_markdown_note(full, vault_root)

        if governed:
            for err in fm_validate(full, vault_root):
                frontmatter.append({
                    "check": "frontmatter",
                    "file": rel,
                    "detail": f"{err.field}: {err.message}",
                })

        if graph_note:
            body = _body(full).strip()
            note_links = [(is_embed, target) for is_embed, target in _links(full) if not is_embed]
            if len(body) > 300 and not note_links:
                no_wikilinks.append({
                    "check": "no_wikilinks",
                    "file": rel,
                    "detail": f"{len(body)} chars, no wikilinks",
                })

        if governed and not _is_transient(rel):
            if rel.startswith(WORK_INDEX_PREFIXES) and not _indexed(full, vault_root, work_index_links):
                index_membership.append({
                    "check": "index_membership",
                    "file": rel,
                    "detail": "missing from work/Index.md",
                })
            if rel.startswith(PERSONAL_INDEX_PREFIXES) and not _indexed(full, vault_root, personal_index_links):
                index_membership.append({
                    "check": "index_membership",
                    "file": rel,
                    "detail": "missing from personal/Index.md",
                })

    return {
        "frontmatter": frontmatter,
        "no_wikilinks": no_wikilinks,
        "index_membership": index_membership,
    }


# ---------------------------------------------------------------------------
# checks 3, 4 — unresolved_links, orphans (vault-wide, graphmark-backed)
# ---------------------------------------------------------------------------

def _run_graph_checks(vault_root: Path, claimed_set: set[str]) -> dict[str, Any]:
    """Build the vault graph and derive unresolved_links / orphans findings.

    Reuses ``graph_cli.build(vault_root)`` (plugins/workbench/machinery/engine/
    graph_cli.py:68-78) for the VaultConfig — same shape as the CI gate
    (``ci/vault_health.py``): scoped_folders=GRAPH_NOTE_DIRS,
    excluded_dirs=GRAPH_EXCLUDED_DIRS, rules_files=OPERATING_FILENAMES,
    transient_prefixes=TRANSIENT_PREFIXES. ``graph_cli`` also re-exports
    graphmark's ``orphans`` directly (identical to ``graphmark.check.orphans``).

    Imported here rather than at module scope: ``graph_cli`` imports
    ``graphmark`` eagerly at ITS module level, so a vault without graphmark
    installed must not lose the frontmatter/wikilink/index checks over it —
    only this function's result degrades to ``not_run``.
    """
    import graph_cli  # noqa: PLC0415

    graph, cfg = graph_cli.build(vault_root)

    unresolved_findings: list[dict[str, Any]] = []
    for source_rel in sorted(graph.unresolved):
        in_scope = source_rel in claimed_set
        for target in graph.unresolved[source_rel]:
            unresolved_findings.append({
                "check": "unresolved_links",
                "file": source_rel,
                "detail": f"broken [[{target}]]",
                "in_scope": in_scope,
            })

    orphan_paths = graph_cli.orphans(graph, cfg)
    orphan_findings = [
        {"check": "orphans", "file": rel, "detail": "no links in or out (graph degree 0)"}
        for rel in sorted(orphan_paths)
        if rel in claimed_set
    ]

    return {
        "unresolved_links": unresolved_findings,
        "orphans": orphan_findings,
        "orphans_vault_wide_count": len(orphan_paths),
    }


# ---------------------------------------------------------------------------
# check 6 — handoff_sections (not pass/fail; evidence for step 9)
# ---------------------------------------------------------------------------

def _extract_headings(text: str) -> list[tuple[int, str]]:
    headings: list[tuple[int, str]] = []
    for i, line in enumerate(text.splitlines(), start=1):
        m = HEADING_RE.match(line)
        if m:
            headings.append((i, m.group(1)))
    return headings


def _nearest_heading_at_or_before(headings: list[tuple[int, str]], line_no: int) -> str | None:
    result: str | None = None
    for hl, htext in headings:
        if hl <= line_no:
            result = htext
        else:
            break
    return result


def _parse_diff_new_line_numbers(diff_text: str) -> list[int]:
    lines_out: list[int] = []
    for line in diff_text.splitlines():
        m = HUNK_RE.match(line)
        if not m:
            continue
        new_start = int(m.group(1))
        new_count = int(m.group(2)) if m.group(2) is not None else 1
        if new_count == 0:
            # Pure deletion: anchor on the insertion point in the new file.
            lines_out.append(new_start)
        else:
            lines_out.extend(range(new_start, new_start + new_count))
    return lines_out


def _handoff_sections(vault_root: Path, base: str) -> dict[str, Any]:
    ctx = read_vault_context(vault_root)
    handoff_rel = f".brain/handoff-{ctx}.md"
    handoff_path = vault_root / handoff_rel
    result: dict[str, Any] = {
        "file": handoff_rel,
        "present": [],
        "touched": [],
        "not_run": None,
    }

    if not handoff_path.exists():
        # No handoff has ever been written for this context — a legitimate
        # state (e.g. a fresh vault), not a failure: nothing to report as
        # touched, and this is not a reason to go INCOMPLETE.
        return result

    text = handoff_path.read_text(encoding="utf-8", errors="replace")
    headings = _extract_headings(text)
    result["present"] = [h for _, h in headings]

    tracked = _git(vault_root, ["ls-files", "--error-unmatch", handoff_rel]) is not None
    if not tracked:
        result["touched"] = list(result["present"])
        return result

    diff_out = _git(vault_root, ["diff", "-U0", base, "--", handoff_rel])
    if diff_out is None:
        result["not_run"] = f"git diff -U0 {base} -- {handoff_rel} failed"
        return result
    if diff_out.strip() == "":
        result["touched"] = []
        return result

    touched_lines = _parse_diff_new_line_numbers(diff_out)
    touched_set = {
        _nearest_heading_at_or_before(headings, line_no) or PREAMBLE
        for line_no in touched_lines
    }
    order = [PREAMBLE] + [h for _, h in headings]
    result["touched"] = [h for h in order if h in touched_set]
    return result


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------

def _cap(findings: list[dict[str, Any]], limit: int) -> tuple[list[dict[str, Any]], int]:
    if limit <= 0 or len(findings) <= limit:
        return findings, 0
    return findings[:limit], len(findings) - limit


def collect(vault_root: Path, files: list[str] | None, base: str = "HEAD", limit: int = 20) -> dict[str, Any]:
    scope = _compute_scope(vault_root, files, base)
    claimed_set = set(scope.claimed)
    not_run: list[dict[str, str]] = []

    if scope.source == "git" and not scope.git_ok:
        reason = "scope undetermined: git evidence unavailable"
        for name in ("frontmatter", "no_wikilinks", "index_membership"):
            not_run.append({"check": name, "reason": reason})
        scoped = {"frontmatter": [], "no_wikilinks": [], "index_membership": []}
    else:
        scoped = _scoped_checks(vault_root, scope.claimed)

    graph_error: str | None = None
    try:
        graph_results = _run_graph_checks(vault_root, claimed_set)
    except Exception as exc:  # noqa: BLE001 - any import/build failure degrades to not_run
        graph_error = f"{type(exc).__name__}: {exc}"
        graph_results = None

    if graph_results is None:
        reason = f"graphmark unavailable: {graph_error}"
        not_run.append({"check": "unresolved_links", "reason": reason})
        not_run.append({"check": "orphans", "reason": reason})
        unresolved_findings: list[dict[str, Any]] = []
        orphan_findings: list[dict[str, Any]] = []
        orphans_vault_wide_count = None
    else:
        unresolved_findings = graph_results["unresolved_links"]
        orphan_findings = graph_results["orphans"]
        orphans_vault_wide_count = graph_results["orphans_vault_wide_count"]

    handoff = _handoff_sections(vault_root, base)
    if handoff.get("not_run"):
        not_run.append({"check": "handoff_sections", "reason": handoff["not_run"]})

    frontmatter_findings, frontmatter_elided = _cap(scoped["frontmatter"], limit)
    no_wikilinks_findings, no_wikilinks_elided = _cap(scoped["no_wikilinks"], limit)
    index_findings, index_elided = _cap(scoped["index_membership"], limit)
    unresolved_capped, unresolved_elided = _cap(unresolved_findings, limit)
    orphan_capped, orphan_elided = _cap(orphan_findings, limit)

    total_findings = (
        len(scoped["frontmatter"])
        + len(scoped["no_wikilinks"])
        + len(unresolved_findings)
        + len(orphan_findings)
        + len(scoped["index_membership"])
    )

    if not_run:
        verdict = "INCOMPLETE"
    elif total_findings > 0:
        verdict = "FINDINGS"
    else:
        verdict = "CLEAN"

    skipped_capped, skipped_elided = _cap(scope.skipped, limit)
    unclaimed_capped = scope.unclaimed_dirty[:limit]
    unclaimed_elided = max(0, len(scope.unclaimed_dirty) - limit) if limit > 0 else 0

    return {
        "verdict": verdict,
        "vault_root": str(vault_root),
        "scope": {
            "source": scope.source,
            "files": scope.claimed,
            "warnings": scope.warnings,
            "skipped": skipped_capped,
            "skipped_count": len(scope.skipped),
            "skipped_elided": skipped_elided,
            "unclaimed_dirty": unclaimed_capped,
            "unclaimed_dirty_count": len(scope.unclaimed_dirty),
            "unclaimed_dirty_elided": unclaimed_elided,
        },
        "checks": {
            "frontmatter": {
                "count": len(scoped["frontmatter"]),
                "findings": frontmatter_findings,
                "elided": frontmatter_elided,
            },
            "no_wikilinks": {
                "count": len(scoped["no_wikilinks"]),
                "findings": no_wikilinks_findings,
                "elided": no_wikilinks_elided,
            },
            "unresolved_links": {
                "count": len(unresolved_findings),
                "findings": unresolved_capped,
                "elided": unresolved_elided,
            },
            "orphans": {
                "count": len(orphan_findings),
                "findings": orphan_capped,
                "elided": orphan_elided,
                "vault_wide_count": orphans_vault_wide_count,
            },
            "index_membership": {
                "count": len(scoped["index_membership"]),
                "findings": index_findings,
                "elided": index_elided,
            },
            "handoff_sections": handoff,
        },
        "not_run": not_run,
        "limit": limit,
    }


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------

def _render_check(lines: list[str], title: str, node: dict[str, Any]) -> None:
    count = node["count"]
    if count == 0:
        lines.append(f"- {title}: clean")
        return
    lines.append(f"- {title} ({count}):")
    for f in node["findings"]:
        in_scope = f.get("in_scope")
        suffix = "" if in_scope is None else f" (in_scope: {str(in_scope).lower()})"
        lines.append(f"  - `{f['file']}`: {f['detail']}{suffix}")
    if node["elided"]:
        lines.append(f"  - ... {node['elided']} more")


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"## Wrap-Up Audit — {report['verdict']}",
        "",
        "### Scope",
        f"- source: {report['scope']['source']}",
        f"- files ({len(report['scope']['files'])}): "
        + (", ".join(f"`{f}`" for f in report["scope"]["files"]) or "(none)"),
    ]
    for w in report["scope"]["warnings"]:
        lines.append(f"- warning: {w}")
    if report["scope"]["skipped_count"]:
        lines.append(f"- skipped ({report['scope']['skipped_count']}):")
        for s in report["scope"]["skipped"]:
            lines.append(f"  - `{s['file']}`: {s['reason']}")
        if report["scope"]["skipped_elided"]:
            lines.append(f"  - ... {report['scope']['skipped_elided']} more")
    if report["scope"]["unclaimed_dirty_count"]:
        lines.append(f"- unclaimed dirty ({report['scope']['unclaimed_dirty_count']}, informational):")
        for u in report["scope"]["unclaimed_dirty"]:
            lines.append(f"  - `{u}`")
        if report["scope"]["unclaimed_dirty_elided"]:
            lines.append(f"  - ... {report['scope']['unclaimed_dirty_elided']} more")
    else:
        lines.append("- unclaimed dirty: none")
    lines.append("")

    lines.append("### Checks")
    checks = report["checks"]
    _render_check(lines, "Frontmatter", checks["frontmatter"])
    _render_check(lines, "No Wikilinks", checks["no_wikilinks"])
    _render_check(lines, "Unresolved Links (vault-wide)", checks["unresolved_links"])
    orphans_node = dict(checks["orphans"])
    vw = orphans_node["vault_wide_count"]
    orphans_title = "Orphans (in-scope)" + (f" — {vw} vault-wide" if vw is not None else "")
    _render_check(lines, orphans_title, orphans_node)
    _render_check(lines, "Index Membership", checks["index_membership"])
    lines.append("")

    handoff = checks["handoff_sections"]
    lines.append(f"### Handoff Sections (`{handoff['file']}`)")
    if handoff.get("not_run"):
        lines.append(f"- not run: {handoff['not_run']}")
    else:
        lines.append(f"- present: {', '.join(handoff['present']) or '(none)'}")
        lines.append(f"- touched: {', '.join(handoff['touched']) or '(none)'}")
    lines.append("")

    lines.append("### Not Run")
    if report["not_run"]:
        for nr in report["not_run"]:
            lines.append(f"- {nr['check']}: {nr['reason']}")
    else:
        lines.append("- (none)")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

VERDICT_EXIT_CODES = {"CLEAN": 0, "FINDINGS": 1, "INCOMPLETE": 2}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Deterministic /wrap-up audit collector — returns a session VERDICT."
    )
    parser.add_argument("--vault-root", type=Path)
    parser.add_argument(
        "--files", nargs="*", default=None,
        help="The session's claimed files (vault-relative or absolute). "
             "Omit to fall back to git status/diff evidence.",
    )
    parser.add_argument("--base", default="HEAD", help="Git ref to diff against (default HEAD).")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of Markdown.")
    parser.add_argument("--limit", type=int, default=20, help="Max finding rows per check.")
    args = parser.parse_args(argv)

    vault_root = args.vault_root.resolve() if args.vault_root else find_vault_root()
    if vault_root is None or not vault_root.is_dir():
        print("ERROR: vault root not found", file=sys.stderr)
        return VERDICT_EXIT_CODES["INCOMPLETE"]

    report = collect(vault_root, files=args.files, base=args.base, limit=args.limit)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(render_markdown(report))

    return VERDICT_EXIT_CODES[report["verdict"]]


if __name__ == "__main__":
    raise SystemExit(main())
