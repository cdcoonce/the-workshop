"""Frontmatter Engine — validates and generates YAML frontmatter for vault notes.

Public interface:
    validate(file_path, vault_root) → list[ValidationError]
        (omit vault_root to auto-detect via the brain/+perf/ signature walk-up)
    generate(note_type, fields) → str
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from vault_utils import WIKILINK_RE, find_vault_root, find_vault_root_from_env
from vault_scope_resolved import is_governed_markdown_note, is_transient_note


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

@dataclass
class ValidationError:
    """A single frontmatter validation failure."""
    file: str
    field: str
    message: str
    severity: str = "error"  # "error" blocks, "warning" continues

    def __str__(self) -> str:
        return f"[{self.severity.upper()}] {self.file}: {self.field} — {self.message}"


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Required fields for every note
UNIVERSAL_FIELDS = ("date", "description", "tags")

class FrontmatterSchemaError(Exception):
    """Raised when an owner's frontmatter_schema.json is malformed.

    Fails closed on purpose, and deliberately unlike ``vault_scope_resolved``,
    which degrades to shipped defaults and reports. A hook must not die on a
    typo in the owner's *scope* config; but silently ignoring a broken *schema*
    would validate every custom note type against nothing, which from the
    outside is indistinguishable from a clean vault.
    """


# The owner's config lives under the vault root, resolved by path — never by a
# directory relative to this module's own ``__file__``. Before the flat reorg
# those were the same place, because the engine was vendored into the vault.
# Now the engine ships inside the installed plugin, so a ``__file__``-relative
# lookup resolves into the plugin's own payload: a directory no owner writes
# to, where the file can never exist (#696). Same class as #691 — owner config
# the runtime cannot reach after the engine moved, failing silently to
# defaults.
_OWNER_SCHEMA = (".vault", "config", "frontmatter_schema.json")


def _owner_schema_path() -> Path | None:
    """Where this vault's owner schema would live, or None outside a vault."""
    root = find_vault_root_from_env()
    return None if root is None else root.joinpath(*_OWNER_SCHEMA)


def load_note_type_schemas(config_dir: Path | None = None) -> dict[str, list[str]]:
    """Load the note-type schema: owner config first, shipped defaults else.

    The owner's ``<vault>/.vault/config/frontmatter_schema.json`` replaces the
    shipped table wholesale when present. Two states legitimately fall back to
    ``frontmatter_schema_defaults.NOTE_TYPE_SCHEMAS`` — no vault, and a vault
    with no owner schema. A malformed file raises ``FrontmatterSchemaError``
    naming the path, so "exists but broken" never looks like "absent".

    Parameters
    ----------
    config_dir
        Read ``frontmatter_schema.json`` from this directory instead of
        resolving the vault root. For unit-testing the PARSING only. Whether
        the owner's file is *found* cannot be tested through this argument —
        passing an explicit path is precisely the input that cannot separate
        "the lookup works" from "the caller was told where to look", which is
        how #696 stayed green while production found nothing. That question is
        answered by ``tests/test_frontmatter_schema_resolution.py``, which
        arranges a real vault and a real subprocess.
    """
    if config_dir is not None:
        path = config_dir / "frontmatter_schema.json"
    else:
        resolved = _owner_schema_path()
        if resolved is None:
            from frontmatter_schema_defaults import NOTE_TYPE_SCHEMAS

            return dict(NOTE_TYPE_SCHEMAS)
        path = resolved
    if not path.exists():
        from frontmatter_schema_defaults import NOTE_TYPE_SCHEMAS

        return dict(NOTE_TYPE_SCHEMAS)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FrontmatterSchemaError(
            f"unreadable or invalid frontmatter_schema.json at {path}: {exc}"
        ) from exc
    if not isinstance(raw, dict):
        raise FrontmatterSchemaError(
            f"frontmatter_schema.json at {path} must be a JSON object mapping "
            "note type to a list of required fields"
        )
    schemas: dict[str, list[str]] = {}
    for note_type, fields in raw.items():
        if not isinstance(fields, list) or not all(
            isinstance(f, str) for f in fields
        ):
            raise FrontmatterSchemaError(
                f"note type {note_type!r} in frontmatter_schema.json must map "
                "to a list of field-name strings"
            )
        schemas[str(note_type)] = list(fields)
    return schemas


