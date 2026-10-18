"""Contract for ``cold_read_audit.py`` (the-workshop#1179).

Incident: on 2026-10-10 three of the first six cold reads were degraded (no
probe build, earlier verdicts seen, a detector command denied), and each was
found only because the reader said so in its own report. Nothing in the engine
inspected what a reader actually did, so a reader that did not notice would
have passed. The audit reads the transcript instead, and prints one
``AUDIT key=value ...`` line of tokens the conductor reads.

Every transcript here is a synthetic JSONL file written under ``tmp_path`` by
the ``Transcript`` builder below; no recorded transcript, and no excerpt of
one, is part of the suite. Each test calls ``main([...])`` and reads the report
from ``capsys``. Each docstring names the defect it guards.
"""

from __future__ import annotations

import ast
import errno
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(SCRIPTS_DIR))

import cold_read_audit as mod  # noqa: E402

SCRIPT = SCRIPTS_DIR / "cold_read_audit.py"
VERSION = "2.1.293"
SCRATCH = "/tmp/cold-read-scratch-4f2a"
CAN_WRITE_READ_ONLY_DIR = hasattr(os, "geteuid") and os.geteuid() == 0

TOKEN_ORDER = [
    "version",
    "complete",
    "bad_lines",
    "agent_type",
    "model",
    "bash_calls",
    "scratch",
    "probe_build",
    "gh_calls",
    "comments_fetch",
    "comments_seen",
    "denied",
    "preflight",
    "flags",
]
INT_TOKENS = [
    "complete",
    "bad_lines",
    "bash_calls",
    "gh_calls",
    "comments_fetch",
    "comments_seen",
    "denied",
]
ROW_TOKENS = [
    "scratch",
    "probe_build",
    "gh_calls",
    "comments_fetch",
    "comments_seen",
    "denied",
    "preflight",
    "flags",
]


# --------------------------------------------------------------------------- #
# synthetic transcript builder
# --------------------------------------------------------------------------- #


class Transcript:
    """Builds a synthetic subagent transcript, one JSON object per line.

    The record shape follows the contract in the issue: ``type`` is
    ``assistant``, ``user`` or ``attachment``; a ``tool_use`` is one block of an
    assistant record's ``message.content``; its ``tool_result`` is one block of
    a later user record, matched by ``tool_use_id``.
    """

    def __init__(self, *, version: str | None = VERSION, model: str = "claude-sonnet-5-5") -> None:
        self.version = version
        self.model = model
        self.lines: list[str] = []
        self.count = 0

    def put(self, record: dict) -> None:
        if self.version is not None:
            record = {"version": self.version, **record}
        self.lines.append(json.dumps(record, ensure_ascii=False))

    def raw(self, line: str) -> None:
        self.lines.append(line)

    def next_id(self) -> str:
        self.count += 1
        return f"toolu_{self.count:03d}"

    def call(
        self,
        name: str,
        tool_input: dict,
        *,
        tid: str | None = None,
        mid: str | None = None,
        stop: str | None = "tool_use",
        model: str | None = None,
    ) -> str:
        """Add an assistant record holding one ``tool_use``; return its id."""
        tid = tid or self.next_id()
        self.put(
            {
                "type": "assistant",
                "message": {
                    "id": mid or f"msg_{tid}",
                    "role": "assistant",
                    "model": model or self.model,
                    "content": [{"type": "tool_use", "id": tid, "name": name, "input": tool_input}],
                    "stop_reason": stop,
                },
            }
        )
        return tid

    def result(self, tid: str, content, *, is_error: bool | None = None, **top) -> None:
        """Add a user record holding one ``tool_result`` for *tid*."""
        block = {"type": "tool_result", "tool_use_id": tid, "content": content}
        if is_error is not None:
            block["is_error"] = is_error
        self.put({"type": "user", "message": {"role": "user", "content": [block]}, **top})

    def bash(self, command: str, output="", *, is_error: bool | None = None, answered: bool = True, **top) -> str:
        """Add a ``Bash`` call and, unless *answered* is false, its result."""
        tid = self.call("Bash", {"command": command})
        if answered:
            self.result(tid, output, is_error=is_error, **top)
        return tid

    def tool(self, name: str = "Read", output: str = "text", **tool_input) -> str:
        tid = self.call(name, tool_input or {"file_path": "README.md"})
        self.result(tid, output)
        return tid

    def end_turn(self, text: str = "Done.") -> None:
        self.put(
            {
                "type": "assistant",
                "message": {
                    "id": f"msg_end_{len(self.lines)}",
                    "role": "assistant",
                    "model": self.model,
                    "content": [{"type": "text", "text": text}],
                    "stop_reason": "end_turn",
                },
            }
        )

    def hand_back(self, report: str = "report") -> None:
        tid = self.call("SubagentHandback", {"report": report})
        self.result(tid, "handed back")

    def text(self) -> str:
        return "\n".join(self.lines) + "\n"

    def write(self, directory: Path, name: str = "agent-aaa.jsonl") -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / name
        path.write_bytes(self.text().encode("utf-8"))
        return path


@dataclass
class Run:
    rc: int
    out: str
    err: str

    @property
    def line(self) -> str:
        lines = [line for line in self.out.split("\n") if line.startswith("AUDIT ")]
        assert len(lines) == 1, f"expected one AUDIT line in: {self.out!r}"
        return lines[0]

    @property
    def tokens(self) -> dict[str, str]:
        body = self.line[len("AUDIT "):]
        return dict(item.split("=", 1) for item in body.split(" "))

    @property
    def details(self) -> list[str]:
        return [line for line in self.out.split("\n") if line.startswith("DETAIL ")]


def run(capsys, path: Path, *args: str) -> Run:
    capsys.readouterr()
    rc = mod.main(["--transcript", str(path), *args])
    captured = capsys.readouterr()
    return Run(rc, captured.out, captured.err)


def one_command(
    directory: Path, command: str, output="ok", *, is_error: bool | None = None, answered: bool = True, **top
) -> Path:
    """A transcript of one ``Bash`` command (and its result) followed by an end of turn."""
    transcript = Transcript()
    transcript.bash(command, output, is_error=is_error, answered=answered, **top)
    transcript.end_turn()
    return transcript.write(directory)


def tokens_of(capsys, directory: Path, command: str, *args: str, output="ok", **kwargs) -> dict[str, str]:
    return run(capsys, one_command(directory, command, output, **kwargs), *args).tokens


def gh_counts(capsys, directory: Path, command: str, issue: str = "1151") -> tuple[str, str]:
    tokens = tokens_of(capsys, directory, command, "--issue", issue)
    return tokens["gh_calls"], tokens["comments_fetch"]


# --------------------------------------------------------------------------- #
# the replay record: one synthetic fixture per row
# --------------------------------------------------------------------------- #

PREFLIGHT_COMMAND = f'python3 "$ENGINE/cold_read_dispatch.py" preflight --scratch {SCRATCH}'
# A preflight command whose own text holds every probe word and the scratch path: it must still be
# neither a probe nor scratch use, because its result begins PREFLIGHT ok.
NOISY_PREFLIGHT_COMMAND = PREFLIGHT_COMMAND + " && uv run pytest --version && make -n test && ls teeth_check.py"
PREFLIGHT_OK = f"PREFLIGHT ok scratch={SCRATCH} git=git version 2.50.0 uv=uv 0.9.0"
COMMENT_RESULT = '{"comments":[{"id":"c1","body":"## Cold read - REWRITE\\nfindings"}]}'
EMPTY_COMMENTS = '{"comments":[]}'
DENIAL = "Permission for this action has been denied. Reason: not allowed."


def row_1151_read_1(directory: Path):
    t = Transcript()
    t.tool("Read", "# /cold-read", file_path="command.md")
    t.bash("gh issue view 1151 --repo cdcoonce/the-workshop --json comments", EMPTY_COMMENTS)
    t.bash("git log --oneline -3", "3b6c0e8b first")
    t.hand_back()
    return t.write(directory), ["--issue", "1151"]


def row_1151_read_2(directory: Path):
    t = Transcript()
    t.bash("mktemp -d", "/tmp/tmp.Ab12Cd")
    t.bash("git archive origin/dev | tar -x -C /tmp/tmp.Ab12Cd", "")
    t.bash("gh issue view 1151 --repo cdcoonce/the-workshop --json comments", COMMENT_RESULT)
    t.bash("cd /tmp/tmp.Ab12Cd && uv run pytest -q tests/test_x.py", "3 passed")
    t.hand_back()
    return t.write(directory), ["--issue", "1151"]


def row_1151_read_3(directory: Path):
    t = Transcript()
    t.bash("mktemp -d", "/tmp/tmp.Ef34Gh")
    t.bash("gh issue view 1152 --repo cdcoonce/the-workshop --json comments", COMMENT_RESULT)
    t.bash("cd /tmp/tmp.Ef34Gh && make test", "ok")
    t.hand_back()
    return t.write(directory), ["--issue", "1151"]


def row_1152_read_1(directory: Path):
    t = Transcript()
    t.bash("mkdir -p /tmp/scratch-a", "")
    t.bash("gh issue view 1151 --repo cdcoonce/the-workshop --json body", "body text")
    t.bash("gh issue view 1151 --repo cdcoonce/the-workshop --json state", '{"state":"OPEN"}')
    t.bash("python3 teeth_check.py spec.json", "killed")
    t.hand_back()
    return t.write(directory), ["--issue", "1152"]


def row_1152_read_2(directory: Path):
    t = Transcript()
    t.bash("git worktree add /tmp/wt-a HEAD", "HEAD is now at 3b6c0e8b")
    t.bash("gh issue view 1151 --repo cdcoonce/the-workshop", "title: x")
    t.bash("cd /tmp/wt-a && pytest -q", "5 passed")
    t.hand_back()
    return t.write(directory), ["--issue", "1152"]


def row_1152_read_3(directory: Path):
    t = Transcript()
    t.bash("mktemp -d", "/tmp/tmp.Ij56Kl")
    t.bash("gh issue view 1151 --repo cdcoonce/the-workshop --json body", "body text")
    t.bash("curl -s https://example.invalid/x", DENIAL, is_error=True, toolDenialKind="classifier")
    t.bash("cd /tmp/tmp.Ij56Kl && uv run pytest -q", "2 passed")
    t.hand_back()
    return t.write(directory), ["--issue", "1152"]


def row_cold_2026_10_11(directory: Path):
    t = Transcript()
    t.bash(PREFLIGHT_COMMAND, PREFLIGHT_OK)
    t.bash(f"ls {SCRATCH}/tree", "README.md")
    t.bash(f"cd {SCRATCH}/tree && uv run python -m pytest -q tests/", "4 passed")
    t.end_turn()
    return t.write(directory), ["--issue", "1179", "--scratch-dir", SCRATCH]


def row_fidelity_2026_10_10(directory: Path):
    t = Transcript()
    t.tool("Read", "decision text", file_path="decisions.md")
    t.bash("grep -n 'append-only' notes.md", "12: append-only")
    t.hand_back()
    return t.write(directory), ["--issue", "1151", "--role", "fidelity"]


def row_fidelity_2026_10_11(directory: Path):
    t = Transcript()
    t.tool("Read", "decision text", file_path="decisions.md")
    t.end_turn()
    return t.write(directory), ["--issue", "1179", "--role", "fidelity"]


COLD_NO_PREFLIGHT = "preflight-none"
REPLAY_ROWS = [
    pytest.param(
        row_1151_read_1,
        ("none", "none", "1", "1", "0", "0", "none", "scratch-none,no-probe-build,gh-used," + COLD_NO_PREFLIGHT),
        id="1151-read-1",
    ),
    pytest.param(
        row_1151_read_2,
        ("ok", "ran", "1", "1", "1", "0", "none", "comments-read,gh-used," + COLD_NO_PREFLIGHT),
        id="1151-read-2",
    ),
    pytest.param(
        row_1151_read_3,
        ("ok", "ran", "1", "0", "0", "0", "none", "gh-used," + COLD_NO_PREFLIGHT),
        id="1151-read-3",
    ),
    pytest.param(
        row_1152_read_1,
        ("ok", "ran", "2", "0", "0", "0", "none", "gh-used," + COLD_NO_PREFLIGHT),
        id="1152-read-1",
    ),
    pytest.param(
        row_1152_read_2,
        ("ok", "ran", "1", "0", "0", "0", "none", "gh-used," + COLD_NO_PREFLIGHT),
        id="1152-read-2",
    ),
    pytest.param(
        row_1152_read_3,
        ("ok", "ran", "1", "0", "0", "1", "none", "gh-used,denied," + COLD_NO_PREFLIGHT),
        id="1152-read-3",
    ),
    pytest.param(
        row_cold_2026_10_11,
        ("ok", "ran", "0", "0", "0", "0", "ok", "none"),
        id="cold-2026-10-11-with-scratch-dir",
    ),
    pytest.param(
        row_fidelity_2026_10_10,
        ("na", "na", "0", "0", "0", "0", "none", COLD_NO_PREFLIGHT),
        id="fidelity-2026-10-10",
    ),
    pytest.param(
        row_fidelity_2026_10_11,
        ("na", "na", "0", "0", "0", "0", "none", COLD_NO_PREFLIGHT),
        id="fidelity-2026-10-11",
    ),
]


