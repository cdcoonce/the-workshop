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
UNUSABLE_PAYLOADS = {
    "malformed-json": "not json at all",
    "empty-stdin": "",
    "whitespace-only": "   \n  ",
    "json-list": "[]",
    "json-string": '"hello"',
    "json-null": "null",
}


def _hook_scripts() -> list[Path]:
    """Every hook script shipped from core/ or a preset.

    Underscore-prefixed files are shared library modules, not hooks (see
    `core/hooks/_git_baseline.py`). They read no stdin, so they pass this suite
    trivially — which is worse than being skipped: it reports a fail-open
    guarantee for something that was never on the tool path, and quietly pads
    the count that makes `test_hook_scripts_are_discovered` meaningful.
    """
    scripts = sorted((REPO_ROOT / "core" / "hooks").glob("*.py"))
    scripts += sorted((REPO_ROOT / "presets").glob("*/hooks/*.py"))
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
def test_hook_fails_open_on_unusable_input(hook: Path, label: str) -> None:
    """Unusable stdin makes the hook a no-op that exits 0."""
    result = subprocess.run(
        [sys.executable, str(hook)],
        input=UNUSABLE_PAYLOADS[label],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, (
        f"{hook.name} exited {result.returncode} on {label} input; hooks must "
        f"fail open. stderr: {result.stderr[:400]}"
    )
