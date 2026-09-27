"""Shared fakes for every pr_land test module.

``gh`` never runs for real in these suites: a ``FakeGh`` answers scripted argv
prefixes and fails loudly on anything unscripted, so a call the code was never
meant to make (the combined-status endpoint, ``gh pr checks``) turns a test red
instead of quietly returning something plausible. ``git`` does run for real,
against a bare ``origin`` on local disk, because SHA resolution, pushes and
remote URLs are process-boundary behaviour a mock would only re-assert.

Sibling test modules rely on this file as-is; extend it only in a way that
keeps every existing name and behaviour.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pr_land import Result  # noqa: E402


def json_result(payload: object) -> Result:
    """Return a successful ``gh`` Result whose stdout is *payload* as JSON."""
    return Result(returncode=0, stdout=json.dumps(payload), stderr="")


def http_error(status: int, message: str) -> Result:
    """Return a failed ``gh api`` Result shaped like the real one.

    On an HTTP error ``gh api`` exits 1, prints the response body on stdout and
    ``gh: <message> (HTTP <status>)`` on stderr.
    """
    body = {"message": message, "documentation_url": "https://docs.github.com", "status": str(status)}
    return Result(returncode=1, stdout=json.dumps(body), stderr=f"gh: {message} (HTTP {status})\n")


class FakeGh:
    """A ``gh`` stand-in scripted by argv prefix.

    The longest scripted prefix matching an argv wins. Each prefix returns its
    queued Results in order and repeats the last one once the queue runs out.
    Every argv is recorded in ``calls``; an unscripted argv raises
    ``AssertionError``.
    """

    def __init__(self) -> None:
        self._scripts: dict[tuple[str, ...], list[Result]] = {}
        self.calls: list[list[str]] = []

    def script(self, prefix: Sequence[str], *results: Result) -> None:
        """Queue *results* for argv starting with *prefix*."""
        if not results:
            raise ValueError("script() needs at least one Result")
        self._scripts.setdefault(tuple(prefix), []).extend(results)

    def run(self, argv: list[str], cwd: str | None = None) -> Result:
        """Record *argv* and return the next Result for its longest prefix."""
        self.calls.append(list(argv))
        matches = [p for p in self._scripts if tuple(argv[: len(p)]) == p]
        if not matches:
            raise AssertionError(f"unscripted gh argv: {argv}")
        queue = self._scripts[max(matches, key=len)]
        return queue.pop(0) if len(queue) > 1 else queue[0]


class FakeClock:
    """A monotonic clock that only moves when ``sleep`` is called."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class CompositeRunner:
    """Routes ``gh`` argv to a FakeGh and runs ``git`` argv for real.

    Every call, ``gh`` and ``git`` alike, is recorded as ``(argv, cwd)`` in
    ``calls``, where cwd is the one the call ran in: the caller's when given,
    ``default_cwd`` otherwise.
    """

    def __init__(self, fake_gh: FakeGh, default_cwd: str | os.PathLike[str]) -> None:
        self.fake_gh = fake_gh
        self.default_cwd = str(default_cwd)
        self.calls: list[tuple[list[str], str]] = []
        self._overlays: list[tuple[tuple[str, ...], str, int | None]] = []

    def overlay(self, argv_prefix: Sequence[str], *, append_stderr: str = "", returncode: int | None = None) -> None:
        """Post-process the next real ``git`` call matching *argv_prefix*.

        The call still runs; its stderr is then extended by *append_stderr* and,
        when given, its returncode replaced. This injects server output a local
        bare origin never prints, such as ``Bypassed rule violations``.
        """
        self._overlays.append((tuple(argv_prefix), append_stderr, returncode))

    def run(self, argv: list[str], cwd: str | None = None) -> Result:
        where = cwd if cwd is not None else self.default_cwd
        self.calls.append((list(argv), where))
        if argv[:1] == ["gh"]:
            return self.fake_gh.run(argv, cwd=where)
        if argv[:1] != ["git"]:
            raise AssertionError(f"CompositeRunner runs only gh and git, got: {argv}")
        proc = subprocess.run(argv, cwd=where, capture_output=True, text=True, check=False)
        result = Result(returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)
        for index, (prefix, append_stderr, returncode) in enumerate(self._overlays):
            if tuple(argv[: len(prefix)]) == prefix:
                del self._overlays[index]
                return Result(
                    returncode=returncode if returncode is not None else result.returncode,
                    stdout=result.stdout,
                    stderr=result.stderr + append_stderr,
                )
        return result


def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


@pytest.fixture
def git_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Yield a clone of a bare ``<tmp>/acme/widget.git`` holding one commit.

    Global and system git config are shut out so a developer's signing or hook
    settings cannot change what the real ``git`` calls do.
    """
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    origin = tmp_path / "acme" / "widget.git"
    origin.parent.mkdir()
    _git("init", "--bare", "--initial-branch=main", str(origin), cwd=tmp_path)
    clone = tmp_path / "clone"
    _git("clone", str(origin), str(clone), cwd=tmp_path)
    _git("config", "user.name", "Test", cwd=clone)
    _git("config", "user.email", "test@example.com", cwd=clone)
    _git("symbolic-ref", "HEAD", "refs/heads/main", cwd=clone)
    (clone / "README.md").write_text("widget\n", encoding="utf-8")
    _git("add", "README.md", cwd=clone)
    _git("commit", "-m", "initial", cwd=clone)
    _git("push", "origin", "main", cwd=clone)
    yield clone
