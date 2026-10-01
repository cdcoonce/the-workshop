"""Guard: warn when a change touches any prompt-injection-tier path.

Diffs ``$(VERSION_BASE)...HEAD`` (``ctx.base`` against ``HEAD``) and warns if
any of the nine named injection-tier paths changed — the hooks wiring and
the skill-router that decide what gets injected into a session. Never
fails: this is a heads-up for review, not a gate, and it never forces
recalibration.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from evals._harness.guards import GuardContext, Result

_GUARD_NAME = "injection_tier_warn"

_WATCHED_PATHS = (
    "plugins/workbench/hooks/hooks.json",
    "plugins/workbench/hooks/run-hook.sh",
    "plugins/workbench/hooks/run-vault-hook.sh",
    "plugins/workbench/hooks/scripts/inject-skill-router.py",
    "plugins/workbench/hooks/scripts/vault-session-start.py",
    "plugins/workbench/hooks/scripts/snapshot-subagent-start.py",
    "plugins/workbench/hooks/scripts/suggest-handoff-on-context.py",
    "plugins/workbench/hooks/scripts/vault-skill-alias.py",
    "plugins/workbench/skills/using-workflow/SKILL.md",
)


def _changed_paths(repo_root: Path, base: str) -> set[str]:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "diff", "--no-renames", "--name-only", f"{base}...HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    return {line for line in result.stdout.splitlines() if line}


def check(ctx: GuardContext) -> list[Result]:
    """Warn when the diff touches any injection-tier path.

    Parameters
    ----------
    ctx : GuardContext
        ``ctx.base`` is the PR's base ref; ``ctx.repo_root`` is the work
        tree to diff against it, checked out at HEAD.

    Returns
    -------
    list[Result]
        A single ``warn`` naming every touched injection-tier path, or an
        empty list if none changed.
    """
    changed = _changed_paths(ctx.repo_root, ctx.base)
    touched = sorted(set(_WATCHED_PATHS) & changed)
    if not touched:
        return []
    return [
        Result(
            level="warn",
            guard=_GUARD_NAME,
            message=f"injection-tier paths changed: {', '.join(touched)}",
        )
    ]
