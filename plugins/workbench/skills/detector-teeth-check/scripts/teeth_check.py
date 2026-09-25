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
   no longer matches the source, or the target file is gone, the spec has
   drifted. Reporting that as a survivor sends someone hunting for a missing
   test that already exists.
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

The source file is restored from its saved bytes in a `finally`, so a crash
mid-run cannot leave mutated code on disk, and a CRLF file comes back
byte-identical rather than rewritten with LF endings.
"""

from __future__ import annotations

import argparse
import dataclasses
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

# vitest's id shape is `<file> > <describe...> > <test>`. A file that failed
# to even *transform* (a syntax error in the mutated source) prints a FAIL
# line with no ` > ` in it at all — `FAIL  x.test.ts [ x.test.ts ]` — and that
# must NOT parse as a failing test: nothing in that file was ever evaluated,
# so scoring it as a kill would manufacture teeth for a property that may
# still be untested. Requiring a file-path-shaped prefix (ending in a known
# JS/TS test-file extension) before the first ` > ` is what tells the two
# apart, and the same constraint keeps the collected-ids regex from mistaking
# a stray output line for a test id.
_JS_TEST_FILE_EXTENSIONS = "tsx|mts|cts|mjs|cjs|jsx|ts|js"
_VITEST_FAILED_RE = re.compile(
    rf"^\s*FAIL\s+(\S+\.(?:{_JS_TEST_FILE_EXTENSIONS}) > .+)$", re.MULTILINE
)
_VITEST_COLLECTED_RE = re.compile(
    rf"^(\S+\.(?:{_JS_TEST_FILE_EXTENSIONS}) > .+)$", re.MULTILINE
)

Runner = Callable[[list[str]], "tuple[int, str]"]


class BaselineNotGreen(Exception):
    """Raised when the suite fails before any mutation is applied."""


class SpecError(Exception):
    """Raised when a spec is unreadable — a refusal, never a verdict."""


class TargetUnreadable(Exception):
    """Raised when a mutant's target file cannot be read.

    Scoped to one mutant, unlike ``SpecError``: the spec loaded fine, but this
    row names a file that cannot be read. It is a spec error on that row,
    like a stale anchor, and the other rows still get checked.
    """


#: What executed the assertion that scored a mutant.
#:
#: ``real`` — the actual dependency ran (a live client, a real database, the
#: genuine library call). The kill bounds behaviour.
#: ``double`` — a stand-in recorded the call. The kill bounds the argument that
#: was passed and nothing else, because the double is built from the shape the
#: code under test emits.
ORACLES = ("real", "double")

#: Per-mutant expectation. ``killed`` is the ordinary claim — this defect
#: should be caught. ``survived`` marks a positive control: a mutation
#: declared, by construction, to be semantically inert. Without one, a run in
#: which every mutant dies cannot distinguish "the tests have teeth" from
#: "this rig reports red for everything" — there is no row proving it can
#: also report green.
EXPECTATIONS = ("killed", "survived")


@dataclass(frozen=True)
class Mutation:
    label: str
    path: Path
    find: str
    replace: str
    oracle: str | None = None
    expect: str = "killed"
    why: str | None = None


@dataclass
class Spec:
    test_command: list[str]
    mutants: list[Mutation]
    collect_command: list[str] | None = None
    runner: str = "pytest"


@dataclass
class MutantResult:
    label: str
    status: str  # "killed" | "survived" | "not-applied" | "unscored" | "control-held" | "control-broken"
    killed_by: list[str] = field(default_factory=list)
    detail: str = ""
    oracle: str | None = None
    expect: str = "killed"
    why: str | None = None


@dataclass
class Report:
    mutants: list[MutantResult]
    never_killed: list[str] | None

    def survivors(self) -> list[MutantResult]:
        """Mutants no test caught — each names an untested property.

        A held control (``expect="survived"`` that stayed green) is not a
        survivor: it is the same run outcome under an opposite meaning,
        because its author declared it in advance. ``status`` keeps the two
        apart, so this never needs to filter on ``expect``.
        """
        return [m for m in self.mutants if m.status == "survived"]

    def unapplied(self) -> list[MutantResult]:
        """Mutants whose anchor or target file failed — broken spec, not weak tests."""
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

    def controls_held(self) -> list[MutantResult]:
        """Controls that stayed green, as their author predicted.

        The positive-control result: proof the rig can report an all-clear
        rather than red for everything.
        """
        return [m for m in self.mutants if m.status == "control-held"]

    def controls_broken(self) -> list[MutantResult]:
        """Controls a test caught anyway — the inertness argument or the test is wrong.

        Which one is a human judgment, not something this tool can resolve,
        so the row is reported with its killers rather than folded into
        either the kill tally or the survivors list.
        """
        return [m for m in self.mutants if m.status == "control-broken"]


def parse_failed_tests(output: str, runner: "RunnerSpec | None" = None) -> set[str]:
    """Extract failing test ids using *runner*'s failure-summary shape.

    Defaults to pytest's ``FAILED <id>`` lines — the only shape this tool
    understood before runners became pluggable, so a caller that does not
    pass one keeps today's behaviour exactly.
    """
    spec = runner if runner is not None else RUNNERS["pytest"]
    return set(spec.failed_re.findall(output))


def parse_collected_tests(output: str, runner: "RunnerSpec | None" = None) -> list[str]:
    """Extract collected test ids using *runner*'s collect-output shape."""
    spec = runner if runner is not None else RUNNERS["pytest"]
    return spec.collected_re.findall(output)


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