# Type-specific required fields (detected by tag presence). Sourced from the
# owner's config when present, shipped defaults otherwise.
#
# Resolved lazily and cached per process, not at import. The answer depends on
# locating a vault, which depends on `CLAUDE_PROJECT_DIR` and the working
# directory; binding it at import time would freeze whatever those happened to
# be when the module was first pulled in — by a hook, by a CLI, or incidentally
# by something that imports this module for `generate()` alone. Lazy also means
# importing the engine outside any vault, or beside a broken schema, no longer
# raises at import: the failure surfaces when the table is actually used.
_TYPE_FIELDS_CACHE: dict[str, list[str]] | None = None


def _type_fields() -> dict[str, list[str]]:
    """The resolved note-type table, loaded once per process."""
    global _TYPE_FIELDS_CACHE
    if _TYPE_FIELDS_CACHE is None:
        _TYPE_FIELDS_CACHE = load_note_type_schemas()
    return _TYPE_FIELDS_CACHE


def __getattr__(name: str):
    """Serve ``TYPE_FIELDS`` lazily to importers that read it as a constant.

    PEP 562 module ``__getattr__`` fires only for attribute access on the
    module object, so this is the external door; code inside this module calls
    ``_type_fields()`` directly.
    """
    if name == "TYPE_FIELDS":
        return _type_fields()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

MIN_WIKILINK_LENGTH = 300  # notes longer than this must have a wikilink


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_excluded(file_path: Path, vault_root: Path) -> bool:
    """Check if a file should be excluded from validation."""
    return not is_governed_markdown_note(file_path, vault_root)


def _parse_frontmatter(content: str) -> tuple[dict[str, Any] | None, str, str | None]:
    """Parse YAML frontmatter from markdown content.

    Returns (frontmatter_dict, body, error_message).
    If frontmatter is missing or malformed, returns (None, full_content, error).
    """
    if not content.startswith("---"):
        return None, content, "No YAML frontmatter found (file must start with ---)"

    parts = content.split("---", 2)
    if len(parts) < 3:
        return None, content, "Malformed frontmatter (missing closing ---)"

    yaml_str = parts[1].strip()
    body = parts[2]

    try:
        fm = yaml.safe_load(yaml_str)
    except yaml.YAMLError as exc:
        line_info = ""
        if hasattr(exc, "problem_mark") and exc.problem_mark is not None:
            mark = exc.problem_mark
            line_info = f" (line {mark.line + 1}, col {mark.column + 1})"
        return None, body, f"YAML parse error{line_info}: {exc}"

    if not isinstance(fm, dict):
        return None, body, "Frontmatter is not a YAML mapping"

    return fm, body, None


