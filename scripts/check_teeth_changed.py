"""Run every committed detector-teeth-check spec whose inputs changed since a base ref.

``check_teeth_anchors`` proves each mutant's anchor still resolves to exactly
one site. It cannot see an anchor that drifted onto a *different* site whose
text happens to match: the spec stays runnable, the mutant quietly stops
being killed, and nothing goes red until a human runs the spec by hand. The
runner's own ``--changed-since`` keys on edits to the spec's rows, so a
refactor of the code under test that leaves the spec untouched is invisible
to it too. In #1147 (PR #1135) a split of ``_subst`` left the ``$( )``
substitution mutant anchored on the process-substitution fallback, which no
test covered; it survived with every gate green.

The only evidence that a mutant still dies is running it. A full run of every
spec is minutes of mutant pytest runs, so this gate runs only the specs a
change can have affected — those whose own file, whose mutation target
file(s), or whose test file(s) differ from the merge-base with ``--base`` —
and runs each of those in full. Two thirds of merged commits touch no spec
input and pay nothing; the rest pay for the specs they could have broken.

A spec runs from the directory its test command's paths resolve against (the
repo root for most, ``plugins/workbench/machinery/`` for its own), so the
same resolution picks the spec's cwd and the test files that count as inputs.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from scripts.check_teeth_anchors import find_specs

_REPO_ROOT = Path(__file__).resolve().parents[1]
_TEETH_CHECK = _REPO_ROOT / "plugins/workbench/skills/detector-teeth-check/scripts/teeth_check.py"


class BaseUnresolvable(Exception):
    """``--base`` names no commit in this repository."""


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True, check=False
    )


def changed_paths(repo: Path, base: str) -> set[str]:
    """Repo-relative paths that differ between the working tree and the merge-base with *base*.

    The merge-base, not *base* itself: a branch behind its base would
    otherwise report every file the base moved since the branch point, and
    run specs this change cannot have affected. The working tree, not HEAD:
    locally the gate runs before the commit, and in CI the two agree.

    Parameters
    ----------
    repo : Path
        Root of the git working tree.
    base : str
        A git revision (``origin/dev`` in this repo's gate).

    Returns
    -------
    set[str]
        Added, modified, deleted or renamed tracked paths, POSIX-relative to
        *repo*.

    Raises
    ------
    BaseUnresolvable
        When *base* is not a commit here. Refused rather than read as "no
        change": an unfetched base would otherwise pass every spec unrun.
    """
    resolved = _git(repo, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}")
    if resolved.returncode != 0:
        raise BaseUnresolvable(
            f"base ref {base!r} not found. CI must check out enough history to "
            "resolve it (actions/checkout defaults to depth 1); locally, fetch it."
        )
    merge_base = _git(repo, "merge-base", base, "HEAD")
    if merge_base.returncode != 0:
        raise BaseUnresolvable(
            f"base ref {base!r} shares no history with HEAD: {merge_base.stderr.strip()}"
        )
    listed = _git(repo, "diff", "--name-only", "-z", merge_base.stdout.strip())
    if listed.returncode != 0:
        raise BaseUnresolvable(f"git diff against {base!r} failed: {listed.stderr.strip()}")
    return {path for path in listed.stdout.split("\0") if path}


def _load(spec: Path) -> dict:
    return json.loads(spec.read_text(encoding="utf-8"))


def _candidates(spec: Path, repo: Path) -> list[Path]:
    """The spec's own directory, its ancestors inside *repo*, then *repo* — nearest first."""
    root = repo.resolve()
    candidates = []
    directory = spec.resolve().parent
    while directory != root and root in directory.parents:
        candidates.append(directory)
        directory = directory.parent
    candidates.append(root)
    return candidates


def _path_args(doc: dict, candidates: list[Path]) -> list[str]:
    """Arguments of the spec's commands that name a path.

    An argument with a slash is a path. A bare word is one too when it exists
    under any candidate directory — ``tests`` in a skill spec that runs from
    its own ``scripts/`` — since ``uv``, ``python`` and ``-q`` never do.
    """
    args = list(doc.get("test_command") or []) + list(doc.get("collect_command") or [])
    return [
        a
        for a in args
        if not a.startswith("-") and ("/" in a or any((c / a).exists() for c in candidates))
    ]


def spec_cwd(spec: Path, repo: Path) -> Path:
    """The directory *spec*'s test command runs from.

    The nearest of the spec's own directory, its ancestors and the repo root
    where every path argument of the command exists. Nearest first, because a
    bare ``tests`` exists at the root too and a skill spec that says ``tests``
    means its own: run from the root it would score the repo's suite against
    the skill's mutants and report seven survivors. A spec with no path
    arguments runs from the root.

    Parameters
    ----------
    spec : Path
        Absolute path of the spec.
    repo : Path
        Root of the working tree.

    Returns
    -------
    Path
        The chosen working directory, absolute.
    """
    candidates = _candidates(spec, repo)
    args = _path_args(_load(spec), candidates)
    if not args:
        return candidates[-1]
    for candidate in candidates:
        if all((candidate / arg).exists() for arg in args):
            return candidate
    return candidates[-1]


def _relative(path: Path, repo: Path) -> str | None:
    try:
        return path.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        return None


def spec_inputs(spec: Path, repo: Path) -> set[str]:
    """Every tracked path whose change can alter *spec*'s verdict.

    The spec itself, each mutant's target file, and each path-like argument
    of its test and collect commands that exists under the spec's cwd (a
    file, or a directory — a changed file beneath it counts). All
    POSIX-relative to *repo*; a target outside the repo is dropped, since no
    commit here can change it.

    Parameters
    ----------
    spec : Path
        Absolute path of the spec.
    repo : Path
        Root of the working tree.

    Returns
    -------
    set[str]
        Repo-relative paths.
    """
    doc = _load(spec)
    cwd = spec_cwd(spec, repo)
    inputs = {_relative(spec, repo)}
    for mutant in doc.get("mutants", []):
        inputs.add(_relative(spec.parent / mutant["file"], repo))
    for arg in _path_args(doc, _candidates(spec, repo)):
        if (cwd / arg).exists():
            inputs.add(_relative(cwd / arg, repo))
    inputs.discard(None)
    return inputs  # type: ignore[return-value]


def _touched(inputs: set[str], changed: set[str]) -> list[str]:
    hits = set()
    for path in changed:
        for item in inputs:
            if path == item or path.startswith(item + "/"):
                hits.add(path)
    return sorted(hits)


def select_specs(repo: Path, base: str) -> list[tuple[Path, list[str]]]:
    """Return ``(spec, changed inputs)`` for every tracked spec an input of which changed since *base*.

    Parameters
    ----------
    repo : Path
        Root of the working tree.
    base : str
        The base revision; see ``changed_paths``.

    Returns
    -------
    list[tuple[Path, list[str]]]
        Sorted by spec path; the second member names the changed paths that
        selected it, for the report.
    """
    changed = changed_paths(repo, base)
    selected = []
    for spec in find_specs(repo):
        hits = _touched(spec_inputs(spec, repo), changed)
        if hits:
            selected.append((spec, hits))
    return selected


def run_spec(spec: Path, repo: Path) -> tuple[int, str]:
    """Run *spec* in full with the real runner and summarise the verdict.

    Parameters
    ----------
    spec : Path
        Absolute path of the spec.
    repo : Path
        Root of the working tree.

    Returns
    -------
    tuple[int, str]
        The runner's exit status and a report: one line per mutant with its
        status and full label, then the runner's stderr when it refused. The
        exit status is the verdict; the text only explains it.
    """
    result = subprocess.run(
        [sys.executable, str(_TEETH_CHECK), "--json", str(spec)],
        cwd=str(spec_cwd(spec, repo)),
        capture_output=True,
        text=True,
        check=False,
    )
    lines = []
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        for mutant in payload.get("mutants", []):
            who = ", ".join(mutant.get("killed_by") or []) or mutant.get("detail") or ""
            lines.append(f"  {mutant['status']:<14} {mutant['label']}  {who}".rstrip())
        never = payload.get("never_killed")
        if never:
            lines.append(f"  never-killed   {len(never)} test(s) killed no mutant:")
            lines.extend(f"                 {test_id}" for test_id in never)
    elif result.stdout.strip():
        lines.extend("  " + line for line in result.stdout.rstrip().splitlines())
    if result.stderr.strip():
        lines.extend("  " + line for line in result.stderr.rstrip().splitlines())
    return result.returncode, "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Select and run the specs a change can have affected; report per spec.

    Parameters
    ----------
    argv : list[str] | None
        ``--base REV`` (required), ``--repo PATH`` (defaults to this
        repository), ``--list`` to print the selection and run nothing.

    Returns
    -------
    int
        0 when every selected spec ran clean or none was selected; 1 when a
        selected spec failed (a survivor, an unapplied or unscored row, a
        broken control, a refused run) or no spec was found at all; 2 when
        the base ref cannot be resolved.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", required=True, help="git revision to diff the working tree against")
    parser.add_argument("--repo", type=Path, default=_REPO_ROOT, help="working tree to check")
    parser.add_argument("--list", action="store_true", help="print the selected specs and exit")
    args = parser.parse_args(argv)
    repo = args.repo.resolve()

    specs = find_specs(repo)
    if not specs:
        print(
            "no teeth specs found — discovery is broken, since this gate checked nothing",
            file=sys.stderr,
        )
        return 1
    try:
        selected = select_specs(repo, args.base)
    except BaseUnresolvable as exc:
        print(f"refusing to run: {exc}", file=sys.stderr)
        return 2

    untouched = len(specs) - len(selected)
    if not selected:
        print(
            f"teeth: no spec input changed since {args.base} "
            f"({untouched} specs untouched); nothing to run"
        )
        return 0

    if args.list:
        for spec, hits in selected:
            print(f"{spec.relative_to(repo).as_posix()}  (changed: {', '.join(hits)})")
        return 0

    failed: list[str] = []
    for spec, hits in selected:
        rel = spec.relative_to(repo).as_posix()
        print(f"RUN   {rel}  (changed: {', '.join(hits)})")
        sys.stdout.flush()
        code, report = run_spec(spec, repo)
        if report:
            print(report)
        if code != 0:
            failed.append(rel)
            print(f"FAIL  {rel}  (teeth_check exited {code})")
        else:
            print(f"ok    {rel}")
    print(f"\n{len(selected)} spec(s) run, {untouched} untouched since {args.base}")

    if failed:
        sys.stdout.flush()
        print(f"\nteeth specs whose mutants did not all die: {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
