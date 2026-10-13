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

The source file is restored from its saved bytes in a `finally`, never by
`git checkout`, and a CRLF file comes back byte-identical rather than
rewritten with LF endings. The `finally` runs on an exception, Ctrl-C, SIGTERM
and SIGHUP (the CLI turns the last two into an exception; a library caller of
`run_teeth_check` installs no handlers), and the test command's whole process
group dies with the run. It cannot run on SIGKILL or power loss, so each
mutation target is also locked by the OS (a second run on the same file
refuses) and journalled in a state directory (``~/.workshop/detector-teeth-check``,
or ``$TEETH_CHECK_STATE_DIR``): the next run on that target, or ``--recover``,
puts the original back, but only if the file still holds the exact mutant the
dead run wrote. A restore likewise never overwrites a file someone edited while
the mutant was on disk; it saves the original beside the journal and refuses.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import dataclasses
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None  # type: ignore[assignment]
    import msvcrt

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


class Interrupted(BaseException):
    """Raised by ``main``'s SIGTERM/SIGHUP handler so ``finally`` restores run.

    A ``BaseException``, like ``KeyboardInterrupt``: nothing that catches
    ``Exception`` may swallow a request to stop.
    """

    def __init__(self, signum: int) -> None:
        super().__init__(signum)
        self.signum = signum


class TargetLocked(Exception):
    """Raised when another live run holds a mutation target's lock."""

    def __init__(self, path: Path, pid: int | None) -> None:
        super().__init__(
            f"another teeth_check run (pid {pid if pid is not None else 'unknown'})"
            f" holds {path}"
        )
        self.path = path
        self.pid = pid


class RecoveryRefused(Exception):
    """Raised when a killed run's mutant cannot be undone without clobbering."""

    def __init__(self, path: Path, saved: Path) -> None:
        super().__init__(
            f"{path} changed after a killed run left a mutant in it; "
            f"the original is saved at {saved}"
        )
        self.path = path
        self.saved = saved


class ConcurrentEdit(Exception):
    """Raised when a target was edited while its mutant was on disk."""

    def __init__(self, path: Path, saved: Path) -> None:
        super().__init__(
            f"{path} was edited while a mutant was on disk; left as found, "
            f"the original is saved at {saved}"
        )
        self.path = path
        self.saved = saved


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


#: Seconds a SIGTERMed test-command group gets before it is SIGKILLed.
_KILL_GRACE_SECONDS = 5

_STATE_ENV = "TEETH_CHECK_STATE_DIR"


def _terminate_group(proc: "subprocess.Popen[str]") -> None:
    """Stop *proc* and everything it started: SIGTERM, a grace, then SIGKILL.

    The test command is ``uv`` -> pytest -> xdist workers; killing only the
    process we spawned orphans the rest, still running against the code the
    caller is about to restore.
    """
    if os.name != "posix":
        proc.kill()
        proc.wait()
        return
    group = proc.pid  # start_new_session made it the group leader
    # EPERM is macOS answering for a group whose members are all zombies.
    gone = (ProcessLookupError, PermissionError)

    def group_alive() -> bool:
        proc.poll()  # reap the leader, or it counts as a live member
        try:
            os.killpg(group, 0)
        except gone:
            return False
        return True

    with contextlib.suppress(*gone):
        os.killpg(group, signal.SIGTERM)
    deadline = time.monotonic() + _KILL_GRACE_SECONDS
    while group_alive() and time.monotonic() < deadline:
        time.sleep(0.05)
    with contextlib.suppress(*gone):
        os.killpg(group, signal.SIGKILL)
    proc.wait()


def _default_runner(cmd: list[str]) -> tuple[int, str]:
    # Purging before the run is not enough on its own: without this, each run
    # writes the cache the *next* row would have to survive.
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    # Its own session, so the whole tree can be signalled as one group (and so
    # a terminal's Ctrl-C reaches only us, which then stops the group).
    extra = {"start_new_session": True} if os.name == "posix" else {}
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        **extra,  # type: ignore[arg-type]
    )
    try:
        stdout, stderr = proc.communicate()
    except BaseException:
        _terminate_group(proc)
        raise
    return proc.returncode, stdout + stderr


