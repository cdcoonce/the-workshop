#!/usr/bin/env python3
"""Background notebook distiller — the "hippocampus" worker.

Spawned detached by ``notebook-update.py`` on every Stop event. Reads the
latest turn from the session transcript, merges it into the live session
notebook (``.brain/notebook-<context>.md``) via a cheap headless batch-model call,
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

import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from notebook_core import NOTEBOOK_SKELETON, build_prompt, latest_turn
from vault_utils import read_batch_model, read_vault_context

MIN_TURN_CHARS = 200           # debounce: skip trivial turns
CLAUDE_TIMEOUT = 90            # seconds for the headless call
STALE_HOURS = 6               # reap per-session notebooks older than this


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


def reap_stale(vault_root: Path, context: str, keep: Path) -> None:
    """Delete per-session notebooks for this context older than STALE_HOURS.

    Per-session keying means orphaned files accumulate as sessions end; this
    self-cleans them. Never touches the file the current session owns (*keep*)
    or the legacy un-suffixed notebook (different glob).
    """
    try:
        cutoff = datetime.now().timestamp() - STALE_HOURS * 3600
        for f in (vault_root / ".brain").glob(f"notebook-{context}-*.md"):
            if f != keep and f.stat().st_mtime < cutoff:
                f.unlink()
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


def main() -> int:
    if len(sys.argv) < 4:
        return 0
    transcript_path = Path(sys.argv[1])
    session_id = sys.argv[2]
    vault_root = Path(sys.argv[3])

    context = read_context(vault_root)
    # Keyed by session_id, not just context: concurrent same-context vault
    # sessions must not clobber each other. /clear preserves session_id, so the
    # SessionStart injector matches this exact file on resume. Reap stale ones.
    notebook_path = vault_root / ".brain" / f"notebook-{context}-{session_id}.md"
    reap_stale(vault_root, context, keep=notebook_path)

    user_text, assistant_text = latest_turn(transcript_path)
    if len(user_text) + len(assistant_text) < MIN_TURN_CHARS:
        return 0  # debounce trivial turns

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    sid = session_id[:8] if session_id else "unknown"

    if notebook_path.exists():
        current = notebook_path.read_text(encoding="utf-8").strip()
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
    notebook_path.write_text(f"{header}\n\n{body}\n", encoding="utf-8")
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
