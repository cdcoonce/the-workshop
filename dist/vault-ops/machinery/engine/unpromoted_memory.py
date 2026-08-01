"""Write-time detection of wikilinks to unpromoted machine-local auto-memories.

A durable fact that lives only in ``~/.claude/projects/<slug>/memory/`` is not in the
vault, so citing it as ``[[its-slug]]`` produces a broken link that survives until
someone runs the health gate. The gate catches it after the fact; this module catches
it at the moment the link is written, when the author still has the context to promote
the memory.

This is deliberately narrower than "the note has a broken link". The distinguishing
property is that the repair is *known*: promote the auto-memory into the vault. Generic
missing targets stay with the ordinary broken-link lane, which cannot say what to do.

Two conditions must both hold, and the order matters for cost, not just correctness:

    1. ``has_candidate_memory_link`` — a cheap, subprocess-free pre-filter over the
       written file's own wikilinks. Almost every write fails this, so almost every
       write pays nothing.
    2. ``unpromoted_memory_links`` — confirms with graphmark that the link is genuinely
       unresolved. A *promoted* memory keeps its auto-memory file, so slug-matching
       alone would fire on every already-correct citation.

Both are fail-soft: no auto-memory directory, an unreadable note, or a failed resolver
scan yields "nothing to report" rather than an error. This runs inside a PostToolUse
hook, and a check that can break a write is worse than no check.
"""

from __future__ import annotations

from pathlib import Path

from graph_gardener import _graphmark_broken, _normalize, detect_auto_memory_drift
from vault_utils import WIKILINK_CAPTURE_RE

__all__ = ["has_candidate_memory_link", "unpromoted_memory_links", "format_warning"]


def _link_targets(text: str) -> list[str]:
    """The link targets in ``text`` — the part before any ``|`` display override."""
    return [m.split("|", 1)[0].strip() for m in WIKILINK_CAPTURE_RE.findall(text)]


def has_candidate_memory_link(
    note_path: Path,
    vault_root: Path,
    *,
    mem_base: Path | None = None,
) -> bool:
    """True if the note links anything sharing a name with an auto-memory file.

    The gate that keeps the resolver subprocess off the common path. It may
    over-approximate — a promoted memory still matches — but it must never
    under-approximate, or the check silently stops firing.
    """
    try:
        memories = detect_auto_memory_drift(vault_root, mem_base)
        if not memories:
            return False
        text = note_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return any(_normalize(t) in memories for t in _link_targets(text))


def unpromoted_memory_links(
    vault_root: Path,
    rel_path: str,
    *,
    broken: dict | None = None,
    mem_base: Path | None = None,
) -> list[tuple[str, str]]:
    """``(display, memory_filename)`` for each unpromoted memory cited by ``rel_path``.

    Args:
        vault_root: the vault being written to.
        rel_path: the written note, relative to ``vault_root`` — results are scoped to
            it, because vault-wide breaks are noise at write time.
        broken: rel_path → broken link displays. Injectable for tests; when omitted the
            live graphmark scan runs. ``None`` means *the scan was unavailable*, which
            yields no findings — an empty dict would be indistinguishable from a clean
            vault, and reporting off a failed scan would be a fabricated finding.
        mem_base: auto-memory root, injectable for tests.
    """
    memories = detect_auto_memory_drift(vault_root, mem_base)
    if not memories:
        return []

    if broken is None:
        raw = _graphmark_broken(vault_root)
        if raw is None:
            return []
        broken = {
            note: [
                e.get("display")
                for e in entries
                if isinstance(e, dict) and isinstance(e.get("display"), str)
            ]
            for note, entries in raw.items()
            if isinstance(entries, list)
        }

    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for display in broken.get(rel_path, []) or []:
        if not isinstance(display, str):
            continue
        key = _normalize(display)
        filename = memories.get(key)
        if filename and key not in seen:
            seen.add(key)
            found.append((display, filename))
    return found


def format_warning(found: list[tuple[str, str]]) -> list[str]:
    """Hook-output lines naming the repair, not just the symptom."""
    if not found:
        return []
    lines = ["📌 Unpromoted auto-memory linked:"]
    for display, filename in found:
        lines.append(
            f"  • [[{display}]] is machine-local auto-memory (`{filename}`), not a vault note."
        )
    lines.append("")
    lines.append(
        "Promote it into the vault (with frontmatter, a wikilink, and its index entry) "
        "in this session, or the link stays broken. Auto-memory → vault, never the reverse."
    )
    return lines
