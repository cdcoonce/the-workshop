"""Exit-code contract tests for the validate-write.py PostToolUse hook.

The hook is invoked by Claude Code as a subprocess with a hook-event JSON on
stdin. Its documented contract is:
    exit 0 — validation passed (or file excluded / no-op)
    exit 1 — blocking validation errors
    exit 2 — non-blocking warnings only (e.g. YAML parse errors)

These tests drive the script exactly that way (subprocess + stdin) so the
stdin parsing and exit-code mapping are covered, not just the underlying
frontmatter_engine.validate (which is tested separately). Tests are hermetic:
they build a throwaway vault under tmp_path with its own CLAUDE.md root.
"""

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "engine"
HOOK = SCRIPTS_DIR / "validate-write.py"

# validate-write.py has a hyphen, so it can't be `import`ed by name — load it by
# path, same pattern used for the other hyphenated hook scripts in this test
# suite (see test_session_stop_integration.py). Registered in sys.modules so
# string-based `patch("validate_write.x")` targets resolve like a real import.
_spec = importlib.util.spec_from_file_location("validate_write", HOOK)
validate_write = importlib.util.module_from_spec(_spec)
sys.modules["validate_write"] = validate_write
_spec.loader.exec_module(validate_write)

VALID_FRONTMATTER = """---
date: 2026-06-07
description: "A hermetic test note used to exercise the validate-write hook contract"
tags:
  - test
---

# A Note

Body content that links to [[Something]] so the wikilink rule is satisfied.
"""

# Well-formed YAML frontmatter that is missing the required `tags` field →
# blocking error (severity "error", exit 1), distinct from a parse warning.
MISSING_REQUIRED_FIELD = """---
date: 2026-06-07
description: "A note whose frontmatter parses but omits the required tags field"
---

# A Note

Body content that links to [[Something]].
"""

# Opening fence with a closing fence but invalid YAML inside → parse warning.
BAD_YAML_FRONTMATTER = """---
date: 2026-06-07
description: "x
tags: [unclosed
---

# A Note

Body.
"""


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    # Full vault_utils.find_vault_root signature: CLAUDE.md + brain/ + perf/.
    (tmp_path / "CLAUDE.md").write_text("# Vault", encoding="utf-8")
    (tmp_path / "brain").mkdir()
    (tmp_path / "perf").mkdir()
    (tmp_path / "work").mkdir()
    return tmp_path


def _run_hook(file_path: Path | str | None) -> subprocess.CompletedProcess[str]:
    """Invoke the hook with a PostToolUse-shaped event on stdin."""
    if file_path is None:
        event = "{}"
    else:
        event = json.dumps({"tool_input": {"file_path": str(file_path)}})
    return _run_hook_raw(event)


def _run_hook_raw(stdin: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=stdin,
        capture_output=True,
        text=True,
    )


