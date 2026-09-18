#!/usr/bin/env python3
"""Verify a test suite actually has teeth, by breaking the code on purpose.

A green suite proves the tests ran, not that they would notice if the code
were wrong. This script re-injects a defect the code is supposed to prevent,
re-runs the suite, and reports which tests — if any — went red. A mutant that
nothing catches names an untested property. A test that catches no mutant is
carrying no weight.

Five distinctions the tool exists to keep straight, because a hand-rolled
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
5. **Cached bytecode is not the code on disk.** CPython validates a ``.pyc``
   against the source's byte size and its mtime truncated to whole seconds,
   neither of which a same-length replacement written inside that second
   disturbs — so the interpreter loads the old bytecode and the mutation never
   runs. Every run purges the mutated module's cache and executes with
   bytecode writing disabled, because a mutant that never executed is reported
   as a survivor and reads exactly like a real gap.
6. **A kill is a claim about the test's oracle, not about reality.** A mutant
   dying proves the test is sensitive to a change in *our source*. If the
   assertion ran against a recording double, that double's oracle IS the code
   under test, so the kill was guaranteed by construction and bounds only what
   was passed — never that the real dependency accepts it. Each mutant
   therefore declares its ``oracle``, and the report keeps the two kinds of
   kill apart instead of summing them into one reassuring number.

The source file is restored in a `finally`, so a crash mid-run cannot leave
mutated code on disk.
"""

from __future__ import annotations

import argparse
import json
import os
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


class SpecError(Exception):
    """Raised when a spec is unreadable — a refusal, never a verdict."""


#: What executed the assertion that scored a mutant.
#:
#: ``real`` — the actual dependency ran (a live client, a real database, the
#: genuine library call). The kill bounds behaviour.
#: ``double`` — a stand-in recorded the call. The kill bounds the argument that
#: was passed and nothing else, because the double is built from the shape the
#: code under test emits.
ORACLES = ("real", "double")


@dataclass(frozen=True)
class Mutation:
    label: str
    path: Path
    find: str
    replace: str
    oracle: str | None = None


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
    oracle: str | None = None


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

    def double_only_kills(self) -> list[MutantResult]:
        """Kills scored solely against a stand-in.

        Not a failure — a *scoped* claim. The mutation changed what the double
        observed, which is guaranteed the moment the double records the code's
        own output. Nothing here says the real collaborator accepts it.
        """
        return [m for m in self.mutants if m.status == "killed" and m.oracle == "double"]


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


def _purge_cached_bytecode(path: Path) -> None:
    """Drop cached bytecode for *path* so a mutation cannot run stale.

    Only ``__pycache__`` entries for this exact module are removed, and only
    files inside it — never the directory, never a sibling module's cache.
    Bytecode is a regenerable artifact, so unlike a checkout this cannot
    destroy work.
    """
    if path.suffix != ".py":
        return
    cache_dir = path.parent / "__pycache__"
    if not cache_dir.is_dir():
        return
    for stale in cache_dir.glob(f"{path.stem}.*.pyc"):
        stale.unlink(missing_ok=True)


def _default_runner(cmd: list[str]) -> tuple[int, str]:
    # Purging before the run is not enough on its own: without this, each run
    # writes the cache the *next* row would have to survive.
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False, env=env)
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

    # A cache left from an earlier aborted run can carry mutated bytecode into
    # the baseline, where it passes unnoticed and every row after it is scored
    # against code that is not on disk.
    for mutant in spec.mutants:
        _purge_cached_bytecode(mutant.path)

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
            results.append(
                MutantResult(
                    mutant.label,
                    "not-applied",
                    detail=str(exc),
                    oracle=mutant.oracle,
                )
            )
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
                        oracle=mutant.oracle,
                    )
                )
                continue

        try:
            mutant.path.write_text(mutated, encoding="utf-8")
            _purge_cached_bytecode(mutant.path)
            code, out = run(spec.test_command)
        finally:
            # Restore before anything else can fail. A crash here would leave
            # deliberately-broken code in the working tree.
            mutant.path.write_text(original, encoding="utf-8")
            # Then drop the cache again: bytecode built from the mutant would
            # otherwise stay live and a *later* row would score this mutation.
            _purge_cached_bytecode(mutant.path)

        if code == 0:
            results.append(
                MutantResult(mutant.label, "survived", oracle=mutant.oracle)
            )
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
                    oracle=mutant.oracle,
                )
            )
            continue

        killers.update(normalize_test_id(t) for t in failed)
        results.append(
            MutantResult(
                mutant.label, "killed", killed_by=failed, oracle=mutant.oracle
            )
        )

    never_killed = (
        None
        if collected is None
        else [t for t in collected if normalize_test_id(t) not in killers]
    )
    return Report(mutants=results, never_killed=never_killed)


def _read_oracle(mutant: dict, label: str) -> str:
    """Return a mutant's declared oracle, refusing anything else.

    Omission refuses rather than defaulting. A mutant whose oracle is assumed
    is the exact false confidence this field exists to remove: the author is
    the only one who knows whether the predicted test drives the real
    dependency or a stand-in, and guessing ``real`` on their behalf would
    manufacture a guarantee nobody checked.
    """
    if "oracle" not in mutant:
        raise SpecError(
            f"mutant {label!r} declares no 'oracle'. Add one of {ORACLES}: "
            "'real' if the predicted test drives the actual dependency, "
            "'double' if a stand-in records the call. A kill against a double "
            "proves the argument was passed, not that the behaviour works."
        )
    oracle = mutant["oracle"]
    if oracle not in ORACLES:
        raise SpecError(
            f"mutant {label!r} declares oracle {oracle!r}; expected one of {ORACLES}"
        )
    return oracle


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
                oracle=_read_oracle(m, m["label"]),
            )
            for m in data["mutants"]
        ],
    )


def render(report: Report) -> str:
    lines = ["mutant                          status       oracle       killed by"]
    for m in report.mutants:
        who = ", ".join(m.killed_by) if m.killed_by else (m.detail or "-")
        oracle = m.oracle or "undeclared"
        lines.append(f"{m.label[:30]:<31} {m.status:<12} {oracle:<12} {who}")

    kills = [m for m in report.mutants if m.status == "killed"]
    if kills:
        real = sum(1 for m in kills if m.oracle == "real")
        doubles = sum(1 for m in kills if m.oracle == "double")
        undeclared = len(kills) - real - doubles
        tally = (
            f"{len(kills)} killed — {real} against the real dependency, "
            f"{doubles} against doubles"
        )
        if undeclared:
            tally += f", {undeclared} undeclared"
        lines.append("")
        lines.append(tally)
        if undeclared:
            lines.append(
                "  (Undeclared is not 'real'. Nobody said what executed those "
                "assertions,\n  so nothing here bounds behaviour.)"
            )

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

    if report.double_only_kills():
        lines.append("")
        lines.append(
            "KILLED AGAINST A DOUBLE ONLY — these prove the argument was "
            "passed, never\nthat the behaviour works. A recording double is "
            "built from the shape the code\nunder test emits, so mutating that "
            "code is killed by construction: the kill\nwas guaranteed before "
            "the suite ran. Write the claim at that scope, or add a\nrow whose "
            "oracle is the real dependency:"
        )
        lines += [f"  {m.label}" for m in report.double_only_kills()]

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
    except (BaselineNotGreen, SpecError) as exc:
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
