"""Validate internal consistency of a source plugin directory.

Plugins ship directly from ``plugins/<name>/`` — what is on disk is what
ships, with no build step in between. This module validates that tree
in place.

Checks:
- .claude-plugin/plugin.json exists with required fields (name, version, description)
- Every directory in skills/ has a SKILL.md
- Every directory in agents/ has a valid AGENT.md (frontmatter with name, description, role)
- Agent names match their directory names
- Agent roles are one of the documented roles (see VALID_ROLES)
- Agent skills.add references resolve to existing skills in skills/
- hooks/hooks.json references scripts (via the run-hook.sh dispatcher) that
  exist in hooks/scripts/
- Every relative link or backtick-quoted path in bundled skill/agent docs
  resolves within that skill/agent directory
- settings.json at root is valid JSON
- Every machinery/engine/ file referenced by machinery/tests/ (imports and
  SCRIPTS_DIR path literals) exists in the plugin
"""

from __future__ import annotations

import json
import re
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

# Valid agent roles, matching the documented vocabulary in CLAUDE.md.
VALID_ROLES = (
    "implementer",
    "reviewer",
    "analyst",
    "qa-tester",
    "skill-writer",
    "strategy",
)

# Link prefixes that are not intra-doc relative paths and should be skipped
# during link resolution (anchors, project-root-relative paths).
_LINK_SKIP_PREFIXES = ("#", ".claude/")

# Matches any URI scheme prefix (e.g. "http:", "mailto:", "tel:") so such
# links aren't mistaken for relative file paths.
_URI_SCHEME_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")

_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")

# Matches a backtick-quoted inline token, e.g. `references/foo.md`.
_BACKTICK_PATTERN = re.compile(r"`([^`\n]+)`")


def _fenced_line_numbers(doc_content: str) -> set[int]:
    """Return line numbers of doc_content that fall inside a ``` fenced code block."""
    in_fence = False
    fenced_lines: set[int] = set()
    for line_num, line in enumerate(doc_content.split("\n")):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            fenced_lines.add(line_num)
    return fenced_lines


def _is_out_of_contract(target: str) -> bool:
    """Return True for anchors, project-root-relative paths, and URI-scheme targets."""
    return target.startswith(_LINK_SKIP_PREFIXES) or bool(
        _URI_SCHEME_PATTERN.match(target)
    )


def _backtick_reference_target(doc_md: Path, raw_token: str) -> str | None:
    """Resolve a backtick-quoted token to a validate-able relative ``.md`` path.

    Applies the scoping contract that separates genuine intra-skill doc
    references from incidental backtick mentions: the token must parse as a
    relative path ending in ``.md`` with no URI scheme and no skip-prefix, and
    its first path segment must exist as a directory alongside ``doc_md``.
    Bare basenames, root-relative mentions, and illustrative example paths
    fail this check and are skipped.

    Parameters
    ----------
    doc_md
        The doc file the token was found in, used to resolve the reference.
    raw_token
        The raw text found between a pair of backticks.

    Returns
    -------
    str | None
        The path portion of the token (query/fragment stripped), or None if
        the token is out of contract and should be skipped.
    """
    target = raw_token.strip()
    if "/" not in target or _is_out_of_contract(target):
        return None
    file_part = re.split(r"[#?]", target, maxsplit=1)[0]
    if not file_part.endswith(".md"):
        return None
    first_segment = file_part.split("/", 1)[0]
    if not first_segment or not (doc_md.parent / first_segment).is_dir():
        return None
    return file_part


