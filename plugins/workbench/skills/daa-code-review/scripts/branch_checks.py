#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml", "ruff"]
# ///
"""Run the diff-aware review checks on a branch and print one JSON report.

Adapted from ``run_checks.py`` in the ``reviewing-gitlab-mrs`` skill by
Biodun Iwayemi, the upstream whose behavior this module ports into the
workbench conventions (numpy docstrings, ``pathlib``, the shared
``models.Severity`` levels).

Every check is isolated: a tool that crashes, times out, or emits unusable
output yields ``status: error`` for that check, never a crash and never a
false pass. Findings carry ``on_changed_line``, computed from
a ``git diff -U0`` of the merge-base with ``--target`` against the working
tree, so uncommitted and untracked work is reviewed too (a new file counts
every line as changed). Values reported by
hardcoded-credential rules are redacted and bandit's ``code`` field is never
emitted, so the report is safe to quote in a review.

Static tools run through ``uvx`` or the ``ruff`` already on PATH and never
import the branch's code. ``pytest`` and ``mypy`` import it, so they run only
with ``--run-project-tools``.

Examples
--------
Run from, or point at, a git worktree::

    uv run --script scripts/branch_checks.py --target origin/dev \
        --worktree ../review-wt --run-project-tools

Exit status is 0 when the run completed (whatever it found) and 2 when the
target ref or worktree is invalid.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil

# Only fixed argument lists are executed, never through a shell.
import subprocess  # nosec B404
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from models import Severity

# Files that change how the project installs or how tests start up; editing
# them lets a branch run code as soon as pytest or mypy imports the project.
BOOTSTRAP_FILES = frozenset(
    {
        "pyproject.toml",
        "uv.lock",
        "setup.py",
        "conftest.py",
        "Makefile",
        "Dockerfile",
        ".gitlab-ci.yml",
        "dbt_project.yml",
        "packages.yml",
        "profiles.yml",
    }
)
# bandit's hardcoded-credential tests; their issue_text quotes the secret.
SECRET_TESTS = frozenset({"B105", "B106", "B107"})
REDACTED_CREDENTIAL = "possible hardcoded credential; value redacted"
# A hung tool must not stall a review.
TOOL_TIMEOUT_SECONDS = 600
# SQLFluff codes that mean a file could not be templated or parsed, so it was
# not really linted.
SQLFLUFF_UNLINTED_CODES = frozenset({"TMP", "PRS"})
# pydoclint codes about type-hint placement and spelling; any setting of its
# type-hint options flags either typed or untyped code, so they are dropped
# and only missing or extra parameters, returns and raises are reported.
PYDOCLINT_IGNORED = frozenset({"DOC105", "DOC106", "DOC107", "DOC108", "DOC605"})
NUMPY_DOCSTRINGS = "lint.pydocstyle.convention = 'numpy'"
HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
PYDOCLINT_RE = re.compile(r"^\s+(\d+): (DOC\d+): (.*)$")
MYPY_RE = re.compile(r"^(.+?):(\d+): error: (.*)$")
_TEST_FILE_NAMES = ("conftest.py",)

Finding = dict[str, Any]
Runner = Callable[[list[str], Path], "subprocess.CompletedProcess[str]"]


class ToolError(RuntimeError):
    """A tool could not be started, timed out, or produced unusable output."""


def run_command(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run a command without a shell and capture its output.

    This is the one place a subprocess is started; tests substitute a fake
    with the same signature.

    Parameters
    ----------
    cmd : list of str
        Program and arguments.
    cwd : pathlib.Path
        Working directory.

    Returns
    -------
    subprocess.CompletedProcess
        The finished process. A non-zero exit code is not an error here,
        because linters use it to report findings.

    Raises
    ------
    ToolError
        If the program is missing or exceeds ``TOOL_TIMEOUT_SECONDS``.
    """
    try:
        # Fixed argument list from this module; no shell is involved.
        return subprocess.run(  # nosec B603
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=TOOL_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ToolError(f"{cmd[0]} is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise ToolError(f"{cmd[0]} timed out after {TOOL_TIMEOUT_SECONDS}s") from exc


def is_test_file(path: str) -> bool:
    """Return whether ``path`` looks like a test module.

    Parameters
    ----------
    path : str
        Path relative to the worktree.

    Returns
    -------
    bool
        True for files under a ``tests`` or ``test`` directory, named
        ``test_*.py`` or ``*_test.py``, or named ``conftest.py``.
    """
    parts = Path(path).parts
    name = parts[-1]
    return (
        any(p in {"tests", "test"} for p in parts[:-1])
        or name.startswith("test_")
        or name.endswith("_test.py")
        or name in _TEST_FILE_NAMES
    )


def _analyze_python(path: Path):  # noqa: ANN202 - returns models.AnalysisResult
    from python_analyzer import analyze_python_file

    return analyze_python_file(path)


def _analyze_markdown(path: Path):  # noqa: ANN202 - returns models.AnalysisResult
    from markdown_analyzer import analyze_markdown_file

    return analyze_markdown_file(path)


@dataclass
class Context:
    """Files under review, the lines changed in each, and the tool seams.

    Attributes
    ----------
    worktree : pathlib.Path
        Root of the checked-out branch.
    changed : dict of str to set of int
        Changed file paths (relative to ``worktree``) mapped to the line
        numbers the branch added or modified.
    run : Runner
        Subprocess seam; defaults to ``run_command``.
    analyze_python : callable
        Seam for ``python_analyzer.analyze_python_file``.
    analyze_markdown : callable
        Seam for ``markdown_analyzer.analyze_markdown_file``.
    """

    worktree: Path
    changed: dict[str, set[int]]
    run: Runner = run_command
    analyze_python: Callable[[Path], Any] = _analyze_python
    analyze_markdown: Callable[[Path], Any] = _analyze_markdown

    def files(self, *suffixes: str) -> list[str]:
        """Return changed files ending in any of ``suffixes``, sorted.

        Parameters
        ----------
        *suffixes : str
            File suffixes such as ``".py"``.

        Returns
        -------
        list of str
            Matching changed paths relative to the worktree.
        """
        return sorted(p for p in self.changed if p.endswith(suffixes))

    @property
    def py(self) -> list[str]:
        """Return the changed Python files."""
        return self.files(".py")

    @property
    def non_test_py(self) -> list[str]:
        """Return the changed Python files that are not tests."""
        return [p for p in self.py if not is_test_file(p)]

    def relative(self, path: str) -> str:
        """Return ``path`` relative to the worktree when it lies inside it.

        Parameters
        ----------
        path : str
            Absolute or relative path reported by a tool.

        Returns
        -------
        str
            Path relative to the worktree, with any ``./`` prefix removed.
        """
        candidate = Path(path)
        if candidate.is_absolute():
            try:
                return candidate.resolve().relative_to(self.worktree).as_posix()
            except ValueError:
                return path
        text = candidate.as_posix()
        return text[2:] if text.startswith("./") else text

    def finding(
        self,
        path: str,
        line: int,
        rule_id: str,
        severity: Severity,
        message: str,
    ) -> Finding:
        """Build a finding tagged with whether it is on a changed line.

        Parameters
        ----------
        path : str
            File path, absolute or relative to the worktree.
        line : int
            1-based line number.
        rule_id : str
            Tool rule identifier.
        severity : Severity
            Severity level.
        message : str
            Human-readable description. Callers must pass already-redacted
            text.

        Returns
        -------
        dict
            The finding with ``file``, ``line``, ``rule_id``, ``severity``,
            ``message`` and ``on_changed_line``.
        """
        rel = self.relative(path)
        return {
            "file": rel,
            "line": line,
            "rule_id": rule_id,
            "severity": severity.value,
            "message": message,
            "on_changed_line": line in self.changed.get(rel, set()),
        }


@dataclass
class CheckResult:
    """Outcome of one check.

    Attributes
    ----------
    tool : str
        Check name as it should appear in the review's table.
    scope : str
        What the check covered, for example ``"2 changed .py files"``.
    status : str
        ``pass``, ``fail``, ``not_run`` or ``error``.
    reason : str
        Why the check did not run, errored, or passed with a caveat.
    findings : list of dict
        Individual results.
    """

    tool: str
    scope: str
    status: str
    reason: str = ""
    findings: list[Finding] = field(default_factory=list)


def _scope(files: list[str], kind: str) -> str:
    return f"{len(files)} changed {kind} file(s)"


def not_run(tool: str, reason: str) -> CheckResult:
    """Build a ``not_run`` result.

    Parameters
    ----------
    tool : str
        Check name.
    reason : str
        Why nothing ran.

    Returns
    -------
    CheckResult
        A result with an empty scope.
    """
    return CheckResult(tool, "", "not_run", reason)


def done(
    tool: str, scope: str, findings: list[Finding], reason: str = ""
) -> CheckResult:
    """Build ``pass`` or ``fail`` from the findings.

    Parameters
    ----------
    tool : str
        Check name.
    scope : str
        What the check covered.
    findings : list of dict
        Findings produced.
    reason : str, optional
        Caveat to carry.

    Returns
    -------
    CheckResult
        ``fail`` when there are findings, otherwise ``pass``.
    """
    return CheckResult(tool, scope, "fail" if findings else "pass", reason, findings)


def parse_json(text: str, tool: str) -> Any:
    """Parse a tool's JSON output.

    Parameters
    ----------
    text : str
        Raw standard output.
    tool : str
        Tool name, used in the error message.

    Returns
    -------
    object
        The decoded JSON value.

    Raises
    ------
    ToolError
        If the output is not valid JSON.
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ToolError(f"{tool} did not produce JSON") from exc


def changed_lines(worktree: Path, target: str, run: Runner = run_command) -> dict[str, set[int]]:
    """Map each added, changed or untracked file to its changed lines.

    Parameters
    ----------
    worktree : pathlib.Path
        Root of the checked-out branch.
    target : str
        Git revision of the target branch, such as ``origin/dev``.
    run : Runner, optional
        Subprocess seam.

    Returns
    -------
    dict of str to set of int
        File paths relative to ``worktree`` mapped to changed line numbers.
        Files with no hunks (new empty files, mode changes) map to an empty
        set.

    Raises
    ------
    ToolError
        If ``git diff`` fails, for example because ``target`` is unknown.
    """
    base = ["git", "-c", "core.quotepath=off", "diff", "--relative", "--no-color"]
    merge_base = run(["git", "merge-base", target, "HEAD"], worktree)
    if merge_base.returncode != 0:
        raise ToolError(merge_base.stderr.strip() or "git merge-base failed")
    # One revision, no "...HEAD": git then diffs the merge-base against the
    # working tree, so staged and unstaged work is reviewed before it is
    # committed. On a clean checkout this equals the three-dot diff.
    span = merge_base.stdout.strip()
    names = run([*base, "--name-only", "-z", "--diff-filter=ACMR", span], worktree)
    if names.returncode != 0:
        raise ToolError(names.stderr.strip() or "git diff failed")
    changed: dict[str, set[int]] = {n: set() for n in names.stdout.split("\0") if n}
    untracked = run(
        ["git", "-c", "core.quotepath=off", "ls-files", "--others", "--exclude-standard", "-z"],
        worktree,
    )
    if untracked.returncode != 0:
        raise ToolError(untracked.stderr.strip() or "git ls-files failed")
    for name in (n for n in untracked.stdout.split("\0") if n):
        try:
            text = (worktree / name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        changed[name] = set(range(1, len(text.splitlines()) + 1))
    patch = run([*base, "-U0", "--diff-filter=ACMR", span], worktree)
    if patch.returncode != 0:
        raise ToolError(patch.stderr.strip() or "git diff failed")
    current: str | None = None
    for line in patch.stdout.splitlines():
        if line.startswith("diff --git "):
            current = None
        elif line.startswith("+++ "):
            name = line[4:].rstrip("\t")
            current = name[2:] if name.startswith("b/") else None
            if current is not None:
                changed.setdefault(current, set())
        elif current is not None and (match := HUNK_RE.match(line)):
            start, count = int(match[3]), int(match[4] if match[4] is not None else 1)
            changed[current].update(range(start, start + count))
    return changed


def ruff_prefix() -> list[str]:
    """Return the command prefix that runs ruff.

    Returns
    -------
    list of str
        ``["ruff"]`` when ruff is on PATH, else ``["uvx", "ruff"]``.
    """
    return ["ruff"] if shutil.which("ruff") else ["uvx", "ruff"]


def check_ruff_lint(ctx: Context) -> CheckResult:
    """Lint changed Python files with ``python_analyzer``.

    Parameters
    ----------
    ctx : Context
        Files under review.

    Returns
    -------
    CheckResult
        The analyzer's findings, minus its format-check issue (the
        ``ruff-format`` check owns that). The repo's ruff config governs
        when one exists; otherwise the analyzer's fallback rules apply.

    Raises
    ------
    ToolError
        If ruff is not available to the analyzer.
    """
    tool, files = "ruff-lint", ctx.py
    if not files:
        return not_run(tool, "no changed Python files")
    findings: list[Finding] = []
    for rel in files:
        result = ctx.analyze_python(ctx.worktree / rel)
        if "ruff" not in result.tools_used:
            raise ToolError("ruff is not available")
        for issue in result.issues:
            if issue.rule_id == "FORMAT":
                continue
            findings.append(
                ctx.finding(
                    rel,
                    issue.location.line_start,
                    issue.rule_id,
                    issue.severity,
                    issue.message,
                )
            )
    return done(tool, _scope(files, "Python"), findings)


def ruff_findings(
    ctx: Context, tool: str, files: list[str], extra: list[str]
) -> list[Finding]:
    """Run ``ruff check`` as JSON and convert the output to minor findings.

    Parameters
    ----------
    ctx : Context
        Files under review.
    tool : str
        Check name, for error messages.
    files : list of str
        Files to lint.
    extra : list of str
        Extra ``ruff check`` arguments.

    Returns
    -------
    list of dict
        One minor finding per diagnostic. Suggested fixes are dropped
        because they can contain source text.
    """
    proc = ctx.run(
        [*ruff_prefix(), "check", "--output-format", "json", *extra, *files],
        ctx.worktree,
    )
    return [
        ctx.finding(
            d["filename"],
            d["location"]["row"],
            d["code"],
            Severity.MINOR,
            d["message"],
        )
        for d in parse_json(proc.stdout, tool)
    ]


def check_docstring_layout(ctx: Context) -> CheckResult:
    """Check numpy docstring layout on changed non-test Python files.

    Parameters
    ----------
    ctx : Context
        Files under review.

    Returns
    -------
    CheckResult
        Ruff ``D`` rules under the numpy convention, as minor findings.
    """
    tool, files = "docstring-layout", ctx.non_test_py
    if not files:
        return not_run(tool, "no changed non-test Python files")
    extra = ["--select", "D", "--config", NUMPY_DOCSTRINGS]
    return done(
        tool, _scope(files, "Python"), ruff_findings(ctx, tool, files, extra)
    )


def format_differences(diff: str) -> list[tuple[str, set[int]]]:
    """Find the current-file lines each formatter hunk actually changes.

    Context lines are ignored, so a hunk next to an edited line does not count
    as touching it. A pure insertion counts as touching the lines on either
    side of the insertion point.

    Parameters
    ----------
    diff : str
        Unified diff from ``ruff format --diff``; its old side is the file as
        it is in the worktree.

    Returns
    -------
    list of tuple of (str, set of int)
        One entry per hunk: the file path and the affected line numbers.
    """
    hunks: list[tuple[str, set[int]]] = []
    path: str | None = None
    old_line = 0
    replacing = False
    for line in diff.splitlines():
        if line.startswith("--- "):
            path = line[4:].strip()
        elif line.startswith("+++ "):
            continue
        elif path and (match := HUNK_RE.match(line)):
            old_line = int(match[1])
            replacing = False
            hunks.append((path, set()))
        elif hunks and line.startswith("-"):
            hunks[-1][1].add(old_line)
            old_line += 1
            replacing = True
        elif hunks and line.startswith("+"):
            # An addition that replaces removed lines touches only those; a
            # pure insertion touches the neighbours on either side.
            if not replacing:
                hunks[-1][1].update({max(old_line - 1, 1), old_line})
        elif hunks and line.startswith(" "):
            old_line += 1
            replacing = False
    return [(p, lines) for p, lines in hunks if lines]


def check_ruff_format(ctx: Context) -> CheckResult:
    """Check formatting and separate branch-caused from pre-existing differences.

    Parameters
    ----------
    ctx : Context
        Files under review.

    Returns
    -------
    CheckResult
        ``pass`` with reason ``pre-existing`` when every difference sits on
        unchanged lines; otherwise ``fail`` with ONE minor finding for the
        whole run.

    Raises
    ------
    ToolError
        If ``ruff format`` exits with anything but 0 (clean) or 1 (differences).
    """
    tool, files = "ruff-format", ctx.py
    if not files:
        return not_run(tool, "no changed Python files")
    proc = ctx.run([*ruff_prefix(), "format", "--diff", *files], ctx.worktree)
    if proc.returncode not in (0, 1):
        raise ToolError(f"ruff format exited {proc.returncode}")
    hits: list[tuple[str, set[int]]] = []
    any_diff = False
    for path, lines in format_differences(proc.stdout):
        any_diff = True
        rel = ctx.relative(path)
        touched = lines & ctx.changed.get(rel, set())
        if touched:
            hits.append((rel, touched))
    scope = _scope(files, "Python")
    if not hits:
        return CheckResult(
            tool, scope, "pass", "pre-existing" if any_diff else ""
        )
    first_file, first_lines = hits[0]
    names = sorted({p for p, _ in hits})
    finding = ctx.finding(
        first_file,
        min(first_lines),
        "FORMAT",
        Severity.MINOR,
        f"ruff format would change changed lines in {len(names)} file(s): "
        + ", ".join(names),
    )
    return done(tool, scope, [finding])


def check_pydoclint(ctx: Context) -> CheckResult:
    """Compare numpy docstrings with function signatures.

    Parameters
    ----------
    ctx : Context
        Files under review.

    Returns
    -------
    CheckResult
        pydoclint result as minor findings. Findings point at the ``def``
        line, so a finding with ``on_changed_line`` false can still belong
        to a changed function.
    """
    tool, files = "pydoclint", ctx.non_test_py
    if not files:
        return not_run(tool, "no changed non-test Python files")
    cmd = [
        "uvx",
        "pydoclint",
        "--style=numpy",
        "--check-return-types=False",
        "--quiet",
        *files,
    ]
    proc = ctx.run(cmd, ctx.worktree)
    findings: list[Finding] = []
    current: str | None = None
    for line in (proc.stdout + proc.stderr).splitlines():
        match = PYDOCLINT_RE.match(line)
        if match and current and match[2] not in PYDOCLINT_IGNORED:
            findings.append(
                ctx.finding(
                    current, int(match[1]), match[2], Severity.MINOR, match[3]
                )
            )
        elif not match and line.strip().endswith(".py") and not line.startswith(" "):
            current = line.strip()
    return done(tool, _scope(files, "Python"), findings)


def file_contains(worktree: Path, name: str, marker: str) -> bool:
    """Return whether a repository file exists and contains ``marker``.

    Parameters
    ----------
    worktree : pathlib.Path
        Root of the checked-out branch.
    name : str
        File name relative to ``worktree``.
    marker : str
        Text to look for, such as a TOML or INI section header.

    Returns
    -------
    bool
        True when the file exists and contains ``marker``.
    """
    path = worktree / name
    return path.is_file() and marker in path.read_text(errors="replace")


def bandit_config(worktree: Path) -> list[str]:
    """Return bandit arguments for the repository's own configuration.

    Parameters
    ----------
    worktree : pathlib.Path
        Root of the checked-out branch.

    Returns
    -------
    list of str
        ``-c``/``--ini`` arguments, or an empty list when there is no config.
    """
    if file_contains(worktree, "pyproject.toml", "[tool.bandit"):
        return ["-c", "pyproject.toml"]
    if (worktree / ".bandit").is_file():
        return ["--ini", ".bandit"]
    for name in ("bandit.yaml", "bandit.yml"):
        if (worktree / name).is_file():
            return ["-c", name]
    return []


def bandit_severity(severity: str, confidence: str, test_id: str) -> Severity:
    """Map bandit's severity and confidence to a review severity.

    Parameters
    ----------
    severity : str
        bandit ``issue_severity``: LOW, MEDIUM or HIGH.
    confidence : str
        bandit ``issue_confidence``: LOW, MEDIUM or HIGH.
    test_id : str
        bandit test id, for example ``B105``.

    Returns
    -------
    Severity
        HIGH with MEDIUM or HIGH confidence is a blocker; HIGH with LOW
        confidence and MEDIUM are major; LOW is minor. Hardcoded-credential
        tests are at least major.
    """
    sev, conf = severity.upper(), confidence.upper()
    if sev == "HIGH":
        level = Severity.BLOCKER if conf in {"MEDIUM", "HIGH"} else Severity.MAJOR
    elif sev == "MEDIUM":
        level = Severity.MAJOR
    else:
        level = Severity.MINOR
    if test_id in SECRET_TESTS and level in {Severity.MINOR, Severity.NIT}:
        return Severity.MAJOR
    return level


def check_bandit(ctx: Context) -> CheckResult:
    """Scan changed non-test Python files with bandit, redacting secrets.

    Parameters
    ----------
    ctx : Context
        Files under review.

    Returns
    -------
    CheckResult
        bandit result. bandit's ``code`` field is never copied, and the
        message of a hardcoded-credential finding is replaced, because both
        can contain the secret value.
    """
    tool, files = "bandit", ctx.non_test_py
    if not files:
        return not_run(tool, "no changed non-test Python files")
    cmd = [
        "uvx",
        "--from",
        "bandit[toml]",
        "bandit",
        "-q",
        "-f",
        "json",
        *bandit_config(ctx.worktree),
        *files,
    ]
    report = parse_json(ctx.run(cmd, ctx.worktree).stdout, tool)
    findings = [
        ctx.finding(
            r["filename"],
            r["line_number"],
            r["test_id"],
            bandit_severity(r["issue_severity"], r["issue_confidence"], r["test_id"]),
            REDACTED_CREDENTIAL if r["test_id"] in SECRET_TESTS else r["issue_text"],
        )
        for r in report.get("results", [])
    ]
    errors = report.get("errors", [])
    scope = _scope(files, "Python")
    if errors and not findings:
        return CheckResult(
            tool, scope, "error", f"bandit could not scan {len(errors)} file(s)"
        )
    reason = f"bandit could not scan {len(errors)} file(s)" if errors else ""
    return done(tool, scope, findings, reason)


def has_sqlfluff_config(worktree: Path) -> bool:
    """Return whether the repository configures SQLFluff itself.

    Parameters
    ----------
    worktree : pathlib.Path
        Root of the checked-out branch.

    Returns
    -------
    bool
        True when ``.sqlfluff`` exists or ``setup.cfg``, ``tox.ini`` or
        ``pyproject.toml`` has a SQLFluff section.
    """
    if (worktree / ".sqlfluff").is_file():
        return True
    markers = {
        "setup.cfg": "[sqlfluff",
        "tox.ini": "[sqlfluff",
        "pyproject.toml": "[tool.sqlfluff",
    }
    return any(
        file_contains(worktree, name, marker) for name, marker in markers.items()
    )


def check_sqlfluff(ctx: Context) -> CheckResult:
    """Lint changed SQL files, using the repo's config or the Snowflake dialect.

    Parameters
    ----------
    ctx : Context
        Files under review.

    Returns
    -------
    CheckResult
        SQLFluff result with minor findings. Files that failed templating or
        parsing (codes ``TMP``, ``PRS``) are named in ``reason`` and make the
        check ``error``; their violations are not reported as findings.
    """
    tool, files = "sqlfluff", ctx.files(".sql")
    if not files:
        return not_run(tool, "no changed SQL files")
    dialect = [] if has_sqlfluff_config(ctx.worktree) else ["--dialect", "snowflake"]
    proc = ctx.run(
        ["uvx", "sqlfluff", "lint", "--format", "json", *dialect, *files],
        ctx.worktree,
    )
    findings: list[Finding] = []
    unlinted: set[str] = set()
    for entry in parse_json(proc.stdout, tool):
        for v in entry.get("violations", []):
            if v.get("code") in SQLFLUFF_UNLINTED_CODES:
                unlinted.add(ctx.relative(entry["filepath"]))
                continue
            line = v.get("start_line_no", v.get("line_no", 0))
            findings.append(
                ctx.finding(
                    entry["filepath"],
                    line,
                    v.get("code") or "",
                    Severity.MINOR,
                    v.get("description") or "",
                )
            )
    scope = _scope(files, "SQL")
    if unlinted:
        reason = f"not linted (templating or parsing): {', '.join(sorted(unlinted))}"
        return CheckResult(tool, scope, "error", reason, findings)
    return done(tool, scope, findings)


def check_markdown(ctx: Context) -> CheckResult:
    """Analyze changed Markdown files with ``markdown_analyzer``.

    Parameters
    ----------
    ctx : Context
        Files under review.

    Returns
    -------
    CheckResult
        The analyzer's findings with its severities (major, minor, nit).
    """
    tool, files = "markdown", ctx.files(".md")
    if not files:
        return not_run(tool, "no changed Markdown files")
    findings: list[Finding] = []
    for rel in files:
        result = ctx.analyze_markdown(ctx.worktree / rel)
        for issue in result.issues:
            findings.append(
                ctx.finding(
                    rel,
                    issue.location.line_start,
                    issue.rule_id,
                    issue.severity,
                    issue.message,
                )
            )
    return done(tool, _scope(files, "Markdown"), findings)


def check_yaml(ctx: Context) -> CheckResult:
    """Parse changed YAML files with a safe loader that tolerates custom tags.

    Parameters
    ----------
    ctx : Context
        Files under review.

    Returns
    -------
    CheckResult
        One blocker finding per file that fails to parse, at the error line.

    Raises
    ------
    ToolError
        If PyYAML is not importable.
    """
    tool, files = "yaml", ctx.files(".yml", ".yaml")
    if not files:
        return not_run(tool, "no changed YAML files")
    try:
        import yaml
    except ImportError as exc:
        raise ToolError("pyyaml is not installed") from exc

    class TagTolerantLoader(yaml.SafeLoader):
        """SafeLoader that accepts application tags such as ``!reference``."""

    # GitLab CI (`!reference`), Dagster and dbt configs use custom tags. They
    # are valid YAML, so only the syntax is checked and the value is ignored.
    TagTolerantLoader.add_multi_constructor("!", lambda loader, suffix, node: None)

    findings: list[Finding] = []
    for rel in files:
        text = (ctx.worktree / rel).read_text(encoding="utf-8", errors="replace")
        try:
            for _ in yaml.load_all(text, Loader=TagTolerantLoader):  # noqa: S506
                pass
        except yaml.YAMLError as exc:
            mark = getattr(exc, "problem_mark", None)
            line = mark.line + 1 if mark is not None else 1
            problem = getattr(exc, "problem", None) or "invalid YAML"
            findings.append(
                ctx.finding(rel, line, "yaml-parse", Severity.BLOCKER, str(problem))
            )
    return done(tool, _scope(files, "YAML"), findings)


def project_module(
    ctx: Context, tool: str, module_args: list[str]
) -> subprocess.CompletedProcess[str] | CheckResult:
    """Run ``uv run python -m <module>`` in the project environment.

    Using ``python -m`` stops ``uv run`` from silently falling back to a
    copy of the tool on ``PATH`` when the project does not provide it.

    Parameters
    ----------
    ctx : Context
        Files under review.
    tool : str
        Check name.
    module_args : list of str
        Module name followed by its arguments.

    Returns
    -------
    subprocess.CompletedProcess or CheckResult
        The finished process, or a ``not_run`` result when there is no
        project or the module is not one of its dependencies.
    """
    if not (ctx.worktree / "pyproject.toml").is_file():
        return not_run(tool, "no pyproject.toml (no project environment)")
    proc = ctx.run(["uv", "run", "python", "-m", *module_args], ctx.worktree)
    if f"No module named {module_args[0]}" in proc.stderr + proc.stdout:
        return not_run(tool, f"{module_args[0]} is not a project dependency")
    return proc


def check_pytest(ctx: Context) -> CheckResult:
    """Run the test suite in the project environment.

    Parameters
    ----------
    ctx : Context
        Files under review.

    Returns
    -------
    CheckResult
        pytest result. Only failing test ids and the summary line are kept;
        tracebacks are suppressed so test data does not leak into the report.
        Each failing test is a blocker finding.
    """
    tool = "pytest"
    proc = project_module(
        ctx, tool, ["pytest", "-q", "--tb=no", "-rfE", "-p", "no:cacheprovider"]
    )
    if isinstance(proc, CheckResult):
        return proc
    lines = proc.stdout.splitlines()
    summary = lines[-1] if lines else ""
    if proc.returncode == 5:
        return not_run(tool, "no tests collected")
    findings = []
    for ln in lines:
        if ln.startswith(("FAILED ", "ERROR ")):
            test_id = ln.split(" ", 1)[1].split(" - ")[0].strip()
            findings.append(
                ctx.finding(
                    test_id.split("::")[0],
                    0,
                    "test-failure",
                    Severity.BLOCKER,
                    f"failing test: {test_id}",
                )
            )
    if proc.returncode != 0 and not findings:
        return CheckResult(tool, "whole suite", "error", summary or "pytest failed")
    return CheckResult(
        tool, "whole suite", "fail" if findings else "pass", summary, findings
    )


def check_mypy(ctx: Context) -> CheckResult:
    """Type-check changed Python files in the project environment.

    Parameters
    ----------
    ctx : Context
        Files under review.

    Returns
    -------
    CheckResult
        mypy result; every reported error is a blocker finding.
    """
    tool, files = "mypy", ctx.py
    if not files:
        return not_run(tool, "no changed Python files")
    proc = project_module(ctx, tool, ["mypy", "--no-error-summary", *files])
    if isinstance(proc, CheckResult):
        return proc
    findings = [
        ctx.finding(m[1], int(m[2]), "mypy", Severity.BLOCKER, m[3])
        for m in map(MYPY_RE.match, proc.stdout.splitlines())
        if m
    ]
    scope = _scope(files, "Python")
    if proc.returncode != 0 and not findings:
        return CheckResult(tool, scope, "error", f"mypy exited {proc.returncode}")
    return done(tool, scope, findings)


STATIC_CHECKS: tuple[tuple[str, Callable[[Context], CheckResult]], ...] = (
    ("ruff-lint", check_ruff_lint),
    ("ruff-format", check_ruff_format),
    ("docstring-layout", check_docstring_layout),
    ("pydoclint", check_pydoclint),
    ("bandit", check_bandit),
    ("sqlfluff", check_sqlfluff),
    ("markdown", check_markdown),
    ("yaml", check_yaml),
)
PROJECT_CHECKS: tuple[tuple[str, Callable[[Context], CheckResult]], ...] = (
    ("pytest", check_pytest),
    ("mypy", check_mypy),
)


def safe_run(
    name: str, check: Callable[[Context], CheckResult], ctx: Context
) -> CheckResult:
    """Run one check, turning any failure into an ``error`` result.

    Parameters
    ----------
    name : str
        Check name for the ``error`` result.
    check : callable
        A check function.
    ctx : Context
        Files under review.

    Returns
    -------
    CheckResult
        The check's result, or an ``error`` result naming the problem. A
        crashed tool is never reported as a pass.
    """
    try:
        return check(ctx)
    except ToolError as exc:
        return CheckResult(name, "", "error", str(exc))
    except Exception as exc:  # noqa: BLE001 - isolation is the point
        return CheckResult(name, "", "error", f"{type(exc).__name__}: {exc}")


def build_report(
    ctx: Context, target: str, run_project_tools: bool
) -> dict[str, Any]:
    """Run every check and assemble the JSON-ready report.

    Parameters
    ----------
    ctx : Context
        Files under review.
    target : str
        Target ref, echoed in the report.
    run_project_tools : bool
        Whether ``pytest`` and ``mypy`` may run.

    Returns
    -------
    dict
        ``target``, ``changed_files``, ``bootstrap_files_changed`` and
        ``checks``.
    """
    results = [safe_run(name, fn, ctx) for name, fn in STATIC_CHECKS]
    for name, fn in PROJECT_CHECKS:
        if run_project_tools:
            results.append(safe_run(name, fn, ctx))
        else:
            results.append(not_run(name, "needs --run-project-tools"))
    return {
        "target": target,
        "changed_files": sorted(ctx.changed),
        "bootstrap_files_changed": sorted(
            p for p in ctx.changed if Path(p).name in BOOTSTRAP_FILES
        ),
        "checks": [asdict(r) for r in results],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Parameters
    ----------
    argv : list of str, optional
        Arguments to parse. Default is ``sys.argv[1:]``.

    Returns
    -------
    argparse.Namespace
        Parsed arguments.
    """
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument(
        "--target", required=True, help="target ref, e.g. origin/dev"
    )
    parser.add_argument(
        "--worktree",
        type=Path,
        default=Path.cwd(),
        help="checked-out branch (default: cwd)",
    )
    parser.add_argument(
        "--run-project-tools",
        action="store_true",
        help="also run pytest and mypy, which import and execute the branch's code",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, run: Runner = run_command) -> int:
    """Run the checks and print the JSON report.

    Parameters
    ----------
    argv : list of str, optional
        Command-line arguments. Default is ``sys.argv[1:]``.
    run : Runner, optional
        Subprocess seam.

    Returns
    -------
    int
        0 when the report was produced, 2 when the worktree or target ref is
        invalid.
    """
    args = parse_args(argv)
    worktree = args.worktree.resolve()
    if not worktree.is_dir():
        print(f"branch_checks: worktree not found: {worktree}", file=sys.stderr)
        return 2
    try:
        top = run(["git", "rev-parse", "--show-toplevel"], worktree)
        if top.returncode != 0:
            raise ToolError(f"not a git worktree: {worktree}")
        verify = run(
            ["git", "rev-parse", "--verify", "--quiet", f"{args.target}^{{commit}}"],
            worktree,
        )
        if verify.returncode != 0:
            raise ToolError(f"unknown target ref: {args.target}")
        ctx = Context(worktree, changed_lines(worktree, args.target, run), run=run)
    except ToolError as exc:
        print(f"branch_checks: {exc}", file=sys.stderr)
        return 2
    report = build_report(ctx, args.target, args.run_project_tools)
    json.dump(report, sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
