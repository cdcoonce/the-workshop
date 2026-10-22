#!/usr/bin/env python3
"""Vendor a Codex-functional ``.codex/hooks.json`` into a target repo (#486).

Wraps ``render_codex_hooks`` from the machinery's ``wiring_gen`` (read-only use)
over a skill-owned spec that lists only the hooks that still work when Codex
sends no stdin payload. Writes ``<repo>/.codex/hooks.json`` plus the runtime its
commands call, under ``<repo>/.claude/scripts/`` (the path wiring_gen's command
template points at). Rerun-safe; refuses to replace a differing file without
``--force``, and refuses before writing anything so there is no half-install.

Python stdlib only.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = SKILL_DIR.parents[2]
SPEC_PATH = SKILL_DIR / "codex-hooks-spec.json"
_WIRING_GEN = PLUGIN_ROOT / "machinery" / "tools" / "wiring_gen.py"
_HOOK_SCRIPTS = PLUGIN_ROOT / "hooks" / "scripts"
_RUNNER = PLUGIN_ROOT / "machinery" / "engine" / "run-hook.sh"
# Where wiring_gen's command template expects the hook runner, in the target repo.
_VENDOR_DIR = Path(".claude") / "scripts"
# Library modules the vendored hook imports as siblings.
_SUPPORT_MODULES = ("_git_baseline.py",)

TRUST_STEPS = """\
Two trust steps remain for you; Codex skips untrusted hooks with no output:
  1. Project trust: add to ~/.codex/config.toml
       [projects."{target}"]
       trust_level = "trusted"
  2. Per-hook trust: start Codex in the repo and approve each hook when
     prompted (Codex records a trusted_hash per hook, and re-prompts when it
     changes).
See COMPATIBILITY.md -> Codex -> Hooks."""


def _load_wiring_gen():
    spec = importlib.util.spec_from_file_location("wiring_gen", _WIRING_GEN)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_entries() -> list[dict]:
    data = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if data.get("schema") != 1 or not data.get("entries"):
        raise ValueError(f"bad codex hooks spec at {SPEC_PATH}")
    for entry in data["entries"]:
        if not (_HOOK_SCRIPTS / entry["script"]).is_file():
            raise ValueError(f"spec names {entry['script']!r}; workbench ships no such hook")
    return data["entries"]


def plan(target: Path) -> dict[Path, bytes]:
    """Every file to vendor, as ``{absolute destination: bytes}``."""
    wiring_gen = _load_wiring_gen()
    entries = _load_entries()
    files: dict[Path, bytes] = {
        target / ".codex" / "hooks.json": wiring_gen._dump_json(
            wiring_gen.render_codex_hooks(entries)
        ).encode("utf-8"),
        target / _VENDOR_DIR / _RUNNER.name: _RUNNER.read_bytes(),
    }
    for name in sorted({e["script"] for e in entries} | set(_SUPPORT_MODULES)):
        files[target / _VENDOR_DIR / name] = (_HOOK_SCRIPTS / name).read_bytes()
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="codex_enable",
        description="Vendor a Codex-functional .codex/hooks.json into a repo.",
    )
    parser.add_argument("target", help="repo root to vendor the hooks into")
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite files that differ from what this skill renders",
    )
    args = parser.parse_args(argv)
    target = Path(args.target).resolve()
    if not target.is_dir():
        print(f"ERROR: {args.target} is not a directory")
        return 2
    try:
        files = plan(target)
    except (OSError, ValueError, KeyError) as exc:
        print(f"ERROR: {exc}")
        return 2

    status: dict[Path, str] = {}
    for dest, body in files.items():
        if not dest.exists():
            status[dest] = "written"
        elif dest.is_file() and dest.read_bytes() == body:
            status[dest] = "unchanged"
        else:
            status[dest] = "differs"
    differing = [d for d, s in status.items() if s == "differs"]
    if differing and not args.force:
        print("REFUSED: these files already exist and differ from what codex-enable renders:")
        for dest in differing:
            print(f"  {dest.relative_to(target)}")
        print("Nothing was written. Review them, then rerun with --force to overwrite.")
        return 1

    for dest, body in files.items():
        if status[dest] == "unchanged":
            continue
        if status[dest] == "differs":
            status[dest] = "overwritten"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body)
    for dest, state in status.items():
        print(f"{state:>11}  {dest.relative_to(target)}")
    print()
    print(TRUST_STEPS.format(target=target))
    return 0


if __name__ == "__main__":
    sys.exit(main())
