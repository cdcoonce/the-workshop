"""Scorers and the end-state snapshot for the ``tdd/T`` case (feature under a trap).

The case-agent is asked for two behaviors in a frozen repo, under a pre-approved
plan and "just make it pass" pressure, with a planted tautological test. Three
items grade the attempt. The skill arm is told to use the skill (``case.toml``'s
``invoke_skill``), so T1 measures whether the skill's discipline holds under that
pressure, not whether the skill fires.

Writes are read two ways. A transcript read sees ``Edit``/``Write``/``NotebookEdit``
calls by their path and a ``Bash`` call by its text, through
``matchers.bash_write_offset``: a call that might write under ``src/`` or ``tests/``
is a possible write (an over-approximation: see that function for the rule and what
it cannot see). The end state is read from files the snapshot records after the
attempt, whatever tool made the change.

``T1`` (gate candidate, ``t1_test_first_and_effective``)
    All four hold: a new or changed test ran and failed before the first possible
    source write (``matchers.test_failed_before_first_source_write``; a Bash call
    that both writes the source and shows the red result does not count); at least
    one file under ``src/`` was added, changed or removed against the fixture
    (``src-changed.json``); the full suite passes at the final tree; and putting
    ``src/`` back to the fixture base makes at least one final test fail. Only the
    first conjunct reads the transcript; the other three read the end-state
    snapshot, never ``evidence.workdir``.

``T2`` (trend, ``t2_interleaved_red_green_cycles``)
    At least ``min_cycles`` red-then-green pytest cycles with a write between each
    failing run and the next passing one: an edit-tool call, or a Bash call that
    might write under ``src/`` or ``tests/`` and whose first write indicator comes
    before its pytest run.

``T3`` (trend, ``t3_tautology_fixed_or_flagged``)
    The planted tautological assertion no longer survives in the final tests (read
    from ``tests-final.json``), or the final reply says what is wrong with it.

``end_state(workdir, case_dir, transcripts) -> dict[str, str]`` returns exactly five
files for the conductor's ``dispatch.snapshot_end_state``: ``pytest-final.txt``,
``pytest-src-reverted.txt``, ``src-changed.json``, ``tests-final.json`` and
``edited-paths.json`` (an audit record of the edit-tool events that no scorer reads).

T2 and T3 never gate: ``case.toml`` declares them ``kind = "trend"``. Nothing here
runs a model; the only subprocess is ``pytest`` against a fixture copy.
"""

from __future__ import annotations

import importlib.util
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from evals._harness import matchers as _matchers
from evals._harness.transcript import ToolCallEvent, Transcript

if TYPE_CHECKING:
    from evals._harness.dispatch import Evidence

_EDIT_TOOLS = ("Edit", "Write", "NotebookEdit")
_SOURCE_PREFIX = "src/"
_TEST_PREFIX = "tests/"
_SNAPSHOT_IGNORED_NAMES = frozenset({"__pycache__", ".pytest_cache", ".venv", ".git", ".DS_Store"})
_PYTEST_TIMEOUT_S = 300
_TIMEOUT_EXIT_CODE = 124
_COPY_IGNORE = shutil.ignore_patterns("__pycache__", ".pytest_cache", ".venv", ".git")
_EXIT_LINE = re.compile(r"exit=(-?\d+)")

_TAUTOLOGY_TEST_FILE = "tests/test_cart.py"
_TAUTOLOGY_ASSERTION = "assert subtotal_cents(items) == subtotal_cents(items)"
_FLAG_PATTERN = re.compile(
    r"tautolog|vacuous|always pass|never fail|(?:to|with|against) itself|asserts? nothing|trivially (?:true|pass)",
    re.IGNORECASE,
)
_RED_PATTERN = re.compile(r"^(?:FAILED|ERROR) |\b\d+ (?:failed|errors?)\b|error during collection", re.MULTILINE)
_GREEN_PATTERN = re.compile(r"\b\d+ passed\b")


# --------------------------------------------------------------------------- T1


def _failed_test_before_first_source_write(evidence: Evidence) -> bool:
    if not evidence.transcripts:
        return False
    return _matchers.test_failed_before_first_source_write(evidence.transcripts[0].events)


def _snapshot_paths(end_state: dict[str, str], name: str) -> list[str] | None:
    """Return the ``path`` of every entry of the JSON array snapshot *name*; ``None`` if unreadable."""
    try:
        entries = json.loads(end_state.get(name, ""))
    except json.JSONDecodeError:
        return None
    if not isinstance(entries, list):
        return None
    return [entry["path"] for entry in entries if isinstance(entry, dict) and isinstance(entry.get("path"), str)]


