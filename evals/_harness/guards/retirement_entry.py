"""Guard: a gated ID removed from checks.manifest must gain a valid retired.md entry.

Diffs ``$(VERSION_BASE)...HEAD`` (``ctx.base`` against ``HEAD``) on
``evals/<skill>/checks.manifest`` for every rostered skill, regardless of
that skill's activation status at either end of the diff. If a gated ID
present at base is absent at head, this fails unless ``evals/<skill>/retired.md``
gains a new entry for that same ID in the same diff — an entry whose ``##
<id>`` heading matches, present at head but not at base, holding a ``date``
in ``YYYY-MM-DD`` form, a ``reason`` that is exactly ``noise``, ``upkeep``,
``removed-by-design``, or ``superseded-by:<id>``, and a non-empty
``evidence``.

Making a skill inactive by removing its last gated ID must not be a way to
skip filing this entry, so this guard has no activation precondition at all
— unlike ``empty_gated_set``, the one guard in this issue scoped to active
skills.

Never reimplements the ``checks.manifest``/``retired.md`` parsers — both are
imported from ``evals._harness.activation`` (owned by #996).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from evals._harness.activation import ROSTERED_SKILLS, parse_checks_manifest, parse_retired_entries
from evals._harness.guards import GuardContext, Result

_GUARD_NAME = "retirement_entry"
_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_REASON_PATTERN = re.compile(
    r"^(noise|upkeep|removed-by-design|superseded-by:[A-Za-z0-9][A-Za-z0-9._-]*)$"
)


def _show_at(repo_root: Path, ref: str, rel_path: str) -> str:
    """Return *rel_path*'s text at *ref*, or "" if it does not exist there."""
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


def _is_valid_new_entry(entry: dict[str, str]) -> bool:
    if not _DATE_PATTERN.match(entry.get("date", "")):
        return False
    if not _REASON_PATTERN.match(entry.get("reason", "")):
        return False
    return bool(entry.get("evidence", "").strip())


def check(ctx: GuardContext) -> list[Result]:
    """Fail a gated-ID removal from ``checks.manifest`` with no matching retirement.

    Parameters
    ----------
    ctx : GuardContext
        ``ctx.base`` is the PR's base ref; ``ctx.repo_root`` is the work
        tree to diff against it, checked out at HEAD.

    Returns
    -------
    list[Result]
        One ``fail`` per gated ID removed from a skill's manifest without a
        valid, newly-added ``retired.md`` entry for it in the same diff.
    """
    results: list[Result] = []
    for skill in ROSTERED_SKILLS:
        manifest_rel = f"evals/{skill}/checks.manifest"
        base_ids = set(parse_checks_manifest(_show_at(ctx.repo_root, ctx.base, manifest_rel)))
        head_ids = set(parse_checks_manifest(_read_at_head(ctx.repo_root, manifest_rel)))
        removed_ids = base_ids - head_ids
        if not removed_ids:
            continue

        retired_rel = f"evals/{skill}/retired.md"
        base_entries = parse_retired_entries(_show_at(ctx.repo_root, ctx.base, retired_rel))
        head_entries = parse_retired_entries(_read_at_head(ctx.repo_root, retired_rel))

        new_entries_by_id: dict[str, list[dict[str, str]]] = {}
        for entry in head_entries:
            if entry not in base_entries:
                new_entries_by_id.setdefault(entry["id"], []).append(entry)

        for removed_id in sorted(removed_ids):
            candidates = new_entries_by_id.get(removed_id, [])
            if any(_is_valid_new_entry(entry) for entry in candidates):
                continue
            results.append(
                Result(
                    level="fail",
                    guard=_GUARD_NAME,
                    message=(
                        f"{skill}: gated id {removed_id!r} removed from checks.manifest "
                        "with no valid retired.md entry added in this diff"
                    ),
                )
            )
    return results