def _state_dir() -> Path:
    """Machine-local state: ``$TEETH_CHECK_STATE_DIR`` or ``~/.workshop/...``."""
    override = os.environ.get(_STATE_ENV)
    if override:
        return Path(override)
    return Path.home() / ".workshop" / "detector-teeth-check"


def _plain_record(path: Path) -> dict:
    return {"pid": os.getpid(), "path": str(path)}


def _save_original(path: Path, original: bytes) -> Path:
    """Keep *original* beside the journal when it cannot safely be written back."""
    digest = hashlib.sha256(original).hexdigest()
    saved = _state_dir() / "recovered" / f"{path.name}.{digest[:12]}.orig"
    saved.parent.mkdir(parents=True, exist_ok=True)
    saved.write_bytes(original)
    return saved


@contextlib.contextmanager
def _signals_deferred() -> Iterator[None]:
    """Hold SIGTERM/SIGHUP/SIGINT back across a file write.

    A handler that fires between ``open("wb")`` truncating a file and the write
    landing would strand an empty file that is neither the original nor the
    mutant, which no restore could then recognise. The signal is delivered the
    moment the write is over.
    """
    if not hasattr(signal, "pthread_sigmask"):
        yield
        return
    held = {signal.SIGINT, signal.SIGTERM}
    if hasattr(signal, "SIGHUP"):
        held.add(signal.SIGHUP)
    # Put back what the caller had, not "unblocked": a signal they were
    # already holding back must stay held.
    previous = signal.pthread_sigmask(signal.SIG_BLOCK, held)
    try:
        yield
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous)


