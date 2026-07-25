#!/usr/bin/env python3
"""SessionStart hook — pulls from remote and injects vault context.

Called by Claude Code on session start/resume/clear.
Reads hook event JSON from stdin, performs git pull, loads context,
and outputs summary via hookSpecificOutput.

Exit codes:
    0 — context loaded successfully
    1 — critical error (git not available, vault not found)
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

# How recent the session notebook must be (hours) to surface it on /clear.
# Past this, it's stale leftovers from an earlier session — prefer the handoff.
NOTEBOOK_FRESH_HOURS = 6

# Add scripts dir to path
SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from context_loader import condense_digest, load_context
from sync_manager import pull
from vault_utils import find_vault_root, read_vault_context


def main() -> int:
    # Read the hook event to learn WHY the session started: "startup" (fresh),
    # "resume" (history restored), or "clear" (history just wiped by /clear).
    source = "startup"
    session_id = ""
    raw_event: dict = {}
    try:
        raw_event = json.load(sys.stdin)
        source = raw_event.get("source", "startup")
        session_id = raw_event.get("session_id", "")
    except (json.JSONDecodeError, ValueError):
        pass

    # $CLAUDE_PROJECT_DIR is always set correctly by Claude Code — use it as a
    # reliable starting point so hooks work regardless of the shell's cwd.
    # (cwd is often ~ on /clear, which causes find_vault_root to return None.)
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    vault_root = find_vault_root(Path(project_dir) if project_dir else None)
    if vault_root is None:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": "⚠️ Not in a vault directory (no CLAUDE.md found)."
            }
        }))
        return 1

    # Debug: log raw event to confirm hook_event_name on /clear.
    hook_event_name = raw_event.get("hook_event_name", "")
    try:
        data_dir = vault_root / ".claude" / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        (data_dir / "session-start.log").open("a", encoding="utf-8").write(
            f"[{stamp}] source={source!r} hook_event_name={hook_event_name!r} session_id={session_id[:8]!r}\n"
        )
    except Exception:
        pass

    lines: list[str] = []

    # Pull from remote
    sync_result = pull(vault_root)
    if not sync_result.success:
        lines.append(f"⚠️ Git sync: {sync_result.message}")
        if sync_result.conflicts:
            lines.append("Conflicting files:")
            for f in sync_result.conflicts:
                lines.append(f"  • {f}")
            lines.append("Resolve conflicts manually before continuing.")
    else:
        lines.append(f"✓ Git: {sync_result.message}")

    # Load context
    try:
        ctx = load_context(vault_root)
        lines.append("")
        lines.append(ctx.summary)
    except Exception:
        traceback.print_exc(file=sys.stderr)
        lines.append("⚠️ Context loading failed. Check stderr for details.")

    # Inject exactly ONE state digest — never both — so there's never a question
    # of which to trust. The notebook and handoff are one memory at two
    # time-scales with one-directional flow (notebook → handoff at session end).
    #
    # Detection: /clear preserves the session_id (empirically confirmed). So the
    # signal is: does THIS session's own notebook exist and is it newer than the
    # handoff? If yes → /clear was run and Stop already wrote notebook state →
    # inject it. Otherwise → cold start → inject handoff.
    #
    # We do NOT fall back to other sessions' notebooks. A prior session's notebook
    # being newer than the handoff just means it was recently active — that's a
    # cold start and the handoff is the right thing to inject.
    #
    # Skeleton check: the distill might not have completed before SessionStart
    # fires after /clear. If the notebook still contains the unfilled placeholder
    # text it's a skeleton — inject the handoff instead (it has real content).
    try:
        context = read_vault_context(vault_root)

        # Placeholder lines written by ensure_stub() before the distiller runs.
        # If ALL four are still present the notebook is an unfilled skeleton.
        _SKELETON_MARKERS = (
            "(what we're actively doing",
            "(durable facts and decisions locked",
            "(unfinished threads / next steps",
            "(files or notes created or edited",
        )

        def _is_skeleton(text: str) -> bool:
            return sum(1 for m in _SKELETON_MARKERS if m in text) >= 3

        handoff_path = vault_root / ".brain" / f"handoff-{context}.md"
        handoff_mtime = handoff_path.stat().st_mtime if handoff_path.exists() else 0.0
        now = time.time()

        # Find the most recent non-skeleton notebook that is fresher than the
        # handoff and within NOTEBOOK_FRESH_HOURS. SessionStart is ALWAYS
        # source='startup' — /clear creates a new session_id every time — so
        # there is no "exact current session" to match. We just want the freshest
        # real notebook available, regardless of which session wrote it.
        injected_notebook = False
        brain_dir = vault_root / ".brain"
        best_mtime = handoff_mtime  # must beat the handoff to qualify
        best_content: str | None = None
        best_name: str = ""
        for nb in brain_dir.glob(f"notebook-{context}-*.md"):
            try:
                mtime = nb.stat().st_mtime
                age_h = (now - mtime) / 3600
                if mtime > best_mtime and age_h <= NOTEBOOK_FRESH_HOURS:
                    content = nb.read_text(encoding="utf-8")
                    if not _is_skeleton(content):
                        best_mtime = mtime
                        best_content = content
                        best_name = nb.name
            except OSError:
                pass

        if best_content is not None:
            lines.append("")
            lines.append(f"## 📓 Session notebook ({context}) — recent session state")
            lines.append(condense_digest(best_content, f".brain/{best_name}"))
            injected_notebook = True
            try:
                data_dir = vault_root / ".claude" / "data"
                stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                (data_dir / "session-start.log").open("a", encoding="utf-8").write(
                    f"[{stamp}] injected notebook: {best_name}\n"
                )
            except Exception:
                pass
        else:
            if handoff_path.exists():
                lines.append("")
                lines.append(f"## 🧠 Orchestrator handoff ({context}) — resume from here")
                lines.append(condense_digest(
                    handoff_path.read_text(encoding="utf-8"),
                    handoff_path.relative_to(vault_root).as_posix(),
                ))
            try:
                data_dir = vault_root / ".claude" / "data"
                stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                (data_dir / "session-start.log").open("a", encoding="utf-8").write(
                    f"[{stamp}] injected handoff (no fresh notebook found)\n"
                )
            except Exception:
                pass
    except Exception:
        traceback.print_exc(file=sys.stderr)

    # Surface gardener queue if non-empty (one-line pointer only — keep context lean).
    try:
        from graph_gardener import queue_summary  # noqa: PLC0415
        gardener_ctx = read_vault_context(vault_root)
        summary = queue_summary(vault_root, gardener_ctx)
        if summary:
            lines.append("")
            lines.append(summary)
    except Exception:
        pass  # fail-soft: never break session-start for gardener output

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": "\n".join(lines)
        }
    }))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc(file=sys.stderr)
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": "⚠️ Session start hook crashed. Check stderr."
            }
        }))
        sys.exit(1)
