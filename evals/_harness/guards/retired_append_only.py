"""Guard: retired.md may only ever gain entries, never lose or edit one.

Diffs ``$(VERSION_BASE)...HEAD`` (``ctx.base`` against ``HEAD``) on
``evals/<skill>/retired.md`` for every rostered skill, regardless of that
skill's activation status at either end of the diff. Parses the entry blocks
at both ends; fails if any entry present at base is missing at head, or
present at both but with any field (``date``, ``reason``, ``evidence``)
changed. A diff that only appends new entry blocks after the existing ones
passes.

This closes the same hole for ``retired.md`` that ``retirement_entry``
closes for ``checks.manifest``: if this guard were skipped once a skill
reads inactive, deleting its only ``retired.md`` entry would silently flip
it back to a state with no retirement record and no consequence. So this
guard has no activation precondition either.

Never reimplements the ``retired.md`` parser — imported from
``evals._harness.activation`` (owned by #996).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from evals._harness.activation import ROSTERED_SKILLS, parse_retired_entries
from evals._harness.guards import GuardContext, Result

_GUARD_NAME = "retired_append_only"


def _show_at(repo_root: Path, ref: str, rel_path: str) -> str:
    """Return *rel_path*'s text at the resolved commit *ref*, or "" if absent there."""
    result = subprocess.run(
        ["git", "-C", str(repo_root), "show", f"{ref}:{rel_path}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout if result.returncode == 0 else ""


def _read_at_head(repo_root: Path, rel_path: str) -> str:
    path = repo_root / rel_path
    return path.read_text(encoding="utf-8") if path.exists() else ""


def check(ctx: GuardContext) -> list[Result]:
    """Fail any edit or deletion of an existing ``retired.md`` entry.

    Parameters
    ----------
    ctx : GuardContext
        ``ctx.base`` is the PR's base ref; ``ctx.repo_root`` is the work
        tree to diff against it, checked out at HEAD.

    Returns
    -------
    list[Result]
        One ``fail`` per base-side entry missing at head, or present at
        head with any field changed.
    """
    # Three-dot semantics: read base-side content at the merge-base of the base
    # ref and HEAD, not the base tip, so a base branch that moved on after the
    # fork never reads as the PR undoing its changes. check=True: an
    # unresolvable base raises instead of reading as "absent at base".
    merge_base = subprocess.run(
        ["git", "-C", str(ctx.repo_root), "merge-base", ctx.base, "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    results: list[Result] = []
    for skill in ROSTERED_SKILLS:
        retired_rel = f"evals/{skill}/retired.md"
        base_entries = parse_retired_entries(_show_at(ctx.repo_root, merge_base, retired_rel))
        if not base_entries:
            continue
        head_entries = parse_retired_entries(_read_at_head(ctx.repo_root, retired_rel))

        head_by_id: dict[str, list[dict[str, str]]] = {}
        for entry in head_entries:
            head_by_id.setdefault(entry["id"], []).append(entry)

        for base_entry in base_entries:
            candidates = head_by_id.get(base_entry["id"], [])
            if base_entry in candidates:
                continue
            results.append(
                Result(
                    level="fail",
                    guard=_GUARD_NAME,
                    message=(
                        f"{skill}: retired.md entry {base_entry['id']!r} was "
                        "edited or removed"
                    ),
                )
            )
    return results