def _normalize_vitest_id(test_id: str) -> str:
    """Collapse internal whitespace so a FAIL-line id and a `list` id compare equal.

    `npx vitest list` and a FAIL line render the same ``file > describe >
    test`` id with different internal spacing, so comparing the raw strings
    would make every test look like it caught nothing — the same failure
    mode ``normalize_test_id`` exists to avoid for pytest, with a different
    cause.
    """
    return re.sub(r"\s+", " ", test_id).strip()


@dataclass(frozen=True)
class RunnerSpec:
    """How to read one test runner's output.

    Pulled apart from pytest because pytest's output shape used to be
    hardcoded: a vitest suite scored every mutant ``unscored`` even when it
    correctly went red, because the FAILED/collected regexes and the
    normalization that makes ids comparable are all runner-specific.
    """

    name: str
    failed_re: re.Pattern[str]
    collected_re: re.Pattern[str]
    normalize: Callable[[str], str]


RUNNERS: dict[str, RunnerSpec] = {
    "pytest": RunnerSpec(
        name="pytest",
        failed_re=_FAILED_RE,
        collected_re=_COLLECTED_RE,
        normalize=normalize_test_id,
    ),
    "vitest": RunnerSpec(
        name="vitest",
        failed_re=_VITEST_FAILED_RE,
        collected_re=_VITEST_COLLECTED_RE,
        normalize=_normalize_vitest_id,
    ),
}


def _find_matching_runner(output: str, *, exclude: str) -> str | None:
    """Return another registered runner whose failed_re matches *output*, if any.

    A row that names no failing test under the configured runner might still
    be a real red run, just parsed with the wrong shape. Checking the other
    registered runners turns a dead-end refusal — fix the mutant, fix the
    test command, neither of which can possibly help — into an actionable
    one: set the right ``runner`` in the spec.
    """
    for name, candidate in RUNNERS.items():
        if name != exclude and candidate.failed_re.search(output):
            return name
    return None


def _runner_mismatch_advice(output: str, configured: str) -> str:
    """Return the ``; set runner ...`` suffix for an unscored row, or "".

    Kept separate because the string is the whole point of the check: it is
    copied straight into a spec, so it has to be valid JSON rather than a
    Python repr, and a test can say so without driving a whole run.
    """
    other = _find_matching_runner(output, exclude=configured)
    if other is None:
        return ""
    return (
        f"; the output DOES match runner {other!r} — set "
        f"{json.dumps({'runner': other})} in the spec"
    )


