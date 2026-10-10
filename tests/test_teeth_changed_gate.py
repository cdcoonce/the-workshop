"""The gate must RUN every teeth spec whose inputs changed, not just resolve its anchors.

`check-teeth-anchors` proves each mutant's anchor still matches exactly one
site. It cannot see an anchor that drifted onto a *different* site whose text
happens to match: the spec stays runnable, the mutant quietly stops being
killed, and nothing goes red until a human runs the spec by hand. In #1147
(PR #1135) a split of `_subst` left the `$( )` substitution mutant anchored on
the process-substitution fallback, which no test covered; it survived for a
day with every gate green.

The only evidence that a mutant still dies is running it. These tests drive
`scripts.check_teeth_changed` against throwaway git repos: a spec is selected
when its own file, a mutation target, or a test file it runs changed since
the base ref, and a selected spec is run in full with the real runner, so a
survivor fails the gate.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import check_teeth_anchors
from scripts.check_teeth_changed import main, select_specs

REPO_ROOT = Path(__file__).resolve().parents[1]

_SOURCE = (
    "def is_ready(state: str) -> bool:\n"
    "    return state == 'ready'\n"
    "\n"
    "\n"
    "def is_done(state: str) -> bool:\n"
    "    return state == 'done'\n"
)

# Covers is_ready only. A mutant on is_done's body resolves fine and survives:
# the #1147 shape, an anchor on a site no test grades.
def _tests(source_dir: str = ".") -> str:
    """A test module importing `ready` from *source_dir*, relative to the tests' parent."""
    return (
        "import sys\n"
        "from pathlib import Path\n"
        f"sys.path.insert(0, str(Path(__file__).resolve().parents[1] / {source_dir!r}))\n"
        "from ready import is_ready\n"
        "\n"
        "\n"
        "def test_ready_state_is_ready() -> None:\n"
        "    assert is_ready('ready')\n"
        "    assert not is_ready('done')\n"
    )

_READY_ANCHOR = "return state == 'ready'"
_DONE_ANCHOR = "return state == 'done'"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def _git_repo(root: Path) -> Path:
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    return root


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD").strip()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _spec(test_file: str, *, file: str, find: str, label: str = "state check always passes") -> str:
    """A one-mutant spec; *test_file* is relative to the directory the spec runs from."""
    return json.dumps(
        {
            "test_command": [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                test_file,
            ],
            "mutants": [
                {
                    "label": label,
                    "file": file,
                    "find": find,
                    "replace": "return True",
                    "oracle": "real",
                }
            ],
        }
    )


def _tool_repo(root: Path, *, anchor: str) -> Path:
    """A repo with `tool/ready.py`, a test for is_ready, and a spec anchored on *anchor*."""
    repo = _git_repo(root)
    _write(repo / "tool/ready.py", _SOURCE)
    _write(repo / "tool/tests/test_ready.py", _tests())
    _write(
        repo / "tool/tests/ready.teeth.json",
        _spec("tool/tests/test_ready.py", file="../ready.py", find=anchor),
    )
    _write(repo / "README.md", "unrelated\n")
    return repo


def _touch_source(repo: Path) -> None:
    """An edit that keeps every anchor resolving — the drift's outward shape."""
    path = repo / "tool/ready.py"
    path.write_text("# refactored\n" + path.read_text())


@pytest.mark.parametrize(
    ("edit", "selected"),
    [
        pytest.param("tool/ready.py", True, id="mutation-target-changed"),
        pytest.param("tool/tests/ready.teeth.json", True, id="spec-itself-changed"),
        pytest.param("tool/tests/test_ready.py", True, id="test-file-changed"),
        pytest.param("README.md", False, id="unrelated-file-changed"),
    ],
)
def test_selects_a_spec_when_one_of_its_inputs_changed_since_base(
    tmp_path: Path, edit: str, selected: bool
) -> None:
    """A spec's inputs are its own file, its mutation targets and the tests it runs.

    A changed test file is an input too: deleting the one test that kills a
    mutant is the other way a tooth goes quietly, and the anchor gate cannot
    see that either.
    """
    repo = _tool_repo(tmp_path, anchor=_READY_ANCHOR)
    base = _commit(repo, "base")
    path = repo / edit
    path.write_text(path.read_text() + "\n")
    _commit(repo, "edit")

    chosen = {spec.relative_to(repo).as_posix() for spec, _ in select_specs(repo, base)}
    assert ("tool/tests/ready.teeth.json" in chosen) is selected


