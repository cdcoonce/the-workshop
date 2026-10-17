#!/usr/bin/env python3
"""Preflight for a ``/cold-read`` reader: stop at its first command when the read cannot run.

Incident: on 2026-10-10 a cold reader whose scratch directory could not be
created spent 174,751 tokens and about nine minutes on a read that could not
probe, and said so only in its report. A read that cannot do the one thing it
exists for should stop at its first command, at the cost of one tool call. The
reader's first command is this script's ``preflight``, supplied by the
conductor in the dispatch; a later subcommand extends this script to generate
the whole dispatch.

Usage::

    python3 "<engine>/cold_read_dispatch.py" preflight --scratch DIR

``preflight`` creates a uniquely named sentinel file in DIR, writes a value to
it, reads the value back and removes the sentinel, then runs ``git --version``
and ``uv --version``. It prints exactly one line to stdout and nothing to
stderr::

    PREFLIGHT ok scratch=<DIR> git=<version> uv=<version>
    PREFLIGHT failed cause=<scratch-missing|scratch-unwritable|git-missing|uv-missing>

Each version is the first line of that program's ``--version`` output. A
failure names the first failing cause in the order shown: a directory that is
not there is ``scratch-missing``; a sentinel that cannot be created, written,
read back or removed, or that reads back a different value, is
``scratch-unwritable``; a program that cannot be started, times out or exits
non-zero is missing. It deletes nothing but its own sentinel.

Exit codes: 0 ok, 1 failed, 2 usage error (a missing ``--scratch``: argparse
writes its usage message to stderr and ``main`` raises ``SystemExit(2)``).

``git`` and ``uv`` run only through the module-level ``_run_tool`` seam and the
sentinel round trip only through ``_roundtrip_sentinel``, so tests inject
fakes with no process and no filesystem. Stdlib only.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile

SENTINEL_PREFIX = ".cold-read-preflight-"


def _run_tool(argv: list[str], timeout: float = 30) -> tuple[int, str, str] | None:
    """Run *argv*, returning ``(exit_code, stdout, stderr)`` or ``None``.

    Parameters
    ----------
    argv : list[str]
        The program and its arguments (e.g. ``["git", "--version"]``).
    timeout : float
        Seconds to wait before giving up.

    Returns
    -------
    tuple[int, str, str] | None
        The process result, or ``None`` when the program cannot be started
        (``OSError``) or outlives *timeout*.
    """
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.returncode, result.stdout, result.stderr


def _roundtrip_sentinel(directory: str, value: str) -> str:
    """Write *value* to a new sentinel file in *directory*, read it back and remove it.

    The sentinel gets an exclusive, uniquely named file, so an entry already in
    *directory* is never truncated, and it is the only thing removed.

    Parameters
    ----------
    directory : str
        An existing directory.
    value : str
        Text to write.

    Returns
    -------
    str
        The text read back from the sentinel.

    Raises
    ------
    OSError
        On any failure to create, write, read or remove the sentinel.
    """
    descriptor, path = tempfile.mkstemp(prefix=SENTINEL_PREFIX, dir=directory)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(value)
        with open(path, encoding="utf-8", errors="replace", newline="") as handle:
            return handle.read()
    finally:
        os.unlink(path)


def _first_line(text: str) -> str:
    return text.split("\n", 1)[0].rstrip("\r")


def _tool_version(argv: list[str]) -> str | None:
    """The first line of the program's output, or ``None`` when it counts as missing."""
    result = _run_tool(argv)
    if result is None or result[0] != 0:
        return None
    return _first_line(result[1])


def _failed(cause: str) -> int:
    print(f"PREFLIGHT failed cause={cause}")
    return 1


def _preflight(scratch: str) -> int:
    if not os.path.isdir(scratch):
        return _failed("scratch-missing")
    value = os.urandom(8).hex()
    try:
        read_back = _roundtrip_sentinel(scratch, value)
    except OSError:
        return _failed("scratch-unwritable")
    if read_back != value:
        return _failed("scratch-unwritable")
    git = _tool_version(["git", "--version"])
    if git is None:
        return _failed("git-missing")
    uv = _tool_version(["uv", "--version"])
    if uv is None:
        return _failed("uv-missing")
    print(f"PREFLIGHT ok scratch={scratch} git={git} uv={uv}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    preflight = commands.add_parser(
        "preflight",
        help="check the scratch directory, git and uv, and print one result line",
    )
    preflight.add_argument(
        "--scratch",
        required=True,
        metavar="DIR",
        help="the read's scratch directory",
    )
    args = parser.parse_args(argv)
    return _preflight(args.scratch)


if __name__ == "__main__":
    raise SystemExit(main())
