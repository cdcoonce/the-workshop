"""Fixtures shared by the A3 case tests.

Lives beside the tests it serves (``A3/case_tests/``), never in
``evals/_harness/tests/conftest.py``, which #991 owns.

Synthetic transcripts keep the real Claude Code subagent envelope shape: JSONL
lines with a top-level ``type``; a tool call is a ``tool_use`` block (``type``,
``id``, ``name``, ``input``) inside an ``assistant`` line's ``message.content[]``;
its result is a ``tool_result`` block (``tool_use_id``, ``is_error``,
``content``) inside a later ``user`` line's ``message.content[]``; assistant prose
is a ``text`` block. Order is file line order.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tomllib
from pathlib import Path

import pytest

from evals._harness.dispatch import Evidence
from evals._harness.transcript import parse_transcript

CASE_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = CASE_DIR.parents[2]
ROSTERED_SKILL = CASE_DIR.parent.name
OTHER_SKILL = "using-workflow"

ENVELOPE_TYPES = {"user", "assistant", "attachment"}


@pytest.fixture(scope="session")
def case_dir() -> Path:
    return CASE_DIR


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def rostered_skill() -> str:
    return ROSTERED_SKILL


@pytest.fixture(scope="session")
def case_toml() -> dict:
    return tomllib.loads((CASE_DIR / "case.toml").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def predicates():
    """``predicates.py`` loaded by file path (the way ``dispatch`` loads it), no bytecode cache."""
    spec = importlib.util.spec_from_file_location("a3_predicates_under_test", CASE_DIR / "predicates.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


@pytest.fixture
def write_transcript(tmp_path):
    """Write a synthetic transcript from steps and return its path.

    Steps: ``("prompt", text)``, ``("say", text)``, ``("skill", name)``,
    ``("tool", name, input)`` and ``("attachment",)``. Every tool call gets its
    result in the next ``user`` line; a ``Skill`` call also gets the skill-body
    ``user`` line that follows a real skill launch.
    """
    counter = {"files": 0}

    def build(steps: list[tuple]) -> Path:
        lines: list[dict] = []

        def stamp(line: dict) -> dict:
            line["timestamp"] = f"2026-10-01T10:00:{len(lines) + 1:02d}.000Z"
            return line

        def assistant(content: list[dict]) -> None:
            lines.append(
                stamp(
                    {
                        "type": "assistant",
                        "message": {"role": "assistant", "model": "claude-sonnet-5-5", "content": content},
                    }
                )
            )

        def user(content: list[dict] | str) -> None:
            lines.append(stamp({"type": "user", "message": {"role": "user", "content": content}}))

        def call(name: str, tool_input: dict, result: str) -> None:
            tool_id = f"toolu_{len(lines):04d}"
            assistant([{"type": "tool_use", "id": tool_id, "name": name, "input": tool_input}])
            user([{"type": "tool_result", "tool_use_id": tool_id, "content": result, "is_error": False}])

        for step in steps:
            kind = step[0]
            if kind == "prompt":
                user(step[1])
            elif kind == "say":
                assistant([{"type": "text", "text": step[1]}])
            elif kind == "skill":
                call("Skill", {"skill": step[1]}, f"Launching skill: {step[1]}")
                user([{"type": "text", "text": f"Base directory for this skill: /skills/{step[1]}"}])
            elif kind == "tool":
                call(step[1], step[2], "ok")
            elif kind == "attachment":
                lines.append(stamp({"type": "attachment", "attachment": {"type": "deferred_tools_delta"}}))
            else:
                raise AssertionError(f"unknown step {kind!r}")

        counter["files"] += 1
        path = tmp_path / f"synthetic-{counter['files']}.jsonl"
        path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")
        return path

    return build


@pytest.fixture
def parse(write_transcript):
    """Build and parse a synthetic transcript in one step; it must parse as complete."""

    def run(steps: list[tuple]):
        transcript = parse_transcript(write_transcript(steps))
        assert transcript.status == "complete"
        return transcript

    return run


@pytest.fixture
def evidence_for():
    """Build the ``Evidence`` a scorer receives from parsed transcripts."""

    def build(*transcripts) -> Evidence:
        return Evidence(transcripts=list(transcripts), findings=[], workdir=None, end_state={})

    return build
