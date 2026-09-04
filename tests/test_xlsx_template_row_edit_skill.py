"""Ownership and boundary coverage for `xlsx-template-row-edit`.

The skill exists because two defects shipped past a green suite in the same
file, four weeks apart: a variance formula left pointing at pre-shift rows,
and a frame-bar fill dropped from the columns flanking the data range. Both
are invisible to value assertions because openpyxl never recalculates.

Like `gitlab-ci-watch`, it is script-backed so the mechanical verification
lives in one tested place rather than in prose discipline a reader can skip.
"""

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPOSITORY_ROOT / "plugins/workbench/skills/xlsx-template-row-edit"
SKILL_MD = SKILL_DIR / "SKILL.md"
SCRIPT = SKILL_DIR / "scripts/xlsx_cell_diff.py"


def _normalized(path: Path) -> str:
    return " ".join(path.read_text().split())


def test_skill_is_owned_by_workbench() -> None:
    """A data/reporting capability with a universal audience."""
    assert SKILL_MD.is_file()


def test_the_diff_script_ships_with_the_skill() -> None:
    """Prose alone already failed — a human read the binary diff and missed it."""
    assert SCRIPT.is_file()


def test_the_script_declares_its_dependency_inline() -> None:
    """It needs openpyxl, so it must run under `uv run --script`."""
    header = SCRIPT.read_text()[:400]
    assert "# /// script" in header
    assert "openpyxl" in header


def test_the_script_imports_without_openpyxl_installed() -> None:
    """The comparison logic is pure so the CI suite can test it.

    Skill-script suites run with only pytest and ruff injected, so a
    module-level `import openpyxl` would make the whole suite uncollectable.
    """
    import ast

    tree = ast.parse(SCRIPT.read_text())
    module_level = [
        node
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    imported = {
        alias.name.split(".")[0]
        for node in module_level
        for alias in getattr(node, "names", [])
    } | {
        node.module.split(".")[0]
        for node in module_level
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "openpyxl" not in imported


def test_skill_names_both_invisible_failure_modes() -> None:
    """The two defects are the reason the skill exists; neither may be dropped."""
    body = _normalized(SKILL_MD).lower()
    assert "never recalculates" in body
    assert "delete_rows" in body
    assert "translator" in body
    assert "fill" in body


def test_skill_defers_teeth_checking_rather_than_restating_it() -> None:
    """Mutation discipline is `detector-teeth-check`'s; don't fork it here."""
    assert "detector-teeth-check" in _normalized(SKILL_MD)
