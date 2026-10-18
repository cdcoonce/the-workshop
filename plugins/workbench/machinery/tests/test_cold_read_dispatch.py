"""Contract for ``cold_read_dispatch.py preflight`` (the-workshop#1181).

Incident: on 2026-10-10 a cold reader whose scratch directory could not be
created spent 174,751 tokens and about nine minutes on a read that could not
probe, and said so only in its report. The reader's first command is now
``preflight``; a failed environment must cost one tool call and print one
parseable line, so the transcript audit can tell "ran the preflight" from "did
not".

Every test fakes ``git`` and ``uv`` only through the module's ``_run_tool``
seam and the sentinel round trip only through its ``_roundtrip_sentinel`` seam;
everything else runs against real directories under ``tmp_path``. Each
docstring names the defect it guards.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import inspect
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(SCRIPTS_DIR))

import cold_read_dispatch as mod  # noqa: E402
import cold_read_ledger  # noqa: E402
import cold_read_stamp  # noqa: E402

SCRIPT = SCRIPTS_DIR / "cold_read_dispatch.py"
OK_GIT = (0, "git version 2.44.0\n", "")
OK_UV = (0, "uv 0.4.0\n", "")
NOT_ROOT = hasattr(os, "geteuid") and os.geteuid() != 0


def fake_tools(monkeypatch, *, git=OK_GIT, uv=OK_UV):
    """Replace ``_run_tool`` with a recorder; return its ``(argv, timeout)`` calls.

    ``git`` and ``uv`` are each the ``(exit_code, stdout, stderr)`` tuple the
    fake returns for that program, or ``None`` for "cannot be started".
    """
    calls: list[tuple[list[str], float]] = []

    def fake(argv, timeout=30):
        calls.append((list(argv), timeout))
        return {"git": git, "uv": uv}[argv[0]]

    monkeypatch.setattr(mod, "_run_tool", fake)
    return calls


def fake_sentinel(monkeypatch, behaviour: str):
    """Replace ``_roundtrip_sentinel``; return the ``(directory, value)`` calls.

    ``behaviour`` is ``"oserror"`` (raise ``OSError``) or ``"differing"``
    (return a value other than the one it was given).
    """
    calls: list[tuple[str, str]] = []

    def fake(directory, value):
        calls.append((directory, value))
        if behaviour == "oserror":
            raise OSError("faked: the sentinel cannot be written")
        return value + "-not-what-was-written"

    monkeypatch.setattr(mod, "_roundtrip_sentinel", fake)
    return calls


def run_preflight(capsys, scratch) -> tuple[int, str, str]:
    """Call ``main`` for ``preflight`` and return ``(exit_code, stdout, stderr)``."""
    code = mod.main(["preflight", "--scratch", str(scratch)])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def snapshot(root: Path) -> dict[str, bytes | None]:
    """Every entry under *root* by relative path: file bytes, ``None`` for a directory.

    Timestamps are deliberately not part of the snapshot.
    """
    return {
        path.relative_to(root).as_posix(): path.read_bytes() if path.is_file() else None
        for path in sorted(root.rglob("*"))
    }


def populated_scratch(tmp_path: Path) -> Path:
    """A writable directory that already holds files, a dotfile and a subdirectory."""
    scratch = tmp_path / "scratch"
    (scratch / "sub").mkdir(parents=True)
    (scratch / "keep.txt").write_bytes(b"keep me\n")
    (scratch / ".hidden").write_bytes(b"\x00\xff\x00")
    (scratch / "sub" / "inner.txt").write_bytes(b"inner")
    return scratch


# --------------------------------------------------------------------------- #
# the ok line
# --------------------------------------------------------------------------- #


def test_writable_directory_prints_the_exact_ok_line(tmp_path, monkeypatch, capsys):
    """The ok line is the whole contract the transcript audit parses: exact
    text, exit 0, one newline, nothing on stderr (a build that also warns on
    stderr on the ok path breaks "nothing on stderr")."""
    fake_tools(monkeypatch)
    code, out, err = run_preflight(capsys, tmp_path)
    assert out == f"PREFLIGHT ok scratch={tmp_path} git=git version 2.44.0 uv=uv 0.4.0\n"
    assert code == 0
    assert err == ""


def test_each_version_is_the_first_line_of_the_program_output(
    tmp_path, monkeypatch, capsys
):
    """``--version`` output can run to several lines; a build that prints the
    whole stdout (stripped or raw) breaks the one-line contract."""
    fake_tools(
        monkeypatch,
        git=(0, "git version 2.44.0\nextra line\n", ""),
        uv=(0, "uv 0.4.0\nsecond line\nthird line\n", ""),
    )
    code, out, err = run_preflight(capsys, tmp_path)
    assert out == f"PREFLIGHT ok scratch={tmp_path} git=git version 2.44.0 uv=uv 0.4.0\n"
    assert (code, err) == (0, "")


def test_tools_run_as_version_calls_with_the_default_timeout(
    tmp_path, monkeypatch, capsys
):
    """The tools are ``git --version`` then ``uv --version`` through the seam
    with its default timeout. A build that asks for ``-V`` still prints the
    same line under a fake that ignores ``argv``, and one whose call site
    passes its own short timeout is invisible to a fake that ignores that too."""
    calls = fake_tools(monkeypatch)
    run_preflight(capsys, tmp_path)
    assert sorted(calls) == [(["git", "--version"], 30), (["uv", "--version"], 30)]


def test_run_tool_signature_is_argv_and_a_thirty_second_timeout():
    """A fake never sees the seam's own default, so a default of ``None`` (no
    limit) or one second would pass every faked test; pin the signature."""
    parameters = inspect.signature(mod._run_tool).parameters
    assert list(parameters) == ["argv", "timeout"]
    assert parameters["timeout"].default == 30


# --------------------------------------------------------------------------- #
# scratch causes
# --------------------------------------------------------------------------- #


def test_missing_directory_is_scratch_missing_and_is_not_created(
    tmp_path, monkeypatch, capsys
):
    """A directory that is not there is reported, never created for the
    reader: a created scratch directory would hide the very fault."""
    fake_tools(monkeypatch)
    scratch = tmp_path / "absent"
    code, out, err = run_preflight(capsys, scratch)
    assert out == "PREFLIGHT failed cause=scratch-missing\n"
    assert (code, err) == (1, "")
    assert not scratch.exists()


@pytest.mark.skipif(not NOT_ROOT, reason="root can write a 0o500 directory")
def test_directory_with_mode_0o500_is_scratch_unwritable(
    tmp_path, monkeypatch, capsys
):
    """A read-only scratch directory is the 2026-10-10 failure: the reader
    cannot create its probe build, and must say so in one line. Skipped as
    root, which writes anywhere; the faked and real-seam tests below hold for
    any user."""
    fake_tools(monkeypatch)
    scratch = tmp_path / "readonly"
    scratch.mkdir()
    scratch.chmod(0o500)
    try:
        code, out, err = run_preflight(capsys, scratch)
    finally:
        scratch.chmod(0o700)
    assert out == "PREFLIGHT failed cause=scratch-unwritable\n"
    assert (code, err) == (1, "")


@pytest.mark.parametrize("behaviour", ["oserror", "differing"])
def test_a_failed_sentinel_round_trip_is_scratch_unwritable(
    tmp_path, monkeypatch, capsys, behaviour
):
    """Whichever user runs the suite: an ``OSError`` from the round trip, and a
    value read back that differs from the one written, are both
    ``scratch-unwritable``. A build that never calls the round trip, or that
    accepts any value read back, prints an ok line here."""
    fake_tools(monkeypatch)
    calls = fake_sentinel(monkeypatch, behaviour)
    code, out, err = run_preflight(capsys, tmp_path)
    assert out == "PREFLIGHT failed cause=scratch-unwritable\n"
    assert (code, err) == (1, "")
    assert len(calls) == 1
    directory, value = calls[0]
    assert str(directory) == str(tmp_path)
    assert isinstance(value, str) and value


def test_real_round_trip_raises_oserror_for_a_missing_directory(tmp_path):
    """The real seam, not faked, signals failure with ``OSError`` for any
    user. A seam that touches nothing and returns the value it was given
    passes every faked test and the mode-0o500 test only when not root."""
    with pytest.raises(OSError):
        mod._roundtrip_sentinel(str(tmp_path / "absent"), "value")


def test_real_round_trip_returns_the_value_it_wrote_and_leaves_no_trace(tmp_path):
    """The seam returns exactly what it wrote (newlines and non-ASCII included,
    so no text-mode translation changes it) and leaves the directory as found."""
    scratch = populated_scratch(tmp_path)
    before = snapshot(scratch)
    value = "line one\r\nline two é中\n"
    assert mod._roundtrip_sentinel(str(scratch), value) == value
    assert snapshot(scratch) == before


# --------------------------------------------------------------------------- #
# tool causes and the order of causes
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("git", [None, (1, "", "git: broken")], ids=["cannot-start", "non-zero"])
def test_git_that_cannot_run_is_git_missing(tmp_path, monkeypatch, capsys, git):
    """A ``git`` that cannot be started or exits non-zero is missing. A build
    that skips the ``git`` check prints an ok line here."""
    fake_tools(monkeypatch, git=git)
    code, out, err = run_preflight(capsys, tmp_path)
    assert out == "PREFLIGHT failed cause=git-missing\n"
    assert (code, err) == (1, "")


@pytest.mark.parametrize("uv", [None, (2, "", "uv: broken")], ids=["cannot-start", "non-zero"])
def test_uv_that_cannot_run_is_uv_missing(tmp_path, monkeypatch, capsys, uv):
    """A ``uv`` that cannot be started or exits non-zero is missing. A build
    that skips the ``uv`` check prints an ok line here."""
    fake_tools(monkeypatch, uv=uv)
    code, out, err = run_preflight(capsys, tmp_path)
    assert out == "PREFLIGHT failed cause=uv-missing\n"
    assert (code, err) == (1, "")


@pytest.mark.parametrize(
    ("scratch", "sentinel", "git", "uv", "cause"),
    [
        pytest.param("writable", "real", None, None, "git-missing", id="git-before-uv"),
        pytest.param(
            "writable", "real", None, (1, "", ""), "git-missing", id="git-before-uv-exit"
        ),
        pytest.param(
            "writable", "real", OK_GIT, None, "uv-missing", id="uv-when-git-is-fine"
        ),
        pytest.param("absent", "real", None, None, "scratch-missing", id="missing-before-git"),
        pytest.param(
            "absent", "oserror", None, None, "scratch-missing", id="missing-before-unwritable"
        ),
        pytest.param(
            "writable", "oserror", None, None, "scratch-unwritable", id="unwritable-before-git"
        ),
        pytest.param(
            "writable", "differing", None, None, "scratch-unwritable", id="differing-before-git"
        ),
        pytest.param(
            "writable", "oserror", OK_GIT, None, "scratch-unwritable", id="unwritable-before-uv"
        ),
    ],
)
def test_the_first_failing_cause_in_the_documented_order_is_reported(
    tmp_path, monkeypatch, capsys, scratch, sentinel, git, uv, cause
):
    """The order is scratch-missing, scratch-unwritable, git-missing,
    uv-missing. A build that reports ``uv-missing`` ahead of ``git-missing``,
    or runs the tool checks ahead of the scratch checks, names a cause that is
    not the first failing one."""
    fake_tools(monkeypatch, git=git, uv=uv)
    if sentinel != "real":
        fake_sentinel(monkeypatch, sentinel)
    directory = tmp_path / ("absent" if scratch == "absent" else "present")
    if scratch == "writable":
        directory.mkdir()
    code, out, err = run_preflight(capsys, directory)
    assert out == f"PREFLIGHT failed cause={cause}\n"
    assert (code, err) == (1, "")


# --------------------------------------------------------------------------- #
# the directory is left as found
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("git", "uv", "cause"),
    [
        pytest.param(OK_GIT, OK_UV, None, id="ok"),
        pytest.param(None, OK_UV, "git-missing", id="git-missing"),
        pytest.param(OK_GIT, None, "uv-missing", id="uv-missing"),
    ],
)
def test_the_directory_holds_exactly_what_it_held_before(
    tmp_path, monkeypatch, capsys, git, uv, cause
):
    """The preflight deletes nothing but its own sentinel: the same entry
    names, each pre-existing file with its bytes, and no sentinel left behind,
    on the ok path and on every failure after the round trip. A build that
    removes the directory, or leaves the sentinel in place, goes red here."""
    fake_tools(monkeypatch, git=git, uv=uv)
    scratch = populated_scratch(tmp_path)
    before = snapshot(scratch)
    code, out, err = run_preflight(capsys, scratch)
    assert scratch.is_dir(), "the preflight removed the scratch directory"
    assert snapshot(scratch) == before
    if cause is None:
        expected = f"PREFLIGHT ok scratch={scratch} git=git version 2.44.0 uv=uv 0.4.0\n"
    else:
        expected = f"PREFLIGHT failed cause={cause}\n"
    assert out == expected
    assert (code, err) == (0 if cause is None else 1, "")


PROBE = textwrap.dedent(
    """
    import json, os, sys

    sys.path.insert(0, sys.argv[1])
    import cold_read_dispatch as mod

    directory = os.path.realpath(sys.argv[2])
    tamper = sys.argv[3] in ("tamper", "tamper-bytes")
    fail_read = sys.argv[3] == "fail-read"
    payload = b"\\xff\\xfe\\xfa" if sys.argv[3] == "tamper-bytes" else b"tampered-by-the-test"
    removed, busy = [], []


    def hook(event, args):
        if busy:
            return
        if event == "os.remove":
            removed.append(os.path.basename(os.fsdecode(args[0])))
        elif fail_read and event == "open":
            path, _mode, flags = args
            if (
                isinstance(path, str)
                and flags & os.O_ACCMODE == os.O_RDONLY
                and os.path.dirname(os.path.realpath(path)) == directory
            ):
                raise PermissionError(13, "the test made the read-back fail")
        elif tamper and event == "open":
            path, _mode, flags = args
            if (
                isinstance(path, str)
                and flags & os.O_ACCMODE == os.O_RDONLY
                and os.path.dirname(os.path.realpath(path)) == directory
                and os.path.exists(path)
            ):
                busy.append(True)
                try:
                    with open(path, "wb") as handle:
                        handle.write(payload)
                finally:
                    busy.pop()


    sys.addaudithook(hook)
    try:
        returned, raised = mod._roundtrip_sentinel(directory, "written-by-the-test"), None
    except OSError as error:
        returned, raised = None, type(error).__name__
    print(
        json.dumps(
            {
                "returned": returned,
                "raised": raised,
                "removed": removed,
                "left": sorted(os.listdir(directory)),
            }
        )
    )
    """
)


def probe_round_trip(directory: Path, mode: str) -> dict:
    """Run the real ``_roundtrip_sentinel`` in a child under an audit hook.

    The hook records every path removed and, in ``"tamper"`` mode (or
    ``"tamper-bytes"``, which writes bytes that are not UTF-8), rewrites the
    sentinel the moment anything reopens it for reading; in ``"fail-read"``
    mode it makes that reopen raise ``PermissionError`` instead. The result
    also carries what was left in *directory*. It lives in a child
    process because an audit hook cannot be uninstalled. Nothing here depends
    on how the module names, writes or removes its sentinel.
    """
    proc = subprocess.run(
        [sys.executable, "-I", "-B", "-c", PROBE, str(SCRIPTS_DIR), str(directory), mode],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_the_sentinel_never_overwrites_an_existing_entry(tmp_path, monkeypatch, capsys):
    """Learn the name the module gives its sentinel (from the removal it
    performs), plant a file of that name with known bytes in a fresh directory
    and run the preflight there. A build that opens one constant file name for
    a truncating write destroys the planted file; criterion: "each
    pre-existing file has the bytes it had before"."""
    learning = tmp_path / "learning"
    learning.mkdir()
    learned = probe_round_trip(learning, "plain")["removed"]
    assert learned, "the round trip removed nothing, so there is no sentinel name to plant"
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    for name in learned:
        (scratch / name).write_bytes(b"precious bytes\n")
    before = snapshot(scratch)
    fake_tools(monkeypatch)
    code, out, err = run_preflight(capsys, scratch)
    assert (code, err) == (0, "")
    assert out.startswith("PREFLIGHT ok ")
    assert snapshot(scratch) == before


