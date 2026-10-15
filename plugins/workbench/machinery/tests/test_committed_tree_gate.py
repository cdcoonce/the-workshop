"""Tests for committed_tree_gate — the health gate run on the staged tree.

On 2026-10-15 a vault /wrap-up passed the gate on the working tree and then
committed a tree that failed it: a staged note linked to a note that was still
untracked, and wrap-up stages only reviewed work. The gate must judge the tree
the commit will record, not the directory it was run from.

Each fixture repo carries a tiny stand-in ``ci/vault_health.py`` that fails on
any ``[[target]]`` with no ``target.md`` beside it under its own root, and names
the offender. Run from the working tree it would pass where these tests expect
a failure, so the tests discriminate between the two trees.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "engine" / "committed_tree_gate.py"

FAKE_GATE = '''\
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
import re, sys
from pathlib import Path
root = Path(__file__).resolve().parent.parent
bad = [
    f"{note.relative_to(root)} -> [[{target}]]"
    for note in sorted(root.rglob("*.md"))
    for target in re.findall(r"\\[\\[([^\\]|]+)", note.read_text())
    if not (root / f"{target}.md").exists()
]
for line in bad:
    print(line, file=sys.stderr)
sys.exit(1 if bad else 0)
'''


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


def _repo(tmp_path: Path, *, gate: bool = True) -> Path:
    repo = tmp_path / "vault"
    repo.mkdir()
    _git(repo, "init", "-q", "--initial-branch=main")
    _git(repo, "config", "user.email", "t@t.t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "commit.gpgsign", "false")
    (repo / "seed.md").write_text("seed\n")
    if gate:
        (repo / "ci").mkdir()
        (repo / "ci" / "vault_health.py").write_text(FAKE_GATE)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed")
    return repo


def _run(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--vault", str(repo)],
        capture_output=True, text=True, timeout=120,
    )


def test_fails_when_staged_note_links_to_an_untracked_note(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "decisions.md").write_text("See [[datasheet]].\n")
    (repo / "datasheet.md").write_text("Present on disk, never staged.\n")
    _git(repo, "add", "decisions.md")

    result = _run(repo)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "decisions.md -> [[datasheet]]" in result.stdout + result.stderr


def test_passes_once_the_linked_note_is_staged_too(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "decisions.md").write_text("See [[datasheet]].\n")
    (repo / "datasheet.md").write_text("Now part of the commit.\n")
    _git(repo, "add", "decisions.md", "datasheet.md")

    result = _run(repo)

    assert result.returncode == 0, result.stdout + result.stderr


def test_unstaged_breakage_in_the_working_tree_does_not_fail_the_commit(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "seed.md").write_text("Unstaged edit linking [[nowhere]].\n")

    result = _run(repo)

    assert result.returncode == 0, result.stdout + result.stderr


def test_leaves_index_and_worktree_untouched(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "decisions.md").write_text("See [[datasheet]].\n")
    (repo / "datasheet.md").write_text("untracked\n")
    _git(repo, "add", "decisions.md")
    index = (repo / ".git" / "index").read_bytes()
    status = _git(repo, "status", "--porcelain")

    _run(repo)

    assert (repo / ".git" / "index").read_bytes() == index
    assert _git(repo, "status", "--porcelain") == status


def test_vault_without_a_gate_script_passes(tmp_path: Path) -> None:
    repo = _repo(tmp_path, gate=False)
    (repo / "decisions.md").write_text("See [[datasheet]].\n")
    _git(repo, "add", "decisions.md")

    result = _run(repo)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "no ci/vault_health.py" in result.stdout


def test_not_a_git_repo_fails_closed(tmp_path: Path) -> None:
    result = _run(tmp_path)

    assert result.returncode == 2