def _detect_note_type(fm: dict[str, Any]) -> str | None:
    """Detect note type from tags in frontmatter."""
    tags = fm.get("tags", [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",")]

    type_fields = _type_fields()
    for tag in tags:
        if tag in type_fields:
            return tag
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate(file_path: str | Path, vault_root: str | Path | None = None) -> list[ValidationError]:
    """Validate frontmatter of a markdown file.

    Args:
        file_path: Path to the markdown file.
        vault_root: Root of the vault. If None, auto-detected via
                    vault_utils.find_vault_root walking up from file_path
                    (the brain/+perf/ signature), falling back to
                    file_path.parent if no signature is found.

    Returns:
        List of ValidationError objects. Empty list means valid.
    """
    file_path = Path(file_path)
    errors: list[ValidationError] = []
    rel_name = file_path.name

    # Resolve vault root
    if vault_root is None:
        vault_root = find_vault_root(file_path.parent)
        if vault_root is None:
            vault_root = file_path.parent
    vault_root = Path(vault_root)

    # Skip non-markdown
    if file_path.suffix.lower() != ".md":
        return errors

    # Skip excluded paths
    if _is_excluded(file_path, vault_root):
        return errors

    # Read file
    try:
        content = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        errors.append(ValidationError(rel_name, "file", f"Cannot read file: {exc}"))
        return errors

    # Parse frontmatter
    fm, body, parse_error = _parse_frontmatter(content)
    if parse_error is not None:
        # YAML parse errors are warnings (per CEO Review decision 4A)
        errors.append(ValidationError(rel_name, "frontmatter", parse_error, severity="warning"))
        return errors

    if fm is None:
        errors.append(ValidationError(rel_name, "frontmatter", "No frontmatter found"))
        return errors

    # --- Universal field validation ---

    # date
    date_val = fm.get("date")
    if date_val is None:
        errors.append(ValidationError(rel_name, "date", "Missing required field 'date'"))
    else:
        date_str = str(date_val)
        if not DATE_RE.match(date_str):
            errors.append(ValidationError(rel_name, "date",
                          f"Invalid date format '{date_str}' — expected YYYY-MM-DD"))

    # description
    desc = fm.get("description")
    if desc is None or (isinstance(desc, str) and desc.strip() == ""):
        errors.append(ValidationError(rel_name, "description",
                      "Missing required field 'description'"))

    # tags
    tags = fm.get("tags")
    if tags is None:
        errors.append(ValidationError(rel_name, "tags", "Missing required field 'tags'"))
    elif isinstance(tags, list) and len(tags) == 0:
        errors.append(ValidationError(rel_name, "tags", "Tags list is empty — at least one tag required"))
    elif isinstance(tags, str) and tags.strip() == "":
        errors.append(ValidationError(rel_name, "tags", "Tags field is empty — at least one tag required"))

    # --- Type-specific validation ---
    note_type = _detect_note_type(fm)  # fm is guaranteed non-None here (guarded + returned above)
    type_fields = _type_fields()
    if note_type and note_type in type_fields:
        for req_field in type_fields[note_type]:
            val = fm.get(req_field)
            if val is None or (isinstance(val, str) and val.strip() == ""):
                errors.append(ValidationError(rel_name, req_field,
                              f"Missing field '{req_field}' (required for {note_type} notes)"))

    # --- Wikilink requirement ---
    body_text = body.strip()
    if len(body_text) > MIN_WIKILINK_LENGTH and not is_transient_note(file_path, vault_root):
        if not WIKILINK_RE.search(body_text):
            errors.append(ValidationError(rel_name, "wikilinks",
                          f"Notes longer than {MIN_WIKILINK_LENGTH} characters must "
                          f"contain at least one [[wikilink]] (body is {len(body_text)} chars)"))

    return errors


def generate(note_type: str, fields: dict[str, Any] | None = None) -> str:
    """Generate YAML frontmatter string for a given note type.

    Args:
        note_type: One of the recognized note types (e.g., "work-note", "decision").
        fields: Optional dict of field values to include. Missing fields get defaults.

    Returns:
        YAML frontmatter string including --- delimiters.
    """
    if fields is None:
        fields = {}

    fm: dict[str, Any] = {
        "date": fields.get("date", date.today().isoformat()),
        "description": fields.get("description", ""),
        "tags": fields.get("tags", [note_type] if note_type else []),
    }

    # Add type-specific fields with defaults
    type_fields = _type_fields()
    if note_type in type_fields:
        for req_field in type_fields[note_type]:
            fm[req_field] = fields.get(req_field, "")

    yaml_str = yaml.dump(fm, default_flow_style=False, sort_keys=False, allow_unicode=True)
    return f"---\n{yaml_str}---\n"
