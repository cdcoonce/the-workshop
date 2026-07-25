"""Regenerate vendor-map.json (schema 2) for the machinery payload (W4).

The map is committed-generated, like ``dist/``: this tool rebuilds it at
build time (``scripts/build_preset.py``) and ``make verify-generated`` fails
when the committed copy is stale. Hand-editing the map is never the move —
change the trees it describes and rebuild.

Sections, in emitted order:

1. ``engine/**``                    -> ``.claude/scripts/**``   (v1 rule)
2. ``agents/*.md``                  -> ``.claude/agents/*.md``  (canonical)
3. ``rendered/codex-agents/*.toml`` -> ``.codex/agents/*.toml`` (generated twins)
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
        Machinery payload root (``engine/``, ``agents/``, ``rendered/``),
        whose parent is the preset root holding the sibling ``skills/`` tree.
    """
    entries: list[dict] = []

    for relative in _tree_files(machinery_dir / "engine"):
        entries.append(
            {
                "kind": "file",
                "source": f"engine/{relative}",
                "target": f".claude/scripts/{relative}",
            }
        )

    agent_names = [
        path.stem for path in sorted((machinery_dir / "agents").glob("*.md"))
    ] if (machinery_dir / "agents").is_dir() else []
    for name in agent_names:
        entries.append(
            {
                "kind": "file",
                "source": f"agents/{name}.md",
                "target": f".claude/agents/{name}.md",
            }
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