def _validate_doc_links(docs_dir: Path, doc_filename: str, label: str) -> list[str]:
    """Validate that relative references in bundled docs resolve to existing files.

    Scans every ``.md`` file bundled alongside each ``doc_filename`` (not just
    ``doc_filename`` itself), checking both markdown-style links
    (``[text](path)``) and in-contract backtick-quoted paths (see
    ``_backtick_reference_target``).

    Parameters
    ----------
    docs_dir
        Root directory to search recursively for doc files (e.g., skills/).
    doc_filename
        Name of the primary doc file that marks a skill/agent directory
        (e.g., "SKILL.md").
    label
        Human-readable label used in error messages (e.g., "Skill").

    Returns
    -------
    list[str]
        Error strings for any references that fail to resolve.
    """
    errors: list[str] = []
    for primary_doc in docs_dir.rglob(doc_filename):
        item_dir = primary_doc.parent
        for doc_md in sorted(item_dir.rglob("*.md")):
            doc_content = doc_md.read_text(encoding="utf-8")
            fenced_lines = _fenced_line_numbers(doc_content)
            doc_rel = doc_md.relative_to(item_dir.parent).as_posix()

            for match in _LINK_PATTERN.finditer(doc_content):
                line_num = doc_content.count("\n", 0, match.start())
                if line_num in fenced_lines:
                    continue
                link_target = match.group(2).strip()
                # Strip an optional markdown link title — [text](path "Title") —
                # keeping only the path token. Skip when the path is
                # quote-wrapped, since such a path may legitimately contain
                # spaces.
                if link_target and not link_target.startswith(("'", '"')):
                    link_target = link_target.split(None, 1)[0]
                if not link_target or _is_out_of_contract(link_target):
                    continue
                file_part = re.split(r"[#?]", link_target, maxsplit=1)[0]
                if not file_part:
                    continue
                resolved = (doc_md.parent / file_part).resolve()
                if not resolved.exists():
                    errors.append(
                        f"{label} '{doc_rel}' links to '{file_part}' but file not found"
                    )

            for match in _BACKTICK_PATTERN.finditer(doc_content):
                line_num = doc_content.count("\n", 0, match.start())
                if line_num in fenced_lines:
                    continue
                file_part = _backtick_reference_target(doc_md, match.group(1))
                if file_part is None:
                    continue
                resolved = (doc_md.parent / file_part).resolve()
                if not resolved.exists():
                    errors.append(
                        f"{label} '{doc_rel}' references "
                        f"'{file_part}' but file not found"
                    )
    return errors


def _strip_quotes(value: str) -> str:
    """Strip a single matching pair of surrounding quotes from a scalar.

    Parameters
    ----------
    value
        Raw scalar text, possibly wrapped in matching ``'`` or ``"`` quotes.

    Returns
    -------
    str
        ``value`` with one surrounding pair of quotes removed, or ``value``
        unchanged if it isn't quoted.
    """
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


@dataclass
class SmokeTestResult:
    """Result of a smoke test run."""

    errors: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return len(self.errors) == 0


def _parse_frontmatter(text: str) -> dict | None:
    """Parse YAML frontmatter from markdown text.

    Parameters
    ----------
    text
        Full markdown text that may begin with ``---`` delimited frontmatter.

    Returns
    -------
    dict | None
        Parsed key-value pairs, or None if no valid frontmatter found.
    """
    if not text.startswith("---"):
        return None
    closing = re.search(r"\n---[ \t]*(?:\n|\Z)", text[3:])
    if closing is None:
        return None
    end = 3 + closing.start()
    frontmatter_text = text[3:end].strip()
    if not frontmatter_text:
        return None
    result: dict = {}
    current_key: str | None = None
    block_scalar = False
    for line in frontmatter_text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        is_indented = line != line.lstrip()
        if ":" in stripped and not stripped.startswith("-") and not is_indented:
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = re.sub(r"\s+#.*$", "", value.strip())
            if value.startswith("[") and value.endswith("]"):
                result[key] = [
                    _strip_quotes(v.strip())
                    for v in value[1:-1].split(",")
                    if v.strip()
                ]
                current_key = None
                block_scalar = False
            elif value and value[0] in ("|", ">"):
                # YAML block scalar (|, >, with optional chomping/indent indicator):
                # the value continues on the following indented lines.
                result[key] = ""
                current_key = key
                block_scalar = True
            elif value:
                result[key] = _strip_quotes(value)
                current_key = None
                block_scalar = False
            else:
                result[key] = {}
                current_key = key
                block_scalar = False
        elif current_key and is_indented:
            if block_scalar:
                # Fold every indented line into the value, colons and all.
                result[current_key] = f"{result[current_key]} {stripped}".strip()
            elif ":" in stripped:
                if not isinstance(result[current_key], dict):
                    result[current_key] = {}
                sub_key, _, sub_value = stripped.partition(":")
                sub_key = sub_key.strip()
                sub_value = sub_value.strip()
                if sub_value.startswith("[") and sub_value.endswith("]"):
                    result[current_key][sub_key] = [
                        _strip_quotes(v.strip())
                        for v in sub_value[1:-1].split(",")
                        if v.strip()
                    ]
                else:
                    result[current_key][sub_key] = _strip_quotes(sub_value)
            elif result[current_key] == {}:
                result[current_key] = stripped
            elif isinstance(result[current_key], str):
                result[current_key] = f"{result[current_key]} {stripped}"
    return result if result else None


