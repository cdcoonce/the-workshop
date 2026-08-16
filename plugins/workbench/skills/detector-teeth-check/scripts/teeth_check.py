#!/usr/bin/env python3
"""Verify a test suite actually has teeth, by breaking the code on purpose.

A green suite proves the tests ran, not that they would notice if the code
were wrong. This script re-injects a defect the code is supposed to prevent,
re-runs the suite, and reports which tests — if any — went red. A mutant that
nothing catches names an untested property. A test that catches no mutant is
carrying no weight.

Three distinctions the tool exists to keep straight, because a hand-rolled
version of this loop gets them wrong:

1. **An unapplied mutation is not a surviving mutation.** If the anchor text
   no longer matches the source, the spec has drifted. Reporting that as a
   survivor sends someone hunting for a missing test that already exists.
2. **A red baseline invalidates the whole run.** Against an already-failing
   suite every mutant looks killed. The run refuses rather than emitting a
   reassuring matrix.
3. **"Not computed" is not "nothing found."** Without a collect command the
   never-killed list is unknown, and is reported as unknown rather than as an
   empty all-clear.
4. **A run that named no failing test scored nothing.** A mutant that does not
   compile, or a test command that aborts before collection, exits non-zero
   with no ``FAILED`` line anywhere. That is the harness breaking, not an
   assertion catching the defect, so it is reported ``unscored`` rather than
   counted as a kill. Absence of a failure signal is never evidence of one.

The source file is restored in a `finally`, so a crash mid-run cannot leave
mutated code on disk.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

_FAILED_RE = re.compile(r"^FAILED\s+(\S+)", re.MULTILINE)
_COLLECTED_RE = re.compile(r"^(\S+::\S+)\s*$", re.MULTILINE)

Runner = Callable[[list[str]], "tuple[int, str]"]


class BaselineNotGreen(Exception):
    """Raised when the suite fails before any mutation is applied."""


@dataclass(frozen=True)
class Mutation:
    label: str
    path: Path
    find: str
    replace: str


@dataclass
class Spec:
    test_command: list[str]
    mutants: list[Mutation]
    collect_command: list[str] | None = None


@dataclass
class MutantResult:
    label: str
    status: str  # "killed" | "survived" | "not-applied" | "unscored"
    killed_by: list[str] = field(default_factory=list)
    detail: str = ""


@dataclass
class Report:
    mutants: list[MutantResult]
    never_killed: list[str] | None

    def survivors(self) -> list[MutantResult]:
        """Mutants no test caught — each names an untested property."""
        return [m for m in self.mutants if m.status == "survived"]

    def unapplied(self) -> list[MutantResult]:
        """Mutants whose anchor did not match — broken spec, not weak tests."""
        return [m for m in self.mutants if m.status == "not-applied"]

    def unscored(self) -> list[MutantResult]:
        """Mutants whose run produced no readable verdict — measured nothing."""
        return [m for m in self.mutants if m.status == "unscored"]


def parse_failed_tests(output: str) -> set[str]:
    """Extract test ids from pytest's ``FAILED <id>`` summary lines."""
    return set(_FAILED_RE.findall(output))


def parse_collected_tests(output: str) -> list[str]:
    """Extract test ids from ``pytest --collect-only -q`` output."""
    return _COLLECTED_RE.findall(output)


def normalize_test_id(test_id: str) -> str:
    """Reduce a pytest node id to a form comparable across invocation roots.

    ``--collect-only`` emits ids relative to pytest's rootdir (resolved from
    the nearest pyproject.toml, often the repo root) while the FAILED summary
    emits them relative to the invocation directory. Comparing raw strings
    makes every test look like it caught nothing.

    Normalizing to ``<file basename>::<rest>`` is enough to match them. Two
    same-named test files in different directories would collide; that is
    accepted here because the alternative — parsing rootdir out of pytest's
    header — is more fragile than the collision is likely.
    """
    file_part, sep, rest = test_id.partition("::")
    return f"{Path(file_part).name}{sep}{rest}"


def apply_mutation(text: str, find: str, replace: str) -> str:
    """Return *text* with *find* replaced by *replace*, exactly once.

    Raises on a missing anchor (the spec drifted from the source) and on an
    ambiguous one (two matches means the spec does not say which it meant).
    Both are spec errors, and both must be loud: a silent no-op would be
    indistinguishable from a mutation the tests failed to catch.
    """
    count = text.count(find)
    if count == 0:
        raise ValueError(f"anchor not found: {find!r}")
    if count > 1:
        raise ValueError(f"anchor is ambiguous ({count} matches): {find!r}")
    return text.replace(find, replace, 1)


