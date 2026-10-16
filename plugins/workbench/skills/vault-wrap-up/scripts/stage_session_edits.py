"""Stage only this session's blocks of a file another session also left dirty.

Vault sessions share one checkout, and /wrap-up sends each of them to the same
anchors. When a file this session edited also holds another session's
uncommitted edits, ``git add <path>`` commits both under this session's
wrap-up (the-vault 857eba8d, 2026-10-16, avoided it only with a hand-rolled
``hash-object``/``update-index`` script). This script is that staging step,
made safe:

    stage_session_edits.py --path "brain/Key Decisions.md" --list --json
    stage_session_edits.py --path "brain/Key Decisions.md" --blocks 1a2b3c4d --json

``--list`` shows the file's change blocks against HEAD (``edit_blocks``: one
per entry, paragraph, list item or replaced line), each with a content-derived
id, its ``## `` section and its first line. ``--blocks`` stages HEAD's content
with only those blocks applied: the blob is written with ``git hash-object -w``
and placed with ``git update-index --cacheinfo``. The working tree is never
written, and no other path's index entry changes.

It refuses, changing nothing, when an id is not a current block, or when the
path's index entry already differs from HEAD: those staged bytes may be
another session's in-progress staging, and overwriting them would drop it.

Exit codes: 0 listed or staged; 1 refused; 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from edit_blocks import apply_blocks, block_section, split_blocks


class Refused(RuntimeError):
    """Staging would be unsafe; nothing was changed."""


def _git(vault: Path, *args: str, stdin: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", "-C", str(vault), *args], input=stdin, capture_output=True, timeout=60)


def _git_ok(vault: Path, *args: str, stdin: bytes | None = None) -> bytes:
    proc = _git(vault, *args, stdin=stdin)
    if proc.returncode != 0:
        raise Refused(f"git {' '.join(args)} failed: {proc.stderr.decode(errors='replace').strip()}")
    return proc.stdout


def _lines(data: bytes) -> list[str]:
    return data.decode("utf-8", "surrogateescape").splitlines(keepends=True)


def _head_entry(vault: Path, path: str) -> tuple[str, bytes] | None:
    """(mode, content) of *path* at HEAD, or None when HEAD has no such file."""
    out = _git(vault, "ls-tree", "-z", "HEAD", "--", path)
    if out.returncode != 0 or not out.stdout:
        return None
    meta = out.stdout.split(b"\t", 1)[0].decode()
    mode, _kind, sha = meta.split()
    return mode, _git_ok(vault, "cat-file", "blob", sha)


def _index_differs_from_head(vault: Path, path: str) -> bool:
    return _git(vault, "diff", "--cached", "--quiet", "HEAD", "--", path).returncode != 0


def _blocks(vault: Path, path: str) -> tuple[str, list[str], list[str]]:
    target = vault / path
    if not target.is_file():
        raise Refused(f"{path} is not a file in the working tree")
    head = _head_entry(vault, path)
    mode, old_bytes = head if head is not None else ("100644", b"")
    return mode, _lines(old_bytes), _lines(target.read_bytes())


def list_blocks(vault: Path, path: str) -> dict:
    _mode, old, new = _blocks(vault, path)
    blocks = split_blocks(old, new)
    return {
        "action": "listed",
        "path": path,
        "blocks": [
            {"id": b.id, "kind": b.kind, "section": block_section(b, old, new), "first_line": b.first_line}
            for b in blocks
        ],
    }


def stage(vault: Path, path: str, selected: list[str]) -> dict:
    mode, old, new = _blocks(vault, path)
    blocks = split_blocks(old, new)
    try:
        staged_lines = apply_blocks(old, blocks, selected)
    except ValueError as exc:
        raise Refused(str(exc)) from exc
    if _index_differs_from_head(vault, path):
        raise Refused(
            f"{path} already has staged changes that differ from HEAD; they may be another "
            "session's in-progress staging, so nothing was changed"
        )
    content = "".join(staged_lines).encode("utf-8", "surrogateescape")
    sha = _git_ok(vault, "hash-object", "-w", "--stdin", stdin=content).decode().strip()
    _git_ok(vault, "update-index", "--add", "--cacheinfo", f"{mode},{sha},{path}")
    left = [b.id for b in blocks if b.id not in set(selected)]
    return {"action": "staged", "path": path, "staged": list(selected), "left_unstaged": left}


def _relpath(vault: Path, raw: str) -> str:
    candidate = Path(raw)
    if candidate.is_absolute():
        return candidate.resolve().relative_to(vault.resolve()).as_posix()
    return candidate.as_posix()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--vault", default=".", help="Vault (git) root; default: cwd")
    parser.add_argument("--path", required=True, help="File to list or stage, relative to the vault root")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--list", action="store_true", help="List the file's change blocks against HEAD")
    mode.add_argument("--blocks", help="Comma-separated block ids to stage (from --list)")
    parser.add_argument("--json", action="store_true", help="Machine-readable report")
    args = parser.parse_args(argv)

    vault = Path(args.vault)
    path = _relpath(vault, args.path)
    try:
        if args.list:
            report = list_blocks(vault, path)
        else:
            selected = [s.strip() for s in args.blocks.split(",") if s.strip()]
            if not selected:
                parser.error("--blocks needs at least one id")
            report = stage(vault, path, selected)
        code = 0
    except Refused as exc:
        report = {"action": "refused", "path": path, "reason": str(exc)}
        code = 1

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    elif report["action"] == "listed":
        for b in report["blocks"]:
            print(f"{b['id']}  {b['kind']:<7}  [{b['section'] or '(preamble)'}]  {b['first_line']}")
    else:
        print(f"{report['action']}: {report.get('reason') or ', '.join(report['staged'])}")
    return code


if __name__ == "__main__":
    sys.exit(main())
