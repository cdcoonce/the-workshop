"""Tests for no_model_calls_check: no module under evals/ may call a model
or the claude CLI.
"""

from __future__ import annotations

from pathlib import Path

from no_model_calls_check import check_file

_REPO_ROOT = Path(__file__).resolve().parents[3]
_EVALS_ROOT = _REPO_ROOT / "evals"


def test_committed_evals_tree_has_no_model_calls():
    offending = {
        str(path.relative_to(_REPO_ROOT)): violations
        for path in sorted(_EVALS_ROOT.rglob("*.py"))
        if (violations := check_file(path))
    }
    assert offending == {}


def test_anthropic_import_is_flagged(tmp_path):
    module = tmp_path / "planted_anthropic_import.py"
    module.write_text("import anthropic\n", encoding="utf-8")
    assert check_file(module) == ["imports model client 'anthropic'"]


def test_claude_agent_sdk_import_is_flagged(tmp_path):
    module = tmp_path / "planted_sdk_import.py"
    module.write_text("from claude_agent_sdk import query\n", encoding="utf-8")
    assert check_file(module) == ["imports model client 'claude_agent_sdk'"]


def test_claude_cli_invocation_is_flagged(tmp_path):
    module = tmp_path / "planted_cli_call.py"
    module.write_text(
        "import subprocess\nsubprocess.run(['claude', 'mcp', 'status'])\n",
        encoding="utf-8",
    )
    assert check_file(module) == ["invokes the claude CLI: 'claude'"]


def test_claude_cli_invocation_via_os_is_flagged(tmp_path):
    module = tmp_path / "planted_os_call.py"
    module.write_text("import os\nos.system('claude --version')\n", encoding="utf-8")
    assert check_file(module) == ["invokes the claude CLI: 'claude --version'"]


def test_unrelated_imports_and_calls_are_not_flagged(tmp_path):
    module = tmp_path / "clean_module.py"
    module.write_text(
        "import json\nimport subprocess\nsubprocess.run(['git', 'status'])\n",
        encoding="utf-8",
    )
    assert check_file(module) == []
