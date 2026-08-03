"""Tests for the remind-skill-announce PostToolUse hook."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_PATH = REPO_ROOT / "core" / "hooks" / "remind-skill-announce.py"
SETTINGS_BASE_PATH = REPO_ROOT / "core" / "settings-base.json"


def run(payload) -> subprocess.CompletedProcess[str]:
    stdin = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.mark.parametrize("payload", ["", "not json", "{ broken"])
def test_fails_open_on_malformed_stdin(payload: str) -> None:
    result = run(payload)
    assert result.returncode == 0
    assert "Traceback" not in result.stderr


def test_wrong_tool_name_no_ops() -> None:
    """Defensive: a matcher-less host (e.g. Codex) could still deliver this."""
    result = run({"tool_name": "Edit", "tool_input": {"skill": "vault-sync"}})
    assert result.returncode == 0
    assert result.stdout == ""


def test_missing_tool_input_no_ops() -> None:
    result = run({"tool_name": "Skill"})
    assert result.returncode == 0
    assert result.stdout == ""


def test_missing_skill_field_no_ops() -> None:
    result = run({"tool_name": "Skill", "tool_input": {"args": "foo"}})
    assert result.returncode == 0
    assert result.stdout == ""


def test_blank_skill_field_no_ops() -> None:
    result = run({"tool_name": "Skill", "tool_input": {"skill": "   "}})
    assert result.returncode == 0
    assert result.stdout == ""


def test_never_blocks() -> None:
    result = run({"tool_name": "Skill", "tool_input": {"skill": "vault-sync"}})
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert "decision" not in payload


def test_emits_additional_context_naming_the_skill() -> None:
    result = run({"tool_name": "Skill", "tool_input": {"skill": "vault-sync"}})
    payload = json.loads(result.stdout)
    output = payload["hookSpecificOutput"]
    assert output["hookEventName"] == "PostToolUse"
    assert "vault-sync" in output["additionalContext"]
    assert "Announce Convention" in output["additionalContext"]


def test_reminder_names_terse_persona_exemption() -> None:
    result = run({"tool_name": "Skill", "tool_input": {"skill": "commit"}})
    payload = json.loads(result.stdout)
    context = payload["hookSpecificOutput"]["additionalContext"]
    assert "terse" in context.lower()
    assert "preamble" in context.lower()


def test_strips_surrounding_whitespace_from_skill_name() -> None:
    result = run({"tool_name": "Skill", "tool_input": {"skill": "  tdd  "}})
    payload = json.loads(result.stdout)
    context = payload["hookSpecificOutput"]["additionalContext"]
    assert '"tdd"' in context
    assert '"  tdd  "' not in context


def test_post_tool_use_matcher_is_dual_cased_and_scoped_to_skill_tool() -> None:
    """The registered PostToolUse matcher must fire on Cortex's lowercase tool
    ID as well as Claude Code's PascalCase one, without over-matching an
    unrelated tool whose name happens to contain "skill" as a substring."""
    settings = json.loads(SETTINGS_BASE_PATH.read_text())
    matcher = settings["hooks"]["PostToolUse"][0]["matcher"]

    pattern = re.compile(matcher)
    assert pattern.fullmatch("Skill")
    assert pattern.fullmatch("skill")
    assert not pattern.fullmatch("skill_search")
