"""Tests for the stranded-branch detector lane of the Graph Gardener.

Red-Green-Refactor: these tests were written BEFORE the implementation.
They cover detect_stranded_branches(), proposal_signature("branch", ...), and
the write_queue() ### Stranded branches rendering.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess as _sp
from pathlib import Path

# ---------------------------------------------------------------------------
# Module bootstrap — load graph_gardener without adding it to the package
# ---------------------------------------------------------------------------

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "engine"

_spec = importlib.util.spec_from_file_location(
    "graph_gardener", SCRIPTS_DIR / "graph_gardener.py"
)
gg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gg)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

OLD_DATE = "2020-01-01T00:00:00 +0000"
_OLD_ENV = {"GIT_COMMITTER_DATE": OLD_DATE, "GIT_AUTHOR_DATE": OLD_DATE}


def _git(repo, *args, env=None):
    merged_env = {**os.environ, **(env or {})}
    _sp.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True,
            env=merged_env)


def _init_repo(tmp_path):
    """Init a git repo with an initial commit on main, using old timestamps."""
    repo = tmp_path
    _git(repo, "init")
    _git(repo, "config", "user.email", "t@t.t")
    _git(repo, "config", "user.name", "t")
    (repo / "personal").mkdir()
    (repo / "personal" / "seed.md").write_text(
        "---\ndate: 2020-01-01\ndescription: seed\ntags:\n  - test\n---\n\nSeed.\n"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "init", env=_OLD_ENV)
    # Ensure the default branch is called 'main'
    try:
        _git(repo, "branch", "-M", "main")
    except Exception:
        pass
    return repo


# ---------------------------------------------------------------------------
# detect_stranded_branches tests
# ---------------------------------------------------------------------------

def test_stale_branch_with_new_note_is_flagged(tmp_path):
    """A branch older than STALE_DAYS with a net-new .md → detected."""
    repo = _init_repo(tmp_path)

    _git(repo, "checkout", "-b", "feat/stranded")
    (repo / "personal" / "new-note.md").write_text(
        "---\ndate: 2020-01-01\ndescription: new\ntags:\n  - test\n---\n\nNew note.\n"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "add new note", env=_OLD_ENV)
    _git(repo, "checkout", "main")

    result = gg.detect_stranded_branches(repo)

    assert len(result) == 1
    assert result[0]["branch"] == "feat/stranded"
    assert "personal/new-note.md" in result[0]["files"]


def test_fresh_branch_not_flagged(tmp_path):
    """A branch whose tip is within STALE_DAYS → not flagged."""
    repo = _init_repo(tmp_path)

    _git(repo, "checkout", "-b", "feat/active-wip")
    (repo / "personal" / "wip-note.md").write_text(
        "---\ndate: 2020-01-01\ndescription: wip\ntags:\n  - test\n---\n\nWIP note.\n"
    )
    _git(repo, "add", "-A")
    # No env override → current timestamp (fresh, within default 14 days)
    _git(repo, "commit", "-m", "add wip note")
    _git(repo, "checkout", "main")

    result = gg.detect_stranded_branches(repo, stale_days=14)

    assert result == []


def test_backup_branch_not_flagged(tmp_path):
    """backup/* branches are excluded even when stale with new notes."""
    repo = _init_repo(tmp_path)

    _git(repo, "checkout", "-b", "backup/2024-01")
    (repo / "personal" / "backup-note.md").write_text(
        "---\ndate: 2020-01-01\ndescription: backup\ntags:\n  - test\n---\n\nBackup.\n"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "backup snapshot", env=_OLD_ENV)
    _git(repo, "checkout", "main")

    result = gg.detect_stranded_branches(repo)

    assert result == []


def test_branch_with_only_edits_not_flagged(tmp_path):
    """A branch that only modifies existing notes (no additions) → not flagged."""
    repo = _init_repo(tmp_path)

    _git(repo, "checkout", "-b", "feat/edit-only")
    (repo / "personal" / "seed.md").write_text(
        "---\ndate: 2020-01-01\ndescription: updated seed\ntags:\n  - test\n---\n\nEdited.\n"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "edit existing note", env=_OLD_ENV)
    _git(repo, "checkout", "main")

    result = gg.detect_stranded_branches(repo)

    assert result == []


def test_git_failure_returns_empty_no_crash(tmp_path):
    """Non-git directory → returns [] without raising an exception."""
    non_repo = tmp_path / "not-a-repo"
    non_repo.mkdir()

    result = gg.detect_stranded_branches(non_repo)

    assert result == []


# ---------------------------------------------------------------------------
# proposal_signature test
# ---------------------------------------------------------------------------

def test_proposal_signature_branch():
    """Branch signatures use the branch name as the key."""
    sig = gg.proposal_signature("branch", "", "feat/my-branch")
    assert sig == "branch|feat/my-branch"


# ---------------------------------------------------------------------------
# write_queue rendering tests
# ---------------------------------------------------------------------------

def test_write_queue_renders_none_when_no_stranded(tmp_path):
    """Empty stranded list → ### Stranded branches section with _(none)_."""
    queue_path = gg.write_queue(
        tmp_path, "personal",
        gg.LaneAResult(), {},
        dry_run=False, dismissed=set(),
        stranded=[],
    )
    content = queue_path.read_text()
    assert "### Stranded branches" in content
    assert "_(none)_" in content


def test_write_queue_renders_stranded_branch_and_file(tmp_path):
    """Stranded branch entry → branch name and file path appear in output."""
    stranded = [{"branch": "feat/old-work", "files": ["personal/new-note.md"]}]
    queue_path = gg.write_queue(
        tmp_path, "personal",
        gg.LaneAResult(), {},
        dry_run=False, dismissed=set(),
        stranded=stranded,
    )
    content = queue_path.read_text()
    assert "feat/old-work" in content
    assert "personal/new-note.md" in content
    # gsig comment for garden apply skill
    assert "gsig: branch|feat/old-work" in content


def test_dismissed_branch_not_in_queue(tmp_path):
    """Dismissed branch signature → suppressed from rendered output."""
    stranded = [{"branch": "feat/suppressed", "files": ["personal/note.md"]}]
    dismissed = {"branch|feat/suppressed"}
    queue_path = gg.write_queue(
        tmp_path, "personal",
        gg.LaneAResult(), {},
        dry_run=False, dismissed=dismissed,
        stranded=stranded,
    )
    content = queue_path.read_text()
    assert "feat/suppressed" not in content
