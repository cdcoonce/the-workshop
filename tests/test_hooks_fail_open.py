"""Every hook must fail open on input it cannot understand.

A hook runs on the user's prompt/tool path. If it crashes on a payload it did
not expect — a malformed body, an empty stdin, or a JSON value that is not the
object the hook assumes — it surfaces an error on an unrelated action and, on
blocking events, can interfere with the user's work. Hooks state fail-open in
their docstrings; this makes it enforceable and automatically covers hooks
added later.

Scope: unparseable/unexpected-shape input only. Hooks that deliberately block
on a *well-formed* payload (protect-files, verify-tests-before-stop) keep that
behaviour — it is covered by their own suites.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# Input that is unparseable or not a JSON object. A hook cannot act on any of
# it, so each must be a silent no-op.
#
# Deliberately excludes "{}": an empty object is the *expected* shape, merely
# without fields, and a hook may legitimately act on it (verify-tests-before-stop
# correctly runs the suite when no stop_hook_active flag is present). Asserting
# a no-op there would encode a false expectation.
#
# Empty/whitespace stdin is a similar special case: it is the *well-formed*
# condition on Codex, which delivers hooks no payload at all (COMPATIBILITY.md
# → Codex → Hooks), and a hook may legitimately derive facts from its working
# directory there. Those cases therefore run in an empty scratch cwd below —
# the guarantee stays "no crash, exit 0", without demanding the hook treat
# payload-less stdin as unusable.
UNUSABLE_PAYLOADS = {
    "malformed-json": "not json at all",
    "empty-stdin": "",
    "whitespace-only": "   \n  ",
    "json-list": "[]",
    "json-string": '"hello"',
    "json-null": "null",
}

PAYLOAD_LESS_LABELS = {"empty-stdin", "whitespace-only"}


def _hook_scripts() -> list[Path]:
    """Every hook script shipped from a plugin's flat hooks/ tree.

    Underscore-prefixed files are shared library modules, not hooks (see
    `plugins/workbench/hooks/scripts/_git_baseline.py`). They read no stdin, so
    they pass this suite trivially — which is worse than being skipped: it
    reports a fail-open guarantee for something that was never on the tool
    path, and quietly pads the count that makes
    `test_hook_scripts_are_discovered` meaningful.
    """
    scripts = sorted((REPO_ROOT / "plugins").glob("*/hooks/scripts/*.py"))
    scripts += sorted((REPO_ROOT / "plugins").glob("*/hooks/*.py"))
    return [s for s in scripts if not s.name.startswith("_")]


HOOKS = _hook_scripts()


def test_hook_scripts_are_discovered() -> None:
    """Guard the guard: discovery must actually find hooks."""
    assert HOOKS, "no hook scripts discovered"


def test_library_modules_are_not_scanned_as_hooks() -> None:
    """A helper module passing a hook contract is a false assurance, not coverage."""
    assert not [h for h in HOOKS if h.name.startswith("_")]
    assert "protect-files.py" in {h.name for h in HOOKS}


@pytest.mark.parametrize("hook", HOOKS, ids=lambda p: p.name)
@pytest.mark.parametrize("label", sorted(UNUSABLE_PAYLOADS))
def test_hook_fails_open_on_unusable_input(
    hook: Path, label: str, tmp_path: Path
) -> None:
    """Unusable stdin makes the hook a no-op that exits 0.

    ``CLAUDE_PROJECT_DIR`` is pinned to the scratch dir rather than inherited:
    Claude Code always sets it when dispatching a real hook, and the vault
    hooks branch on it. Inheriting it made this suite environment-dependent —
    unset (CI, plain shells) the vault wrappers failed open before ever
    reaching the engine, while inside a Claude Code session the engine ran
    against the *session's* project dir, wrote its breadcrumb into that real
    repo, and its not-a-vault exit code escaped. Pinning to an empty scratch
    dir exercises the "hook fired outside any vault" path deterministically
    everywhere and keeps hook side effects in tmp.
    """
    result = subprocess.run(
        [sys.executable, str(hook)],
        input=UNUSABLE_PAYLOADS[label],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=tmp_path if label in PAYLOAD_LESS_LABELS else REPO_ROOT,
        env=os.environ | {"CLAUDE_PROJECT_DIR": str(tmp_path)},
    )
    assert result.returncode == 0, (
        f"{hook.name} exited {result.returncode} on {label} input; hooks must "
        f"fail open. stderr: {result.stderr[:400]}"
    )
