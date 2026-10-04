"""Real child processes, temporary Vaults, and no model or live hook calls."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

import pytest

ENGINE = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(ENGINE))
import graph_gardener as gg


WORKER = r'''
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import graph_gardener as gg
repo, sid, mode = Path(sys.argv[2]), sys.argv[3], sys.argv[4]
note = repo / "personal" / (sid + ".md")
gg.collect_touched_notes = lambda root, state, override=None: ([note], "cursor-" + sid)
gg.head_commit = lambda _: "head-" + sid
gg.broken_links_by_note = lambda _: {}
gg.run_lane_a = lambda *a, **k: gg.LaneAResult()
gg.detect_stranded_branches = lambda _: []
gg.detect_auto_memory_drift = lambda _: {}
gg.detect_unprofiled_people = lambda *a, **k: []
gg.read_batch_model = lambda: "test-model"
def review(*args):
    print("review:" + sid, flush=True)
    if mode == "block-review":
        sys.stdin.readline()
    return {"missing_links": [], "orphans": [{"note": str(note.relative_to(repo)), "rationale": sid}]}
gg.run_lane_b_headless = review
if mode in ("block-queue-replace", "block-state-replace"):
    original_replace = gg.os.replace
    target = "gardener-personal.md" if mode == "block-queue-replace" else "gardener-state.json"
    def pause_replace(source, destination):
        if Path(destination).name == target:
            print("before-replace:" + target, flush=True)
            sys.stdin.readline()
        return original_replace(source, destination)
    gg.os.replace = pause_replace
print("result:" + str(gg.run_worker(sid, repo)), flush=True)
'''


def _vault(tmp_path: Path) -> Path:
    (tmp_path / "personal").mkdir()
    (tmp_path / ".vault-context").write_text("personal")
    for sid in ("first", "second"):
        (tmp_path / "personal" / f"{sid}.md").write_text(f"note {sid}\n")
    return tmp_path


def _start(repo: Path, sid: str, mode: str = "normal") -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, "-B", "-c", WORKER, str(ENGINE), str(repo), sid, mode],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )


def _line(process: subprocess.Popen[str]) -> str:
    received: queue.Queue[str] = queue.Queue()
    threading.Thread(target=lambda: received.put(process.stdout.readline()), daemon=True).start()
    try:
        return received.get(timeout=10).strip()
    except queue.Empty:
        pytest.fail("child did not reach the controlled test boundary")


def _stop(process: subprocess.Popen[str]) -> None:
    if process.poll() is None:
        process.kill()
    process.communicate(timeout=10)


def _run(repo: Path, sid: str) -> str:
    process = _start(repo, sid)
    try:
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 0, stderr
        return stdout
    finally:
        _stop(process)


def test_competing_workers_do_not_overwrite_state_or_queue(tmp_path: Path) -> None:
    repo = _vault(tmp_path)
    first = _start(repo, "first", "block-review")
    try:
        assert _line(first) == "review:first"
        second_output = _run(repo, "second")
        assert "review:" not in second_output
        assert not (repo / ".brain/gardener-personal.md").exists()
        stdout, stderr = first.communicate(input="\n", timeout=10)
        assert first.returncode == 0, stderr
        assert "result:0" in stdout
        first_state = gg.load_state(repo)
        assert first_state["gardened_session_ids"] == ["first"]

        assert "review:second" in _run(repo, "second")
        state = gg.load_state(repo)
        assert state["gardened_session_ids"] == ["first", "second"]
        assert state["gardened"]["personal/first.md"] == first_state["gardened"]["personal/first.md"]
        assert "personal/second.md" in state["gardened"]
    finally:
        _stop(first)


def test_legacy_debounce_migrates_once_and_killed_worker_can_retry(tmp_path: Path) -> None:
    repo = _vault(tmp_path)
    original = {
        "gardened_session_ids": ["first", "old-complete"],
        "gardened": {"personal/older.md": "saved-hash"},
        "sweep_cursor": "saved-cursor", "last_gardened_commit": "saved-head",
        "last_run_ts": "saved-time", "last_applied_ts": "saved-apply",
    }
    gg.save_state(repo, original)
    queue_path = repo / ".brain/gardener-personal.md"
    queue_path.parent.mkdir()
    queue_path.write_text("pending proposals\n")
    child = _start(repo, "first", "block-review")
    try:
        assert _line(child) == "review:first"
        assert gg.load_state(repo) == {
            **original, "gardened_session_ids": [], "_completion_protocol": 1,
        }
        assert queue_path.read_text() == "pending proposals\n"
        child.kill()
        child.communicate(timeout=10)
        assert "review:first" in _run(repo, "first")
        completed = gg.load_state(repo)
        assert completed["gardened_session_ids"] == ["first"]
        assert completed["gardened"]["personal/older.md"] == "saved-hash"
        assert completed["last_applied_ts"] == "saved-apply"
        assert "review:" not in _run(repo, "first")
        assert gg.load_state(repo) == completed
    finally:
        _stop(child)


@pytest.mark.parametrize("boundary", ["queue", "state"])
def test_killed_publication_leaves_complete_files_and_retry_eligible(
    tmp_path: Path, boundary: str,
) -> None:
    repo = _vault(tmp_path)
    original = {"_completion_protocol": 1, "gardened_session_ids": [], "last_applied_ts": "preserved"}
    gg.save_state(repo, original)
    queue_path = repo / ".brain/gardener-personal.md"
    queue_path.parent.mkdir()
    queue_path.write_text("previous queue\n")
    child = _start(repo, "first", f"block-{boundary}-replace")
    try:
        assert _line(child) == "review:first"
        target = "gardener-personal.md" if boundary == "queue" else "gardener-state.json"
        assert _line(child) == f"before-replace:{target}"
        assert json.loads((repo / gg.STATE_FILE_REL).read_text()) == original
        if boundary == "queue":
            assert queue_path.read_text() == "previous queue\n"
        else:
            assert "personal/first.md" in queue_path.read_text()
        assert "done:" not in (repo / gg.GARDENER_LOG_REL).read_text()
        child.kill()
        child.communicate(timeout=10)
        assert "review:first" in _run(repo, "first")
        assert gg.load_state(repo)["gardened_session_ids"] == ["first"]
    finally:
        _stop(child)


def test_apply_mutators_coordinate_with_running_producer(tmp_path: Path) -> None:
    repo = _vault(tmp_path)
    child = _start(repo, "first", "block-review")
    try:
        assert _line(child) == "review:first"
        assert gg.acquire_apply_lock(repo, "apply") is False
        assert not (repo / gg.APPLY_LOCK_REL).exists()
        assert gg.mark_applied(repo) is False
        assert gg.release_apply_lock(repo, mark_applied=True) is False
        assert "last_applied_ts" not in gg.load_state(repo)
        stdout, stderr = child.communicate(input="\n", timeout=10)
        assert child.returncode == 0, stderr
        assert "result:0" in stdout

        assert gg.acquire_apply_lock(repo, "apply") is True
        assert gg.acquire_apply_lock(repo, "other") is False
        assert json.loads((repo / gg.APPLY_LOCK_REL).read_text())["session"] == "apply"
        state_before = gg.load_state(repo)
        queue_before = (repo / ".brain/gardener-personal.md").read_bytes()
        assert "review:" not in _run(repo, "second")
        assert gg.load_state(repo) == state_before
        assert (repo / ".brain/gardener-personal.md").read_bytes() == queue_before

        assert gg.release_apply_lock(repo, mark_applied=True) is True
        applied = gg.load_state(repo)["last_applied_ts"]
        assert not (repo / gg.APPLY_LOCK_REL).exists()
        assert "review:second" in _run(repo, "second")
        assert gg.load_state(repo)["last_applied_ts"] == applied
        assert gg.load_state(repo)["gardened_session_ids"] == ["first", "second"]
    finally:
        _stop(child)