def apply_mutation(text: str, find: str, replace: str) -> str:
    """Return *text* with *find* replaced by *replace*, exactly once.

    Raises on a missing anchor (the spec drifted from the source) and on an
    ambiguous one (two matches means the spec does not say which it meant).
    Both are spec errors, and both must be loud: a silent no-op would be
    indistinguishable from a mutation the tests failed to catch.

    Line endings are not part of an anchor. A newline in *find* matches
    ``\\n`` or ``\\r\\n``, so a spec resolves whichever platform saved the
    file, and newlines in *replace* are written in the file's own style.
    Only the matched span changes: re-encoding the whole text would rewrite
    every LF line of a CRLF file that was later edited elsewhere.
    """
    lines = find.replace("\r\n", "\n").split("\n")
    pattern = re.compile(r"\r?\n".join(re.escape(line) for line in lines))
    matches = list(pattern.finditer(text))
    if not matches:
        raise ValueError(f"anchor not found: {find!r}")
    if len(matches) > 1:
        raise ValueError(f"anchor is ambiguous ({len(matches)} matches): {find!r}")
    eol = "\r\n" if "\r\n" in text else "\n"
    new = replace.replace("\r\n", "\n").replace("\n", eol)
    start, end = matches[0].span()
    return text[:start] + new + text[end:]


def _read_source(path: Path) -> tuple[bytes, str]:
    """Return *path*'s exact bytes and their text, with no newline translation.

    ``read_text`` translates ``\\r\\n`` to ``\\n``, so a restore written from
    its result rewrote every line of a CRLF file: a whole-file diff on a file
    the run claims to leave byte-identical. The bytes are what the restore
    writes back. ``--check-anchors`` reads through here too, so an anchor
    cannot pass the fast check and then fail to apply in the run.

    Any ``OSError`` from the read — the file deleted or renamed, a directory
    where the file was, no permission to read it — raises
    ``TargetUnreadable`` naming the path. Every one of them means the same
    thing: this row's target cannot be mutated, so the row reports it and the
    rest of the spec still runs. Bytes that are not UTF-8 — a binary file, a
    Latin-1 source — mean the same again, and raise it too: an anchor is
    text, so there is no text to find it in. The decode gets its own
    ``except`` rather than leaning on the callers' ``except ValueError``,
    which ``UnicodeDecodeError`` would also satisfy, because only here is
    the path still in hand to name. Only the read and the decode are
    covered; nothing has been written yet, so there is nothing a caught
    error could leave unrestored.
    """
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        raise TargetUnreadable(f"file not found: {path}") from None
    except OSError as exc:
        raise TargetUnreadable(f"cannot read {path}: {exc.strerror or exc}") from None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise TargetUnreadable(f"not UTF-8: {path}") from None
    return raw, text


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
    runner_spec = RUNNERS[spec.runner]

    collected: list[str] | None = None
    if spec.collect_command is not None:
        _, out = run(spec.collect_command)
        collected = parse_collected_tests(out, runner_spec)

    # A cache left from an earlier aborted run can carry mutated bytecode into
    # the baseline, where it passes unnoticed and every row after it is scored
    # against code that is not on disk.
    for mutant in spec.mutants:
        _purge_cached_bytecode(mutant.path)

    code, out = run(spec.test_command)
    if code != 0:
        raise BaselineNotGreen(
            "suite is red before mutation; every mutant would look killed:\n"
            + "\n".join(sorted(parse_failed_tests(out, runner_spec)))
        )

    results: list[MutantResult] = []
    killers: set[str] = set()

    for mutant in spec.mutants:
        try:
            original, text = _read_source(mutant.path)
        except TargetUnreadable as exc:
            results.append(
                MutantResult(
                    mutant.label,
                    "not-applied",
                    detail=str(exc),
                    oracle=mutant.oracle,
                    expect=mutant.expect,
                    why=mutant.why,
                )
            )
            continue
        try:
            mutated = apply_mutation(text, mutant.find, mutant.replace)
        except ValueError as exc:
            results.append(
                MutantResult(
                    mutant.label,
                    "not-applied",
                    detail=str(exc),
                    oracle=mutant.oracle,
                    expect=mutant.expect,
                    why=mutant.why,
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
                        expect=mutant.expect,
                        why=mutant.why,
                    )
                )
                continue

        try:
            mutant.path.write_bytes(mutated.encode("utf-8"))
            _purge_cached_bytecode(mutant.path)
            code, out = run(spec.test_command)
        finally:
            # Restore before anything else can fail. A crash here would leave
            # deliberately-broken code in the working tree.
            mutant.path.write_bytes(original)
            # Then drop the cache again: bytecode built from the mutant would
            # otherwise stay live and a *later* row would score this mutation.
            _purge_cached_bytecode(mutant.path)

        if code == 0:
            # A control that stays green held, as its author predicted; an
            # ordinary mutant that stays green survived. Same run outcome,
            # opposite meaning — only the control declared it in advance.
            status = "control-held" if mutant.expect == "survived" else "survived"
            results.append(
                MutantResult(
                    mutant.label,
                    status,
                    oracle=mutant.oracle,
                    expect=mutant.expect,
                    why=mutant.why,
                )
            )
            continue

        failed = sorted(parse_failed_tests(out, runner_spec))
        if not failed:
            # Non-zero with nothing named: the command aborted before it could
            # collect (an unrecognised flag, a missing plugin, an import
            # error) — or the configured runner is simply reading the wrong
            # output shape. Scoring this as a kill would credit teeth to a
            # run that never evaluated an assertion, so check whether another
            # registered runner's shape would have matched before giving up.
            detail = (
                f"run exited {code} naming no failing test under runner "
                f"{spec.runner!r}"
            )
            detail += _runner_mismatch_advice(out, spec.runner)
            results.append(
                MutantResult(
                    mutant.label,
                    "unscored",
                    detail=detail,
                    oracle=mutant.oracle,
                    expect=mutant.expect,
                    why=mutant.why,
                )
            )
            continue

        killers.update(runner_spec.normalize(t) for t in failed)
        # A control that goes red broke: something caught a mutation its
        # author argued was inert. An ordinary mutant that goes red killed,
        # as before.
        status = "control-broken" if mutant.expect == "survived" else "killed"
        results.append(
            MutantResult(
                mutant.label,
                status,
                killed_by=failed,
                oracle=mutant.oracle,
                expect=mutant.expect,
                why=mutant.why,
            )
        )

    never_killed = (
        None
        if collected is None
        else [t for t in collected if runner_spec.normalize(t) not in killers]
    )
    return Report(mutants=results, never_killed=never_killed)


