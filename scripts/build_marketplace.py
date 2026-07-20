"""Generate Claude and Codex marketplace indexes from preset manifests.

Scans presets/ for manifest.json files and produces marketplace indexes at
.claude-plugin/marketplace.json and .agents/plugins/marketplace.json.
"""

from __future__ import annotations

import json
from pathlib import Path


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

    plugins: list[dict[str, str]] = []
    seen_names: dict[str, str] = {}
    for preset_dir in sorted(presets_dir.iterdir()):
        if not preset_dir.is_dir():
            continue
        manifest_path = preset_dir / "manifest.json"
        if not manifest_path.exists():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Preset manifest is not valid JSON: {preset_dir.name} "
                f"({manifest_path}): {exc}"
            ) from exc
        name = manifest.get("name")
        if name is None:
            raise ValueError(
                f"Preset manifest missing required 'name' field: {preset_dir.name} "
                f"({manifest_path})"
            )
        if name in seen_names:
            raise ValueError(
                f"Duplicate plugin name '{name}' in presets "
                f"'{seen_names[name]}' and '{preset_dir.name}'"
            )
        seen_names[name] = preset_dir.name
        plugins.append(
            {
                "name": name,
                "version": manifest.get("version", "0.0.0"),
                "description": manifest.get("description", ""),
                # Derive source from the directory name -- build_preset writes
                # output to dist/<directory name>, so keying off the manifest
                # 'name' would let the advertised path drift from what is built.
                "source": f"./dist/{preset_dir.name}",
            }
        )

    plugins.sort(key=lambda p: p["name"])

    claude_marketplace_dir = root / ".claude-plugin"
    claude_marketplace_dir.mkdir(parents=True, exist_ok=True)

    claude_marketplace = {
        "name": "the-workshop",
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
        "name": "the-workshop",
        "interface": {"displayName": "The Workshop"},
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
