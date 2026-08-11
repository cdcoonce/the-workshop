"""Render per-runtime hook/agent adapters from the runtime-neutral wiring (W4).

One spec, three rendered surfaces. ``wiring/hooks-spec.json`` describes the
vault's hook wiring once — event, engine-relative script, args, timeout, and a
semantic matcher intent instead of a runtime regex. The canonical agent
definitions live in the plugin's own ``agents/<name>/AGENT.md`` — Claude Code's
registration surface, and the only place it discovers plugin agents. (They used
to sit in ``machinery/agents/``, where the CLI never saw them and every vault
had to vendor its own copies to get them at all; see #667.) This tool renders
both into ``rendered/``:

- ``rendered/claude-settings-hooks.json`` — the exact VALUE of the ``hooks``
  key for a vault's ``.claude/settings.json`` (vendored as a json-key merge,
  never a file copy — settings.json carries unmanaged sibling keys).
- ``rendered/codex-hooks.json`` — the full ``.codex/hooks.json`` file body.
  Per COMPATIBILITY.md (2026-07-25): the flat repo-level path is the proven
  one, Codex reads the Claude-style schema, hook cwd is the workspace root
  (so the ``${CLAUDE_PROJECT_DIR:-.}`` fallback resolves), and matchers must
  stay dual-convention — hence the shared command template and the
  ``file-write`` intent expanding to both runtimes' tool-ID spellings.
- ``rendered/codex-agents/<name>.toml`` — a generated twin per agent that
  declares ``codex`` in its ``runtimes`` frontmatter (field mapping:
  ``name``/``description`` plus the full body as ``developer_instructions``).
  Where a hand-written vault TOML drifted from its ``AGENT.md``, the
  ``AGENT.md`` wins. Codex needs these vendored because a Codex plugin
  **cannot** ship agents — its manifest schema has no ``agents`` key
  (COMPATIBILITY.md) — so unlike Claude, it has no plugin path to them.
  Agents without the declaration are Claude-only and get no twin, which is
  what keeps the builder agents out of every vault's ``.codex/agents/``.

Run by ``scripts/stamp.py`` (and standalone via
``python wiring_gen.py``). Output is byte-stable across runs: no timestamps,
fixed serializers, sorted directory iteration. Event order in the rendered
hooks follows spec order, which is semantic — it must reproduce the vault's
live settings.json ``hooks`` key byte-for-byte (proven by fixture test).

Python stdlib only, like every machinery tool.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

# Semantic matcher intents -> the literal matcher both runtimes receive.
# Dual-convention on purpose: Codex tool IDs are lowercase/underscored
# (`write`, `edit`, `multi_edit`), Claude Code's are CamelCase — one matcher
# string serves both (COMPATIBILITY.md, verified 2026-07-25).
MATCHER_INTENTS = {
    "file-write": "write|edit|multiedit|multi_edit|Write|Edit|MultiEdit",
}

# Both runtimes invoke hooks through the vault's run-hook.sh shim; Codex's
# hook cwd is the workspace root, so the same project-dir fallback works.
_COMMAND_TEMPLATE = (
    'bash "${{CLAUDE_PROJECT_DIR:-.}}"/.claude/scripts/run-hook.sh {script}'
)

_SPEC_RELPATH = Path("wiring") / "hooks-spec.json"
_REQUIRED_ENTRY_FIELDS = ("event", "script", "args", "timeout_ms")


class WiringSpecError(Exception):
    """Raised when the wiring spec is unreadable, malformed, or inconsistent."""


def load_spec(machinery_dir: Path) -> list[dict]:
    """Load and validate the wiring spec against the machinery dir.

    Parameters
    ----------
    machinery_dir
        Machinery payload root holding ``wiring/hooks-spec.json`` and
        ``engine/``.

    Returns
    -------
    list[dict]
        The validated spec entries, in file order.

    Raises
    ------
    WiringSpecError
        On unreadable/invalid JSON, an unsupported schema, a malformed entry,
        an unknown matcher intent, or a script the engine does not ship.
    """
    spec_path = machinery_dir / _SPEC_RELPATH
    if not spec_path.is_file():
        raise WiringSpecError(f"no wiring spec at {spec_path}")
    try:
        data = json.loads(spec_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise WiringSpecError(f"wiring spec at {spec_path} is not valid JSON: {exc}")
    if data.get("schema") != 1:
        raise WiringSpecError(
            f"wiring spec schema {data.get('schema')!r} is not supported"
        )
    entries = data.get("entries")
    if not isinstance(entries, list) or not entries:
        raise WiringSpecError("wiring spec has no entries")
    for entry in entries:
        for field in _REQUIRED_ENTRY_FIELDS:
            if field not in entry:
                raise WiringSpecError(f"wiring entry missing {field!r}: {entry}")
        matcher = entry.get("matcher")
        if matcher is not None and matcher not in MATCHER_INTENTS:
            raise WiringSpecError(
                f"unknown matcher intent {matcher!r} "
                f"(known: {sorted(MATCHER_INTENTS)})"
            )
        script = entry["script"]
        if not (machinery_dir / "engine" / script).is_file():
            raise WiringSpecError(
                f"wiring spec names {script!r} but engine/ does not ship it"
            )
    return entries


def _hook_command(entry: dict) -> str:
    command = _COMMAND_TEMPLATE.format(script=entry["script"])
    if entry["args"]:
        command += " " + " ".join(entry["args"])
    return command


def render_claude_settings_hooks(entries: list[dict]) -> dict:
    """The value of the ``hooks`` key, in Claude Code settings.json shape.

    Events appear in spec order; entries sharing an event and matcher intent
    share one matcher group (so the Stop chain is one group of three hooks),
    exactly reproducing the vault's live wiring.
    """
    events: dict[str, list[dict]] = {}
    for entry in entries:
        matcher = entry.get("matcher")
        groups = events.setdefault(entry["event"], [])
        literal = MATCHER_INTENTS[matcher] if matcher is not None else None
        group = next(
            (g for g in groups if g.get("matcher") == literal or
             (literal is None and "matcher" not in g)),
            None,
        )
        if group is None:
            group = {} if literal is None else {"matcher": literal}
            group["hooks"] = []
            groups.append(group)
        group["hooks"].append(
            {
                "type": "command",
                "command": _hook_command(entry),
                "timeout": entry["timeout_ms"],
            }
        )
    return events


def render_codex_hooks(entries: list[dict]) -> dict:
    """The full ``.codex/hooks.json`` body: same schema, same commands."""
    return {"hooks": render_claude_settings_hooks(entries)}


# ---------------------------------------------------------------------------
# Codex agent TOML twins
# ---------------------------------------------------------------------------


def _parse_agent_md(md_path: Path) -> tuple[str, str, str]:
    """(name, description, body) from a canonical agent ``.md``.

    The frontmatter parse is deliberately minimal — plain ``key: value``
    scalars — because that is all the canonical agent files use; anything the
    TOML mapping does not carry (``role``, ``model``, ``skills``) stays
    Claude-runtime-only and is ignored here.
    """
    text = md_path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise WiringSpecError(f"{md_path} has no frontmatter")
    end = text.find("\n---", 4)
    if end == -1:
        raise WiringSpecError(f"{md_path} has unterminated frontmatter")
    frontmatter = text[4:end]
    body = text[end + len("\n---"):]
    fields = {}
    for line in frontmatter.splitlines():
        if ":" in line and not line.startswith((" ", "\t", "-")):
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()
    for required in ("name", "description"):
        if not fields.get(required):
            raise WiringSpecError(f"{md_path} frontmatter missing {required!r}")
    return fields["name"], fields["description"], body.strip("\n")


def _toml_basic_string(value: str) -> str:
    """A single-line TOML basic string."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _toml_multiline_body(value: str) -> str:
    """Escape a body for a TOML multi-line basic string.

    Backslashes are escaped so path-like content survives; runs of three or
    more quotes are broken by escaping every third quote so the delimiter can
    never appear inside the string. (A trailing single or double quote before
    the closing delimiter is valid TOML.)
    """
    escaped = value.replace("\\", "\\\\")
    return escaped.replace('"""', '""\\"')