def test_the_round_trip_returns_what_the_sentinel_file_holds(tmp_path):
    """The seam returns the value it READ BACK. Rewrite the sentinel at the
    moment it is reopened for reading: a build that writes, removes and returns
    the value it was given (or checks ``os.access`` and returns it) never
    reopens the file and so returns the written value, not the file's."""
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    assert probe_round_trip(scratch, "tamper")["returned"] == "tampered-by-the-test"
    assert not any(scratch.iterdir())


def test_a_failed_read_back_still_removes_the_sentinel(tmp_path):
    """A failure after the sentinel was written must not leave it behind:
    "no sentinel remains" holds for every run, so the removal cannot be a step
    that only the success path reaches."""
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    outcome = probe_round_trip(scratch, "fail-read")
    assert outcome["raised"] == "PermissionError"
    assert outcome["left"] == []


def test_a_sentinel_that_reads_back_as_undecodable_bytes_is_a_differing_value(tmp_path):
    """The sentinel is read back with ``errors="replace"``. A file another
    process corrupted is then a value that differs (``scratch-unwritable``),
    not a ``UnicodeDecodeError`` that escapes as a traceback with no PREFLIGHT
    line."""
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    returned = probe_round_trip(scratch, "tamper-bytes")["returned"]
    assert returned != "written-by-the-test"
    assert "\ufffd" in returned


# --------------------------------------------------------------------------- #
# the real tool runner
# --------------------------------------------------------------------------- #


def test_run_tool_returns_none_for_a_program_that_does_not_exist():
    """A program that cannot be started is ``None``, not an exception: a
    missing ``uv`` once produced an 18-line traceback and no PREFLIGHT line."""
    assert mod._run_tool(["cold-read-dispatch-no-such-program-xyz", "--version"]) is None


@pytest.mark.skipif(not NOT_ROOT, reason="root can execute a file without mode bits")
def test_run_tool_returns_none_for_a_file_that_cannot_be_executed(tmp_path):
    """A start failure that is not 'not found' is still 'cannot be started'."""
    plain = tmp_path / "plain.sh"
    plain.write_text("#!/bin/sh\nexit 0\n")
    plain.chmod(0o644)
    assert mod._run_tool([str(plain)]) is None


def test_run_tool_returns_none_for_a_program_that_outlives_the_timeout():
    """A tool that times out counts as one that cannot be started. Without the
    ``timeout`` the call waits the program out (here 3 s) and returns a tuple."""
    started = [sys.executable, "-c", "import time; time.sleep(3)"]
    assert mod._run_tool(started, timeout=0.2) is None


def test_run_tool_returns_exit_code_stdout_and_stderr():
    """Otherwise a tuple whose first element is the exit code."""
    program = "import sys; sys.stdout.write('out'); sys.stderr.write('err'); sys.exit(3)"
    assert mod._run_tool([sys.executable, "-c", program]) == (3, "out", "err")
    result = mod._run_tool([sys.executable, "-c", "pass"])
    assert isinstance(result, tuple) and result[0] == 0


def test_run_tool_decodes_output_that_is_not_utf8_instead_of_raising():
    """A tool's output is another process's data: undecodable bytes become
    replacement characters, so ``main`` still prints its one line."""
    program = "import sys; sys.stdout.buffer.write(b'\\xff\\xfe ok')"
    result = mod._run_tool([sys.executable, "-c", program])
    assert result is not None and result[0] == 0
    assert "ok" in result[1] and "\ufffd" in result[1]


def test_main_with_an_empty_path_reports_git_missing(tmp_path, monkeypatch, capsys):
    """Nothing faked but the environment: with an empty directory as the whole
    of ``PATH`` neither tool can start, so the cause is ``git-missing``, the
    exit code is 1 and stderr stays empty (no traceback)."""
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    code, out, err = run_preflight(capsys, scratch)
    assert out == "PREFLIGHT failed cause=git-missing\n"
    assert (code, err) == (1, "")
    assert not any(scratch.iterdir())


# --------------------------------------------------------------------------- #
# usage and module shape
# --------------------------------------------------------------------------- #


def test_missing_scratch_option_raises_systemexit_2_with_a_usage_message(capsys):
    """Exit 2 is a usage error and ``main`` raises it (the argument parser's
    ``SystemExit``). A build that catches that ``SystemExit`` and returns 2
    instead is a different contract; the usage message must also name
    ``--scratch`` on stderr, with nothing on stdout."""
    with pytest.raises(SystemExit) as raised:
        mod.main(["preflight"])
    assert raised.value.code == 2
    captured = capsys.readouterr()
    assert "--scratch" in captured.err
    assert captured.out == ""


# --------------------------------------------------------------------------- #
# survivors the independent teeth pass found (the-workshop#1223 follow-up)
# --------------------------------------------------------------------------- #


def test_run_tool_hands_subprocess_run_exactly_the_timeout_it_was_given(monkeypatch):
    """The timeout that reaches ``subprocess.run`` is the seam's contract: 30
    seconds by default and the caller's value otherwise. A build that passes a
    constant, ``min(timeout, 1)`` or a tenth of it still passes every test that
    only observes whether a long sleep is cut short, because nothing else sees
    the number. The tuple it returns is still ``(returncode, stdout, stderr)``."""
    recorded: list[dict] = []

    def recorder(argv, **kwargs):
        recorded.append(dict(kwargs, argv=list(argv)))
        return subprocess.CompletedProcess(argv, 7, stdout="out text", stderr="err text")

    monkeypatch.setattr(mod.subprocess, "run", recorder)
    assert mod._run_tool(["x"]) == (7, "out text", "err text")
    assert mod._run_tool(["x"], timeout=5) == (7, "out text", "err text")
    assert [call["argv"] for call in recorded] == [["x"], ["x"]]
    assert [call["timeout"] for call in recorded] == [30, 5]


PLANTED = b"planted before the open proceeds\n"
PLANT_PROBE = textwrap.dedent(
    """
    import contextlib, io, json, os, sys

    sys.path.insert(0, sys.argv[1])
    import cold_read_dispatch as mod

    directory = os.path.realpath(sys.argv[2])
    mode = sys.argv[3]
    planted, busy = [], []
    content = open(sys.argv[4], "rb").read()


    def hook(event, args):
        if busy or event != "open":
            return
        path, _mode, flags = args
        if not (isinstance(path, str) and flags & os.O_CREAT):
            return
        if os.path.dirname(os.path.realpath(path)) != directory:
            return
        if os.path.exists(path) or len(planted) >= 3:
            return
        busy.append(True)
        try:
            with open(path, "wb") as handle:
                handle.write(content)
        finally:
            busy.pop()
        planted.append(os.path.basename(path))


    def fake_run_tool(argv, timeout=30):
        return {"git": (0, "git version 2.44.0\\n", ""), "uv": (0, "uv 0.4.0\\n", "")}[argv[0]]


    mod._run_tool = fake_run_tool
    sys.addaudithook(hook)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        if mode == "preflight":
            code = mod.main(["preflight", "--scratch", directory])
        else:
            code = mod._roundtrip_sentinel(directory, "seam value")
    print(
        json.dumps(
            {
                "code": code,
                "out": out.getvalue(),
                "planted": sorted(planted),
                "left": sorted(os.listdir(directory)),
            }
        )
    )
    """
)


