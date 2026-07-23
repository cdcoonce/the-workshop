"""Tests for merge_order.

Git behaviour is exercised against real fixture repositories in temp dirs
rather than mocks: the whole point of this skill is that `git merge-tree`
reports something non-obvious (two branches individually clean, mutually
conflicting), and a mock would just re-assert our own assumptions.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import merge_order  # noqa: E402


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


def commit_all(repo: Path, message: str) -> None:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repo with `dev` and a shared doc file."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "dev")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    write(repo, "docs/operations.md", "line1\nline2\nline3\n")
    write(repo, "unrelated.md", "untouched\n")
    commit_all(repo, "init")
    return repo


def branch_from(repo: Path, name: str, base: str = "dev") -> None:
    git(repo, "checkout", "-q", "-b", name, base)


# --- platform detection -----------------------------------------------------


@pytest.mark.parametrize(
    ("remote", "expected"),
    [
        ("git@gitlab.com:group/proj.git", "gitlab"),
        ("https://gitlab.com/group/proj.git", "gitlab"),
        ("git@github.com:user/proj.git", "github"),
        ("https://github.com/user/proj.git", "github"),
        ("https://example.invalid/x.git", None),
    ],
)
def test_detect_platform(remote: str, expected: str | None) -> None:
    assert merge_order.detect_platform(remote) == expected


# --- conflict detection -----------------------------------------------------


def test_individually_clean_branches_can_still_conflict_with_each_other(
    repo: Path,
) -> None:
    """The core insight: both merge into dev cleanly, but not after each other."""
    branch_from(repo, "big")
    write(repo, "docs/operations.md", "line1\n" + "".join(f"big{i}\n" for i in range(40)) + "line3\n")
    commit_all(repo, "big change")

    branch_from(repo, "small", "dev")
    write(repo, "docs/operations.md", "line1\nsmall-edit\nline3\n")
    commit_all(repo, "small change")

    assert merge_order.merges_clean(repo, "dev", "big") is True
    assert merge_order.merges_clean(repo, "dev", "small") is True

    pairs = merge_order.pairwise_conflicts(repo, "dev", ["big", "small"])
    assert pairs[("big", "small")] == ["docs/operations.md"]


def test_non_overlapping_branches_report_no_conflict(repo: Path) -> None:
    branch_from(repo, "a")
    write(repo, "a.md", "a\n")
    commit_all(repo, "a")

    branch_from(repo, "b", "dev")
    write(repo, "b.md", "b\n")
    commit_all(repo, "b")

    pairs = merge_order.pairwise_conflicts(repo, "dev", ["a", "b"])
    assert pairs[("a", "b")] == []


# --- cost / ordering --------------------------------------------------------


def test_contested_size_counts_added_plus_deleted(repo: Path) -> None:
    branch_from(repo, "big")
    write(repo, "docs/operations.md", "line1\n" + "".join(f"big{i}\n" for i in range(40)) + "line3\n")
    commit_all(repo, "big change")

    size = merge_order.contested_size(repo, "dev", "big", "docs/operations.md")
    assert size > 20


@pytest.mark.parametrize(
    ("first_name", "second_name", "first_size", "second_size"),
    [
        # Pair key is sorted, so these two cases exercise BOTH sides of the
        # size comparison. Testing only one lets an inverted comparison fall
        # through to the equal-size tie-break and still produce the right
        # answer by luck — which is exactly what a mutation check caught.
        ("a-big", "z-small", 45, 10),
        ("a-small", "z-big", 10, 45),
    ],
)
def test_larger_change_is_recommended_first(
    first_name: str, second_name: str, first_size: int, second_size: int
) -> None:
    """The MR with the bigger contested diff merges first; the small one rebases."""
    bigger = first_name if first_size > second_size else second_name
    smaller = second_name if first_size > second_size else first_name
    order = merge_order.recommend_order(
        branches=[first_name, second_name],
        conflicts={(first_name, second_name): ["docs/operations.md"]},
        sizes={
            (first_name, "docs/operations.md"): first_size,
            (second_name, "docs/operations.md"): second_size,
        },
        drafts=set(),
        chains=[],
    )
    assert order.sequence == [bigger, smaller]
    assert order.contested is False
    assert bigger in order.rationale[0]


def test_equal_size_breaks_tie_toward_non_draft(repo: Path) -> None:
    order = merge_order.recommend_order(
        branches=["draft-one", "ready-one"],
        conflicts={("draft-one", "ready-one"): ["docs/operations.md"]},
        sizes={
            ("draft-one", "docs/operations.md"): 10,
            ("ready-one", "docs/operations.md"): 10,
        },
        drafts={"draft-one"},
        chains=[],
    )
    assert order.sequence[0] == "ready-one"


def test_no_conflicts_yields_any_order(repo: Path) -> None:
    order = merge_order.recommend_order(
        branches=["a", "b"],
        conflicts={("a", "b"): []},
        sizes={},
        drafts=set(),
        chains=[],
    )
    assert order.any_order is True


# --- stacked chains ---------------------------------------------------------


def test_stacked_chain_is_a_hard_dependency(repo: Path) -> None:
    """B targets A, so A must merge first regardless of diff size."""
    mrs = [
        merge_order.MergeRequest(ident="1", source="feat-a", target="dev", draft=False),
        merge_order.MergeRequest(ident="2", source="feat-b", target="feat-a", draft=False),
    ]
    chains = merge_order.detect_chains(mrs)
    assert chains == [["feat-a", "feat-b"]]


def test_chain_order_survives_cost_ranking(repo: Path) -> None:
    order = merge_order.recommend_order(
        branches=["feat-a", "feat-b"],
        conflicts={},
        sizes={},
        drafts=set(),
        chains=[["feat-a", "feat-b"]],
    )
    assert order.sequence.index("feat-a") < order.sequence.index("feat-b")


def test_independent_mrs_produce_no_chain(repo: Path) -> None:
    mrs = [
        merge_order.MergeRequest(ident="1", source="feat-a", target="dev", draft=False),
        merge_order.MergeRequest(ident="2", source="feat-b", target="dev", draft=False),
    ]
    assert merge_order.detect_chains(mrs) == []


# --- guards -----------------------------------------------------------------


def test_git_version_guard_rejects_old_git() -> None:
    assert merge_order.supports_write_tree("git version 2.37.1") is False
    assert merge_order.supports_write_tree("git version 2.38.0") is True
    assert merge_order.supports_write_tree("git version 2.43.0") is True


def test_cycle_is_reported_not_invented(repo: Path) -> None:
    """A 3-way mutual conflict with equal sizes must not fabricate a total order."""
    order = merge_order.recommend_order(
        branches=["x", "y", "z"],
        conflicts={("x", "y"): ["f"], ("y", "z"): ["f"], ("x", "z"): ["f"]},
        sizes={
            ("x", "f"): 10,
            ("y", "f"): 10,
            ("z", "f"): 10,
        },
        drafts=set(),
        chains=[],
    )
    # Still returns a defensible sequence, but flags that it is arbitrary.
    assert len(order.sequence) == 3
    assert order.contested is True


# --- report -----------------------------------------------------------------


def test_report_lists_analysed_mrs_even_when_no_conflicts() -> None:
    """"Any order works" must be distinguishable from "found nothing"."""
    mrs = [
        merge_order.MergeRequest(ident="84", source="fix/sql", target="dev", draft=True),
        merge_order.MergeRequest(ident="85", source="docs/reconcile", target="dev"),
    ]
    order = merge_order.Order(sequence=["docs/reconcile", "fix/sql"], any_order=True)
    report = merge_order.build_report("repo", "dev", mrs, {}, order)

    assert "Analysed (2 open)" in report
    assert "!84" in report and "!85" in report
    assert "*(draft)*" in report
    assert "any order works" in report.lower()


def test_report_says_so_when_no_mrs_found() -> None:
    order = merge_order.Order(sequence=[], any_order=True)
    report = merge_order.build_report("repo", "dev", [], {}, order)
    assert "No open merge requests found." in report


def test_mr_lookup_runs_in_the_target_repo(monkeypatch, tmp_path: Path) -> None:
    """glab/gh resolve the project from cwd — querying from the caller's cwd
    silently returns a DIFFERENT repo's MRs. Caught live during smoke testing."""
    seen: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        seen["cwd"] = kwargs.get("cwd")

        class R:
            returncode = 0
            stdout = "[]"

        return R()

    monkeypatch.setattr(merge_order.subprocess, "run", fake_run)
    merge_order.list_merge_requests("gitlab", "dev", tmp_path)
    assert seen["cwd"] == str(tmp_path)


def test_resolve_target_prefers_remote_tracking_ref(repo: Path) -> None:
    """A stale local branch silently fabricates conflicts — analysed against
    origin/<target> instead. Caught live: local dev was 25 commits behind."""
    git(repo, "update-ref", "refs/remotes/origin/dev", git(repo, "rev-parse", "dev"))
    branch_from(repo, "ahead")
    write(repo, "new.md", "x\n")
    commit_all(repo, "advance")
    git(repo, "update-ref", "refs/remotes/origin/dev", git(repo, "rev-parse", "ahead"))

    ref, note = merge_order.resolve_target(repo, "dev")
    assert ref == "origin/dev"
    assert note is not None and "behind" in note


def test_resolve_target_falls_back_to_local_when_no_remote(repo: Path) -> None:
    ref, note = merge_order.resolve_target(repo, "dev")
    assert ref == "dev"
    assert note is not None and "no `origin/dev`" in note