@pytest.mark.parametrize(("build", "expected"), REPLAY_ROWS)
def test_each_replay_row_yields_its_tokens_and_flags(build, expected, tmp_path, capsys):
    """Guards a build that miscounts a token or misorders the flags on a real reader.

    The replay record lists, per reader, the exact tokens and ``flags`` the
    audit must produce. Each row also reports ``bad_lines`` 0 and ``complete`` 1
    (a hand-back call for the readers of 2026-10-10, an ``end_turn`` record for
    those of 2026-10-11).
    """
    path, args = build(tmp_path)
    result = run(capsys, path, *args)
    assert result.rc == 0
    tokens = result.tokens
    assert tuple(tokens[key] for key in ROW_TOKENS) == expected
    assert tokens["bad_lines"] == "0"
    assert tokens["complete"] == "1"


def test_cold_reader_with_preflight_and_no_gh_command_has_no_flags(tmp_path, capsys):
    """Guards a build that flags a clean reader.

    A cold reader that ran the preflight, made a scratch directory, ran a test
    and never touched ``gh`` yields ``gh_calls`` 0 and ``flags`` ``none``,
    without a ``--scratch-dir`` (the no-flag scratch pattern decides).
    """
    t = Transcript()
    t.bash(PREFLIGHT_COMMAND, PREFLIGHT_OK)
    t.bash("mktemp -d", "/tmp/tmp.Mn78Op")
    t.bash("uv run pytest -q", "1 passed")
    t.end_turn()
    tokens = run(capsys, t.write(tmp_path), "--issue", "1179").tokens
    assert tokens["gh_calls"] == "0"
    assert tokens["preflight"] == "ok"
    assert tokens["flags"] == "none"


def test_fidelity_role_reports_na_for_scratch_and_probe_build(tmp_path, capsys):
    """Guards a build that reports ``scratch=none`` (or flags) for the fidelity role.

    A fidelity reader writes nothing, so a missing scratch directory or probe
    build on it is expected and must not read as degradation: the tokens are
    ``na`` and neither ``scratch-none`` nor ``no-probe-build`` is flagged, even
    when the reader made Bash calls that match neither pattern.
    """
    t = Transcript()
    t.bash("ls", "a b c")
    t.bash(PREFLIGHT_COMMAND, PREFLIGHT_OK)
    t.end_turn()
    tokens = run(capsys, t.write(tmp_path), "--issue", "1179", "--role", "fidelity").tokens
    assert (tokens["scratch"], tokens["probe_build"]) == ("na", "na")
    assert tokens["flags"] == "none"


def test_role_defaults_to_cold(tmp_path, capsys):
    """Guards a build that defaults ``--role`` to fidelity (or drops the default).

    A run without ``--role`` is a cold run: a reader with no scratch directory
    and no probe is flagged for both.
    """
    tokens = tokens_of(capsys, tmp_path, "ls", "--issue", "1179")
    assert (tokens["scratch"], tokens["probe_build"]) == ("none", "none")
    assert tokens["flags"] == "scratch-none,no-probe-build,preflight-none"


# --------------------------------------------------------------------------- #
# scratch, probe_build and the preflight
# --------------------------------------------------------------------------- #


def preflight_transcript(*commands: str, result: str = PREFLIGHT_OK) -> Transcript:
    t = Transcript()
    t.bash(NOISY_PREFLIGHT_COMMAND, result)
    for command in commands:
        t.bash(command, "ok")
    t.end_turn()
    return t


def test_preflight_only_run_is_neither_scratch_nor_probe(tmp_path, capsys):
    """Guards a build that counts the preflight command as scratch use.

    With ``--scratch-dir D`` the preflight command names D, but a command whose
    result begins ``PREFLIGHT ok`` is not a use of the scratch directory. A
    transcript whose only command is the preflight has no scratch use and no
    probe build.
    """
    path = preflight_transcript().write(tmp_path)
    tokens = run(capsys, path, "--issue", "1179", "--scratch-dir", SCRATCH).tokens
    assert (tokens["scratch"], tokens["probe_build"], tokens["preflight"]) == ("none", "none", "ok")
    assert tokens["flags"] == "scratch-none,no-probe-build"


def test_preflight_only_run_with_a_failed_preflight_is_not_scratch_either(tmp_path, capsys):
    """Guards a build that exempts only ``PREFLIGHT ok`` commands from scratch use.

    A command whose result begins ``PREFLIGHT failed`` is a preflight command
    too; it never counts as scratch use or a probe.
    """
    path = preflight_transcript(result="PREFLIGHT failed cause=uv-missing").write(tmp_path)
    tokens = run(capsys, path, "--issue", "1179", "--scratch-dir", SCRATCH).tokens
    assert (tokens["scratch"], tokens["probe_build"], tokens["preflight"]) == ("none", "none", "failed")


def test_preflight_plus_ls_of_scratch_dir_is_scratch_without_a_probe(tmp_path, capsys):
    """Guards a build that reports ``probe_build=ran`` for any command touching the scratch directory.

    A preflight and an ``ls D`` make ``scratch`` ok and leave ``probe_build``
    ``none``: the reader never ran a test. One that also runs ``pytest`` has.
    """
    tokens = run(
        capsys, preflight_transcript(f"ls {SCRATCH}").write(tmp_path / "a"), "--issue", "1179", "--scratch-dir", SCRATCH
    ).tokens
    assert (tokens["scratch"], tokens["probe_build"], tokens["preflight"]) == ("ok", "none", "ok")
    assert tokens["flags"] == "no-probe-build"
    tokens = run(
        capsys,
        preflight_transcript(f"ls {SCRATCH}", "pytest -q").write(tmp_path / "b"),
        "--issue",
        "1179",
        "--scratch-dir",
        SCRATCH,
    ).tokens
    assert (tokens["scratch"], tokens["probe_build"]) == ("ok", "ran")
    assert tokens["flags"] == "none"


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        pytest.param("pytest -q", "ran", id="bare-pytest"),
        pytest.param("uv run pytest tests/", "ran", id="uv-run-pytest"),
        pytest.param("python -m pytest -q", "ran", id="python-m-pytest"),
        pytest.param("python3 teeth_check.py spec.json", "ran", id="teeth-check"),
        pytest.param("make test", "ran", id="make-with-target"),
        pytest.param("ls /tmp/pytest-of-u/pytest-0", "none", id="pytest-inside-a-path"),
        pytest.param("ls pytest_cache", "none", id="pytest-underscore-word"),
        pytest.param("echo pytest-cov", "none", id="pytest-hyphen-word"),
        pytest.param("make", "none", id="make-without-a-target"),
        pytest.param("cat Makefile", "none", id="makefile-is-not-make"),
        pytest.param("echo remake test", "none", id="make-inside-a-word"),
    ],
)
def test_probe_pattern_matches_a_probe_and_not_a_lookalike(command, expected, tmp_path, capsys):
    """Guards a build that matches ``pytest`` (or ``make``) anywhere in a word or path.

    ``probe_build`` is ``ran`` for ``pytest``, ``teeth_check.py`` or
    ``make <target>`` as a program, and a path such as ``pytest-of-u/pytest-0``
    is not a probe.
    """
    assert tokens_of(capsys, tmp_path, command, "--issue", "1179")["probe_build"] == expected


def test_a_red_pytest_run_still_counts_as_a_probe(tmp_path, capsys):
    """Guards a build that requires the probe's result not to be an error.

    A red or refused run is still a probe: ``probe_build`` is ``ran`` for a
    ``pytest`` command whose result has ``is_error`` true.
    """
    tokens = tokens_of(
        capsys, tmp_path, "uv run pytest -q", "--issue", "1179", output="Exit code 1\n1 failed", is_error=True
    )
    assert tokens["probe_build"] == "ran"


def test_probe_run_in_a_heredoc_driver_counts(tmp_path, capsys):
    """Guards a build that removes heredoc bodies before the ``probe_build`` pattern.

    A mutation driver written as a heredoc is a probe, so the pattern is
    applied to the whole command, heredoc body included.
    """
    command = 'python3 - <<\'PY\'\nimport subprocess\nsubprocess.run(["pytest", "-q"])\nPY'
    assert tokens_of(capsys, tmp_path, command, "--issue", "1179")["probe_build"] == "ran"


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        pytest.param("mktemp -d", "ok", id="mktemp"),
        pytest.param("mkdir -p /tmp/w", "ok", id="mkdir"),
        pytest.param('python3 -c "import tempfile; tempfile.mkdtemp()"', "ok", id="tempfile"),
        pytest.param("git archive HEAD | tar -x -C /tmp/w", "ok", id="git-archive"),
        pytest.param("git clone /src /tmp/w", "ok", id="git-clone"),
        pytest.param("git worktree add /tmp/w HEAD", "ok", id="git-worktree-add"),
        pytest.param("echo hello", "none", id="unrelated"),
        pytest.param("git status", "none", id="git-status"),
        pytest.param("git worktree list", "none", id="git-worktree-list"),
        pytest.param("echo tempfiles", "none", id="word-prefix"),
    ],
)
def test_scratch_pattern_without_a_scratch_dir(command, expected, tmp_path, capsys):
    """Guards a build that drops one alternative of the no-flag scratch pattern.

    With no ``--scratch-dir`` a successful ``mktemp``, ``mkdir``, ``tempfile``,
    ``git archive``, ``git clone`` or ``git worktree add`` command is scratch use.
    """
    assert tokens_of(capsys, tmp_path, command, "--issue", "1179")["scratch"] == expected


def test_scratch_pattern_reads_a_heredoc_body(tmp_path, capsys):
    """Guards a build that removes heredoc bodies before the ``scratch`` pattern.

    The pattern is applied to the whole command with heredoc bodies included,
    as for ``probe_build``: ``import tempfile`` inside a heredoc is scratch use.
    """
    command = "python3 - <<'PY'\nimport tempfile\ntempfile.mkdtemp()\nPY"
    assert tokens_of(capsys, tmp_path, command, "--issue", "1179")["scratch"] == "ok"


def test_unanswered_tool_use_is_not_scratch_use_or_a_probe(tmp_path, capsys):
    """Guards a build that counts ``scratch=ok`` (or ``ran``) without checking the result.

    A ``tool_use`` with no result in the file did not run to completion as far
    as the transcript shows: it counts in ``bash_calls`` and nowhere else.
    """
    t = Transcript()
    t.bash("mkdir /tmp/never", answered=False)
    t.bash("pytest -q", answered=False)
    t.end_turn()
    tokens = run(capsys, t.write(tmp_path), "--issue", "1179").tokens
    assert (tokens["scratch"], tokens["probe_build"], tokens["bash_calls"]) == ("none", "none", "2")


def test_failed_command_holding_the_scratch_path_is_not_scratch_use(tmp_path, capsys):
    """Guards a build that drops the "result is not an error" condition of ``scratch``.

    A command that names the scratch directory but failed (``is_error`` true)
    is not a successful use of it.
    """
    tokens = tokens_of(
        capsys, tmp_path, f"ls {SCRATCH}", "--issue", "1179", "--scratch-dir", SCRATCH,
        output="Exit code 2\nls: cannot access", is_error=True,
    )
    assert tokens["scratch"] == "none"


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        pytest.param("ls /tmp/x", "ok", id="exact-path"),
        pytest.param("ls /tmp/x/sub", "ok", id="path-then-slash"),
        pytest.param("cd /tmp/x && ls", "ok", id="path-then-space"),
        pytest.param("ls /tmp/xy/z", "none", id="longer-name"),
        pytest.param("ls /tmp/x1", "none", id="digit-after"),
        pytest.param("ls /tmp/x_y", "none", id="underscore-after"),
        pytest.param("ls /tmp/x-y", "none", id="hyphen-after"),
        pytest.param("mktemp -d", "none", id="mktemp-of-another-directory"),
    ],
)
def test_scratch_dir_matches_as_a_whole_path(command, expected, tmp_path, capsys):
    """Guards a build that matches ``--scratch-dir`` as a bare prefix or substring.

    With ``--scratch-dir /tmp/x`` only a successful command containing that path
    as a whole is scratch use: ``ls /tmp/xy/z`` is not, and a successful
    ``mktemp -d`` of another directory is not either (the no-flag pattern is
    not consulted once a scratch directory is given).
    """
    tokens = tokens_of(capsys, tmp_path, command, "--issue", "1179", "--scratch-dir", "/tmp/x")
    assert tokens["scratch"] == expected


