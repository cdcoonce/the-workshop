"""Generate Claude and Codex marketplace indexes from preset manifests.

Scans presets/ for manifest.json files and produces marketplace indexes at
.claude-plugin/marketplace.json and .agents/plugins/marketplace.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _scan_presets(presets_dir: Path) -> list[dict[str, str]]:
    """Scan *presets_dir* and return one entry per preset that has a manifest.

    Parameters
    ----------
    presets_dir
        Directory containing one sub-directory per preset.

    Returns
    -------
    list[dict[str, str]]
        Unsorted list of plugin descriptor dicts with keys
        ``name``, ``version``, ``description``, and ``source``.
    """
    plugins: list[dict[str, str]] = []
    for preset_dir in sorted(presets_dir.iterdir()):
        if not preset_dir.is_dir():
            continue
        manifest_path = preset_dir / "manifest.json"
        if not manifest_path.exists():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        plugins.append({
            "name": manifest["name"],
            "version": manifest.get("version", "0.0.0"),
            "description": manifest.get("description", ""),
            "source": f"./dist/{manifest['name']}",
        })
    return plugins


def _to_codex_plugin_entry(plugin: dict[str, str]) -> dict[str, object]:
    """Convert a Claude marketplace plugin entry to Codex marketplace shape."""
    return {
        "name": plugin["name"],
        "source": {
            "source": "local",
            "path": plugin["source"],
        },
        "policy": {
            "installation": "AVAILABLE",
            "authentication": "ON_INSTALL",
        },
        "category": "Productivity",
    }


def build_marketplace(repo_root: Path | None = None) -> Path:
    """Generate marketplace.json files listing all available plugins.

    Parameters
    ----------
    repo_root
        Root of the template repo. Defaults to current working directory.

    Returns
    -------
    Path
        Path to the generated marketplace.json file.
    """
    root = repo_root or Path.cwd()
    presets_dir = root / "presets"

    plugins = _scan_presets(presets_dir)
    plugins.sort(key=lambda p: p["name"])

    claude_marketplace_dir = root / ".claude-plugin"
    claude_marketplace_dir.mkdir(parents=True, exist_ok=True)

    claude_marketplace = {
        "name": "claude-workflow",
        "owner": {"name": "Charles Coonce"},
        "plugins": plugins,
    }

    claude_marketplace_path = claude_marketplace_dir / "marketplace.json"
    claude_marketplace_path.write_text(
        json.dumps(claude_marketplace, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    codex_marketplace_dir = root / ".agents" / "plugins"
    codex_marketplace_dir.mkdir(parents=True, exist_ok=True)
    codex_marketplace = {
        "name": "claude-workflow",
        "interface": {"displayName": "Claude Workflow"},
        "plugins": [_to_codex_plugin_entry(plugin) for plugin in plugins],
    }

    codex_marketplace_path = codex_marketplace_dir / "marketplace.json"
    codex_marketplace_path.write_text(
        json.dumps(codex_marketplace, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    return claude_marketplace_path


if __name__ == "__main__":
    output = build_marketplace()
    print(f"Generated marketplace: {output}")