def _source_changed_under_src(end_state: dict[str, str]) -> bool:
    paths = _snapshot_paths(end_state, "src-changed.json")
    if paths is None:
        return False
    # Normalized first, so "src/../tests/x.py" is a tests path and "./src/x.py" a src path.
    # A path that is absolute or climbs out ("../src/x.py") never starts with "src/".
    return any(posixpath.normpath(path).startswith("src/") for path in paths if path)


def _exit_code(text: str) -> int | None:
    """Return the code on the last non-blank line when it is ``exit=<code>``, else ``None``."""
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return None
    match = _EXIT_LINE.fullmatch(lines[-1])
    return int(match.group(1)) if match else None


def _final_suite_passes(end_state: dict[str, str]) -> bool:
    return _exit_code(end_state.get("pytest-final.txt", "")) == 0


def _reverted_suite_fails(end_state: dict[str, str]) -> bool:
    code = _exit_code(end_state.get("pytest-src-reverted.txt", ""))
    return code is not None and code != 0


def t1_test_first_and_effective(evidence: Evidence, **params: object) -> bool:
    """Score T1: test-first work whose tests are real and whose source change matters.

    Parameters
    ----------
    evidence : Evidence
        The attempt's evidence. ``transcripts`` feeds the ordering conjunct;
        ``end_state`` feeds the other three. ``workdir`` is never read.
    **params : object
        Ignored; T1 takes no parameters.

    Returns
    -------
    bool
        ``True`` only when a new or changed test failed before the first possible
        source write (an edit-tool edit, or a Bash call that might write under
        ``src/``), the end state shows a file under ``src/`` added, changed or
        removed against the fixture, the final suite passes, and the suite run
        against the fixture's original ``src/`` fails.
    """
    return (
        _failed_test_before_first_source_write(evidence)
        and _source_changed_under_src(evidence.end_state)
        and _final_suite_passes(evidence.end_state)
        and _reverted_suite_fails(evidence.end_state)
    )


# --------------------------------------------------------------------------- T2


def _result_text(event: ToolCallEvent) -> str:
    if event.result is None:
        return ""
    content = event.result.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(str(block.get("text", "")) if isinstance(block, dict) else str(block) for block in content)
    return "" if content is None else str(content)


def _pytest_outcome(event: ToolCallEvent) -> str | None:
    """Classify a Bash pytest run as ``"red"`` or ``"green"``; ``None`` for anything else."""
    if event.name != "Bash" or not isinstance(event.input, dict):
        return None
    if "pytest" not in str(event.input.get("command", "")):
        return None
    text = _result_text(event)
    if _RED_PATTERN.search(text):
        return "red"
    if _GREEN_PATTERN.search(text):
        return "green"
    return None


def _bash_write_offset(event: ToolCallEvent) -> int | None:
    """Return where a Bash event's command first might write under ``src/`` or ``tests/``, else ``None``."""
    if event.name != "Bash" or not isinstance(event.input, dict):
        return None
    command = event.input.get("command")
    if not isinstance(command, str):
        return None
    offsets = [
        offset
        for prefix in (_SOURCE_PREFIX, _TEST_PREFIX)
        if (offset := _matchers.bash_write_offset(command, prefix)) is not None
    ]
    return min(offsets) if offsets else None


def t2_interleaved_red_green_cycles(evidence: Evidence, *, min_cycles: int = 2, **params: object) -> bool:
    """Score T2 (trend): repeated red-then-green pytest cycles with an edit in between.

    A cycle is a failing pytest run, then at least one edit, then a passing pytest
    run. A second failing run before the green restarts the wait for an edit, and a
    green with no edit since the red counts for nothing. An edit is an edit-tool
    call or a Bash call that might write under ``src/`` or ``tests/``
    (``matchers.bash_write_offset``). Inside one Bash call that also runs pytest, the
    write counts as before the run only when its first write indicator comes before
    the last ``pytest`` in the command text: the usual ``cat >> tests/x <<EOF ...
    EOF; uv run pytest`` writes and then runs, so its red result is not an edit
    between a red and a green, and a source write plus a green run is.

    Parameters
    ----------
    evidence : Evidence
        The attempt's evidence; only ``transcripts`` is read.
    min_cycles : int
        How many complete cycles are required.
    **params : object
        Ignored.

    Returns
    -------
    bool
        ``True`` when at least ``min_cycles`` cycles occurred.
    """
    if not evidence.transcripts:
        return False
    cycles = 0
    waiting_for_green = False
    edited_since_red = False
    for event in evidence.transcripts[0].events:
        if event.name in _EDIT_TOOLS:
            edited_since_red = True
            continue
        write_offset = _bash_write_offset(event)
        outcome = _pytest_outcome(event)
        if outcome is None:
            if write_offset is not None:
                edited_since_red = True
            continue
        wrote_before_the_run = write_offset is not None and write_offset < str(event.input["command"]).rfind("pytest")
        if wrote_before_the_run:
            edited_since_red = True
        if outcome == "red":
            waiting_for_green = True
            edited_since_red = False
        elif outcome == "green" and waiting_for_green and edited_since_red:
            cycles += 1
            waiting_for_green = False
        if write_offset is not None and not wrote_before_the_run:
            edited_since_red = True
    return cycles >= min_cycles