def test_preflight_token_comes_from_the_result_not_the_command(tmp_path, capsys):
    """Guards a build that keys ``preflight`` on the command text instead of the result.

    A command that looks like the preflight but whose result is a traceback has
    not run it (``preflight`` is ``none``); a command that does not look like it
    but whose result begins ``PREFLIGHT failed`` has (``preflight`` is
    ``failed``).
    """
    t = Transcript()
    t.bash(PREFLIGHT_COMMAND, "Traceback (most recent call last):\n  File x")
    t.end_turn()
    assert run(capsys, t.write(tmp_path / "a"), "--issue", "1179").tokens["preflight"] == "none"
    t = Transcript()
    t.bash("echo setup", "PREFLIGHT failed cause=scratch-missing")
    t.end_turn()
    assert run(capsys, t.write(tmp_path / "b"), "--issue", "1179").tokens["preflight"] == "failed"


def test_preflight_token_is_the_first_preflight_result(tmp_path, capsys):
    """Guards a build that takes ``preflight`` from a later preflight-shaped result.

    ``PREFLIGHT failed`` and then a later ``PREFLIGHT ok`` gives ``failed``.
    """
    t = Transcript()
    t.bash("echo one", "PREFLIGHT failed cause=git-missing")
    t.bash("echo two", PREFLIGHT_OK)
    t.end_turn()
    assert run(capsys, t.write(tmp_path), "--issue", "1179").tokens["preflight"] == "failed"


def test_preflight_failed_flag_needs_another_tool_use_after_it(tmp_path, capsys):
    """Guards a build that flags ``preflight-failed`` on a failed preflight alone, or counts a hand-back.

    A reader that stopped at the failed preflight (the contract: no other call)
    is not flagged, also when a ``SubagentHandback`` call follows; one that went
    on to use another tool is. A ``Read`` counts, not only a second ``Bash`` call.
    """
    only = Transcript()
    only.bash("echo setup", "PREFLIGHT failed cause=x")
    only.end_turn()
    assert run(capsys, only.write(tmp_path / "a"), "--issue", "1179").tokens["flags"] == "scratch-none,no-probe-build"
    handed = Transcript()
    handed.bash("echo setup", "PREFLIGHT failed cause=x")
    handed.hand_back()
    tokens = run(capsys, handed.write(tmp_path / "b"), "--issue", "1179").tokens
    assert (tokens["preflight"], tokens["flags"]) == ("failed", "scratch-none,no-probe-build")
    went_on = Transcript()
    went_on.bash("echo setup", "PREFLIGHT failed cause=x")
    went_on.tool("Read", "text", file_path="a.md")
    went_on.end_turn()
    tokens = run(capsys, went_on.write(tmp_path / "c"), "--issue", "1179").tokens
    assert tokens["flags"] == "scratch-none,no-probe-build,preflight-failed"


# --------------------------------------------------------------------------- #
# gh_calls and comments_fetch
# --------------------------------------------------------------------------- #

COMMAND_POSITIONS = [
    pytest.param("gh label list", id="start-of-command"),
    pytest.param("echo a; gh x", id="after-semicolon"),
    pytest.param("echo a && gh x", id="after-and-and"),
    pytest.param("echo a & gh x", id="after-ampersand"),
    pytest.param("echo a | gh x", id="after-pipe"),
    pytest.param("false || gh x", id="after-or-or"),
    pytest.param("(gh x)", id="after-open-paren"),
    pytest.param("echo $(gh x)", id="after-dollar-paren"),
    pytest.param("echo `gh x`", id="after-backtick"),
    pytest.param("if true; then gh x; fi", id="after-then"),
    pytest.param("if false; then :; else gh x; fi", id="after-else"),
    pytest.param("if gh x; then :; fi", id="after-if"),
    pytest.param("for i in 1; do gh issue view 5; done", id="after-do-in-a-loop"),
    pytest.param("do gh issue view 5", id="after-do"),
    pytest.param("ls | xargs gh x", id="after-xargs"),
    pytest.param("! gh x", id="after-bang"),
    pytest.param("GH_TOKEN=t gh x", id="after-an-assignment"),
    pytest.param('GH_HOST="a b" GH_TOKEN=t gh x', id="after-two-assignments"),
    pytest.param("/usr/local/bin/gh x", id="path-ending-in-gh"),
    pytest.param("gh -R x/y issue view 5", id="flag-before-the-subcommand"),
    pytest.param("./gh label list", id="relative-path-to-gh"),
    pytest.param("~/bin/gh label list", id="home-path-to-gh"),
    pytest.param("GH_HOST='a b' gh x", id="single-quoted-assignment-value"),
    pytest.param("GH_TOKEN= gh x", id="empty-assignment-value"),
    pytest.param("token=t gh x", id="lower-case-assignment-name"),
]


@pytest.mark.parametrize("command", COMMAND_POSITIONS)
def test_gh_invocation_counts_at_each_command_position(command, tmp_path, capsys):
    """Guards a build that leaves one of the closed command positions out of the ``gh`` pattern.

    ``gh_calls`` counts a Bash command that holds an invocation of ``gh`` as a
    program at the start of the command, after ``;``, ``&``, ``&&``, ``||``,
    ``|``, ``(``, ``$(`` or a backtick, after ``do``, ``then``, ``else``, ``if``,
    ``!`` or ``xargs``, after leading ``NAME=value`` assignments, with or
    without a path ending ``/gh``.
    """
    assert gh_counts(capsys, tmp_path, command)[0] == "1"


@pytest.mark.parametrize(
    "command",
    [
        pytest.param("echo gh x", id="argument-of-echo"),
        pytest.param('echo "gh x"', id="inside-quotes"),
        pytest.param("ls gh-pages", id="hyphenated-name"),
        pytest.param("cat ghost.txt", id="longer-word"),
        pytest.param("gh=1", id="assignment-to-gh"),
        pytest.param("cd /tmp/gh", id="directory-named-gh"),
    ],
)
def test_gh_word_that_is_not_a_program_does_not_count(command, tmp_path, capsys):
    """Guards a build that matches ``gh`` anywhere at a word boundary.

    ``gh`` counts only as a program at a command position: an argument, a
    quoted string, a hyphenated name or a directory is not an invocation.
    """
    assert gh_counts(capsys, tmp_path, command)[0] == "0"


def test_gh_on_its_own_line_counts_after_a_newline(tmp_path, capsys):
    """Guards a build that leaves the start of a line out of the command positions.

    A ``gh`` on its own line after a newline, indented or not, counts.
    """
    assert gh_counts(capsys, tmp_path / "a", "echo a\ngh label list")[0] == "1"
    assert gh_counts(capsys, tmp_path / "b", "echo a\n   gh label list")[0] == "1"


def test_gh_subcommand_and_flags_do_not_matter(tmp_path, capsys):
    """Guards a build that counts only the ``issue``, ``api`` and ``pr`` subcommands.

    Any subcommand and any flags count: ``gh label list``, ``gh -R x/y issue
    view 5`` and ``gh issue view 1151 -c`` each add one to ``gh_calls``; the last
    is also a comments fetch.
    """
    assert gh_counts(capsys, tmp_path / "a", "gh label list") == ("1", "0")
    assert gh_counts(capsys, tmp_path / "b", "gh -R x/y issue view 5") == ("1", "0")
    assert gh_counts(capsys, tmp_path / "c", "gh issue view 1151 -c") == ("1", "1")
    assert gh_counts(capsys, tmp_path / "d", "gh repo list") == ("1", "0")
    assert gh_counts(capsys, tmp_path / "e", "gh auth status") == ("1", "0")


def test_gh_calls_counts_commands_not_invocations(tmp_path, capsys):
    """Guards a build that adds one per ``gh`` invocation instead of one per command.

    ``gh_calls`` is the number of Bash commands holding at least one ``gh``
    invocation, and ``comments_fetch`` counts commands the same way: a command
    with two of each adds one.
    """
    assert gh_counts(capsys, tmp_path / "a", "gh issue view 5; gh pr list")[0] == "1"
    two_fetches = "gh issue view 1151 --json comments; gh api repos/o/r/issues/1151/comments"
    assert gh_counts(capsys, tmp_path / "b", two_fetches) == ("1", "1")


HEREDOC_CASES = [
    pytest.param("cat <<EOF\ngh issue view 1151 --json comments\nEOF", "0", id="unquoted-word"),
    pytest.param("cat <<'EOF'\ngh issue view 1151 --json comments\nEOF", "0", id="single-quoted-word"),
    pytest.param('cat <<"EOF"\ngh issue view 1151 --json comments\nEOF', "0", id="double-quoted-word"),
    pytest.param("cat <<-EOF\ngh issue view 1151 --json comments\nEOF", "0", id="dash-form"),
    pytest.param("gh issue view 1151 --json comments", "1", id="same-text-as-a-command"),
    pytest.param("cat <<-EOF\n\tgh x\n\tEOF\ngh label list", "1", id="dash-form-tab-terminator-ends-the-body"),
    pytest.param("cat <<EOF\nbody\nEOF\ngh label list", "1", id="exact-terminator-ends-the-body"),
    pytest.param("cat <<EOF\ngh label list", "0", id="unterminated-hides-the-rest"),
    pytest.param("cat <<< EOF\ngh label list", "1", id="here-string-is-no-heredoc"),
    pytest.param("cat <<<EOF\ngh label list", "1", id="here-string-without-a-space-is-no-heredoc"),
    pytest.param("cat <<EOF\nEOFX\ngh label list\nEOF", "0", id="longer-line-is-not-the-terminator"),
    pytest.param("cat <<EOF\nEOF extra\ngh label list\nEOF", "0", id="terminator-plus-text-is-not-the-terminator"),
    pytest.param("cat <<-EOF\n  EOF\ngh label list\nEOF", "0", id="spaces-do-not-end-a-dash-body"),
    pytest.param("cat <<EOF\nEOF \ngh label list\nEOF", "0", id="trailing-space-does-not-end-the-body"),
    pytest.param("cat <<EOF\n\tEOF\ngh label list\nEOF", "0", id="tab-does-not-end-a-plain-body"),
    pytest.param("cat <<'EOF'\n\tEOF\ngh label list\nEOF", "0", id="tab-does-not-end-a-quoted-body"),
]


@pytest.mark.parametrize(("command", "expected"), HEREDOC_CASES)
def test_heredoc_bodies_are_removed_before_the_gh_pattern(command, expected, tmp_path, capsys):
    """Guards a build that applies the ``gh`` pattern to heredoc bodies, or ends a body wrongly.

    The four forms ``<<W``, ``<<'W'``, ``<<"W"`` and ``<<-W`` hide their body,
    which ends at a line equal to W (tabs allowed before it for ``<<-`` only),
    or at the end of the command when none. ``<<<`` is no heredoc.
    """
    assert gh_counts(capsys, tmp_path, command)[0] == expected


def test_heredoc_body_is_not_a_comments_fetch(tmp_path, capsys):
    """Guards a build that counts a heredoc body toward ``comments_fetch``.

    The same text as a command is a fetch; inside a heredoc body it is not.
    """
    body = "cat <<EOF\ngh issue view 1151 --json comments\nEOF"
    assert gh_counts(capsys, tmp_path / "a", body) == ("0", "0")
    assert gh_counts(capsys, tmp_path / "b", "gh issue view 1151 --json comments") == ("1", "1")


STANDALONE_NUMBER_CASES = [
    pytest.param("gh issue view 1151 --json comments", "1", id="exact-number"),
    pytest.param("gh api repos/o/r/issues/1151/comments", "1", id="inside-an-api-path"),
    pytest.param("gh issue view 1151 -c", "1", id="short-flag"),
    pytest.param("gh issue view 1151 --comments", "1", id="long-flag"),
    pytest.param("gh pr view 1151 -c", "1", id="pr-view-short-flag"),
    pytest.param("gh issue view 11510 --json comments", "0", id="digit-after"),
    pytest.param("gh issue view 1151a --json comments", "0", id="letter-after"),
    pytest.param("gh issue view 1151_x --json comments", "0", id="underscore-after"),
    pytest.param("gh issue view 21151 --json comments", "0", id="digit-before"),
    pytest.param("gh issue view x1151 --json comments", "0", id="letter-before"),
    pytest.param("gh issue view _1151 --json comments", "0", id="underscore-before"),
    pytest.param("echo 1151; gh issue view 5 --json comments", "0", id="number-outside-the-gh-segment"),
    pytest.param("gh issue view 1151 --json body | python3 -c 'print(1)'", "0", id="dash-c-after-a-pipe"),
    pytest.param("gh issue view 1151 --json body && python3 -c 'print(1)'", "0", id="dash-c-after-and-and"),
    pytest.param("gh issue view 1151 --json body\npython3 -c 'print(1)'", "0", id="dash-c-after-a-newline"),
    pytest.param("gh issue view 1151 --json body; python3 -c 'print(1)'", "0", id="dash-c-after-a-semicolon"),
    pytest.param("gh issue comment 1151 --body x", "0", id="singular-comment"),
    pytest.param("gh label list 1151 -c", "0", id="dash-c-without-issue-view"),
    pytest.param("gh pr list 1151 -c", "0", id="dash-c-without-pr-view"),
    pytest.param("gh issue view 1151 --json title", "0", id="no-comments-at-all"),
]


