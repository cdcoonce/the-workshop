"""Context Loader — assembles machine-aware session context from the vault.

Public interface:
    load_context(vault_path) → SessionContext
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from vault_utils import read_vault_context

# ---------------------------------------------------------------------------
# SessionStart context budget
# ---------------------------------------------------------------------------
# Whatever SessionStart emits stays resident for the whole session, so it pays
# for orientation only: totals, the newest few items, and a pointer to the file
# that holds the rest. The full lists remain on SessionContext for consumers
# that want them — only the rendered summary is budgeted.

SUMMARY_PREVIEW = 3        # items shown per bucket
SUMMARY_ITEM_CHARS = 100   # index descriptions run 130-350 chars; clip them
GIT_PREVIEW = 5            # commit subjects are already short

HANDOFF_RESUME_ENTRIES = 1  # newest "**▶ <date>" entries kept under "Resume from here"
HANDOFF_ENTRY_CHARS = 1200  # per-entry clip
HANDOFF_MAX_BYTES = 8000    # ceiling; whole trailing sections drop past it


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

@dataclass
class SessionContext:
    """Assembled session context for Claude."""
    machine: str  # "work" or "personal" or "unknown"
    summary: str  # Human-readable summary for injection
    north_star: str  # North Star goals content
    active_work: list[str]  # Active project names from indexes
    active_personal: list[str]  # Active personal items
    recent_git: str  # Recent git log output
    quick_reference: str  # Quick-Reference content for fast decoding


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_vault_context(vault_path: Path) -> str:
    """Read .vault-context to detect machine type (delegates to the canonical reader)."""
    return read_vault_context(vault_path)


def _read_file_content(path: Path) -> str:
    """Safely read a file's content, returning empty string on error."""
    try:
        if path.exists():
            return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        pass
    return ""


def _extract_section_items(content: str, section_header: str) -> list[str]:
    """Extract items listed under a markdown section header.

    Looks for lines starting with '- ' or '- [[' under the given ## header.
    """
    items: list[str] = []
    in_section = False

    for line in content.splitlines():
        stripped = line.strip()

        # Check for section headers
        if stripped.startswith("## "):
            in_section = stripped.lower() == f"## {section_header.lower()}"
            continue

        if in_section:
            # Stop at next section or end
            if stripped.startswith("## ") or stripped.startswith("# "):
                break
            # Capture list items and wikilinks
            if stripped.startswith("- ") and stripped != "- [ ]":
                item = stripped[2:].strip()
                if item and not item.startswith("<!--"):
                    items.append(item)

    return items


