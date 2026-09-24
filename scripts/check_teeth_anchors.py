"""Resolve every committed detector-teeth-check spec's anchors, without running mutants.

A teeth spec anchors each mutant on an exact source string, so a refactor of
the code it quotes stales the anchor while every suite stays green — the spec
just stops being runnable, and nobody learns that until the next full mutation
run. ``teeth_check.py --check-anchors`` already answers the question in well
under a second; this module makes the gate ask it of every spec, every run.

Specs are found by name in the index (``*.teeth.json`` and
``teeth-spec-*.json``) rather than listed by hand, so a new spec is gated the
moment it is committed. Mutant ``file`` paths resolve against each spec's own
directory, so the per-spec cwd that a full run needs (the repo root for most,
``plugins/workbench/machinery/`` for its own spec) does not matter here.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_TEETH_CHECK = _REPO_ROOT / "plugins/workbench/skills/detector-teeth-check/scripts/teeth_check.py"
_SPEC_PATHSPECS = (":(glob)**/*.teeth.json", ":(glob)**/teeth-spec-*.json")


def find_specs(repo_root: Path) -> list[Path]:
    """Return every tracked teeth spec under *repo_root*.

    Discovery reads the index, not the filesystem: a stray local draft must
    not gate a merge, and a tree walk from the main checkout would descend
    into ``.claude/worktrees/`` and judge other sessions' branches.

    Parameters
    ----------
    repo_root : Path
        Root of the git working tree to search.

    Returns
    -------
    list[Path]
        Absolute paths of every tracked spec, sorted.
    """
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--", *_SPEC_PATHSPECS],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return sorted(repo_root / rel for rel in listed.split("\0") if rel)


def check_spec(spec: Path) -> list[str]:
    """Return why *spec*'s anchors do not all resolve; empty only if they do.

    The exit code is the verdict. The JSON only explains it, and a spec the
    checker refuses (a message on stderr) or a checker that crashes outright
    (a traceback) prints none — so a non-zero exit is never read as clean just
    because no stale anchor could be listed.

    Parameters
    ----------
    spec : Path
        The teeth spec to check.

    Returns
    -------
    list[str]
        One ``label: reason`` line per unresolvable anchor, or a single line
        naming the checker's exit status when it could not report per anchor.
    """
    result = subprocess.run(
        [sys.executable, str(_TEETH_CHECK), "--check-anchors", "--json", str(spec)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return []
    try:
        outcomes = json.loads(result.stdout)
    except json.JSONDecodeError:
        outcomes = []
    problems = [f"{o['label']}: {o['error']}" for o in outcomes if o["error"] is not None]
    if problems:
        return problems
    last_line = result.stderr.strip().splitlines()[-1:] or [""]
    return [f"teeth_check exited {result.returncode}: {last_line[0]}"]


def main(argv: list[str] | None = None) -> int:
    """Check every tracked spec's anchors and report per spec.

    Parameters
    ----------
    argv : list[str] | None
        Optional single argument: the repo root to check. Defaults to this
        repository.

    Returns
    -------
    int
        0 when every anchor of every spec resolves; 1 when any does not, or
        when no spec was found at all.
    """
    repo_root = Path(argv[0]) if argv else _REPO_ROOT
    specs = find_specs(repo_root)
    if not specs:
        # This repo always commits specs, so none found means discovery broke —
        # and a gate that passed on that would check nothing, forever.
        print(
            "no teeth specs found — discovery is broken, since this gate "
            f"checked nothing (pathspecs: {', '.join(_SPEC_PATHSPECS)})",
            file=sys.stderr,
        )
        return 1

    stale: list[str] = []
    for spec in specs:
        rel = spec.relative_to(repo_root)
        problems = check_spec(spec)
        if problems:
            stale.append(str(rel))
            print(f"STALE {rel}")
            for problem in problems:
                print(f"  {problem}")
        else:
            print(f"ok    {rel}")

    if stale:
        # Piped (as in CI), stdout is block-buffered and this summary would
        # land above the per-spec list it summarizes.
        sys.stdout.flush()
        print(f"\nteeth specs with unresolvable anchors: {', '.join(stale)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