@pytest.mark.parametrize(("command", "expected"), STANDALONE_NUMBER_CASES)
def test_standalone_issue_number_decides_comments_fetch(command, expected, tmp_path, capsys):
    """Guards a build that compares the issue number as a substring, or reads text outside the ``gh`` segment.

    A comments fetch is a ``gh`` invocation whose own segment (to the next
    ``;``, ``&``, ``|`` or newline) holds the issue number as a standalone token
    (no letter, digit or ``_`` directly before or after) and the text
    ``comments``, or ``-c`` / ``--comments`` with ``issue view`` or ``pr view``.
    Every case still counts in ``gh_calls``.
    """
    assert gh_counts(capsys, tmp_path, command) == ("1", expected)


def test_gh_segment_ends_at_the_next_separator(tmp_path, capsys):
    """Guards a build that tests ``-c`` against the whole command instead of the ``gh`` segment.

    ``gh issue view 1151 --json body | python3 -c "print(1)"`` counts in
    ``gh_calls`` but not in ``comments_fetch``: the ``-c`` belongs to
    ``python3``, after the pipe.
    """
    command = 'gh issue view 1151 --json body | python3 -c "print(1)"'
    assert gh_counts(capsys, tmp_path, command) == ("1", "0")


def test_issue_number_follows_the_issue_argument(tmp_path, capsys):
    """Guards a build that ignores ``--issue`` when deciding a comments fetch.

    The sibling issue's lookup is a ``gh`` call but not a comments fetch of
    this issue: with ``--issue 1152``, ``gh issue view 1151 --json comments``
    counts in ``gh_calls`` only.
    """
    assert gh_counts(capsys, tmp_path / "a", "gh issue view 1151 --json comments", issue="1152") == ("1", "0")
    assert gh_counts(capsys, tmp_path / "b", "gh issue view 1152 --json comments", issue="1152") == ("1", "1")


# --------------------------------------------------------------------------- #
# comments_seen
# --------------------------------------------------------------------------- #


def seen(capsys, directory: Path, result, *, command: str = "gh issue view 1151 --json comments", answered=True):
    path = one_command(directory, command, result, answered=answered)
    return run(capsys, path, "--issue", "1151").tokens["comments_seen"]


def test_truncated_comments_result_is_seen(tmp_path, capsys):
    """Guards a build that drops the ``head -c`` fallback pattern for ``comments_seen``.

    A result cut off by ``head -c`` is not valid JSON, but the prefix
    ``{"comments":[{"id":"x","body":"ok`` shows a comment was returned
    (``comments_seen`` 1), and ``{"comments":[]`` shows none (0).
    """
    assert seen(capsys, tmp_path / "a", '{"comments":[{"id":"x","body":"ok') == "1"
    assert seen(capsys, tmp_path / "b", '{"comments":[]') == "0"
    assert seen(capsys, tmp_path / "c", '{"comments": [\n  {\n    "id": "x"') == "1"


def test_comments_seen_by_the_cold_read_marker_or_a_parsed_list(tmp_path, capsys):
    """Guards a build that tests only one of the three ways a comment is seen.

    A result containing ``## Cold read``, a top-level JSON array from ``gh
    api`` whose elements' ``body`` starts ``## Cold read``, and a JSON object
    whose ``comments`` list is non-empty each set ``comments_seen`` to 1; an
    empty list does not.
    """
    assert seen(capsys, tmp_path / "a", "plain text with ## Cold read - BUILD inside") == "1"
    array = json.dumps([{"id": 1, "body": "## Cold read - BUILD\nok"}, {"id": 2, "body": "later"}])
    assert seen(capsys, tmp_path / "b", array, command="gh api repos/o/r/issues/1151/comments") == "1"
    assert seen(capsys, tmp_path / "c", json.dumps({"comments": ["x"]})) == "1"
    assert seen(capsys, tmp_path / "d", json.dumps({"comments": []})) == "0"
    assert seen(capsys, tmp_path / "e", "no comments here") == "0"


def test_comments_seen_needs_a_fetch_result_that_is_present(tmp_path, capsys):
    """Guards a build that reads comments from a result nobody asked for.

    ``comments_seen`` is read from comments-fetch results only: a fetch with
    no result in the file sets 0, and a result of another command (here a
    ``cat`` of a note, and a command that is a fetch of another issue) holding
    ``## Cold read`` or a comments list does not set it.
    """
    assert seen(capsys, tmp_path / "a", "unused", answered=False) == "0"
    t = Transcript()
    t.bash("cat notes.md", "## Cold read - BUILD")
    t.bash("gh issue view 1151 --json comments", EMPTY_COMMENTS)
    t.bash("gh issue view 1152 --json comments", COMMENT_RESULT)
    t.bash("echo x", '{"comments": [{"id": 1}]}')
    t.end_turn()
    assert run(capsys, t.write(tmp_path / "b"), "--issue", "1151").tokens["comments_seen"] == "0"


# --------------------------------------------------------------------------- #
# denied
# --------------------------------------------------------------------------- #


def denied(capsys, directory: Path, output, *, is_error=None, **top) -> str:
    path = one_command(directory, "ls", output, is_error=is_error, **top)
    return run(capsys, path, "--issue", "1179").tokens["denied"]


def test_exit_code_is_not_a_denial(tmp_path, capsys):
    """Guards a build that treats ``is_error`` true as denied regardless of text.

    ``is_error`` is true for any non-zero exit status, so a result of ``Exit
    code 1`` is not a denial, nor is an error whose later text says
    ``Permission denied``.
    """
    assert denied(capsys, tmp_path / "a", "Exit code 1", is_error=True) == "0"
    assert denied(capsys, tmp_path / "b", "Exit code 1\nPermission denied", is_error=True) == "0"
    assert denied(capsys, tmp_path / "c", "fine", is_error=False) == "0"


def test_tool_denial_kind_is_a_denial_whatever_the_text(tmp_path, capsys):
    """Guards a build that ignores ``toolDenialKind`` on the result's record.

    A result whose record carries ``toolDenialKind`` is denied even when its
    text holds no denial words.
    """
    assert denied(capsys, tmp_path, "all good", toolDenialKind="classifier") == "1"


def test_structured_denial_through_permission_decision_reject(tmp_path, capsys):
    """Guards a build that drops the ``permissionDecision.decision`` of ``reject`` branch.

    A result whose record has ``permissionDecision.decision`` ``reject``, no
    ``toolDenialKind`` and no denial text is denied; ``allow`` is not.
    """
    assert denied(capsys, tmp_path / "a", "fine", permissionDecision={"decision": "reject"}) == "1"
    assert denied(capsys, tmp_path / "b", "fine", permissionDecision={"decision": "allow"}) == "0"


def test_denied_vocabulary_is_exact(tmp_path, capsys):
    """Guards a build that widens or narrows the three denial clauses.

    ``toolDenialKind`` ``interrupted`` is not a denial; an error result that
    begins ``Permission for this action`` is; one that only contains
    ``Permission denied`` is not; the same beginning without ``is_error`` true
    is not; a null ``toolDenialKind`` is not.
    """
    assert denied(capsys, tmp_path / "a", "stopped", toolDenialKind="interrupted") == "0"
    assert denied(capsys, tmp_path / "b", DENIAL, is_error=True) == "1"
    assert denied(capsys, tmp_path / "c", "Exit code 1\nPermission denied", is_error=True) == "0"
    assert denied(capsys, tmp_path / "d", DENIAL) == "0"
    assert denied(capsys, tmp_path / "e", "fine", toolDenialKind=None) == "0"
    assert denied(capsys, tmp_path / "f", "fine", toolDenialKind="") == "0"


def test_a_result_counts_once_however_many_denial_clauses_match(tmp_path, capsys):
    """Guards a build that adds one per matching clause instead of one per result."""
    both = {"toolDenialKind": "classifier", "permissionDecision": {"decision": "reject"}}
    assert denied(capsys, tmp_path, DENIAL, is_error=True, **both) == "1"


def test_denied_counts_results_of_any_tool_but_details_list_bash_only(tmp_path, capsys):
    """Guards a build that counts denials of Bash results only, or lists a non-Bash call as a command.

    ``denied`` counts results; ``--details`` lists commands.
    """
    t = Transcript()
    tid = t.call("Read", {"file_path": "secret"})
    t.result(tid, "no", toolDenialKind="classifier")
    t.end_turn()
    result = run(capsys, t.write(tmp_path), "--issue", "1179", "--details")
    assert result.tokens["denied"] == "1"
    assert result.details == []


# --------------------------------------------------------------------------- #
# parsing: lines, bad_lines, complete, partial transcripts
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("char", [" ", " ", "\u0085"])
def test_u2028_inside_a_json_string_does_not_split_the_record(char, tmp_path, capsys):
    """Guards a build that splits lines with ``splitlines()``.

    A line ends at ``\\n`` only: U+2028, U+2029 and U+0085 inside a JSON string
    are part of the record, which still parses (``bad_lines`` 0) and is read
    (here a ``mkdir`` command whose text holds the character).
    """
    t = Transcript()
    t.bash(f"echo a{char}b; mkdir /tmp/w", "ok")
    t.end_turn()
    text = t.text()
    assert char in text
    tokens = run(capsys, t.write(tmp_path), "--issue", "1179").tokens
    assert tokens["bad_lines"] == "0"
    assert tokens["scratch"] == "ok"


def test_blank_lines_are_skipped_and_not_counted(tmp_path, capsys):
    """Guards a build that counts a blank line in ``bad_lines``."""
    t = Transcript()
    t.raw("")
    t.bash("ls", "ok")
    t.raw("   ")
    t.raw("")
    t.end_turn()
    assert run(capsys, t.write(tmp_path), "--issue", "1179").tokens["bad_lines"] == "0"


@pytest.mark.parametrize("line", ["[1]", "3", '"x"', "null", "not json at all", '{"type": "user"'])
def test_a_line_that_is_not_a_json_object_is_a_bad_line(line, tmp_path, capsys):
    """Guards a build that counts only lines that fail to parse, not valid JSON that is no object."""
    t = Transcript()
    t.raw(line)
    t.bash("ls", "ok")
    t.end_turn()
    assert run(capsys, t.write(tmp_path), "--issue", "1179").tokens["bad_lines"] == "1"


def test_end_turn_without_a_hand_back_is_complete(tmp_path, capsys):
    """Guards a build that requires ``SubagentHandback`` for ``complete``.

    The dispatch readers of 2026-10-11 end with an ``end_turn`` record and no
    hand-back call.
    """
    t = Transcript()
    t.bash("ls", "ok")
    t.end_turn()
    result = run(capsys, t.write(tmp_path), "--issue", "1179")
    assert (result.rc, result.tokens["complete"]) == (0, "1")


def test_hand_back_without_an_end_turn_is_complete(tmp_path, capsys):
    """Guards a build that requires an ``end_turn`` record for ``complete``.

    The readers of 2026-10-10 end with a hand-back call and no ``end_turn``.
    """
    t = Transcript()
    t.bash("ls", "ok")
    t.hand_back()
    result = run(capsys, t.write(tmp_path), "--issue", "1179")
    assert (result.rc, result.tokens["complete"]) == (0, "1")


def test_complete_comes_from_the_last_assistant_record(tmp_path, capsys):
    """Guards a build that takes ``complete`` from any assistant record.

    An ``end_turn`` in the middle of the file, followed by a later assistant
    record that is not an ``end_turn``, is a transcript still running.
    """
    t = Transcript()
    t.end_turn("early stop")
    t.bash("ls", "ok")
    t.call("Read", {"file_path": "a"}, stop="tool_use")
    result = run(capsys, t.write(tmp_path), "--issue", "1179")
    assert (result.rc, result.tokens["complete"]) == (3, "0")


