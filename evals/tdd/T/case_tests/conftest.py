"""Shared fixtures for the tdd/T case tests.

``predicates.py`` is loaded by file path (the way ``dispatch`` loads it), because
``evals/tdd/T`` is not an importable package. Synthetic transcripts keep the real
Claude Code subagent envelope shape: a ``tool_use`` block inside an ``assistant``
line's ``message.content[]`` and its ``tool_result`` block inside a later ``user``
line's ``message.content[]``.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from evals._harness.dispatch import Evidence
from evals._harness.transcript import parse_transcript

CASE_DIR = Path(__file__).resolve().parents[1]
TRANSCRIPTS = Path(__file__).resolve().parent / "transcripts"
TAUTOLOGY = "assert subtotal_cents(items) == subtotal_cents(items)"

PASSED = ".....\n5 passed in 0.01s\n"
FAILED = (
    "F....\n"
    "=========================== short test summary info ============================\n"
    "FAILED tests/test_cart.py::test_bulk_line_gets_fifteen_percent_off - assert 3330 == 2831\n"
    "1 failed, 4 passed in 0.03s\n"
)


def _load_predicates():
    spec = importlib.util.spec_from_file_location("tdd_t_predicates_under_test", CASE_DIR / "predicates.py")
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


@pytest.fixture(scope="session")
def predicates():
    return _load_predicates()


@pytest.fixture
def load_transcript():
    """Parse one committed synthetic transcript by file stem."""

    def load(stem: str):
        path = TRANSCRIPTS / f"{stem}.jsonl"
        transcript = parse_transcript(path)
        assert transcript.status == "complete", stem
        return transcript

    return load


@pytest.fixture
def make_transcript(tmp_path):
    """Write a synthetic transcript from steps and return its path.

    Steps: ``("say", text)``, ``("read", path)``, ``("edit", path, old, new)``,
    ``("write", path, content)``, ``("notebook", path)``, ``("pytest", output)``,
    ``("bash", command, output)`` and ``("tool", name, input, result)``.
    Timestamps count up from a fixed instant unless ``timestamps=False``.
    """
    counter = {"files": 0}

    def build(steps: list[tuple], *, timestamps: bool = True) -> Path:
        lines: list[dict] = []
        clock = {"n": 0}

        def envelope(kind: str, message: dict) -> dict:
            line = {"type": kind, "message": message}
            if timestamps:
                clock["n"] += 1
                line["timestamp"] = f"2026-09-30T10:00:{clock['n']:02d}.000Z"
            return line

        def call(name: str, tool_input: dict, result: str) -> None:
            tool_id = f"toolu_{len(lines):04d}"
            lines.append(
                envelope(
                    "assistant",
                    {
                        "role": "assistant",
                        "model": "claude-sonnet-5-5",
                        "content": [{"type": "tool_use", "id": tool_id, "name": name, "input": tool_input}],
                    },
                )
            )
            lines.append(
                envelope(
                    "user",
                    {
                        "role": "user",
                        "content": [
                            {"type": "tool_result", "tool_use_id": tool_id, "content": result, "is_error": False}
                        ],
                    },
                )
            )

        for step in steps:
            kind = step[0]
            if kind == "say":
                lines.append(
                    envelope(
                        "assistant",
                        {
                            "role": "assistant",
                            "model": "claude-sonnet-5-5",
                            "content": [{"type": "text", "text": step[1]}],
                        },
                    )
                )
            elif kind == "read":
                call("Read", {"file_path": step[1]}, "(contents)")
            elif kind == "edit":
                call("Edit", {"file_path": step[1], "old_string": step[2], "new_string": step[3]}, "updated")
            elif kind == "write":
                call("Write", {"file_path": step[1], "content": step[2]}, "created")
            elif kind == "notebook":
                call("NotebookEdit", {"notebook_path": step[1], "new_source": "x"}, "updated")
            elif kind == "pytest":
                call("Bash", {"command": "uv run pytest"}, step[1])
            elif kind == "bash":
                call("Bash", {"command": step[1]}, step[2])
            elif kind == "tool":
                call(step[1], step[2], step[3])
            else:
                raise AssertionError(f"unknown step {kind!r}")

        counter["files"] += 1
        path = tmp_path / f"synthetic-{counter['files']}.jsonl"
        path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")
        return path

    return build


@pytest.fixture
def parse(make_transcript):
    """Build and parse a synthetic transcript in one step."""

    def run(steps: list[tuple], **kwargs):
        return parse_transcript(make_transcript(steps, **kwargs))

    return run


def tests_tree(*, tautology_present: bool) -> dict[str, str]:
    """The final ``tests/`` the way ``tests-final.json`` records it."""
    planted = f"    {TAUTOLOGY}\n" if tautology_present else "    assert subtotal_cents(items) == 1500\n"
    return {
        "tests/test_cart.py": "def test_subtotal_adds_up_line_items():\n    items = []\n" + planted,
        "tests/test_checkout.py": "def test_order_total_of_empty_cart_is_zero():\n    assert order_total_cents([]) == 0\n",
    }


@pytest.fixture
def make_snapshot():
    """Build an end-state mapping in the formats ``end_state`` writes.

    A ``None`` exit code leaves that file out entirely. ``src_changed`` takes paths
    (or ``{"path", "change"}`` objects); ``edited`` is the edit-tool audit record,
    which no scorer reads. ``tautology_present`` shapes the default ``tests-final.json``;
    ``tests_final`` replaces it outright.
    """

    def build(
        *,
        final_exit: int | None = 0,
        reverted_exit: int | None = 1,
        edited: list | None = None,
        src_changed: list | None = None,
        tautology_present: bool = False,
        tests_final: dict | None = None,
    ) -> dict:
        if edited is None:
            edited = [
                {"path": "tests/test_cart.py", "timestamp": "2026-09-30T10:00:05.000Z"},
                {"path": "src/shop/cart.py", "timestamp": "2026-09-30T10:00:15.000Z"},
            ]
        if src_changed is None:
            src_changed = ["src/shop/cart.py"]
        changed = [
            entry if isinstance(entry, dict) else {"path": entry, "change": "changed"} for entry in src_changed
        ]
        if tests_final is None:
            tests_final = tests_tree(tautology_present=tautology_present)
        result: dict[str, str] = {
            "edited-paths.json": json.dumps(edited),
            "src-changed.json": json.dumps(changed),
            "tests-final.json": json.dumps(tests_final),
        }
        if final_exit is not None:
            result["pytest-final.txt"] = f"{PASSED}exit={final_exit}\n"
        if reverted_exit is not None:
            result["pytest-src-reverted.txt"] = f"{FAILED}exit={reverted_exit}\n"
        return result

    return build


@pytest.fixture
def make_evidence():
    """Build the ``Evidence`` a scorer receives."""

    def build(transcripts, end_state, workdir=None) -> Evidence:
        return Evidence(transcripts=list(transcripts), findings=[], workdir=workdir, end_state=end_state)

    return build
