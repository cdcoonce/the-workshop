"""Tests for evals._harness.fingerprint — run and builder-output fingerprints."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from evals._harness.deps import tree_hash
from evals._harness.fingerprint import builder_output_fingerprint, compute_fingerprint

_FIXED_GIT_ENV = {
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_AUTHOR_DATE": "2020-01-01T00:00:00+00:00",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
    "GIT_COMMITTER_DATE": "2020-01-01T00:00:00+00:00",
}


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
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")


def _commit_all(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    env = {**os.environ, **_FIXED_GIT_ENV}
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "-m", message],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )


def _write(repo: Path, rel_path: str, content: str) -> None:
    path = repo / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_builder_output_fingerprint_equal_for_identical_repos(tmp_path):
    repo_a = tmp_path / "a"
    repo_b = tmp_path / "b"
    for repo in (repo_a, repo_b):
        _init_repo(repo)
        _write(repo, "src/main.py", "print('hi')\n")
        _write(repo, ".env", "SECRET=1\n")
        _commit_all(repo, "initial commit")

    assert builder_output_fingerprint(repo_a) == builder_output_fingerprint(repo_b)


def test_builder_output_fingerprint_changes_with_untracked_env_file(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "main.py", "a")
    _commit_all(repo, "initial")
    before = builder_output_fingerprint(repo)

    _write(repo, ".env", "SECRET=1\n")
    after = builder_output_fingerprint(repo)

    assert before != after


def test_builder_output_fingerprint_changes_with_gitignored_file(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "main.py", "a")
    _write(repo, ".gitignore", "ignored.txt\n")
    _commit_all(repo, "initial")
    before = builder_output_fingerprint(repo)

    _write(repo, "ignored.txt", "secret data")
    after = builder_output_fingerprint(repo)

    assert before != after


def test_builder_output_fingerprint_changes_with_new_commit(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "main.py", "a")
    _commit_all(repo, "initial")
    before = builder_output_fingerprint(repo)

    _write(repo, "main.py", "b")
    _commit_all(repo, "second commit")
    after = builder_output_fingerprint(repo)

    assert before != after


def test_builder_output_fingerprint_changes_with_new_empty_commit(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "main.py", "a")
    _commit_all(repo, "initial")
    before = builder_output_fingerprint(repo)

    env = {
        **os.environ,
        **_FIXED_GIT_ENV,
        "GIT_AUTHOR_DATE": "2020-01-02T00:00:00+00:00",
        "GIT_COMMITTER_DATE": "2020-01-02T00:00:00+00:00",
    }
    subprocess.run(
        ["git", "-C", str(repo), "commit", "--allow-empty", "-q", "-m", "second"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    after = builder_output_fingerprint(repo)

    # No file content changed — only the commit log did.
    assert before != after


def test_builder_output_fingerprint_unchanged_by_file_inside_git_dir(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "main.py", "a")
    _commit_all(repo, "initial")
    before = builder_output_fingerprint(repo)

    _write(repo, ".git/some-stray-file", "stray")
    after = builder_output_fingerprint(repo)

    assert before == after


def test_builder_output_fingerprint_empty_for_non_git_directory(tmp_path):
    root = tmp_path / "plain"
    root.mkdir()
    _write(root, "file.txt", "hello")

    # Must not raise even though `root` has no `.git`; the git-log segment is
    # simply empty.
    fingerprint = builder_output_fingerprint(root)
    assert isinstance(fingerprint, str)
    assert len(fingerprint) == 64


def test_builder_output_fingerprint_does_not_walk_up_to_a_parent_repo(tmp_path):
    # `root` sits inside a git repo with real commits but is not itself a
    # repo root (no `.git` of its own). `git -C root log` would otherwise
    # walk up and pick up the *parent* repo's log; the spec says the
    # git-log segment must be empty in that case, exactly as it is for a
    # directory outside any repo entirely.
    outer = tmp_path / "outer"
    _init_repo(outer)
    _write(outer, "README.md", "outer\n")
    _commit_all(outer, "outer initial")

    inner = outer / "inner"
    _write(inner, "file.txt", "hello")

    standalone = tmp_path / "standalone"
    standalone.mkdir()
    _write(standalone, "file.txt", "hello")

    assert builder_output_fingerprint(inner) == builder_output_fingerprint(standalone)


def test_compute_fingerprint_composes_tier_hashes_version_and_date(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "pkg/a.py", "a")
    _write(repo, "inj/b.py", "b")
    _commit_all(repo, "initial")

    fingerprint = compute_fingerprint(
        direct_paths=["pkg"],
        injection_paths=["inj"],
        plugin_version="1.0.0",
        claude_code_version="2.0.0",
        run_date="2026-09-27",
        ref="HEAD",
        repo=repo,
    )

    assert fingerprint == {
        "direct_tier_hash": tree_hash(["pkg"], ref="HEAD", repo=repo),
        "injection_tier_hash": tree_hash(["inj"], ref="HEAD", repo=repo),
        "plugin_version": "1.0.0",
        "claude_code_version": "2.0.0",
        "run_date": "2026-09-27",
    }


def test_compute_fingerprint_never_holds_a_commit_sha(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "pkg/a.py", "a")
    _write(repo, "inj/b.py", "b")
    _commit_all(repo, "initial")
    head_sha = _git(repo, "rev-parse", "HEAD")

    fingerprint = compute_fingerprint(
        direct_paths=["pkg"],
        injection_paths=["inj"],
        plugin_version="1.0.0",
        claude_code_version="2.0.0",
        run_date="2026-09-27",
        ref="HEAD",
        repo=repo,
    )

    for value in fingerprint.values():
        assert value != head_sha