def _default_runner(cmd: list[str]) -> tuple[int, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return proc.returncode, proc.stdout + proc.stderr


def run_teeth_check(spec: Spec, *, runner: Runner | None = None) -> Report:
    """Run every mutant in *spec* and report which tests caught which.

    The baseline runs first: if the suite is not green before any mutation,
    the whole exercise is meaningless and this raises rather than reporting.
    """
    run = _default_runner if runner is None else runner

    collected: list[str] | None = None
    if spec.collect_command is not None:
        _, out = run(spec.collect_command)
        collected = parse_collected_tests(out)

    code, out = run(spec.test_command)
    if code != 0:
        raise BaselineNotGreen(
            "suite is red before mutation; every mutant would look killed:\n"
            + "\n".join(sorted(parse_failed_tests(out)))
        )

    results: list[MutantResult] = []
    killers: set[str] = set()

    for mutant in spec.mutants:
        original = mutant.path.read_text(encoding="utf-8")
        try:
            mutated = apply_mutation(original, mutant.find, mutant.replace)
        except ValueError as exc:
            results.append(MutantResult(mutant.label, "not-applied", detail=str(exc)))
            continue

        # A mutant that cannot compile reds the suite by breaking the import,
        # not by tripping an assertion. Catch it here rather than letting the
        # run report a kill nothing actually earned.
        if mutant.path.suffix == ".py":
            try:
                compile(mutated, str(mutant.path), "exec")
            except SyntaxError as exc:
                results.append(
                    MutantResult(
                        mutant.label,
                        "unscored",
                        detail=f"mutant does not compile: {exc}",
                    )
                )
                continue

        try:
            mutant.path.write_text(mutated, encoding="utf-8")
            code, out = run(spec.test_command)
        finally:
            # Restore before anything else can fail. A crash here would leave
            # deliberately-broken code in the working tree.
            mutant.path.write_text(original, encoding="utf-8")

        if code == 0:
            results.append(MutantResult(mutant.label, "survived"))
            continue

        failed = sorted(parse_failed_tests(out))
        if not failed:
            # Non-zero with nothing named: the command aborted before it could
            # collect (an unrecognised flag, a missing plugin, an import error).
            # Scoring this as a kill would credit teeth to a run that never
            # evaluated an assertion.
            results.append(
                MutantResult(
                    mutant.label,
                    "unscored",
                    detail=f"run exited {code} naming no failing test",
                )
            )
            continue

        killers.update(normalize_test_id(t) for t in failed)
        results.append(MutantResult(mutant.label, "killed", killed_by=failed))

    never_killed = (
        None
        if collected is None
        else [t for t in collected if normalize_test_id(t) not in killers]
    )
    return Report(mutants=results, never_killed=never_killed)


def load_spec(path: Path) -> Spec:
    """Load a JSON spec. Mutation paths resolve relative to the spec file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    base = path.parent
    return Spec(
        test_command=data["test_command"],
        collect_command=data.get("collect_command"),
        mutants=[
            Mutation(
                label=m["label"],
                path=(base / m["file"]).resolve(),
                find=m["find"],
                replace=m["replace"],
            )
            for m in data["mutants"]
        ],
    )


def render(report: Report) -> str:
    lines = ["mutant                          status       killed by"]
    for m in report.mutants:
        who = ", ".join(m.killed_by) if m.killed_by else (m.detail or "-")
        lines.append(f"{m.label[:30]:<31} {m.status:<12} {who}")

    if report.unapplied():
        lines.append("")
        lines.append("SPEC ERROR — these anchors did not match; not a test weakness:")
        lines += [f"  {m.label}: {m.detail}" for m in report.unapplied()]

    if report.unscored():
        lines.append("")
        lines.append(
            "UNSCORED — these runs named no failing test, so they measured "
            "nothing.\nFix the mutant or the test command and re-run; do NOT "
            "read them as kills."
        )
        lines += [f"  {m.label}: {m.detail}" for m in report.unscored()]

    if report.survivors():
        lines.append("")
        lines.append("SURVIVORS — no test caught these; each names an untested property:")
        lines += [f"  {m.label}" for m in report.survivors()]
        lines.append(
            "  (Before hunting for a missing test, confirm each mutant actually "
            "changes\n  behaviour — a semantic no-op survives everything.)"
        )

    lines.append("")
    if report.never_killed is None:
        lines.append("never-killed tests: not computed (no collect_command in spec)")
    elif report.never_killed:
        lines.append(
            "CAUGHT NO MUTANT IN THIS RUN — not necessarily dead weight. A "
            "happy-path\ntest legitimately kills no defensive mutant. Read this "
            "as: either the\nspec lacks a mutant for what they cover, or they "
            "duplicate another test."
        )
        lines += [f"  {t}" for t in report.never_killed]
    else:
        lines.append("every collected test caught at least one mutant")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("spec", type=Path, help="JSON spec file")
    parser.add_argument(
        "--json", action="store_true", help="emit machine-readable JSON instead"
    )
    args = parser.parse_args(argv)

    try:
        report = run_teeth_check(load_spec(args.spec))
    except BaselineNotGreen as exc:
        print(f"refusing to run: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(
            json.dumps(
                {
                    "mutants": [vars(m) for m in report.mutants],
                    "never_killed": report.never_killed,
                },
                indent=2,
            )
        )
    else:
        print(render(report))

    # Non-zero when the suite lacks teeth somewhere, or when any row failed to
    # produce a verdict — an unscored run is not a pass.
    return 1 if report.survivors() or report.unapplied() or report.unscored() else 0


if __name__ == "__main__":
    raise SystemExit(main())
