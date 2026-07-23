"""Tests that every preset ships the hook scripts its hooks.json references.

A preset inherits core hooks into hooks.json via settings-base.json, but only
copies the scripts named in its manifest's core.hooks/preset_hooks. When those
two disagree the built plugin wires hooks whose scripts do not exist, and every
matching tool call fails with a FileNotFoundError from run-hook.sh. PreToolUse
hooks fail closed, so a missing protect-files.py blocks all Write and Edit.
"""

import json
from pathlib import Path
import re

import pytest

from scripts.build_preset import build_preset

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PRESET_NAMES = sorted(
    path.name for path in (REPOSITORY_ROOT / "presets").iterdir() if path.is_dir()
)

# run-hook.sh resolves a bare script name against hooks/scripts/.
SCRIPT_REFERENCE = re.compile(r"run-hook\.sh\s+(\S+\.py)")


def _referenced_scripts(hooks_config: dict) -> set[str]:
    """Collect every .py filename a hooks.json command invokes."""
    return set(SCRIPT_REFERENCE.findall(json.dumps(hooks_config)))


@pytest.mark.parametrize("preset_name", PRESET_NAMES)
def test_manifest_declares_every_inherited_hook_script(preset_name: str) -> None:
    """Each preset's manifest declares the scripts its settings wire up."""
    manifest = json.loads(
        (REPOSITORY_ROOT / "presets" / preset_name / "manifest.json").read_text()
    )
    declared = set(manifest["core"].get("hooks", [])) | set(
        manifest.get("preset_hooks", [])
    )

    if manifest.get("base_settings", True):
        settings = json.loads(
            (REPOSITORY_ROOT / "core" / "settings-base.json").read_text()
        )
        inherited = _referenced_scripts({"hooks": settings.get("hooks", {})})
    else:
        inherited = set()

    missing = inherited - declared
    assert not missing, (
        f"{preset_name} inherits core hooks {sorted(missing)} from "
        f"settings-base.json but does not declare them in manifest core.hooks, "
        f"so build_preset ships hooks.json entries with no scripts behind them. "
        f"Either declare them or set base_settings=false."
    )


@pytest.mark.parametrize("preset_name", PRESET_NAMES)
def test_built_preset_ships_every_referenced_hook_script(preset_name: str) -> None:
    """A built preset's hooks.json never references a script it omits."""
    hooks_dir = build_preset(preset_name, repo_root=REPOSITORY_ROOT) / "hooks"
    hooks_config = json.loads((hooks_dir / "hooks.json").read_text())
    referenced = _referenced_scripts(hooks_config)
    shipped = {path.name for path in (hooks_dir / "scripts").glob("*.py")}

    missing = referenced - shipped
    assert not missing, (
        f"dist/{preset_name}/hooks/hooks.json invokes {sorted(missing)} but "
        f"hooks/scripts/ only contains {sorted(shipped)}. Installing this "
        f"preset breaks every tool call the missing hooks match."
    )
