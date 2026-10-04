#!/usr/bin/env python3
"""Background notebook distiller — the "hippocampus" worker.

Spawned detached by ``notebook-update.py`` on every Stop event. Reads the
latest turn from the session transcript, merges it into the live session
notebook (``.brain/notebook-<context>-<session_id>.md``) via a cheap headless batch-model call,
and writes the result back.

Design notes:
    * Runs the ``claude -p`` call from a TEMP cwd so it does NOT load the vault
      CLAUDE.md or re-trigger vault hooks (no recursion, lean context).
    * Fail-soft: this is a convenience layer, never a gate. Any error is logged
      to ``.claude/data/notebook.log`` (gitignored) and the existing notebook is
      left untouched. It must never break Charles's session.
    * Stdlib only — matches the rest of ``.claude/scripts`` (no Anthropic SDK).

Argv: <transcript_path> <session_id> <vault_root>
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

sys.path.insert(0, str(Path(__file__).resolve().parent))

from notebook_core import NOTEBOOK_SKELETON, build_prompt, latest_turn_from_text, valid_session_id
from vault_utils import read_batch_model, read_vault_context

MIN_TURN_CHARS = 200           # debounce: skip trivial turns
CLAUDE_TIMEOUT = 90            # seconds for the headless call
STALE_HOURS = 6               # flag old notebooks for explicit promotion/archive


@contextmanager
def notebook_lock(vault_root: Path, notebook_path: Path) -> Iterator[None]:
    """Serialize session workers with a lock released by the OS on process exit.

    Lock files stay in gitignored runtime data. Never unlink them: a waiter
    could still hold the old inode while a new worker locks a replacement.
    """
    data_dir = vault_root / ".claude" / "data" / "notebooks"
    data_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(notebook_path.name.encode("utf-8")).hexdigest()
    with (data_dir / f"{key}.lock").open("a+b") as lock_file:
        if os.name == "nt":
            import msvcrt

            if lock_file.tell() == 0:
                lock_file.write(b"\0")
                lock_file.flush()
            while True:
                lock_file.seek(0)
                try:
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError as exc:
                    if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                        raise
                    time.sleep(0.05)
            try:
                yield
            finally:
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file, fcntl.LOCK_UN)


def log(vault_root: Path, msg: str) -> None:
    """Append a timestamped line to the gitignored notebook log."""
    try:
        data_dir = vault_root / ".claude" / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        (data_dir / "notebook.log").open("a", encoding="utf-8").write(
            f"[{stamp}] {msg}\n"
        )
    except Exception:
        pass  # logging must never raise


def retain_stale(vault_root: Path, context: str, keep: Path) -> None:
    """Report old notebooks without assuming their contents were promoted."""
    try:
        cutoff = datetime.now().timestamp() - STALE_HOURS * 3600
        for f in (vault_root / ".brain").glob(f"notebook-{context}-*.md"):
            if f != keep and f.stat().st_mtime < cutoff:
                log(vault_root, f"{f.name} retained: age does not prove promotion; explicitly archive after review")
    except OSError:
        pass


def read_context(vault_root: Path) -> str:
    """Machine context from .vault-context (canonical reader; 'unknown' if absent)."""
    return read_vault_context(vault_root)


def distill(prompt: str, model: str) -> str | None:
    """Run headless *model* from a temp cwd; return its text output or None."""
    try:
        result = subprocess.run(
            ["claude", "-p", "--model", model],
            input=prompt,
            capture_output=True,
            text=True,
            cwd=tempfile.gettempdir(),  # avoid loading vault CLAUDE.md / hooks
            timeout=CLAUDE_TIMEOUT,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None  # claude not on PATH, or call hung — fail-soft
    if result.returncode != 0:
        return None
    out = result.stdout.strip()
    return out or None


def atomic_write(
    path: Path, content: bytes, *, check_base: bool = False, base: bytes | None = None
) -> bool:
    """Replace complete output, optionally rejecting a changed base just before swap.

    The content check protects edits made while the model runs. It is not a
    filesystem compare-and-swap against arbitrary noncooperating writers.
    """
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if check_base:
            current = path.read_bytes() if path.exists() else None
            if current != base:
                return False
        os.replace(temporary, path)
        return True
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> int:
    if len(sys.argv) < 4:
        return 0
    transcript_path = Path(sys.argv[1])
    session_id = sys.argv[2]
    vault_root = Path(sys.argv[3])
    if not valid_session_id(session_id):
        return 0

    context = read_context(vault_root)
    # Keyed by session_id, not just context: concurrent same-context vault
    # sessions must not clobber each other. Startup can reuse this file only
    # when the runtime supplies the same exact session identity. Retain old ones.
    notebook_path = vault_root / ".brain" / f"notebook-{context}-{session_id}.md"
    retain_stale(vault_root, context, keep=notebook_path)

    with notebook_lock(vault_root, notebook_path):
        return update_notebook(transcript_path, session_id, vault_root, context, notebook_path)


def update_notebook(
    transcript_path: Path, session_id: str, vault_root: Path, context: str, notebook_path: Path
) -> int:
    """Read and merge current state while the caller holds the session lock."""
    try:
        transcript = transcript_path.read_text(encoding="utf-8")
    except OSError:
        return 0
    user_text, assistant_text = latest_turn_from_text(transcript)
    if len(user_text) + len(assistant_text) < MIN_TURN_CHARS:
        return 0  # debounce trivial turns

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    sid = session_id[:8] if session_id else "unknown"

    base = notebook_path.read_bytes() if notebook_path.exists() else None
    transcript_digest = hashlib.sha256(transcript.encode("utf-8")).hexdigest()
    key = hashlib.sha256(notebook_path.name.encode("utf-8")).hexdigest()
    state_path = vault_root / ".claude" / "data" / "notebooks" / f"{key}.json"
    expected_state = {
        "transcript_sha256": transcript_digest,
        "notebook_sha256": hashlib.sha256(base or b"").hexdigest(),
    }
    try:
        if json.loads(state_path.read_text(encoding="utf-8")) == expected_state:
            return 0  # a queued worker sees a snapshot already persisted
    except (OSError, ValueError):
        pass

    if base is not None:
        current = base.decode("utf-8").strip()
    else:
        current = NOTEBOOK_SKELETON.format(
            context_title=context.title(), stamp=stamp, sid=sid
        )

    prompt = build_prompt(current, user_text, assistant_text)
    updated = distill(prompt, read_batch_model())
    if not updated:
        log(vault_root, "distill produced no output; notebook left unchanged")
        return 0

    # Refresh the metadata line so freshness is visible at a glance.
    header = (
        f"# Session Notebook — {context.title()}\n\n"
        f"_Live session state · updated {stamp} · session {sid}_"
    )
    body = updated
    # If the model echoed its own header, strip it so we control the stamp line.
    if body.lstrip().startswith("# Session Notebook"):
        lines = body.splitlines()
        # drop the model's title + its stamp line (first two non-empty lines)
        kept: list[str] = []
        dropped = 0
        for ln in lines:
            if dropped < 2 and (ln.startswith("# Session Notebook") or ln.startswith("_Live session state")):
                dropped += 1
                continue
            kept.append(ln)
        body = "\n".join(kept).lstrip("\n")

    notebook_path.parent.mkdir(parents=True, exist_ok=True)
    output = f"{header}\n\n{body}\n".encode("utf-8")
    if not atomic_write(notebook_path, output, check_base=True, base=base):
        log(vault_root, f"{notebook_path.name} changed during distill; result discarded, retry on next Stop")
        return 0
    # Record success only after the notebook is persisted. A crash before this
    # marker may repeat a merge, but must never claim an unwritten turn is done.
    expected_state["notebook_sha256"] = hashlib.sha256(output).hexdigest()
    atomic_write(state_path, json.dumps(expected_state).encode("utf-8"))
    log(vault_root, f"{notebook_path.name} updated ({len(body)} chars)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # fail-soft, always
        try:
            root = Path(sys.argv[3]) if len(sys.argv) > 3 else Path.cwd()
            log(root, f"distill crashed: {exc!r}")
        except Exception:
            pass
        sys.exit(0)