def check_anchors(spec: Spec) -> list[tuple[str, str | None]]:
    """Check every mutant's anchor without running anything or touching disk.

    A spec's ``find`` anchors are exact source strings, so a refactor of the
    code under test can desync them silently — nothing else in this tool
    would notice until the next full run. This reads each mutant's file and
    asks ``apply_mutation`` whether the anchor still resolves to exactly one
    site, and nothing more: no baseline, no test command, no write. Fast and
    safe enough to sit ahead of a slow full run in a gate. A file it cannot
    read is that row's error, so one deleted target still leaves every other
    row checked and reported.
    """
    outcomes: list[tuple[str, str | None]] = []
    for mutant in spec.mutants:
        try:
            _, text = _read_source(mutant.path)
        except TargetUnreadable as exc:
            outcomes.append((mutant.label, str(exc)))
            continue
        try:
            apply_mutation(text, mutant.find, mutant.replace)
        except ValueError as exc:
            outcomes.append((mutant.label, str(exc)))
        else:
            outcomes.append((mutant.label, None))
    return outcomes


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


def _read_expectation(mutant: dict, label: str) -> tuple[str, str | None]:
    """Return a mutant's declared ``(expect, why)``.

    ``expect`` defaults to ``killed``, so an ordinary mutant needs no new
    key — this is additive, not a second required field alongside ``oracle``.
    A ``survived`` control is different: the whole point is a deliberate
    no-op, and a control nobody argued for is indistinguishable from a
    survivor someone decided to ignore. So ``why`` is optional documentation
    on any mutant, but required — and non-blank — exactly when ``expect`` is
    ``survived``.
    """
    expect = mutant.get("expect", "killed")
    if expect not in EXPECTATIONS:
        raise SpecError(
            f"mutant {label!r} declares expect {expect!r}; expected one of "
            f"{EXPECTATIONS}"
        )
    why = mutant.get("why")
    if expect == "survived" and not (why and why.strip()):
        raise SpecError(
            f"mutant {label!r} declares expect='survived' with no 'why': a "
            "control without a stated argument for its own inertness is "
            "indistinguishable from a survivor someone decided to ignore."
        )
    return expect, why


