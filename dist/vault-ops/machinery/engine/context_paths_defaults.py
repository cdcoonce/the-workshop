"""Shipped default note paths for the session digest.

Managed tier: upgrade owns this file. It is the fallback only — the paths a
vault actually reads live in the scaffold-rendered ``context_paths.py``
(``scaffold/context_paths.py.tmpl``), which init writes once and upgrade never
touches. context_loader prefers that config and falls back here for any name it
does not define, so a vault vendored before the config existed still digests.
"""

from __future__ import annotations

# Read for every session, regardless of the detected machine context.
COMMON_NOTE_PATHS: dict[str, str] = {
    "north_star": "brain/North Star.md",
    "quick_reference": "brain/Quick-Reference.md",
}

# Grouped by the machine context each note belongs to. context_loader has
# never gated a *read* on the detected `.vault-context` value — only how it
# summarizes the result — so every section here is read every session; the
# grouping is for readability, not conditional loading.
CONTEXT_NOTE_PATHS: dict[str, dict[str, str]] = {
    "work": {"work_index": "work/Index.md"},
    "personal": {"personal_index": "personal/Index.md"},
    # Read on every machine: coursework competes with work and personal time
    # on both of them.
    "school": {"school_index": "school/Index.md"},
}
