"""Regenerate vendor-map.json (schema 2) for the machinery payload (W4).

The map is committed-generated, but nothing rebuilds it automatically any
more: the composition build that used to invoke this tool died with the flat
reorg (#656), and ``scripts/stamp.py`` does not own ``vendor-map.json``. Run
this tool directly. Hand-editing the map is never the move — change the trees
it describes and regenerate.

Regenerating is currently a deliberate act, not a routine one. The scan
widened from the vault's own skills to all of workbench's when vault-ops
folded in, so a regeneration right now would commit a map that vendors the
entire workbench into the vault. Two tests are ``xfail(strict)`` on exactly
that, and #638 deletes this subsystem outright.

Sections, in emitted order:

1. ``engine/**``                    -> ``.claude/scripts/**``   (v1 rule),
   EXCEPT ``engine/vault_scope.py`` — scaffold-owned since W5: init renders
   it from ``scaffold/vault_scope.py.tmpl`` with the owner's note-dir
   taxonomy and upgrade never touches it, so it must stay out of the
   managed map (machinery_sync errors on any scaffold/managed overlap).
2. lifecycle tools                  -> ``.claude/scripts/`` (W5: the
   ``machinery_check.py``/``machinery_sync.py`` pair, vendored so hooks and
   afk Docker slices can run the drift check offline)
3. ``rendered/codex-agents/*.toml`` -> ``.codex/agents/*.toml`` (generated twins;
   Codex-only — Claude agents ship in the plugin's ``agents/`` dir and are not
   vendored at all, because Claude Code registers them from there)
4. ``rendered/codex-hooks.json``    -> ``.codex/hooks.json``
5. ``rendered/claude-settings-hooks.json``
                                    -> ``.claude/settings.json`` ``hooks`` key
   (``kind: "json-key"`` — a partial-file merge; settings.json carries
   unmanaged sibling keys a file copy would clobber)
6. sibling ``skills/**``            -> ``.claude/skills/**``    (source_root
7. sibling ``skills/**``            -> ``.codex/skills/**``      "preset")

Schema 2 because the map now carries non-schema-1 constructs: the json-key
kind and preset-root sources (skills live beside machinery/, not inside it).
A stale schema-1 reader vendored into a vault refuses the whole map loudly
("schema 2 is not supported") instead of tripping over the first unknown
construct — exactly the behavior wanted for stale tools.

Python stdlib only, deterministic output (sorted walks, fixed serializer).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

_JUNK_DIR_NAMES = frozenset(
    {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"}
)
_JUNK_FILE_NAMES = frozenset({".DS_Store"})
_JUNK_SUFFIXES = (".pyc",)

# Engine files owned by the scaffold tier (init writes them once with the
# owner's parameters; upgrade never touches them). They stay in engine/ so
# the machinery test-suite and sibling imports keep working in this repo,
# but they must never enter the managed map.
_SCAFFOLD_OWNED_ENGINE_FILES = frozenset({"vault_scope.py"})

# The lifecycle tool pair vendored into the vault so hooks and afk Docker
# slices can run the drift check offline (.claude/scripts is already an
# UNTRACKED scan root, so mapping them keeps the check clean).
_VENDORED_TOOLS = ("machinery_check.py", "machinery_sync.py")


def _tree_files(root: Path) -> list[str]:
    """Sorted junk-free relative posix paths of every file under ``root``."""
    if not root.is_dir():
        return []
    files = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if _JUNK_DIR_NAMES & set(relative.parts[:-1]):
            continue
        if relative.name in _JUNK_FILE_NAMES or relative.name.endswith(
            _JUNK_SUFFIXES
        ):
            continue
        files.append(relative.as_posix())
    return files


def generate_map(machinery_dir: Path) -> dict:
    """Build the schema-2 vendor map dict for ``machinery_dir``.

    Parameters
    ----------
    machinery_dir
        Machinery payload root (``engine/``, ``rendered/``), whose parent is
        the preset root holding the sibling ``skills/`` and ``agents/`` trees.
    """
    entries: list[dict] = []

    for relative in _tree_files(machinery_dir / "engine"):
        if relative in _SCAFFOLD_OWNED_ENGINE_FILES:
            continue
        entries.append(
            {
                "kind": "file",
                "source": f"engine/{relative}",
                "target": f".claude/scripts/{relative}",
            }
        )

    for tool_name in _VENDORED_TOOLS:
        entries.append(
            {
                "kind": "file",
                "source": f"tools/{tool_name}",
                "target": f".claude/scripts/{tool_name}",
            }
        )

    # Claude agents are NOT vendored: they ship in the plugin's own agents/ dir
    # and Claude Code registers them from there. Codex twins still are, because
    # a Codex plugin cannot carry agents at all — its manifest schema has no
    # `agents` key (COMPATIBILITY.md), so vendoring is the only delivery path
    # that runtime has.
    #
    # The twin list is derived from what wiring_gen actually rendered rather
    # than re-deciding it here. Two independent answers to "which agents serve
    # Codex?" is exactly the drift this map exists to prevent.
    rendered_agents = machinery_dir / "rendered" / "codex-agents"
    agent_names = (
        [path.stem for path in sorted(rendered_agents.glob("*.toml"))]
        if rendered_agents.is_dir()
        else []
    )
    for name in agent_names:
        entries.append(
            {
                "kind": "file",
                "source": f"rendered/codex-agents/{name}.toml",
                "target": f".codex/agents/{name}.toml",
            }
        )

    entries.append(
        {
            "kind": "file",
            "source": "rendered/codex-hooks.json",
            "target": ".codex/hooks.json",
        }
    )
    entries.append(
        {
            "kind": "json-key",
            "source": "rendered/claude-settings-hooks.json",
            "target": ".claude/settings.json",
            "key": "hooks",
        }
    )

    skill_files = _tree_files(machinery_dir.parent / "skills")
    for runtime in (".claude", ".codex"):
        for relative in skill_files:
            entries.append(
                {
                    "kind": "file",
                    "source": f"skills/{relative}",
                    "source_root": "preset",
                    "target": f"{runtime}/skills/{relative}",
                }
            )

    return {"schema": 2, "entries": entries}


def generate(machinery_dir: Path) -> Path:
    """Write vendor-map.json into ``machinery_dir`` and return its path."""
    map_path = machinery_dir / "vendor-map.json"
    map_path.write_text(
        json.dumps(generate_map(machinery_dir), indent=2) + "\n",
        encoding="utf-8",
    )
    return map_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="vendor_map_gen",
        description="Regenerate the machinery vendor map (schema 2).",
    )
    parser.add_argument(
        "--machinery",
        default=str(Path(__file__).resolve().parent.parent),
        help="machinery dir to map (default: this tool's own machinery dir)",
    )
    args = parser.parse_args(argv)
    map_path = generate(Path(args.machinery))
    print(f"wrote {map_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
