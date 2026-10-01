"""Tests for evals._harness.guards.retired_append_only."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from evals._harness.guards import GuardContext
from evals._harness.guards.retired_append_only import check


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


_ENTRY_ONE = "## gated.old\n- date: 2026-01-01\n- reason: noise\n- evidence: flaked repeatedly\n"


def _base_repo(tmp_path: Path, retired_text: str = _ENTRY_ONE) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "evals/commit/retired.md", retired_text)
    base_sha = _commit(repo, "base")
    return repo, base_sha


def test_fails_when_an_existing_entrys_date_is_edited(tmp_path):
    repo, base_sha = _base_repo(tmp_path)
    _write(
        repo,
        "evals/commit/retired.md",
        "## gated.old\n- date: 2026-02-02\n- reason: noise\n- evidence: flaked repeatedly\n",
    )
    _commit(repo, "edit the date")

    results = check(GuardContext(base=base_sha, repo_root=repo))

    assert len(results) == 1
    assert results[0].level == "fail"
    assert results[0].guard == "retired_append_only"
    assert "commit" in results[0].message


def test_fails_when_an_existing_entrys_reason_is_edited(tmp_path):
    repo, base_sha = _base_repo(tmp_path)
    _write(
        repo,
        "evals/commit/retired.md",
        "## gated.old\n- date: 2026-01-01\n- reason: upkeep\n- evidence: flaked repeatedly\n",
    )
    _commit(repo, "edit the reason")

    results = check(GuardContext(base=base_sha, repo_root=repo))

    assert len(results) == 1
    assert results[0].level == "fail"


def test_fails_when_an_existing_entrys_evidence_is_edited(tmp_path):
    repo, base_sha = _base_repo(tmp_path)
    _write(
        repo,
        "evals/commit/retired.md",
        "## gated.old\n- date: 2026-01-01\n- reason: noise\n- evidence: something else entirely\n",
    )
    _commit(repo, "edit the evidence")

    results = check(GuardContext(base=base_sha, repo_root=repo))

    assert len(results) == 1
    assert results[0].level == "fail"


def test_fails_when_an_existing_entry_is_deleted(tmp_path):
    repo, base_sha = _base_repo(tmp_path)
    _write(repo, "evals/commit/retired.md", "")
    _commit(repo, "delete the entry")

    results = check(GuardContext(base=base_sha, repo_root=repo))

    assert len(results) == 1
    assert results[0].level == "fail"


def test_fires_even_though_deleting_the_only_entry_flips_the_skill_to_inactive(tmp_path):
    """Guards this issue's #2 (retirement_entry) closes off manually removing
    a gated ID without filing a retired.md entry. This guard closes the
    matching hole for retired.md itself: deleting the skill's only entry
    would silently flip it back to a state with no retirement record and no
    consequence, if this guard were skipped once the skill reads inactive.
    """
    repo, base_sha = _base_repo(tmp_path)
    _write(repo, "evals/commit/retired.md", "")
    _commit(repo, "delete the only retired entry, going inactive")

    results = check(GuardContext(base=base_sha, repo_root=repo))

    assert len(results) == 1
    assert results[0].level == "fail"


def test_passes_when_only_appending_new_entries(tmp_path):
    repo, base_sha = _base_repo(tmp_path)
    _write(
        repo,
        "evals/commit/retired.md",
        _ENTRY_ONE + "\n## gated.new\n- date: 2026-03-01\n- reason: upkeep\n- evidence: superseded by a newer check\n",
    )
    _commit(repo, "append a new entry")

    results = check(GuardContext(base=base_sha, repo_root=repo))

    assert results == []


def test_no_fail_on_no_change(tmp_path):
    repo, base_sha = _base_repo(tmp_path)
    _write(repo, "evals/commit/unrelated.txt", "hello\n")
    _commit(repo, "unrelated change")

    results = check(GuardContext(base=base_sha, repo_root=repo))

    assert results == []


def _diverged_repo(tmp_path: Path) -> tuple[Path, str]:
    """Fork at F; base branch moves on; the PR branch changes only an unrelated file.

    Returns (repo, base_branch_name) with HEAD checked out on the PR branch.
    The base branch TIP differs from the merge-base in exactly the ways every
    guard here reads: it adds gated id ``y``, adds retired entry ``z``, and
    edits a direct-tier file. A guard that reads the TIP of base instead of
    the merge-base sees all of that as the PR removing/editing it.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "evals/commit/checks.manifest", "x A description\n")
    _write(repo, "evals/commit/retired.md", "")
    _write(repo, "evals/commit/marker.txt", "original\n")
    _write(repo, "evals/commit/deps", 'direct = ["evals/commit/marker.txt"]\ninjection = []\n')
    _commit(repo, "fork point")
    base_branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")

    _git(repo, "checkout", "-q", "-b", "pr")
    _write(repo, "unrelated.txt", "pr change\n")
    _commit(repo, "pr: unrelated change")

    _git(repo, "checkout", "-q", base_branch)
    _write(repo, "evals/commit/checks.manifest", "x A description\ny B description\n")
    _write(
        repo,
        "evals/commit/retired.md",
        "## z\n- date: 2026-01-01\n- reason: noise\n- evidence: flaked repeatedly\n",
    )
    _write(repo, "evals/commit/marker.txt", "base moved on\n")
    _commit(repo, "base moves on after the fork")

    _git(repo, "checkout", "-q", "pr")
    return repo, base_branch


def test_reads_base_content_at_the_merge_base_not_the_base_tip(tmp_path):
    repo, base_branch = _diverged_repo(tmp_path)

    results = check(GuardContext(base=base_branch, repo_root=repo))

    assert results == []


def test_fails_loudly_when_the_base_ref_cannot_be_resolved(tmp_path):
    repo, _base_branch = _diverged_repo(tmp_path)

    with pytest.raises(subprocess.CalledProcessError):
        check(GuardContext(base="no-such-ref", repo_root=repo))