def test_incomplete_transcript_exits_3_after_printing_the_report(tmp_path, capsys):
    """Guards a build that exits 0 on an incomplete transcript, or exits before printing.

    A transcript with no ``end_turn`` last record and no hand-back call exits
    3 without ``--allow-partial`` (the report is printed first) and 0 with it.
    """
    t = Transcript()
    t.bash("ls", "ok")
    t.call("Read", {"file_path": "a"})
    path = t.write(tmp_path)
    blocked = run(capsys, path, "--issue", "1179")
    assert blocked.rc == 3
    assert blocked.tokens["complete"] == "0"
    allowed = run(capsys, path, "--issue", "1179", "--allow-partial")
    assert allowed.rc == 0
    assert allowed.tokens == blocked.tokens


def test_no_assistant_record_at_all_is_incomplete(tmp_path, capsys):
    """Guards a build that reads ``complete`` as 1 when there is nothing to read."""
    path = tmp_path / "agent-aaa.jsonl"
    path.write_text("", encoding="utf-8")
    result = run(capsys, path, "--issue", "1179")
    assert (result.rc, result.tokens["complete"], result.tokens["bad_lines"]) == (3, "0", "0")


def cut_at_sixty_percent(directory: Path, *, inside_character: bool) -> tuple[Path, bytes]:
    """A transcript cut at 60 percent of its bytes, in a line or in a UTF-8 character.

    One long command line sits among shorter ones; the number of lines before
    and after it is searched until 60 percent of the bytes falls inside it, on a
    printable ASCII byte (``inside_character`` false) or on a continuation byte
    of a multi-byte character (true).
    """
    filler = "\u00e9\u2014" * 150 if inside_character else "a" * 600
    for before in range(14):
        for after in range(14):
            t = Transcript()
            for index in range(before):
                t.bash(f"echo before {index}", "ok")
            t.bash("echo " + filler, "ok")
            for index in range(after):
                t.bash(f"echo after {index}", "ok")
            t.end_turn()
            data = t.text().encode("utf-8")
            cut = int(len(data) * 0.6)
            on_continuation = data[cut] & 0xC0 == 0x80
            plain = 0x20 <= data[cut - 1] < 0x80 and 0x20 <= data[cut] < 0x80
            if (inside_character and on_continuation) or (not inside_character and plain):
                directory.mkdir(parents=True, exist_ok=True)
                path = directory / "agent-aaa.jsonl"
                path.write_bytes(data[:cut])
                return path, data[:cut]
    raise AssertionError("no layout put the 60 percent cut where the test needs it")


@pytest.mark.parametrize("inside_character", [False, True], ids=["mid-line", "mid-utf8"])
def test_partial_transcript_cut_at_sixty_percent_is_incomplete(inside_character, tmp_path, capsys):
    """Guards a build that exits 0, or treats a missing hand-back as complete, on a cut transcript.

    A transcript cut at 60 percent of its bytes, in the middle of a line or of a
    UTF-8 character, parses without an exception, reports one bad line, and
    exits 3 without ``--allow-partial`` and 0 with it.
    """
    path, data = cut_at_sixty_percent(tmp_path, inside_character=inside_character)
    blocked = run(capsys, path, "--issue", "1179")
    assert blocked.rc == 3
    assert blocked.tokens["bad_lines"] == "1"
    assert blocked.tokens["complete"] == "0"
    allowed = run(capsys, path, "--issue", "1179", "--allow-partial")
    assert allowed.rc == 0
    assert allowed.tokens["bad_lines"] == "1"
    assert path.read_bytes() == data


def test_deeply_nested_line_is_a_bad_line_not_a_crash(tmp_path, capsys):
    """Guards a build that lets the JSON parser's recursion error escape on a hostile line."""
    t = Transcript()
    t.raw("[" * 200000)
    t.bash("ls", "ok")
    t.end_turn()
    result = run(capsys, t.write(tmp_path), "--issue", "1179")
    assert (result.rc, result.tokens["bad_lines"]) == (0, "1")


# --------------------------------------------------------------------------- #
# record shapes
# --------------------------------------------------------------------------- #


def test_parallel_calls_are_matched_by_tool_use_id(tmp_path, capsys):
    """Guards a build that matches results to calls by adjacency instead of ``tool_use_id``.

    Parallel calls are separate records sharing ``message.id``; the results
    arrive in the other order. The failed ``mkdir`` is matched to its own error
    result, so ``scratch`` stays ``none``, and each call counts once.
    """
    t = Transcript()
    t.call("Bash", {"command": "mkdir /tmp/s/a"}, tid="toolu_a", mid="msg_1")
    t.call("Bash", {"command": "echo hi"}, tid="toolu_b", mid="msg_1")
    t.result("toolu_b", "hi")
    t.result("toolu_a", "mkdir: cannot create directory", is_error=True)
    t.end_turn()
    tokens = run(capsys, t.write(tmp_path), "--issue", "1179").tokens
    assert (tokens["scratch"], tokens["bash_calls"]) == ("none", "2")


def test_result_content_that_is_a_list_of_text_blocks_is_flattened(tmp_path, capsys):
    """Guards a build that skips flattening a list ``content``.

    A result whose ``content`` is a list of ``{type: "text", text}`` blocks is
    scanned like a string: a preflight line, a denial and a comment marker in
    list form are all found, and a non-text block is ignored.
    """
    t = Transcript()
    t.bash(PREFLIGHT_COMMAND, [{"type": "text", "text": PREFLIGHT_OK}])
    t.bash("curl x", [{"type": "text", "text": DENIAL}], is_error=True)
    t.bash(
        "gh issue view 1151 --json comments",
        [{"type": "image", "source": "x"}, {"type": "text", "text": "## Cold read - BUILD"}],
    )
    t.end_turn()
    tokens = run(capsys, t.write(tmp_path), "--issue", "1151").tokens
    assert (tokens["preflight"], tokens["denied"], tokens["comments_seen"]) == ("ok", "1", "1")


def test_result_content_of_none_is_empty_text(tmp_path, capsys):
    """Guards a build that crashes on, or mis-reads, a result whose ``content`` is ``None``.

    A result of ``None`` is empty text: the command still has a present result,
    so a ``mkdir`` with such a result is scratch use.
    """
    result = run(capsys, one_command(tmp_path, "mkdir /tmp/w", None), "--issue", "1179")
    assert (result.rc, result.tokens["scratch"]) == (0, "ok")


def test_plain_string_message_content_carries_no_blocks(tmp_path, capsys):
    """Guards a build that iterates a plain-string ``message.content`` as a list of blocks."""
    t = Transcript()
    t.put({"type": "user", "message": {"role": "user", "content": "hello there"}})
    t.put({"type": "assistant", "message": {"role": "assistant", "model": "claude-x", "content": "plain"}})
    t.bash("ls", "ok")
    t.end_turn()
    result = run(capsys, t.write(tmp_path), "--issue", "1179")
    assert (result.rc, result.tokens["bad_lines"], result.tokens["bash_calls"]) == (0, "0", "1")


@pytest.mark.parametrize(
    "record",
    [
        pytest.param({"type": "assistant", "message": "text only"}, id="message-is-text"),
        pytest.param({"type": "assistant"}, id="no-message-at-all"),
        pytest.param({"type": "assistant", "message": {"model": "m", "stop_reason": "tool_use"}}, id="assistant-message-without-content"),
        pytest.param({"type": "user", "message": {"role": "user"}}, id="user-message-without-content"),
        pytest.param({"type": "assistant", "message": {"content": [None, 3, "x", ["y"]]}}, id="blocks-are-not-objects"),
        pytest.param(
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": ["x"], "name": ["Bash"], "input": 3}]}},
            id="tool-use-id-and-name-are-lists",
        ),
        pytest.param(
            {
                "type": "assistant",
                "message": {"content": [{"type": "tool_use", "id": {"a": 1}, "name": "Bash", "input": {"command": "mkdir /tmp/w"}}]},
            },
            id="tool-use-id-is-an-object",
        ),
        pytest.param(
            {
                "type": "assistant",
                "message": {"content": [{"type": "tool_use", "id": "t", "name": "Bash", "input": {"command": 4}}]},
            },
            id="command-is-a-number",
        ),
        pytest.param(
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": ["x"], "content": {"a": 1}}]}},
            id="result-id-is-a-list",
        ),
        pytest.param(
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": {"a": 1}, "content": 5}]}},
            id="result-id-is-an-object",
        ),
        pytest.param(
            {
                "type": "user",
                "toolDenialKind": {"a": 1},
                "permissionDecision": "reject",
                "message": {"content": [{"type": "tool_result", "tool_use_id": "toolu_x", "content": "no", "is_error": "yes"}]},
            },
            id="denial-fields-of-the-wrong-type-on-a-result",
        ),
        pytest.param(
            {"type": "assistant", "version": 5, "message": {"model": ["m"], "stop_reason": ["end_turn"], "content": []}},
            id="version-model-and-stop-reason-of-the-wrong-type",
        ),
        pytest.param({"type": ["assistant"], "message": {"content": []}}, id="type-is-a-list"),
    ],
)
def test_malformed_record_fields_are_untrusted(record, tmp_path, capsys):
    """Guards a build that uses a field of an untrusted record as a key or set member unchecked.

    Fields of a file another tool writes are not trusted: a list where a name or
    an id belongs, a number for a command, a dict for content, must not raise.
    """
    t = Transcript()
    t.put(record)
    t.bash("ls", "ok")
    t.end_turn()
    result = run(capsys, t.write(tmp_path), "--issue", "1179")
    assert result.rc == 0
    assert result.tokens["bad_lines"] == "0"


def test_undecodable_bytes_are_replaced_not_fatal(tmp_path, capsys):
    """Guards a build that decodes the transcript strictly."""
    t = Transcript()
    t.bash("ls", "ok")
    t.end_turn()
    data = b"\xff\xfe not utf-8 \xc3\x28\n" + t.text().encode("utf-8")
    path = tmp_path / "agent-aaa.jsonl"
    path.write_bytes(data)
    result = run(capsys, path, "--issue", "1179")
    assert (result.rc, result.tokens["bad_lines"], result.tokens["bash_calls"]) == (0, "1", "1")


def test_a_repeated_tool_use_id_counts_once_and_other_tools_not_at_all(tmp_path, capsys):
    """Guards a build that counts ``bash_calls`` per record, or counts tool uses that are not ``Bash``."""
    t = Transcript()
    t.call("Bash", {"command": "echo one"}, tid="toolu_dup")
    t.call("Bash", {"command": "echo one"}, tid="toolu_dup")
    t.result("toolu_dup", "one")
    t.tool("Read", "x", file_path="a")
    t.tool("Grep", "x", pattern="a")
    t.end_turn()
    assert run(capsys, t.write(tmp_path), "--issue", "1179").tokens["bash_calls"] == "1"


# --------------------------------------------------------------------------- #
# model, version, agent type
# --------------------------------------------------------------------------- #


def test_model_is_the_sorted_distinct_set(tmp_path, capsys):
    """Guards a build that reports one model, an unsorted list, duplicates or never reads ``message.model``."""
    t = Transcript(model="claude-b")
    t.bash("ls", "ok")
    t.call("Read", {"file_path": "a"}, model="claude-a")
    t.result("toolu_002", "x")
    t.bash("pwd", "ok")
    t.end_turn()
    assert run(capsys, t.write(tmp_path / "a"), "--issue", "1179").tokens["model"] == "claude-a,claude-b"
    bare = Transcript()
    bare.model = ""
    bare.bash("ls", "ok")
    bare.end_turn()
    assert run(capsys, bare.write(tmp_path / "b"), "--issue", "1179").tokens["model"] == "unknown"


def test_version_is_the_first_one_a_record_carries(tmp_path, capsys):
    """Guards a build that reads ``version`` from a later record, or invents one when none is carried.

    The token is ``2.1.293`` for records that carry it, ``unknown`` for records
    that carry none, and the first record's value when versions differ.
    """
    t = Transcript()
    t.bash("ls", "ok")
    t.end_turn()
    assert run(capsys, t.write(tmp_path / "a"), "--issue", "1179").tokens["version"] == "2.1.293"
    none = Transcript(version=None)
    none.bash("ls", "ok")
    none.end_turn()
    assert run(capsys, none.write(tmp_path / "b"), "--issue", "1179").tokens["version"] == "unknown"
    mixed = Transcript(version=None)
    mixed.bash("ls", "ok")
    mixed.version = "2.1.100"
    mixed.bash("ls", "ok")
    mixed.version = "2.1.293"
    mixed.end_turn()
    assert run(capsys, mixed.write(tmp_path / "c"), "--issue", "1179").tokens["version"] == "2.1.100"


