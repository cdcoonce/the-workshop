#!/usr/bin/env python3
"""Stop hook: verify the project's test suite is green before Claude stops.

Auto-detects the test command (a Makefile `test:` target, then pytest via
pyproject.toml/tests/, then `npm test`) and only actually runs it when
tracked/untracked source has changed since the last verified green run —
so an unrelated Stop (a question, a plan, a read-only turn) is a cheap
no-op instead of a full suite run.

Fails open everywhere: no test command detected, not a git repo, git/test
binary missing, or the run itself errors out all exit 0 rather than
blocking on ambiguity. Portable across Claude Code, Cortex Code (CoCo),
and Codex — pure stdlib. Codex delivers hooks *no stdin payload at all*
(see COMPATIBILITY.md → Codex → Hooks), so empty stdin is the payload-less
platform condition, not malformed input: the hook proceeds with
self-derived facts (cwd from its own working directory, a `default`
session). Because `stop_hook_active` never arrives payload-less, that path
blocks once per failing tree state instead of looping. Non-empty stdin
that isn't a JSON object still fails open.
"""

# This hook's wiring lives here; scripts/stamp.py statically reads it to emit
# hooks/hooks.json.
WORKSHOP_HOOK = {"event": "Stop"}

import json  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

raw_payload = sys.stdin.read()
payload_absent = not raw_payload.strip()
if payload_absent:
    # Codex: hooks receive no stdin payload — every fact below self-derives.
    data = {}
else:
    try:
        data = json.loads(raw_payload)
    except json.JSONDecodeError:
        sys.exit(0)
    if not isinstance(data, dict):
        # Fail open: a payload that isn't a JSON object isn't ours to act on.
        sys.exit(0)

# Claude Code sets this once it has already blocked a Stop to force a
# continuation loop. Codex/CoCo may never send it — absence just means
# "not currently in a continuation loop," so default to False.
if data.get("stop_hook_active"):
    sys.exit(0)

cwd = Path(data.get("cwd") or ".").resolve()


def detect_test_command(project_dir: Path):
    """Return the argv for the project's test command, or None if none is found."""
    makefile = project_dir / "Makefile"
    if makefile.exists():
        try:
            text = makefile.read_text()
        except OSError:
            text = ""
        if re.search(r"(?m)^test:", text):
            return ["make", "test"]

    package_json = project_dir / "package.json"
    if package_json.exists():
        try:
            pkg = json.loads(package_json.read_text())
        except (OSError, json.JSONDecodeError):
            pkg = {}
        scripts = pkg.get("scripts", {}) if isinstance(pkg, dict) else {}
        test_script = scripts.get("test", "")
        if test_script and "no test specified" not in test_script:
            return ["npm", "test", "--silent"]

    has_pytest_project = (project_dir / "pyproject.toml").exists()
    has_tests_dir = (project_dir / "tests").is_dir()
    if has_pytest_project or has_tests_dir:
        if shutil.which("uv"):
            return ["uv", "run", "--with", "pytest", "python", "-m", "pytest", "-q"]
        if shutil.which("pytest"):
            return ["pytest", "-q"]

    return None


test_command = detect_test_command(cwd)
if test_command is None:
    sys.exit(0)

try:
    from _git_baseline import git_dir, head_sha, working_tree_signature
except ImportError:
    # Fail open: the helper module ships alongside every hook, but a stale or
    # partial install must no-op rather than crash the user's tool path.
    sys.exit(0)


repo_git_dir = git_dir(cwd)
if repo_git_dir is None:
    # No cheap way to tell "unchanged" from "changed" outside a git repo —
    # don't force a full suite run on every single Stop.
    sys.exit(0)

signature = working_tree_signature(cwd)
if signature is None:
    sys.exit(0)
signature = f"{head_sha(cwd) or ''}\n{signature}"

session_id = data.get("session_id") or "default"
state_file = repo_git_dir / "the-workshop-stop-gate" / f"{session_id}.txt"
blocked_file = repo_git_dir / "the-workshop-stop-gate" / f"{session_id}.blocked"

if payload_absent and blocked_file.exists():
    # Payload-less platforms never send stop_hook_active, so this marker is
    # the loop guard: one block per failing tree state. Any change to the
    # tree produces a new signature and re-arms the block.
    try:
        if blocked_file.read_text() == signature:
            sys.exit(0)
    except OSError:
        pass

previous_signature = None
if state_file.exists():
    try:
        previous_signature = state_file.read_text()
    except OSError:
        previous_signature = None

if signature == previous_signature:
    sys.exit(0)

try:
    result = subprocess.run(
        test_command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=600,
    )
except (OSError, subprocess.TimeoutExpired) as exc:
    print(
        f"verify-tests-before-stop: could not run `{' '.join(test_command)}`: {exc}",
        file=sys.stderr,
    )
    sys.exit(0)

if result.returncode == 0:
    try:
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(signature)
        blocked_file.unlink(missing_ok=True)
    except OSError:
        pass
    sys.exit(0)

if payload_absent:
    try:
        blocked_file.parent.mkdir(parents=True, exist_ok=True)
        blocked_file.write_text(signature)
    except OSError:
        pass

tail = "\n".join((result.stdout + result.stderr).splitlines()[-40:])
print(
    "Tests are failing — fix them before stopping.\n"
    f"$ {' '.join(test_command)}\n{tail}",
    file=sys.stderr,
)
sys.exit(2)
