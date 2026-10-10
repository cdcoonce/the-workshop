"""The conductor's fixture copy: copies ``fixture/`` without the case's private files.

A case's ``fixture/`` may hold a file no dispatched agent may see (A2's answer
key, ``defects.json``). The case lists such files in an optional top-level
``fixture_private`` array in ``case.toml`` (POSIX paths relative to
``fixture/``; a path may name a file or a directory). The key is not part of
``calibration.compute_input_hash``, so declaring it never stales a record, and
the file stays where it is, so ``fixture_fingerprint`` is unchanged.

``copy_fixture`` omits every private path; ``find_private_leaks`` is the loud
check over a finished ``<dest>``. Both fail closed: a malformed, stale or
mis-spelled declaration raises ``FixtureCopyError`` rather than protecting
nothing.

``copy_fixture`` also refuses:

- a builder case (a ``builder`` key or a case-local ``build_fixture.py``; run
  ``python <builder> <dest>`` instead);
- a ``dest`` inside the case's own ``fixture/``;
- a ``fixture/`` that differs from git's tracked blobs at HEAD (any untracked,
  modified, staged or ignored-but-present path under it). ``fixture_fingerprint``
  hashes HEAD blobs, so a dirty work tree would be dispatched under a
  fingerprint that does not describe it. Ignored files are included in the
  refusal on purpose: they are copied but never hashed. Outside a git work tree
  there is nothing to compare against, and the copy proceeds (an explicit
  branch: ``fixture_dirty_paths`` returns ``None``).

``find_private_leaks`` flags, under ``dest`` at any depth: a path matching a
private entry, a file with a private file's basename, ``acceptance.md`` or
anything under ``ab_raws`` (names compared casefolded and NFC-normalized), any
regular file whose bytes equal a private file's (sha256, read through
symlinks), and any symlink that resolves into the case's ``fixture/``.

Stated limit: content is matched byte for byte. The contents of an archive
(zip, tar) and a pasted excerpt or reworded summary of a private file are out
of scope; nothing here can see them.

Command line (the two invocations ``.claude/skills/eval-suite/SKILL.md`` step 1
tells the conductor to run, from the repo root)::

    python -m evals._harness.fixture_copy <case_dir> <dest>
    python -m evals._harness.fixture_copy --check <case_dir> <dest>

Exit codes: 0 clean, 1 ``--check`` found a leak, 2 on any error.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tomllib
import unicodedata
from pathlib import Path, PurePosixPath

# Never fixture material: leaks wherever they appear under a dest.
_ALWAYS_PRIVATE_NAMES = ("acceptance.md",)
_ALWAYS_PRIVATE_DIRS = ("ab_raws",)


class FixtureCopyError(ValueError):
    """A fixture copy or its private declaration is unusable."""


def _case_label(case_dir: Path) -> str:
    return case_dir.name


def _norm(text: str) -> str:
    """Casefolded, NFC-normalized text: how names are compared (APFS folds both)."""
    return unicodedata.normalize("NFC", text).casefold()


def _load_case_toml(case_dir: Path) -> dict:
    path = case_dir / "case.toml"
    if not path.is_file():
        raise FixtureCopyError(f"case {_case_label(case_dir)}: {case_dir} is not a case (no case.toml)")
    return tomllib.loads(path.read_text(encoding="utf-8"))


def has_builder(case_dir: Path) -> bool:
    """Whether the case builds its fixture: a ``builder`` key or a case-local ``build_fixture.py``.

    The same decision ``calibration._resolve_builder`` makes (a test pins the
    two together on every committed case); it lives here so this module and
    the answer-key guard need only the standard library.
    """
    case_dir = Path(case_dir)
    return bool(_load_case_toml(case_dir).get("builder")) or (case_dir / "build_fixture.py").exists()


def _on_disk_path(case_dir: Path, fixture: Path, entry: str) -> None:
    """Require *entry*'s exact spelling on disk, component by component."""
    label = _case_label(case_dir)
    current = fixture
    for part in PurePosixPath(entry).parts:
        names = os.listdir(current) if current.is_dir() else []
        if part in names:
            current = current / part
            continue
        lookalikes = [n for n in names if _norm(n) == _norm(part)]
        if lookalikes:
            raise FixtureCopyError(
                f"case {label}: fixture_private entry {entry!r} is spelled {part!r} but on disk it is "
                f"{lookalikes[0]!r}; a case- or normalization-insensitive filesystem would validate it and "
                "the copy would still carry the file"
            )
        raise FixtureCopyError(
            f"case {label}: fixture_private entry {entry!r} does not exist under fixture/ "
            "(a stale declaration protects nothing)"
        )


def private_fixture_paths(case_dir: Path) -> tuple[str, ...]:
    """Return the case's validated ``fixture_private`` entries (empty if undeclared).

    Raises
    ------
    FixtureCopyError
        If the directory is not a case, the key is not a list of non-empty
        strings, an entry is absolute, contains ``..`` or a backslash, names
        ``fixture/`` itself, or escapes ``fixture/`` (including through a
        symlink), an entry does not exist, or an entry's spelling differs
        from the on-disk spelling in case or Unicode normalization.
    """
    case_dir = Path(case_dir)
    label = _case_label(case_dir)
    case_toml = _load_case_toml(case_dir)
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
        _on_disk_path(case_dir, fixture, posix.as_posix())
        resolved = (fixture / posix.as_posix()).resolve()
        if resolved == fixture_real or fixture_real not in resolved.parents:
            raise FixtureCopyError(f"case {label}: fixture_private entry {entry!r} escapes fixture/")
        entries.append(posix.as_posix())
    return tuple(entries)