def _agent_runtimes(md_path: Path) -> tuple[str, ...]:
    """The runtimes an agent serves, from its ``runtimes:`` frontmatter list.

    Absent means Claude-only. That default is deliberate: agents now share one
    directory with the Claude-only builder agents, and a permissive default
    would silently render twins for all of them — expanding what ``/vault-init``
    scaffolds into every new vault's ``.codex/agents/``. Opting in is a visible
    line in a file; opting out would be an invisible omission.

    Parsed as a flat ``[a, b]`` scalar because that is all these files use, and
    ``_parse_agent_md`` already reads frontmatter the same minimal way.
    """
    text = md_path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return ()
    end = text.find("\n---", 4)
    if end == -1:
        return ()
    for line in text[4:end].splitlines():
        key, _, value = line.partition(":")
        if key.strip() == "runtimes":
            return tuple(
                part.strip()
                for part in value.strip().strip("[]").split(",")
                if part.strip()
            )
    return ()


def render_codex_agent_toml(md_path: Path) -> str:
    """Render one canonical agent ``.md`` into its Codex TOML twin.

    The field mapping mirrors the vault's hand-written ``.codex/agents``
    files: ``name``, ``description``, and the full body as
    ``developer_instructions``. The ``.md`` is canonical — content the hand
    TOMLs dropped is regenerated here.
    """
    name, description, body = _parse_agent_md(md_path)
    return (
        f"name = {_toml_basic_string(name)}\n"
        f"description = {_toml_basic_string(description)}\n"
        f'developer_instructions = """\n{_toml_multiline_body(body)}"""\n'
    )


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


