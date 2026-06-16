"""Generate .claude-plugin/marketplace.json from all preset manifests.

Scans presets/ for manifest.json files and produces a single marketplace
index at .claude-plugin/marketplace.json in the repo root.
"""

from __future__ import annotations

import json
from pathlib import Path


def build_marketplace(repo_root: Path | None = None) -> Path:
    """Generate marketplace.json listing all available plugins.

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
    for preset_dir in sorted(presets_dir.iterdir()):
        if not preset_dir.is_dir():
            continue
        manifest_path = preset_dir / "manifest.json"
        if not manifest_path.exists():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        name = manifest.get("name")
        if name is None:
            raise ValueError(
                f"Preset manifest missing required 'name' field: {preset_dir.name} "
                f"({manifest_path})"
            )
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

    marketplace_dir = root / ".claude-plugin"
    marketplace_dir.mkdir(parents=True, exist_ok=True)

    marketplace = {
        "name": "claude-workflow",
        "owner": {"name": "Charles Coonce"},
        "plugins": plugins,
    }

    marketplace_path = marketplace_dir / "marketplace.json"
    marketplace_path.write_text(
        json.dumps(marketplace, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    return marketplace_path


if __name__ == "__main__":
    output = build_marketplace()
    print(f"Generated marketplace: {output}")
