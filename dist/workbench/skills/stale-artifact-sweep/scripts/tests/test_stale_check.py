"""Tests for stale_check.

Exercised against real fixture repositories in temp dirs rather than mocks.
The whole point of this skill is that git reports something a human (or an
agent) reading a recorded artifact would get wrong — "this commit is still
pending" when its effect is already in the target, or "this patch still
applies" when the file moved underneath it. A mock would just re-assert the
assumption we are trying to test.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import stale_check  # noqa: E402


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def write(repo: Path, path: str, content: str) -> None:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)


def commit_all(repo: Path, message: str) -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repo on `dev` with a doc file and an unrelated file."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "dev")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    write(repo, "docs/operations.md", "alpha\nbravo\ncharlie\n")
    write(repo, "unrelated.md", "untouched\n")
    commit_all(repo, "init")
    return repo


def branch_from(repo: Path, name: str, base: str = "dev") -> None:
    git(repo, "checkout", "-q", "-b", name, base)


# --- commit containment -----------------------------------------------------


def test_commit_already_done_when_ancestor(repo: Path) -> None:
    """A commit already merged into the target is not pending work."""
    write(repo, "docs/operations.md", "alpha\nbravo\ncharlie\ndelta\n")
    sha = commit_all(repo, "add delta")

    result = stale_check.commit_status(repo, sha, "dev")

    assert result.verdict == stale_check.ALREADY_DONE
    assert any("ancestor" in line for line in result.evidence)


def test_commit_already_done_when_cherry_equivalent(repo: Path) -> None:
    """The same patch landed on the target under a different sha."""
    branch_from(repo, "feature")
    write(repo, "docs/operations.md", "alpha\nbravo\ncharlie\ndelta\n")
    sha = commit_all(repo, "add delta on feature")

    git(repo, "checkout", "-q", "dev")
    write(repo, "docs/operations.md", "alpha\nbravo\ncharlie\ndelta\n")
    commit_all(repo, "add delta directly on dev")

    result = stale_check.commit_status(repo, sha, "dev")

    assert result.verdict == stale_check.ALREADY_DONE
    assert any("equivalent" in line for line in result.evidence)


def test_commit_already_done_when_effect_present(repo: Path) -> None:
    """Target reached the same state by a different diff — not patch-identical.

    This is the case a patch-id comparison alone misses: the target contains
    the change *plus* an unrelated edit elsewhere in the same file, so the
    diffs differ but re-applying the recorded change is a no-op.
    """
    branch_from(repo, "feature")
    write(repo, "docs/operations.md", "alpha\nbravo\ncharlie\ndelta\n")
    sha = commit_all(repo, "add delta")

    git(repo, "checkout", "-q", "dev")
    write(repo, "docs/operations.md", "PREFACE\n\nalpha\nbravo\ncharlie\ndelta\n")
    commit_all(repo, "add preface and delta")

    result = stale_check.commit_status(repo, sha, "dev")

    assert result.verdict == stale_check.ALREADY_DONE
    assert any("already present" in line for line in result.evidence)


def test_commit_still_valid_when_additive(repo: Path) -> None:
    branch_from(repo, "feature")
    write(repo, "docs/operations.md", "alpha\nbravo\ncharlie\ndelta\n")
    sha = commit_all(repo, "add delta")

    result = stale_check.commit_status(repo, sha, "dev")

    assert result.verdict == stale_check.STILL_VALID
    assert any("applies cleanly" in line for line in result.evidence)


def test_commit_superseded_when_target_moved_under_it(repo: Path) -> None:
    """Correct when written, stale by merge time — the case that regresses docs."""
    branch_from(repo, "feature")
    write(repo, "docs/operations.md", "alpha\nbravo REVISED\ncharlie\n")
    sha = commit_all(repo, "revise bravo")

    git(repo, "checkout", "-q", "dev")
    write(repo, "docs/operations.md", "one\ntwo\nthree\nfour\nfive\n")
    commit_all(repo, "rewrite the table wholesale")

    result = stale_check.commit_status(repo, sha, "dev")

    assert result.verdict == stale_check.SUPERSEDED
    assert any("docs/operations.md" in line for line in result.evidence)


def test_commit_unverifiable_for_unknown_revision(repo: Path) -> None:
    result = stale_check.commit_status(repo, "deadbeef", "dev")

    assert result.verdict == stale_check.UNVERIFIABLE


def test_commit_unverifiable_for_unknown_target(repo: Path) -> None:
    sha = git(repo, "rev-parse", "HEAD")

    result = stale_check.commit_status(repo, sha, "no-such-branch")

    assert result.verdict == stale_check.UNVERIFIABLE


# --- branch containment -----------------------------------------------------


def test_branch_partially_contained_reports_each_commit(repo: Path) -> None:
    """Half a branch already landed — reviving it wholesale conflicts for zero gain."""
    branch_from(repo, "feature")
    write(repo, "docs/operations.md", "alpha\nbravo\ncharlie\ndelta\n")
    commit_all(repo, "add delta")
    write(repo, "unrelated.md", "untouched\nplus more\n")
    commit_all(repo, "extend unrelated")

    git(repo, "checkout", "-q", "dev")
    write(repo, "docs/operations.md", "alpha\nbravo\ncharlie\ndelta\n")
    commit_all(repo, "add delta directly on dev")

    result = stale_check.branch_status(repo, "feature", "dev")

    assert result.verdict == stale_check.STILL_VALID
    verdicts = [c.verdict for c in result.commits]
    assert verdicts.count(stale_check.ALREADY_DONE) == 1
    assert verdicts.count(stale_check.STILL_VALID) == 1
    assert any("1 of 2" in line for line in result.evidence)


def test_branch_fully_contained_is_already_done(repo: Path) -> None:
    branch_from(repo, "feature")
    write(repo, "docs/operations.md", "alpha\nbravo\ncharlie\ndelta\n")
    commit_all(repo, "add delta")
    git(repo, "checkout", "-q", "dev")
    git(repo, "merge", "-q", "--ff-only", "feature")

    result = stale_check.branch_status(repo, "feature", "dev")

    assert result.verdict == stale_check.ALREADY_DONE
    assert result.commits == []


def test_branch_unverifiable_when_missing(repo: Path) -> None:
    result = stale_check.branch_status(repo, "no-such-branch", "dev")

    assert result.verdict == stale_check.UNVERIFIABLE


# --- review findings --------------------------------------------------------


def test_finding_still_valid_when_cited_files_untouched(repo: Path) -> None:
    reviewed = git(repo, "rev-parse", "HEAD")
    write(repo, "unrelated.md", "untouched\nbut edited\n")
    commit_all(repo, "edit an unrelated file")

    result = stale_check.finding_status(repo, reviewed, "dev", ["docs/operations.md"])

    assert result.verdict == stale_check.STILL_VALID
    assert any("untouched" in line for line in result.evidence)


def test_finding_unverifiable_when_cited_files_changed(repo: Path) -> None:
    """The fix may have landed after the review — the script cannot decide, and says so."""
    reviewed = git(repo, "rev-parse", "HEAD")
    write(repo, "docs/operations.md", "alpha\nbravo\ncharlie\nthe fix\n")
    fix = commit_all(repo, "fix the finding")

    result = stale_check.finding_status(repo, reviewed, "dev", ["docs/operations.md"])

    assert result.verdict == stale_check.UNVERIFIABLE
    assert any(fix[:7] in line for line in result.evidence)
    assert any("re-run" in line for line in result.evidence)


def test_finding_unverifiable_when_reviewed_commit_not_in_target(repo: Path) -> None:
    branch_from(repo, "feature")
    write(repo, "docs/operations.md", "alpha\nbravo\ncharlie\ndelta\n")
    reviewed = commit_all(repo, "add delta")

    result = stale_check.finding_status(repo, reviewed, "dev", ["docs/operations.md"])

    assert result.verdict == stale_check.UNVERIFIABLE
    assert any("not in" in line for line in result.evidence)


def test_finding_with_no_cited_files_uses_whole_tree(repo: Path) -> None:
    reviewed = git(repo, "rev-parse", "HEAD")
    write(repo, "unrelated.md", "untouched\nbut edited\n")
    commit_all(repo, "edit an unrelated file")

    result = stale_check.finding_status(repo, reviewed, "dev", [])

    assert result.verdict == stale_check.UNVERIFIABLE


# --- reporting --------------------------------------------------------------


def test_report_states_it_is_read_only(repo: Path) -> None:
    sha = git(repo, "rev-parse", "HEAD")
    report = stale_check.format_report([stale_check.commit_status(repo, sha, "dev")])

    assert "read-only" in report.lower()


def test_report_carries_evidence_for_every_verdict(repo: Path) -> None:
    """A bare verdict is exactly the failure mode this skill exists to prevent."""
    sha = git(repo, "rev-parse", "HEAD")
    result = stale_check.commit_status(repo, sha, "dev")
    report = stale_check.format_report([result])

    assert result.verdict in report
    for line in result.evidence:
        assert line in report


def test_main_reports_and_exits_zero(repo: Path, capsys: pytest.CaptureFixture) -> None:
    sha = git(repo, "rev-parse", "HEAD")

    code = stale_check.main(["--repo", str(repo), "--target", "dev", "commit", sha])

    assert code == 0
    assert stale_check.ALREADY_DONE in capsys.readouterr().out
