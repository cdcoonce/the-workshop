#!/usr/bin/env python3
"""Deterministic checks run before a GitLab merge request is opened.

``sweep`` finds identifiers the diff between ``--base`` and ``--head`` renamed
and reports every reference to the old name that survives at head. With
``--description``, the waivers in that MR description's sweep block
(``- waive TOKEN path: reason``) excuse their hits, and a malformed waiver line
blocks; ``--update`` rewrites the block in place. Exit codes: 0 clean,
1 unwaived references or malformed waivers, 2 setup error.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from description_blocks import (  # noqa: E402
    BlockError,
    find_block,
    parse_waivers,
    replace_block,
    waiver_lines,
)
from reference_sweep import Hit, sweep  # noqa: E402
from rename_detector import Rename, detect_renames  # noqa: E402

CLEAN = 0
HITS = 1
SETUP_ERROR = 2


def _git(repo: Path, *args: str) -> str:
    # Bytes, decoded by hand: `text=True` applies universal newlines, turning
    # a `\r` inside a diffed line into a line break that splits it in two.
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True)
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(stderr or f"git {' '.join(args)} failed")
    return result.stdout.decode("utf-8", "replace")


def _read_description(path: Path) -> str:
    # Bytes in, decoded by hand, so a CRLF description is read as written.
    return path.read_bytes().decode("utf-8", "surrogateescape")


def _write_description(path: Path, text: str) -> None:
    """Replace ``path`` with ``text`` all at once.

    Written to a sibling temp file, then renamed over the original: writing in
    place truncates first, so a full disk or a kill mid-write would leave the
    author's description empty or cut short.
    """
    target = path.resolve()
    fd, temp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(text.encode("utf-8", "surrogateescape"))
        shutil.copymode(target, temp)
        os.replace(temp, target)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


def render_body(renames: list[Rename], blocking: list[Hit], waivers: list[str]) -> str:
    """The sweep block's body: what was renamed, what still blocks, and the
    author's waiver lines exactly as written."""
    sections = []
    if renames:
        sections.append(
            "Renamed on this branch:\n\n"
            + "".join(f"- `{r.old}` -> `{r.new}` in `{r.path}`\n" for r in renames)
        )
    else:
        sections.append("No renamed identifiers on this branch.\n")
    if blocking:
        sections.append(
            "Unwaived references (fix each, or waive it below as `- waive TOKEN path: reason`):\n\n"
            + "".join(f"- [ ] `{h.path}:{h.line}` `{h.rename.old}`\n" for h in blocking)
        )
    if waivers:
        sections.append("Waivers:\n\n" + "".join(f"{line}\n" for line in waivers))
    return "**mr-preflight sweep**\n\n" + "\n".join(sections)


def run_sweep(base: str, head: str, description: Path | None = None, update: bool = False) -> int:
    waived: dict[tuple[str, str], str] = {}
    malformed: list[str] = []
    body = ""
    if description is not None:
        try:
            text = _read_description(description)
            block = find_block(text, "sweep")
        except (OSError, BlockError) as error:
            print(f"mr-preflight: {error}", file=sys.stderr)
            return SETUP_ERROR
        body = text[block.start : block.end] if block else ""
        waivers, malformed = parse_waivers(body)
        waived = {(w.token, w.path): w.reason for w in waivers}

    try:
        # `git grep <tree>` searches only the cwd's subtree, so run from the
        # top: a leftover at the repo root counts wherever this was invoked.
        repo = Path(_git(Path.cwd(), "rev-parse", "--show-toplevel").strip())
        diff_text = _git(repo, "diff", "-U0", "--no-color", "--no-ext-diff", base, head)
        renames = detect_renames(diff_text)
        hits = sweep(repo, head, renames)
    except RuntimeError as error:
        print(f"mr-preflight: {error}", file=sys.stderr)
        return SETUP_ERROR

    blocking = []
    for hit in hits:
        reason = waived.get((hit.rename.old, hit.path))
        if reason is None:
            blocking.append(hit)
        else:
            print(f"waived: {hit.path}:{hit.line}: {hit.rename.old}: {reason}")
    for hit in blocking:
        print(f"{hit.path}:{hit.line}: {hit.rename.old} (renamed to {hit.rename.new} in {hit.rename.path})")
    for line in malformed:
        print(f"malformed waiver: {line}")
    # A branch that renamed nothing gains no block: its MR goes out exactly as
    # written. An existing block is still rewritten, so a stale one copied from
    # an earlier run cannot keep claiming hits that are gone.
    if update and description is not None and (renames or block is not None):
        rendered = replace_block(text, "sweep", render_body(renames, blocking, waiver_lines(body)))
        try:
            _write_description(description, rendered)
        except OSError as error:
            # stdout is block-buffered into a pipe and stderr is not, so flush
            # the hits first or a merged stream shows the error above them.
            sys.stdout.flush()
            print(f"mr-preflight: could not update {description}: {error}", file=sys.stderr)
            return SETUP_ERROR
    if blocking:
        print(f"mr-preflight: {len(blocking)} surviving reference(s) to renamed identifiers.")
    if malformed:
        print(f"mr-preflight: {len(malformed)} malformed waiver line(s); the form is `- waive TOKEN path: reason`.")
    if blocking or malformed:
        return HITS
    return CLEAN


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    sweep_cmd = commands.add_parser("sweep", help="report surviving references to renamed identifiers")
    sweep_cmd.add_argument("--base", required=True, help="commit-ish the diff starts from")
    sweep_cmd.add_argument("--head", default="HEAD", help="commit-ish whose tree is searched")
    sweep_cmd.add_argument(
        "--description", type=Path, help="MR description whose sweep block holds the waivers"
    )
    sweep_cmd.add_argument(
        "--update",
        action="store_true",
        help="rewrite the description's sweep block in place (needs --description)",
    )
    args = parser.parse_args()
    if args.update and args.description is None:
        parser.error("--update needs --description")
    return run_sweep(args.base, args.head, args.description, args.update)


if __name__ == "__main__":
    sys.exit(main())
