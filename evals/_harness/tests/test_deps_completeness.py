"""Tests for evals._harness.guards.deps_completeness."""

from __future__ import annotations

import subprocess
from pathlib import Path

from evals._harness.guards import GuardContext
from evals._harness.guards.deps_completeness import _markdown_link_targets, check


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


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _write(repo: Path, rel_path: str, content: str) -> None:
    path = repo / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _build_repo(tmp_path: Path, *, direct: str) -> Path:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(
        repo,
        "plugins/workbench/skills/commit/SKILL.md",
        "See [the conventions](other.md) for details.\n",
    )
    _write(repo, "plugins/workbench/skills/commit/other.md", "conventions\n")
    _write(repo, "evals/commit/deps", f'direct = ["{direct}"]\ninjection = []\n')
    _commit(repo, "initial")
    return repo


def test_fails_when_a_skill_md_link_is_not_covered_by_the_direct_list(tmp_path):
    repo = _build_repo(tmp_path, direct="plugins/workbench/skills/commit/SKILL.md")

    results = check(GuardContext(base="HEAD", repo_root=repo))

    assert len(results) == 1
    assert results[0].level == "fail"
    assert results[0].guard == "deps_completeness"
    assert "commit" in results[0].message
    assert "other.md" in results[0].message


def test_passes_when_the_whole_skill_directory_covers_the_link(tmp_path):
    repo = _build_repo(tmp_path, direct="plugins/workbench/skills/commit")

    results = check(GuardContext(base="HEAD", repo_root=repo))

    assert results == []


def test_ignores_http_links(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(
        repo,
        "plugins/workbench/skills/commit/SKILL.md",
        "See [the spec](https://example.com/spec.md) for details.\n",
    )
    _write(
        repo,
        "evals/commit/deps",
        'direct = ["plugins/workbench/skills/commit/SKILL.md"]\ninjection = []\n',
    )
    _commit(repo, "initial")

    results = check(GuardContext(base="HEAD", repo_root=repo))

    assert results == []


def test_markdown_link_targets_excludes_urls_strips_fragments_and_titles():
    text = (
        "[a](http://x.com/a.md) [b](https://y.com/b.md) "
        '[c](local.md#section) [d](other.md "a title")'
    )
    assert _markdown_link_targets(text) == ["local.md", "other.md"]


def test_no_fail_for_a_link_to_an_untracked_file(tmp_path):
    """The positive conjunct: an untracked link target is not a violation."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(
        repo,
        "plugins/workbench/skills/commit/SKILL.md",
        "See [nope](does-not-exist.md) for details.\n",
    )
    _write(
        repo,
        "evals/commit/deps",
        'direct = ["plugins/workbench/skills/commit/SKILL.md"]\ninjection = []\n',
    )
    _commit(repo, "initial")

    results = check(GuardContext(base="HEAD", repo_root=repo))

    assert results == []


def test_skips_a_rostered_skill_with_no_deps_file_yet(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(
        repo,
        "plugins/workbench/skills/commit/SKILL.md",
        "See [the conventions](other.md) for details.\n",
    )
    _write(repo, "plugins/workbench/skills/commit/other.md", "conventions\n")
    _commit(repo, "initial")

    results = check(GuardContext(base="HEAD", repo_root=repo))

    assert results == []