def write_meta(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


CLEAN_ARGS = ["--issue", "1179", "--scratch-dir", SCRATCH]


def clean_cold_run() -> Transcript:
    """A cold reader that ran the preflight, used its scratch directory and ran a test."""
    t = Transcript()
    t.bash(PREFLIGHT_COMMAND, PREFLIGHT_OK)
    t.bash(f"ls {SCRATCH}", "ok")
    t.bash("pytest -q", "ok")
    t.end_turn()
    return t


def test_agent_type_mismatch_is_flagged(tmp_path, capsys):
    """Guards a build that does not flag a reader of the wrong agent type.

    ``--expect-agent-type general-purpose`` on a sibling meta file saying
    ``Explore`` puts ``agent-type`` in ``flags``; the default meta file is the
    one beside the transcript with the same stem.
    """
    path = clean_cold_run().write(tmp_path, "agent-abc.jsonl")
    write_meta(tmp_path / "agent-abc.meta.json", json.dumps({"agentType": "Explore"}))
    tokens = run(capsys, path, *CLEAN_ARGS, "--expect-agent-type", "general-purpose").tokens
    assert tokens["agent_type"] == "Explore"
    assert tokens["flags"] == "agent-type"


def test_agent_type_that_matches_is_not_flagged(tmp_path, capsys):
    """Guards a build that flags ``agent-type`` whenever one is expected, or when the types match."""
    path = clean_cold_run().write(tmp_path, "agent-abc.jsonl")
    write_meta(tmp_path / "agent-abc.meta.json", json.dumps({"agentType": "general-purpose"}))
    tokens = run(capsys, path, *CLEAN_ARGS, "--expect-agent-type", "general-purpose").tokens
    assert (tokens["agent_type"], tokens["flags"]) == ("general-purpose", "none")
    tokens = run(capsys, path, *CLEAN_ARGS).tokens
    assert (tokens["agent_type"], tokens["flags"]) == ("general-purpose", "none")


@pytest.mark.parametrize(
    "meta",
    [None, "not json", "[]", "{}", json.dumps({"agentType": 5}), json.dumps({"agentType": ""}), json.dumps(["Explore"])],
    ids=["missing", "not-json", "list", "no-key", "number", "empty", "list-of-name"],
)
def test_missing_or_malformed_meta_gives_unknown_and_no_flag(meta, tmp_path, capsys):
    """Guards a build that crashes on, or flags, a missing or malformed meta file.

    A missing meta file gives ``agent_type=unknown`` and no flag, also with
    ``--expect-agent-type``: only a different *known* value is a mismatch.
    """
    path = clean_cold_run().write(tmp_path, "agent-abc.jsonl")
    if meta is not None:
        write_meta(tmp_path / "agent-abc.meta.json", meta)
    result = run(capsys, path, *CLEAN_ARGS, "--expect-agent-type", "general-purpose")
    assert (result.rc, result.tokens["agent_type"], result.tokens["flags"]) == (0, "unknown", "none")


def test_meta_option_overrides_the_sibling_file(tmp_path, capsys):
    """Guards a build that ignores ``--meta`` and always reads the sibling meta file."""
    t = Transcript()
    t.bash("ls", "ok")
    t.end_turn()
    path = t.write(tmp_path / "run", "agent-abc.jsonl")
    write_meta(tmp_path / "run" / "agent-abc.meta.json", json.dumps({"agentType": "Explore"}))
    other = tmp_path / "elsewhere" / "meta.json"
    other.parent.mkdir()
    write_meta(other, json.dumps({"agentType": "general-purpose"}))
    assert run(capsys, path, "--issue", "1179", "--meta", str(other)).tokens["agent_type"] == "general-purpose"
    assert run(capsys, path, "--issue", "1179").tokens["agent_type"] == "Explore"


def test_meta_run_is_read_only(tmp_path, capsys):
    """Guards a build that opens the transcript or the meta file for writing, or writes beside them.

    The transcript and the meta file, each mode 0o444 in a directory mode
    0o555, are audited with exit 0 and the meta file's ``agentType``; both stay
    byte-identical and the directory gains no file. Skipped when the process
    can write there anyway, as root can.
    """
    directory = tmp_path / "readonly"
    t = Transcript()
    t.bash("ls", "ok")
    t.end_turn()
    path = t.write(directory, "agent-abc.jsonl")
    meta = directory / "side.json"
    write_meta(meta, json.dumps({"agentType": "general-purpose"}))
    path.chmod(0o444)
    meta.chmod(0o444)
    directory.chmod(0o555)
    try:
        if os.access(directory, os.W_OK) or CAN_WRITE_READ_ONLY_DIR:
            pytest.skip("the process can write into a mode 0o555 directory")
        before = (path.read_bytes(), meta.read_bytes(), sorted(os.listdir(directory)))
        result = run(capsys, path, "--issue", "1179", "--meta", str(meta), "--details")
        after = (path.read_bytes(), meta.read_bytes(), sorted(os.listdir(directory)))
    finally:
        directory.chmod(0o755)
    assert result.rc == 0
    assert result.tokens["agent_type"] == "general-purpose"
    assert after == before


# --------------------------------------------------------------------------- #
# the printed report
# --------------------------------------------------------------------------- #


def golden_transcript(directory: Path):
    """One transcript touching every token, with a known report."""
    t = Transcript(model="claude-b")
    t.raw("[1]")
    t.raw("")
    t.raw("null")
    t.put({"type": "user", "message": {"role": "user", "content": "hello"}})
    t.bash(PREFLIGHT_COMMAND, PREFLIGHT_OK)
    t.bash("mkdir -p /tmp/g", "")
    t.tool("Read", "text", file_path="a.md")
    t.call("Bash", {"command": "echo repeated"}, tid="toolu_dup")
    t.call("Bash", {"command": "echo repeated"}, tid="toolu_dup", model="claude-a")
    t.result("toolu_dup", "repeated")
    t.bash("uv run pytest -q", "Exit code 1\n1 failed", is_error=True)
    t.tool("Grep", "x", pattern="a")
    t.bash("gh issue view 1151 --json comments", COMMENT_RESULT)
    t.bash("rm x", "refused", permissionDecision={"decision": "reject"})
    t.end_turn()
    path = t.write(directory, "agent-golden.jsonl")
    write_meta(directory / "agent-golden.meta.json", json.dumps({"agentType": "general-purpose"}))
    return path


GOLDEN_LINE = (
    "AUDIT version=2.1.293 complete=1 bad_lines=2 agent_type=general-purpose model=claude-a,claude-b "
    "bash_calls=6 scratch=ok probe_build=ran gh_calls=1 comments_fetch=1 comments_seen=1 denied=1 "
    "preflight=ok flags=comments-read,gh-used,denied"
)


def test_audit_line_has_the_keys_in_the_stated_order(tmp_path, capsys):
    """Guards a build that prints the tokens in another order, with another prefix, or computes one wrongly.

    The report is one line ``AUDIT key=value ...`` in the order
    version, complete, bad_lines, agent_type, model, bash_calls, scratch,
    probe_build, gh_calls, comments_fetch, comments_seen, denied, preflight,
    flags. The whole line of a transcript touching every token is asserted.
    """
    result = run(capsys, golden_transcript(tmp_path), "--issue", "1151")
    assert result.rc == 0
    assert result.line == GOLDEN_LINE
    assert list(result.tokens) == TOKEN_ORDER
    assert result.out.count("\n") == 1


def test_json_object_has_integer_counts_and_one_string_of_flags(tmp_path, capsys):
    """Guards a build that emits counts as strings, ``flags`` as a list, or omits a token under ``--json``."""
    result = run(capsys, golden_transcript(tmp_path), "--issue", "1151", "--json")
    assert result.rc == 0
    assert result.out.count("\n") == 1
    payload = json.loads(result.out)
    assert list(payload) == TOKEN_ORDER
    for key in INT_TOKENS:
        assert type(payload[key]) is int, key
    for key in set(TOKEN_ORDER) - set(INT_TOKENS):
        assert type(payload[key]) is str, key
    assert payload["flags"] == "comments-read,gh-used,denied"
    text_tokens = Run(0, GOLDEN_LINE + "\n", "").tokens
    assert {key: str(value) for key, value in payload.items()} == text_tokens


def test_flags_are_listed_in_the_stated_order(tmp_path, capsys):
    """Guards a build that drops a flag or emits the flags in another order.

    scratch-none, no-probe-build, comments-read, gh-used, denied, agent-type,
    then preflight-none or preflight-failed.
    """
    t = Transcript()
    t.bash("gh issue view 1151 --json comments", COMMENT_RESULT)
    t.bash("rm x", DENIAL, is_error=True)
    t.end_turn()
    path = t.write(tmp_path / "a", "agent-abc.jsonl")
    write_meta(tmp_path / "a" / "agent-abc.meta.json", json.dumps({"agentType": "Explore"}))
    flags = run(capsys, path, "--issue", "1151", "--expect-agent-type", "general-purpose").tokens["flags"]
    assert flags == "scratch-none,no-probe-build,comments-read,gh-used,denied,agent-type,preflight-none"
    failed = Transcript()
    failed.bash("echo setup", "PREFLIGHT failed cause=x")
    failed.bash("gh issue view 1151 --json comments", COMMENT_RESULT)
    failed.bash("rm x", DENIAL, is_error=True)
    failed.end_turn()
    path = failed.write(tmp_path / "b", "agent-abc.jsonl")
    write_meta(tmp_path / "b" / "agent-abc.meta.json", json.dumps({"agentType": "Explore"}))
    flags = run(capsys, path, "--issue", "1151", "--expect-agent-type", "general-purpose").tokens["flags"]
    assert flags == "scratch-none,no-probe-build,comments-read,gh-used,denied,agent-type,preflight-failed"


def test_spaces_in_an_untrusted_value_do_not_break_the_line(tmp_path, capsys):
    """Guards a build that prints a value containing whitespace, which would split the one-line report."""
    t = Transcript(version="2.1.293 beta\nx", model="my model")
    t.bash("ls", "ok")
    t.end_turn()
    path = t.write(tmp_path, "agent-abc.jsonl")
    write_meta(tmp_path / "agent-abc.meta.json", json.dumps({"agentType": "two words"}))
    result = run(capsys, path, "--issue", "1179")
    assert result.out.count("\n") == 1
    assert list(result.tokens) == TOKEN_ORDER
    assert result.tokens["version"] == "2.1.293_beta_x"
    assert result.tokens["agent_type"] == "two_words"
    assert result.tokens["model"] == "my_model"
    payload = json.loads(run(capsys, path, "--issue", "1179", "--json").out)
    assert list(payload) == TOKEN_ORDER
    for key in INT_TOKENS:
        assert type(payload[key]) is int, key
    for key in set(TOKEN_ORDER) - set(INT_TOKENS):
        assert type(payload[key]) is str, key
    assert (payload["version"], payload["agent_type"], payload["model"]) == ("2.1.293_beta_x", "two_words", "my_model")


# --------------------------------------------------------------------------- #
# --details
# --------------------------------------------------------------------------- #

DETAIL_RE = re.compile(r'^DETAIL id=(?P<id>\S+) flags=(?P<flags>\S+) command=(?P<command>".*") result=(?P<result>null|".*")$')


def details_transcript(directory: Path):
    long_command = "gh issue view 1151 --json comments " + "x" * 300
    long_result = "## Cold read - BUILD " + "y" * 300
    t = Transcript()
    first = t.bash(long_command, long_result)
    t.bash("ls", "plain")
    second = t.bash("gh label list", "labels")
    third = t.bash("rm x", "refused", toolDenialKind="classifier")
    fourth = t.bash("gh api x", answered=False)
    t.end_turn()
    return t.write(directory), (first, second, third, fourth), long_command, long_result


def test_details_lists_flagged_commands_truncated(tmp_path, capsys):
    """Guards a build whose ``--details`` lists unflagged commands, loses their order, or does not truncate.

    One ``DETAIL`` line per Bash command that carries ``gh-used``,
    ``comments-read`` or ``denied``, in transcript order: its id, its flags, the
    first 170 characters of the command and the first 120 of the result, both
    JSON-quoted (``result=null`` when it has none).
    """
    path, ids, command, output = details_transcript(tmp_path)
    result = run(capsys, path, "--issue", "1151", "--details")
    assert result.rc == 0
    assert result.out.split("\n")[0].startswith("AUDIT ")
    rows = [DETAIL_RE.match(line) for line in result.details]
    assert all(rows), result.details
    assert [row["id"] for row in rows] == list(ids)
    assert [row["flags"] for row in rows] == ["comments-read,gh-used", "gh-used", "denied", "gh-used"]
    assert json.loads(rows[0]["command"]) == command[:170]
    assert len(json.loads(rows[0]["command"])) == 170
    assert json.loads(rows[0]["result"]) == output[:120]
    assert len(json.loads(rows[0]["result"])) == 120
    assert json.loads(rows[1]["result"]) == "labels"
    assert rows[3]["result"] == "null"


def test_details_object_under_json_has_the_same_fields(tmp_path, capsys):
    """Guards a build whose ``--json`` object lacks ``details`` (or adds it without ``--details``)."""
    path, ids, command, output = details_transcript(tmp_path)
    payload = json.loads(run(capsys, path, "--issue", "1151", "--json", "--details").out)
    assert list(payload)[: len(TOKEN_ORDER)] == TOKEN_ORDER
    assert payload["details"][0] == {
        "id": ids[0],
        "flags": "comments-read,gh-used",
        "command": command[:170],
        "result": output[:120],
    }
    assert payload["details"][3]["result"] is None
    assert [item["id"] for item in payload["details"]] == list(ids)
    plain = json.loads(run(capsys, path, "--issue", "1151", "--json").out)
    assert "details" not in plain
    assert run(capsys, path, "--issue", "1151").details == []


# --------------------------------------------------------------------------- #
# usage, exit codes and the module's own constraints
# --------------------------------------------------------------------------- #


def test_missing_transcript_path_exits_2(tmp_path, capsys):
    """Guards a build that raises (or exits 1) on a transcript path that does not exist."""
    missing = tmp_path / "absent.jsonl"
    result = run(capsys, missing, "--issue", "1179")
    assert result.rc == 2
    assert result.out == ""
    assert result.err == f"cold_read_audit: cannot read transcript {missing}: {os.strerror(errno.ENOENT)}\n"


def test_unreadable_transcript_path_exits_2(tmp_path, capsys):
    """Guards a build that raises on a transcript path that cannot be read (here, a directory)."""
    result = run(capsys, tmp_path, "--issue", "1179")
    assert (result.rc, result.out) == (2, "")
    assert result.err == f"cold_read_audit: cannot read transcript {tmp_path}: {os.strerror(errno.EISDIR)}\n"


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(["--issue", "abc"], id="issue-not-an-integer"),
        pytest.param([], id="issue-missing"),
        pytest.param(["--issue", "1179", "--role", "judge"], id="unknown-role"),
    ],
)
def test_usage_errors_exit_2(argv, tmp_path, capsys):
    """Guards a build that declares ``--issue`` as text, makes it optional, or accepts any ``--role``.

    argparse writes its usage message to stderr and ``main`` raises
    ``SystemExit(2)``.
    """
    path = one_command(tmp_path, "ls")
    capsys.readouterr()
    with pytest.raises(SystemExit) as exit_info:
        mod.main(["--transcript", str(path), *argv])
    assert exit_info.value.code == 2
    assert capsys.readouterr().out == ""


