"""Contract for the shared `assert_sole_owner` skill-ownership helper."""

from pathlib import Path

import pytest

from tests.conftest import assert_sole_owner


def _ship(root: Path, plugin: str, slug: str) -> None:
    skill = root / "plugins" / plugin / "skills" / slug
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("x\n")


def test_passes_when_exactly_one_plugin_ships_the_slug(tmp_path: Path) -> None:
    _ship(tmp_path, "alpha", "demo")
    assert_sole_owner(tmp_path, "demo")


def test_fails_when_two_plugins_ship_the_slug(tmp_path: Path) -> None:
    _ship(tmp_path, "alpha", "demo")
    _ship(tmp_path, "beta", "demo")
    with pytest.raises(AssertionError, match="shipped by 2 plugins"):
        assert_sole_owner(tmp_path, "demo")


def test_fails_when_no_plugin_ships_the_slug(tmp_path: Path) -> None:
    with pytest.raises(AssertionError, match="shipped by 0 plugins"):
        assert_sole_owner(tmp_path, "demo")


def test_ignores_a_copy_under_a_worktrees_path_segment(tmp_path: Path) -> None:
    _ship(tmp_path, "alpha", "demo")
    _ship(tmp_path, "worktrees", "demo")
    assert_sole_owner(tmp_path, "demo")


def test_worktree_filter_is_relative_to_the_repo_root(tmp_path: Path) -> None:
    # A repo that itself lives under a directory named "worktrees" is still a
    # repo: only parts below the root count.
    root = tmp_path / "worktrees" / "repo"
    _ship(root, "alpha", "demo")
    assert_sole_owner(root, "demo")


def test_a_near_named_slug_is_not_the_same_skill(tmp_path: Path) -> None:
    _ship(tmp_path, "alpha", "demo")
    _ship(tmp_path, "beta", "demo-extra")
    assert_sole_owner(tmp_path, "demo")


@pytest.mark.parametrize(
    "test_file", ["test_drill_me_skill.py", "test_using_workflow_skill.py"]
)
def test_skill_contract_call_sites_really_call_the_helper(test_file: str) -> None:
    import ast

    tree = ast.parse((Path(__file__).parent / test_file).read_text(encoding="utf-8"))
    calls = [
        n
        for fn in ast.walk(tree)
        if isinstance(fn, ast.FunctionDef) and fn.name.startswith("test_")
        for n in ast.walk(fn)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "assert_sole_owner"
    ]
    assert calls, f"{test_file} no longer calls assert_sole_owner from a test"
