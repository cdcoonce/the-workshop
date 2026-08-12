"""Shipped default note-type schema for frontmatter validation.

Managed tier: upgrade owns this file. It is the table every vault validates
against unless its owner has written one of their own, by hand, at
``<vault>/.vault/config/frontmatter_schema.json``. ``frontmatter_engine``
resolves that path from the vault root and prefers it wholesale; this module
is the fallback for the two states where there is nothing to prefer — no
vault, and a vault whose owner wrote no schema.

Nothing scaffolds the owner's file. It was once rendered at init from
``scaffold/frontmatter_schema.json.tmpl``, which is why this docstring used to
describe it as the schema a vault "actually" validates against; #687 removed
that template, and #696 found that the engine had been looking for the file
next to its own source — inside the installed plugin, where no owner writes —
so the override was unreachable for as long as it was documented.
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
