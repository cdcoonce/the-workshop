"""Tests for evals._harness.deps — deps-file parsing and tier hashing."""

from __future__ import annotations

import subprocess
from pathlib import Path

from evals._harness.deps import expand_paths, parse_deps, tree_hash


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "-c", "user.email=test@example.com", "-c", "user.name=Test", "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=test@example.com", "-c", "user.name=Test", "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _write(repo: Path, rel_path: str, content: str) -> None:
    path = repo / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_parse_deps_reads_direct_and_injection_lists():
    text = """
    direct = ["skills/foo/SKILL.md", "skills/foo/scripts"]
    injection = ["fixtures/injected.md"]
    """
    deps = parse_deps(text)
    assert deps == {
        "direct": ["skills/foo/SKILL.md", "skills/foo/scripts"],
        "injection": ["fixtures/injected.md"],
    }


def test_expand_paths_expands_directory_to_tracked_files(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "pkg/a.py", "a")
    _write(repo, "pkg/sub/b.py", "b")
    _write(repo, "top.py", "top")
    _commit(repo, "initial")

    resolved = expand_paths(["pkg", "top.py"], ref="HEAD", repo=repo)

    assert resolved == sorted(["pkg/a.py", "pkg/sub/b.py", "top.py"])


def test_tree_hash_stable_across_reruns(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "pkg/a.py", "a")
    _commit(repo, "initial")

    first = tree_hash(["pkg"], ref="HEAD", repo=repo)
    second = tree_hash(["pkg"], ref="HEAD", repo=repo)

    assert first == second
    assert isinstance(first, str)
    assert len(first) == 64


def test_tree_hash_differs_at_older_ref_after_file_changes(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "pkg/a.py", "original")
    old_sha = _commit(repo, "initial")

    _write(repo, "pkg/a.py", "changed")
    _commit(repo, "update")

    old_hash = tree_hash(["pkg"], ref=old_sha, repo=repo)
    new_hash = tree_hash(["pkg"], ref="HEAD", repo=repo)

    assert old_hash != new_hash
    # Re-hashing the old ref again must reproduce the same value.
    assert tree_hash(["pkg"], ref=old_sha, repo=repo) == old_hash


def test_tree_hash_hashes_a_separate_temporary_repo(tmp_path):
    repo_a = tmp_path / "repo_a"
    repo_b = tmp_path / "repo_b"
    _init_repo(repo_a)
    _write(repo_a, "pkg/a.py", "a-content")
    _commit(repo_a, "initial")

    _init_repo(repo_b)
    _write(repo_b, "pkg/a.py", "b-content")
    _commit(repo_b, "initial")

    hash_a = tree_hash(["pkg"], ref="HEAD", repo=repo_a)
    hash_b = tree_hash(["pkg"], ref="HEAD", repo=repo_b)

    assert hash_a != hash_b
