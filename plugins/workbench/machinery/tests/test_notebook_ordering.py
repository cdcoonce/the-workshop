"""Notebook persistence contracts, exercised without live model calls."""

from __future__ import annotations

import importlib.util
import io
import json
import multiprocessing
import os
import sys
from pathlib import Path

import pytest

ENGINE = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(ENGINE))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ENGINE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _transcript(path: Path, label: str) -> None:
    entries = [
        {"type": "user", "message": {"content": f"{label} " * 60}},
        {"type": "assistant", "message": {"content": f"answer {label} " * 60}},
    ]
    path.write_text("\n".join(json.dumps(entry) for entry in entries), encoding="utf-8")


def _worker(root: str, kind: str, entered, release, finished) -> None:
    worker = _load("notebook-distill")

    def fake_distill(prompt: str, model: str) -> str:
        entered.set()
        if kind == "first":
            if not release.wait(10):
                raise RuntimeError("test did not release first worker")
            return "## Established\nfirst durable fact"
        prior = "first durable fact\n" if "first durable fact" in prompt else ""
        latest = "second durable fact" if "second-turn" in prompt else "STALE TRANSCRIPT"
        return f"## Established\n{prior}{latest}"

    worker.distill = fake_distill
    worker.read_batch_model = lambda: "test-model"
    worker.sys.argv = ["notebook-distill.py", str(Path(root) / "turns.jsonl"), "sess-1", root]
    worker.main()
    finished.set()


def test_overlapping_workers_merge_latest_notebook_and_transcript(tmp_path: Path) -> None:
    """A slow earlier result must not overwrite a later turn's durable state."""
    (tmp_path / ".vault-context").write_text("personal\n")
    _transcript(tmp_path / "turns.jsonl", "first-turn")
    ctx = multiprocessing.get_context("spawn")
    first_entered, second_entered = ctx.Event(), ctx.Event()
    release, first_done, second_done = ctx.Event(), ctx.Event(), ctx.Event()
    first = ctx.Process(target=_worker, args=(str(tmp_path), "first", first_entered, release, first_done))
    second = ctx.Process(target=_worker, args=(str(tmp_path), "second", second_entered, release, second_done))
    try:
        first.start()
        assert first_entered.wait(10)
        _transcript(tmp_path / "turns.jsonl", "second-turn")
        second.start()
        # Before the fix the second worker finishes while the first is blocked;
        # a serialized worker instead waits and rereads the first worker's output.
        second_done.wait(0.5)
        release.set()
        first.join(10)
        second.join(10)
        assert first.exitcode == second.exitcode == 0
        notebook = (tmp_path / ".brain" / "notebook-personal-sess-1.md").read_text()
        assert "first durable fact" in notebook
        assert "second durable fact" in notebook
        assert "STALE TRANSCRIPT" not in notebook
    finally:
        release.set()
        for process in (first, second):
            if process.pid is not None:
                if process.is_alive():
                    process.terminate()
                process.join(10)


@pytest.fixture
def worker(tmp_path: Path, monkeypatch):
    module = _load("notebook-distill")
    (tmp_path / ".vault-context").write_text("personal\n")
    _transcript(tmp_path / "turns.jsonl", "durable-turn")
    monkeypatch.setattr(module, "read_batch_model", lambda: "test-model")
    monkeypatch.setattr(module.sys, "argv", ["worker", str(tmp_path / "turns.jsonl"), "sess-1", str(tmp_path)])
    return module


def test_duplicate_snapshot_is_distilled_once(tmp_path: Path, worker, monkeypatch) -> None:
    prompts = []

    def fake_distill(prompt: str, model: str) -> str:
        prompts.append(prompt)
        return "## Established\nA captured decision"

    monkeypatch.setattr(worker, "distill", fake_distill)
    assert worker.main() == 0
    assert worker.main() == 0
    assert len(prompts) == 1


