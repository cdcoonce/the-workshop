"""The skill-script test gate must auto-discover every suite, not a hand list."""

from pathlib import Path

from scripts.discover_skill_test_suites import find_suites

REPO_ROOT = Path(__file__).resolve().parents[1]


def _on_disk_suites() -> set[Path]:
    """Every `.../scripts` dir whose `tests/` holds at least one test_*.py."""
    found: set[Path] = set()
    for base in ("plugins",):
        for tests_dir in (REPO_ROOT / base).rglob("scripts/tests"):
            if any(tests_dir.glob("test_*.py")):
                found.add(tests_dir.parent.resolve())
    return found


def test_discovers_known_suites() -> None:
    suites = {p.resolve() for p in find_suites(REPO_ROOT)}
    for name in ("daa-code-review", "transcript-notes", "mr-merge-order", "stale-artifact-sweep"):
        expected = (REPO_ROOT / "plugins/workbench/skills" / name / "scripts").resolve()
        assert expected in suites, f"{name} script suite not discovered"


def test_excludes_empty_scaffolding(tmp_path: Path) -> None:
    """A scripts/tests dir with no test files is not treated as a suite."""
    empty = tmp_path / "plugins/demo-plugin/skills/scaffolded/scripts"
    (empty / "tests").mkdir(parents=True)
    (empty / "tests" / "__init__.py").write_text("")
    real = tmp_path / "plugins/demo-plugin/skills/covered/scripts"
    (real / "tests").mkdir(parents=True)
    (real / "tests" / "test_thing.py").write_text("def test_ok() -> None:\n    assert True\n")

    suites = {p.resolve() for p in find_suites(tmp_path)}
    assert empty.resolve() not in suites
    assert real.resolve() in suites


def test_discovery_matches_disk_exactly() -> None:
    """No suite with real tests is ever silently missed by the gate."""
    assert {p.resolve() for p in find_suites(REPO_ROOT)} == _on_disk_suites()
