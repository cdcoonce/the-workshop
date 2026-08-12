"""Tests for notebook-distill.py's headless-model sourcing (#431).

The hyphenated hook file is loaded directly via importlib (the module name is
independent of the file path). Only ``distill()`` and ``main()``'s model wiring
are covered here — the pure transcript/prompt helpers live in notebook_core.py
and are tested in test_notebook_core.py.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess as _sp
import sys
from pathlib import Path

_ENGINE_DIR = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(_ENGINE_DIR))

_spec = importlib.util.spec_from_file_location(
    "notebook_distill", _ENGINE_DIR / "notebook-distill.py"
)
nd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(nd)

import vault_utils  # noqa: E402


def _capture_claude_argv(monkeypatch, captured):
    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        return _sp.CompletedProcess(argv, 0, stdout="updated notebook", stderr="")

    monkeypatch.setattr(nd.subprocess, "run", fake_run)


def _write_transcript(path: Path) -> None:
    long_text = "x" * 250
    records = [
        {"type": "user", "message": {"role": "user", "content": long_text}},
        {"type": "assistant", "message": {"role": "assistant", "content": long_text}},
    ]
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


def test_distill_passes_model_to_claude_argv(monkeypatch):
    captured = {}
    _capture_claude_argv(monkeypatch, captured)
    result = nd.distill("prompt text", "claude-opus-5")
    assert captured["argv"] == ["claude", "-p", "--model", "claude-opus-5"]
    assert result == "updated notebook"


def test_main_uses_custom_owner_model(tmp_path, monkeypatch, owner_scope):
    transcript = tmp_path / "transcript.jsonl"
    _write_transcript(transcript)
    owner_scope(BATCH_MODEL="claude-opus-5")

    captured = {}
    _capture_claude_argv(monkeypatch, captured)
    monkeypatch.setattr(
        nd.sys, "argv", ["notebook-distill.py", str(transcript), "sess-1", str(tmp_path)]
    )
    assert nd.main() == 0
    assert captured["argv"] == ["claude", "-p", "--model", "claude-opus-5"]


def test_main_falls_back_when_owner_value_absent(tmp_path, monkeypatch, owner_scope):
    transcript = tmp_path / "transcript.jsonl"
    _write_transcript(transcript)
    owner_scope(TASKS_DIR="custom/tasks")  # a config defining no BATCH_MODEL

    captured = {}
    _capture_claude_argv(monkeypatch, captured)
    monkeypatch.setattr(
        nd.sys, "argv", ["notebook-distill.py", str(transcript), "sess-2", str(tmp_path)]
    )
    assert nd.main() == 0
    assert captured["argv"] == ["claude", "-p", "--model", vault_utils.DEFAULT_BATCH_MODEL]
