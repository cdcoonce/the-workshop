"""The vault sync target has one rule, held in three places that cannot drift.

``vault-sync`` and ``vault-wrap-up`` each ship ``scripts/sync_target.py`` so
every skill stays self-contained, and the engine's ``sync_manager`` -- vendored
into the vault on its own -- carries the rule inline. A copy that drifts
reintroduces the 2026-09-24 failure in exactly one path: a worktree session
whose pull, squash, replay, and push disagree about where its work goes.

The matrix runs every checkout shape the vault actually has -- the primary
checkout on ``main``, published feature branches, the desktop app's worktrees
on unpublished ``claude/*`` branches, Codex's detached worktrees -- against
real git, through both implementations.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKBENCH = REPO_ROOT / "plugins/workbench"
SKILL_COPIES = (
    WORKBENCH / "skills/vault-sync/scripts/sync_target.py",
    WORKBENCH / "skills/vault-wrap-up/scripts/sync_target.py",
)
ENGINE = WORKBENCH / "machinery/engine/sync_manager.py"


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses resolve their module during exec
    spec.loader.exec_module(module)
    return module


skill = _load("sync_target_under_test", SKILL_COPIES[0])
engine = _load("sync_manager_under_test", ENGINE)

Expected = tuple[str | None, str, str] | None


@pytest.fixture(autouse=True)
def _isolated_git(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both resolvers inherit the process environment; keep the developer's
    global git config (default branch, hooks, signing) out of the answer."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for key in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(key, "Test")
    for key in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(key, "test@example.com")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _vault(tmp_path: Path) -> tuple[Path, Path]:
    """Bare remote plus the primary checkout on main, tracking origin/main."""
    remote = tmp_path / "remote.git"
    remote.mkdir()
    _git(remote, "init", "-q", "--bare", "-b", "main")
    local = tmp_path / "vault"
    _git(tmp_path, "clone", "-q", str(remote), str(local))
    _git(local, "symbolic-ref", "HEAD", "refs/heads/main")
    (local / "seed.md").write_text("seed\n", encoding="utf-8")
    _git(local, "add", "seed.md")
    _git(local, "commit", "-q", "-m", "seed")
    _git(local, "push", "-q", "-u", "origin", "main")
    return remote, local


def _primary_checkout(tmp_path: Path) -> tuple[Path, Expected]:
    _remote, local = _vault(tmp_path)
    return local, ("main", "main", "upstream")


def _published_feature_branch_without_upstream(tmp_path: Path) -> tuple[Path, Expected]:
    _remote, local = _vault(tmp_path)
    _git(local, "switch", "-q", "-c", "feat/gardener")
    _git(local, "push", "-q", "origin", "feat/gardener")
    return local, ("feat/gardener", "feat/gardener", "same-name")


def _desktop_worktree(tmp_path: Path) -> tuple[Path, Expected]:
    _remote, local = _vault(tmp_path)
    worktree = tmp_path / "wt"
    _git(local, "worktree", "add", "-q", "-b", "claude/clever-benz", str(worktree), "main")
    return worktree, ("claude/clever-benz", "main", "remote-default")


def _worktree_tracking_origin_main(tmp_path: Path) -> tuple[Path, Expected]:
    _remote, local = _vault(tmp_path)
    worktree = tmp_path / "wt"
    _git(
        local, "worktree", "add", "-q", "--track", "-b", "claude/tracked",
        str(worktree), "origin/main",
    )
    return worktree, ("claude/tracked", "main", "upstream")


def _worktree_tracking_published_feature_branch(tmp_path: Path) -> tuple[Path, Expected]:
    _remote, local = _vault(tmp_path)
    _git(local, "push", "-q", "origin", "main:feat/gardener")
    _git(local, "fetch", "-q", "origin")
    worktree = tmp_path / "wt"
    _git(
        local, "worktree", "add", "-q", "--track", "-b", "claude/on-feature",
        str(worktree), "origin/feat/gardener",
    )
    return worktree, ("claude/on-feature", "feat/gardener", "upstream")


def _detached_worktree(tmp_path: Path) -> tuple[Path, Expected]:
    _remote, local = _vault(tmp_path)
    worktree = tmp_path / "wt"
    _git(local, "worktree", "add", "-q", "--detach", str(worktree), "main")
    return worktree, (None, "main", "remote-default")


def _remote_default_is_not_main(tmp_path: Path) -> tuple[Path, Expected]:
    remote, local = _vault(tmp_path)
    _git(local, "push", "-q", "origin", "main:trunk")
    _git(remote, "symbolic-ref", "HEAD", "refs/heads/trunk")
    worktree = tmp_path / "wt"
    _git(local, "worktree", "add", "-q", "-b", "claude/on-trunk", str(worktree), "main")
    return worktree, ("claude/on-trunk", "trunk", "remote-default")


def _unreachable_remote(tmp_path: Path) -> tuple[Path, Expected]:
    _remote, local = _vault(tmp_path)
    worktree = tmp_path / "wt"
    _git(local, "worktree", "add", "-q", "-b", "claude/offline", str(worktree), "main")
    _git(local, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    return worktree, None


def _remote_names_no_default(tmp_path: Path) -> tuple[Path, Expected]:
    remote, local = _vault(tmp_path)
    _git(remote, "symbolic-ref", "HEAD", "refs/heads/unborn")
    worktree = tmp_path / "wt"
    _git(local, "worktree", "add", "-q", "-b", "claude/adrift", str(worktree), "main")
    return worktree, None


CASES: dict[str, Callable[[Path], tuple[Path, Expected]]] = {
    "primary checkout on main": _primary_checkout,
    "published feature branch, no upstream": _published_feature_branch_without_upstream,
    "desktop worktree on unpublished claude/* branch": _desktop_worktree,
    "worktree branch tracking origin/main": _worktree_tracking_origin_main,
    "session branch tracking a published feature branch": _worktree_tracking_published_feature_branch,
    "detached worktree (Codex)": _detached_worktree,
    "remote default branch is not main": _remote_default_is_not_main,
    "unreachable remote": _unreachable_remote,
    "remote names no default branch": _remote_names_no_default,
}


def _skill_answer(checkout: Path) -> Expected:
    try:
        found = skill.resolve("origin", cwd=checkout)
    except skill.UnresolvedTarget:
        return None
    return (found.branch, found.target, found.source)


def _engine_answer(checkout: Path) -> Expected:
    found = engine._sync_target(checkout)
    return None if found is None else (found.branch, found.target, found.source)


def test_skill_copies_of_sync_target_are_byte_identical() -> None:
    first, second = (path.read_bytes() for path in SKILL_COPIES)
    assert first == second, (
        "the vault-sync and vault-wrap-up copies of sync_target.py differ; "
        "edit one and copy it over the other"
    )


@pytest.mark.parametrize("case", list(CASES))
def test_skill_and_engine_resolve_the_same_sync_target(tmp_path: Path, case: str) -> None:
    checkout, expected = CASES[case](tmp_path)

    assert _skill_answer(checkout) == expected, f"skill sync_target.py: {case}"
    assert _engine_answer(checkout) == expected, f"engine sync_manager: {case}"
