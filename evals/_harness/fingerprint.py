"""Computes content fingerprints for eval runs and built fixtures.

A run's content fingerprint never includes a commit SHA anywhere: it is
composed from tier tree hashes (content hashes of files, from
``deps.tree_hash``), version strings, and a run date. ``deps.tree_hash`` is
the sole tier-hash implementation; this module never reimplements it.

``builder_output_fingerprint`` is a different kind of fingerprint: it
describes a fixture builder's full built output (tracked, untracked and
ignored files alike), not a run, so the commit SHAs inside that built repo's
own history are part of what it hashes. ``deps.tree_hash`` cannot be used for
this purpose since it only sees files git tracks at a ref.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from evals._harness.deps import tree_hash


def compute_fingerprint(
    *,
    direct_paths: list[str],
    injection_paths: list[str],
    plugin_version: str,
    claude_code_version: str,
    run_date: str,
    ref: str = "HEAD",
    repo: Path | None = None,
) -> dict[str, str]:
    """Compose a run's content fingerprint.

    Parameters
    ----------
    direct_paths : list[str]
        The skill's direct-tier deps, as listed in its ``deps`` file.
    injection_paths : list[str]
        The skill's injection-tier deps, as listed in its ``deps`` file.
    plugin_version : str
        The shipping plugin's version.
    claude_code_version : str
        The Claude Code version the run executed under.
    run_date : str
        The run's date, ``YYYY-MM-DD``.
    ref : str
        The git ref to hash the tiers at.
    repo : Path | None
        The git repository to hash against. Defaults to this repository.

    Returns
    -------
    dict[str, str]
        ``{"direct_tier_hash", "injection_tier_hash", "plugin_version",
        "claude_code_version", "run_date"}``. Never a commit SHA.
    """
    return {
        "direct_tier_hash": tree_hash(direct_paths, ref=ref, repo=repo),
        "injection_tier_hash": tree_hash(injection_paths, ref=ref, repo=repo),
        "plugin_version": plugin_version,
        "claude_code_version": claude_code_version,
        "run_date": run_date,
    }


def _iter_files(root: Path):
    for path in root.rglob("*"):
        if path.is_dir():
            continue
        if ".git" in path.relative_to(root).parts:
            continue
        yield path


def _is_own_repo_root(root: Path) -> bool:
    """Return whether *root* is itself a git repository's top level.

    ``git -C root log`` walks up to a parent repository when *root* sits
    inside one but is not itself a repo root, which would leak that parent's
    log into this fixture's fingerprint. Comparing the resolved toplevel to
    *root* catches exactly that case.
    """
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False
    try:
        return Path(result.stdout.strip()).resolve() == root.resolve()
    except OSError:
        return False


def _git_log_all(root: Path) -> str:
    if not _is_own_repo_root(root):
        return ""
    result = subprocess.run(
        ["git", "-C", str(root), "log", "--all", "--format=%H%x00%s"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return ""
    return result.stdout


def builder_output_fingerprint(root: Path) -> str:
    """Fingerprint a fixture builder's full built working tree.

    Hashes every file under *root* — tracked, untracked and ignored alike —
    plus that repository's full commit log, so the fingerprint changes
    whenever the built output changes in any way, including a file such as
    ``.env`` that git would otherwise ignore.

    Parameters
    ----------
    root : Path
        The built fixture's root directory.

    Returns
    -------
    str
        A sha256 hex digest of: the sorted ``path\\0content-sha256`` lines
        for every file under *root* (excluding the contents of ``.git/``),
        joined by ``\\n``; then ``\\n--git-log--\\n``; then the output of
        ``git -C <root> log --all --format=%H%x00%s`` (``""`` when *root* is
        not itself a git repository's top level — including when it sits
        inside one, so the log is never a parent repo's).
    """
    lines = sorted(
        f"{path.relative_to(root).as_posix()}\0{hashlib.sha256(path.read_bytes()).hexdigest()}"
        for path in _iter_files(root)
    )
    body = "\n".join(lines)
    git_log = _git_log_all(root)
    full = f"{body}\n--git-log--\n{git_log}"
    return hashlib.sha256(full.encode("utf-8")).hexdigest()
