"""Dev cycle state file parser and validator.

Parses YAML frontmatter from dev-cycle state files and validates schema_version
bounds, status/current_phase membership, feature-slug/filename agreement,
artifact completeness, and duplicate-slug detection across a directory. It does
not validate phase transitions.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

VALID_PHASES = (
    "brainstorm", "plan", "ceo_review", "issues",
    "implement", "code_review", "pr",
)
VALID_STATUSES = ("not_started", "in_progress", "completed", "abandoned")
VALID_ARTIFACT_STATUSES = ("pending", "in_progress", "completed", "blocked")
CURRENT_SCHEMA_VERSION = 1

_FRONTMATTER_RE = re.compile(r"\A---\n(.+?)\n---", re.DOTALL)
_FIELD_RE = re.compile(r"^(\w+):\s*(.+?)(?:\s*#.*)?$", re.MULTILINE)
_ARTIFACT_ROW_RE = re.compile(
    r"^\|\s*(\w+)\s*\|\s*(\w+)\s*\|\s*(.+?)\s*\|$", re.MULTILINE
)

REQUIRED_FIELDS = ("feature", "status", "current_phase")

# Values that mean "no artifact": em dash, hyphen, empty string.
_EMPTY_ARTIFACT_MARKERS = ("—", "-", "")


@dataclass
class ArtifactRow:
    """A single row from the Artifacts table."""

    phase: str
    status: str
    artifact: str


@dataclass
class StateFile:
    """Parsed representation of a dev-cycle state file."""

    schema_version: int
    feature: str
    status: str
    current_phase: str
    created: str = ""
    updated: str = ""
    branch: str = ""
    path: Path = field(default_factory=lambda: Path())
    artifacts: list[ArtifactRow] = field(default_factory=list)
    had_schema_version: bool = True


def _parse_artifacts(text: str) -> list[ArtifactRow]:
    """Parse the Artifacts markdown table from state file body.

    Parameters
    ----------
    text : str
        Full text content of the state file.

    Returns
    -------
    list[ArtifactRow]
        Parsed artifact rows, excluding header and separator rows.
    """
    rows: list[ArtifactRow] = []
    for match in _ARTIFACT_ROW_RE.finditer(text):
        phase = match.group(1)
        status = match.group(2)
        artifact = match.group(3).strip()
        if phase not in VALID_PHASES:
            continue
        rows.append(ArtifactRow(phase=phase, status=status, artifact=artifact))
    return rows


def parse_state_file(path: Path) -> StateFile:
    """Parse a dev-cycle state file and return a StateFile object.

    Parameters
    ----------
    path : Path
        Path to the state file.

    Returns
    -------
    StateFile
        Parsed state file data.

    Raises
    ------
    ValueError
        If the file has no frontmatter, is missing required fields, or has
        a non-integer schema_version.
    """
    text = path.read_text()
    match = _FRONTMATTER_RE.search(text)
    if not match:
        raise ValueError(f"No YAML frontmatter found in {path.name}")

    raw_fields: dict[str, str] = {}
    for field_match in _FIELD_RE.finditer(match.group(1)):
        raw_fields[field_match.group(1)] = field_match.group(2).strip()

    for req in REQUIRED_FIELDS:
        if req not in raw_fields:
            raise ValueError(
                f"Missing required field '{req}' in {path.name}"
            )

    had_schema_version = "schema_version" in raw_fields
    if not had_schema_version:
        raw_fields["schema_version"] = "1"

    raw_schema_version = raw_fields["schema_version"]
    try:
        schema_version = int(raw_schema_version)
    except ValueError:
        raise ValueError(
            f"{path.name} has a non-integer schema_version: '{raw_schema_version}'"
        ) from None

    state = StateFile(
        schema_version=schema_version,
        feature=raw_fields["feature"],
        status=raw_fields["status"],
        current_phase=raw_fields["current_phase"],
        created=raw_fields.get("created", ""),
        updated=raw_fields.get("updated", ""),
        branch=raw_fields.get("branch", ""),
        path=path,
        had_schema_version=had_schema_version,
    )
    state.artifacts = _parse_artifacts(text)
    return state


@dataclass
class ValidationResult:
    """Result of validating a state file."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return len(self.errors) == 0


