"""The gate must resolve every committed teeth spec's anchors on every run.

A detector-teeth-check spec anchors each mutant on an exact source string, so
an unrelated refactor of the code under test can desync it without anything
going red: the spec just stops being runnable, and nobody learns that until
the next full mutation run. In #941 an unrelated edit staled two anchors while
`make test` stayed green; only a hand-run `--check-anchors` caught them.

These tests drive the gate step against throwaway git repos, so each property
is shown against a spec whose anchors are known to resolve or known not to.
"""

import json
import re
import subprocess
from pathlib import Path
from typing import Callable

import pytest

from scripts.check_teeth_anchors import find_specs, main

REPO_ROOT = Path(__file__).resolve().parents[1]

_SOURCE = "def is_ready(state: str) -> bool:\n    return state == 'ready'\n"


def _git_repo(root: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    return root


def _track(repo: Path, *paths: str) -> None:
    subprocess.run(["git", "add", "--", *paths], cwd=repo, check=True)


def _write_spec(path: Path, *, file: str, find: str) -> None:
    """Write a one-mutant spec anchoring *find* in *file* (relative to the spec)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "test_command": ["python", "-m", "pytest", "-q"],
                "mutants": [
                    {
                        "label": "readiness check always passes",
                        "file": file,
                        "find": find,
                        "replace": "return True",
                        "oracle": "real",
                    }
                ],
            }
        )
    )


def _write_source(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_SOURCE)


def test_passes_when_every_tracked_anchor_resolves(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _git_repo(tmp_path)
    _write_source(repo / "tool/ready.py")
    _write_spec(
        repo / "tool/tests/ready.teeth.json",
        file="../ready.py",
        find="return state == 'ready'",
    )
    _track(repo, "tool")

    assert main([str(repo)]) == 0
    assert "tool/tests/ready.teeth.json" in capsys.readouterr().out


def test_fails_naming_the_spec_and_mutant_whose_anchor_went_stale(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The #941 shape: the source moved on, the spec still quotes the old line."""
    repo = _git_repo(tmp_path)
    _write_source(repo / "tool/ready.py")
    _write_spec(
        repo / "tool/tests/ready.teeth.json",
        file="../ready.py",
        find="return state == 'READY'",
    )
    _track(repo, "tool")

    assert main([str(repo)]) == 1
    out = capsys.readouterr()
    report = out.out + out.err
    assert "tool/tests/ready.teeth.json" in report
    assert "readiness check always passes" in report


def test_checks_machinery_style_specs_relative_to_their_own_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`teeth-spec-*.json` is the second naming convention, and its paths are spec-relative.

    The machinery spec sits beside `engine/` and runs its suite from its own
    directory, so a gate that resolved `file` against the repo root would
    report every one of its anchors missing — or, worse, never find the spec
    and pass without checking it. Only a spec that was found AND resolved
    against its own directory is reported `ok`.
    """
    repo = _git_repo(tmp_path)
    _write_source(repo / "machinery/engine/ready.py")
    _write_spec(
        repo / "machinery/teeth-spec-ready.json",
        file="engine/ready.py",
        find="return state == 'ready'",
    )
    _track(repo, "machinery")

    assert main([str(repo)]) == 0
    out = capsys.readouterr().out
    assert re.search(r"^ok\s+machinery/teeth-spec-ready\.json$", out, re.MULTILINE), out


@pytest.mark.parametrize(
    ("spec_file", "mutate_spec"),
    [
        pytest.param("../deleted.py", None, id="target-file-deleted"),
        pytest.param("../ready.py", lambda m: m.pop("oracle"), id="spec-refused"),
    ],
)
def test_a_spec_the_checker_cannot_read_fails_the_gate(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    spec_file: str,
    mutate_spec: Callable[[dict], object] | None,
) -> None:
    """A spec whose target is gone or that is refused has no resolvable anchors either.

    A deleted target file is reported as that row's error; a malformed spec
    is refused on stderr with no JSON verdict at all. The gate must read both
    as failures of that spec — never as a crash of its own, and never as an
    empty (so clean) list of stale anchors.
    """
    repo = _git_repo(tmp_path)
    _write_source(repo / "tool/ready.py")
    spec = repo / "tool/tests/ready.teeth.json"
    _write_spec(spec, file=spec_file, find="return state == 'ready'")
    if mutate_spec is not None:
        data = json.loads(spec.read_text())
        mutate_spec(data["mutants"][0])
        spec.write_text(json.dumps(data))
    _track(repo, "tool")

    assert main([str(repo)]) == 1
    assert "STALE tool/tests/ready.teeth.json" in capsys.readouterr().out


def test_finding_no_specs_fails_rather_than_passing_vacuously(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Checking zero specs proves nothing, and this repo always commits some.

    An empty result means discovery broke — a mistyped pathspec, a rename of
    the naming convention — and a gate that reported that as green would go
    on checking nothing, forever, without anyone noticing.
    """
    repo = _git_repo(tmp_path)
    _write_source(repo / "tool/ready.py")
    _track(repo, "tool")

    assert main([str(repo)]) == 1
    assert "no teeth specs found" in capsys.readouterr().err


def test_untracked_specs_are_not_checked(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Only committed specs gate a merge; a stray local one must not.

    Discovery goes through the index, not the filesystem. A tree walk from the
    main checkout would also descend into `.claude/worktrees/`, and fail this
    branch on whatever state another session's worktree happens to be in.
    """
    repo = _git_repo(tmp_path)
    _write_source(repo / "tool/ready.py")
    _write_spec(
        repo / "tool/tests/ready.teeth.json",
        file="../ready.py",
        find="return state == 'ready'",
    )
    _track(repo, "tool")
    _write_spec(
        repo / "scratch/draft.teeth.json",
        file="../tool/ready.py",
        find="return state == 'READY'",
    )

    assert main([str(repo)]) == 0
    assert "scratch/draft.teeth.json" not in capsys.readouterr().out


def test_discovers_this_repos_specs_under_both_naming_conventions() -> None:
    specs = {p.relative_to(REPO_ROOT).as_posix() for p in find_specs(REPO_ROOT)}
    assert "plugins/workbench/machinery/teeth-spec-link-advisory.json" in specs
    assert (
        "plugins/workbench/skills/detector-teeth-check/scripts/tests/teeth_check.teeth.json"
        in specs
    )