class TestVaultRootSignature:
    """Root resolution delegates to vault_utils.find_vault_root, which requires
    the full brain/ + perf/ + CLAUDE.md signature — not CLAUDE.md/AGENTS.md alone.
    Each negative case writes into a governed dir (``work/``) with content that
    would otherwise fail validation, so exit 0 proves validation was skipped
    rather than merely passing. The governed dir is load-bearing: a note at the
    tmpdir root is never governed (``vault_scope_defaults.is_governed_markdown_note``
    requires ``parts[0]`` in ``GOVERNED_NOTE_DIRS``), so ``validate()`` returns no
    errors regardless of which root resolved, and the case cannot fail.
    """

    def test_claude_md_alone_skips_validation(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE.md").write_text("# not a vault", encoding="utf-8")
        (tmp_path / "work").mkdir()
        note = tmp_path / "work" / "broken.md"
        note.write_text(MISSING_REQUIRED_FIELD, encoding="utf-8")

        result = _run_hook(note)

        assert result.returncode == 0, result.stderr

    def test_agents_md_alone_skips_validation(self, tmp_path: Path) -> None:
        (tmp_path / "AGENTS.md").write_text("# not a vault", encoding="utf-8")
        (tmp_path / "work").mkdir()
        note = tmp_path / "work" / "broken.md"
        note.write_text(MISSING_REQUIRED_FIELD, encoding="utf-8")

        result = _run_hook(note)

        assert result.returncode == 0, result.stderr

    def test_full_signature_validates(self, vault: Path) -> None:
        note = vault / "work" / "broken.md"
        note.write_text(MISSING_REQUIRED_FIELD, encoding="utf-8")

        result = _run_hook(note)

        assert result.returncode == 1, result.stderr


class TestValidWrite:
    def test_valid_note_exits_zero(self, vault: Path) -> None:
        note = vault / "work" / "note.md"
        note.write_text(VALID_FRONTMATTER, encoding="utf-8")

        result = _run_hook(note)

        assert result.returncode == 0, result.stderr


class TestBlockingError:
    def test_missing_required_field_exits_one(self, vault: Path) -> None:
        note = vault / "work" / "broken.md"
        note.write_text(MISSING_REQUIRED_FIELD, encoding="utf-8")

        result = _run_hook(note)

        assert result.returncode == 1, result.stderr
        # Blocking failures must emit structured hookSpecificOutput —
        # {hookEventName, additionalContext}, not a bare string.
        payload = json.loads(result.stdout)
        assert isinstance(payload["hookSpecificOutput"], dict)
        assert payload["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
        additional_context = payload["hookSpecificOutput"]["additionalContext"]
        assert "failed" in additional_context.lower()
        assert "Fix these issues before proceeding." in additional_context
        assert "systemMessage" not in payload


class TestNoFrontmatter:
    def test_missing_fence_is_warning_exit_two(self, vault: Path) -> None:
        # A file that does not start with --- parses as a frontmatter warning
        # (severity "warning") per the engine, which the hook maps to exit 2.
        note = vault / "work" / "no-fm.md"
        note.write_text(
            "# A Note\n\nNo frontmatter fence at all.\n", encoding="utf-8"
        )

        result = _run_hook(note)

        assert result.returncode == 2, result.stderr
        payload = json.loads(result.stdout)
        assert isinstance(payload["hookSpecificOutput"], dict)
        assert "additionalContext" in payload["hookSpecificOutput"]


class TestWarningOnly:
    def test_yaml_parse_error_exits_two(self, vault: Path) -> None:
        note = vault / "work" / "bad-yaml.md"
        note.write_text(BAD_YAML_FRONTMATTER, encoding="utf-8")

        result = _run_hook(note)

        assert result.returncode == 2, result.stderr
        payload = json.loads(result.stdout)
        assert isinstance(payload["hookSpecificOutput"], dict)
        assert "additionalContext" in payload["hookSpecificOutput"]


class TestUnpromotedMemoryLane:
    """The lane must warn, never block.

    Driven through the real subprocess like the rest of this file, so the wiring is
    covered and not just ``unpromoted_memory``'s pure functions (tested separately).
    Auto-memory is redirected via ``HOME``, which the child inherits — these tests
    must never read the real memory store.
    """

    @staticmethod
    def _stub_resolver(vault: Path, payload: dict) -> None:
        """A stand-in ``graph_cli.py --diagnose-broken`` at the path the lane shells to.

        Stubbing the seam rather than the function keeps the subprocess boundary under
        test — argv shape, exit code, JSON parsing — which is where a wiring bug would
        actually live. A tmp vault has no graphmark, and without this the positive path
        cannot fire at all.
        """
        scripts = vault / ".claude" / "scripts"
        scripts.mkdir(parents=True, exist_ok=True)
        (scripts / "graph_cli.py").write_text(
            "import json, sys\nprint(json.dumps(%r))\n" % (payload,), encoding="utf-8"
        )

    @staticmethod
    def _fake_home(tmp_path: Path, vault: Path, *slugs: str) -> str:
        home = tmp_path / "home"
        mem = home / ".claude" / "projects" / str(vault).replace("/", "-") / "memory"
        mem.mkdir(parents=True)
        (mem / "MEMORY.md").write_text("# Memory Index\n", encoding="utf-8")
        for slug in slugs:
            (mem / f"{slug}.md").write_text("a durable fact", encoding="utf-8")
        return str(home)

    def test_unpromoted_link_warns_without_blocking(
        self, vault: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOME", self._fake_home(tmp_path, vault, "some-durable-lesson"))
        note = vault / "work" / "decisions.md"
        note.write_text(
            VALID_FRONTMATTER.replace("[[Something]]", "[[some-durable-lesson]]"),
            encoding="utf-8",
        )
        self._stub_resolver(
            vault,
            {
                "work/decisions.md": [
                    {"display": "some-durable-lesson", "reason": "missing", "candidates": []}
                ]
            },
        )

        result = _run_hook(note)

        # Exit 2, never 1: a forward reference is legitimate and must stay writable.
        assert result.returncode == 2, result.stderr
        output = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        assert "some-durable-lesson" in output
        assert "auto-memory" in output

    def test_link_naming_no_memory_stays_silent(
        self, vault: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A plain unresolved link is the existing lane's business, not this one."""
        monkeypatch.setenv("HOME", self._fake_home(tmp_path, vault, "some-durable-lesson"))
        note = vault / "work" / "note.md"
        note.write_text(VALID_FRONTMATTER, encoding="utf-8")  # links [[Something]]

        result = _run_hook(note)

        assert result.returncode == 0, result.stderr

    def test_fires_on_a_note_outside_frontmatter_governance(
        self, vault: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Frontmatter governance and graph scope are different questions.

        ``thinking/`` is exempt from the frontmatter contract but its wikilinks are
        fully counted by graphmark and by ``vault_health``. Gating this lane on the
        frontmatter exclusion set therefore silenced the check on notes that can
        still break the gate — verified live, where a ``thinking/`` note with an
        unpromoted-memory link failed ``max_unresolved_links`` while the hook said
        nothing. graphmark is the only authority on scope here.
        """
        monkeypatch.setenv("HOME", self._fake_home(tmp_path, vault, "some-durable-lesson"))
        thinking = vault / "thinking"
        thinking.mkdir()
        note = thinking / "a-design-note.md"
        note.write_text(
            "# Design\n\nBuilding on [[some-durable-lesson]].\n", encoding="utf-8"
        )
        self._stub_resolver(
            vault,
            {
                "thinking/a-design-note.md": [
                    {"display": "some-durable-lesson", "reason": "missing", "candidates": []}
                ]
            },
        )

        result = _run_hook(note)

        assert result.returncode == 2, result.stderr
        additional_context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        assert "some-durable-lesson" in additional_context

    def test_no_auto_memory_on_machine_is_silent(
        self, vault: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Self-sufficiency: a fresh machine has no memory store and must still pass."""
        monkeypatch.setenv("HOME", str(tmp_path / "empty-home"))
        note = vault / "work" / "note.md"
        note.write_text(VALID_FRONTMATTER, encoding="utf-8")

        result = _run_hook(note)

        assert result.returncode == 0, result.stderr


class TestExcludedAndNoop:
    def test_non_markdown_path_exits_zero(self, vault: Path) -> None:
        other = vault / "work" / "data.json"
        other.write_text("{}", encoding="utf-8")

        result = _run_hook(other)

        assert result.returncode == 0, result.stderr

    def test_excluded_claude_md_exits_zero(self, vault: Path) -> None:
        # CLAUDE.md is excluded at any depth; even with no frontmatter it passes.
        result = _run_hook(vault / "CLAUDE.md")
        assert result.returncode == 0, result.stderr

    def test_excluded_agents_md_exits_zero(self, vault: Path) -> None:
        agents = vault / "work" / "AGENTS.md"
        agents.write_text("# Work rules\nNo frontmatter.\n", encoding="utf-8")
        result = _run_hook(agents)
        assert result.returncode == 0, result.stderr

    def test_missing_file_path_exits_zero(self, vault: Path) -> None:
        # Event with no file_path → no-op.
        result = _run_hook(None)
        assert result.returncode == 0, result.stderr

    def test_empty_stdin_exits_zero(self) -> None:
        result = _run_hook_raw("")
        assert result.returncode == 0, result.stderr

    def test_whitespace_stdin_exits_zero(self) -> None:
        result = _run_hook_raw("   \n  ")
        assert result.returncode == 0, result.stderr

    def test_garbage_stdin_exits_zero(self) -> None:
        # Malformed JSON must not crash the hook.
        result = _run_hook_raw("this is not json {{{")
        assert result.returncode == 0, result.stderr


class TestCrashPayloadShapes:
    """The two crash handlers must emit the same {hookSpecificOutput:
    {hookEventName, additionalContext}} shape as the normal-path output —
    a crash is still a PostToolUse response, not a different channel.
    """

    def test_validate_engine_crash_emits_structured_payload(
        self, vault: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """`validate()` raising is caught at the inner handler (~line 94)."""
        note = vault / "work" / "note.md"
        note.write_text(VALID_FRONTMATTER, encoding="utf-8")
        event = json.dumps({"tool_input": {"file_path": str(note)}})

        with patch("validate_write.validate", side_effect=RuntimeError("boom")), \
             patch.object(sys, "stdin", io.StringIO(event)):
            exit_code = validate_write.main()

        assert exit_code == 2
        payload = json.loads(capsys.readouterr().out)
        assert isinstance(payload["hookSpecificOutput"], dict)
        assert payload["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
        additional_context = payload["hookSpecificOutput"]["additionalContext"]
        assert "crashed" in additional_context.lower()
        assert "systemMessage" not in payload

    def test_outer_wrapper_crash_emits_structured_payload(self) -> None:
        """A non-dict-but-valid-JSON event (e.g. a bare list) makes
        `event.get(...)` raise AttributeError outside every inner try/except,
        exercising the outer `if __name__ == "__main__":` handler (~line 144).
        """
        result = _run_hook_raw("[]")

        assert result.returncode == 2, result.stderr
        payload = json.loads(result.stdout)
        assert isinstance(payload["hookSpecificOutput"], dict)
        assert payload["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
        additional_context = payload["hookSpecificOutput"]["additionalContext"]
        assert "crashed" in additional_context.lower()
        assert "systemMessage" not in payload