def _get_recent_git_log(vault_path: Path, hours: int = 48) -> str:
    """Get recent git log entries."""
    try:
        result = subprocess.run(
            ["git", "log", f"--since={hours} hours ago", "--oneline", "--no-decorate"],
            cwd=vault_path,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return ""


def _clip(text: str, limit: int) -> str:
    """Trim text to a length, preferring a line boundary, marking the elision.

    Parameters
    ----------
    text : str
        Text to trim.
    limit : int
        Maximum characters before the elision marker.

    Returns
    -------
    str
        `text` unchanged when short enough, else a clipped copy ending in "…".
    """
    if len(text) <= limit:
        return text
    cut = text[:limit]
    newline = cut.rfind("\n")
    if newline > limit // 2:
        cut = cut[:newline]
    return cut.rstrip() + " …"


def _append_bucket(out: list[str], label: str, items: list[str], source: str) -> None:
    """Append "label: N", the first few items clipped, then a pointer for the tail.

    Parameters
    ----------
    out : list of str
        Summary lines, appended to in place.
    label : str
        Human-readable bucket name.
    items : list of str
        Every item in the bucket; only the first `SUMMARY_PREVIEW` are rendered.
    source : str
        Vault-relative path holding the full list, named in the pointer line.
    """
    if not items:
        return
    out.append(f"{label}: {len(items)}")
    for item in items[:SUMMARY_PREVIEW]:
        out.append(f"  • {_clip(item, SUMMARY_ITEM_CHARS)}")
    if len(items) > SUMMARY_PREVIEW:
        out.append(f"  … +{len(items) - SUMMARY_PREVIEW} more — see `{source}`")


_ENTRY_RE = re.compile(r"^\s*\*\*▶")
_ELIDED_RE = re.compile(r"^_\+\d+ older session entries elided")


def _split_sections(text: str) -> list[list[str]]:
    """Split markdown into blocks at "## " headers; index 0 is the preamble."""
    sections: list[list[str]] = [[]]
    for line in text.splitlines():
        if line.startswith("## "):
            sections.append([])
        sections[-1].append(line)
    return sections


def _condense_resume(section: list[str], rel_path: str) -> str:
    """Keep the newest few "**▶" session entries; count and point at the rest."""
    entries: list[list[str]] = [[]]
    for line in section:
        if _ENTRY_RE.match(line):
            entries.append([])
        entries[-1].append(line)

    head = [line for line in entries[0] if not _ELIDED_RE.match(line.strip())]
    parts = ["\n".join(head).strip()]
    kept = entries[1:1 + HANDOFF_RESUME_ENTRIES]
    for entry in kept:
        parts.append(_clip("\n".join(entry).strip(), HANDOFF_ENTRY_CHARS))

    dropped = len(entries) - 1 - len(kept)
    if dropped > 0:
        parts.append(
            f"_+{dropped} older session entries elided — full history in `{rel_path}`._"
        )
    return "\n\n".join(part for part in parts if part)


def _budget_sections(body: str, rel_path: str) -> str:
    """Drop whole trailing sections until the digest fits the byte ceiling."""
    if len(body.encode("utf-8")) <= HANDOFF_MAX_BYTES:
        return body

    blocks = [block for block in ("\n".join(s).strip() for s in _split_sections(body)) if block]
    dropped: list[str] = []
    while (
        len("\n\n".join(blocks).encode("utf-8")) > HANDOFF_MAX_BYTES
        and len(blocks) > 1
    ):
        dropped.append(blocks.pop().splitlines()[0].lstrip("# ").strip())

    out = "\n\n".join(blocks)
    if dropped:
        out += (
            f"\n\n_Elided for context budget ({', '.join(reversed(dropped))}) "
            f"— read `{rel_path}`._"
        )
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def condense_digest(text: str, rel_path: str) -> str:
    """Budget a handoff or notebook digest for SessionStart injection.

    Every section is preserved, but the reverse-chronological "**▶" entry stack
    under "Resume from here" collapses to the newest few plus a count and a
    pointer, and trailing sections drop once the result exceeds
    `HANDOFF_MAX_BYTES`. A no-op for digests that are already small.

    Parameters
    ----------
    text : str
        Raw digest content.
    rel_path : str
        Vault-relative path to the digest, named in every pointer line.

    Returns
    -------
    str
        The budgeted digest. Idempotent: condensing twice equals condensing once.
    """
    out: list[str] = []
    for section in _split_sections(text):
        head = section[0] if section else ""
        if head.startswith("## ") and "resume" in head.lower():
            out.append(_condense_resume(section, rel_path))
        else:
            out.append("\n".join(section).strip())
    return _budget_sections("\n\n".join(s for s in out if s), rel_path)

def load_context(vault_path: str | Path) -> SessionContext:
    """Load session context from the vault.

    Reads .vault-context for machine detection, loads North Star goals,
    scans indexes for active items, and gathers recent git history.

    Args:
        vault_path: Path to the vault root directory.

    Returns:
        SessionContext with assembled context for the session.
    """
    vault_path = Path(vault_path)

    # Detect machine
    machine = _read_vault_context(vault_path)

    # Load North Star
    north_star = _read_file_content(vault_path / "brain" / "North Star.md")

    # Load Quick Reference for fast decoding
    quick_reference = _read_file_content(vault_path / "brain" / "Quick-Reference.md")

    # Scan indexes for active items
    work_index = _read_file_content(vault_path / "work" / "Index.md")
    personal_index = _read_file_content(vault_path / "personal" / "Index.md")

    active_work = _extract_section_items(work_index, "Active Projects")
    active_personal = (
        _extract_section_items(personal_index, "Learning")
        + _extract_section_items(personal_index, "Side Projects")
        + _extract_section_items(personal_index, "Ideas")
    )

    # Recent git activity
    recent_git = _get_recent_git_log(vault_path)

    # Build summary
    summary_lines = [f"Machine context: {machine}"]

    _append_bucket(summary_lines, "Active work projects", active_work, "work/Index.md")

    if machine in ("personal", "unknown"):
        _append_bucket(
            summary_lines, "Active personal items", active_personal, "personal/Index.md"
        )

    if recent_git:
        git_lines = recent_git.splitlines()
        summary_lines.append(f"Recent commits (last 48h): {len(git_lines)}")
        for line in git_lines[:GIT_PREVIEW]:
            summary_lines.append(f"  • {line}")

    if not active_work and not active_personal and not recent_git:
        summary_lines.append("New vault — no projects or history yet.")

    summary = "\n".join(summary_lines)

    return SessionContext(
        machine=machine,
        summary=summary,
        north_star=north_star,
        active_work=active_work,
        active_personal=active_personal,
        recent_git=recent_git,
        quick_reference=quick_reference,
    )
