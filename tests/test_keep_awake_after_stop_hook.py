"""Tests for the keep-awake-after-stop Stop hook.

Drives the hook as a real subprocess with JSON on stdin. Fake ``caffeinate`` and
``pmset`` executables live in a per-test bin dir that is the whole of PATH (plus a
symlink to the real ``ps``), so the real macOS binaries are never reachable. The
fake caffeinate logs its argv and pid, then sleeps; every hold a test started is
killed in the fixture finalizer.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_PATH = (
    REPO_ROOT
    / "plugins"
    / "workbench"
    / "hooks"
    / "scripts"
    / "keep-awake-after-stop.py"
)

AC_OUT = "Now drawing from 'AC Power'"
BATTERY_OUT = "Now drawing from 'Battery Power'"


def _assistant(input_t, cache_read=0, cache_create=0, *, sidechain=False) -> str:
    record = {
        "type": "assistant",
        "message": {
            "usage": {
                "input_tokens": input_t,
                "cache_read_input_tokens": cache_read,
                "cache_creation_input_tokens": cache_create,
                "output_tokens": 5,
            }
        },
    }
    if sidechain:
        record["isSidechain"] = True
    return json.dumps(record)


def wait_for(predicate, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class Rig:
    def __init__(
        self,
        root: Path,
        *,
        caffeinate: bool = True,
        pmset: bool = True,
        ps: bool = True,
        pmset_out: str = AC_OUT,
        pmset_rc: int = 0,
    ) -> None:
        self.root = root
        self.bin = root / "bin"
        self.state = root / "a" / "state"
        self.log = root / "caffeinate.log"
        self.pmset_log = root / "pmset.log"
        self.transcript = root / "t.jsonl"
        self.extra_procs: list[subprocess.Popen] = []
        self.bin.mkdir(parents=True)
        (root / "home").mkdir()
        if caffeinate:
            impl = self.bin / "caffeinate_impl.py"
            impl.write_text(
                "import json, os, sys, time\n"
                f"with open({str(self.log)!r}, 'a') as f:\n"
                "    f.write(json.dumps({'pid': os.getpid(), 'argv': sys.argv[1:]}) + '\\n')\n"
                "time.sleep(30)\n",
                encoding="utf-8",
            )
            self._script(
                "caffeinate",
                f"exec {shlex.quote(sys.executable)} {shlex.quote(str(impl))} \"$@\"\n",
            )
        if pmset:
            self._script(
                "pmset",
                f"echo \"$@\" >> {shlex.quote(str(self.pmset_log))}\n"
                f"printf '%s\\n' {shlex.quote(pmset_out)}\n"
                f"exit {pmset_rc}\n",
            )
        if ps:
            real_ps = shutil.which("ps")
            assert real_ps, "test host has no ps"
            (self.bin / "ps").symlink_to(real_ps)

    def _script(self, name: str, body: str) -> None:
        path = self.bin / name
        path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
        path.chmod(0o755)

    def write_transcript(self, *lines: str) -> Path:
        self.transcript.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return self.transcript

    def run(self, payload=None, *, env_extra: dict | None = None):
        if payload is None:
            payload = {
                "session_id": "sess-1",
                "transcript_path": str(self.transcript),
            }
        stdin = payload if isinstance(payload, str) else json.dumps(payload)
        env = {
            "PATH": str(self.bin),
            "HOME": str(self.root / "home"),
            "WORKSHOP_KEEP_AWAKE_DIR": str(self.state),
        }
        env.update(env_extra or {})
        return subprocess.run(
            [sys.executable, str(HOOK_PATH)],
            input=stdin,
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )

    def pid_files(self) -> list[Path]:
        return sorted(self.state.glob("*.pid")) if self.state.is_dir() else []

    def log_entries(self) -> list[dict]:
        if not self.log.exists():
            return []
        out = []
        for line in self.log.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(json.loads(line))
        return out

    def wait_logged(self, n: int = 1) -> list[dict]:
        assert wait_for(lambda: len(self.log_entries()) >= n), "no hold started"
        return self.log_entries()

    def spawned(self) -> bool:
        return bool(self.pid_files())

    def cleanup(self) -> None:
        pids: set[int] = {e["pid"] for e in self.log_entries()}
        for pf in self.pid_files():
            try:
                pids.add(int(pf.read_text().strip()))
            except (ValueError, OSError):
                pass
        for pid in pids:
            if not alive(pid):
                continue
            ps = subprocess.run(
                ["ps", "-p", str(pid), "-o", "command="],
                capture_output=True,
                text=True,
            )
            if ps.returncode == 0 and str(self.bin) in ps.stdout:
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        for proc in self.extra_procs:
            if proc.poll() is None:
                proc.kill()
            proc.wait()


@pytest.fixture
def make_rig(tmp_path):
    rigs: list[Rig] = []
    counter = [0]

    def factory(**kwargs) -> Rig:
        counter[0] += 1
        rig = Rig(tmp_path / f"rig{counter[0]}", **kwargs)
        rigs.append(rig)
        return rig

    yield factory
    for rig in rigs:
        rig.cleanup()


@pytest.fixture
def rig(make_rig) -> Rig:
    r = make_rig()
    r.write_transcript(_assistant(250_000))
    return r


# B1


def test_spawns_caffeinate_with_exact_argv(rig):
    result = rig.run()
    assert result.returncode == 0
    assert result.stdout == ""
    entries = rig.wait_logged()
    assert [e["argv"] for e in entries] == [["-i", "-t", "4200"]]
    assert rig.spawned()
    assert "-g" in rig.pmset_log.read_text() and "batt" in rig.pmset_log.read_text()


# B2


def test_below_floor_does_not_spawn(rig):
    rig.write_transcript(_assistant(199_999))
    result = rig.run()
    assert result.returncode == 0 and result.stdout == ""
    assert not rig.spawned()
    assert not rig.log.exists()


def test_exactly_at_floor_spawns(rig):
    rig.write_transcript(_assistant(100_000, 50_000, 50_000))
    result = rig.run()
    assert result.returncode == 0
    assert rig.spawned()
    rig.wait_logged()


# B3


def test_env_floor_override(make_rig):
    low = make_rig()
    low.write_transcript(_assistant(5_000))
    assert low.run(env_extra={"CLAUDE_CODE_IDLE_COMPACT_MIN_TOKENS": "1000"}).returncode == 0
    assert low.spawned()

    high = make_rig()
    high.write_transcript(_assistant(250_000))
    result = high.run(env_extra={"CLAUDE_CODE_IDLE_COMPACT_MIN_TOKENS": "300000"})
    assert result.returncode == 0
    assert not high.spawned()


@pytest.mark.parametrize("value", ["", "abc", "0", "-5", "1.5"])
def test_invalid_env_floor_falls_back_to_default(make_rig, value):
    r = make_rig()
    r.write_transcript(_assistant(150_000))
    result = r.run(env_extra={"CLAUDE_CODE_IDLE_COMPACT_MIN_TOKENS": value})
    assert result.returncode == 0
    assert not r.spawned()

    r2 = make_rig()
    r2.write_transcript(_assistant(200_000))
    r2.run(env_extra={"CLAUDE_CODE_IDLE_COMPACT_MIN_TOKENS": value})
    assert r2.spawned()


# B4


def test_on_battery_does_not_spawn(make_rig):
    r = make_rig(pmset_out=BATTERY_OUT)
    r.write_transcript(_assistant(250_000))
    result = r.run()
    assert result.returncode == 0 and result.stdout == ""
    assert not r.spawned()
    assert r.pmset_log.exists()


def test_pmset_failure_does_not_spawn(make_rig):
    r = make_rig(pmset_out=AC_OUT, pmset_rc=1)
    r.write_transcript(_assistant(250_000))
    result = r.run()
    assert result.returncode == 0
    assert not r.spawned()


# B5


def test_context_uses_last_main_thread_assistant_usage(make_rig):
    big_then_small = make_rig()
    big_then_small.write_transcript(
        _assistant(900_000),
        _assistant(500, 400, 100),
        json.dumps({"type": "user", "message": {"content": "hi"}}),
    )
    assert big_then_small.run().returncode == 0
    assert not big_then_small.spawned()

    small_then_big = make_rig()
    small_then_big.write_transcript(
        _assistant(10),
        "{not json",
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "usage": {
                        "input_tokens": 100_000,
                        "cache_read_input_tokens": 150_000,
                        "cache_creation_input_tokens": "oops",
                    }
                },
            }
        ),
        "also not json",
        json.dumps({"type": "user", "message": {"content": "hi"}}),
    )
    assert small_then_big.run().returncode == 0
    assert small_then_big.spawned()

    no_assistant = make_rig()
    no_assistant.write_transcript(json.dumps({"type": "user"}), "garbage")
    assert no_assistant.run().returncode == 0
    assert not no_assistant.spawned()


def test_sidechain_usage_is_ignored(make_rig):
    ignored_big = make_rig()
    ignored_big.write_transcript(
        _assistant(1_000), _assistant(900_000, sidechain=True)
    )
    assert ignored_big.run().returncode == 0
    assert not ignored_big.spawned()

    ignored_small = make_rig()
    ignored_small.write_transcript(
        _assistant(250_000), _assistant(10, sidechain=True)
    )
    assert ignored_small.run().returncode == 0
    assert ignored_small.spawned()


# B6


def test_missing_binaries_is_a_noop(make_rig):
    for kwargs in ({"caffeinate": False}, {"pmset": False}):
        r = make_rig(**kwargs)
        r.write_transcript(_assistant(250_000))
        result = r.run()
        assert result.returncode == 0 and result.stdout == ""
        assert not r.spawned()
        assert not r.log.exists()


# B7


def test_replaces_previous_hold_for_same_session(rig):
    assert rig.run().returncode == 0
    first = rig.wait_logged(1)[0]["pid"]
    pid_file = rig.state / "sess-1.pid"
    assert int(pid_file.read_text().strip()) == first

    assert rig.run().returncode == 0
    entries = rig.wait_logged(2)
    second = entries[1]["pid"]
    assert second != first
    assert wait_for(lambda: not alive(first)), "previous hold was not replaced"
    assert alive(second)
    assert int(pid_file.read_text().strip()) == second


# B8


def test_does_not_kill_pid_that_is_not_caffeinate(rig):
    decoy = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    rig.extra_procs.append(decoy)
    rig.state.mkdir(parents=True)
    (rig.state / "sess-1.pid").write_text(str(decoy.pid), encoding="utf-8")

    assert rig.run().returncode == 0
    entries = rig.wait_logged()
    time.sleep(0.3)
    assert decoy.poll() is None, "a non-caffeinate pid was signalled"
    new_pid = entries[0]["pid"]
    assert int((rig.state / "sess-1.pid").read_text().strip()) == new_pid


def test_missing_ps_signals_nothing_and_still_spawns(make_rig):
    r = make_rig(ps=False)
    r.write_transcript(_assistant(250_000))
    # A genuine fake hold from a previous run, still alive.
    old = subprocess.Popen(
        [str(r.bin / "caffeinate"), "-i", "-t", "4200"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    r.extra_procs.append(old)
    assert wait_for(lambda: len(r.log_entries()) >= 1)
    r.state.mkdir(parents=True)
    (r.state / "sess-1.pid").write_text(str(old.pid), encoding="utf-8")

    assert r.run().returncode == 0
    entries = r.wait_logged(2)
    time.sleep(0.3)
    assert old.poll() is None
    assert int((r.state / "sess-1.pid").read_text().strip()) == entries[1]["pid"]


# B9


def test_unsafe_session_id_does_not_escape_state_dir(rig):
    payload = {"session_id": "../../x", "transcript_path": str(rig.transcript)}
    assert rig.run(payload).returncode == 0
    rig.wait_logged()
    assert not (rig.root / "x.pid").exists()
    assert not (rig.root / "x").exists()
    files = rig.pid_files()
    assert len(files) == 1
    expected = hashlib.sha256(str(rig.transcript).encode("utf-8")).hexdigest()[:16]
    assert files[0].name == f"{expected}.pid"
    assert re.fullmatch(r"[0-9a-f]{16}\.pid", files[0].name)


# B10


def test_opt_out_env_disables(rig):
    result = rig.run(env_extra={"WORKSHOP_KEEP_AWAKE": "0"})
    assert result.returncode == 0 and result.stdout == ""
    assert not rig.spawned()
    assert not rig.pmset_log.exists()


# B11


def test_returns_promptly_while_hold_runs(rig):
    start = time.monotonic()
    result = rig.run()
    elapsed = time.monotonic() - start
    assert result.returncode == 0
    assert elapsed < 10
    pid = rig.wait_logged()[0]["pid"]
    assert alive(pid)


# B12


@pytest.mark.parametrize(
    "case",
    [
        "empty",
        "non_json",
        "json_array",
        "missing_transcript",
        "non_string_transcript",
        "transcript_not_a_file",
        "non_string_session_id",
    ],
)
def test_fails_open_on_bad_input(rig, case):
    transcript = str(rig.transcript)
    payloads = {
        "empty": "",
        "non_json": "not json {",
        "json_array": "[1, 2]",
        "missing_transcript": {"session_id": "s"},
        "non_string_transcript": {"session_id": "s", "transcript_path": 42},
        "transcript_not_a_file": {
            "session_id": "s",
            "transcript_path": str(rig.root / "nope.jsonl"),
        },
        "non_string_session_id": {"session_id": 12345, "transcript_path": transcript},
    }
    result = rig.run(payloads[case])
    assert result.returncode == 0
    assert result.stdout == ""
    if case == "non_string_session_id":
        expected = hashlib.sha256(transcript.encode("utf-8")).hexdigest()[:16]
        assert [p.name for p in rig.pid_files()] == [f"{expected}.pid"]
        rig.wait_logged()
    else:
        assert not rig.spawned()
