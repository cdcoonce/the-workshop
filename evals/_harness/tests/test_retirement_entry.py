"""Tests for evals._harness.guards.retirement_entry."""

from __future__ import annotations

import subprocess
from pathlib import Path

from evals._harness.guards import GuardContext
from evals._harness.guards.retirement_entry import check


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


def _base_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "evals/commit/checks.manifest", "gated.old A description\n")
    _write(repo, "evals/commit/retired.md", "")
    base_sha = _commit(repo, "base")
    return repo, base_sha


def test_fails_when_a_gated_id_is_removed_with_no_retired_entry(tmp_path):
    repo, base_sha = _base_repo(tmp_path)
    _write(repo, "evals/commit/checks.manifest", "")
    _commit(repo, "remove the gated id")

    results = check(GuardContext(base=base_sha, repo_root=repo))

    assert len(results) == 1
    assert results[0].level == "fail"
    assert results[0].guard == "retirement_entry"
    assert "commit" in results[0].message
    assert "gated.old" in results[0].message


def test_passes_when_removal_is_paired_with_a_valid_retired_entry(tmp_path):
    repo, base_sha = _base_repo(tmp_path)
    _write(repo, "evals/commit/checks.manifest", "")
    _write(
        repo,
        "evals/commit/retired.md",
        "## gated.old\n- date: 2026-01-01\n- reason: noise\n- evidence: flaked repeatedly\n",
    )
    _commit(repo, "retire the gated id")

    results = check(GuardContext(base=base_sha, repo_root=repo))

    assert results == []


def test_passes_with_a_superseded_by_reason(tmp_path):
    repo, base_sha = _base_repo(tmp_path)
    _write(repo, "evals/commit/checks.manifest", "")
    _write(
        repo,
        "evals/commit/retired.md",
        "## gated.old\n- date: 2026-01-01\n- reason: superseded-by:gated.new\n- evidence: replaced\n",
    )
    _commit(repo, "retire the gated id via supersession")

    results = check(GuardContext(base=base_sha, repo_root=repo))

    assert results == []


def test_fails_when_the_new_entry_has_no_date(tmp_path):
    repo, base_sha = _base_repo(tmp_path)
    _write(repo, "evals/commit/checks.manifest", "")
    _write(
        repo,
        "evals/commit/retired.md",
        "## gated.old\n- reason: noise\n- evidence: flaked repeatedly\n",
    )
    _commit(repo, "retire without a date")

    results = check(GuardContext(base=base_sha, repo_root=repo))

    assert len(results) == 1
    assert results[0].level == "fail"


def test_fails_when_the_new_entry_has_a_malformed_date(tmp_path):
    repo, base_sha = _base_repo(tmp_path)
    _write(repo, "evals/commit/checks.manifest", "")
    _write(
        repo,
        "evals/commit/retired.md",
        "## gated.old\n- date: 01/01/2026\n- reason: noise\n- evidence: flaked repeatedly\n",
    )
    _commit(repo, "retire with a malformed date")

    results = check(GuardContext(base=base_sha, repo_root=repo))

    assert len(results) == 1
    assert results[0].level == "fail"


def test_fails_when_the_new_entry_has_an_invalid_reason(tmp_path):
    repo, base_sha = _base_repo(tmp_path)
    _write(repo, "evals/commit/checks.manifest", "")
    _write(
        repo,
        "evals/commit/retired.md",
        "## gated.old\n- date: 2026-01-01\n- reason: flaky\n- evidence: flaked repeatedly\n",
    )
    _commit(repo, "retire with an invalid reason")

    results = check(GuardContext(base=base_sha, repo_root=repo))

    assert len(results) == 1
    assert results[0].level == "fail"


def test_fails_when_the_new_entry_has_no_evidence(tmp_path):
    repo, base_sha = _base_repo(tmp_path)
    _write(repo, "evals/commit/checks.manifest", "")
    _write(
        repo,
        "evals/commit/retired.md",
        "## gated.old\n- date: 2026-01-01\n- reason: noise\n",
    )
    _commit(repo, "retire with no evidence")

    results = check(GuardContext(base=base_sha, repo_root=repo))

    assert len(results) == 1
    assert results[0].level == "fail"


def test_fires_even_though_the_skill_reads_inactive_at_both_base_and_head(tmp_path):
    """The floor guard (#997 empty_gated_set) is the only guard in this issue
    scoped to active skills. This one must fire unconditionally: making the
    skill inactive by removing its last gated ID must not be a way to skip
    filing a retired.md entry for that ID.
    """
    repo, base_sha = _base_repo(tmp_path)
    # At base the skill is active (one gated id, no retired entries). At head
    # it reads inactive too (empty manifest, empty retired.md) -- the guard
    # must still fail.
    _write(repo, "evals/commit/checks.manifest", "")
    _commit(repo, "remove the only gated id, going inactive")

    results = check(GuardContext(base=base_sha, repo_root=repo))

    assert len(results) == 1
    assert results[0].level == "fail"


def test_no_fail_when_no_gated_id_is_removed(tmp_path):
    repo, base_sha = _base_repo(tmp_path)
    _write(repo, "evals/commit/unrelated.txt", "hello\n")
    _commit(repo, "unrelated change")

    results = check(GuardContext(base=base_sha, repo_root=repo))

    assert results == []