def test_a_changed_file_under_a_test_directory_argument_selects_the_spec(
    tmp_path: Path,
) -> None:
    """Skill-script specs name their tests DIRECTORY; a file beneath it is an input."""
    repo = _tool_repo(tmp_path, anchor=_READY_ANCHOR)
    spec = repo / "tool/tests/ready.teeth.json"
    spec.write_text(_spec("tool/tests", file="../ready.py", find=_READY_ANCHOR))
    base = _commit(repo, "base")
    path = repo / "tool/tests/test_ready.py"
    path.write_text(path.read_text() + "\n")
    _commit(repo, "edit a test")

    chosen = {s.relative_to(repo).as_posix() for s, _ in select_specs(repo, base)}
    assert chosen == {"tool/tests/ready.teeth.json"}


def test_files_the_base_moved_are_not_this_branchs_changes(tmp_path: Path) -> None:
    """The change set is the diff from the MERGE-BASE, not from the base's tip.

    A branch behind its base would otherwise be charged for every spec input
    the base touched since the branch point, and run specs this change cannot
    have affected — on a repo where a third of merges touch one.
    """
    repo = _tool_repo(tmp_path, anchor=_READY_ANCHOR)
    fork = _commit(repo, "fork point")
    _git(repo, "checkout", "-q", "-b", "feature")
    (repo / "README.md").write_text("docs only\n")
    _commit(repo, "docs")
    _git(repo, "checkout", "-q", "main")
    _touch_source(repo)
    _commit(repo, "base moves the classifier")
    _git(repo, "checkout", "-q", "feature")

    assert select_specs(repo, "main") == []
    assert select_specs(repo, fork) == []


def test_an_uncommitted_edit_to_an_input_selects_the_spec(tmp_path: Path) -> None:
    """Locally the gate runs before the commit; the working tree is the change set."""
    repo = _tool_repo(tmp_path, anchor=_READY_ANCHOR)
    base = _commit(repo, "base")
    _touch_source(repo)

    chosen = {spec.relative_to(repo).as_posix() for spec, _ in select_specs(repo, base)}
    assert chosen == {"tool/tests/ready.teeth.json"}