def _is_private(rel: str, entries: tuple[str, ...]) -> bool:
    rel_n = _norm(rel)
    return any(rel_n == _norm(e) or rel_n.startswith(_norm(e) + "/") for e in entries)


def fixture_dirty_paths(case_dir: Path) -> list[str] | None:
    """Paths under the case's ``fixture/`` that differ from git's HEAD, or ``None`` outside git.

    Runs ``git status --porcelain --untracked-files=all --ignored`` scoped to
    ``fixture/`` (no shell). ``None`` means the case is not in a git work tree
    (or git is unavailable), so there is nothing to compare against.
    """
    case_dir = Path(case_dir)
    try:
        inside = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"], cwd=case_dir, capture_output=True, text=True, check=False
        )
    except OSError:
        return None
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return None
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all", "--ignored", "--", "fixture"],
        cwd=case_dir, capture_output=True, text=True, check=False,
    )
    if status.returncode != 0:
        raise FixtureCopyError(f"case {_case_label(case_dir)}: git status failed: {status.stderr.strip()}")
    return [line[3:] for line in status.stdout.splitlines() if line.strip()]


def copy_fixture(case_dir: Path, dest: Path) -> list[str]:
    """Copy ``<case_dir>/fixture/`` into the not-yet-existing *dest*, omitting private paths.

    Returns
    -------
    list[str]
        The sorted relative paths copied.

    Raises
    ------
    FixtureCopyError
        If the directory is not a case, the case builds its fixture, there is
        no ``fixture/``, the declaration is bad, *dest* exists or lies inside
        ``fixture/``, ``fixture/`` differs from git's HEAD, or the fixture
        holds a symlink. Nothing is written in any of those cases.
    """
    case_dir, dest = Path(case_dir), Path(dest)
    label = _case_label(case_dir)
    _load_case_toml(case_dir)
    if has_builder(case_dir):
        raise FixtureCopyError(
            f"case {label}: builds its fixture; run `python <builder> <dest>` instead of copying fixture/"
        )
    fixture = case_dir / "fixture"
    if not fixture.is_dir():
        raise FixtureCopyError(f"case {label}: has no fixture/ directory to copy")
    entries = private_fixture_paths(case_dir)
    if os.path.lexists(dest):
        raise FixtureCopyError(f"case {label}: dest {dest} already exists; it must not")
    fixture_real = fixture.resolve()
    dest_real = dest.resolve()
    if dest_real == fixture_real or fixture_real in dest_real.parents:
        raise FixtureCopyError(f"case {label}: dest {dest} is inside the case's fixture/")
    dirty = fixture_dirty_paths(case_dir)
    if dirty:
        raise FixtureCopyError(
            f"case {label}: fixture/ differs from git's HEAD (fixture_fingerprint hashes HEAD, not the work "
            f"tree); commit or remove: {', '.join(dirty)}"
        )

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


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as handle:  # follows symlinks on purpose
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def find_private_leaks(case_dir: Path, dest: Path) -> list[str]:
    """Return the paths under *dest* that are private, at any depth.

    See the module docstring for what counts and the stated limit.

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
    fixture_real = fixture.resolve()

    private_files: list[Path] = []
    for entry in entries:
        target = fixture / entry
        if target.is_dir():
            private_files.extend(p for p in target.rglob("*") if p.is_file())
        else:
            private_files.append(target)
    private_basenames = {_norm(p.name) for p in private_files}
    private_reals = {p.resolve() for p in private_files}
    private_digests = {_digest(p) for p in private_files if p.stat().st_size > 0}

    leaks: list[str] = []
    for root, dirs, files in os.walk(dest, followlinks=False):
        for name in [*dirs, *files]:
            path = Path(root) / name
            rel = path.relative_to(dest).as_posix()
            padded = "/" + _norm(rel) + "/"
            by_path = any("/" + _norm(entry) + "/" in padded for entry in entries)
            always = _norm(name) in _ALWAYS_PRIVATE_NAMES or any(
                "/" + d + "/" in padded for d in _ALWAYS_PRIVATE_DIRS
            )
            if path.is_symlink():
                target = path.resolve()
                if target in private_reals or target == fixture_real or fixture_real in target.parents:
                    leaks.append(rel)
                    continue
            if name in files:
                by_name = _norm(name) in private_basenames
                by_content = False
                if private_digests and path.is_file():
                    try:
                        by_content = _digest(path) in private_digests
                    except OSError:
                        by_content = False
                if by_path or by_name or always or by_content:
                    leaks.append(rel)
            elif (by_path or always) and not any(path.rglob("*")):
                leaks.append(rel)  # an empty private directory still names the leak
    return sorted(set(leaks))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evals._harness.fixture_copy")
    parser.add_argument("--check", action="store_true", help="exit 1 if <dest> holds a private file")
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
