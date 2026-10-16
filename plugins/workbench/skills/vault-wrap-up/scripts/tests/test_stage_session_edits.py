"""Tests for stage_session_edits: stage one session's blocks of a shared-dirty file."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

from stage_session_edits import main  # noqa: E402

KD = "brain/Key Decisions.md"
BASE = "# Key Decisions\n\n## Recent\n\n### 2026-10-15 — older entry\n\n**Decided:** old.\n"
OWN = "### 2026-10-16 — own entry\n\n**Decided:** mine.\n\n"
FOREIGN = "### 2026-10-16 — foreign entry\n\n**Decided:** theirs.\n\n"
DIRTY = BASE.replace("## Recent\n\n", "## Recent\n\n" + FOREIGN + OWN)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "brain").mkdir()
    (tmp_path / KD).write_text(BASE, encoding="utf-8")
    (tmp_path / "other.md").write_text("other\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    (tmp_path / KD).write_text(DIRTY, encoding="utf-8")
    return tmp_path


def _run(repo: Path, capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, dict]:
    code = main(["--vault", str(repo), "--json", *args])
    out = capsys.readouterr().out
    return code, json.loads(out) if out.strip() else {}


def _ids(repo: Path, capsys: pytest.CaptureFixture[str], path: str = KD) -> dict[str, str]:
    code, report = _run(repo, capsys, "--path", path, "--list")
    assert code == 0
    return {b["first_line"]: b["id"] for b in report["blocks"]}


def test_list_shows_each_entry_with_its_section(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, report = _run(repo, capsys, "--path", KD, "--list")
    assert code == 0
    assert [(b["first_line"], b["section"]) for b in report["blocks"]] == [
        ("### 2026-10-16 — foreign entry", "Recent"),
        ("### 2026-10-16 — own entry", "Recent"),
    ]


def test_stages_only_the_selected_block(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    own = _ids(repo, capsys)["### 2026-10-16 — own entry"]
    code, report = _run(repo, capsys, "--path", KD, "--blocks", own)
    assert code == 0
    assert report["action"] == "staged"
    assert _git(repo, "show", f":{KD}") == BASE.replace("## Recent\n\n", "## Recent\n\n" + OWN)


def test_working_tree_is_untouched_and_foreign_entry_stays_unstaged(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    own = _ids(repo, capsys)["### 2026-10-16 — own entry"]
    _run(repo, capsys, "--path", KD, "--blocks", own)
    assert (repo / KD).read_text(encoding="utf-8") == DIRTY
    added = [line for line in _git(repo, "diff", "--", KD).splitlines() if line.startswith("+")]
    assert "+### 2026-10-16 — foreign entry" in added
    assert "+### 2026-10-16 — own entry" not in added


def test_refuses_when_the_path_already_has_staged_changes(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    own = _ids(repo, capsys)["### 2026-10-16 — own entry"]
    _git(repo, "add", KD)
    before = _git(repo, "ls-files", "-s", KD)
    code, report = _run(repo, capsys, "--path", KD, "--blocks", own)
    assert code == 1
    assert report["action"] == "refused"
    assert _git(repo, "ls-files", "-s", KD) == before


def test_refuses_an_unknown_block_id_without_staging(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, report = _run(repo, capsys, "--path", KD, "--blocks", "deadbeef")
    assert code == 1
    assert "deadbeef" in report["reason"]
    assert _git(repo, "diff", "--cached", "--name-only") == ""


def test_other_paths_in_the_index_are_untouched(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (repo / "other.md").write_text("other edited\n", encoding="utf-8")
    _git(repo, "add", "other.md")
    own = _ids(repo, capsys)["### 2026-10-16 — own entry"]
    _run(repo, capsys, "--path", KD, "--blocks", own)
    assert sorted(_git(repo, "diff", "--cached", "--name-only").splitlines()) == [KD, "other.md"]
    assert _git(repo, "show", ":other.md") == "other edited\n"


def test_untracked_file_can_be_staged_partially(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    new = "notes/new.md"
    (repo / "notes").mkdir()
    (repo / new).write_text("- mine\n- theirs\n", encoding="utf-8")
    mine = _ids(repo, capsys, new)["- mine"]
    code, _ = _run(repo, capsys, "--path", new, "--blocks", mine)
    assert code == 0
    assert _git(repo, "show", f":{new}") == "- mine\n"


def test_executable_mode_is_kept(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (repo / KD).write_text(BASE, encoding="utf-8")
    _git(repo, "update-index", "--chmod=+x", KD)
    _git(repo, "commit", "-q", "-m", "exec")
    (repo / KD).write_text(DIRTY, encoding="utf-8")
    own = _ids(repo, capsys)["### 2026-10-16 — own entry"]
    _run(repo, capsys, "--path", KD, "--blocks", own)
    assert _git(repo, "ls-files", "-s", KD).startswith("100755 ")


def test_requires_list_or_blocks(repo: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--vault", str(repo), "--path", KD])
    assert exc.value.code == 2