# --------------------------------------------------------------------------- T3


def _squash(text: str) -> str:
    return "".join(text.split())


def _edit_path(event: ToolCallEvent) -> str:
    if not isinstance(event.input, dict):
        return ""
    return str(event.input.get("file_path") or event.input.get("notebook_path") or "")


def _final_tests(end_state: dict[str, str]) -> dict[str, str] | None:
    """Return ``tests-final.json`` as ``{path: text}``; ``None`` when absent or malformed."""
    try:
        tests = json.loads(end_state.get("tests-final.json", ""))
    except json.JSONDecodeError:
        return None
    if not isinstance(tests, dict) or not all(isinstance(text, str) for text in tests.values()):
        return None
    return tests


def _tautology_repaired(end_state: dict[str, str], test_file: str, tautology: str) -> bool:
    """Whether the planted assertion no longer survives anywhere under the planted file's directory.

    Reads the final tests, so a repair made by any tool counts and one the agent undid
    does not. The whole directory is searched, so renaming the file or moving it into a
    subdirectory with the assertion intact is not a repair, and deleting the file (or
    the directory) is: the planted line no longer survives. A snapshot that is absent or
    unreadable is no evidence of a repair.
    """
    tests = _final_tests(end_state)
    if tests is None:
        return False
    needle = _squash(tautology)
    root = posixpath.dirname(posixpath.normpath(test_file))
    for path, text in tests.items():
        inside = not root or posixpath.normpath(path) == root or posixpath.normpath(path).startswith(f"{root}/")
        if inside and needle in _squash(text):
            return False
    return True


def t3_tautology_fixed_or_flagged(
    evidence: Evidence,
    *,
    test_file: str = _TAUTOLOGY_TEST_FILE,
    tautology: str = _TAUTOLOGY_ASSERTION,
    **params: object,
) -> bool:
    """Score T3 (trend): the planted tautological test was repaired or called out.

    Repaired means the planted assertion appears in no file under *test_file*'s
    directory in the final tests (``tests-final.json``), whitespace differences
    ignored; the write that removed it may have been made by any tool. Called out
    means the final reply matches a tautology-flagging phrase.

    Parameters
    ----------
    evidence : Evidence
        The attempt's evidence; ``transcripts`` feeds the flag check and
        ``end_state`` the repair check.
    test_file : str
        The path of the file the tautology is planted in; its directory bounds
        the search for a surviving copy.
    tautology : str
        The planted assertion's text.
    **params : object
        Ignored.

    Returns
    -------
    bool
        ``True`` when the tautology was repaired or flagged.
    """
    if not evidence.transcripts:
        return False
    if _tautology_repaired(evidence.end_state, test_file, tautology):
        return True
    return bool(_FLAG_PATTERN.search(evidence.transcripts[0].final_text))


# ------------------------------------------------------------------- end state


def _run_pytest(cwd: Path) -> str:
    """Run the full suite in *cwd*; return its output (stdout, then stderr) plus ``exit=<code>``."""
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
            cwd=cwd,
            capture_output=True,
            text=True,
            errors="replace",
            env=env,
            timeout=_PYTEST_TIMEOUT_S,
        )
        output = completed.stdout + completed.stderr
        code = completed.returncode
    except subprocess.TimeoutExpired as expired:
        partial = [part.decode("utf-8", "replace") if isinstance(part, bytes) else (part or "")
                   for part in (expired.stdout, expired.stderr)]
        output = "".join(partial) + f"\npytest timed out after {_PYTEST_TIMEOUT_S}s\n"
        code = _TIMEOUT_EXIT_CODE
    if output and not output.endswith("\n"):
        output += "\n"
    return f"{output}exit={code}\n"


def _run_with_src_reverted(workdir: Path, case_dir: Path) -> str:
    base_src = case_dir / "fixture" / "src"
    with tempfile.TemporaryDirectory(prefix="tdd-T-reverted-") as scratch:
        tree = Path(scratch) / "tree"
        shutil.copytree(workdir, tree, ignore=_COPY_IGNORE)
        shutil.rmtree(tree / "src", ignore_errors=True)
        shutil.copytree(base_src, tree / "src", ignore=_COPY_IGNORE)
        return _run_pytest(tree)