# Matches a double-quoted span so literal quoted trigger phrases (e.g. a user
# phrase that happens to contain "pipeline") are excluded before linting.
_QUOTED_SPAN_PATTERN = re.compile(r'"[^"]*"')

# (human-readable label, pattern) pairs for process/workflow-summary markers
# that don't belong in a trigger-only skill description.
_PROCESS_MARKER_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "a phase-count marker (e.g. '7-phase')",
        re.compile(r"\d+[- ]phase", re.IGNORECASE),
    ),
    ("the word 'pipeline'", re.compile(r"\bpipeline\b", re.IGNORECASE)),
    ("a '→' step chain", re.compile("→")),
    ("' then '", re.compile(r" then ", re.IGNORECASE)),
)


def _lint_description_process_markers(description: str) -> list[str]:
    """Flag process/workflow-summary markers in a skill description.

    A skill description is a retrieval index, not a spec: it should name only
    the conditions that trigger the skill, never the skill's internal
    process, workflow, or phase count. Matches inside double-quoted spans are
    ignored so a literal quoted trigger phrase is never flagged.

    Parameters
    ----------
    description
        The skill's frontmatter ``description`` value.

    Returns
    -------
    list[str]
        Human-readable names of the process markers found, empty if none.
    """
    text_outside_quotes = _QUOTED_SPAN_PATTERN.sub("", description)
    return [
        label
        for label, pattern in _PROCESS_MARKER_PATTERNS
        if pattern.search(text_outside_quotes)
    ]


# Minimum word count for a quoted trigger phrase to count as distinctive enough
# that two skills sharing it is a real retrieval collision rather than noise.
_TRIGGER_MIN_WORDS = 3

# Normalized quoted phrases intentionally shared by more than one skill.
# Shrink-only: add an entry only with a comment justifying the shared trigger.
_TRIGGER_OVERLAP_ALLOWLIST: frozenset[str] = frozenset()


def _quoted_trigger_phrases(description: str) -> set[str]:
    """Normalized quoted phrases in a description with >= _TRIGGER_MIN_WORDS words."""
    phrases: set[str] = set()
    for span in _QUOTED_SPAN_PATTERN.findall(description):
        normalized = " ".join(span.strip('"').split()).casefold()
        if len(normalized.split()) >= _TRIGGER_MIN_WORDS:
            phrases.add(normalized)
    return phrases


def _lint_trigger_overlaps(descriptions: dict[str, str]) -> list[str]:
    """Flag distinctive quoted trigger phrases shared across skills.

    Two skills that quote the same multi-word trigger phrase compete for the
    same retrieval, so the agent cannot tell which to load — the collision that
    let README and reference-docs requests route to the wrong skill. Matching is
    on normalized (case- and whitespace-folded) quoted phrases of at least
    ``_TRIGGER_MIN_WORDS`` words; short generic tokens are ignored.

    Parameters
    ----------
    descriptions
        Mapping of skill name to its frontmatter ``description``.

    Returns
    -------
    list[str]
        One message per colliding phrase, empty if none.
    """
    owners: dict[str, list[str]] = {}
    for skill_name, description in descriptions.items():
        for phrase in _quoted_trigger_phrases(description):
            if phrase in _TRIGGER_OVERLAP_ALLOWLIST:
                continue
            owners.setdefault(phrase, []).append(skill_name)

    findings: list[str] = []
    for phrase, skills in sorted(owners.items()):
        if len(skills) > 1:
            findings.append(
                f'trigger phrase "{phrase}" is claimed by multiple skills: '
                f"{', '.join(sorted(skills))}"
            )
    return findings


# Third-party modules the machinery test runner provides at gate time (see the
# Makefile's test-machinery step); imports of these are not engine references.
_MACHINERY_EXTERNAL_MODULES = frozenset({"pytest", "hypothesis", "numpy", "yaml"})

# Top-level (column-0) import statements in a machinery test module.
_MACHINERY_IMPORT_PATTERN = re.compile(
    r"^(?:import|from)\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE
)

# Engine file references built from the tests' SCRIPTS_DIR anchor, e.g.
# `SCRIPTS_DIR / "session-stop.py"` or `SCRIPTS_DIR / "queries" / "x.py"`.
# Captures the *entire* chain of quoted `/ "segment"` hops after SCRIPTS_DIR
# (upstream #644: a fixed one-or-two-segment cap silently truncated 3+-segment
# references, so a broken third segment never got checked). The chain is
# split into individual segments by `_MACHINERY_PATH_SEGMENT` below.
_MACHINERY_PATH_REFERENCE = re.compile(r'SCRIPTS_DIR((?:\s*/\s*"[^"\n]+")+)')
_MACHINERY_PATH_SEGMENT = re.compile(r'"([^"\n]+)"')


