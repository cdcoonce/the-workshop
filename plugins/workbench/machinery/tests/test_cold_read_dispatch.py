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
import inspect
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(SCRIPTS_DIR))

import cold_read_dispatch as mod  # noqa: E402

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
    assert calls == [(["git", "--version"], 30), (["uv", "--version"], 30)]


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
    tamper = sys.argv[3] == "tamper"
    removed, busy = [], []


    def hook(event, args):
        if busy:
            return
        if event == "os.remove":
            removed.append(os.path.basename(os.fsdecode(args[0])))
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
                    with open(path, "w", encoding="utf-8") as handle:
                        handle.write("tampered-by-the-test")
                finally:
                    busy.pop()


    sys.addaudithook(hook)
    returned = mod._roundtrip_sentinel(directory, "written-by-the-test")
    print(json.dumps({"returned": returned, "removed": removed}))
    """
)


def probe_round_trip(directory: Path, mode: str) -> dict:
    """Run the real ``_roundtrip_sentinel`` in a child under an audit hook.

    The hook records every path removed and, in ``"tamper"`` mode, rewrites the
    sentinel the moment anything reopens it for reading. It lives in a child
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


def test_every_import_in_the_script_is_standard_library():
    """Stdlib only, at any depth: a lazy ``import yaml`` inside a function
    would break the preflight on exactly the machine where the environment is
    the problem."""
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0 and node.module, ast.dump(node)
            imported.append(node.module)
    assert imported, "the script imports nothing, so this test would pass vacuously"
    outside = sorted({n for n in imported if n.split(".")[0] not in sys.stdlib_module_names})
    assert outside == []