def test_replace_failure_preserves_base_and_does_not_mark_turn_done(tmp_path: Path, worker, monkeypatch) -> None:
    notebook = tmp_path / ".brain" / "notebook-personal-sess-1.md"
    notebook.parent.mkdir()
    notebook.write_text("Existing decision\n")
    prompts = []

    def fake_distill(prompt: str, model: str) -> str:
        prompts.append(prompt)
        return "## Established\nMerged decision"

    def reject_replace(source, destination) -> None:
        raise OSError("simulated replacement failure")

    monkeypatch.setattr(worker, "distill", fake_distill)
    real_replace = worker.os.replace
    monkeypatch.setattr(worker.os, "replace", reject_replace)
    with pytest.raises(OSError, match="replacement failure"):
        worker.main()
    assert notebook.read_text() == "Existing decision\n"
    assert list(notebook.parent.iterdir()) == [notebook]
    monkeypatch.setattr(worker.os, "replace", real_replace)
    assert worker.main() == 0
    assert "Merged decision" in notebook.read_text()
    assert len(prompts) == 2


def test_external_edit_during_distill_is_preserved_and_retried(tmp_path: Path, worker, monkeypatch) -> None:
    notebook = tmp_path / ".brain" / "notebook-personal-sess-1.md"
    notebook.parent.mkdir()
    notebook.write_text("Original decision\n")

    def edit_during_distill(prompt: str, model: str) -> str:
        notebook.write_text("Owner correction\n")
        return "## Established\nOutdated result"

    monkeypatch.setattr(worker, "distill", edit_during_distill)
    assert worker.main() == 0
    assert notebook.read_text() == "Owner correction\n"
    prompts = []

    def retry(prompt: str, model: str) -> str:
        prompts.append(prompt)
        return "## Established\nOwner correction and latest turn"

    monkeypatch.setattr(worker, "distill", retry)
    assert worker.main() == 0
    assert len(prompts) == 1
    assert "Owner correction" in prompts[0]


def test_unpromoted_old_notebook_is_retained(tmp_path: Path, worker, monkeypatch) -> None:
    old_notebook = tmp_path / ".brain" / "notebook-personal-previous.md"
    old_notebook.parent.mkdir()
    old_notebook.write_text("Only copy of an unpromoted decision\n")
    os.utime(old_notebook, (1, 1))
    monkeypatch.setattr(worker, "distill", lambda prompt, model: "## Now\nNew session")
    assert worker.main() == 0
    assert old_notebook.exists()
    assert old_notebook.read_text() == "Only copy of an unpromoted decision\n"
    assert "retained" in (tmp_path / ".claude" / "data" / "notebook.log").read_text()


def test_stub_does_not_clobber_a_concurrent_writer(tmp_path: Path, monkeypatch) -> None:
    update = _load("notebook-update")
    notebook = tmp_path / ".brain" / "notebook-personal-sess-1.md"
    original_open = Path.open
    raced = False

    def racing_open(path, mode="r", *args, **kwargs):
        nonlocal raced
        if path == notebook and ("w" in mode or "x" in mode) and not raced:
            raced = True
            with original_open(path, "w", encoding="utf-8") as existing:
                existing.write("Already enriched by another worker\n")
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", racing_open)
    update.ensure_stub(tmp_path, "personal", "sess-1")
    assert raced
    assert notebook.read_text() == "Already enriched by another worker\n"


@pytest.mark.parametrize("identity", ["", None, 42, "../escape", "bad\\id", "bad\0id"])
def test_writers_reject_unowned_session_ids(tmp_path: Path, worker, monkeypatch, identity) -> None:
    update = _load("notebook-update")
    update.ensure_stub(tmp_path, "personal", identity)
    monkeypatch.setattr(worker.sys, "argv", ["worker", str(tmp_path / "turns.jsonl"), identity, str(tmp_path)])
    monkeypatch.setattr(worker, "distill", lambda *args: pytest.fail("invalid identity reached model"))
    assert worker.main() == 0

    payload = {"session_id": identity, "transcript_path": str(tmp_path / "turns.jsonl")}
    monkeypatch.setattr(update.sys, "stdin", io.StringIO(json.dumps(payload)))
    monkeypatch.setattr(update, "find_vault_root_from_env", lambda: tmp_path)
    monkeypatch.setattr(update.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("invalid identity spawned worker"))
    assert update.main() == 0
    assert not (tmp_path / ".brain").exists()
