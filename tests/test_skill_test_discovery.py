"""The skill-script test gate must auto-discover every suite, not a hand list."""

import subprocess
from pathlib import Path

import pytest

from scripts import discover_skill_test_suites
from scripts.discover_skill_test_suites import find_suites, main

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


def _make_suite(root: Path, name: str) -> Path:
    scripts = root / f"plugins/demo-plugin/skills/{name}/scripts"
    (scripts / "tests").mkdir(parents=True)
    (scripts / "tests" / "test_thing.py").write_text("def test_ok() -> None:\n    pass\n")
    return scripts


def _stub_run(monkeypatch: pytest.MonkeyPatch, failing: set[str]) -> list[Path]:
    """Replace subprocess.run; suites whose dir name is in *failing* exit 1."""
    calls: list[Path] = []

    def fake_run(cmd: list[str], cwd: Path, check: bool) -> subprocess.CompletedProcess[str]:
        calls.append(Path(cwd))
        code = 1 if Path(cwd).parent.name in failing else 0
        return subprocess.CompletedProcess(cmd, code)

    monkeypatch.setattr(discover_skill_test_suites.subprocess, "run", fake_run)
    return calls


def test_main_returns_0_and_runs_nothing_when_no_suites(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls = _stub_run(monkeypatch, set())

    assert main([str(tmp_path)]) == 0
    assert calls == []
    assert "no skill-script test suites found" in capsys.readouterr().out


def test_main_returns_0_when_every_suite_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _make_suite(tmp_path, "alpha")
    second = _make_suite(tmp_path, "beta")
    calls = _stub_run(monkeypatch, set())

    assert main([str(tmp_path)]) == 0
    assert calls == [first, second]


def test_main_returns_1_and_names_only_the_failing_suite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _make_suite(tmp_path, "alpha")
    _make_suite(tmp_path, "beta")
    calls = _stub_run(monkeypatch, {"beta"})

    assert main([str(tmp_path)]) == 1
    assert len(calls) == 2  # a failure does not stop later suites from running
    err = capsys.readouterr().err
    assert "plugins/demo-plugin/skills/beta/scripts" in err
    assert "skills/alpha/scripts" not in err