def _dump_json(value: dict) -> str:
    return json.dumps(value, indent=2) + "\n"


def agents_dir_for(machinery_dir: Path) -> Path:
    """The plugin's agent registration surface, given its machinery dir.

    One definition of the location, shared with ``vendor_map_gen``, so the two
    generators cannot disagree about where agents live.
    """
    return machinery_dir.parent / "agents"


def generate(machinery_dir: Path, out_dir: Path | None = None) -> Path:
    """Render every adapter surface into ``out_dir`` (default: rendered/).

    The output directory is rebuilt from scratch so removed agents cannot
    leave stale twins behind. Byte-stable across runs.
    """
    entries = load_spec(machinery_dir)
    destination = out_dir if out_dir is not None else machinery_dir / "rendered"
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)

    (destination / "claude-settings-hooks.json").write_text(
        _dump_json(render_claude_settings_hooks(entries)), encoding="utf-8"
    )
    (destination / "codex-hooks.json").write_text(
        _dump_json(render_codex_hooks(entries)), encoding="utf-8"
    )

    # The plugin's agents/ sits beside machinery/, not inside it, because that
    # is where Claude Code looks. Name the twin from the agent's directory —
    # every file here is `AGENT.md`, so `md_path.stem` would collide on all of
    # them.
    agents_dir = agents_dir_for(machinery_dir)
    agent_sources = (
        sorted(
            path
            for path in agents_dir.glob("*/AGENT.md")
            if "codex" in _agent_runtimes(path)
        )
        if agents_dir.is_dir()
        else []
    )
    if agent_sources:
        (destination / "codex-agents").mkdir()
        for md_path in agent_sources:
            (destination / "codex-agents" / f"{md_path.parent.name}.toml").write_text(
                render_codex_agent_toml(md_path), encoding="utf-8"
            )
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="wiring_gen",
        description="Render per-runtime hook/agent adapters from the wiring spec.",
    )
    parser.add_argument(
        "--machinery",
        default=str(Path(__file__).resolve().parent.parent),
        help="machinery dir holding wiring/ and engine/ (agents/ is read from "
        "its sibling, the plugin's registration surface) "
        "(default: this tool's own machinery dir)",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="output directory (default: <machinery>/rendered)",
    )
    args = parser.parse_args(argv)
    try:
        destination = generate(
            Path(args.machinery), Path(args.out) if args.out else None
        )
    except WiringSpecError as exc:
        print(f"ERROR: {exc}")
        return 2
    print(f"rendered wiring adapters -> {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
