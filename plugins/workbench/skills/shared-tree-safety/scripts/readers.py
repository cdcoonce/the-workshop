#!/usr/bin/env python3
"""Report who else uses a tree, index, venv or cache.

Given one or more needles (a path, a venv, a script name), list the live
processes whose full command line contains one, the MCP / launchd / cron
registrations that name one, the plugin-cache holders that pin a version, and
the other checkouts of a needle that is a path inside a git repository.

Read-only. The only signal ever sent is signal 0.

Exit codes: 0 nothing live and nothing held, 3 a live process or live holder,
2 usage error.
"""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import subprocess
import sys
from pathlib import Path

BLIND_SPOTS = (
    "Blind spots: an open-handle probe misses stores opened per query; nothing "
    "here shows how often a reader is exercised, only that it exists or would "
    "start."
)


def _note(message: str) -> None:
    print(message, file=sys.stderr)


def _matches(needles: list[str], *texts: object) -> bool:
    return any(
        needle in text
        for text in texts
        if isinstance(text, str)
        for needle in needles
    )


def _process_rows() -> list[dict]:
    result = subprocess.run(
        ["ps", "-axww", "-o", "pid=,ppid=,etime=,command="],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        _note(f"ps failed: {result.stderr.strip()}")
        raise SystemExit(2)
    rows = []
    for line in result.stdout.splitlines():
        parts = line.split(None, 3)
        if len(parts) < 4 or not parts[0].isdigit() or not parts[1].isdigit():
            continue
        rows.append(
            {
                "pid": int(parts[0]),
                "ppid": int(parts[1]),
                "etime": parts[2],
                "command": parts[3],
            }
        )
    return rows


def live_processes(needles: list[str], ignore: set[int]) -> list[dict]:
    rows = _process_rows()
    parent_of = {row["pid"]: row["ppid"] for row in rows}
    ancestors: set[int] = set()
    pid = os.getpid()
    while pid and pid not in ancestors:
        ancestors.add(pid)
        pid = parent_of.get(pid, 0)
    excluded = ancestors | ignore
    own = os.getpid()
    return [
        row
        for row in rows
        if row["pid"] not in excluded
        and not (row["ppid"] == own and row["command"].startswith("ps -axww"))
        and _matches(needles, row["command"])
    ]


def _server_entries(
    source: str, scope: str, servers: object, needles: list[str]
) -> list[dict]:
    entries = []
    if not isinstance(servers, dict):
        return entries
    for name, server in servers.items():
        if not isinstance(server, dict):
            continue
        args = server.get("args")
        elements = args if isinstance(args, list) else []
        if _matches(needles, server.get("command"), *elements):
            entries.append({"source": source, "scope": scope, "name": str(name)})
    return entries


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        _note(f"skipped {path}: {exc}")
        return None


def declared_claude(home: Path, needles: list[str]) -> list[dict]:
    data = _read_json(home / ".claude.json")
    if not isinstance(data, dict):
        return []
    entries = _server_entries("claude", "user", data.get("mcpServers"), needles)
    projects = data.get("projects")
    if isinstance(projects, dict):
        for path, project in projects.items():
            if isinstance(project, dict):
                entries += _server_entries(
                    "claude", str(path), project.get("mcpServers"), needles
                )
    return entries


def declared_codex(home: Path, needles: list[str]) -> list[dict]:
    path = home / ".codex" / "config.toml"
    try:
        import tomllib
    except ImportError:
        _note("skipped codex: tomllib is unavailable (Python older than 3.11)")
        return []
    try:
        data = tomllib.loads(path.read_text())
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as exc:
        _note(f"skipped {path}: {exc}")
        return []
    return _server_entries("codex", "user", data.get("mcp_servers"), needles)


def declared_launchd(home: Path, needles: list[str]) -> list[dict]:
    entries = []
    for path in sorted((home / "Library" / "LaunchAgents").glob("*.plist")):
        try:
            data = plistlib.loads(path.read_bytes())
        except Exception as exc:  # malformed plists raise assorted parser errors
            _note(f"skipped {path}: {exc}")
            continue
        if not isinstance(data, dict):
            continue
        arguments = data.get("ProgramArguments")
        elements = arguments if isinstance(arguments, list) else []
        if _matches(needles, data.get("WorkingDirectory"), *elements):
            entries.append(
                {
                    "source": "launchd",
                    "scope": str(path.relative_to(home)),
                    "name": str(data.get("Label", path.stem)),
                }
            )
    return entries


def declared_cron(needles: list[str]) -> list[dict]:
    try:
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    except OSError:
        return []
    if result.returncode != 0:
        return []
    return [
        {"source": "cron", "scope": "crontab", "name": str(number)}
        for number, line in enumerate(result.stdout.splitlines(), start=1)
        if _matches(needles, line)
    ]


def declared_mcp_json(repos: list[str], needles: list[str]) -> list[dict]:
    entries = []
    for repo in repos:
        data = _read_json(Path(repo) / ".mcp.json")
        if isinstance(data, dict):
            entries += _server_entries("mcp-json", repo, data.get("mcpServers"), needles)
    return entries


def _pid_is_live(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except (ProcessLookupError, OverflowError):
        return False
    return True


def holders(dirs: list[str], ignore: set[int]) -> list[dict]:
    found = []
    for directory in dirs:
        for marker in sorted(Path(directory).glob("*/.in_use/*")):
            if not marker.name.isascii() or not marker.name.isdigit():
                continue
            pid = int(marker.name)
            if pid <= 0 or pid in ignore or not _pid_is_live(pid):
                continue
            found.append({"pid": pid, "path": str(marker)})
    return found


def worktrees(needles: list[str]) -> list[str]:
    found: list[str] = []
    for needle in needles:
        path = Path(needle)
        if not path.exists():
            continue
        cwd = path if path.is_dir() else path.parent
        result = subprocess.run(
            ["git", "-C", str(cwd), "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            continue
        for line in result.stdout.splitlines():
            if line.startswith("worktree "):
                entry = line[len("worktree ") :]
                if entry not in found:
                    found.append(entry)
    return found


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Report who else uses a tree, index, venv or cache."
    )
    parser.add_argument("needles", nargs="+", metavar="NEEDLE")
    parser.add_argument("--home", type=Path, default=None)
    parser.add_argument("--repo", action="append", default=[])
    parser.add_argument("--holders", action="append", default=[])
    parser.add_argument("--ignore-pid", action="append", type=int, default=[])
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_intermixed_args(argv)
    home = args.home if args.home is not None else Path.home()
    needles = list(args.needles)
    ignore = set(args.ignore_pid)

    processes = live_processes(needles, ignore)
    declared = (
        declared_claude(home, needles)
        + declared_codex(home, needles)
        + declared_launchd(home, needles)
        + declared_cron(needles)
        + declared_mcp_json(args.repo, needles)
    )
    declared.sort(key=lambda e: (e["source"], e["scope"], e["name"]))
    held = holders(args.holders, ignore)
    other = worktrees(needles)
    summary = {"live": len(processes), "declared": len(declared), "holders": len(held)}

    if args.json:
        print(
            json.dumps(
                {
                    "needles": needles,
                    "processes": processes,
                    "declared": declared,
                    "holders": held,
                    "worktrees": other,
                    "summary": summary,
                }
            )
        )
    else:
        for row in processes:
            print(f"{row['pid']} {row['command']}")
        for entry in declared:
            print(f"{entry['source']} {entry['scope']} {entry['name']}")
        for holder in held:
            print(f"holder {holder['pid']} {holder['path']}")
        for path in other:
            print(f"worktree {path}")
        print(
            f"READERS needles={len(needles)} live={summary['live']} "
            f"declared={summary['declared']} holders={summary['holders']}"
        )
        print(BLIND_SPOTS)
    return 3 if processes or held else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