def test_transcript_option_is_required(capsys):
    """Guards a build that runs without a transcript."""
    with pytest.raises(SystemExit) as exit_info:
        mod.main(["--issue", "1179"])
    assert exit_info.value.code == 2


def test_imports_are_standard_library_only_and_never_reach_the_network(capsys):
    """Guards a build that imports a third-party module, ``evals/``, or a module that can post.

    An AST walk over every ``import`` and ``from`` statement, at any depth,
    finds only standard-library modules and none of ``subprocess``, ``socket``,
    ``urllib`` or ``http``: the script never posts a comment, applies a label,
    voids a read or edits an issue.
    """
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "a relative import cannot be a standard-library module"
            names.add((node.module or "").split(".")[0])
    assert names, "the walk found no import at all"
    assert names <= set(sys.stdlib_module_names), sorted(names - set(sys.stdlib_module_names))
    assert not names & {"subprocess", "socket", "urllib", "http"}


def test_script_preamble_is_code_not_text():
    """Guards a build that drops or neuters the script preamble, or fakes it in a comment.

    The shebang is the first line; the future import, the ``main`` signature
    and the ``__main__`` guard are read from the syntax tree, so a commented-out
    line or a misspelt guard does not satisfy them.
    """
    source = SCRIPT.read_text(encoding="utf-8")
    assert source.startswith("#!/usr/bin/env python3\n")
    tree = ast.parse(source)
    futures = [name.name for node in tree.body if isinstance(node, ast.ImportFrom) and node.module == "__future__" for name in node.names]
    assert futures == ["annotations"]
    mains = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main"]
    assert len(mains) == 1
    wanted = ast.parse("def main(argv: list[str] | None = None) -> int: ...").body[0]
    assert ast.dump(mains[0].args) == ast.dump(wanted.args)
    assert ast.dump(mains[0].returns) == ast.dump(wanted.returns)
    guard = tree.body[-1]
    assert isinstance(guard, ast.If)
    assert ast.dump(guard.test) == ast.dump(ast.parse('__name__ == "__main__"', mode="eval").body)
    assert [ast.dump(node) for node in guard.body] == [ast.dump(node) for node in ast.parse("raise SystemExit(main())").body]
    assert guard.orelse == []


def run_script(*args: str) -> subprocess.CompletedProcess:
    """Run the script as a program, isolated from the environment, the way the conductor does."""
    return subprocess.run(
        [sys.executable, "-I", str(SCRIPT), *args], capture_output=True, text=True, timeout=120, check=False
    )


def test_script_run_as_a_program_prints_one_audit_line_and_exits_0(tmp_path):
    """Guards a build whose ``__main__`` guard is misspelt, commented out or never reached.

    Run as a process, a complete transcript prints exactly one ``AUDIT`` line
    on stdout, nothing on stderr, and exits 0; importing the module in the
    suite cannot show that the entry point works.
    """
    path = one_command(tmp_path, "ls")
    done = run_script("--transcript", str(path), "--issue", "1179")
    assert done.returncode == 0
    assert done.stderr == ""
    lines = done.stdout.split("\n")
    assert len(lines) == 2 and lines[1] == ""
    report = Run(done.returncode, done.stdout, done.stderr)
    assert list(report.tokens) == TOKEN_ORDER
    assert report.tokens["bash_calls"] == "1"


def test_script_run_as_a_program_on_a_partial_transcript_prints_then_exits_3(tmp_path):
    """Guards a build whose process exit status is not ``main``'s return value (``main()`` without ``SystemExit``).

    An incomplete transcript prints its report, says why on stderr, and the
    process exits 3.
    """
    t = Transcript()
    t.bash("ls", "ok")
    t.call("Read", {"file_path": "a"})
    done = run_script("--transcript", str(t.write(tmp_path)), "--issue", "1179")
    assert done.returncode == 3
    assert Run(3, done.stdout, "").tokens["complete"] == "0"
    assert "incomplete" in done.stderr
    allowed = run_script("--transcript", str(tmp_path / "agent-aaa.jsonl"), "--issue", "1179", "--allow-partial")
    assert allowed.returncode == 0


def test_script_run_as_a_program_on_a_missing_path_exits_2(tmp_path):
    """Guards a build whose process exits 0 or 1, or prints a traceback, on a transcript path that is missing."""
    missing = tmp_path / "absent.jsonl"
    done = run_script("--transcript", str(missing), "--issue", "1179")
    assert done.returncode == 2
    assert done.stdout == ""
    assert done.stderr == f"cold_read_audit: cannot read transcript {missing}: {os.strerror(errno.ENOENT)}\n"
    usage = run_script("--transcript", str(missing), "--issue", "abc")
    assert usage.returncode == 2
    assert usage.stdout == ""


# --------------------------------------------------------------------------- #
# strengthened by the independent teeth pass (PR #1225)
# --------------------------------------------------------------------------- #


def test_heredoc_opener_line_still_counts(tmp_path, capsys):
    """Guards a build that drops the opener's own line together with the heredoc body.

    Only the body is removed: ``gh api x --input - <<EOF`` is a ``gh`` call, a
    comments fetch written with a heredoc is still a fetch, and so is a ``gh``
    after a pipe on the opener line.
    """
    assert gh_counts(capsys, tmp_path / "a", "gh api x --input - <<EOF\n{}\nEOF") == ("1", "0")
    assert gh_counts(capsys, tmp_path / "b", "gh issue view 1151 --json comments <<'EOF'\nhi\nEOF") == ("1", "1")
    assert gh_counts(capsys, tmp_path / "c", "cat <<EOF | gh label list\nbody\nEOF") == ("1", "0")


def test_every_text_block_of_a_list_result_is_read(tmp_path, capsys):
    """Guards a build that keeps only the first text block of a list ``content``.

    A comments marker in the second, or the last, of several text blocks is
    seen; so is one after non-text blocks.
    """
    for name, blocks in {
        "second": [{"type": "text", "text": "a"}, {"type": "text", "text": "## Cold read - BUILD"}],
        "last-of-three": [
            {"type": "text", "text": "a"},
            {"type": "image", "source": "x"},
            {"type": "text", "text": "b"},
            {"type": "text", "text": "## Cold read - BUILD"},
        ],
    }.items():
        assert seen(capsys, tmp_path / name, blocks) == "1", name


def test_list_result_with_untrusted_members_is_read_from_its_text_blocks(tmp_path, capsys):
    """Guards a build that joins a non-string ``text`` or calls ``.get`` on a non-object list member.

    A list holding a number, a string, a list, ``None``, a text block whose
    ``text`` is a number, and then a real text block is read from the real one.
    """
    blocks = [5, "x", ["y"], None, {"type": "text", "text": 5}, {"type": "text", "text": "## Cold read - BUILD"}]
    assert seen(capsys, tmp_path, blocks) == "1"


def test_only_bash_tool_uses_are_commands(tmp_path, capsys):
    """Guards a build that treats any tool whose input has a ``command`` field as ``Bash``.

    A ``Monitor`` use carrying a ``gh`` comments fetch, a ``mkdir`` and a
    ``pytest`` counts in no ``Bash`` token: ``bash_calls``, ``gh_calls``,
    ``comments_fetch``, ``comments_seen``, ``scratch`` and ``probe_build``.
    """
    t = Transcript()
    tid = t.call("Monitor", {"command": "gh issue view 1151 -c; mkdir /tmp/m; pytest -q"})
    t.result(tid, "## Cold read - BUILD")
    t.bash("ls", "ok")
    t.end_turn()
    tokens = run(capsys, t.write(tmp_path), "--issue", "1151").tokens
    assert tokens["bash_calls"] == "1"
    assert (tokens["gh_calls"], tokens["comments_fetch"], tokens["comments_seen"]) == ("0", "0", "0")
    assert (tokens["scratch"], tokens["probe_build"]) == ("none", "none")


def test_scratch_dir_is_matched_literally(tmp_path, capsys):
    """Guards a build that leaves the scratch path unescaped in its regular expression.

    ``/tmp/a+b`` and ``/tmp/(x)`` match themselves; ``/tmp/t.mp`` does not
    match ``/tmp/tXmp``.
    """
    for index, (path, command, expected) in enumerate(
        [
            ("/tmp/a+b", "ls /tmp/a+b", "ok"),
            ("/tmp/a+b", "ls /tmp/aab", "none"),
            ("/tmp/(x)", "ls /tmp/(x)", "ok"),
            ("/tmp/t.mp", "ls /tmp/t.mp", "ok"),
            ("/tmp/t.mp", "ls /tmp/tXmp", "none"),
        ]
    ):
        tokens = tokens_of(capsys, tmp_path / str(index), command, "--issue", "1179", "--scratch-dir", path)
        assert tokens["scratch"] == expected, (path, command)


def test_a_preflight_command_that_names_a_probe_is_still_not_a_probe(tmp_path, capsys):
    """Guards a build that exempts a preflight command from ``scratch`` but not from ``probe_build``.

    The preflight command here holds ``pytest``, ``make test`` and
    ``teeth_check.py``, and names the scratch directory: its result begins
    ``PREFLIGHT ok``, so it is neither a probe nor scratch use.
    """
    t = Transcript()
    t.bash(NOISY_PREFLIGHT_COMMAND, PREFLIGHT_OK)
    t.end_turn()
    tokens = run(capsys, t.write(tmp_path), "--issue", "1179", "--scratch-dir", SCRATCH).tokens
    assert (tokens["scratch"], tokens["probe_build"], tokens["preflight"]) == ("none", "none", "ok")
    plain = Transcript()
    plain.bash(NOISY_PREFLIGHT_COMMAND, PREFLIGHT_OK)
    plain.end_turn()
    tokens = run(capsys, plain.write(tmp_path / "b"), "--issue", "1179").tokens
    assert (tokens["scratch"], tokens["probe_build"]) == ("none", "none")


