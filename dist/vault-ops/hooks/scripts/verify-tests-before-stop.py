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
and Codex — pure stdlib, no reliance on Claude-Code-only stdin fields
beyond ones that degrade safely when absent (`stop_hook_active`,
`session_id`).
"""

import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

try:
    data = json.load(sys.stdin)
except json.JSONDecodeError:
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


def git_dir(project_dir: Path):
    """Return the repo's absolute .git dir, or None if not inside a git repo."""
    try:
        result = subprocess.run(
            ["git", "-C", str(project_dir), "rev-parse", "--absolute-git-dir"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip())


def working_tree_signature(project_dir: Path):
    """A content-aware fingerprint of what's changed.

    `git status --porcelain` alone only reports per-path status flags (M/A/??),
    not content — editing an already-modified file's content again produces the
    identical porcelain line, which would wrongly look "unchanged." So this
    hashes the status output plus the current bytes of every listed path.
    """
    try:
        status = subprocess.run(
            ["git", "-C", str(project_dir), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if status.returncode != 0:
        return None

    hasher = hashlib.sha256()
    hasher.update(status.stdout.encode("utf-8", "surrogateescape"))
    for line in status.stdout.splitlines():
        path_part = line[3:]
        if " -> " in path_part:
            path_part = path_part.split(" -> ")[-1]
        path_part = path_part.strip('"')
        try:
            hasher.update((project_dir / path_part).read_bytes())
        except OSError:
            pass
    return hasher.hexdigest()


repo_git_dir = git_dir(cwd)
if repo_git_dir is None:
    # No cheap way to tell "unchanged" from "changed" outside a git repo —
    # don't force a full suite run on every single Stop.
    sys.exit(0)

signature = working_tree_signature(cwd)
if signature is None:
    sys.exit(0)

session_id = data.get("session_id") or "default"
state_file = repo_git_dir / "the-workshop-stop-gate" / f"{session_id}.txt"

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
    except OSError:
        pass
    sys.exit(0)

tail = "\n".join((result.stdout + result.stderr).splitlines()[-40:])
print(
    "Tests are failing — fix them before stopping.\n"
    f"$ {' '.join(test_command)}\n{tail}",
    file=sys.stderr,
)
sys.exit(2)