def _validate_machinery(machinery_dir: Path) -> list[str]:
    """Every engine file the machinery tests reference must have shipped.

    The machinery analogue of the wired-but-not-shipped hook guard: a test
    module that imports an engine module, or points its SCRIPTS_DIR anchor at
    an engine file, which the build did not ship would only fail later at
    machinery-test runtime — catch the inconsistency at smoke time instead.

    Parameters
    ----------
    machinery_dir
        The ``machinery/`` directory inside a plugin tree, expected to hold
        ``engine/`` and ``tests/`` subtrees.

    Returns
    -------
    list[str]
        Error strings for unresolved engine references.
    """
    errors: list[str] = []
    engine_dir = machinery_dir / "engine"
    tests_dir = machinery_dir / "tests"
    if not tests_dir.is_dir():
        return errors
    if not engine_dir.is_dir():
        return ["machinery/ ships tests/ but no engine/ directory"]

    for test_file in sorted(tests_dir.glob("*.py")):
        text = test_file.read_text(encoding="utf-8")

        for module_name in _MACHINERY_IMPORT_PATTERN.findall(text):
            if module_name in sys.stdlib_module_names:
                continue
            if module_name in _MACHINERY_EXTERNAL_MODULES:
                continue
            if module_name.startswith("test_") or module_name == "conftest":
                continue
            if (engine_dir / f"{module_name}.py").is_file():
                continue
            if (engine_dir / "queries" / f"{module_name}.py").is_file():
                continue
            errors.append(
                f"machinery test '{test_file.name}' imports '{module_name}' "
                f"but machinery/engine/{module_name}.py is not in the plugin"
            )

        for match in _MACHINERY_PATH_REFERENCE.finditer(text):
            segments = _MACHINERY_PATH_SEGMENT.findall(match.group(1))
            relative = "/".join(segments)
            if not (engine_dir / relative).exists():
                errors.append(
                    f"machinery test '{test_file.name}' references "
                    f"machinery/engine/{relative} but it is not in the plugin"
                )

    return errors


