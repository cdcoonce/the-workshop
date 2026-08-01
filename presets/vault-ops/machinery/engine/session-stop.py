#!/usr/bin/env python3
"""Explicit sync helper retained for compatibility.

Lifecycle Stop events are not evidence that the user ended the session. Syncing
there can sweep unrelated work from the shared checkout, so callers must pass
``--explicit-sync`` to authorize a commit and push.

Exit codes:
    0 — sync complete (or no changes)
    1 — sync failed
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import traceback
from pathlib import Path

# Add scripts dir to path
SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from glossary_manager import parse_glossary
from session_terms import changed_files_since
from sync_manager import push
from term_tracker import record_terms
from vault_utils import find_vault_root_from_env


def _vault_health_check(cwd: Path) -> tuple[bool, str]:
    """Run ``ci/vault_health.py`` as a pre-push gate, if the vault has one.

    Not every consumer of this vendored engine ships that script, and a missing
    or misbehaving checker must never be able to block sync — so absence, a
    timeout, or any other failure to run it is treated as a pass (fail-open).
    Only an actual regression reported by the script blocks the push.
    """
    script = cwd / "ci" / "vault_health.py"
    if not script.exists():
        return True, ""
    try:
        result = subprocess.run(
            ["uv", "run", str(script)],
            cwd=cwd, capture_output=True, text=True, check=False, timeout=30,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return True, ""
    if result.returncode == 0:
        return True, ""
    detail = result.stderr.strip() or result.stdout.strip()
    return False, detail


def _sync_branch_status(vault_root: Path) -> tuple[bool, str, str]:
    """Return (on_sync_branch, current_branch, default_branch).

    The auto-commit hook should only fire on the default sync branch (main).
    On a feature branch, deliberate per-commit work wins — auto-sync would
    sweep WIP and interleave noise commits with curated ones. `/sync` still
    works on any branch when the user explicitly asks for it.
    """
    cur = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=vault_root, capture_output=True, text=True, check=False, timeout=10,
    ).stdout.strip()
    head = subprocess.run(
        ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
        cwd=vault_root, capture_output=True, text=True, check=False, timeout=10,
    )
    default = head.stdout.strip().rsplit("/", 1)[-1] if head.returncode == 0 else "main"
    if not default:
        default = "main"
    return (cur == default, cur, default)


def main() -> int:
    if "--explicit-sync" not in sys.argv[1:]:
        print(json.dumps({"systemMessage": (
            "Git sync skipped — run /sync or /wrap-up explicitly to commit and push."
        )}))
        return 0

    # Anchor to the project Claude Code launched in (the vault), NOT the shell's
    # current directory — a session may have `cd`'d into another repo, and we must
    # never auto-commit that repo. find_vault_root_from_env() additionally requires
    # the vault signature, so a non-vault CLAUDE_PROJECT_DIR resolves to None.
    vault_root = find_vault_root_from_env()
    if vault_root is None:
        return 0  # Not in vault — silently skip

    lines: list[str] = []

    # Auto-sync only on the default branch. On a feature branch, skip the
    # commit/push so deliberate work isn't swept into auto-sync commits.
    on_sync_branch, cur_branch, default_branch = _sync_branch_status(vault_root)
    if not on_sync_branch:
        print(json.dumps({"systemMessage": (
            f"⏸️ Auto-sync paused — on feature branch '{cur_branch}' "
            f"(not '{default_branch}'). Commit deliberately; run /sync to push."
        )}))
        return 0

    # Capture HEAD before push so term tracking can tell whether THIS session committed
    # (a no-op session must not re-count a prior commit's files — see session_terms).
    pre_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=vault_root,
        capture_output=True, text=True, check=False, timeout=10,
    ).stdout.strip()

    # Push changes — gated on vault health so a regression (e.g. a broken
    # wikilink from /garden, /connect, or a manual edit) is committed locally
    # but never pushed to the shared remote unvetted.
    result = push(vault_root, pre_push_check=_vault_health_check)
    if result.success:
        lines.append(f"✓ Git: {result.message}")
    else:
        lines.append(f"⚠️ Git sync failed: {result.message}")

    # Update term frequency from files changed this session (best-effort)
    try:
        glossary_path = vault_root / "brain" / "Glossary.md"
        if glossary_path.exists():
            # Only the files THIS session committed (empty on a no-op session) — fixes term
            # frequency drifting from a prior commit's files when nothing changed.
            changed_files = [
                vault_root / f
                for f in changed_files_since(vault_root, pre_sha)
                if f.endswith(".md")
            ]

            if changed_files:
                changed_content = ""
                for cf in changed_files:
                    if cf.exists():
                        try:
                            changed_content += cf.read_text(encoding="utf-8") + "\n"
                        except (OSError, UnicodeDecodeError):
                            pass

                known_terms = [e.term for e in parse_glossary(glossary_path)]
                # Pass one element per occurrence so record_terms can grow
                # `count` by total occurrences (`sessions` grows by 1 per term).
                used_terms = [
                    t for t in known_terms
                    for _ in re.findall(rf"\b{re.escape(t)}\b", changed_content)
                ]
                distinct_terms = len(set(used_terms))

                if used_terms:
                    record_terms(vault_root, used_terms)
                    lines.append(
                        f"✓ Term frequency: tracked {distinct_terms} terms "
                        f"from {len(changed_files)} changed files"
                    )
                else:
                    lines.append("✓ Term frequency: no known terms in changed files")
            else:
                lines.append("✓ Term frequency: no changes this session")
    except Exception:
        lines.append("⚠️ Term frequency tracking skipped (non-critical error)")

    # Session end checklist
    lines.append("")
    lines.append("Session checklist:")
    lines.append("  • Are all new notes linked to the graph?")
    lines.append("  • Are indexes up to date?")
    lines.append("  • Any notes ready to archive?")

    print(json.dumps({"systemMessage": "\n".join(lines)}))
    return 0 if result.success else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc(file=sys.stderr)
        print(json.dumps({
            "systemMessage": "⚠️ Session stop hook crashed. Changes may not be synced."
        }))
        sys.exit(1)
