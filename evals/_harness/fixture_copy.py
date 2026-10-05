"""The conductor's fixture copy: copies ``fixture/`` without the case's private files.

A case's ``fixture/`` may hold a file no dispatched agent may see (A2's answer
key, ``defects.json``). The case lists such files in an optional top-level
``fixture_private`` array in ``case.toml`` (POSIX paths relative to
``fixture/``; a path may name a file or a directory). The key is not part of
``calibration.compute_input_hash``, so declaring it never stales a record, and
the file stays where it is, so ``fixture_fingerprint`` is unchanged.

``copy_fixture`` omits every private path; ``find_private_leaks`` is the loud
check over a finished ``<dest>``. Both fail closed: a malformed or stale
declaration raises ``FixtureCopyError`` rather than protecting nothing.

Command line (the two invocations ``.claude/skills/eval-suite/SKILL.md`` step 1
tells the conductor to run)::

    python -m evals._harness.fixture_copy <case_dir> <dest>
    python -m evals._harness.fixture_copy --check <case_dir> <dest>
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tomllib
from pathlib import Path, PurePosixPath

# Never fixture material: leaks wherever they appear under a dest.
_ALWAYS_PRIVATE_NAMES = ("acceptance.md",)
_ALWAYS_PRIVATE_DIRS = ("ab_raws",)


class FixtureCopyError(ValueError):
    """A fixture copy or its private declaration is unusable."""


def _case_label(case_dir: Path) -> str:
    return case_dir.name


def private_fixture_paths(case_dir: Path) -> tuple[str, ...]:
    """Return the case's validated ``fixture_private`` entries (empty if undeclared).

    Raises
    ------
    FixtureCopyError
        If the key is not a list of non-empty strings, an entry is absolute,
        contains ``..``, names ``fixture/`` itself, or escapes ``fixture/``
        (including through a symlink), or an entry does not exist.
    """
    case_dir = Path(case_dir)
    label = _case_label(case_dir)
    case_toml = tomllib.loads((case_dir / "case.toml").read_text(encoding="utf-8"))
    if "fixture_private" not in case_toml:
        return ()
    declared = case_toml["fixture_private"]
    if not isinstance(declared, list) or not all(isinstance(e, str) and e.strip() for e in declared):
        raise FixtureCopyError(
            f"case {label}: fixture_private must be a list of non-empty strings, got {declared!r}"
        )
    fixture = case_dir / "fixture"
    fixture_real = fixture.resolve()
    entries: list[str] = []
    for entry in declared:
        posix = PurePosixPath(entry)
        if posix.is_absolute() or ".." in posix.parts or "\\" in entry:
            raise FixtureCopyError(
                f"case {label}: fixture_private entry {entry!r} must be a relative POSIX path inside fixture/"
            )
        if not posix.parts or posix == PurePosixPath("."):
            raise FixtureCopyError(f"case {label}: fixture_private entry {entry!r} names fixture/ itself")
        target = fixture / posix.as_posix()
        if not os.path.lexists(target):
            raise FixtureCopyError(
                f"case {label}: fixture_private entry {entry!r} does not exist under fixture/ "
                "(a stale declaration protects nothing)"
            )
        resolved = target.resolve()
        if resolved == fixture_real or fixture_real not in resolved.parents:
            raise FixtureCopyError(f"case {label}: fixture_private entry {entry!r} escapes fixture/")
        entries.append(posix.as_posix())
    return tuple(entries)


def _is_private(rel: str, entries: tuple[str, ...]) -> bool:
    return any(rel == entry or rel.startswith(entry + "/") for entry in entries)


def copy_fixture(case_dir: Path, dest: Path) -> list[str]:
    """Copy ``<case_dir>/fixture/`` into the not-yet-existing *dest*, omitting private paths.

    Returns
    -------
    list[str]
        The sorted relative paths copied.

    Raises
    ------
    FixtureCopyError
        If the case has no ``fixture/``, *dest* already exists, the
        declaration is bad, or the fixture holds a symlink. Nothing is
        written in any of those cases.
    """
    case_dir, dest = Path(case_dir), Path(dest)
    label = _case_label(case_dir)
    fixture = case_dir / "fixture"
    if not fixture.is_dir():
        raise FixtureCopyError(f"case {label}: has no fixture/ directory to copy")
    entries = private_fixture_paths(case_dir)
    if os.path.lexists(dest):
        raise FixtureCopyError(f"case {label}: dest {dest} already exists; it must not")

    to_copy: list[str] = []
    for root, dirs, files in os.walk(fixture, followlinks=False):
        for name in [*dirs, *files]:
            path = Path(root) / name
            if path.is_symlink():
                raise FixtureCopyError(
                    f"case {label}: fixture holds a symlink {path.relative_to(fixture).as_posix()!r}; "
                    "a copy never follows one"
                )
        for name in files:
            rel = (Path(root) / name).relative_to(fixture).as_posix()
            if not _is_private(rel, entries):
                to_copy.append(rel)
    to_copy.sort()

    dest.mkdir(parents=True)
    for rel in to_copy:
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(fixture / rel, target)
    return to_copy


def find_private_leaks(case_dir: Path, dest: Path) -> list[str]:
    """Return the paths under *dest* that are private, at any depth.

    A path under *dest* leaks if it matches a private entry by relative path
    (at the top or beneath any prefix directory), if its basename is that of a
    file the case marks private, or if it is an ``acceptance.md`` or sits
    under an ``ab_raws`` directory.

    Raises
    ------
    FixtureCopyError
        If *dest* does not exist (a missing dest must not read as clean) or
        the declaration is bad.
    """
    case_dir, dest = Path(case_dir), Path(dest)
    if not dest.is_dir():
        raise FixtureCopyError(f"case {_case_label(case_dir)}: dest {dest} is not a directory")
    entries = private_fixture_paths(case_dir)
    fixture = case_dir / "fixture"
    private_basenames: set[str] = set()
    for entry in entries:
        target = fixture / entry
        if target.is_dir():
            private_basenames.update(p.name for p in target.rglob("*") if not p.is_dir())
        else:
            private_basenames.add(target.name)

    leaks: list[str] = []
    for root, dirs, files in os.walk(dest, followlinks=False):
        for name in [*dirs, *files]:
            rel = (Path(root) / name).relative_to(dest).as_posix()
            padded = "/" + rel + "/"
            by_path = any("/" + entry + "/" in padded for entry in entries)
            by_name = name in private_basenames and name in files
            always = name in _ALWAYS_PRIVATE_NAMES or any(
                "/" + d + "/" in padded for d in _ALWAYS_PRIVATE_DIRS
            )
            if (by_path or by_name or always) and name in files:
                leaks.append(rel)
            elif (by_path or always) and name in dirs and not any(
                (Path(root) / name).rglob("*")
            ):
                leaks.append(rel)  # an empty private directory still names the leak
    return sorted(set(leaks))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evals._harness.fixture_copy")
    parser.add_argument("--check", action="store_true", help="fail if <dest> holds a private file")
    parser.add_argument("case_dir", type=Path)
    parser.add_argument("dest", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.check:
            leaks = find_private_leaks(args.case_dir, args.dest)
            for leak in leaks:
                print(f"LEAK {leak}")
            return 1 if leaks else 0
        for rel in copy_fixture(args.case_dir, args.dest):
            print(rel)
        return 0
    except FixtureCopyError as exc:
        print(f"fixture_copy: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