def test_a_drifted_anchor_that_still_resolves_fails_the_gate_as_a_survivor(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The #1147 shape: the anchor resolves, on a site no test covers.

    `check-teeth-anchors` passes this repo — that is the gap. The changed-
    inputs gate runs the spec, the mutant survives, and the failure names the
    spec and the mutant in full.
    """
    repo = _tool_repo(tmp_path, anchor=_DONE_ANCHOR)
    base = _commit(repo, "base")
    _touch_source(repo)
    _commit(repo, "refactor that keeps the anchor text present")

    assert check_teeth_anchors.main([str(repo)]) == 0, "precondition: anchor gate is blind here"
    capsys.readouterr()

    assert main(["--base", base, "--repo", str(repo)]) == 1
    out = capsys.readouterr()
    report = out.out + out.err
    assert "FAIL  tool/tests/ready.teeth.json" in report
    assert "state check always passes" in report
    assert "survived" in report


def test_passes_when_every_selected_mutant_is_killed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _tool_repo(tmp_path, anchor=_READY_ANCHOR)
    base = _commit(repo, "base")
    _touch_source(repo)
    _commit(repo, "refactor")

    assert main(["--base", base, "--repo", str(repo)]) == 0
    out = capsys.readouterr().out
    assert "RUN   tool/tests/ready.teeth.json" in out
    assert "tool/ready.py" in out, "the run names the input that selected the spec"
    assert "killed" in out


def test_runs_nothing_when_no_spec_input_changed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Most commits touch no spec input; the gate must cost nothing then.

    This is not a vacuous pass: `check-teeth-anchors` still resolves every
    spec on every run, and a spec whose inputs did not change cannot have
    lost a tooth since the base ref.
    """
    repo = _tool_repo(tmp_path, anchor=_DONE_ANCHOR)
    base = _commit(repo, "base")
    (repo / "README.md").write_text("still unrelated\n")
    _commit(repo, "docs")

    assert main(["--base", base, "--repo", str(repo)]) == 0
    out = capsys.readouterr().out
    assert "RUN" not in out
    assert "nothing to run" in out


def test_refuses_an_unresolvable_base_rather_than_reading_it_as_no_change(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A typo'd or unfetched base must not pass as "no inputs changed"."""
    repo = _tool_repo(tmp_path, anchor=_DONE_ANCHOR)
    _commit(repo, "base")

    assert main(["--base", "origin/nowhere", "--repo", str(repo)]) == 2
    err = capsys.readouterr().err
    assert "origin/nowhere" in err
    assert "fetch" in err


def test_finding_no_specs_fails_rather_than_passing_vacuously(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _git_repo(tmp_path)
    _write(repo / "tool/ready.py", _SOURCE)
    base = _commit(repo, "base")

    assert main(["--base", base, "--repo", str(repo)]) == 1
    assert "no teeth specs found" in capsys.readouterr().err


def test_a_machinery_style_spec_runs_from_its_own_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`teeth-spec-*.json` beside `engine/` runs its suite from its own directory.

    Its test command names `tests/...` relative to that directory, so a run
    from the repo root would find no tests, go red on the baseline, and the
    gate would fail a spec whose mutant is in fact killed.
    """
    repo = _git_repo(tmp_path)
    _write(repo / "machinery/engine/ready.py", _SOURCE)
    _write(repo / "machinery/tests/test_ready.py", _tests("engine"))
    _write(
        repo / "machinery/teeth-spec-ready.json",
        _spec("tests/test_ready.py", file="engine/ready.py", find=_READY_ANCHOR),
    )
    base = _commit(repo, "base")
    path = repo / "machinery/engine/ready.py"
    path.write_text("# refactored\n" + path.read_text())
    _commit(repo, "refactor")

    assert main(["--base", base, "--repo", str(repo)]) == 0
    out = capsys.readouterr().out
    assert "RUN   machinery/teeth-spec-ready.json" in out
    assert "killed" in out


def test_a_skill_spec_naming_a_bare_tests_directory_runs_from_its_own_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A bare `tests` argument means the spec's own `tests/`, not the root's.

    Both exist. Run from the root, the mutants in `scripts/tool.py` would be
    scored against the root suite, which never imports them, and every one
    would read as a survivor — a false FAIL on a spec whose teeth are fine.
    """
    repo = _git_repo(tmp_path)
    _write(repo / "tests/test_root.py", "def test_root() -> None:\n    assert True\n")
    _write(repo / "skill/scripts/ready.py", _SOURCE)
    _write(repo / "skill/scripts/tests/test_ready.py", _tests())
    _write(
        repo / "skill/scripts/ready.teeth.json",
        _spec("tests", file="ready.py", find=_READY_ANCHOR),
    )
    base = _commit(repo, "base")
    path = repo / "skill/scripts/ready.py"
    path.write_text("# refactored\n" + path.read_text())
    _commit(repo, "refactor")

    from scripts.check_teeth_changed import spec_cwd, spec_inputs

    spec = repo / "skill/scripts/ready.teeth.json"
    assert spec_cwd(spec, repo) == (repo / "skill/scripts").resolve()
    assert "skill/scripts/tests" in spec_inputs(spec, repo)
    assert main(["--base", base, "--repo", str(repo)]) == 0
    assert "killed" in capsys.readouterr().out


def test_this_repos_specs_each_resolve_every_path_argument_from_their_cwd() -> None:
    """Every committed spec's test command must find its files from the chosen cwd.

    Pins the three shapes in the tree: the harness specs run from the root,
    the machinery specs from `plugins/workbench/machinery/`, and the
    live-view skill's spec from its own `scripts/` (its command says `tests`).
    """
    from scripts.check_teeth_changed import _candidates, _path_args, spec_cwd

    expected = {
        "evals/_harness/tests/test_bash_allowlist.teeth.json": ".",
        "plugins/workbench/machinery/teeth-spec-link-advisory.json": "plugins/workbench/machinery",
        "plugins/workbench/skills/live-view-simulate-diff/scripts/sim_diff.teeth.json": (
            "plugins/workbench/skills/live-view-simulate-diff/scripts"
        ),
    }
    for spec in check_teeth_anchors.find_specs(REPO_ROOT):
        cwd = spec_cwd(spec, REPO_ROOT)
        doc = json.loads(spec.read_text())
        for arg in _path_args(doc, _candidates(spec, REPO_ROOT)):
            assert (cwd / arg).exists(), f"{spec}: {arg} not under {cwd}"
        rel = spec.relative_to(REPO_ROOT).as_posix()
        if rel in expected:
            assert cwd == (REPO_ROOT / expected[rel]).resolve(), rel


def test_list_mode_names_the_selection_and_runs_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _tool_repo(tmp_path, anchor=_DONE_ANCHOR)
    base = _commit(repo, "base")
    _touch_source(repo)

    assert main(["--base", base, "--repo", str(repo), "--list"]) == 0
    out = capsys.readouterr().out
    assert "tool/tests/ready.teeth.json" in out
    assert "tool/ready.py" in out
    assert "survived" not in out and "RUN" not in out


def test_this_repos_bash_classifier_specs_are_selected_by_their_shared_target() -> None:
    """The instance: every spec anchored in bash_classify.py fires on its change.

    Five sidecars under evals/_harness/tests anchor there. A selection keyed
    on the spec's own path alone would have run none of them for 59b680d8,
    which touched only the classifier (and one other spec).
    """
    from scripts.check_teeth_changed import spec_inputs

    specs = check_teeth_anchors.find_specs(REPO_ROOT)
    target = "evals/_harness/bash_classify.py"
    firing = {
        spec.relative_to(REPO_ROOT).as_posix()
        for spec in specs
        if target in spec_inputs(spec, REPO_ROOT)
    }
    assert "evals/_harness/tests/test_bash_allowlist.teeth.json" in firing
    assert len(firing) >= 5
