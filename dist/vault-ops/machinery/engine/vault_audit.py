#!/usr/bin/env python3
"""Read-only structural audit for the My Brain vault.

This is the executable counterpart to `.claude/commands/vault-audit.md`.
It is deliberately deterministic and local: no LLM calls, no writes.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from frontmatter_engine import _parse_frontmatter, validate  # noqa: E402
from vault_scope import (  # noqa: E402
    TRANSIENT_PREFIXES,
    is_operating_file,
    is_root_excluded_file,
    is_governed_markdown_note,
    iter_governed_markdown_notes,
    iter_graph_markdown_notes,
    rel_posix,
)
from vault_utils import find_vault_root  # noqa: E402

WIKILINK_RE = re.compile(r"(!?)\[\[([^\]\n]+)\]\]")
FENCED_CODE_RE = re.compile(r"(^|\n)```.*?(?:\n```|$)", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
OBSIDIAN_BASE_RECOMMENDATIONS = (
    "Decisions.base",
    "People Missing Context.base",
    "Archive Candidates.base",
    "Thinking Promotion Queue.base",
    "Stale Active Work.base",
)


@dataclass
class Issue:
    file: str
    detail: str


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _strip_target(raw: str) -> str:
    target = raw.split("|", 1)[0].split("#", 1)[0].strip()
    return target[:-3] if target.endswith(".md") else target


def _norm_title(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _frontmatter(path: Path) -> dict[str, Any]:
    fm, _, _ = _parse_frontmatter(_read(path))
    return fm or {}


def _body(path: Path) -> str:
    _, body, _ = _parse_frontmatter(_read(path))
    return body


def _is_transient(rel: str) -> bool:
    return rel.startswith(TRANSIENT_PREFIXES)


def _catalog(vault_root: Path) -> tuple[dict[str, Path], dict[str, list[Path]]]:
    """Build exact/path/stem/normalized resolution catalogs."""
    exact: dict[str, Path] = {}
    normalized: dict[str, list[Path]] = defaultdict(list)

    resolvable = list({
        *iter_graph_markdown_notes(vault_root),
        *iter_governed_markdown_notes(vault_root),
    })
    resolvable.extend(
        p for p in vault_root.rglob("*.md")
        if is_operating_file(p) or is_root_excluded_file(p, vault_root)
    )
    bases_dir = vault_root / "bases"
    if bases_dir.is_dir():
        resolvable.extend(sorted(bases_dir.glob("*.base")))

    for path in resolvable:
        rel = rel_posix(path, vault_root)
        if rel is None:
            continue
        no_ext = rel.rsplit(".", 1)[0]
        exact[rel] = path
        exact[no_ext] = path
        exact[path.name] = path
        exact[path.stem] = path
        normalized[_norm_title(path.stem)].append(path)
        fm = _frontmatter(path)
        aliases = fm.get("aliases", [])
        if isinstance(aliases, str):
            aliases = [aliases]
        if isinstance(aliases, list):
            for alias in aliases:
                if isinstance(alias, str) and alias.strip():
                    exact[alias.strip()] = path
                    normalized[_norm_title(alias)].append(path)
        name = fm.get("name")
        if isinstance(name, str) and name.strip():
            exact[name.strip()] = path
            normalized[_norm_title(name)].append(path)
    return exact, normalized


def _resolve(target: str, exact: dict[str, Path], normalized: dict[str, list[Path]]) -> list[Path]:
    if target in exact:
        return [exact[target]]
    if f"{target}.md" in exact:
        return [exact[f"{target}.md"]]
    if f"{target}.base" in exact:
        return [exact[f"{target}.base"]]
    return normalized.get(_norm_title(Path(target).name), [])


def _code_spans(text: str) -> list[tuple[int, int]]:
    spans = [(m.start(), m.end()) for m in FENCED_CODE_RE.finditer(text)]
    spans.extend((m.start(), m.end()) for m in INLINE_CODE_RE.finditer(text))
    return spans


def _inside_spans(pos: int, spans: list[tuple[int, int]]) -> bool:
    return any(start <= pos < end for start, end in spans)


def _links(path: Path) -> list[tuple[bool, str]]:
    out: list[tuple[bool, str]] = []
    text = _read(path)
    code_spans = _code_spans(text)
    for match in WIKILINK_RE.finditer(text):
        if _inside_spans(match.start(), code_spans):
            continue
        bang, raw = match.groups()
        target = _strip_target(raw)
        if target:
            out.append((bool(bang), target))
    return out


def _index_links(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {target for is_embed, target in _links(path) if not is_embed}


def _indexed(path: Path, vault_root: Path, linkset: set[str]) -> bool:
    rel = rel_posix(path, vault_root)
    if rel is None:
        return False
    candidates = {path.stem, rel.rsplit(".", 1)[0]}
    return bool(candidates & linkset)


def audit(vault_root: Path, today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    governed = iter_governed_markdown_notes(vault_root)
    graph_notes = iter_graph_markdown_notes(vault_root)
    exact, normalized = _catalog(vault_root)

    frontmatter_issues: list[Issue] = []
    for path in governed:
        rel = rel_posix(path, vault_root) or str(path)
        for err in validate(path, vault_root):
            frontmatter_issues.append(Issue(rel, f"{err.field}: {err.message}"))

    no_wikilinks: list[Issue] = []
    broken_links: list[Issue] = []
    ambiguous_links: list[Issue] = []
    incoming: dict[Path, set[Path]] = defaultdict(set)

    for path in graph_notes:
        body = _body(path).strip()
        rel = rel_posix(path, vault_root) or str(path)
        note_links = [(is_embed, target) for is_embed, target in _links(path) if not is_embed]
        if len(body) > 300 and not note_links:
            no_wikilinks.append(Issue(rel, f"{len(body)} chars, no wikilinks"))
        for _, target in note_links:
            matches = _resolve(target, exact, normalized)
            if len(matches) == 1:
                incoming[matches[0]].add(path)
            elif len(matches) == 0:
                broken_links.append(Issue(rel, f"broken [[{target}]]"))
            else:
                sample = ", ".join(rel_posix(m, vault_root) or str(m) for m in matches[:3])
                ambiguous_links.append(Issue(rel, f"ambiguous [[{target}]] -> {sample}"))

    orphans: list[Issue] = []
    for path in graph_notes:
        rel = rel_posix(path, vault_root) or str(path)
        if _is_transient(rel):
            continue
        if rel in {
            "brain/Memories.md",
            "brain/North Star.md",
            "brain/Key Decisions.md",
            "brain/Patterns.md",
            "brain/Gotchas.md",
            "brain/Capabilities.md",
            "work/Index.md",
            "personal/Index.md",
            "org/People & Context.md",
            "perf/Brag Doc.md",
        }:
            continue
        if len(_body(path).strip()) > 300 and not incoming[path]:
            orphans.append(Issue(rel, "no incoming backlinks"))

    work_index_links = _index_links(vault_root / "work" / "Index.md")
    personal_index_links = _index_links(vault_root / "personal" / "Index.md")
    work_prefixes = ("work/active/", "work/archive/", "work/decisions/", "work/incidents/", "work/1-1/")
    personal_prefixes = ("personal/learning/", "personal/projects/", "personal/ideas/", "personal/decisions/")
    work_not_indexed: list[Issue] = []
    personal_not_indexed: list[Issue] = []
    for path in governed:
        rel = rel_posix(path, vault_root) or ""
        if _is_transient(rel):
            continue
        if rel.startswith(work_prefixes) and not _indexed(path, vault_root, work_index_links):
            work_not_indexed.append(Issue(rel, "missing from work/Index.md"))
        if rel.startswith(personal_prefixes) and not _indexed(path, vault_root, personal_index_links):
            personal_not_indexed.append(Issue(rel, "missing from personal/Index.md"))

    stale_active: list[Issue] = []
    now = datetime.now()
    for path in governed:
        fm = _frontmatter(path)
        if str(fm.get("status", "")) != "active":
            continue
        rel = rel_posix(path, vault_root) or str(path)
        mtime_age = (now - datetime.fromtimestamp(path.stat().st_mtime)).days
        if mtime_age > 90:
            stale_active.append(Issue(rel, f"active; mtime age {mtime_age} days"))
            continue
        updated_val = fm.get("updated")
        if updated_val is None:
            continue
        try:
            updated_day = updated_val if isinstance(updated_val, date) else date.fromisoformat(str(updated_val))
            age = (today - updated_day).days
            if age > 90:
                stale_active.append(Issue(rel, f"active; updated age {age} days"))
        except Exception:
            pass

    descs: dict[str, list[str]] = defaultdict(list)
    for path in governed:
        rel = rel_posix(path, vault_root) or str(path)
        if _is_transient(rel):
            continue
        desc = _frontmatter(path).get("description")
        if isinstance(desc, str) and desc.strip():
            descs[re.sub(r"\s+", " ", desc.strip().lower())].append(rel)
    duplicate_descriptions = [
        Issue(files[0], f"description shared by {len(files)} notes: {', '.join(files[:4])}")
        for files in descs.values()
        if len(files) > 1
    ]

    thinking_incoming = Counter()
    for path, sources in incoming.items():
        rel = rel_posix(path, vault_root) or ""
        if rel.startswith("thinking/") and sources:
            thinking_incoming[rel] = len(sources)
    thinking_promotion_queue = [
        {"file": rel, "incoming": count}
        for rel, count in thinking_incoming.most_common(20)
        if count >= 2
    ]

    bases_dir = vault_root / "bases"
    existing_bases = {p.name for p in bases_dir.glob("*.base")} if bases_dir.is_dir() else set()
    missing_bases = [name for name in OBSIDIAN_BASE_RECOMMENDATIONS if name not in existing_bases]

    issue_groups = {
        "frontmatter": frontmatter_issues,
        "no_wikilinks": no_wikilinks,
        "broken_links": broken_links,
        "ambiguous_links": ambiguous_links,
        "orphans": orphans,
        "work_index": work_not_indexed,
        "personal_index": personal_not_indexed,
        "stale_active": stale_active,
        "duplicate_descriptions": duplicate_descriptions,
    }

    return {
        "summary": {
            "governed_notes": len(governed),
            "graph_notes": len(graph_notes),
            "issue_count": sum(len(v) for v in issue_groups.values()),
        },
        "issues": {name: [asdict(issue) for issue in issues] for name, issues in issue_groups.items()},
        "thinking_promotion_queue": thinking_promotion_queue,
        "obsidian_dashboard_gaps": missing_bases,
    }


def _section(lines: list[str], title: str, issues: list[dict[str, str]], limit: int) -> None:
    lines.append(f"#### {title} ({len(issues)})")
    for issue in issues[:limit]:
        lines.append(f"- `{issue['file']}`: {issue['detail']}")
    if len(issues) > limit:
        lines.append(f"- ... {len(issues) - limit} more")
    lines.append("")


def render_markdown(report: dict[str, Any], limit: int = 20) -> str:
    summary = report["summary"]
    lines = [
        "## Vault Audit Report",
        "",
        "### Summary",
        f"- Governed notes: {summary['governed_notes']}",
        f"- Graph/search notes: {summary['graph_notes']}",
        f"- Issues: {summary['issue_count']}",
        "",
        "### Issues by Category",
    ]
    labels = {
        "frontmatter": "Frontmatter",
        "no_wikilinks": "No Wikilinks",
        "broken_links": "Broken Links",
        "ambiguous_links": "Ambiguous Links",
        "orphans": "Orphans",
        "work_index": "Work Index Drift",
        "personal_index": "Personal Index Drift",
        "stale_active": "Stale Active",
        "duplicate_descriptions": "Duplicate Descriptions",
    }
    for key, label in labels.items():
        _section(lines, label, report["issues"][key], limit)

    lines.append("### Thinking Promotion Queue")
    queue = report["thinking_promotion_queue"]
    if queue:
        for item in queue[:limit]:
            lines.append(f"- `{item['file']}`: {item['incoming']} incoming links")
    else:
        lines.append("- None")
    lines.append("")

    lines.append("### Obsidian Dashboard Gaps")
    gaps = report["obsidian_dashboard_gaps"]
    if gaps:
        for name in gaps:
            lines.append(f"- `{name}`")
    else:
        lines.append("- None")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only My Brain vault structural audit.")
    parser.add_argument("--vault-root", type=Path)
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of Markdown.")
    parser.add_argument("--limit", type=int, default=20, help="Max issues per category in Markdown output.")
    args = parser.parse_args(argv)

    vault_root = args.vault_root.resolve() if args.vault_root else find_vault_root()
    if vault_root is None:
        print("ERROR: vault root not found", file=sys.stderr)
        return 1

    report = audit(vault_root)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(render_markdown(report, args.limit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
