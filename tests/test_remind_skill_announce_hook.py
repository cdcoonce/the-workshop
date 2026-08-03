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
    unrelated tool whose name happens to contain "skill" as a substring.

    The negative assertions use re.search because that is the semantics under
    which a matcher can over-match at all; re.fullmatch is vacuously true for
    any pattern that full-matches only the two literals. Whether the host
    actually searches or anchors is unresolved (#606) — the anchored matcher
    is correct either way, which is why this does not depend on the answer."""
    settings = json.loads(SETTINGS_BASE_PATH.read_text())
    matcher = settings["hooks"]["PostToolUse"][0]["matcher"]

    pattern = re.compile(matcher)
    assert pattern.search("Skill")
    assert pattern.search("skill")
    assert not pattern.search("skill_search")
    assert not pattern.search("search_skills")


def test_pre_tool_use_matcher_is_left_unanchored_on_purpose() -> None:
    """The PreToolUse matcher gates `protect-files.py`, a guard — so it is
    deliberately NOT anchored, unlike the PostToolUse reminder.

    For a guard the two failure directions are not symmetric: over-matching
    costs a no-op invocation, under-matching silently lets a write through.
    If the host searches rather than anchors, the unanchored form also covers
    tool names that merely contain a branch — an MCP tool such as
    `mcp__server__write_file`, say. Anchoring would drop those. Whether the
    host anchors is unresolved (#606), so the guard stays wide until it is.
    """
    settings = json.loads(SETTINGS_BASE_PATH.read_text())
    matcher = settings["hooks"]["PreToolUse"][0]["matcher"]

    assert not matcher.startswith("^"), (
        "PreToolUse gates a guard; anchoring it can only narrow what is "
        "protected. See #606."
    )

    pattern = re.compile(matcher)
    assert pattern.search("Edit")
    assert pattern.search("edit")
    assert pattern.search("mcp__server__write_file")
