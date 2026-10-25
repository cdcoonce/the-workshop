#!/usr/bin/env python3
"""Stop hook: verify the project's test suite is green before Claude stops.

Auto-detects the test command (a Makefile `test:` target, then `npm test`,
then pytest via pyproject.toml or a tests/ directory holding Python files) and only actually runs it when
tracked/untracked source has changed since the last verified green run —
so an unrelated Stop (a question, a plan, a read-only turn) is a cheap
no-op instead of a full suite run.

Fails open everywhere: no test command detected, not a git repo, git/test
binary missing, or the run itself errors out all exit 0 rather than
blocking on ambiguity. A gate already running in the same worktree (the same
test command, or a `teeth_check.py` run, whose cwd is inside it) defers the
check instead of starting a second suite beside it, since a teeth stage
mutates source in place. Portable across Claude Code, Cortex Code (CoCo),
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
import os  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

try:
    raw_payload = sys.stdin.read()
except ValueError:
    # Fail open: undecodable bytes (UnicodeDecodeError is a ValueError) name
    # nothing this hook can act on.
    sys.exit(0)
payload_absent = not raw_payload.strip()
if payload_absent:
    # Codex: hooks receive no stdin payload — every fact below self-derives.
    data = {}
else:
    try:
        data = json.loads(raw_payload)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)
    if not isinstance(data, dict):
        # Fail open: a payload that isn't a JSON object isn't ours to act on.
        sys.exit(0)

# Claude Code sets this once it has already blocked a Stop to force a
# continuation loop. Codex/CoCo may never send it — absence just means
# "not currently in a continuation loop," so default to False.
if data.get("stop_hook_active"):
    sys.exit(0)

raw_cwd = data.get("cwd")
# Fail open: Path() raises TypeError on a non-string, before any try/except.
cwd = Path(raw_cwd if isinstance(raw_cwd, str) and raw_cwd else ".").resolve()


def detect_test_command(project_dir: Path):
    """Return the argv for the project's test command, or None if none is found."""
    makefile = project_dir / "Makefile"
    if makefile.exists():
        try:
            text = makefile.read_text()
        except (OSError, UnicodeDecodeError):
            text = ""
        if re.search(r"(?m)^test:", text):
            return ["make", "test"]

    package_json = project_dir / "package.json"
    if package_json.exists():
        try:
            pkg = json.loads(package_json.read_text())
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            pkg = {}
        scripts = pkg.get("scripts", {}) if isinstance(pkg, dict) else {}
        test_script = scripts.get("test", "")
        if test_script and "no test specified" not in test_script:
            return ["npm", "test", "--silent"]

    has_pytest_project = (project_dir / "pyproject.toml").exists()
    tests_dir = project_dir / "tests"
    has_tests_dir = tests_dir.is_dir() and any(tests_dir.rglob("*.py"))
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


def _process_table():
    """Yield ``(pid, ppid, argv)`` for every visible process, or nothing.

    Linux reads ``/proc`` for exact argv; elsewhere ``ps`` is split on
    whitespace, which is lossy only for arguments that contain spaces.
    """
    proc = Path("/proc")
    if (proc / "self" / "cmdline").exists():
        for entry in proc.iterdir():
            if not entry.name.isdigit():
                continue
            try:
                argv = (entry / "cmdline").read_bytes().split(b"\0")
                stat = (entry / "stat").read_text()
            except OSError:
                continue
            fields = stat.rsplit(")", 1)[-1].split()
            if len(fields) < 2 or not fields[1].isdigit():
                continue
            yield int(entry.name), int(fields[1]), [
                a.decode("utf-8", "replace") for a in argv if a
            ]
        return
    try:
        listed = subprocess.run(
            ["ps", "-axo", "pid=,ppid=,args="],
            capture_output=True, text=True, timeout=10, errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired):
        return
    for line in listed.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0].isdigit() and parts[1].isdigit():
            yield int(parts[0]), int(parts[1]), parts[2:]


def _process_cwds(pids):
    """Map each pid to its working directory, where the OS will say."""
    if not pids:
        return {}
    if Path("/proc/self/cwd").exists():
        found = {}
        for pid in pids:
            try:
                found[pid] = Path(os.readlink(f"/proc/{pid}/cwd"))
            except OSError:
                pass
        return found
    try:
        listed = subprocess.run(
            ["lsof", "-a", "-d", "cwd", "-Fpn", "-p", ",".join(map(str, pids))],
            capture_output=True, text=True, timeout=10, errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    found, pid = {}, None
    for line in listed.stdout.splitlines():
        if line.startswith("p") and line[1:].isdigit():
            pid = int(line[1:])
        elif line.startswith("n") and pid is not None:
            found[pid] = Path(line[1:])
    return found


def _is_gate(argv, command):
    """True when *argv* runs *command* (extra arguments allowed) or teeth_check.py."""
    if any(Path(arg).name == "teeth_check.py" for arg in argv):
        return True
    if not argv or Path(argv[0]).name != Path(command[0]).name:
        return False
    rest = iter(argv[1:])
    return all(token in rest for token in command[1:])


def live_gate(project_dir: Path, command):
    """The pid of a gate already running in *project_dir*'s worktree, else None.

    The suite this hook runs may mutate source in place (a teeth stage), so a
    second run beside a live one in the same tree can capture the other's
    mutants or fail on them. Our own ancestors are not a rival run.
    """
    table = list(_process_table())
    parents = {pid: ppid for pid, ppid, _ in table}
    ours, pid = set(), os.getpid()
    while pid and pid not in ours:
        ours.add(pid)
        pid = parents.get(pid, 0)
    candidates = [p for p, _, argv in table if p not in ours and _is_gate(argv, command)]
    if not candidates:
        return None
    try:
        top = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=project_dir, capture_output=True, text=True, timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return None
    if not top:
        return None
    root = Path(top).resolve()
    for pid, where in _process_cwds(candidates).items():
        try:
            where = where.resolve()
        except OSError:
            continue
        if where == root or root in where.parents:
            return pid
    return None


rival = live_gate(cwd, test_command)
if rival is not None:
    # Defer, not pass: no state is written, so the next Stop verifies again.
    print(
        f"verify-tests-before-stop: a gate is already running in this tree "
        f"(pid {rival}); not starting `{' '.join(test_command)}` beside it.",
        file=sys.stderr,
    )
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