class _TargetLock:
    """An OS lock on one mutation target, whose file doubles as its journal.

    The lock is held by an open file descriptor, so the OS drops it when the
    process dies, even by SIGKILL. The file's content is one JSON object: this
    run's ``pid`` and ``path``, plus — only while a mutant is on disk — the
    original's bytes and both hashes, which is what lets a later run undo a
    mutant the dead run could not.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        digest = hashlib.sha256(str(path).encode("utf-8")).hexdigest()
        self.lockfile = _state_dir() / "locks" / f"{digest}.lock"
        self.fd: int | None = None

    def acquire(self) -> None:
        self.lockfile.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.lockfile, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            else:  # best-effort on Windows
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except (BlockingIOError, PermissionError):
            record = self._read(fd)
            os.close(fd)
            pid = record.get("pid")
            raise TargetLocked(self.path, pid if isinstance(pid, int) else None)
        except BaseException:
            os.close(fd)
            raise
        self.fd = fd

    @staticmethod
    def _read(fd: int) -> dict:
        chunks = []
        offset = 0
        while chunk := os.pread(fd, 1 << 16, offset):
            chunks.append(chunk)
            offset += len(chunk)
        try:
            record = json.loads(b"".join(chunks))
        except ValueError:
            return {}
        return record if isinstance(record, dict) else {}

    def read(self) -> dict:
        assert self.fd is not None
        return self._read(self.fd)

    def _write(self, record: dict) -> None:
        assert self.fd is not None
        data = json.dumps(record).encode("utf-8")
        os.ftruncate(self.fd, 0)
        os.lseek(self.fd, 0, os.SEEK_SET)
        os.write(self.fd, data)
        os.fsync(self.fd)

    def clear(self) -> None:
        self._write(_plain_record(self.path))

    def begin(self, original: bytes, mutant: bytes) -> None:
        """Journal *original* durably, before the mutant reaches the disk."""
        self._write(
            {
                **_plain_record(self.path),
                "original_b64": base64.b64encode(original).decode("ascii"),
                "original_sha256": hashlib.sha256(original).hexdigest(),
                "mutant_sha256": hashlib.sha256(mutant).hexdigest(),
            }
        )

    def release(self) -> None:
        if self.fd is not None:
            os.close(self.fd)  # drops the lock
            self.fd = None

    def recover(self) -> tuple[str, int | None]:
        """Undo what a killed holder left behind; return ``(outcome, its pid)``.

        The original is written back only when the file still holds exactly
        the mutant the record names. Anything else — someone edited it since,
        or it is gone — is left as found.
        """
        record = self.read()
        mutant_sha = record.get("mutant_sha256")
        if not mutant_sha:
            self.clear()
            return "clean", None
        dead_pid = record.get("pid")
        dead_pid = dead_pid if isinstance(dead_pid, int) else None
        try:
            original = base64.b64decode(record.get("original_b64", ""))
        except ValueError:
            original = b""
        try:
            current: str | None = hashlib.sha256(self.path.read_bytes()).hexdigest()
        except OSError:
            current = None
        if current == mutant_sha and (
            hashlib.sha256(original).hexdigest() == record.get("original_sha256")
        ):
            with _signals_deferred():
                self.path.write_bytes(original)
                _purge_cached_bytecode(self.path)
                self.clear()
            return "recovered", dead_pid
        if current == record.get("original_sha256"):
            self.clear()
            return "clean", None
        saved = _save_original(self.path, original)
        self.clear()
        raise RecoveryRefused(self.path, saved)


def _target_paths(spec: "Spec") -> list[Path]:
    return sorted({m.path.resolve() for m in spec.mutants}, key=str)


@contextlib.contextmanager
def _held_targets(
    paths: list[Path],
) -> Iterator[tuple[dict[Path, _TargetLock], list[tuple[Path, int | None]]]]:
    """Lock every path, undo any killed run's mutant, hold until the block ends.

    All locks are taken before any recovery writes, so a refusal on one target
    has mutated nothing on another. Yields the locks and the targets recovered.
    """
    locks: dict[Path, _TargetLock] = {}
    try:
        for path in paths:
            lock = _TargetLock(path)
            lock.acquire()
            locks[path] = lock
        recovered: list[tuple[Path, int | None]] = []
        for path, lock in locks.items():
            outcome, dead_pid = lock.recover()
            if outcome == "recovered":
                recovered.append((path, dead_pid))
        yield locks, recovered
    finally:
        for lock in locks.values():
            lock.release()


def _recovered_line(path: Path, dead_pid: int | None) -> str:
    pid = dead_pid if dead_pid is not None else "unknown"
    return (
        f"recovered {path}: restored the original a killed run (pid {pid}) "
        "left mutated"
    )


def _restore(
    path: Path, original: bytes, mutant: bytes, journal: _TargetLock
) -> ConcurrentEdit | None:
    """Put *original* back, unless the file is no longer what this run wrote.

    A file that is neither the mutant nor the original was edited by someone
    else while the mutant was on disk; writing the original over it would
    destroy that work, so it is left as found and the original is saved.
    """
    with _signals_deferred():
        try:
            current: bytes | None = path.read_bytes()
        except OSError:
            current = None
        edit = None
        if current == mutant:
            path.write_bytes(original)
        elif current != original:
            edit = ConcurrentEdit(path, _save_original(path, original))
        # Then drop the cache again: bytecode built from the mutant would
        # otherwise stay live and a *later* row would score this mutation.
        _purge_cached_bytecode(path)
        journal.clear()
    return edit


def run_teeth_check(spec: Spec, *, runner: Runner | None = None) -> Report:
    """Run every mutant in *spec* and report which tests caught which.

    The baseline runs first: if the suite is not green before any mutation,
    the whole exercise is meaningless and this raises rather than reporting.

    Every distinct target is locked for the whole call, before the collect
    command or the baseline, so only one run mutates a file at a time. A
    target held by another live run raises ``TargetLocked`` having mutated
    nothing; a mutant a killed run left behind is undone first (or raises
    ``RecoveryRefused`` if the file changed since). A target edited while its
    mutant was on disk raises ``ConcurrentEdit``. No signal handlers are
    installed here: that is ``main``'s job, so a library caller keeps its own.
    """
    run = _default_runner if runner is None else runner
    with _held_targets(_target_paths(spec)) as (locks, recovered):
        for path, dead_pid in recovered:
            print(_recovered_line(path, dead_pid), file=sys.stderr)
        return _score_mutants(spec, run, locks)


def _score_mutants(
    spec: Spec, run: Runner, locks: dict[Path, _TargetLock]
) -> Report:
    """Baseline, then score each mutant; the caller holds every target's lock."""
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

        mutated_bytes = mutated.encode("utf-8")
        journal = locks[mutant.path.resolve()]
        # The original is on disk in the journal before the mutant is, so a
        # run killed past any `finally` still leaves the way back.
        journal.begin(original, mutated_bytes)
        try:
            with _signals_deferred():
                mutant.path.write_bytes(mutated_bytes)
            _purge_cached_bytecode(mutant.path)
            code, out = run(spec.test_command)
        finally:
            # Restore before anything else can fail. A crash here would leave
            # deliberately-broken code in the working tree.
            edit = _restore(mutant.path, original, mutated_bytes, journal)
            if edit is not None:
                raise edit

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


