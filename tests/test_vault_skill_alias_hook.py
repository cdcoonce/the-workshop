"""Tests for the vault-skill-alias UserPromptSubmit hook.

Drives the hook as a real subprocess with JSON on stdin, following the pattern
in `test_suggest_handoff_on_context_hook.py`. The hook resolves its plugin root
from its own file location (`hooks/scripts/` -> plugin root), so most cases run
against a throwaway plugin tree built under `tmp_path`, with a copy of the real
hook script placed at the matching relative path. One case runs the real,
shipped script against the real `plugins/workbench` tree, so a change to actual
skill frontmatter (an alias renamed, a flag added or dropped) is caught here
too, not only in the synthetic fixture.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_HOOK = (
    REPO_ROOT / "plugins" / "workbench" / "hooks" / "scripts" / "vault-skill-alias.py"
)
REAL_PLUGIN_ROOT = REPO_ROOT / "plugins" / "workbench"


def run(hook_path: Path, payload) -> subprocess.CompletedProcess:
    stdin = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run(
        [sys.executable, str(hook_path)],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _skill(
    plugin_root: Path,
    slug: str,
    *,
    flagged: bool,
    alias: str | None,
    disable_value: str | None = None,
) -> None:
    lines = ["---", f"name: {slug}", "description: >"]
    body = f"  Run the {slug} workflow."
    if alias:
        body += f" Trigger when Charles invokes /{alias}, mentions /{alias}."
    lines.append(body)
    if disable_value is not None:
        lines.append(f"disable-model-invocation: {disable_value}")
    elif flagged:
        lines.append("disable-model-invocation: true")
    lines.append("---")
    lines.append("")
    lines.append(f"# {slug}")
    skill_dir = plugin_root / "skills" / slug
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def hook_tree(tmp_path: Path) -> tuple[Path, Path]:
    """A throwaway plugin tree with a copy of the real hook at the real relative path.

    Returns (hook_path, plugin_root).
    """
    plugin_root = tmp_path / "workbench"
    scripts_dir = plugin_root / "hooks" / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    hook_path = scripts_dir / "vault-skill-alias.py"
    hook_path.write_text(REAL_HOOK.read_text(encoding="utf-8"), encoding="utf-8")

    # Flagged, alias differs from slug.
    _skill(plugin_root, "vault-standup", flagged=True, alias="standup")
    # Flagged, alias equals slug -- must not be routed as an "alias".
    _skill(plugin_root, "vault-audit", flagged=True, alias="vault-audit")
    # Not flagged, alias phrase present -- must stay silent (teeth #4 guard).
    _skill(plugin_root, "vault-handoff", flagged=False, alias="handoff")
    # Not flagged, no alias phrase, slug shares a prefix with a real alias.
    _skill(plugin_root, "write-a-prd", flagged=False, alias=None)
    _skill(plugin_root, "vault-write", flagged=True, alias="write")
    # Explicit `disable-model-invocation: false` -- a truthy-string bug would
    # treat this non-empty value as flagged and wrongly route /falsy.
    _skill(plugin_root, "vault-falsy", flagged=False, alias="falsy", disable_value="false")

    return hook_path, plugin_root


class TestFailOpen:
    @pytest.mark.parametrize(
        "payload", ["", "not json", "{ broken", "[]", '"hello"', "null", "123"]
    )
    def test_malformed_stdin_no_ops(self, hook_tree, payload: str) -> None:
        hook_path, _ = hook_tree
        result = run(hook_path, payload)
        assert result.returncode == 0
        assert result.stdout == ""
        assert "Traceback" not in result.stderr

    def test_missing_prompt_field_no_ops(self, hook_tree) -> None:
        hook_path, _ = hook_tree
        result = run(hook_path, {"session_id": "s1"})
        assert result.returncode == 0
        assert result.stdout == ""

    def test_non_string_prompt_no_ops(self, hook_tree) -> None:
        hook_path, _ = hook_tree
        result = run(hook_path, {"prompt": 123})
        assert result.returncode == 0
        assert result.stdout == ""


class TestAliasRouting:
    def test_alias_with_trailing_args_names_the_skill_md(self, hook_tree) -> None:
        hook_path, plugin_root = hook_tree
        result = run(hook_path, {"prompt": "/standup --deep"})
        assert result.returncode == 0
        out = json.loads(result.stdout)
        hso = out["hookSpecificOutput"]
        assert hso["hookEventName"] == "UserPromptSubmit"
        expected_path = str(plugin_root / "skills" / "vault-standup" / "SKILL.md")
        assert expected_path in hso["additionalContext"]
        assert "/standup" in hso["additionalContext"]
        assert "vault-standup" in hso["additionalContext"]

    def test_real_slug_typed_directly_is_silent(self, hook_tree) -> None:
        """Typing the actual slug (even one whose alias equals its slug) needs
        no routing help -- it already works as a real slash command."""
        hook_path, _ = hook_tree
        result = run(hook_path, {"prompt": "/vault-standup"})
        assert result.returncode == 0
        assert result.stdout == ""

    def test_alias_equal_to_slug_typed_directly_is_silent(self, hook_tree) -> None:
        hook_path, _ = hook_tree
        result = run(hook_path, {"prompt": "/vault-audit"})
        assert result.returncode == 0
        assert result.stdout == ""

    def test_alias_not_at_start_of_prompt_is_silent(self, hook_tree) -> None:
        hook_path, _ = hook_tree
        result = run(hook_path, {"prompt": "please /standup"})
        assert result.returncode == 0
        assert result.stdout == ""

    def test_unknown_slash_command_is_silent(self, hook_tree) -> None:
        hook_path, _ = hook_tree
        result = run(hook_path, {"prompt": "/nonexistent"})
        assert result.returncode == 0
        assert result.stdout == ""

    def test_longer_slug_sharing_an_alias_prefix_is_silent(self, hook_tree) -> None:
        """`/write-a-prd` must not be mistaken for the `/write` alias."""
        hook_path, _ = hook_tree
        result = run(hook_path, {"prompt": "/write-a-prd"})
        assert result.returncode == 0
        assert result.stdout == ""

    def test_non_flagged_skills_alias_is_silent(self, hook_tree) -> None:
        """`vault-handoff` is not flagged, so its `/handoff` alias is a normal,
        already-model-invocable trigger -- nothing for this hook to add."""
        hook_path, _ = hook_tree
        result = run(hook_path, {"prompt": "/handoff"})
        assert result.returncode == 0
        assert result.stdout == ""

    def test_explicit_false_flag_is_silent(self, hook_tree) -> None:
        """`disable-model-invocation: false` is a non-empty string -- a naive
        truthiness check on it would wrongly treat `vault-falsy` as flagged and
        route `/falsy`. It must stay silent, same as any other non-flagged skill."""
        hook_path, _ = hook_tree
        result = run(hook_path, {"prompt": "/falsy"})
        assert result.returncode == 0
        assert result.stdout == ""


class TestRealPluginRoot:
    """Guard against drift in the actual shipped skill frontmatter."""

    def test_standup_alias_names_the_real_skill_md(self) -> None:
        result = run(REAL_HOOK, {"prompt": "/standup --deep"})
        assert result.returncode == 0
        out = json.loads(result.stdout)
        expected_path = str(REAL_PLUGIN_ROOT / "skills" / "vault-standup" / "SKILL.md")
        assert expected_path in out["hookSpecificOutput"]["additionalContext"]

    def test_vault_standup_slug_typed_directly_is_silent(self) -> None:
        result = run(REAL_HOOK, {"prompt": "/vault-standup"})
        assert result.returncode == 0
        assert result.stdout == ""

    def test_write_a_prd_is_silent(self) -> None:
        result = run(REAL_HOOK, {"prompt": "/write-a-prd"})
        assert result.returncode == 0
        assert result.stdout == ""

    def test_handoff_alias_is_silent_because_vault_handoff_is_not_flagged(self) -> None:
        result = run(REAL_HOOK, {"prompt": "/handoff"})
        assert result.returncode == 0
        assert result.stdout == ""

    def test_hook_is_executable_and_present(self) -> None:
        assert REAL_HOOK.exists(), f"{REAL_HOOK} is missing"
        assert shutil.which(sys.executable), "python is required to run this hook"
