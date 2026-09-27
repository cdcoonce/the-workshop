"""Parses a skill's eval ``deps`` file and computes tier hashes.

A skill's ``evals/<skill>/deps`` file is TOML with two keys, ``direct`` and
``injection``, each a list of repo-relative paths. A listed path that names a
directory expands to every file tracked in the git repository under it.

This module is the sole tier-hash implementation in the repo: any other
module that needs a tier hash, or a fixture-tree hash, imports
``tree_hash`` from here rather than reimplementing it.

Public contract
----------------
``parse_deps(text) -> dict[str, list[str]]``
    Parses a ``deps`` file's TOML text into ``{"direct": [...], "injection":
    [...]}``.

``expand_paths(paths, ref="HEAD", repo=None) -> list[str]``
    Expands every directory in ``paths`` to the files git tracks under it at
    ``ref``, in the git repository ``repo`` (default: this repository).

``tree_hash(paths, ref="HEAD", repo=None) -> str``
    A sha256 hex digest over the sorted set of ``path\\0blob-sha`` lines, one
    per file resolved from ``paths`` by ``expand_paths``, where ``blob-sha``
    is that file's git blob SHA at ``ref`` — a content hash, never a commit
    SHA.
"""

from __future__ import annotations

import hashlib
import subprocess
import tomllib
from pathlib import Path

# evals/_harness/deps.py -> evals/_harness -> evals -> repo root.
_THIS_REPO_ROOT = Path(__file__).resolve().parents[2]


def parse_deps(text: str) -> dict[str, list[str]]:
    """Parse a ``deps`` file's TOML text.

    Parameters
    ----------
    text : str
        The ``deps`` file's contents.

    Returns
    -------
    dict[str, list[str]]
        ``{"direct": [...], "injection": [...]}``, each a list of
        repo-relative paths as declared in the file.
    """
    data = tomllib.loads(text)
    return {
        "direct": list(data.get("direct", [])),
        "injection": list(data.get("injection", [])),
    }


def _git_ls_tree(ref: str, repo: Path) -> list[tuple[str, str]]:
    """Return ``(path, blob_sha)`` for every file tracked at *ref* in *repo*."""
    result = subprocess.run(
        ["git", "-C", str(repo), "ls-tree", "-r", ref],
        capture_output=True,
        text=True,
        check=True,
    )
    entries: list[tuple[str, str]] = []
    for line in result.stdout.splitlines():
        if not line:
            continue
        meta, path = line.split("\t", 1)
        blob_sha = meta.split()[2]
        entries.append((path, blob_sha))
    return entries


def expand_paths(paths: list[str], ref: str = "HEAD", repo: Path | None = None) -> list[str]:
    """Expand every directory in *paths* to the files tracked under it at *ref*.

    Parameters
    ----------
    paths : list[str]
        Repo-relative paths, each either a tracked file or a directory.
    ref : str
        The git ref to resolve tracked files at.
    repo : Path | None
        The git repository to resolve against. Defaults to this repository.

    Returns
    -------
    list[str]
        The sorted, deduplicated set of tracked file paths resolved from
        *paths*: a file path is kept as-is, a directory path is replaced by
        every tracked file under it.
    """
    repo_dir = repo if repo is not None else _THIS_REPO_ROOT
    tracked_paths = {path for path, _ in _git_ls_tree(ref, repo_dir)}

    resolved: set[str] = set()
    for raw_path in paths:
        normalized = raw_path.rstrip("/")
        if normalized in tracked_paths:
            resolved.add(normalized)
            continue
        prefix = normalized + "/"
        resolved.update(path for path in tracked_paths if path.startswith(prefix))

    return sorted(resolved)


def tree_hash(paths: list[str], ref: str = "HEAD", repo: Path | None = None) -> str:
    """Compute a tier hash over the files resolved from *paths* at *ref*.

    Parameters
    ----------
    paths : list[str]
        Repo-relative paths, each either a tracked file or a directory.
    ref : str
        The git ref to hash at.
    repo : Path | None
        The git repository to hash against. Defaults to this repository.

    Returns
    -------
    str
        A sha256 hex digest over the sorted set of ``path\\0blob-sha``
        lines, one per resolved file.
    """
    repo_dir = repo if repo is not None else _THIS_REPO_ROOT
    resolved = expand_paths(paths, ref=ref, repo=repo_dir)
    blob_shas = dict(_git_ls_tree(ref, repo_dir))

    lines = sorted(f"{path}\0{blob_shas[path]}" for path in resolved)
    digest = hashlib.sha256("\n".join(lines).encode("utf-8"))
    return digest.hexdigest()
