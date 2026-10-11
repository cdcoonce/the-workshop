"""The shared-tree-safety recipe for advancing a checked-out branch must keep the index.

``git reset --keep`` preserves working-tree files but resets the index, so a
staged rename in another session's tree comes back as an unstaged delete plus an
untracked file. The skill documents a recipe that snapshots the index, resets,
re-applies the cached patch, and verifies ``git status --porcelain`` matches.

This test does not match prose. It extracts the recipe's fenced bash block from
``SKILL.md`` and executes it against a scratch repo holding a staged rename and an
unstaged edit, so deleting or weakening a step in the doc turns it red (#983).
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL = REPO_ROOT / "plugins/workbench/skills/shared-tree-safety/SKILL.md"
COMMAND_MD = REPO_ROOT / "plugins/workbench/skills/vault-sync/references/command.md"
HEADING = "## Advancing a branch checked out in a shared tree"

_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
}


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=check, env=_ENV
    )


def _section() -> str:
    text = SKILL.read_text(encoding="utf-8")
    assert HEADING in text, f"SKILL.md has no {HEADING!r} section"
    body = text.split(HEADING, 1)[1]
    return re.split(r"^## ", body, maxsplit=1, flags=re.M)[0]


def _recipe() -> str:
    """The first fenced bash block in the section: the index-preserving reset."""
    match = re.search(r"```bash\n(.*?)```", _section(), flags=re.S)
    assert match, "the section has no fenced bash recipe"
    return match.group(1)


@pytest.fixture
def scenario(tmp_path: Path) -> Path:
    """A clone whose local main diverged from origin/main, with a live staged rename.

    Local main holds a pre-rebase commit whose content was re-landed upstream as a
    different commit, so a fast-forward is impossible but nothing is lost by a reset.
    """
    origin = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(seed)], check=True)
    for name, body in (("a.md", "alpha\n"), ("b.md", "bravo\n")):
        (seed / name).write_text(body)
    _git(seed, "add", ".")
    _git(seed, "commit", "-q", "-m", "base")
    _git(seed, "remote", "add", "origin", str(origin))
    _git(seed, "push", "-q", "origin", "main")

    work = tmp_path / "work"
    subprocess.run(["git", "clone", "-q", str(origin), str(work)], check=True)
    (work / "c.md").write_text("charlie\n")
    _git(work, "add", "c.md")
    _git(work, "commit", "-q", "-m", "pre-rebase copy of c")

    (seed / "c.md").write_text("charlie\n")
    _git(seed, "add", "c.md")
    _git(seed, "commit", "-q", "-m", "c, re-landed upstream")
    (seed / "d.md").write_text("delta\n")
    _git(seed, "add", "d.md")
    _git(seed, "commit", "-q", "-m", "more upstream")
    _git(seed, "push", "-q", "origin", "main")
    _git(work, "fetch", "-q", "origin")

    # The other live session's state: a staged rename plus an unstaged edit.
    _git(work, "mv", "a.md", "renamed.md")
    (work / "b.md").write_text("bravo, edited\n")
    return work


def _porcelain(repo: Path) -> str:
    return _git(repo, "status", "--porcelain").stdout


def test_ff_only_refuses_the_diverged_branch_and_touches_nothing(scenario: Path) -> None:
    before = _porcelain(scenario)
    head = _git(scenario, "rev-parse", "HEAD").stdout
    result = _git(scenario, "merge", "--ff-only", "origin/main", check=False)
    assert result.returncode != 0
    assert _porcelain(scenario) == before
    assert _git(scenario, "rev-parse", "HEAD").stdout == head


def test_bare_reset_keep_drops_the_staged_rename(scenario: Path) -> None:
    """The hazard itself: confirms the scenario really loses the index without the recipe."""
    before = _porcelain(scenario)
    assert "R  a.md -> renamed.md" in before
    _git(scenario, "reset", "--keep", "origin/main")
    after = _porcelain(scenario)
    assert after != before
    assert " D a.md" in after and "?? renamed.md" in after


def test_recipe_ends_with_an_identical_porcelain_snapshot(scenario: Path) -> None:
    before = _porcelain(scenario)
    result = subprocess.run(
        ["bash", "-e", "-c", _recipe()],
        cwd=scenario,
        capture_output=True,
        text=True,
        env={**_ENV, "TARGET": "origin/main"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert _porcelain(scenario) == before
    # The branch really advanced onto the target.
    assert _git(scenario, "rev-parse", "HEAD").stdout == _git(scenario, "rev-parse", "origin/main").stdout
    assert (scenario / "d.md").is_file()


def test_recipe_hands_back_when_the_snapshot_does_not_match(scenario: Path) -> None:
    """A recipe that cannot restore the index must exit nonzero, not report success."""
    broken = _recipe().replace("git apply --cached", "git apply --cached --check")
    result = subprocess.run(
        ["bash", "-e", "-c", broken],
        cwd=scenario,
        capture_output=True,
        text=True,
        env={**_ENV, "TARGET": "origin/main"},
    )
    assert result.returncode != 0


def test_the_section_names_ff_only_first_and_forbids_bare_reset() -> None:
    section = _section()
    assert "git merge --ff-only" in section
    assert section.index("git merge --ff-only") < section.index("git reset --keep")
    assert re.search(r"[Nn]ever .*bare .*reset", section)


def test_vault_sync_points_at_the_recipe() -> None:
    text = COMMAND_MD.read_text(encoding="utf-8")
    assert "shared-tree-safety" in text
    assert "Advancing a branch checked out in a shared tree" in text
