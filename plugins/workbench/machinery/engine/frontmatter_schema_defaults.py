"""Shipped default note-type schema for frontmatter validation.

Managed tier: upgrade owns this file. It is the fallback only — the
note-type schema a vault actually validates against lives in the
scaffolded ``frontmatter_schema.json`` (``scaffold/frontmatter_schema.json.tmpl``),
which init writes once and upgrade never touches. frontmatter_engine prefers
that config and falls back here when it is absent, so a vault vendored
before the config existed keeps identical validation behavior.
"""

from __future__ import annotations

# Required fields per note type, detected by tag presence.
NOTE_TYPE_SCHEMAS: dict[str, list[str]] = {
    "work-note": ["status", "project"],
    "decision": ["status"],
    "1-1": ["participant"],
    "incident": ["ticket", "severity"],
    "competency": ["current_level", "target_level"],
    "learning": ["source", "status"],
    "side-project": ["status"],
    "person": ["role", "team"],
    "tasks": ["week"],
}
