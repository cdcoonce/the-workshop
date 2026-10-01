"""Write-scope tests for evals._harness.dispatch.

#993 already asserts, per module, that the harness writes only under
``evals/`` and never a file named ``tests.md`` (see
``test_ledger.py::test_write_run_writes_only_under_runs_dir_and_never_a_file_named_tests_md``
and the equivalent in ``test_report.py``). This extends that same assertion
to #995's own write surface rather than duplicating either of those tests:
``build_dispatch_prompt``, ``build_no_skill_prompt``, and ``score_attempt``
are read-only, and ``snapshot_end_state`` writes only under the ``dest`` its
caller supplies.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import types
from pathlib import Path

import pytest

from evals._harness.dispatch import (
    build_dispatch_prompt,
    build_no_skill_prompt,
    find_duplicate_item_ids,
    find_invalid_modes,
    score_attempt,
    snapshot_end_state,
)


class StrayWriteError(AssertionError):
    """A write (or a process spawn) happened where the code under test may not make one."""


_STATE_ATTR = "_eval_suite_write_scope_state"
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND

# audit event -> indexes of the arguments that are written/removed paths
_PATH_EVENTS: dict[str, tuple[int, ...]] = {
    "os.mkdir": (0,),
    "os.remove": (0,),
    "os.rmdir": (0,),
    "os.truncate": (0,),
    "os.utime": (0,),
    "os.chmod": (0,),
    "os.rename": (0, 1),
    "os.link": (0, 1),
    "os.symlink": (1,),
    "shutil.copyfile": (1,),
    "shutil.copymode": (1,),
    "shutil.copystat": (1,),
    "shutil.copytree": (1,),
    "shutil.move": (0, 1),
    "shutil.rmtree": (0,),
    "shutil.make_archive": (0,),
    "shutil.unpack_archive": (1,),
    "sqlite3.connect": (0,),
}
# Spawning any process is a write the recorder cannot see into: never allowed.
_PROCESS_EVENTS = frozenset(
    {
        "subprocess.Popen",
        "os.system",
        "os.exec",
        "os.posix_spawn",
        "os.spawn",
        "os.fork",
        "os.forkpty",
    }
)
_CREATES_DIRECTORIES = frozenset({"os.mkdir"})


def _audit_hook(event: str, args: tuple) -> None:
    recorder = getattr(sys, _STATE_ATTR).active
    if recorder is not None:
        recorder.audit(event, args)


# Audit hooks cannot be removed, so the hook is installed once per process and
# is inert unless a ``WriteRecorder`` context is active. The state hangs off
# ``sys`` so a second import of this module (importlib mode) does not stack a
# second hook.
if not hasattr(sys, _STATE_ATTR):
    setattr(sys, _STATE_ATTR, types.SimpleNamespace(active=None))
    sys.addaudithook(_audit_hook)


def recorder_is_off() -> bool:
    return getattr(sys, _STATE_ATTR).active is None


class WriteRecorder:
    """Records every write the code under test makes, however it is reached, and blocks stray ones.

    Diffing ``tmp_path`` before and after only sees writes that land inside it,
    and patching ``open``/``os.*`` misses aliases bound before the patch
    (``_o = open``, ``from os import mkdir``, a pre-bound ``os.open``), shell-outs
    and ``sqlite3``. A ``sys.addaudithook`` hook sees the event at the C layer
    whatever name the caller used: ``open`` (builtin, ``io``, ``os.open``,
    ``FileIO``, ``Path.write_*``/``touch``), ``os.mkdir``/``rename``/``remove``/
    ``rmdir``/``symlink``/``link``/``truncate``/``utime``/``chmod``, the audited
    ``shutil`` operations, ``sqlite3.connect``, and every process spawn
    (``subprocess.Popen``, ``os.system``, ``os.exec*``, ``os.spawn*``,
    ``os.posix_spawn``, ``os.fork``). The hook raises ``StrayWriteError`` before
    the operation happens when its target is outside ``allowed_roots`` (a
    process spawn is never allowed), so a blocked mutant leaves no junk behind.
    A ``mkdir`` may also create an ancestor of an allowed root.

    Use as a context manager; the on/off flag is cleared on exit even when the
    body raises.
    """

    def __init__(self, allowed_roots: list[Path]):
        self.writes: list[tuple[str, Path]] = []
        self._roots = [Path(os.path.realpath(root)) for root in allowed_roots]

    def __enter__(self) -> "WriteRecorder":
        state = getattr(sys, _STATE_ATTR)
        assert state.active is None, "a WriteRecorder is already active"
        state.active = self
        return self

    def __exit__(self, *exc_info) -> None:
        getattr(sys, _STATE_ATTR).active = None

    def audit(self, event: str, args: tuple) -> None:
        if event in _PROCESS_EVENTS:
            self.writes.append((event, Path(event)))
            raise StrayWriteError(f"{event} spawned a process while recording writes")
        if event == "open":
            path, flags = args[0], args[2]
            if isinstance(flags, int) and flags & _WRITE_FLAGS:
                self._note("open", path)
        elif event in _PATH_EVENTS:
            for index in _PATH_EVENTS[event]:
                if index < len(args):
                    self._note(event, args[index])

    def _note(self, op: str, target) -> None:
        if not isinstance(target, (str, bytes, os.PathLike)):
            return
        text = os.fsdecode(target)
        if text in ("", ":memory:"):
            return
        path = Path(os.path.realpath(text))
        self.writes.append((op, path))
        if not self._allowed(op, path):
            raise StrayWriteError(f"{op} wrote outside the allowed roots: {path}")

    def _allowed(self, op: str, path: Path) -> bool:
        for root in self._roots:
            if path == root or root in path.parents:
                return True
            if op in _CREATES_DIRECTORIES and path in root.parents:
                return True
        return False

    def stray_names(self) -> set[str]:
        return {path.name for _, path in self.writes}


@pytest.fixture(autouse=True)
def _recorder_flag_is_off_after_every_test():
    yield
    assert recorder_is_off(), "a test left the write recorder switched on"


def _files_under(root: Path) -> set[Path]:
    return {path for path in root.rglob("*") if path.is_file()}


def _make_minimal_case(case_dir: Path, *, with_end_state: bool = False) -> None:
    case_dir.mkdir(parents=True)
    (case_dir / "prompt.md").write_text("Investigate the repo.\n", encoding="utf-8")
    (case_dir / "acceptance.md").write_text("private\n", encoding="utf-8")
    predicates = "def always_true(evidence):\n    return True\n"
    if with_end_state:
        predicates += (
            "\n\ndef end_state(workdir, case_dir, transcripts):\n"
            "    return {'note.txt': 'noted'}\n"
        )
    (case_dir / "predicates.py").write_text(predicates, encoding="utf-8")
    (case_dir / "case.toml").write_text(
        'mode = "subagent"\n'
        'prompt = "prompt.md"\n'
        "\n"
        "[[items]]\n"
        'id = "item-a"\n'
        'kind = "trend"\n'
        'scorer = "always_true"\n',
        encoding="utf-8",
    )


def _write_transcript(path: Path, final_text: str = "done") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(
        {
            "type": "assistant",
            "message": {"model": "claude-test", "content": [{"type": "text", "text": final_text}]},
        }
    )
    path.write_text(line + "\n", encoding="utf-8")


def test_prompt_and_score_builders_write_nothing(tmp_path, monkeypatch):
    case_dir = tmp_path / "skill-x" / "case-a"
    _make_minimal_case(case_dir)
    transcript_path = tmp_path / "raws" / "t.jsonl"
    _write_transcript(transcript_path)

    before = _files_under(tmp_path)

    with WriteRecorder([]):
        build_dispatch_prompt(case_dir)
        build_no_skill_prompt(case_dir)
        score_attempt(case_dir, [transcript_path], None, {"item-a"})

    after = _files_under(tmp_path)

    assert after == before
    assert not any(path.name == "tests.md" for path in tmp_path.rglob("*"))


def test_snapshot_end_state_writes_only_under_dest_and_never_tests_md(tmp_path, monkeypatch):
    case_dir = tmp_path / "skill-x" / "case-b"
    _make_minimal_case(case_dir, with_end_state=True)
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    transcript_path = tmp_path / "raws" / "t2.jsonl"
    _write_transcript(transcript_path)
    dest = tmp_path / "attempt-1" / "end_state"

    before = _files_under(tmp_path)

    with WriteRecorder([dest]):
        snapshot_end_state(case_dir, workdir, [transcript_path], dest)

    after = _files_under(tmp_path)
    new_files = after - before

    assert new_files == {dest / "note.txt"}
    assert not any(path.name == "tests.md" for path in tmp_path.rglob("*"))


# ---------------------------------------------------------------------------
# the recorder itself: every write entry point must be seen (positive controls)
# ---------------------------------------------------------------------------


def _write_via_path_write_text(target: Path) -> None:
    target.write_text("x", encoding="utf-8")


def _write_via_path_write_bytes(target: Path) -> None:
    target.write_bytes(b"x")


def _write_via_open(target: Path) -> None:
    with open(target, "w", encoding="utf-8") as handle:
        handle.write("x")


def _write_via_io_open_append(target: Path) -> None:
    with io.open(target, "a", encoding="utf-8") as handle:
        handle.write("x")


def _write_via_os_open(target: Path) -> None:
    os.close(os.open(target, os.O_WRONLY | os.O_CREAT))


def _write_via_touch(target: Path) -> None:
    target.touch()


def _write_via_mkdir(target: Path) -> None:
    target.mkdir()


def _write_via_makedirs(target: Path) -> None:
    os.makedirs(target / "nested")


def _write_via_shutil_copyfile(target: Path) -> None:
    shutil.copyfile(__file__, target)


def _write_via_symlink(target: Path) -> None:
    os.symlink(__file__, target)


def _write_via_subprocess_touch(target: Path) -> None:
    subprocess.run(["touch", str(target)], check=False)


def _write_via_os_system(target: Path) -> None:
    os.system(f"touch {target}")


def _write_via_sqlite(target: Path) -> None:
    sqlite3.connect(target).close()


_ALIASED_OS_MKDIR = os.mkdir
_ALIASED_OPEN = open
_PREBOUND_OS_OPEN = os.open
_PREBOUND_OS_WRITE = os.write


def _write_via_aliased_os_mkdir(target: Path) -> None:
    _ALIASED_OS_MKDIR(target)


def _write_via_aliased_open(target: Path) -> None:
    _ALIASED_OPEN(target, "w").close()


def _write_via_prebound_os_open_and_write(target: Path) -> None:
    fd = _PREBOUND_OS_OPEN(target, os.O_WRONLY | os.O_CREAT)
    _PREBOUND_OS_WRITE(fd, b"x")
    os.close(fd)


def _write_via_rename(target: Path) -> None:
    os.rename(__file__, target)


def _write_via_remove(target: Path) -> None:
    os.remove(target)


def _write_via_rmdir(target: Path) -> None:
    os.rmdir(target)


def _write_via_hard_link(target: Path) -> None:
    os.link(__file__, target)


def _write_via_truncate(target: Path) -> None:
    os.truncate(target, 0)


def _write_via_shutil_move(target: Path) -> None:
    shutil.move(__file__, target)


def _write_via_shutil_copytree(target: Path) -> None:
    shutil.copytree(Path(__file__).parent, target)


def _write_via_shutil_rmtree(target: Path) -> None:
    shutil.rmtree(target)


def _write_via_fileio(target: Path) -> None:
    io.FileIO(target, "w").close()


_WRITERS = [
    _write_via_subprocess_touch,
    _write_via_os_system,
    _write_via_sqlite,
    _write_via_aliased_os_mkdir,
    _write_via_aliased_open,
    _write_via_prebound_os_open_and_write,
    _write_via_rename,
    _write_via_remove,
    _write_via_rmdir,
    _write_via_hard_link,
    _write_via_truncate,
    _write_via_shutil_move,
    _write_via_shutil_copytree,
    _write_via_shutil_rmtree,
    _write_via_fileio,
    _write_via_path_write_text,
    _write_via_path_write_bytes,
    _write_via_open,
    _write_via_io_open_append,
    _write_via_os_open,
    _write_via_touch,
    _write_via_mkdir,
    _write_via_makedirs,
    _write_via_shutil_copyfile,
    _write_via_symlink,
]


@pytest.mark.parametrize("writer", _WRITERS, ids=lambda fn: fn.__name__)
def test_the_recorder_blocks_and_records_a_write_outside_the_allowed_root(tmp_path, writer):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    stray = tmp_path / "stray"
    # Targets that must already exist for the operation to make sense.
    stray_dir = tmp_path / "stray-existing"
    stray_dir.mkdir()
    (tmp_path / "stray-file").write_text("x", encoding="utf-8")

    with WriteRecorder([allowed]) as recorder:
        with pytest.raises(StrayWriteError):
            writer(stray)

    assert recorder.writes, "the write was not even recorded"
    assert not stray.exists()


def test_the_recorder_allows_writes_under_the_allowed_root_and_records_them(tmp_path):
    allowed = tmp_path / "allowed"

    with WriteRecorder([allowed]) as recorder:
        (allowed / "deep").mkdir(parents=True)
        (allowed / "deep" / "note.txt").write_text("x", encoding="utf-8")

    assert {path.name for _, path in recorder.writes} >= {"allowed", "deep", "note.txt"}


def test_the_recorder_blocks_a_sibling_directory_that_merely_shares_the_prefix(tmp_path):
    (tmp_path / "allowed").mkdir()

    with WriteRecorder([tmp_path / "allowed"]):
        with pytest.raises(StrayWriteError):
            (tmp_path / "allowed-sibling").mkdir()


def test_the_recorder_ignores_reads(tmp_path):
    readable = tmp_path / "readable.txt"
    readable.write_text("x", encoding="utf-8")

    with WriteRecorder([]) as recorder:
        assert readable.read_text(encoding="utf-8") == "x"
        with open(readable, encoding="utf-8") as handle:
            handle.read()
        os.listdir(tmp_path)

    assert recorder.writes == []


def test_a_process_spawn_is_blocked_even_inside_an_allowed_root(tmp_path):
    with WriteRecorder([tmp_path]):
        with pytest.raises(StrayWriteError):
            subprocess.run(["true"], check=False)


def test_the_on_off_flag_is_cleared_when_the_body_raises(tmp_path):
    with pytest.raises(RuntimeError):
        with WriteRecorder([tmp_path]):
            assert not recorder_is_off()
            raise RuntimeError("body failed")

    assert recorder_is_off()


def test_recorders_do_not_nest(tmp_path):
    with WriteRecorder([tmp_path]):
        with pytest.raises(AssertionError, match="already active"):
            with WriteRecorder([tmp_path]):
                pass
    assert recorder_is_off()


def test_the_audit_hook_is_inert_outside_a_recording_window(tmp_path):
    (tmp_path / "unrecorded.txt").write_text("fine", encoding="utf-8")
    subprocess.run(["true"], check=True)

    assert recorder_is_off()


# ---------------------------------------------------------------------------
# the entry points write only where they are allowed to, anywhere on disk
# ---------------------------------------------------------------------------


def _sandbox(tmp_path: Path, monkeypatch) -> Path:
    """cwd, HOME and TMPDIR all point at one watched empty directory."""
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    monkeypatch.chdir(sandbox)
    monkeypatch.setenv("HOME", str(sandbox))
    monkeypatch.setenv("TMPDIR", str(sandbox))
    return sandbox


def test_read_only_entry_points_write_nothing_anywhere_on_disk(tmp_path, monkeypatch):
    case_dir = tmp_path / "skill-x" / "case-a"
    _make_minimal_case(case_dir)
    transcript_path = tmp_path / "raws" / "t.jsonl"
    _write_transcript(transcript_path)
    sandbox = _sandbox(tmp_path, monkeypatch)

    with WriteRecorder([]) as recorder:
        build_dispatch_prompt(case_dir)
        build_no_skill_prompt(case_dir)
        score_attempt(case_dir, [transcript_path], None, {"item-a"})
        find_invalid_modes([case_dir])
        find_duplicate_item_ids(tmp_path / "skill-x")

    assert recorder.writes == []
    assert list(sandbox.iterdir()) == []


def test_snapshot_end_state_writes_only_under_dest_anywhere_on_disk(tmp_path, monkeypatch):
    case_dir = tmp_path / "skill-x" / "case-b"
    _make_minimal_case(case_dir, with_end_state=True)
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    transcript_path = tmp_path / "raws" / "t3.jsonl"
    _write_transcript(transcript_path)
    dest = tmp_path / "attempt-1" / "end_state"
    sandbox = _sandbox(tmp_path, monkeypatch)

    with WriteRecorder([dest]) as recorder:
        snapshot_end_state(case_dir, workdir, [transcript_path], dest)

    written_files = [path for op, path in recorder.writes if op == "open"]
    assert written_files == [Path(os.path.realpath(dest / "note.txt"))]
    assert "tests.md" not in recorder.stray_names()
    assert list(sandbox.iterdir()) == []