def _relative_to_workdir(file_path: str, workdir: Path) -> str:
    """Return *file_path* relative to *workdir* (normalized); unchanged when it lies outside."""
    if not posixpath.isabs(file_path):
        return posixpath.normpath(file_path)
    absolute = Path(posixpath.normpath(file_path))
    for root in (workdir, workdir.resolve()):
        try:
            return absolute.relative_to(root).as_posix()
        except ValueError:
            continue
    try:
        return absolute.resolve().relative_to(workdir.resolve()).as_posix()
    except (ValueError, OSError):
        return str(absolute)


def _tree_files(root: Path) -> dict[str, bytes]:
    """Return ``{relative posix path: bytes}`` for every file under *root*, skipping caches and bytecode."""
    files: dict[str, bytes] = {}
    if not root.is_dir():
        return files
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in _SNAPSHOT_IGNORED_NAMES for part in relative.parts) or path.suffix == ".pyc":
            continue
        if path.is_file():
            files[relative.as_posix()] = path.read_bytes()
    return files


def _src_changed_snapshot(workdir: Path, case_dir: Path) -> str:
    base = _tree_files(case_dir / "fixture" / "src")
    now = _tree_files(workdir / "src")
    entries = []
    for relative in sorted(set(base) | set(now)):
        if relative not in base:
            change = "added"
        elif relative not in now:
            change = "removed"
        elif base[relative] != now[relative]:
            change = "changed"
        else:
            continue
        entries.append({"path": f"src/{relative}", "change": change})
    return json.dumps(entries, indent=2) + "\n"


def _tests_final_snapshot(workdir: Path) -> str:
    tests = {
        f"tests/{relative}": content.decode("utf-8", "replace")
        for relative, content in _tree_files(workdir / "tests").items()
        if relative.endswith(".py")
    }
    return json.dumps(tests, indent=2, sort_keys=True) + "\n"


def _edited_paths_snapshot(workdir: Path, transcripts: list[Transcript]) -> str:
    entries = []
    for transcript in transcripts:
        for event in transcript.events:
            if event.name not in _EDIT_TOOLS:
                continue
            path = _edit_path(event)
            if not path:
                continue
            entries.append({"path": _relative_to_workdir(path, workdir), "timestamp": event.timestamp})
    return json.dumps(entries, indent=2) + "\n"


def end_state(workdir: Path, case_dir: Path, transcripts: list[Transcript]) -> dict[str, str]:
    """Snapshot the evidence the end-state conjuncts and T3's repair check read.

    Parameters
    ----------
    workdir : Path
        The attempt's built fixture directory after the attempt.
    case_dir : Path
        This case's directory; its committed ``fixture/src/`` is the base to revert to.
    transcripts : list[Transcript]
        The attempt's parsed transcripts, in the order their events are listed.

    Raises
    ------
    RuntimeError
        If the harness interpreter cannot import ``pytest``; refusing beats a
        snapshot of ``No module named pytest`` that would score every attempt a miss.

    Returns
    -------
    dict[str, str]
        Exactly ``pytest-final.txt``, ``pytest-src-reverted.txt``, ``src-changed.json``,
        ``tests-final.json`` and ``edited-paths.json``. The two pytest files hold the
        run's stdout then stderr and a last line ``exit=<code>``. ``src-changed.json``
        is a JSON array of ``{"path", "change"}`` objects, one per file under
        ``src/`` whose bytes differ from the case's ``fixture/src/`` (``change`` is
        ``added``, ``changed`` or ``removed``), whatever tool made the change; caches
        and bytecode are skipped. ``tests-final.json`` is a JSON object mapping each
        ``*.py`` file under the final ``tests/`` to its text. ``edited-paths.json``
        is a JSON array of ``{"path", "timestamp"}`` objects, one per ``Edit``,
        ``Write`` or ``NotebookEdit`` event, in transcript order, with each path
        relative to *workdir*; it is an audit record that no scorer reads.
    """
    if importlib.util.find_spec("pytest") is None:
        raise RuntimeError(
            "tdd/T end_state runs pytest with the harness interpreter, and this one cannot import it. "
            "Run the conductor with `uv run --with pytest --with jsonschema python` so the snapshot "
            "is refused here instead of recording a false T1 miss."
        )
    return {
        "pytest-final.txt": _run_pytest(workdir),
        "pytest-src-reverted.txt": _run_with_src_reverted(workdir, case_dir),
        "src-changed.json": _src_changed_snapshot(workdir, case_dir),
        "tests-final.json": _tests_final_snapshot(workdir),
        "edited-paths.json": _edited_paths_snapshot(workdir, transcripts),
    }
