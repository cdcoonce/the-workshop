#!/usr/bin/env python3
"""Stop hook: hold the Mac awake after a turn so idle compaction can fire.

Claude Code's idle compaction writes a summary about an hour after a session's
last request, but only if the computer is awake. A Mac that sleeps a minute after
going idle never reaches it. After a turn ends this hook starts
``caffeinate -i -t 4200`` (70 minutes) detached, so the machine stays awake long
enough for the compaction to run.

It stays out of the way unless idle compaction could actually fire: the session's
context (the last main-thread assistant usage in the transcript) must be at or
above the floor (default 200000, override with
``CLAUDE_CODE_IDLE_COMPACT_MIN_TOKENS``), and ``pmset -g batt`` must report
``AC Power``. ``WORKSHOP_KEEP_AWAKE=0`` turns it off. A second Stop for the same
session replaces that session's earlier hold (pid kept under
``WORKSHOP_KEEP_AWAKE_DIR``, default ``~/.workshop/keep-awake``), signalling the
old pid only when ``ps`` confirms it is still a caffeinate.

Stdlib only, fail-open: every path exits 0 and prints nothing, so a Stop hook can
never block or confuse the host. Hosts without ``caffeinate``/``pmset`` make it a
no-op.
"""

from __future__ import annotations

# scripts/stamp.py statically reads this constant to build hooks/hooks.json.
WORKSHOP_HOOK = {"event": "Stop"}

import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import signal  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

DEFAULT_FLOOR = 200_000
HOLD_SECONDS = 4200
_FLOOR_ENV = "CLAUDE_CODE_IDLE_COMPACT_MIN_TOKENS"
_SAFE_SESSION = re.compile(r"[A-Za-z0-9_-]{1,64}")


def _floor() -> int:
    raw = os.environ.get(_FLOOR_ENV, "")
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_FLOOR
    return value if value > 0 else DEFAULT_FLOOR


def _context_tokens(transcript_path: Path) -> int | None:
    """Context size from the last main-thread assistant usage, else None."""
    try:
        lines = transcript_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict) or record.get("type") != "assistant":
            continue
        if record.get("isSidechain") is True:
            continue
        message = record.get("message")
        usage = message.get("usage") if isinstance(message, dict) else None
        if not isinstance(usage, dict):
            continue
        total = 0
        for field in (
            "input_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
        ):
            value = usage.get(field)
            if isinstance(value, int) and not isinstance(value, bool):
                total += value
        return total
    return None


def _session_key(data: dict, transcript_path: str) -> str:
    session_id = data.get("session_id")
    if isinstance(session_id, str) and _SAFE_SESSION.fullmatch(session_id):
        return session_id
    return hashlib.sha256(transcript_path.encode("utf-8")).hexdigest()[:16]


def _state_dir() -> Path:
    override = os.environ.get("WORKSHOP_KEEP_AWAKE_DIR")
    if override:
        return Path(override)
    return Path.home() / ".workshop" / "keep-awake"


def _on_ac_power(pmset: str) -> bool:
    try:
        result = subprocess.run(
            [pmset, "-g", "batt"],
            capture_output=True,
            text=True,
            timeout=10,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return False
    return result.returncode == 0 and "AC Power" in result.stdout


def _replace_previous(pid_file: Path) -> None:
    """SIGTERM the session's previous hold, only if ps says it is a caffeinate."""
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return
    if pid <= 1:
        return
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            timeout=10,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return
    if result.returncode != 0 or "caffeinate" not in result.stdout:
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass


def main() -> int:
    if os.environ.get("WORKSHOP_KEEP_AWAKE") == "0":
        return 0
    try:
        data = json.loads(sys.stdin.read())
    except (ValueError, OSError):
        return 0
    if not isinstance(data, dict):
        return 0
    transcript_path = data.get("transcript_path")
    if not isinstance(transcript_path, str) or not transcript_path:
        return 0

    caffeinate = shutil.which("caffeinate")
    pmset = shutil.which("pmset")
    if caffeinate is None or pmset is None:
        return 0

    if not Path(transcript_path).is_file():
        return 0
    tokens = _context_tokens(Path(transcript_path))
    if tokens is None or tokens < _floor():
        return 0

    if not _on_ac_power(pmset):
        return 0

    state_dir = _state_dir()
    pid_file = state_dir / f"{_session_key(data, transcript_path)}.pid"
    _replace_previous(pid_file)

    child = subprocess.Popen(
        [caffeinate, "-i", "-t", str(HOLD_SECONDS)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        pid_file.write_text(str(child.pid), encoding="utf-8")
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 - a Stop hook must never fail the host
        pass
    sys.exit(0)