def _read_runner(data: dict) -> str:
    """Return the spec's declared runner, defaulting to ``pytest``.

    Unlike ``oracle``, defaulting here cannot manufacture a false guarantee:
    a wrong runner makes every row ``unscored`` — a loud refusal — never a
    false kill. That asymmetry is exactly why ``oracle`` is required per
    mutant while ``runner`` is defaulted for the whole spec.
    """
    name = data.get("runner", "pytest")
    if name not in RUNNERS:
        raise SpecError(f"unknown runner {name!r}; expected one of {sorted(RUNNERS)}")
    return name


def _build_mutation(raw: dict, base: Path) -> Mutation:
    label = raw["label"]
    expect, why = _read_expectation(raw, label)
    return Mutation(
        label=label,
        path=(base / raw["file"]).resolve(),
        find=raw["find"],
        replace=raw["replace"],
        oracle=_read_oracle(raw, label),
        expect=expect,
        why=why,
    )


def load_spec(path: Path) -> Spec:
    """Load a JSON spec. Mutation paths resolve relative to the spec file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    base = path.parent
    return Spec(
        test_command=data["test_command"],
        collect_command=data.get("collect_command"),
        runner=_read_runner(data),
        mutants=[_build_mutation(m, base) for m in data["mutants"]],
    )


def render(report: Report, *, never_killed_unknown: str = "no collect_command in spec") -> str:
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
        lines.append("SPEC ERROR — these mutants could not be applied; not a test weakness:")
        lines += [f"  {m.label}: {m.detail}" for m in report.unapplied()]

    if report.unscored():
        lines.append("")
        lines.append(
            "UNSCORED — these runs named no failing test, so they measured "
            "nothing.\nCheck the configured runner first — a mismatched "
            "output shape reads exactly\nlike a broken mutant or test "
            "command, but no amount of fixing either one\ncan help. Only "
            "once that's ruled out, fix the mutant or the test command\n"
            "and re-run; do NOT read these as kills."
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

    if report.controls_held():
        lines.append("")
        lines.append(
            "CONTROLS HELD — declared inert by construction, and stayed "
            "green. The\nauthor's argument for each, verbatim:"
        )
        lines += [f"  {m.label}: {m.why}" for m in report.controls_held()]

    if report.controls_broken():
        lines.append("")
        lines.append(
            "CONTROL BROKEN — declared inert, but a test caught it anyway. "
            "Either the\ninertness argument is wrong — read this row as a "
            "real mutant — or a test is\nasserting incidental form rather "
            "than behaviour. A human has to decide which:"
        )
        lines += [
            f"  {m.label}: {', '.join(m.killed_by)}" for m in report.controls_broken()
        ]

    if report.controls_held() and not kills:
        lines.append("")
        lines.append(
            "NOTE — a control held but nothing was killed: this run proved "
            "the rig executes,\nnot that anything here has teeth."
        )

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
        lines.append(f"never-killed tests: not computed ({never_killed_unknown})")
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


def _exit_code(report: Report) -> int:
    """Non-zero when the suite lacks teeth, a row produced no verdict, or a
    control caught something it declared inert.

    A broken control gets the same treatment as a survivor or an unscored
    row: it is "a human has to look at this," not a pass. A held control is
    not in this list — green is the correct, expected outcome for one.
    """
    return (
        1
        if report.survivors()
        or report.unapplied()
        or report.unscored()
        or report.controls_broken()
        else 0
    )


def select_changed_rows(spec_path: Path, spec: Spec, rev: str) -> Spec:
    """Return *spec* cut to rows added or edited since *rev*, plus controls.

    A row is unchanged only when the same JSON object appears in the spec as
    committed at *rev*; any edit to it — a re-anchor, a new replace, a
    relabel — selects it. Controls always run, since a partial run with no
    control cannot show the rig still discriminates.
    """
    resolved = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}"],
        cwd=spec_path.parent,
        capture_output=True,
    )
    if resolved.returncode != 0:
        # Checked apart from the path lookup below: both fail the same way,
        # and a typo read as "spec is new here" would quietly run every row.
        raise SpecError(
            f"--changed-since {rev!r} is not a commit in a git repository "
            f"holding {spec_path}"
        )
    committed = f"{rev}:./{spec_path.name}"
    present = subprocess.run(
        ["git", "cat-file", "-e", committed],
        cwd=spec_path.parent,
        capture_output=True,
    )
    if present.returncode != 0:
        # First written after REV: every row is new.
        old_rows: list[dict] = []
    else:
        before = subprocess.run(
            ["git", "show", committed],
            cwd=spec_path.parent,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        old_rows = json.loads(before)["mutants"]
    raw_rows = json.loads(spec_path.read_text(encoding="utf-8"))["mutants"]
    keep = [
        mutant
        for raw, mutant in zip(raw_rows, spec.mutants, strict=True)
        if raw not in old_rows or mutant.expect == "survived"
    ]
    return dataclasses.replace(spec, mutants=keep)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("spec", type=Path, help="JSON spec file")
    parser.add_argument(
        "--json", action="store_true", help="emit machine-readable JSON instead"
    )
    parser.add_argument(
        "--check-anchors",
        action="store_true",
        help=(
            "verify every mutant's anchor resolves against its file and "
            "exit — no baseline, no test command, no writes"
        ),
    )
    parser.add_argument(
        "--changed-since",
        metavar="REV",
        help=(
            "run only rows added or edited since git revision REV, plus "
            "controls — a fix round's inner loop, never the recorded tally"
        ),
    )
    args = parser.parse_args(argv)

    try:
        spec = load_spec(args.spec)
    except SpecError as exc:
        print(f"refusing to run: {exc}", file=sys.stderr)
        return 2

    if args.check_anchors:
        outcomes = check_anchors(spec)
        if args.json:
            print(
                json.dumps(
                    [{"label": label, "error": error} for label, error in outcomes],
                    indent=2,
                )
            )
        else:
            for label, error in outcomes:
                print(f"{label}: {'ok' if error is None else error}")
        return 0 if all(error is None for _, error in outcomes) else 1

    # A stale row costs nothing to find here and a whole run to find in the
    # loop, which reaches it only after the baseline and every row before it
    # — and a run holding any unapplied row can never be the recorded tally.
    # The loop still scores `not-applied` itself, for a file that changes
    # after this check.
    stale = [(label, error) for label, error in check_anchors(spec) if error]
    if stale:
        print(
            f"refusing to run: {len(stale)} anchor(s) no longer resolve; "
            "nothing ran. Re-anchor these rows, then re-run:",
            file=sys.stderr,
        )
        for label, error in stale:
            print(f"  {label}: {error}", file=sys.stderr)
        return 2

    total = len(spec.mutants)
    if args.changed_since is not None:
        try:
            spec = select_changed_rows(args.spec, spec, args.changed_since)
        except SpecError as exc:
            print(f"refusing to run: {exc}", file=sys.stderr)
            return 2
        if all(m.expect == "survived" for m in spec.mutants):
            print(
                f"refusing to run: no rows added or edited since "
                f"{args.changed_since}; controls alone verify nothing",
                file=sys.stderr,
            )
            return 2
    # Only a run of every row is a count a pull request may carry; a partial
    # one says so on its first line, where a paste would begin.
    partial = (
        {"ran": len(spec.mutants), "of": total, "changed_since": args.changed_since}
        if len(spec.mutants) < total
        else None
    )
    if partial is not None:
        # A test that kills only a skipped row would read as killing nothing.
        spec = dataclasses.replace(spec, collect_command=None)

    try:
        report = run_teeth_check(spec)
    except BaselineNotGreen as exc:
        print(f"refusing to run: {exc}", file=sys.stderr)
        return 2

    if args.json:
        payload: dict = {
            "mutants": [vars(m) for m in report.mutants],
            "never_killed": report.never_killed,
        }
        if partial is not None:
            payload["partial"] = partial
        print(json.dumps(payload, indent=2))
    else:
        if partial is not None:
            print(
                f"PARTIAL: {partial['ran']} of {partial['of']} rows (changed since "
                f"{partial['changed_since']}, plus controls) — not the tally; "
                "run the full spec before recording a count\n"
            )
            print(render(report, never_killed_unknown="partial run"))
        else:
            print(render(report))

    return _exit_code(report)


if __name__ == "__main__":
    raise SystemExit(main())
