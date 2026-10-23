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
import os
import stat
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


def plan(target: Path) -> dict[Path, tuple[bytes, int]]:
    """Every file to vendor as ``{destination: (bytes, mode)}``, runtime first.

    ``hooks.json`` is last on purpose: it is the file that makes Codex run
    anything, so it must never exist without the runtime it calls.
    """
    wiring_gen = _load_wiring_gen()
    entries = _load_entries()
    files: dict[Path, tuple[bytes, int]] = {
        target / _VENDOR_DIR / _RUNNER.name: _file(_RUNNER),
    }
    for name in sorted({e["script"] for e in entries} | set(_SUPPORT_MODULES)):
        files[target / _VENDOR_DIR / name] = _file(_HOOK_SCRIPTS / name)
    hooks = wiring_gen._dump_json(wiring_gen.render_codex_hooks(entries))
    files[target / ".codex" / "hooks.json"] = (hooks.encode("utf-8"), 0o644)
    return files


def _file(path: Path) -> tuple[bytes, int]:
    return path.read_bytes(), stat.S_IMODE(path.stat().st_mode)


def _blocker(dest: Path) -> str | None:
    """Why ``dest`` cannot be written at all (``--force`` does not help), if so."""
    if dest.is_symlink() and not dest.exists():
        return "is a dangling symlink"
    if dest.exists():
        if not dest.is_file():
            return "exists and is not a regular file"
        if not os.access(dest, os.W_OK):
            return "is not writable"
        return None
    ancestor = dest.parent
    while not ancestor.exists():
        if ancestor.is_symlink():
            return f"has a dangling symlink at {ancestor}"
        ancestor = ancestor.parent
    if not ancestor.is_dir():
        return f"needs {ancestor} to be a directory"
    if not os.access(ancestor, os.W_OK | os.X_OK):
        return f"needs {ancestor} to be writable"
    return None


def _write_all(files, status) -> None:
    """Write every pending file; on any OSError undo what this run changed."""
    undo: list[tuple[Path, bytes | None, int | None]] = []
    made_dirs: list[Path] = []
    try:
        for dest, (body, mode) in files.items():
            if status[dest] == "unchanged":
                continue
            missing = []
            parent = dest.parent
            while not parent.exists():
                missing.append(parent)
                parent = parent.parent
            dest.parent.mkdir(parents=True, exist_ok=True)
            made_dirs.extend(reversed(missing))
            if dest.exists():
                undo.append((dest, dest.read_bytes(), stat.S_IMODE(dest.stat().st_mode)))
            else:
                undo.append((dest, None, None))
            dest.write_bytes(body)
            os.chmod(dest, mode)
    except OSError:
        for dest, old, old_mode in reversed(undo):
            if old is None:
                dest.unlink(missing_ok=True)
            else:
                dest.write_bytes(old)
                os.chmod(dest, old_mode)
        for directory in reversed(made_dirs):
            try:
                directory.rmdir()
            except OSError:
                pass
        raise


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

    blocked = [(d, why) for d in files if (why := _blocker(d))]
    if blocked:
        for dest, why in blocked:
            print(f"ERROR: {dest.relative_to(target)} {why}")
        print("Nothing was written.")
        return 2

    status: dict[Path, str] = {}
    for dest, (body, _mode) in files.items():
        if not dest.exists():
            status[dest] = "written"
        elif dest.read_bytes() == body:
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

    try:
        _write_all(files, status)
    except OSError as exc:
        print(f"ERROR: {exc}")
        print("Nothing was left behind; the target is as it was.")
        return 2
    for dest, state in status.items():
        print(f"{'overwritten' if state == 'differs' else state:>11}  {dest.relative_to(target)}")
    print()
    print(TRUST_STEPS.format(target=target))
    return 0


if __name__ == "__main__":
    sys.exit(main())