def test_patterns_read_the_command_never_the_result(tmp_path, capsys):
    """Guards a build that searches the result text for the scratch or probe patterns.

    A command that merely prints ``mkdir``, ``git clone``, ``pytest`` or the
    scratch path is not scratch use or a probe, with and without
    ``--scratch-dir``.
    """
    t = Transcript()
    t.bash("pwd", "mkdir -p /tmp/w && git clone x y")
    t.bash("ls", "collected via pytest, then make test, then teeth_check.py")
    t.end_turn()
    tokens = run(capsys, t.write(tmp_path / "a"), "--issue", "1179").tokens
    assert (tokens["scratch"], tokens["probe_build"]) == ("none", "none")
    named = Transcript()
    named.bash("pwd", SCRATCH + "\n")
    named.end_turn()
    tokens = run(capsys, named.write(tmp_path / "b"), "--issue", "1179", "--scratch-dir", SCRATCH).tokens
    assert tokens["scratch"] == "none"


def test_is_error_false_is_not_an_error(tmp_path, capsys):
    """Guards a build that reads ``is_error`` as the presence of the key.

    A result with ``is_error`` false is a success: ``mkdir`` is scratch use,
    and denial text without the error flag is not a denial.
    """
    assert tokens_of(capsys, tmp_path / "a", "mkdir /tmp/w", "--issue", "1179", is_error=False)["scratch"] == "ok"
    assert denied(capsys, tmp_path / "b", DENIAL, is_error=False) == "0"


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        pytest.param("Permission for this action", "1", id="the-prefix-alone"),
        pytest.param("Permission for this action was denied", "1", id="a-shorter-sentence"),
        pytest.param("Permission for this action has been denied. Reason: x", "1", id="the-long-sentence"),
        pytest.param("Exit code 1\nPermission for this action has been denied", "0", id="later-in-the-text"),
        pytest.param("blocked: Permission for this action", "0", id="after-other-words"),
    ],
)
def test_denial_prefix_must_begin_an_error_result(output, expected, tmp_path, capsys):
    """Guards a build that finds ``Permission for this action`` anywhere in the text, or needs its longer sentence.

    The text must begin with the prefix, whatever follows it; the same words
    later in the text, or after other words, are not a denial.
    """
    assert denied(capsys, tmp_path, output, is_error=True) == expected


@pytest.mark.parametrize(
    ("decision", "expected"),
    [
        pytest.param({"decision": "reject"}, "1", id="reject"),
        pytest.param({"decision": "ask"}, "0", id="ask"),
        pytest.param({"decision": "deny"}, "0", id="deny"),
        pytest.param({"decision": "allow"}, "0", id="allow"),
        pytest.param({}, "0", id="no-decision"),
        pytest.param({"decision": None}, "0", id="null-decision"),
        pytest.param("reject", "0", id="a-string-instead-of-an-object"),
        pytest.param(["reject"], "0", id="a-list-instead-of-an-object"),
    ],
)
def test_only_a_permission_decision_of_reject_is_a_denial(decision, expected, tmp_path, capsys):
    """Guards a build that reads any ``permissionDecision`` other than ``allow`` as ``reject``, or crashes on a non-object.

    Only ``permissionDecision.decision`` equal to ``reject`` counts; ``ask``,
    ``deny``, a missing or null decision, and a ``permissionDecision`` that is not
    an object do not, and none of them raises.
    """
    assert denied(capsys, tmp_path, "fine", permissionDecision=decision) == expected


def test_hand_back_without_a_result_record_still_completes(tmp_path, capsys):
    """Guards a build that needs the hand-back call to have a result.

    The hand-back is the reader's last act, so its result record may be absent
    from the file.
    """
    t = Transcript()
    t.bash("ls", "ok")
    t.call("SubagentHandback", {"report": "r"})
    result = run(capsys, t.write(tmp_path), "--issue", "1179")
    assert (result.rc, result.tokens["complete"]) == (0, "1")


def test_hand_back_need_not_be_the_last_call(tmp_path, capsys):
    """Guards a build that accepts the hand-back only as the last ``tool_use``."""
    t = Transcript()
    t.bash("ls", "ok")
    t.hand_back()
    t.tool("Read", "x", file_path="a")
    result = run(capsys, t.write(tmp_path), "--issue", "1179")
    assert (result.rc, result.tokens["complete"]) == (0, "1")


def test_earlier_end_turn_then_a_null_stop_reason_is_incomplete(tmp_path, capsys):
    """Guards a build that lets a null ``stop_reason`` keep an earlier ``end_turn``.

    The last assistant record decides: here it has no stop reason at all.
    """
    t = Transcript()
    t.end_turn("early")
    t.call("Read", {"file_path": "a"}, stop=None)
    result = run(capsys, t.write(tmp_path), "--issue", "1179")
    assert (result.rc, result.tokens["complete"]) == (3, "0")


@pytest.mark.parametrize("stop", ["max_tokens", "stop_sequence", "tool_use", "pause_turn", ""])
def test_only_end_turn_is_a_finished_turn(stop, tmp_path, capsys):
    """Guards a build that counts ``max_tokens`` or ``stop_sequence`` (a cut-off reply) as complete."""
    t = Transcript()
    t.bash("ls", "ok")
    t.call("Read", {"file_path": "a"}, stop=stop)
    result = run(capsys, t.write(tmp_path), "--issue", "1179")
    assert (result.rc, result.tokens["complete"]) == (3, "0")


def test_comments_seen_reads_every_comments_fetch_result(tmp_path, capsys):
    """Guards a build that reads only the first, or only the last, comments-fetch result.

    ``comments_seen`` is 1 when some fetch returned comments, wherever it
    falls among the fetches; with every fetch empty it is 0.
    """
    fetch = "gh issue view 1151 --json comments"
    cases = {
        "empty-then-full": ([EMPTY_COMMENTS, COMMENT_RESULT], "1"),
        "full-then-empty": ([COMMENT_RESULT, EMPTY_COMMENTS], "1"),
        "full-in-the-middle": ([EMPTY_COMMENTS, COMMENT_RESULT, EMPTY_COMMENTS], "1"),
        "all-empty": ([EMPTY_COMMENTS, EMPTY_COMMENTS], "0"),
    }
    for name, (results, expected) in cases.items():
        t = Transcript()
        for output in results:
            t.bash(fetch, output)
        t.end_turn()
        assert run(capsys, t.write(tmp_path / name), "--issue", "1151").tokens["comments_seen"] == expected, name


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        pytest.param("PREFLIGHT ok", "ok", id="bare-ok"),
        pytest.param("PREFLIGHT failed", "failed", id="bare-failed"),
        pytest.param("note: PREFLIGHT ok follows", "none", id="ok-inside-the-text"),
        pytest.param("see PREFLIGHT failed later", "none", id="failed-inside-the-text"),
    ],
)
def test_preflight_words_must_begin_the_result(output, expected, tmp_path, capsys):
    """Guards a build that finds ``PREFLIGHT ok`` or ``PREFLIGHT failed`` anywhere in the result, or needs more than the prefix.

    The result must begin with the words; a result that is exactly them is
    enough, and the same words later in the text are not a preflight.
    """
    assert tokens_of(capsys, tmp_path, "echo setup", "--issue", "1179", output=output)["preflight"] == expected


def test_preflight_is_read_from_bash_results_only(tmp_path, capsys):
    """Guards a build that reads ``preflight`` from the result of any tool.

    A ``Read`` result that begins ``PREFLIGHT ok`` is not a preflight; and the
    first ``Bash`` result decides even when a ``Read`` result before it says
    otherwise.
    """
    only_read = Transcript()
    only_read.tool("Read", PREFLIGHT_OK, file_path="a")
    only_read.end_turn()
    assert run(capsys, only_read.write(tmp_path / "a"), "--issue", "1179").tokens["preflight"] == "none"
    mixed = Transcript()
    mixed.tool("Read", "PREFLIGHT failed cause=x", file_path="a")
    mixed.bash("echo setup", PREFLIGHT_OK)
    mixed.end_turn()
    assert run(capsys, mixed.write(tmp_path / "b"), "--issue", "1179").tokens["preflight"] == "ok"


def test_preflight_failed_fires_for_a_tool_use_before_the_preflight(tmp_path, capsys):
    """Guards a build that counts only tool uses after the preflight command for ``preflight-failed``.

    The body says the transcript holds a ``tool_use`` other than the ``Bash``
    command that set ``preflight``: before it counts as much as after it.
    """
    t = Transcript()
    t.tool("Read", "text", file_path="a")
    t.bash("echo setup", "PREFLIGHT failed cause=x")
    t.end_turn()
    flags = run(capsys, t.write(tmp_path), "--issue", "1179").tokens["flags"]
    assert flags == "scratch-none,no-probe-build,preflight-failed"


def test_cold_read_marker_is_enough_without_its_continuation(tmp_path, capsys):
    """Guards a build that needs more than ``## Cold read`` (a dash, a verdict) to see a comment."""
    assert seen(capsys, tmp_path, "## Cold read") == "1"


def test_deeply_nested_fetch_result_is_not_a_crash(tmp_path, capsys):
    """Guards a build that lets a recursion error escape when a fetch result is parsed as JSON."""
    path = one_command(tmp_path, "gh issue view 1151 --json comments", "[" * 200000)
    result = run(capsys, path, "--issue", "1151")
    assert (result.rc, result.tokens["comments_seen"]) == (0, "0")


def test_deeply_nested_meta_file_is_unknown_not_a_crash(tmp_path, capsys):
    """Guards a build that lets a recursion error escape when the meta file is parsed."""
    path = one_command(tmp_path, "ls")
    write_meta(tmp_path / "agent-aaa.meta.json", "[" * 200000)
    result = run(capsys, path, "--issue", "1179", "--expect-agent-type", "general-purpose")
    assert (result.rc, result.tokens["agent_type"]) == (0, "unknown")
    assert "agent-type" not in result.tokens["flags"]


def test_unhashable_ids_do_not_crash_and_do_not_hide_the_valid_commands(tmp_path, capsys):
    """Guards a build that uses a ``tool_use`` or ``tool_use_id`` as a set member or key unchecked.

    A list or an object where an id belongs must not raise, and the valid
    commands around it still count.
    """
    t = Transcript()
    t.call("Bash", {"command": "mkdir /tmp/lost"}, tid=["x"])
    t.call("Bash", {"command": "echo"}, tid={"a": 1})
    t.result(["x"], "ok")
    t.result({"a": 1}, "ok")
    t.bash("mkdir /tmp/w", "ok")
    t.end_turn()
    result = run(capsys, t.write(tmp_path), "--issue", "1179")
    assert (result.rc, result.tokens["scratch"], result.tokens["bad_lines"]) == (0, "ok", "0")


def test_denial_fields_of_the_wrong_type_on_a_real_result_are_read_safely(tmp_path, capsys):
    """Guards a build that calls ``.get`` on a string ``permissionDecision`` or breaks on an odd ``toolDenialKind``.

    The record reaches the denial test (it holds a ``tool_result``): a string
    ``permissionDecision`` is not a reject, and the result counts at most once.
    """
    t = Transcript()
    tid = t.call("Bash", {"command": "ls"})
    t.result(tid, "ok", permissionDecision="reject")
    t.end_turn()
    result = run(capsys, t.write(tmp_path), "--issue", "1179")
    assert (result.rc, result.tokens["denied"]) == (0, "0")
    odd = Transcript()
    tid = odd.call("Bash", {"command": "ls"})
    odd.result(tid, "ok", toolDenialKind={"a": 1}, permissionDecision=["reject"])
    odd.end_turn()
    result = run(capsys, odd.write(tmp_path / "b"), "--issue", "1179")
    assert result.rc == 0
    assert result.tokens["denied"] in {"0", "1"}


VENDOR_MAP = Path(__file__).resolve().parent.parent / "vendor-map.json"


def vendor_entry(name: str) -> re.Pattern[str]:
    return re.compile(
        rf'^( +)\{{\n\1  "kind": "file",\n\1  "source": "engine/{re.escape(name)}",\n\1  "target": "\.claude/scripts/{re.escape(name)}"\n\1\}},?\n',
        re.MULTILINE,
    )


def test_vendor_map_entry_is_appended_after_the_dispatch_entry_in_the_existing_indentation():
    """Guards an entry written in another indentation, or placed before the dispatch entry instead of appended.

    The audit entry is one ``kind: file`` entry in the indentation of the other
    ``cold_read_*`` entries, and it comes after the dispatch entry.
    """
    text = VENDOR_MAP.read_text(encoding="utf-8")
    json.loads(text)
    siblings = [vendor_entry(name).search(text) for name in (
        "cold_read_evidence.py", "cold_read_stamp.py", "cold_read_edit_lint.py", "cold_read_ledger.py", "cold_read_dispatch.py"
    )]
    assert all(siblings)
    audit = vendor_entry("cold_read_audit.py").findall(text)
    assert len(audit) == 1
    indent = siblings[0].group(1)
    assert len(indent) % 2 == 0 and indent
    assert {match.group(1) for match in siblings} == {indent}
    assert audit[0] == indent
    assert vendor_entry("cold_read_audit.py").search(text).start() > siblings[-1].start()