@pytest.mark.parametrize("mode", ["preflight", "seam"])
def test_a_file_planted_where_any_create_is_about_to_happen_survives(tmp_path, mode):
    """Naming-independent form of "deletes nothing but its own sentinel". A
    child under an audit hook plants a file, with known bytes, at the exact
    path of every create-open inside the directory that does not exist yet (at
    most three), before that open proceeds; then it runs the real preflight (or
    the real seam). A build whose sentinel name is exclusive retries a new name
    and leaves each planted file alone; a build whose name is fixed, or derived
    from the pid or the directory, opens it for a truncating write and empties
    it. The ok line is unchanged and no sentinel remains."""
    scratch = (tmp_path / "scratch").resolve()
    scratch.mkdir()
    content = tmp_path / "planted.bin"
    content.write_bytes(PLANTED)
    proc = subprocess.run(
        [sys.executable, "-I", "-B", "-c", PLANT_PROBE, str(SCRIPTS_DIR), str(scratch), mode, str(content)],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    outcome = json.loads(proc.stdout)
    assert outcome["planted"], "the module created nothing, so there was nothing to plant under"
    for name in outcome["planted"]:
        assert (scratch / name).exists(), f"{name} was removed"
        assert (scratch / name).read_bytes() == PLANTED, f"{name} was overwritten"
    assert outcome["left"] == outcome["planted"], "an entry other than the planted files remains"
    if mode == "preflight":
        assert outcome["code"] == 0
        assert outcome["out"] == (
            f"PREFLIGHT ok scratch={scratch} git=git version 2.44.0 uv=uv 0.4.0\n"
        )
    else:
        assert outcome["code"] == "seam value"


def run_script(*args: str) -> subprocess.CompletedProcess:
    """Run the script file as a process, isolated, the way a reader would."""
    return subprocess.run(
        [sys.executable, "-I", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def test_running_the_script_as_a_process_exits_with_the_line_it_printed(tmp_path):
    """The reader runs ``python3 cold_read_dispatch.py preflight ...``, not an
    import. A script whose ``__main__`` block does not hand ``main``'s result to
    ``SystemExit`` (it calls ``main()`` and drops the code, ends with exit 0, or
    is missing) exits 0 on a failed environment. The scratch check precedes git
    and uv, so this needs neither tool nor network."""
    proc = run_script("preflight", "--scratch", str(tmp_path / "absent"))
    assert proc.returncode == 1
    assert proc.stdout == "PREFLIGHT failed cause=scratch-missing\n"
    assert proc.stderr == ""


def test_running_the_script_without_scratch_exits_2_with_usage_on_stderr():
    """A usage error in a real process: exit 2, nothing on stdout, a usage
    message naming ``--scratch`` on stderr."""
    proc = run_script("preflight")
    assert proc.returncode == 2
    assert proc.stdout == ""
    assert "--scratch" in proc.stderr


@pytest.mark.parametrize("code", [3, 127, -1])
def test_git_exiting_with_any_other_non_zero_code_is_git_missing(
    tmp_path, monkeypatch, capsys, code
):
    """Every non-zero exit, not only 1 and 2, counts as missing: 127 is the
    shell's "not found" and a negative code is a signal. A build that tests
    ``> 0`` or ``in (1, 2)`` treats these as a working ``git``."""
    fake_tools(monkeypatch, git=(code, "git version 2.44.0\n", ""))
    exit_code, out, err = run_preflight(capsys, tmp_path)
    assert out == "PREFLIGHT failed cause=git-missing\n"
    assert (exit_code, err) == (1, "")


@pytest.mark.parametrize("code", [3, 127, -1])
def test_uv_exiting_with_any_other_non_zero_code_is_uv_missing(
    tmp_path, monkeypatch, capsys, code
):
    """The same for ``uv``."""
    fake_tools(monkeypatch, uv=(code, "uv 0.4.0\n", ""))
    exit_code, out, err = run_preflight(capsys, tmp_path)
    assert out == "PREFLIGHT failed cause=uv-missing\n"
    assert (exit_code, err) == (1, "")


def scratch_with_empty_entries(tmp_path: Path) -> Path:
    """``populated_scratch`` plus an empty subdirectory and a zero-byte file."""
    scratch = populated_scratch(tmp_path)
    (scratch / "empty-dir").mkdir()
    (scratch / "empty.txt").write_bytes(b"")
    return scratch


def entries_with_kinds(root: Path) -> dict[str, tuple[str, bytes | None]]:
    """Every entry under *root* by relative path: ``(kind, bytes)``, with
    ``None`` bytes for anything that is not a regular file."""
    entries: dict[str, tuple[str, bytes | None]] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            entries[relative] = ("symlink", None)
        elif path.is_dir():
            entries[relative] = ("dir", None)
        else:
            entries[relative] = ("file", path.read_bytes())
    return entries


@pytest.mark.parametrize(
    ("git", "uv", "cause"),
    [
        pytest.param(OK_GIT, OK_UV, None, id="ok"),
        pytest.param(None, OK_UV, "git-missing", id="git-missing"),
        pytest.param(OK_GIT, None, "uv-missing", id="uv-missing"),
    ],
)
def test_empty_entries_are_left_exactly_as_found(
    tmp_path, monkeypatch, capsys, git, uv, cause
):
    """An empty subdirectory and a zero-byte file look like debris, so a build
    that tidies the directory after its sentinel is gone removes them. The
    directory must hold the same entry names, kinds and bytes after an ok run
    and after a failure run."""
    fake_tools(monkeypatch, git=git, uv=uv)
    scratch = scratch_with_empty_entries(tmp_path)
    before = entries_with_kinds(scratch)
    assert before["empty-dir"] == ("dir", None)
    assert before["empty.txt"] == ("file", b"")
    code, out, err = run_preflight(capsys, scratch)
    assert (code, err) == (0 if cause is None else 1, "")
    assert out.startswith("PREFLIGHT ok " if cause is None else "PREFLIGHT failed ")
    assert entries_with_kinds(scratch) == before


# --------------------------------------------------------------------------- #
# build: the generator procedure step 1 describes (the-workshop#1178)
#
# On 2026-10-10 the reader prompts for this gate were assembled by a one-off
# script that hashed the body differently from `cold_read_stamp.py`, hardcoded
# plugin-cache paths, a user id and a fork branch, and left detector 10 to the
# reader. Every test below fakes `gh` and the detectors only through the module
# seams `_run_gh` and `_run_detector`; `_run_git` runs real `git` against real
# repositories (an `origin` and a clone) under `tmp_path`, and the tests that
# watch it wrap the real seam.
# --------------------------------------------------------------------------- #

REPO_ROOT = Path(__file__).resolve().parents[4]
COMMAND_MD = (
    REPO_ROOT / "plugins" / "workbench" / "skills" / "vault-cold-read" / "references" / "command.md"
)
VECTOR = Path(__file__).resolve().parent / "fixtures" / "cold_read_stamp_vector.json"
HAND_BUILT = "Build path: hand-built under the `drain-queue` skill"
TRUNK_AND_INTEGRATION = 'trunk_branch = "dev"\nintegration_target = "afk/staging"\n'
BRANCHES = ("dev", "afk/staging", "afk/epic-7", "afk/epic-12", "override-branch")
SIBLING_MODULES = frozenset({"cold_read_stamp", "cold_read_ledger"})
READER_GIVEN = (
    "The cold constraint",
    "Probe builds",
    "Detectors",
    "Survivors and reachability",
    "Evidence rule",
    "Every finding carries a default",
    "Anti-rubber-stamp",
    "Constraints",
    "Reader contract",
)
GIT_ENV = {
    "GIT_AUTHOR_NAME": "Fixture",
    "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
    "GIT_COMMITTER_NAME": "Fixture",
    "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}
REAL_RUN_DETECTOR = getattr(mod, "_run_detector", None)
FIVE_STDOUT = '{"rows": [], "verdict": "ok"}\n'
TEN_STDOUT = '{"matched": false}\n'
UNSET = object()


def git_in(cwd, *args: str) -> str:
    """Run real ``git`` in *cwd* with a fixed identity and no user config."""
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
        env={**os.environ, **GIT_ENV},
    )
    assert proc.returncode == 0, f"git {' '.join(args)} failed: {proc.stderr}"
    return proc.stdout.strip()


def commit_file(repo, relative: str, text: str, message: str = "change") -> str:
    """Write *text* to *relative* in *repo*, commit it and return the new SHA."""
    target = Path(repo) / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    git_in(repo, "add", relative)
    git_in(repo, "commit", "-q", "-m", message)
    return git_in(repo, "rev-parse", "HEAD")


class World:
    """A bare ``origin``, the ``seed`` repository that pushes to it and a clone.

    ``main`` and each of ``BRANCHES`` hold a ``marker.txt`` naming the branch,
    so a tree archived from the wrong branch is visible in its files.
    """

    def __init__(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        self.root = root
        self.origin = root / "origin.git"
        self.seed = root / "seed"
        self.checkout = root / "checkout"
        git_in(root, "init", "-q", "--bare", "-b", "main", str(self.origin))
        git_in(root, "init", "-q", "-b", "main", str(self.seed))
        git_in(self.seed, "remote", "add", "origin", str(self.origin))
        self.tips: dict[str, str] = {}
        commit_file(self.seed, "marker.txt", "main\n", "main")
        self.tips["main"] = commit_file(self.seed, "src/app.py", "print('app')\n", "app")
        git_in(self.seed, "push", "-q", "origin", "main")
        for branch in BRANCHES:
            git_in(self.seed, "checkout", "-q", "-b", branch, "main")
            self.tips[branch] = commit_file(self.seed, "marker.txt", f"{branch}\n", branch)
            git_in(self.seed, "push", "-q", "origin", branch)
        git_in(self.seed, "checkout", "-q", "main")
        git_in(root, "clone", "-q", str(self.origin), str(self.checkout))


def clone_of(world: World, destination: Path, config: str | None = None) -> Path:
    """A fresh clone of the world's origin, with ``.afk/config.toml`` when *config* is given."""
    git_in(destination.parent, "clone", "-q", str(world.origin), str(destination))
    if config is not None:
        (destination / ".afk").mkdir()
        (destination / ".afk" / "config.toml").write_text(config, encoding="utf-8")
    return destination


PLACEHOLDER_LINES = (
    "ENGINE=<engine>\n"
    "AFK=<path-to-afk-agent-system>\n"
    "TREE=<local checkout>\n"
    "REF=<fork point SHA>\n"
    "VAULT=<absolute vault path>\n"
)
PROBE_TEXT = (
    "Probe builds text, with the ref <fork point SHA>.\n\n"
    "```text\n## Not a heading: it sits inside a code fence\n```\n\n"
    "Text after the fence belongs to the same section.\n"
)
SPEC_INTRO = (
    "# A spec copy for the tests\n\n"
    "Intro, never given to the reader. Step 2 fetches comments with --comments; read-only.\n\n"
)
SPEC_PROCEDURE = "1. Conductor only: step 2 fetches them with --comments. This is read-only.\n"
DEFAULT_GIVEN = ("Probe builds", "Detectors", "Reader contract")


def spec_text(
    *,
    given=DEFAULT_GIVEN,
    omit=(),
    bullet=True,
    detectors_extra="",
    probe_text=PROBE_TEXT,
    contract_extra="",
) -> str:
    """A small spec: three sections the reader is given and two it is not.

    *omit* leaves named sections out of the file while the bullet still names
    them; *bullet* ``False`` drops the ``What the reader is given.`` bullet.
    """
    contract = "- **Agent.** The cold reader runs as a `general-purpose` subagent.\n"
    if bullet:
        names = ", ".join(f"`{name}`" for name in given)
        contract += (
            "- **What the reader is given.** The reader's prompt carries these "
            f"sections of this file verbatim and no others: {names}.\n"
        )
    bodies = {
        "Probe builds": probe_text,
        "Detectors": PLACEHOLDER_LINES + detectors_extra,
        "Reader contract": contract + contract_extra,
    }
    parts = [SPEC_INTRO]
    for name, text in bodies.items():
        if name not in omit:
            parts.append(f"## {name}\n\n{text}\n")
    parts.append(f"## Procedure\n\n{SPEC_PROCEDURE}")
    return "".join(parts)


class Result:
    """What one ``main(["build", ...])`` call returned and wrote."""

    def __init__(self, code: int, out: str, err: str, out_dir: Path) -> None:
        self.code, self.out, self.err, self.out_dir = code, out, err, out_dir

    @property
    def manifest(self):
        path = self.out_dir / "manifest.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    @property
    def reader(self):
        path = self.out_dir / "reader.md"
        return path.read_bytes().decode("utf-8") if path.exists() else None


class BuildEnv:
    """Everything one ``build`` run needs, with ``gh`` and the detectors faked."""

    repo = "octo/repo"
    issue = 42

    def __init__(self, tmp_path: Path, world: World, monkeypatch, capsys) -> None:
        self.tmp_path, self.world = tmp_path, world
        self.monkeypatch, self.capsys = monkeypatch, capsys
        self.module = mod
        self.checkout = world.checkout
        self.scratch_root = tmp_path / "scratch-root"
        self.scratch_root.mkdir()
        self.out = tmp_path / "out"
        self.afk = tmp_path / "afk-project"
        self.afk.mkdir()
        self.spec = tmp_path / "spec.md"
        self.spec.write_text(spec_text(), encoding="utf-8")
        self.comments_json = tmp_path / "comments.json"
        self.write_comments([])
        self.gh_calls: list = []
        self.detector_calls: list = []
        self.set_body("Plain body.\n")
        self.fake_detectors()

    def write_comments(self, comments) -> None:
        self.comments_json.write_text(json.dumps({"comments": comments}), encoding="utf-8")

    def set_body(self, body, *, response=UNSET) -> None:
        """Fake ``gh`` to return *body* (or *response*, which may be ``None``)."""
        calls = self.gh_calls = []

        def fake(args, timeout=30):
            calls.append((list(args), timeout))
            if response is not UNSET:
                return response
            payload = {"number": self.issue, "state": "open", "body": body}
            return 0, json.dumps(payload), ""

        self.monkeypatch.setattr(self.module, "_run_gh", fake)

    def fake_detectors(self, *, five=(0, FIVE_STDOUT, ""), ten=(0, TEN_STDOUT, "")) -> None:
        """Fake the detector seam; each result is a tuple, a callable on argv or an exception."""
        calls = self.detector_calls = []

        def fake(argv, cwd, timeout):
            body_file = argv[argv.index("--body-file") + 1] if "--body-file" in argv else None
            exists = body_file is not None and Path(body_file).exists()
            snapshot = Path(body_file).read_bytes() if exists else None
            calls.append({"argv": list(argv), "cwd": cwd, "timeout": timeout, "body": snapshot})
            result = ten if "afk-driver" in argv else five
            if isinstance(result, BaseException):
                raise result
            return result(argv) if callable(result) else result

        self.monkeypatch.setattr(self.module, "_run_detector", fake)

    def argv(self, *extra: str, omit=()) -> list[str]:
        pairs = [
            ("--repo", self.repo),
            ("--issue", str(self.issue)),
            ("--checkout", str(self.checkout)),
            ("--scratch-root", str(self.scratch_root)),
            ("--out", str(self.out)),
            ("--spec", str(self.spec)),
            ("--afk-project", str(self.afk)),
            ("--comments-json", str(self.comments_json)),
        ]
        flat = ["build"]
        for flag, value in pairs:
            if flag not in omit:
                flat += [flag, value]
        return flat + list(extra)

    def build(self, *extra: str, omit=()) -> Result:
        code = self.module.main(self.argv(*extra, omit=omit))
        captured = self.capsys.readouterr()
        return Result(code, captured.out, captured.err, self.out)


@pytest.fixture(scope="module")
def shared_world(tmp_path_factory):
    return World(tmp_path_factory.mktemp("shared-world"))


@pytest.fixture
def git_env(monkeypatch):
    for key, value in GIT_ENV.items():
        monkeypatch.setenv(key, value)


@pytest.fixture
def env(tmp_path, monkeypatch, capsys, shared_world, git_env):
    return BuildEnv(tmp_path, shared_world, monkeypatch, capsys)


def spy_git(monkeypatch) -> list:
    """Wrap the real ``_run_git`` seam; return its ``(args, cwd, timeout)`` calls."""
    real = mod._run_git
    calls: list = []

    def spy(args, cwd=None, timeout=30):
        calls.append((list(args), cwd, timeout))
        return real(args, cwd, timeout)

    monkeypatch.setattr(mod, "_run_git", spy)
    return calls


FENCE_LINE = re.compile(r"^(`{3,})$", re.MULTILINE)


class Block:
    """A labelled fenced block of ``reader.md``: its head, content and fence."""

    def __init__(self, reader: str, label: str) -> None:
        start = reader.index(label)
        opening = FENCE_LINE.search(reader, start)
        assert opening, f"no fence after {label!r}"
        self.fence = opening.group(1)
        self.head = reader[start : opening.start()]
        body_start = opening.end() + 1
        close = reader.index("\n" + self.fence, body_start)
        self.content = reader[body_start:close]
        self.start = start
        self.end = close + 1 + len(self.fence)


def without_body(reader: str) -> str:
    block = Block(reader, "## Issue body")
    return reader[: block.start] + reader[block.end :]


def dispatch_block(reader: str) -> str:
    start = reader.index("## This dispatch")
    return reader[start : reader.index("\n## ", start + 1)]


def outside_code_fences(text: str) -> str:
    """*text* without any fenced code block (the ``` or longer fence lines included)."""
    kept: list[str] = []
    fence = None
    for line in text.split("\n"):
        if fence is None:
            opening = re.match(r"^(`{3,})", line)
            if opening:
                fence = opening.group(1)
            else:
                kept.append(line)
        elif line.startswith(fence) and not line.strip("`\r"):
            fence = None
    return "\n".join(kept)


def has_word(text: str, words=("gh", "curl")) -> bool:
    """Whether a whole word of *words* occurs in *text*; a word inside a path does not count."""
    pattern = r"(?<![\w/.\-])(?:" + "|".join(words) + r")(?![\w/.\-])"
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


# --------------------------------------------------------------------------- #
# module shape and the three seams
# --------------------------------------------------------------------------- #


def test_every_import_is_standard_library_or_a_sibling_engine_module():
    """Stdlib only, at any depth, plus the two engine modules the issue names:
    a lazy ``import yaml`` would break the script on the machine whose
    environment is the problem, and a hashing or verdict classifier of its own
    would drift from ``cold_read_stamp`` and ``cold_read_ledger``. This
    replaces #1181's all-stdlib test, which no faithful ``build`` can satisfy."""
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0 and node.module, ast.dump(node)
            imported.append(node.module)
    assert imported, "the script imports nothing, so this test would pass vacuously"
    roots = {name.split(".")[0] for name in imported}
    assert sorted(roots - set(sys.stdlib_module_names) - SIBLING_MODULES) == []
    assert SIBLING_MODULES <= roots, "the script must import both sibling modules"


def test_the_module_takes_the_hasher_and_the_verdict_title_from_the_siblings():
    """The body hash and the verdict predicate belong to ``cold_read_stamp`` and
    ``cold_read_ledger``; a local copy drifts (the one-off script's hash differed
    from the stamp's for a body ending in three newlines)."""
    assert mod.body_hash is cold_read_stamp.body_hash
    assert mod.VERDICT_TITLE == cold_read_ledger.VERDICT_TITLE


def test_the_three_seams_have_the_documented_signatures():
    """Tests (and the teeth spec) fake ``_run_gh``, ``_run_git`` and
    ``_run_detector`` by name and arity; ``_run_gh`` keeps the call shape of
    ``cold_read_stamp.py`` with its 30-second default."""
    gh = inspect.signature(mod._run_gh).parameters
    assert list(gh) == ["args", "timeout"] and gh["timeout"].default == 30
    assert list(inspect.signature(mod._run_git).parameters) == ["args", "cwd", "timeout"]
    assert list(inspect.signature(mod._run_detector).parameters) == ["argv", "cwd", "timeout"]


def test_run_detector_returns_exit_stdout_and_stderr_in_the_given_directory(tmp_path):
    """A non-zero exit is data, so the real runner reports it instead of raising,
    in the working directory it was given and decoding undecodable output."""
    program = "import os, sys; print(os.getcwd()); sys.stderr.write('err'); sys.exit(3)"
    code, out, err = mod._run_detector([sys.executable, "-c", program], str(tmp_path), 30)
    assert code == 3 and err == "err"
    assert Path(out.strip()).resolve() == tmp_path.resolve()
    raw = "import sys; sys.stdout.buffer.write(b'\\xff ok')"
    code, out, _ = mod._run_detector([sys.executable, "-c", raw], str(tmp_path), 30)
    assert code == 0 and "ok" in out and "�" in out


def test_run_detector_raises_for_a_program_that_cannot_start_or_outlives_its_timeout(tmp_path):
    """``build`` turns both into exit 4; the seam must raise them rather than
    return a made-up result, or a missing ``uv`` would read as a detector verdict."""
    with pytest.raises(OSError):
        mod._run_detector(["cold-read-dispatch-no-such-program-xyz"], str(tmp_path), 30)
    sleeper = [sys.executable, "-c", "import time; time.sleep(30)"]
    with pytest.raises(subprocess.TimeoutExpired):
        mod._run_detector(sleeper, str(tmp_path), 0.3)


def test_run_gh_and_run_git_report_a_program_that_cannot_run_as_none(tmp_path, monkeypatch):
    """The two seams that mirror ``cold_read_stamp.py`` return ``None`` for a
    program that cannot start (an absent ``gh``, an absent working directory)
    and a ``(code, stdout, stderr)`` tuple otherwise."""
    original_path = os.environ["PATH"]
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    stub_dir = tmp_path / "stub-bin"
    stub_dir.mkdir()
    stub = stub_dir / "gh"
    stub.write_text('#!/bin/sh\necho "$@"\nexit 3\n')
    stub.chmod(0o755)
    monkeypatch.setenv("PATH", str(empty))
    assert mod._run_gh(["api", "x"]) is None
    monkeypatch.setenv("PATH", str(stub_dir))
    assert mod._run_gh(["api", "x"]) == (3, "api x\n", "")
    monkeypatch.setenv("PATH", original_path)
    assert mod._run_git(["--version"], str(tmp_path / "absent")) is None
    code, out, _ = mod._run_git(["--version"], str(tmp_path))
    assert code == 0 and out.startswith("git version")


def test_run_gh_and_run_git_report_a_program_that_outlives_its_timeout_as_none(tmp_path, monkeypatch):
    """A ``gh`` or ``git`` that hangs is the same as one that cannot run: the
    seams return ``None`` (``build`` exits 4) rather than raising
    ``subprocess.TimeoutExpired`` or waiting the hang out."""
    stub_dir = tmp_path / "stub-bin"
    stub_dir.mkdir()
    for name in ("gh", "git"):
        stub = stub_dir / name
        stub.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(30)\n")
        stub.chmod(0o755)
    monkeypatch.setenv("PATH", str(stub_dir))
    assert mod._run_gh(["api", "x"], 0.3) is None
    assert mod._run_git(["status"], str(tmp_path), 0.3) is None


# --------------------------------------------------------------------------- #
# the body, its hash and --expect-body
# --------------------------------------------------------------------------- #


def test_the_body_hash_of_a_body_ending_in_three_newlines_is_the_stamp_hash(env):
    """The one-off assembler hashed the newline-normalised text, which differs
    from the canonical stamp hash of a body that ends in three newlines; the
    manifest carries the first 12 hex of ``cold_read_stamp.body_hash``."""
    body = "# Slice\n\nText.\n\n\n"
    env.set_body(body)
    result = env.build()
    assert result.code == 0, result.err
    expected = cold_read_stamp.body_hash(body)[:12]
    assert result.manifest["body_hash"] == expected
    normalised = hashlib.sha256((body.rstrip("\n") + "\n").encode("utf-8")).hexdigest()[:12]
    assert expected != normalised
    assert re.fullmatch(r"[0-9a-f]{12}", expected)


def test_the_shared_stamp_vector_gives_the_same_hash_through_the_script(env):
    """The vector carries CRLF, a lone CR, U+2028 and stamp lines, the cases on
    which two hashers disagree; the script must agree with the vector."""
    vector = json.loads(VECTOR.read_text(encoding="utf-8"))
    env.set_body(vector["body"])
    result = env.build()
    assert result.code == 0, result.err
    assert result.manifest["body_hash"] == vector["hash"][:12]


def test_expect_body_mismatch_exits_3_prints_both_values_and_creates_nothing(env):
    """A body that changed since the conductor recorded its hash must stop the
    build before anything is written, fetched or run; a build that skips the
    comparison dispatches a reader on a body nobody stamped."""
    env.set_body("The body as it is now.\n")
    actual = cold_read_stamp.body_hash("The body as it is now.\n")[:12]
    wrong = "0" * 12
    result = env.build("--expect-body", wrong)
    assert result.code == 3
    shown = result.out + result.err
    assert wrong in shown and actual in shown
    assert not env.out.exists(), "exit 3 created the output directory"
    assert list(env.scratch_root.iterdir()) == []
    assert env.detector_calls == []


@pytest.mark.parametrize("kind", ["prefix", "empty", "longer"])
def test_expect_body_that_is_a_prefix_an_empty_value_or_longer_is_a_mismatch(env, kind):
    """The comparison is equality of the 12-hex values: a proper prefix of the
    real hash, an empty value and the hash with extra characters all exit 3.
    A build that tests ``startswith`` or treats an empty value as not given
    dispatches on a body nobody verified."""
    env.set_body("The body as it is now.\n")
    actual = cold_read_stamp.body_hash("The body as it is now.\n")[:12]
    given = {"prefix": actual[:6], "empty": "", "longer": actual + "0"}[kind]
    result = env.build("--expect-body", given)
    assert result.code == 3
    assert actual in result.out + result.err
    assert not env.out.exists() and env.detector_calls == []


def test_expect_body_with_the_equal_value_builds(env):
    """The comparison is equality: the recorded value lets the build through."""
    env.set_body("The body as it is now.\n")
    actual = cold_read_stamp.body_hash("The body as it is now.\n")[:12]
    result = env.build("--expect-body", actual)
    assert result.code == 0, result.err
    assert result.manifest["body_hash"] == actual


@pytest.mark.parametrize(
    "body",
    [
        "Plain body.\n",
        "Line one\r\nLine two\r\n\r\n```\r\ncode\r\n```\r\n",
        "no trailing newline",
        "",
        "a\n\n\n",
        "Caf\u00e9 \u2014 na\u00efve \u4e2d\u6587 \u2713\n",
    ],
    ids=["lf", "crlf", "no-newline", "empty", "trailing-blank-lines", "unicode"],
)
def test_body_md_is_the_fetched_body_byte_for_byte(env, body):
    """Line endings are part of the body the reader reads and the detector
    hashes; a build that normalises CRLF, strips trailing newlines or writes in
    text mode changes it."""
    env.set_body(body)
    result = env.build()
    assert result.code == 0, result.err
    assert (env.out / "body.md").read_bytes() == body.encode("utf-8")


def test_gh_is_called_once_through_api_without_jq(env):
    """The body fetch has the call shape ``cold_read_stamp.py`` uses: ``gh api``
    on the issue and nothing else (no ``--jq``, which would hide the field)."""
    result = env.build()
    assert result.code == 0, result.err
    assert [args for args, _ in env.gh_calls] == [["api", f"repos/{env.repo}/issues/{env.issue}"]]
    assert [timeout for _, timeout in env.gh_calls] == [30]


@pytest.mark.parametrize(
    ("response", "message"),
    [
        ((1, "", "HTTP 404"), "failed (exit 1)"),
        ((1, json.dumps({"body": "A body that would build."}), "HTTP 500"), "failed (exit 1)"),
        (None, "could not be run"),
        ((0, "not json", ""), "returned invalid JSON"),
        ((0, '{"title": "no body"}', ""), "returned no 'body' field"),
    ],
    ids=["non-zero", "non-zero-with-valid-json", "cannot-run", "invalid-json", "no-body-field"],
)
def test_a_gh_failure_exits_4_and_says_which_failure_it_was(env, response, message):
    """A fetch that fails, cannot run or returns no ``body`` field must stop the
    build with exit 4 and no traceback, never build on an empty body. Each cause
    has its own message: a non-zero exit whose stdout happens to be valid JSON
    with a ``body`` is still a failed fetch (a build that ignores the exit code
    builds on it), and the exit-code message cannot be mistaken for the
    invalid-JSON one."""
    env.set_body("ignored", response=response)
    result = env.build()
    assert result.code == 4
    assert "gh api repos/octo/repo/issues/42" in result.err and message in result.err
    if message == "failed (exit 1)":
        assert "invalid JSON" not in result.err
    assert env.detector_calls == []
    assert not (env.out / "reader.md").exists()


# --------------------------------------------------------------------------- #
# the fork point
# --------------------------------------------------------------------------- #

FORK_CASES = [
    pytest.param("Target: afk/epic-7\nText.\n", TRUNK_AND_INTEGRATION, (), "afk/epic-7", "target-line", id="target-line-beats-every-setting"),
    pytest.param(f"{HAND_BUILT}\nTarget: afk/epic-7\n", TRUNK_AND_INTEGRATION, (), "afk/epic-7", "target-line", id="target-line-beats-the-hand-built-trunk"),
    pytest.param("Target:afk/epic-7\r\nText.\r\n", TRUNK_AND_INTEGRATION, (), "afk/epic-7", "target-line", id="target-line-without-a-space-with-crlf"),
    pytest.param("Target: afk/epic-12\n", TRUNK_AND_INTEGRATION, (), "afk/epic-12", "target-line", id="target-line-with-two-digits"),
    pytest.param("Target: afk/epic-7x\n", TRUNK_AND_INTEGRATION, (), "afk/staging", "integration_target", id="a-non-numeric-epic-suffix-is-prose"),
    pytest.param("Target: dev\n", TRUNK_AND_INTEGRATION, (), "afk/staging", "integration_target", id="a-target-line-must-name-an-epic-branch"),
    pytest.param(f"  {HAND_BUILT}\nText.\n", TRUNK_AND_INTEGRATION, (), "afk/staging", "integration_target", id="leading-spaces-before-the-hand-built-line-do-not-count"),
    pytest.param(f"{HAND_BUILT}\r\r\nText.\n", TRUNK_AND_INTEGRATION, (), "afk/staging", "integration_target", id="two-trailing-carriage-returns-are-not-one"),
    pytest.param(f"{HAND_BUILT}\n\nText.\n", TRUNK_AND_INTEGRATION, (), "dev", "trunk_branch", id="hand-built-uses-trunk-branch"),
    pytest.param(f"\n \n{HAND_BUILT}\nText.\n", TRUNK_AND_INTEGRATION, (), "dev", "trunk_branch", id="blank-lines-may-precede-the-hand-built-line"),
    pytest.param(f"{HAND_BUILT}\r\n\r\nText.\r\n", TRUNK_AND_INTEGRATION, (), "dev", "trunk_branch", id="crlf-hand-built-line"),
    pytest.param("Text.\n", TRUNK_AND_INTEGRATION, (), "afk/staging", "integration_target", id="no-hand-built-line-uses-integration-target"),
    pytest.param(f"Intro first.\n{HAND_BUILT}\n", TRUNK_AND_INTEGRATION, (), "afk/staging", "integration_target", id="the-hand-built-line-must-be-first"),
    pytest.param(f"{HAND_BUILT} \nText.\n", TRUNK_AND_INTEGRATION, (), "afk/staging", "integration_target", id="a-trailing-space-is-not-exactly-the-line"),
    pytest.param(f"{HAND_BUILT}\nText.\n", 'integration_target = "afk/staging"\n', (), "afk/staging", "integration_target", id="hand-built-without-trunk-branch-falls-through"),
    pytest.param(f"{HAND_BUILT}\nText.\n", 'trunk_branch = 5\nintegration_target = "afk/staging"\n', (), "afk/staging", "integration_target", id="a-non-string-trunk-branch-is-ignored"),
    pytest.param("see Target: afk/epic-7\n", TRUNK_AND_INTEGRATION, (), "afk/staging", "integration_target", id="a-mid-line-target-is-prose"),
    pytest.param("Target: afk/epic-7 and more\n", TRUNK_AND_INTEGRATION, (), "afk/staging", "integration_target", id="trailing-text-is-not-a-target-line"),
    pytest.param("Text.\n", None, (), "main", "default", id="no-settings-file-is-main"),
    pytest.param("Text.\n", 'integration_target = ""\n', (), "main", "default", id="an-empty-setting-is-unset"),
    pytest.param("Text.\n", TRUNK_AND_INTEGRATION, ("--fork-branch", "override-branch"), "override-branch", "override", id="fork-branch-wins"),
    pytest.param("Target: afk/epic-7\n", TRUNK_AND_INTEGRATION, ("--fork-branch", "override-branch"), "override-branch", "override", id="fork-branch-beats-the-target-line"),
]


@pytest.mark.parametrize(("body", "config", "extra", "branch", "source"), FORK_CASES)
def test_fork_branch_precedence(env, tmp_path, body, config, extra, branch, source):
    """The fork branch is the first rule that applies: ``--fork-branch``, a
    ``Target:`` line, ``trunk_branch`` for a body that opens with the hand-built
    line, ``integration_target``, then ``main``. Swapping ``trunk_branch`` and
    ``integration_target``, matching the hand-built line anywhere or with its
    ``\\r`` still on, or matching ``Target:`` mid-line, each resolves a branch
    this table does not expect."""
    env.checkout = clone_of(env.world, tmp_path / "checkout-with-settings", config)
    env.set_body(body)
    result = env.build(*extra)
    assert result.code == 0, result.err
    manifest = result.manifest
    assert (manifest["fork_branch"], manifest["fork_source"]) == (branch, source)
    assert manifest["fork_sha"] == env.world.tips[branch]


@pytest.mark.parametrize("with_config", [False, True], ids=["other-toml-only", "other-toml-beside-config"])
def test_settings_come_from_config_toml_and_no_other_file(env, tmp_path, with_config):
    """The settings file is ``.afk/config.toml``; the same keys in another file
    of that directory are ignored, including siblings whose names start with
    ``config`` and sort before it. A build that reads the first ``*.toml`` or
    the first ``config*.toml`` resolves ``dev`` here instead of ``main`` or
    ``afk/staging``."""
    checkout = clone_of(env.world, tmp_path / "checkout-with-settings", None)
    (checkout / ".afk").mkdir()
    for sibling in ("aaa-other.toml", "config-a.toml", "config.local.toml"):
        (checkout / ".afk" / sibling).write_text('integration_target = "dev"\n', encoding="utf-8")
    if with_config:
        (checkout / ".afk" / "config.toml").write_text('integration_target = "afk/staging"\n', encoding="utf-8")
    env.checkout = checkout
    result = env.build()
    assert result.code == 0, result.err
    expected = ("afk/staging", "integration_target") if with_config else ("main", "default")
    assert (result.manifest["fork_branch"], result.manifest["fork_source"]) == expected


def test_a_malformed_settings_file_exits_2_instead_of_guessing_a_branch(env, tmp_path):
    """Unreadable input is exit 2: a settings file that does not parse must not
    silently fall through to ``main`` and archive the wrong tree."""
    env.checkout = clone_of(env.world, tmp_path / "checkout-with-settings", "this is = = not toml\n")
    result = env.build()
    assert result.code == 2
    assert "config.toml" in result.err


def test_the_fork_sha_is_the_remotes_not_the_stale_tracking_ref(tmp_path, monkeypatch, capsys, git_env):
    """With a clone whose ``origin/dev`` is two commits stale, the SHA is the
    remote's tip and ``tree/`` holds the tip's files. A build that reads the
    remote-tracking ref archives the stale tree."""
    world = World(tmp_path / "private-world")
    stale = git_in(world.checkout, "rev-parse", "origin/dev")
    git_in(world.seed, "checkout", "-q", "dev")
    commit_file(world.seed, "newer.txt", "one\n", "newer one")
    tip = commit_file(world.seed, "newer.txt", "two\n", "newer two")
    git_in(world.seed, "push", "-q", "origin", "dev")
    assert git_in(world.checkout, "rev-parse", "origin/dev") == stale != tip
    build_env = BuildEnv(tmp_path, world, monkeypatch, capsys)
    result = build_env.build("--fork-branch", "dev")
    assert result.code == 0, result.err
    manifest = result.manifest
    assert manifest["fork_sha"] == tip
    assert (Path(manifest["tree_dir"]) / "newer.txt").read_text(encoding="utf-8") == "two\n"
    assert (Path(manifest["tree_dir"]) / "marker.txt").read_text(encoding="utf-8") == "dev\n"


def test_the_git_calls_are_ls_remote_then_fetch_then_archive_in_the_checkout(env):
    """The SHA comes from ``git ls-remote origin refs/heads/<branch>``, then the
    checkout fetches that branch, then ``git archive`` writes ``fork.tar`` in the
    scratch directory; all three run in the checkout, in this order."""
    calls = spy_git(env.monkeypatch)
    result = env.build("--fork-branch", "dev")
    assert result.code == 0, result.err
    manifest = result.manifest
    assert [args for args, _, _ in calls] == [
        ["ls-remote", "origin", "refs/heads/dev"],
        ["fetch", "origin", "dev"],
        ["archive", "--format=tar", "-o", f"{manifest['scratch_dir']}/fork.tar", manifest["fork_sha"]],
    ]
    assert {str(cwd) for _, cwd, _ in calls} == {str(env.checkout)}


def test_the_archived_tree_holds_the_forks_files(env):
    """``tree/`` is the extracted archive of the fork SHA, not of the checkout's
    own branch (the checkout is on ``main``)."""
    result = env.build("--fork-branch", "override-branch")
    assert result.code == 0, result.err
    tree = Path(result.manifest["tree_dir"])
    assert (tree / "marker.txt").read_text(encoding="utf-8") == "override-branch\n"
    assert (tree / "src" / "app.py").read_text(encoding="utf-8") == "print('app')\n"
    assert not (tree / ".git").exists(), "an archive has no .git"


def test_a_branch_that_is_not_on_origin_exits_4_before_any_fetch(env):
    """Empty ``ls-remote`` output is exit 4 and stops there. A build that goes on
    to ``git fetch`` and ``git archive`` with an empty SHA exits by accident (or
    with a traceback), and leaves a scratch directory behind."""
    calls = spy_git(env.monkeypatch)
    result = env.build("--fork-branch", "no-such-branch")
    assert result.code == 4
    assert "no-such-branch" in result.err
    assert [args[0] for args, _, _ in calls] == ["ls-remote"]
    assert list(env.scratch_root.iterdir()) == []
    assert env.detector_calls == []


def test_an_empty_origin_exits_4_without_a_traceback(env, tmp_path):
    """A repository with no commits has no fork point: exit 4, not an uncaught
    ``IndexError`` from a build that indexes the first ``ls-remote`` word."""
    empty_origin = tmp_path / "empty-origin.git"
    git_in(tmp_path, "init", "-q", "--bare", "-b", "main", str(empty_origin))
    empty_clone = tmp_path / "empty-clone"
    git_in(tmp_path, "clone", "-q", str(empty_origin), str(empty_clone))
    env.checkout = empty_clone
    result = env.build()
    assert result.code == 4
    assert "Traceback" not in result.err


def test_a_fork_whose_tree_is_empty_exits_4_without_a_traceback(tmp_path, monkeypatch, capsys, git_env):
    """A commit with the empty tree archives to a tar that ``tarfile`` rejects;
    the exit codes list no other outcome than 4 for an archive that cannot be
    used, so the build must not end in a traceback (exit 1)."""
    origin = tmp_path / "empty-tree-origin.git"
    seed = tmp_path / "empty-tree-seed"
    git_in(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    git_in(tmp_path, "init", "-q", "-b", "main", str(seed))
    git_in(seed, "remote", "add", "origin", str(origin))
    git_in(seed, "commit", "-q", "--allow-empty", "-m", "empty tree")
    git_in(seed, "push", "-q", "origin", "main")
    clone = tmp_path / "empty-tree-clone"
    git_in(tmp_path, "clone", "-q", str(origin), str(clone))
    build_env = BuildEnv(tmp_path, SimpleNamespace(checkout=clone, tips={}), monkeypatch, capsys)
    result = build_env.build()
    assert result.code == 4
    assert "cannot extract the archive of" in result.err
    assert "git archive of" not in result.err and "Traceback" not in result.err


def test_the_checkout_is_byte_identical_after_a_build(env, tmp_path):
    """The build may fetch into the checkout and nothing else: ``HEAD``, the
    index and every working-tree file are the same afterwards and
    ``git status --porcelain`` is empty."""
    checkout = clone_of(env.world, tmp_path / "watched-checkout")
    env.checkout = checkout

    def state():
        files = {
            path.relative_to(checkout).as_posix(): path.read_bytes()
            for path in sorted(checkout.rglob("*"))
            if path.is_file() and ".git" not in path.relative_to(checkout).parts
        }
        return {
            "head": git_in(checkout, "rev-parse", "HEAD"),
            "index": git_in(checkout, "ls-files", "-s"),
            "status": git_in(checkout, "status", "--porcelain"),
            "files": files,
        }

    before = state()
    assert before["status"] == ""
    result = env.build("--fork-branch", "dev")
    assert result.code == 0, result.err
    assert state() == before


def test_two_builds_with_the_same_arguments_get_two_scratch_directories(env):
    """A fixed scratch name made parallel readers collide and one ``rm -rf`` the
    other's tree; each build makes a new directory under ``--scratch-root``, with
    ``tree/`` inside it."""
    first = env.build().manifest
    second = env.build().manifest
    assert first["scratch_dir"] != second["scratch_dir"]
    for manifest in (first, second):
        scratch = Path(manifest["scratch_dir"])
        assert scratch.parent == env.scratch_root and scratch.name.startswith("cold-read-42-")
        assert Path(manifest["tree_dir"]) == scratch / "tree" and (scratch / "tree").is_dir()


def test_a_missing_scratch_root_exits_2_and_is_not_created(env, tmp_path):
    """The scratch root is the conductor's to provide: creating it, or letting
    ``mkdtemp`` raise, would hide a misconfigured path (exit 1 with a traceback)."""
    env.scratch_root = tmp_path / "no-such-root"
    result = env.build()
    assert result.code == 2
    assert "scratch-root" in result.err
    assert not env.scratch_root.exists()


def test_an_unreadable_spec_or_comments_file_is_a_usage_error(env, tmp_path):
    """Unreadable input is exit 2 with no traceback: a spec file or comments file
    that is not there, and a comments file that is not the ``gh`` JSON shape."""
    env.spec = tmp_path / "no-such-spec.md"
    assert env.build().code == 2
    env.spec = tmp_path / "spec.md"
    env.comments_json = tmp_path / "no-such-comments.json"
    assert env.build().code == 2
    env.comments_json.write_text("not json", encoding="utf-8")
    assert env.build().code == 2
    env.comments_json.write_text('{"title": "no comments key"}', encoding="utf-8")
    assert env.build().code == 2


@pytest.mark.parametrize("flag", ["--scratch-root", "--checkout"])
def test_a_regular_file_where_a_directory_is_expected_is_a_usage_error(env, tmp_path, flag):
    """``exists`` is not ``isdir``: a path that is a file passes an existence
    check and then ends in a ``NotADirectoryError`` traceback (exit 1) instead of
    exit 2 naming the option."""
    plain = tmp_path / "plain-file"
    plain.write_text("not a directory\n", encoding="utf-8")
    if flag == "--scratch-root":
        env.scratch_root = plain
    else:
        env.checkout = plain
    calls = spy_git(env.monkeypatch)
    result = env.build()
    assert result.code == 2 and flag in result.err
    assert calls == [] and env.detector_calls == []


REQUIRED_OPTIONS = (
    "--repo", "--issue", "--checkout", "--scratch-root", "--out", "--spec", "--afk-project", "--comments-json",
)


@pytest.mark.parametrize("flag", REQUIRED_OPTIONS)
def test_each_required_option_omitted_is_the_parsers_exit_2_naming_only_it(env, flag):
    """Every option of ``build`` but the optional ones is required: omitting one
    is the parser's ``SystemExit(2)`` with nothing on stdout and a "required"
    line that names that option and no other. The usage synopsis lists every
    flag, so a bare "flag in stderr" check cannot tell a required option from an
    optional one; an option made optional dies later with a ``TypeError`` (exit
    1) or is accepted."""
    with pytest.raises(SystemExit) as raised:
        env.module.main(env.argv(omit=(flag,)))
    assert raised.value.code == 2
    captured = env.capsys.readouterr()
    assert captured.out == ""
    required = re.search(r"the following arguments are required: (.+)", captured.err)
    assert required and required.group(1).strip() == flag
    assert env.gh_calls == [] and env.detector_calls == []


# --------------------------------------------------------------------------- #
# comments
# --------------------------------------------------------------------------- #

VERDICT_COMMENTS = [
    {"author": {"login": "bot"}, "createdAt": "2026-10-10T10:00:00Z", "body": "## Cold read — REWRITE\nfinding one"},
    {"author": {"login": "bot"}, "createdAt": "2026-10-10T11:00:00Z", "body": "## Cold read — REWRITE\nfinding two"},
    {"author": {"login": "bot"}, "createdAt": "2026-10-10T12:00:00Z", "body": "  \n\t## Cold read — BUILD\nleading whitespace verdict"},
    {"author": {"login": "bot"}, "createdAt": "2026-10-10T13:00:00Z", "body": "\u00a0## Cold read — REWRITE\nno-break space verdict"},
    {"author": {"login": "bot"}, "createdAt": "2026-10-10T14:00:00Z", "body": "\u2003## Cold read — BUILD\nem space verdict"},
    {"author": {"login": "bot"}, "createdAt": "2026-10-10T15:00:00Z", "body": "\x0b## Cold read — REWRITE\nvertical tab verdict"},
    {"author": {"login": "bot"}, "createdAt": "2026-10-10T16:00:00Z", "body": "\x0c## Cold read — REWRITE\nform feed verdict"},
]
HUMAN_COMMENTS = [
    {"author": {"login": "charles"}, "createdAt": "2026-10-11T09:30:00Z", "body": "A human decision: keep the table.\nSecond line."},
    {"author": {"login": "dana"}, "createdAt": "2026-10-11T10:00:00Z", "body": "Mentions ## Cold read only mid-sentence."},
]


def test_verdict_comments_are_dropped_and_the_rest_keep_their_attribution(env):
    """The reader must never see earlier verdicts (one fetched them and saw 6,000
    characters of read 1). The filter agrees with the ledger's own predicate on
    every comment, leading whitespace included."""
    comments = VERDICT_COMMENTS[:2] + [HUMAN_COMMENTS[0]] + VERDICT_COMMENTS[2:] + [HUMAN_COMMENTS[1]]
    env.write_comments(comments)
    result = env.build()
    assert result.code == 0, result.err
    text = (env.out / "comments.md").read_text(encoding="utf-8")
    for comment in comments:
        kept = comment["body"] in text
        assert kept == (not cold_read_ledger._is_verdict_comment(comment["body"])), comment
    assert "### Comment by charles at 2026-10-11T09:30:00Z\n" in text
    assert "### Comment by dana at 2026-10-11T10:00:00Z\n" in text
    assert "finding one" not in text and "leading whitespace verdict" not in text
    assert all(cold_read_ledger._is_verdict_comment(c["body"]) for c in VERDICT_COMMENTS)
    for token in ("no-break space verdict", "em space verdict", "vertical tab verdict", "form feed verdict"):
        assert token not in text, token


def test_only_verdict_comments_leave_the_no_comments_line(env):
    """With nothing but verdicts, the file says so instead of being empty."""
    env.write_comments(VERDICT_COMMENTS)
    result = env.build()
    assert result.code == 0, result.err
    assert (env.out / "comments.md").read_text(encoding="utf-8") == (
        "No comments other than cold-read verdicts.\n"
    )


def test_the_verdict_prefix_is_the_modules_verdict_title(env, monkeypatch):
    """The filter reads ``VERDICT_TITLE`` rather than a literal ``## Cold read``:
    with another prefix set, that prefix is dropped and ``## Cold read`` kept."""
    monkeypatch.setattr(mod, "VERDICT_TITLE", "## Review note")
    env.write_comments(
        [
            {"author": {"login": "a"}, "createdAt": "t1", "body": "## Review note\ndropped"},
            {"author": {"login": "b"}, "createdAt": "t2", "body": "## Cold read — BUILD\nkept"},
        ]
    )
    result = env.build()
    assert result.code == 0, result.err
    text = (env.out / "comments.md").read_text(encoding="utf-8")
    assert "dropped" not in text and "kept" in text


def test_malformed_comment_entries_do_not_crash_the_build(env):
    """A comments file is another tool's output: entries that are not objects, a
    body that is not a string and a missing author must not raise."""
    env.write_comments([None, "text", {"body": 5}, {"body": "ok", "author": "no-login"}, {"body": "fine"}])
    result = env.build()
    assert result.code == 0, result.err
    text = (env.out / "comments.md").read_text(encoding="utf-8")
    assert "ok" in text and "fine" in text and "unknown" in text


# --------------------------------------------------------------------------- #
# the detectors
# --------------------------------------------------------------------------- #


def test_detector_5_argv_and_detector_10_call_follow_the_issue(env):
    """Detector 5 passes the body file, the real checkout path and the pinned
    graphmark range, and ends ``--json --ref <fork sha>``; detector 10 runs in the
    afk project. Both run once each, 600 seconds each. A command that drops
    ``--body-file``, passes the display ``<checkout>`` as ``--repo-dir``, or runs
    detector 10 without its working directory is wrong here."""
    result = env.build()
    assert result.code == 0, result.err
    five, ten = env.detector_calls
    sha = result.manifest["fork_sha"]
    argv = five["argv"]
    engine = str(mod.SCRIPTS_DIR)
    assert argv[:8] == [
        "uv", "run", "--with", "graphmark>=0.11,<0.12", "--with", "pyyaml", "python",
        f"{engine}/cold_read_evidence.py",
    ]
    assert argv[argv.index("--repo") + 1] == env.repo
    assert argv[argv.index("--repo-dir") + 1] == str(env.checkout)
    assert argv[argv.index("--body-file") + 1] == str(env.out / "body.md")
    assert argv[-3:] == ["--json", "--ref", sha]
    assert "--vault-root" not in argv
    assert ten["argv"] == [
        "uv", "run", "afk-driver", "--project", str(env.afk), "--repo", env.repo,
        "--deny-surface-check", str(env.issue), "--json",
    ]
    assert str(ten["cwd"]) == str(env.afk)
    assert five["timeout"] == 600 and ten["timeout"] == 600
    assert five["body"] == b"Plain body.\n", "body.md was not written before detector 5 ran"


def test_detector_5_ref_override_replaces_the_fork_sha_in_its_argv(env):
    """``--detector5-ref`` is the ref detector 5 runs against; the archive is
    still the fork SHA's."""
    result = env.build("--detector5-ref", "abc1234")
    assert result.code == 0, result.err
    assert env.detector_calls[0]["argv"][-3:] == ["--json", "--ref", "abc1234"]
    assert result.manifest["fork_sha"] == env.world.tips["main"]
    assert env.world.tips["main"] in dispatch_block(result.reader)


def test_a_non_zero_detector_exit_is_recorded_as_data(env):
    """Detector 5 exits 1 when it finds CHECK rows and detector 10 exits 1 on a
    match; both are findings for the reader, not build failures."""
    env.fake_detectors(five=(1, '{"rows": [1]}\n', "warn"), ten=(2, "", ""))
    result = env.build()
    assert result.code == 0, result.err
    manifest = result.manifest
    assert (manifest["detector5"]["exit"], manifest["detector10"]["exit"]) == (1, 2)
    assert (env.out / "detector5.json").read_text(encoding="utf-8") == '{"rows": [1]}\n'
    assert (env.out / "detector10.json").read_text(encoding="utf-8") == ""


@pytest.mark.parametrize(
    ("which", "failure", "needle"),
    [
        ("five", OSError("uv: not found"), "cold_read_evidence.py"),
        ("ten", OSError("uv: not found"), "afk-driver"),
        ("five", subprocess.TimeoutExpired("uv", 600), "cold_read_evidence.py"),
        ("ten", subprocess.TimeoutExpired("uv", 600), "afk-driver"),
    ],
    ids=["five-cannot-start", "ten-cannot-start", "five-times-out", "ten-times-out"],
)
def test_a_detector_that_cannot_start_or_times_out_exits_4_naming_its_command(env, which, failure, needle):
    """A detector that cannot run is not a verdict: exit 4, and the stderr line
    names the command so the conductor can run it by hand."""
    env.fake_detectors(**{which: failure})
    result = env.build()
    assert result.code == 4
    assert needle in result.err and "Traceback" not in result.err
    assert not (env.out / "reader.md").exists()


def test_the_real_runner_times_out_at_the_modules_detector_timeout(env, tmp_path, monkeypatch):
    """End to end through the real ``_run_detector``: a stub ``uv`` that outlives
    the timeout ends the build with exit 4 naming the command."""
    stub_dir = tmp_path / "stub-bin"
    stub_dir.mkdir()
    stub = stub_dir / "uv"
    stub.write_text("#!/bin/sh\nexec sleep 30\n")
    stub.chmod(0o755)
    monkeypatch.setenv("PATH", str(stub_dir) + os.pathsep + os.environ["PATH"])
    monkeypatch.setattr(mod, "_run_detector", REAL_RUN_DETECTOR)
    monkeypatch.setattr(mod, "DETECTOR_TIMEOUT", 1)
    result = env.build()
    assert result.code == 4
    assert "cold_read_evidence.py" in result.err


def test_build_runs_exactly_two_detectors_and_never_the_preflight(env, monkeypatch):
    """The preflight is the reader's first command, not the build's: no seam call
    mentions it, and neither ``_run_tool`` nor ``_roundtrip_sentinel`` (the
    preflight's seams) is called. Detector 5 runs before detector 10, and
    only those two run."""

    def forbidden(*args, **kwargs):
        raise AssertionError("build called a preflight seam")

    monkeypatch.setattr(mod, "_run_tool", forbidden)
    monkeypatch.setattr(mod, "_roundtrip_sentinel", forbidden)
    git_calls = spy_git(monkeypatch)
    result = env.build()
    assert result.code == 0, result.err
    assert len(env.detector_calls) == 2
    assert "cold_read_evidence.py" in " ".join(env.detector_calls[0]["argv"])
    assert "afk-driver" in env.detector_calls[1]["argv"]
    seen = [call["argv"] for call in env.detector_calls] + [args for args, _, _ in git_calls]
    seen += [args for args, _ in env.gh_calls]
    assert not any("preflight" in word for argv in seen for word in argv)


def test_detector_stdout_with_the_checkout_path_is_rewritten_everywhere(env):
    """The reader's prompt never names the live checkout: a detector that echoes
    the ``--repo-dir`` it ran with leaves ``<checkout>`` in
    ``detector5.json`` and in ``reader.md``, with the recorded exit unchanged."""
    env.fake_detectors(
        five=lambda argv: (1, json.dumps({"repo_dir": argv[argv.index("--repo-dir") + 1]}) + "\n", "")
    )
    result = env.build()
    assert result.code == 0, result.err
    live = str(env.checkout)
    written = (env.out / "detector5.json").read_text(encoding="utf-8")
    assert live not in written and written == '{"repo_dir": "<checkout>"}\n'
    assert live not in result.reader
    assert result.manifest["detector5"]["exit"] == 1


def test_every_occurrence_of_the_checkout_path_is_hidden_not_only_the_first(env, tmp_path):
    """The command and the detector's stdout can each hold the path several
    times (``--repo-dir``, ``--vault-root`` and ``--body-file`` under it; three
    echoes in the output); a build that replaces only the first occurrence
    leaves the rest in the manifest, the evidence file and the prompt."""
    clone = clone_of(env.world, tmp_path / "multi-checkout")
    vault = clone / "vault"
    vault.mkdir()
    env.checkout = clone
    env.out = clone / "dispatch-out"
    env.set_body("See [[Some Note]].\n")
    live = str(clone)
    env.fake_detectors(
        five=(0, json.dumps({"a": live, "b": live + "/x", "c": live + "/y"}) + "\n", "")
    )
    result = env.build("--vault-root", str(vault))
    assert result.code == 0, result.err
    command = result.manifest["detector5"]["command"]
    assert live not in command and command.count("<checkout>") == 3
    written = (env.out / "detector5.json").read_text(encoding="utf-8")
    assert live not in written and written.count("<checkout>") == 3
    shown = Block(result.reader, "## Detector 5 command and output")
    assert live not in shown.head and live not in shown.content
    assert shown.head.count("<checkout>") == 3 and shown.content.count("<checkout>") == 3


def test_a_checkout_path_with_a_trailing_slash_is_still_hidden(env):
    """The evidence script echoes ``str(Path(repo_dir))``, which drops a trailing
    slash; replacing only the argument exactly as given leaves the live path in
    the output."""
    env.checkout = str(env.checkout) + "/"
    env.fake_detectors(five=lambda argv: (0, json.dumps({"seen": str(env.world.checkout)}) + "\n", ""))
    result = env.build()
    assert result.code == 0, result.err
    live = str(env.world.checkout)
    assert live not in (env.out / "detector5.json").read_text(encoding="utf-8")
    assert live not in without_body(result.reader)


# --------------------------------------------------------------------------- #
# reader.md
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "body",
    [
        "Plain body.\n",
        "Line\n`````\nfive backticks above\n",
        "CRLF one\r\n````\r\nfour above\r\n",
        "no trailing newline",
        "",
        "``` three at a line start\nand a mid-line run `````` of six\n",
    ],
    ids=["plain", "five-backticks", "crlf-four-backticks", "no-newline", "empty", "mid-line-run-of-six"],
)
def test_the_body_sits_byte_for_byte_inside_a_fence_one_backtick_longer(env, body):
    """A body quoting a code fence must not close the prompt's own: the fence is
    one backtick longer than the longest run in the body (four at least), and
    the body inside it is unmodified, line endings included."""
    env.set_body(body)
    result = env.build()
    assert result.code == 0, result.err
    block = Block(result.reader, "## Issue body")
    longest = max((len(run) for run in re.findall(r"`+", body)), default=0)
    assert len(block.fence) == max(4, longest + 1)
    assert block.content == body
    assert re.search(r"^Body hash: ([0-9a-f]+)$", block.head, re.MULTILINE).group(1) == result.manifest["body_hash"]


def test_reader_md_has_the_nine_sections_of_the_repository_spec_in_file_order(env, tmp_path):
    """Built from this repository's own ``command.md`` (once #1177 has landed it
    carries the ``What the reader is given.`` bullet): exit 0, the contract check
    passes, the nine sections appear verbatim in file order after the expansion,
    and no placeholder survives outside a code fence except
    ``<absolute vault path>`` when no ``--vault-root`` was given."""
    spec = COMMAND_MD.read_text(encoding="utf-8")
    env.spec = COMMAND_MD
    result = env.build()
    assert result.code == 0, result.err
    manifest = result.manifest
    tokens = {
        "<engine>": str(mod.SCRIPTS_DIR),
        "<path-to-afk-agent-system>": str(env.afk),
        "<local checkout>": manifest["tree_dir"],
        "<fork point SHA>": manifest["fork_sha"],
    }
    headings = [(m.start(), m.group(1)) for m in re.finditer(r"^## (.*?)[ \t]*$", spec, flags=re.MULTILINE)]
    in_file_order = [name for _, name in headings if name in READER_GIVEN]
    assert sorted(in_file_order) == sorted(READER_GIVEN)
    assert manifest["spec_sections"] == in_file_order
    reader = result.reader
    last = -1
    for index, (start, name) in enumerate(headings):
        if name not in READER_GIVEN:
            continue
        end = headings[index + 1][0] if index + 1 < len(headings) else len(spec)
        expected = spec[start:end].rstrip("\n")
        for token, value in tokens.items():
            expected = expected.replace(token, value)
        position = reader.find(expected)
        assert position > last, f"section {name!r} is missing or out of file order"
        assert f"\n## {name}\n" in reader, f"the heading of {name!r} does not start a line"
        last = position
    outside = outside_code_fences(reader)
    for token in tokens:
        assert token not in outside, f"{token} survives in reader.md"
    assert "<absolute vault path>" in outside


def test_reader_md_built_from_the_repository_spec_expands_the_vault_path_when_given(env, tmp_path):
    """``<absolute vault path>`` becomes ``--vault-root`` when that flag is given
    and is otherwise left as written; a build that never expands it, or that
    expands it for everything, leaves the wrong text in the prompt."""
    vault = tmp_path / "the-vault"
    vault.mkdir()
    env.spec = COMMAND_MD
    result = env.build("--vault-root", str(vault))
    assert result.code == 0, result.err
    outside = outside_code_fences(result.reader)
    assert "<absolute vault path>" not in outside
    assert f"--vault-root {vault}" in outside


def test_placeholders_in_the_spec_text_expand_to_their_values(env, tmp_path):
    """Each placeholder becomes the value the issue names, not just something
    other than itself: ``<engine>`` this script's directory,
    ``<path-to-afk-agent-system>`` ``--afk-project``, ``<local checkout>`` the
    tree directory (never the live checkout), ``<fork point SHA>`` the ref detector
    5 ran against, ``<absolute vault path>`` ``--vault-root`` when given."""
    result = env.build()
    assert result.code == 0, result.err
    lines = result.reader.split("\n")
    manifest = result.manifest
    for line in (
        f"ENGINE={mod.SCRIPTS_DIR}",
        f"AFK={env.afk}",
        f"TREE={manifest['tree_dir']}",
        f"REF={manifest['fork_sha']}",
        "VAULT=<absolute vault path>",
    ):
        assert line in lines, line
    assert f"Probe builds text, with the ref {manifest['fork_sha']}." in result.reader
    assert str(env.checkout) not in without_body(result.reader)
    vault = tmp_path / "the-vault"
    vault.mkdir()
    again = env.build("--vault-root", str(vault), "--detector5-ref", "abc1234")
    assert again.code == 0, again.err
    lines = again.reader.split("\n")
    assert f"VAULT={vault}" in lines and "REF=abc1234" in lines
    assert f"AFK={env.afk}" in lines


def test_a_code_fenced_heading_does_not_end_a_section(env):
    """A ``## `` line inside a code fence is text, not a heading: the section
    keeps everything up to the next real heading."""
    result = env.build()
    assert result.code == 0, result.err
    assert (
        "```text\n## Not a heading: it sits inside a code fence\n```\n\n"
        "Text after the fence belongs to the same section."
    ) in result.reader
    assert result.manifest["spec_sections"] == list(DEFAULT_GIVEN)


def test_spec_sections_are_the_names_the_bullet_lists_in_file_order(env):
    """The section list is parsed from the ``What the reader is given.`` bullet,
    never hardcoded, and the sections follow the file's order, not the bullet's.
    A build that carries the repository's nine names fails on a two-name spec."""
    env.spec.write_text(spec_text(given=("Detectors", "Probe builds")), encoding="utf-8")
    result = env.build()
    assert result.code == 0, result.err
    assert result.manifest["spec_sections"] == ["Probe builds", "Detectors"]
    reader = result.reader
    assert reader.index("## Probe builds") < reader.index("## Detectors")
    assert "## Reader contract" not in reader and "## Procedure" not in reader
    assert "Intro, never given" not in reader


def test_a_named_section_missing_from_the_spec_exits_4_naming_it(env):
    """A missing section would hand the reader a prompt with no procedure; it is
    exit 4 and the message names the section."""
    env.spec.write_text(spec_text(omit=("Detectors",)), encoding="utf-8")
    result = env.build()
    assert result.code == 4
    assert "Detectors" in result.err
    assert not (env.out / "reader.md").exists()


@pytest.mark.parametrize(
    "text",
    [spec_text(bullet=False), spec_text(given=())],
    ids=["no-bullet", "bullet-without-backticked-names"],
)
def test_a_spec_with_no_what_the_reader_is_given_names_exits_4_naming_the_bullet(env, text):
    """A spec that names no section to carry is not an empty prompt: exit 4,
    naming the bullet."""
    env.spec.write_text(text, encoding="utf-8")
    result = env.build()
    assert result.code == 4
    assert "What the reader is given." in result.err
    assert not (env.out / "reader.md").exists()


def test_the_dispatch_block_names_every_path_and_the_preflight_command(env):
    """The reader's prompt carries the scratch and tree directories, this
    script's directory, the ``teeth_check.py`` path, the comments file, the
    fork SHA, the ``TEETH_CHECK_STATE_DIR`` line and the preflight command
    (equal to the manifest's, with ``<engine>`` and ``<scratch_dir>``
    expanded). Each omission leaves the reader a path it must invent."""
    result = env.build()
    assert result.code == 0, result.err
    manifest, reader = result.manifest, result.reader
    lines = reader.split("\n")
    assert lines[0] == f"# Cold read of {env.repo}#{env.issue}" and lines[2] == "## This dispatch"
    block = dispatch_block(reader)
    engine = str(mod.SCRIPTS_DIR)
    teeth = os.path.normpath(
        os.path.join(engine, "..", "..", "skills", "detector-teeth-check", "scripts", "teeth_check.py")
    )
    for expected in (
        manifest["scratch_dir"],
        manifest["tree_dir"],
        engine,
        teeth,
        manifest["comments_file"],
        manifest["fork_sha"],
    ):
        assert expected in block, expected
    assert manifest["preflight_command"] == (
        f'python3 "{engine}/cold_read_dispatch.py" preflight --scratch {manifest["scratch_dir"]}'
    )
    assert manifest["preflight_command"] in block
    block_lines = block.split("\n")
    assert f"TEETH_CHECK_STATE_DIR={manifest['scratch_dir']}/teeth-state" in block_lines
    for line in (
        f"- Repository: {env.repo}",
        f"- Issue: #{env.issue}",
        f"- Fork point: {manifest['fork_branch']} at {manifest['fork_sha']}",
        f"- Scratch directory: {manifest['scratch_dir']}",
        f"- Tree directory: {manifest['tree_dir']}",
        f"- Engine directory: {engine}",
        f"- teeth_check.py: {teeth}",
        f"- Comments file: {manifest['comments_file']}",
        f"- Preflight command: {manifest['preflight_command']}",
    ):
        assert line in block_lines, line


def test_each_detector_block_repeats_its_command_exit_and_stdout(env):
    """One labelled block per detector: its command (the manifest's, with the
    checkout path written ``<checkout>``), its recorded exit code and its
    stdout, byte-equal to ``detector5.json`` or ``detector10.json``. The command
    the build ran keeps the real path."""
    env.fake_detectors(five=(1, '{"rows": ["a", "b"]}\n```\nfence in output\n', ""), ten=(0, "", ""))
    result = env.build()
    assert result.code == 0, result.err
    manifest = result.manifest
    for number in (5, 10):
        block = Block(result.reader, f"## Detector {number} command and output")
        entry = manifest[f"detector{number}"]
        assert re.search(r"^Command: (.*)$", block.head, re.MULTILINE).group(1) == entry["command"]
        assert re.search(r"^Exit code: (\d+)$", block.head, re.MULTILINE).group(1) == str(entry["exit"])
        written = Path(entry["file"]).read_text(encoding="utf-8")
        assert block.content == written
        assert Path(entry["file"]) == env.out / f"detector{number}.json"
    real = shlex.join(env.detector_calls[0]["argv"])
    assert manifest["detector5"]["command"] == real.replace(str(env.checkout), "<checkout>")
    assert "<checkout>" in manifest["detector5"]["command"]
    assert str(env.checkout) in real and str(env.checkout) not in manifest["detector5"]["command"]


def test_the_comments_block_equals_comments_md(env):
    """The reader sees the comments file's content in a labelled block, byte for
    byte."""
    env.write_comments(HUMAN_COMMENTS)
    result = env.build()
    assert result.code == 0, result.err
    block = Block(result.reader, "## Comments")
    assert block.content == (env.out / "comments.md").read_text(encoding="utf-8")
    assert result.manifest["comments_file"] == str(env.out / "comments.md")


def test_the_title_and_dispatch_block_name_neither_gh_nor_curl(env):
    """The reader is told not to run ``gh`` by the spec's ``Reader contract``;
    the dispatch must not hand it a ``gh`` command of its own (a
    ``gh api .../comments`` line in the block) or a ``curl`` fallback."""
    result = env.build()
    assert result.code == 0, result.err
    reader = result.reader
    assert not has_word(reader.split("\n", 1)[0])
    assert not has_word(dispatch_block(reader))


def test_the_build_writes_no_contract_prose_of_its_own(env):
    """The ``gh`` ban, the tool fence, the preflight instruction and the ``CHECK``
    handling live in the spec's sections; the build writes none of them. A spec
    without them yields a prompt with none of their vocabulary outside the
    fenced blocks."""
    result = env.build()
    assert result.code == 0, result.err
    outside = outside_code_fences(result.reader)
    for word in ("gh", "curl", "Monitor", "CHECK", "network"):
        assert not has_word(outside, (word,)), word


# --------------------------------------------------------------------------- #
# the contract check
# --------------------------------------------------------------------------- #

CONTRACT_CASES = [
    ("--comments", "--comments"),
    ("--COMMENTS", "--comments"),
    ("step 2 fetches them", "step 2"),
    ("Step 2 fetches them", "step 2"),
    ("STEP 2", "step 2"),
    ("read-only", "read-only"),
    ("Read-only", "read-only"),
    ("READ-ONLY", "read-only"),
]


@pytest.mark.parametrize(("planted", "needle"), CONTRACT_CASES, ids=[c[0] for c in CONTRACT_CASES])
def test_a_conductor_only_string_in_a_given_section_exits_5_naming_it(env, planted, needle):
    """A leftover ``step 2 fetches them`` hands the reader a command it must not
    run. Each of the three strings is checked, in any case, and the build writes
    no ``reader.md``. A check that tests only one needle, or only the lowercase
    spelling, passes the others."""
    env.spec.write_text(spec_text(detectors_extra=f"\n{planted}\n"), encoding="utf-8")
    result = env.build()
    assert result.code == 5
    assert needle in result.err
    assert not (env.out / "reader.md").exists()


DISPATCH_CASES = [
    ("--comments", "--comments"),
    ("--COMMENTS", "--comments"),
    ("step 2", "step 2"),
    ("Step 2", "step 2"),
    ("read-only", "read-only"),
    ("READ-ONLY", "read-only"),
]


@pytest.mark.parametrize(("planted", "needle"), DISPATCH_CASES, ids=[c[0] for c in DISPATCH_CASES])
def test_a_conductor_only_string_in_the_dispatch_block_exits_5(env, tmp_path, planted, needle):
    """The check covers the dispatch block as well as the spec text, in any case:
    a path the block prints (here the comments file under ``--out``) that holds
    the string is as much a leak as the spec's own. A check that lowers only the
    spec text passes the mixed-case paths."""
    env.out = tmp_path / planted / "out"
    result = env.build()
    assert result.code == 5
    assert needle in result.err
    assert not (env.out / "reader.md").exists()


@pytest.mark.parametrize("section", list(DEFAULT_GIVEN))
def test_a_conductor_only_string_in_any_given_section_exits_5(env, section):
    """The scan covers every section the reader is given, not the middle one: a
    scan that skips the first or the last given section passes a needle planted
    there."""
    planted = "\nstep 2 fetches them\n"
    changed = {
        "Probe builds": {"probe_text": PROBE_TEXT + planted},
        "Detectors": {"detectors_extra": planted},
        "Reader contract": {"contract_extra": planted},
    }[section]
    env.spec.write_text(spec_text(**changed), encoding="utf-8")
    result = env.build()
    assert result.code == 5
    assert "step 2" in result.err
    assert not (env.out / "reader.md").exists()


def test_the_same_strings_in_the_body_the_detectors_and_the_comments_do_not_fail_the_check(env):
    """Only the spec-derived text and the dispatch block are scanned. The issue
    body may quote ``step 2 fetches them`` (it is the data under read), and
    detector output and human comments are data too."""
    text = "see (step 2 fetches them), --comments and read-only"
    env.set_body(f"Body quoting {text}\n")
    env.fake_detectors(five=(0, f'{{"note": "{text}"}}\n', ""))
    env.write_comments([{"author": {"login": "x"}, "createdAt": "t", "body": text}])
    result = env.build()
    assert result.code == 0, result.err
    assert text in result.reader and "Traceback" not in result.err


def test_a_failed_build_leaves_no_reader_or_manifest_from_an_earlier_one(env):
    """Step 1 removes any ``reader.md`` and ``manifest.json`` already in ``--out``
    before anything can fail, so a build that exits 5 (or 4) never leaves the
    previous build's prompt looking current."""
    first = env.build()
    assert first.code == 0, first.err
    assert (env.out / "reader.md").exists() and (env.out / "manifest.json").exists()
    env.spec.write_text(spec_text(detectors_extra="\nstep 2 fetches them\n"), encoding="utf-8")
    assert env.build().code == 5
    assert not (env.out / "reader.md").exists() and not (env.out / "manifest.json").exists()
    assert (env.out / "body.md").exists()
    env.spec.write_text(spec_text(), encoding="utf-8")
    assert env.build().code == 0
    assert (env.out / "reader.md").exists() and (env.out / "manifest.json").exists()
    env.spec.write_text(spec_text(omit=("Detectors",)), encoding="utf-8")
    assert env.build().code == 4
    assert not (env.out / "reader.md").exists() and not (env.out / "manifest.json").exists()


# --------------------------------------------------------------------------- #
# the manifest and what is printed
# --------------------------------------------------------------------------- #

MANIFEST_KEYS = {
    "subagent_type", "model", "prompt_file", "body_hash", "fork_branch", "fork_source",
    "fork_sha", "scratch_dir", "tree_dir", "detector5", "detector10", "comments_file",
    "preflight_command", "spec_sections",
}


def test_the_manifest_has_exactly_the_documented_keys_and_an_existing_prompt(env):
    """A key more or fewer is a contract the dispatch tooling does not know;
    ``prompt_file`` names the ``reader.md`` that was written."""
    result = env.build()
    assert result.code == 0, result.err
    manifest = result.manifest
    assert set(manifest) == MANIFEST_KEYS
    assert Path(manifest["prompt_file"]) == env.out / "reader.md" and Path(manifest["prompt_file"]).is_file()
    for number in (5, 10):
        assert set(manifest[f"detector{number}"]) == {"command", "exit", "file"}
        assert isinstance(manifest[f"detector{number}"]["exit"], int)
    assert re.fullmatch(r"[0-9a-f]{40}", manifest["fork_sha"])
    assert manifest["fork_sha"] == env.world.tips["main"]
    assert (manifest["fork_branch"], manifest["fork_source"]) == ("main", "default")


def test_the_manifest_agent_type_and_model_are_the_ones_the_spec_names(env):
    """``Explore``'s role prompt forbids creating files, and one of six readers
    obeyed it. The manifest carries the type and the model the spec's ``Agent.``
    bullet names (``general-purpose`` and ``sonnet``), read from the spec rather
    than copied here, and never names ``Explore``."""
    spec = COMMAND_MD.read_text(encoding="utf-8")
    agent = next(line for line in spec.splitlines() if line.startswith("- **Agent.**"))
    agent_type = re.search(r"runs as a `([^`]+)` subagent", agent).group(1)
    model = re.search(r"\(`([^`]+)` or stronger\)", agent).group(1)
    assert (agent_type, model) == ("general-purpose", "sonnet")
    result = env.build()
    assert result.code == 0, result.err
    assert result.manifest["subagent_type"] == agent_type
    assert result.manifest["model"] == model
    assert "Explore" not in json.dumps(result.manifest)


def test_without_json_three_lines_are_printed(env):
    """The conductor reads three lines: the dispatch summary, the scratch
    directory and the prompt path. The hash and SHA are abbreviated to 12
    characters; a build that prints the full hash, the tree directory or a fourth
    line breaks the reader of this output."""
    result = env.build()
    assert result.code == 0, result.err
    manifest = result.manifest
    assert result.out == (
        f"DISPATCH issue={env.issue} body={manifest['body_hash']} "
        f"fork=main@{manifest['fork_sha'][:12]}\n"
        f"SCRATCH {manifest['scratch_dir']}\n"
        f"PROMPT {manifest['prompt_file']}\n"
    )
    assert len(manifest["body_hash"]) == 12


def test_with_json_the_manifest_is_printed(env):
    """``--json`` prints the manifest that was written, and only it."""
    result = env.build("--json")
    assert result.code == 0, result.err
    assert json.loads(result.out) == result.manifest


# --------------------------------------------------------------------------- #
# --vault-root
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("body", "give_flag", "expect_flag"),
    [
        ("See [[Some Note]] for context.\n", True, True),
        ("See [[Some Note]] for context.\n", False, False),
        ("No wikilinks here.\n", True, False),
    ],
    ids=["flag-and-wikilinks", "wikilinks-without-flag", "flag-without-wikilinks"],
)
def test_vault_root_reaches_detector_5_only_with_the_flag_and_a_wikilink(env, tmp_path, body, give_flag, expect_flag):
    """Wikilink resolution needs a vault; the evidence script reports a bad
    ``--vault-root`` as ``not_run``, so the flag is passed exactly when it was
    given and the body has ``[[``, before ``--json``. A build that ignores the
    flag leaves every wikilink unresolved."""
    vault = tmp_path / "the-vault"
    vault.mkdir()
    env.set_body(body)
    result = env.build(*(["--vault-root", str(vault)] if give_flag else []))
    assert result.code == 0, result.err
    argv = env.detector_calls[0]["argv"]
    if expect_flag:
        at = argv.index("--vault-root")
        assert argv[at + 1] == str(vault) and at < argv.index("--json")
    else:
        assert "--vault-root" not in argv


# --------------------------------------------------------------------------- #
# own location: no plugin cache, no user id
# --------------------------------------------------------------------------- #


def install_copy(base: Path) -> Path:
    """Copy the script and its two sibling modules to ``<base>/machinery/engine``."""
    engine = base / "machinery" / "engine"
    engine.mkdir(parents=True)
    for name in ("cold_read_dispatch.py", "cold_read_stamp.py", "cold_read_ledger.py"):
        shutil.copy2(SCRIPTS_DIR / name, engine / name)
    return engine


def load_copy(engine: Path, monkeypatch):
    monkeypatch.setattr(sys, "path", list(sys.path))
    spec = importlib.util.spec_from_file_location("cold_read_dispatch_copy", engine / "cold_read_dispatch.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_path_derives_from_the_arguments_or_the_scripts_own_location(env, tmp_path, monkeypatch):
    """With the script copied to another directory and ``HOME`` and ``USER`` set
    to a fixture value, the prompt, the manifest and the printed output name the
    copy's directory and contain neither a plugin-cache path nor the user id; the
    ``teeth_check.py`` path is derived from the copy, and an absent file exits 4
    asking for ``--teeth-check``."""
    base = tmp_path / "other-install"
    engine = install_copy(base)
    teeth = base / "skills" / "detector-teeth-check" / "scripts" / "teeth_check.py"
    monkeypatch.setenv("HOME", "/home/fixture-user-9x7")
    monkeypatch.setenv("USER", "fixture-user-9x7")
    copy = load_copy(engine, monkeypatch)
    env.module = copy
    env.set_body("Plain body.\n")
    env.fake_detectors()
    absent = env.build()
    assert absent.code == 4 and "--teeth-check" in absent.err
    teeth.parent.mkdir(parents=True)
    teeth.write_text("# stand-in\n", encoding="utf-8")
    result = env.build()
    assert result.code == 0, result.err
    manifest, reader = result.manifest, result.reader
    where = str(engine.resolve())
    assert manifest["preflight_command"] == (
        f'python3 "{where}/cold_read_dispatch.py" preflight --scratch {manifest["scratch_dir"]}'
    )
    assert f"ENGINE={where}" in reader.split("\n")
    assert str(teeth.resolve()) in dispatch_block(reader)
    assert env.detector_calls[0]["argv"][7] == f"{where}/cold_read_evidence.py"
    everything = reader + json.dumps(manifest) + result.out + result.err
    for forbidden in ("/plugins/cache/", "fixture-user-9x7"):
        assert forbidden not in everything, forbidden


def test_an_explicit_teeth_check_path_is_used_as_given(env, tmp_path):
    """``--teeth-check`` overrides the derived path; an explicit path that is not
    a file exits 4 like the derived one."""
    teeth = tmp_path / "somewhere" / "teeth_check.py"
    teeth.parent.mkdir()
    teeth.write_text("# stand-in\n", encoding="utf-8")
    result = env.build("--teeth-check", str(teeth))
    assert result.code == 0, result.err
    assert str(teeth) in dispatch_block(result.reader)
    missing = env.build("--teeth-check", str(tmp_path / "absent" / "teeth_check.py"))
    assert missing.code == 4 and "--teeth-check" in missing.err


# --------------------------------------------------------------------------- #
# further guards found while reading the tests against the issue's rules
# --------------------------------------------------------------------------- #


def test_reader_md_blocks_follow_the_documented_order(env):
    """The reader's prompt is, in order: a title, the dispatch block, one block
    per detector, the comments, the body and then the spec sections. A build
    that reorders them hands the reader the same text in a shape the procedure
    does not describe."""
    result = env.build()
    assert result.code == 0, result.err
    reader = result.reader
    markers = [
        "# Cold read of ",
        "## This dispatch",
        "## Detector 5 command and output",
        "## Detector 10 command and output",
        "## Comments",
        "## Issue body",
        "## Probe builds",
        "## Detectors\n",
        "## Reader contract",
    ]
    positions = [reader.index(marker) for marker in markers]
    assert positions[0] == 0 and positions == sorted(positions) and len(set(positions)) == len(markers)


@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("--fork-branch", "--upload-pack=touch-a-file"),
        ("--fork-branch", "-x"),
        ("--fork-branch", "a..b"),
        ("--detector5-ref", "--json"),
    ],
)
def test_a_ref_that_could_be_read_as_an_option_is_a_usage_error_before_any_git_call(env, option, value):
    """A branch name goes to ``git fetch`` and a ref to the detector's command
    line; one that starts with ``-`` would be read as an option (``--upload-pack``
    runs a program). Exit 2 before anything runs."""
    calls = spy_git(env.monkeypatch)
    result = env.build(f"{option}={value}")
    assert result.code == 2
    assert calls == [] and env.detector_calls == []


def test_a_settings_branch_that_could_be_read_as_an_option_exits_4_before_any_git_call(env, tmp_path):
    """The same guard for a branch that came from the checkout's settings."""
    env.checkout = clone_of(env.world, tmp_path / "checkout-with-settings", 'integration_target = "--upload-pack=x"\n')
    calls = spy_git(env.monkeypatch)
    result = env.build()
    assert result.code == 4
    assert calls == [] and env.detector_calls == []


@pytest.mark.parametrize(
    ("verb", "failure"),
    [
        ("ls-remote", (128, "", "fatal: unable to access")),
        ("ls-remote", None),
        ("fetch", (1, "", "fatal: couldn't find remote ref")),
        ("fetch", None),
        ("archive", (1, "", "fatal: not a valid object")),
        ("archive", None),
    ],
    ids=["ls-remote-fails", "ls-remote-cannot-run", "fetch-fails", "fetch-cannot-run", "archive-fails", "archive-cannot-run"],
)
def test_a_git_command_that_fails_exits_4_and_the_build_goes_no_further(env, verb, failure):
    """Each of the three git commands is a value the build cannot do without
    (fork SHA, fetched branch, archive): a non-zero exit or a program that cannot
    run is exit 4 naming the command, and the detectors are never run."""
    real = mod._run_git
    seen: list[str] = []

    def fake(args, cwd=None, timeout=30):
        seen.append(args[0])
        return failure if args[0] == verb else real(args, cwd, timeout)

    env.monkeypatch.setattr(mod, "_run_git", fake)
    result = env.build()
    assert result.code == 4
    said = {
        "ls-remote": "git ls-remote origin refs/heads/main failed",
        "fetch": "git fetch origin main failed",
        "archive": "git archive of",
    }[verb]
    assert said in result.err and "Traceback" not in result.err
    assert "cannot extract" not in result.err
    order = ["ls-remote", "fetch", "archive"]
    assert seen == order[: order.index(verb) + 1]
    assert env.detector_calls == []


def test_a_spec_with_crlf_line_endings_yields_the_same_sections(env):
    """The spec is a file another tool may have checked out with CRLF endings;
    its code fences must still close and its headings still split sections."""
    env.spec.write_bytes(spec_text().replace("\n", "\r\n").encode("utf-8"))
    result = env.build()
    assert result.code == 0, result.err
    assert result.manifest["spec_sections"] == list(DEFAULT_GIVEN)
    assert "\r" not in result.reader
    assert "Text after the fence belongs to the same section." in result.reader


def test_a_checkout_reached_through_a_symlink_is_hidden_under_both_spellings(env, tmp_path):
    """A detector may echo the path the checkout really lives at, not the one
    the conductor passed; the prompt must hide both."""
    link = tmp_path / "checkout-link"
    link.symlink_to(env.world.checkout, target_is_directory=True)
    env.checkout = link
    real = str(env.world.checkout.resolve())
    env.fake_detectors(five=(0, json.dumps({"real": real, "link": str(link)}) + "\n", ""))
    result = env.build()
    assert result.code == 0, result.err
    written = (env.out / "detector5.json").read_text(encoding="utf-8")
    assert real not in written and str(link) not in written
    assert real not in without_body(result.reader) and str(link) not in without_body(result.reader)


def test_a_checkout_that_is_not_a_directory_is_a_usage_error(env, tmp_path):
    """Unreadable input is exit 2, decided before any ``git`` call: a build
    pointed at a path that is not a directory would otherwise exit 4 with a
    message about ``ls-remote`` that hides the real mistake."""
    env.checkout = tmp_path / "no-such-checkout"
    calls = spy_git(env.monkeypatch)
    result = env.build()
    assert result.code == 2 and "--checkout" in result.err
    assert calls == []


def test_undecodable_bytes_in_the_spec_or_the_comments_file_do_not_stop_the_build(env):
    """Every file another tool wrote is decoded with replacement characters:
    a stray byte in a comment or in the spec's intro must not raise a
    ``UnicodeDecodeError``."""
    env.spec.write_bytes(spec_text().replace("Intro,", "Intro \u00e9,").encode("latin-1", errors="replace") + b"\xff\n")
    env.comments_json.write_bytes(
        b'{"comments": [{"body": "caf\xe9 note", "author": {"login": "a"}, "createdAt": "t"}]}'
    )
    result = env.build()
    assert result.code == 0, result.err
    assert "caf\ufffd note" in (env.out / "comments.md").read_text(encoding="utf-8")


def test_a_wrapped_what_the_reader_is_given_bullet_is_read_whole_and_no_further(env):
    """The bullet may wrap onto continuation lines, and the next bullet's own
    backticked words are not section names; a parser that stops at the first
    line misses names, one that runs on takes the next bullet's."""
    spec = spec_text(bullet=False).replace(
        "## Procedure",
        "- **What the reader is given.** The reader's prompt carries these sections\n"
        "  of this file verbatim and no others: `Probe builds`,\n"
        "  `Detectors` and `Reader contract`.\n"
        "- **Another bullet.** It mentions `Unrelated section` in passing.\n\n"
        "## Procedure",
    )
    env.spec.write_text(spec, encoding="utf-8")
    result = env.build()
    assert result.code == 0, result.err
    assert result.manifest["spec_sections"] == list(DEFAULT_GIVEN)

