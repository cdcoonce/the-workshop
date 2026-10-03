"""SessionStart may resume only the current session's own notebook (#111)."""

from __future__ import annotations

import importlib.util
import io
import json
import os
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest

from notebook_core import NOTEBOOK_SKELETON

ENGINE_DIR = Path(__file__).resolve().parent.parent / "engine"
NOW = 1_700_000_000.0
StartSession = Callable[[dict[str, object]], str]


def _write_digest(root: Path, name: str, text: str, age: float) -> Path:
    path = root / ".brain" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    os.utime(path, (NOW - age, NOW - age))
    return path


@pytest.fixture
def start_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> StartSession:
    """Exercise engine output in a temporary vault, with remote sync replaced."""
    spec = importlib.util.spec_from_file_location("session_start_ownership", ENGINE_DIR / "session-start.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path / ".vault").mkdir()
    (tmp_path / ".vault" / "vault.json").write_text("{}")
    (tmp_path / ".vault-context").write_text("personal")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr(module.time, "time", lambda: NOW)
    monkeypatch.setattr(module, "pull", lambda root: SimpleNamespace(success=True, message="test sync"))
    # The unrelated context summary can call git; the digest loader below it
    # remains real, including ownership, timestamps, skeleton checks and output.
    monkeypatch.setattr(module, "load_context", lambda root: SimpleNamespace(summary="test summary"))
    _write_digest(tmp_path, "handoff-personal.md", "CURATED HANDOFF", age=3600)

    def run(event: dict[str, object]) -> str:
        monkeypatch.setattr(module.sys, "stdin", io.StringIO(json.dumps(event)))
        assert module.main() == 0
        return json.loads(capsys.readouterr().out)["hookSpecificOutput"]["additionalContext"]

    return run


@pytest.mark.parametrize("source", ["startup", "resume", "clear", "compact"])
def test_own_notebook_wins_over_fresher_foreign_notebook(
    tmp_path: Path, start_session: StartSession, source: str
) -> None:
    _write_digest(tmp_path, "notebook-personal-own.md", "OWN SESSION", age=60)
    _write_digest(tmp_path, "notebook-personal-foreign.md", "FOREIGN SESSION", age=30)

    context = start_session({"session_id": "own", "source": source})

    assert "OWN SESSION" in context
    assert "FOREIGN SESSION" not in context
    assert "CURATED HANDOFF" not in context


@pytest.mark.parametrize("event", [
    {}, {"session_id": ""}, {"session_id": None}, {"session_id": 17},
    {"session_id": []}, {"session_id": {}}, {"session_id": "nested/id"},
    {"session_id": "bad\\id"},
])
def test_missing_or_invalid_identity_uses_handoff(
    tmp_path: Path, start_session: StartSession, event: dict[str, object]
) -> None:
    # A notebook whose filename happens to stringify an invalid payload is not
    # proof of ownership. A missing identity must not select the empty-ID file.
    identity = event.get("session_id", "")
    _write_digest(tmp_path, f"notebook-personal-{identity}.md", "UNOWNED NOTEBOOK", age=30)

    context = start_session(event)

    assert "CURATED HANDOFF" in context
    assert "UNOWNED NOTEBOOK" not in context


def test_clear_with_new_identity_does_not_guess_predecessor(
    tmp_path: Path, start_session: StartSession
) -> None:
    _write_digest(tmp_path, "notebook-personal-previous.md", "PREVIOUS SESSION", age=30)

    context = start_session({"session_id": "new-session", "source": "clear"})

    assert "CURATED HANDOFF" in context
    assert "PREVIOUS SESSION" not in context


def test_same_identity_from_other_context_does_not_resume(
    tmp_path: Path, start_session: StartSession
) -> None:
    _write_digest(tmp_path, "notebook-work-own.md", "WORK CONTEXT", age=30)

    context = start_session({"session_id": "own", "source": "resume"})

    assert "CURATED HANDOFF" in context
    assert "WORK CONTEXT" not in context


@pytest.mark.parametrize("age, expected", [(6 * 3600, "OWN SESSION"), (6 * 3600 + 1, "CURATED HANDOFF")])
def test_notebook_six_hour_freshness_boundary(
    tmp_path: Path, start_session: StartSession, age: int, expected: str
) -> None:
    # An even older handoff isolates the age ceiling from the newer-than test.
    _write_digest(tmp_path, "handoff-personal.md", "CURATED HANDOFF", age=24 * 3600)
    _write_digest(tmp_path, "notebook-personal-own.md", "OWN SESSION", age=age)

    context = start_session({"session_id": "own"})

    assert expected in context
    assert ("OWN SESSION" in context) != ("CURATED HANDOFF" in context)


@pytest.mark.parametrize("age", [3600, 3601])
def test_notebook_must_be_strictly_newer_than_handoff(
    tmp_path: Path, start_session: StartSession, age: int
) -> None:
    _write_digest(tmp_path, "notebook-personal-own.md", "OWN SESSION", age=age)

    context = start_session({"session_id": "own"})

    assert "CURATED HANDOFF" in context
    assert "OWN SESSION" not in context


@pytest.mark.parametrize("placeholders", [3, 4])
def test_unfilled_own_notebook_uses_handoff(
    tmp_path: Path, start_session: StartSession, placeholders: int
) -> None:
    skeleton = NOTEBOOK_SKELETON.format(context_title="Personal", stamp="today", sid="own")
    if placeholders == 3:
        skeleton = skeleton.replace("(files or notes created or edited this session)", "one note")
    _write_digest(tmp_path, "notebook-personal-own.md", skeleton, age=30)
    _write_digest(tmp_path, "notebook-personal-foreign.md", "FOREIGN SESSION", age=10)

    context = start_session({"session_id": "own"})

    assert "CURATED HANDOFF" in context
    assert "FOREIGN SESSION" not in context
    assert "Session Notebook" not in context


def test_unreadable_own_notebook_uses_handoff(
    tmp_path: Path, start_session: StartSession
) -> None:
    notebook = tmp_path / ".brain" / "notebook-personal-own.md"
    notebook.mkdir()
    os.utime(notebook, (NOW - 30, NOW - 30))

    context = start_session({"session_id": "own"})

    assert "CURATED HANDOFF" in context
