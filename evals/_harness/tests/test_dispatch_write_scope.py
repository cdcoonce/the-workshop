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

import builtins
import io
import json
import os
import shutil
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
    """A write landed outside the directory the entry point is allowed to write under."""


_MKDIR_LIKE = {"mkdir"}
_ONE_PATH_OPS = ("mkdir", "remove", "unlink", "rmdir", "truncate", "utime")


class WriteRecorder:
    """Records every filesystem write the code under test makes, and blocks stray ones.

    Diffing ``tmp_path`` before and after only sees writes that land inside
    it, so a function that writes ``/tmp/stray.txt`` or ``./tests.md`` passes
    unnoticed. This patches every Python-level write entry point
    (``open``/``io.open``, ``os.open``, ``os.mkdir``, ``os.rename``,
    ``os.replace``, ``os.remove``/``unlink``/``rmdir``, ``os.symlink``,
    ``os.link``, ``os.truncate``, ``os.utime``) instead — ``pathlib``'s
    ``write_text``/``write_bytes``/``touch``/``mkdir`` and ``shutil.copyfile``
    all route through them — records each target, and raises
    ``StrayWriteError`` before the write happens when the target is outside
    ``allowed_roots`` (so a blocked mutant leaves no junk behind). A
    ``mkdir`` may also create an ancestor of an allowed root.
    """

    def __init__(self, monkeypatch, allowed_roots: list[Path]):
        self.writes: list[tuple[str, Path]] = []
        self._roots = [Path(os.path.realpath(root)) for root in allowed_roots]
        self._install(monkeypatch)

    def _note(self, op: str, target) -> None:
        if not isinstance(target, (str, bytes, os.PathLike)):
            return
        path = Path(os.path.realpath(os.fsdecode(target)))
        self.writes.append((op, path))
        if not self._allowed(op, path):
            raise StrayWriteError(f"{op} wrote outside the allowed roots: {path}")

    def _allowed(self, op: str, path: Path) -> bool:
        for root in self._roots:
            if path == root or root in path.parents:
                return True
            if op in _MKDIR_LIKE and path in root.parents:
                return True
        return False

    def _install(self, monkeypatch) -> None:
        recorder = self
        real_open = builtins.open

        def guarded_open(file, mode="r", *args, **kwargs):
            if set(str(mode)) & set("wax+"):
                recorder._note("open", file)
            return real_open(file, mode, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", guarded_open)
        monkeypatch.setattr(io, "open", guarded_open)

        real_os_open = os.open
        write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND

        def guarded_os_open(path, flags, *args, **kwargs):
            if flags & write_flags:
                recorder._note("os.open", path)
            return real_os_open(path, flags, *args, **kwargs)

        monkeypatch.setattr(os, "open", guarded_os_open)

        def wrap(name: str, targets: tuple[int, ...]) -> None:
            real = getattr(os, name)

            def guarded(*args, **kwargs):
                for index in targets:
                    if index < len(args):
                        recorder._note(name, args[index])
                return real(*args, **kwargs)

            monkeypatch.setattr(os, name, guarded)

        for name in _ONE_PATH_OPS:
            wrap(name, (0,))
        wrap("rename", (0, 1))
        wrap("replace", (0, 1))
        wrap("link", (1,))
        wrap("symlink", (1,))

    def stray_names(self) -> set[str]:
        return {path.name for _, path in self.writes}


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
    WriteRecorder(monkeypatch, [])

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
    WriteRecorder(monkeypatch, [dest])

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


_WRITERS = [
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
def test_the_recorder_blocks_and_records_a_write_outside_the_allowed_root(
    tmp_path, monkeypatch, writer
):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    stray = tmp_path / "stray"
    recorder = WriteRecorder(monkeypatch, [allowed])

    with pytest.raises(StrayWriteError):
        writer(stray)

    assert recorder.writes, "the write was not even recorded"
    monkeypatch.undo()
    assert not stray.exists()


def test_the_recorder_allows_writes_under_the_allowed_root_and_records_them(tmp_path, monkeypatch):
    allowed = tmp_path / "allowed"
    recorder = WriteRecorder(monkeypatch, [allowed])

    (allowed / "deep").mkdir(parents=True)
    (allowed / "deep" / "note.txt").write_text("x", encoding="utf-8")

    assert {path.name for _, path in recorder.writes} >= {"allowed", "deep", "note.txt"}


def test_the_recorder_ignores_reads(tmp_path, monkeypatch):
    readable = tmp_path / "readable.txt"
    readable.write_text("x", encoding="utf-8")
    recorder = WriteRecorder(monkeypatch, [])

    assert readable.read_text(encoding="utf-8") == "x"
    with open(readable, encoding="utf-8") as handle:
        handle.read()

    assert recorder.writes == []


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
    recorder = WriteRecorder(monkeypatch, [])

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
    recorder = WriteRecorder(monkeypatch, [dest])

    snapshot_end_state(case_dir, workdir, [transcript_path], dest)

    written_files = [path for op, path in recorder.writes if op == "open"]
    assert written_files == [Path(os.path.realpath(dest / "note.txt"))]
    assert "tests.md" not in recorder.stray_names()
    assert list(sandbox.iterdir()) == []