def _validate_parsed_state(state: StateFile) -> list[str]:
    """Validate field values on an already-parsed StateFile.

    Parameters
    ----------
    state : StateFile
        A parsed state file object.

    Returns
    -------
    list[str]
        Validation error messages (empty if valid).
    """
    errors: list[str] = []
    name = state.path.name

    if state.schema_version > CURRENT_SCHEMA_VERSION:
        errors.append(
            f"Unsupported schema_version {state.schema_version} "
            f"in {name} (max supported: {CURRENT_SCHEMA_VERSION})"
        )

    if state.status not in VALID_STATUSES:
        errors.append(
            f"Invalid status '{state.status}' in {name}. "
            f"Valid values: {', '.join(VALID_STATUSES)}"
        )

    if state.current_phase not in VALID_PHASES:
        errors.append(
            f"Invalid current_phase '{state.current_phase}' in {name}. "
            f"Valid values: {', '.join(VALID_PHASES)}"
        )

    expected_slug = state.path.name.removesuffix(".state.md")
    if state.feature != expected_slug:
        errors.append(
            f"Feature slug '{state.feature}' does not match "
            f"filename '{expected_slug}' in {name}"
        )

    for row in state.artifacts:
        if row.status not in VALID_ARTIFACT_STATUSES:
            errors.append(
                f"Invalid artifact status '{row.status}' for phase '{row.phase}' "
                f"in {name}. Valid values: {', '.join(VALID_ARTIFACT_STATUSES)}"
            )
        if row.status == "completed" and row.artifact in _EMPTY_ARTIFACT_MARKERS:
            errors.append(
                f"Phase '{row.phase}' is completed but has no artifact "
                f"in {name}"
            )

    return errors


def _validation_result_for_state(state: StateFile) -> ValidationResult:
    """Build a ValidationResult for an already-parsed StateFile.

    Parameters
    ----------
    state : StateFile
        A parsed state file object.

    Returns
    -------
    ValidationResult
        Validation result with any errors and warnings found.
    """
    warnings: list[str] = []
    if not state.had_schema_version:
        warnings.append(
            f"Missing 'schema_version' in {state.path.name} (defaulting to 1)"
        )
    return ValidationResult(errors=_validate_parsed_state(state), warnings=warnings)


def validate_state_file(path: Path) -> ValidationResult:
    """Validate a single dev-cycle state file.

    Parameters
    ----------
    path : Path
        Path to the state file.

    Returns
    -------
    ValidationResult
        Validation result with any errors found.
    """
    try:
        state = parse_state_file(path)
    except ValueError as exc:
        return ValidationResult(errors=[str(exc)])

    return _validation_result_for_state(state)


def validate_directory(directory: Path) -> ValidationResult:
    """Validate all state files in a dev-cycle directory.

    Parameters
    ----------
    directory : Path
        Path to the docs/dev-cycle/ directory.

    Returns
    -------
    ValidationResult
        Combined validation result for all files.
    """
    errors: list[str] = []
    warnings: list[str] = []
    slugs: dict[str, list[str]] = {}

    state_files = sorted(directory.glob("*.state.md"))
    for path in state_files:
        try:
            state = parse_state_file(path)
        except ValueError as exc:
            errors.append(str(exc))
            continue

        file_result = _validation_result_for_state(state)
        errors.extend(file_result.errors)
        warnings.extend(file_result.warnings)
        slugs.setdefault(state.feature, []).append(path.name)

    for slug, filenames in slugs.items():
        if len(filenames) > 1:
            errors.append(
                f"Duplicate feature slug '{slug}' found in files: "
                f"{', '.join(filenames)}"
            )

    return ValidationResult(errors=errors, warnings=warnings)


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("Usage: uv run python -m scripts.dev_cycle_validate <dev-cycle-directory>")
        print("  Validates all *.state.md files in the given directory.")
        sys.exit(1)

    directory = Path(sys.argv[1])
    if not directory.is_dir():
        print(f"Error: {directory} is not a directory")
        sys.exit(1)

    result = validate_directory(directory)
    for warning in result.warnings:
        print(f"WARNING: {warning}")
    if result.passed:
        state_count = len(list(directory.glob("*.state.md")))
        print(f"PASS: {state_count} state file(s) validated successfully")
    else:
        print(f"FAIL: {len(result.errors)} error(s) found:")
        for error in result.errors:
            print(f"  - {error}")
        sys.exit(1)
