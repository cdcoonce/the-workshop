"""`predicates.end_state`: the snapshot the conductor takes after each attempt."""

from __future__ import annotations

import pytest

from commit_c_support import git, write_transcript

from evals._harness.dispatch import CaseContractError, snapshot_end_state


def _commit(repo, message: str, *paths: str) -> str:
    git(repo, "add", "--", *paths)
    git(repo, "commit", "--quiet", "-m", message)
    return git(repo, "rev-parse", "HEAD").strip()


def test_two_new_commits_give_four_files_oldest_first(predicates, built_repo, case_dir):
    first = _commit(built_repo, "feat(invoice): add bulk pricing", "invoice/pricing.py", "tests/test_pricing.py")
    second = _commit(built_repo, "fix(names): collapse inner whitespace", "names/normalize.py", "tests/test_names.py")

    snapshot = predicates.end_state(built_repo, case_dir, [])

    assert sorted(snapshot) == ["commit-1.files", "commit-1.log", "commit-2.files", "commit-2.log"]
    assert snapshot["commit-1.log"] == f"{first}\nfeat(invoice): add bulk pricing\n\n"
    assert snapshot["commit-2.log"] == f"{second}\nfix(names): collapse inner whitespace\n\n"
    assert snapshot["commit-1.files"] == "invoice/pricing.py\ntests/test_pricing.py\n"
    assert snapshot["commit-2.files"] == "names/normalize.py\ntests/test_names.py\n"


def test_the_log_and_files_formats_are_the_documented_git_commands(predicates, built_repo, case_dir):
    (built_repo / "README.md").write_text("# invoice-tools\n\nMore words.\n")
    sha = _commit(built_repo, "docs: describe the helpers\n\nA body line.", "README.md")

    snapshot = predicates.end_state(built_repo, case_dir, [])

    assert snapshot["commit-1.log"] == git(built_repo, "log", "-1", "--format=%H%n%B", sha)
    assert snapshot["commit-1.files"] == git(built_repo, "show", "--name-only", "--format=", sha)


def test_zero_new_commits_gives_no_commit_files(predicates, built_repo, case_dir):
    assert predicates.end_state(built_repo, case_dir, []) == {}


def test_the_planted_history_is_never_a_new_commit(predicates, built_repo, case_dir):
    snapshot = predicates.end_state(built_repo, case_dir, [])
    assert not any(name.startswith("commit-") for name in snapshot)
    assert len(git(built_repo, "rev-list", "--all").split()) >= 3


def test_commits_on_another_branch_are_new_commits_too(predicates, built_repo, case_dir):
    git(built_repo, "switch", "--quiet", "-c", "topic")
    _commit(built_repo, "feat: add bulk pricing", "invoice/pricing.py")
    git(built_repo, "switch", "--quiet", "main")

    assert sorted(predicates.end_state(built_repo, case_dir, [])) == ["commit-1.files", "commit-1.log"]


def test_a_committed_dotenv_shows_in_the_files_snapshot(predicates, built_repo, case_dir):
    _commit(built_repo, "chore: add local config", ".env")
    snapshot = predicates.end_state(built_repo, case_dir, [])
    assert snapshot["commit-1.files"].split() == [".env"]


def test_commit_numbers_past_nine_keep_their_order(predicates, built_repo, case_dir):
    for number in range(11):
        (built_repo / "README.md").write_text(f"# invoice-tools {number}\n")
        _commit(built_repo, f"docs: revision {number}", "README.md")
    snapshot = predicates.end_state(built_repo, case_dir, [])
    assert snapshot["commit-1.log"].splitlines()[1] == "docs: revision 0"
    assert snapshot["commit-10.log"].splitlines()[1] == "docs: revision 9"
    assert snapshot["commit-11.log"].splitlines()[1] == "docs: revision 10"


def test_a_workdir_without_the_base_head_file_is_refused(predicates, built_repo, case_dir):
    (built_repo / ".git" / "eval-base-head").unlink()
    with pytest.raises(FileNotFoundError):
        predicates.end_state(built_repo, case_dir, [])


def test_the_harness_snapshot_writes_the_files(built_repo, case_dir, tmp_path):
    _commit(built_repo, "feat: add bulk pricing", "invoice/pricing.py")
    transcript = write_transcript(tmp_path / "agent-x.jsonl", ["make test"])
    dest = tmp_path / "end_state"

    snapshot_end_state(case_dir, built_repo, [transcript], dest)

    assert sorted(path.name for path in dest.iterdir()) == ["commit-1.files", "commit-1.log"]


def test_the_harness_snapshot_of_an_untouched_repo_is_empty(built_repo, case_dir, tmp_path):
    dest = tmp_path / "end_state"
    snapshot_end_state(case_dir, built_repo, [], dest)
    assert dest.is_dir()
    assert list(dest.iterdir()) == []


def test_the_harness_names_are_safe_file_names(built_repo, case_dir, tmp_path):
    """The harness refuses unsafe snapshot names; ours must never trip it."""
    _commit(built_repo, "feat: add bulk pricing", "invoice/pricing.py")
    try:
        snapshot_end_state(case_dir, built_repo, [], tmp_path / "end_state")
    except CaseContractError as error:  # pragma: no cover - the failure being guarded
        pytest.fail(str(error))
