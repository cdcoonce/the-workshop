"""Context Loader — assembles machine-aware session context from the vault.

Public interface:
    load_context(vault_path) → SessionContext
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from vault_utils import read_vault_context


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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

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

    if active_work:
        summary_lines.append(f"Active work projects: {len(active_work)}")
        for item in active_work[:5]:
            summary_lines.append(f"  • {item}")

    if active_personal and machine in ("personal", "unknown"):
        summary_lines.append(f"Active personal items: {len(active_personal)}")
        for item in active_personal[:5]:
            summary_lines.append(f"  • {item}")

    if recent_git:
        git_lines = recent_git.splitlines()
        summary_lines.append(f"Recent commits (last 48h): {len(git_lines)}")
        for line in git_lines[:5]:
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