def _require_key(raw: dict, key: str, label: str) -> object:
    """Return ``raw[key]``, refusing with a ``SpecError`` naming a missing key."""
    if key not in raw:
        raise SpecError(f"mutant {label!r} is missing required key {key!r}")
    return raw[key]


def _build_mutation(raw: dict, base: Path) -> Mutation:
    label = _require_key(raw, "label", "<unlabelled>")
    expect, why = _read_expectation(raw, label)
    return Mutation(
        label=label,
        path=(base / _require_key(raw, "file", label)).resolve(),
        find=_require_key(raw, "find", label),
        replace=_require_key(raw, "replace", label),
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


def _committed_spec(spec_path: Path, rev: str) -> dict | None:
    """Return the spec as committed at *rev*, or None if it was not there.

    Refuses (``SpecError``) rather than guessing: an unresolvable *rev* must
    not read as "the spec is new here" and quietly run every row, and a spec
    that was not a readable teeth spec at *rev* has no rows to compare with.
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
        return None
    before = subprocess.run(
        ["git", "show", committed],
        cwd=spec_path.parent,
        capture_output=True,
        check=True,
    ).stdout
    try:
        doc = json.loads(before.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SpecError(f"{spec_path.name} at {rev!r} is not JSON: {exc}") from None
    rows = doc.get("mutants") if isinstance(doc, dict) else None
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        raise SpecError(
            f"{spec_path.name} at {rev!r} has no list of mutant objects to "
            "compare with"
        )
    return doc


def select_changed_rows(spec_path: Path, spec: Spec, rev: str) -> Spec:
    """Return *spec* cut to rows added or edited since *rev*, plus controls.

    A row is unchanged only when the same JSON object appears in the spec as
    committed at *rev*; any edit to it — a re-anchor, a new replace, a
    relabel — selects it. Controls always run, since a partial run with no
    control cannot show the rig still discriminates.
    """
    # Through a symlink, git would show the link's text, not the spec.
    spec_path = spec_path.resolve()
    before = _committed_spec(spec_path, rev)
    current = json.loads(spec_path.read_text(encoding="utf-8"))
    raw_rows = current["mutants"]

    def settings(doc: dict) -> dict:
        return {key: value for key, value in doc.items() if key != "mutants"}

    # First written after REV, every row is new. A changed test command,
    # collect command or runner can flip any row's verdict, so every row
    # counts as changed then too.
    old_rows = (
        []
        if before is None or settings(before) != settings(current)
        else before["mutants"]
    )
    # Each committed row vouches for one current row, so a verbatim copy
    # added since REV is still new.
    unmatched = list(old_rows)
    keep = []
    for raw, mutant in zip(raw_rows, spec.mutants):
        if raw in unmatched:
            unmatched.remove(raw)
            if mutant.expect != "survived":
                continue
        keep.append(mutant)
    return dataclasses.replace(spec, mutants=keep)


def _recover_targets(spec: Spec) -> list[tuple[Path, str, str]]:
    """Lock, repair and release each distinct target; one outcome per target.

    Each outcome is ``(path, status, detail)``: ``clean``, ``recovered`` (detail
    is the killed run's pid), or ``refused`` (detail is the refusal text).
    """
    outcomes: list[tuple[Path, str, str]] = []
    for path in _target_paths(spec):
        try:
            with _held_targets([path]) as (_, recovered):
                if recovered:
                    pid = recovered[0][1]
                    outcomes.append((path, "recovered", str(pid or "unknown")))
                else:
                    outcomes.append((path, "clean", ""))
        except (TargetLocked, RecoveryRefused) as exc:
            outcomes.append((path, "refused", f"refusing to run: {exc}"))
    return outcomes


def _raise_interrupted(signum: int, frame: object) -> None:
    raise Interrupted(signum)


def main(argv: list[str] | None = None) -> int:
    """Run the CLI; SIGTERM and SIGHUP restore the mutants, then exit 128+n.

    The handlers live here, not in ``run_teeth_check``, so a library caller
    keeps its own; they are put back when this returns.
    """
    caught = [signal.SIGTERM]
    if hasattr(signal, "SIGHUP"):
        caught.append(signal.SIGHUP)
    previous = {}
    try:
        for signum in caught:
            previous[signum] = signal.signal(signum, _raise_interrupted)
    except ValueError:  # not the main thread: no handlers can be installed
        pass
    try:
        return _main(argv)
    except Interrupted as exc:
        name = signal.Signals(exc.signum).name
        print(f"interrupted by {name}; mutated files were restored", file=sys.stderr)
        return 128 + exc.signum
    except KeyboardInterrupt:
        print("interrupted by SIGINT; mutated files were restored", file=sys.stderr)
        return 130
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def _main(argv: list[str] | None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("spec", type=Path, help="JSON spec file")
    parser.add_argument(
        "--json", action="store_true", help="emit machine-readable JSON instead"
    )
    # Anchors are checked for every row regardless, so a revision given
    # alongside would be read by nothing.
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check-anchors",
        action="store_true",
        help=(
            "verify every mutant's anchor resolves against its file and "
            "exit — no baseline, no test command, no writes"
        ),
    )
    mode.add_argument(
        "--changed-since",
        metavar="REV",
        help=(
            "run only rows added or edited since git revision REV, plus "
            "controls — a fix round's inner loop, never the recorded tally"
        ),
    )
    mode.add_argument(
        "--recover",
        action="store_true",
        help=(
            "undo any mutant a killed run left in the spec's targets, then "
            "exit — no baseline, no test command"
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

    if args.recover:
        outcomes = _recover_targets(spec)
        for path, status, detail in outcomes:
            print(detail if status == "refused" else f"{path}: {status}")
        return 2 if any(status == "refused" for _, status, _ in outcomes) else 0

    # A mutant a killed run left on disk has already broken its own anchor, so
    # it must be undone before the anchor preflight can mistake it for drift.
    outcomes = _recover_targets(spec)
    for path, status, detail in outcomes:
        if status == "recovered":
            pid = int(detail) if detail.isdigit() else None
            print(_recovered_line(path, pid), file=sys.stderr)
    refused = [detail for _, status, detail in outcomes if status == "refused"]
    if refused:
        for detail in refused:
            print(detail, file=sys.stderr)
        return 2

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
    except (BaselineNotGreen, TargetLocked, RecoveryRefused, ConcurrentEdit) as exc:
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