def _validate_machinery_wiring(machinery_dir: Path) -> list[str]:
    """W4 consistency checks on the shipped wiring spec + generated output.

    - Every wiring-spec entry's script must exist in ``engine/`` (the
      rendered hook commands would otherwise invoke absent scripts).
    - Every rendered adapter must parse (JSON for the hook surfaces, TOML
      for the Codex agent twins) — a build that shipped an unparseable
      adapter would only fail later inside a vault.
    - The vendor map must parse and keep unique targets: a duplicated
      target would silently overwrite one managed file with another.
    """
    errors: list[str] = []
    engine_dir = machinery_dir / "engine"

    spec_path = machinery_dir / "wiring" / "hooks-spec.json"
    if spec_path.is_file():
        try:
            spec = json.loads(spec_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            errors.append("machinery wiring/hooks-spec.json is not valid JSON")
            spec = {"entries": []}
        for entry in spec.get("entries", []):
            script = entry.get("script", "")
            if not (engine_dir / script).is_file():
                errors.append(
                    f"machinery wiring spec names '{script}' but "
                    f"machinery/engine/{script} is not in the plugin"
                )

    rendered_dir = machinery_dir / "rendered"
    if rendered_dir.is_dir():
        for rendered in sorted(rendered_dir.rglob("*")):
            if not rendered.is_file():
                continue
            relative = rendered.relative_to(machinery_dir).as_posix()
            if rendered.suffix == ".json":
                try:
                    json.loads(rendered.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    errors.append(f"machinery {relative} is not valid JSON")
            elif rendered.suffix == ".toml":
                try:
                    tomllib.loads(rendered.read_text(encoding="utf-8"))
                except tomllib.TOMLDecodeError:
                    errors.append(f"machinery {relative} is not valid TOML")

    map_path = machinery_dir / "vendor-map.json"
    if map_path.is_file():
        try:
            vendor_map = json.loads(map_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            errors.append("machinery vendor-map.json is not valid JSON")
            vendor_map = {"entries": []}
        seen: set[str] = set()
        for entry in vendor_map.get("entries", []):
            target = entry.get("target", "")
            if target in seen:
                errors.append(
                    f"machinery vendor-map.json has duplicate target '{target}'"
                )
            seen.add(target)

    return errors


def _resolve_skill_slug(plugin_path: Path, slug: str) -> Path | None:
    """Find the one plugin that ships ``slug``, or None if nothing does.

    Resolution is a flat glob across every sibling plugin, which is only
    unambiguous because slug uniqueness is a global invariant enforced at stamp
    time. If that invariant ever lapses this returns an arbitrary winner — so
    the stamper's duplicate-slug failure is what keeps this function honest,
    not anything here.

    Falls back to the plugin's own ``skills/`` when it has no siblings, which is
    the case for a synthetic single-plugin tree in a test.
    """
    own = plugin_path / "skills" / slug
    if own.is_dir():
        return own
    plugins_root = plugin_path.parent
    for candidate in sorted(plugins_root.glob(f"*/skills/{slug}")):
        if candidate.is_dir():
            return candidate
    return None


def smoke_test(plugin_path: Path) -> SmokeTestResult:
    """Validate internal consistency of a source plugin directory.

    Parameters
    ----------
    plugin_path
        Path to the plugin directory (e.g., plugins/workbench/). Plugins ship
        directly from this tree — there is no build step, so this validates
        what is on disk, not a derived artifact.

    Returns
    -------
    SmokeTestResult
        Result with any errors found.
    """
    result = SmokeTestResult()

    # 1. Validate .claude-plugin/plugin.json
    plugin_json_path = plugin_path / ".claude-plugin" / "plugin.json"
    if not plugin_json_path.exists():
        result.errors.append("plugin.json not found at .claude-plugin/plugin.json")
        return result

    try:
        plugin_data = json.loads(plugin_json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        result.errors.append("plugin.json is not valid JSON")
        return result

    for required_field in ["name", "version", "description"]:
        if required_field not in plugin_data:
            result.errors.append(
                f"plugin.json missing required field '{required_field}'"
            )

    # 2. Validate skills: every directory in skills/ has a valid SKILL.md
    skills_dir = plugin_path / "skills"
    skill_descriptions: dict[str, str] = {}
    if skills_dir.exists():
        for skill_dir in sorted(skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                result.errors.append(
                    f"Skill '{skill_dir.name}' directory has no SKILL.md"
                )
                continue

            skill_md_text = skill_md.read_text(encoding="utf-8")

            frontmatter = _parse_frontmatter(skill_md_text)
            if frontmatter is None:
                result.errors.append(
                    f"Skill '{skill_dir.name}/SKILL.md' has no valid frontmatter"
                )
                continue

            for req_field in ["name", "description"]:
                if req_field not in frontmatter or not frontmatter.get(req_field):
                    result.errors.append(
                        f"Skill '{skill_dir.name}/SKILL.md' missing required "
                        f"field '{req_field}'"
                    )

            description = frontmatter.get("description")
            if isinstance(description, str):
                skill_descriptions[skill_dir.name] = description
                process_markers = _lint_description_process_markers(description)
                if process_markers:
                    markers_str = ", ".join(process_markers)
                    result.errors.append(
                        f"Skill '{skill_dir.name}/SKILL.md' description is not "
                        f"trigger-only: found {markers_str}"
                    )

    # 2b. Cross-skill: no two skills may claim the same distinctive trigger.
    for overlap in _lint_trigger_overlaps(skill_descriptions):
        result.errors.append(f"Trigger collision — {overlap}")

    # 3. Validate agents: every directory in agents/ has a valid AGENT.md
    agents_dir = plugin_path / "agents"
    if agents_dir.exists():
        for agent_dir in sorted(agents_dir.iterdir()):
            if not agent_dir.is_dir():
                continue
            agent_md = agent_dir / "AGENT.md"
            if not agent_md.exists():
                result.errors.append(
                    f"Agent '{agent_dir.name}' directory has no AGENT.md"
                )
                continue

            frontmatter = _parse_frontmatter(agent_md.read_text(encoding="utf-8"))
            if frontmatter is None:
                result.errors.append(
                    f"Agent '{agent_dir.name}/AGENT.md' has no valid frontmatter"
                )
                continue

            # Check required fields
            for req_field in ["name", "description", "role"]:
                if req_field not in frontmatter:
                    result.errors.append(
                        f"Agent '{agent_dir.name}/AGENT.md' missing required "
                        f"field '{req_field}'"
                    )

            # Validate role
            role = frontmatter.get("role", "")
            if role and role not in VALID_ROLES:
                valid = ", ".join(repr(r) for r in VALID_ROLES)
                result.errors.append(
                    f"Agent '{agent_dir.name}/AGENT.md' has invalid role "
                    f"'{role}' (must be one of {valid})"
                )

            # Validate name matches directory
            name = frontmatter.get("name", "")
            if name and name != agent_dir.name:
                result.errors.append(
                    f"Agent '{agent_dir.name}/AGENT.md' name '{name}' does not "
                    f"match directory name '{agent_dir.name}'"
                )

            # Validate skills.add references against the WHOLE plugins/ tree,
            # not just this plugin's own skills/.
            #
            # Under the composition build an agent could only name a skill its
            # own preset composed in, because each preset was a closed bundle.
            # Flat plugins are not closed: one slug lives in exactly one plugin
            # (a global invariant `stamp.py` enforces), and a plugin relies on
            # its siblings being enabled — workshop-maintainer's agents reach
            # for `tdd`, `commit`, and `daa-code-review`, which are workbench's,
            # the same way its skills rely on workbench's hooks being present.
            # Scoping this check to the plugin would make that arrangement
            # unrepresentable and force three skills to be duplicated, which is
            # the thing slug uniqueness exists to prevent.
            skills_config = frontmatter.get("skills", {})
            if isinstance(skills_config, dict):
                for skill_ref in skills_config.get("add", []):
                    if not _resolve_skill_slug(plugin_path, skill_ref):
                        result.errors.append(
                            f"Agent '{agent_dir.name}/AGENT.md' references skill "
                            f"'{skill_ref}' in skills.add but no plugin ships it"
                        )

    # 4. Validate hooks: hooks.json references scripts (dispatched through the
    # run-hook.sh wrapper as `run-hook.sh [--uv] <script> [args...]`) that
    # exist in hooks/scripts/.
    hooks_json_path = plugin_path / "hooks" / "hooks.json"
    if hooks_json_path.exists():
        try:
            hooks_data = json.loads(hooks_json_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            result.errors.append("hooks/hooks.json is not valid JSON")
            hooks_data = {}

        hooks_scripts_dir = plugin_path / "hooks" / "scripts"
        for hook_type, hook_entries in hooks_data.get("hooks", {}).items():
            for entry in hook_entries:
                for hook in entry.get("hooks", []):
                    command = hook.get("command", "")
                    # Extract the script name dispatched through run-hook.sh,
                    # e.g. `.../hooks/run-hook.sh protect-files.py` or, with
                    # the optional uv-runner flag, `run-hook.sh --uv
                    # inject_persona.py`.
                    hook_match = re.search(
                        r'run-hook\.sh\s+(?:--uv\s+)?([^\s"]+)', command
                    )
                    if hook_match:
                        script_name = hook_match.group(1)
                        if not (hooks_scripts_dir / script_name).exists():
                            result.errors.append(
                                f"Hook script '{script_name}' referenced in "
                                f"hooks.json but not found in hooks/scripts/"
                            )

    # 5. Validate intra-skill reference links in SKILL.md files
    if skills_dir.exists():
        result.errors.extend(_validate_doc_links(skills_dir, "SKILL.md", "Skill"))

    # 5b. Validate intra-agent reference links in AGENT.md files
    if agents_dir.exists():
        result.errors.extend(_validate_doc_links(agents_dir, "AGENT.md", "Agent"))

    # 6. Validate settings.json is valid JSON
    settings_path = plugin_path / "settings.json"
    if settings_path.exists():
        try:
            json.loads(settings_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            result.errors.append("settings.json is not valid JSON")

    # 7. Validate the machinery payload: every engine file its tests reference
    # must exist in the plugin (the wired-but-not-shipped guard of check 4,
    # applied to machinery).
    machinery_dir = plugin_path / "machinery"
    if machinery_dir.exists():
        result.errors.extend(_validate_machinery(machinery_dir))
        result.errors.extend(_validate_machinery_wiring(machinery_dir))

    return result


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: uv run python -m scripts.smoke_test <plugin_name>")
        sys.exit(1)

    plugin_name = sys.argv[1]
    plugin_path = Path(__file__).resolve().parent.parent / "plugins" / plugin_name

    if not plugin_path.is_dir():
        print(f"FAIL: no plugin directory at plugins/{plugin_name}")
        sys.exit(1)

    result = smoke_test(plugin_path)

    if result.passed:
        print(f"PASS: plugin '{plugin_name}' is internally consistent")
    else:
        print(f"FAIL: plugin '{plugin_name}' has {len(result.errors)} error(s):")
        for error in result.errors:
            print(f"  - {error}")
        sys.exit(1)
