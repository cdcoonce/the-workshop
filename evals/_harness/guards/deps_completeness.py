"""Guard: a rostered skill's SKILL.md never links a file its deps direct tier omits.

For each rostered skill, parses its ``SKILL.md`` for relative Markdown links
(excluding ``http://``/``https://`` targets), resolves each against the
skill's own directory, and fails if any resolved path is a tracked file
that its ``deps`` file's ``direct`` list does not cover. Runs regardless of
a skill's active/inactive status — an incomplete direct tier is a defect in
the scaffolding itself, not something activation state excuses.

Never reimplements ``deps`` TOML parsing or tier expansion — both are
imported from ``evals._harness.deps`` (owned by #993).
"""

from __future__ import annotations

import posixpath
import re

from evals._harness.activation import ROSTERED_SKILLS
from evals._harness.deps import expand_paths, parse_deps
from evals._harness.guards import GuardContext, Result

_GUARD_NAME = "deps_completeness"
_SKILLS_ROOT = "plugins/workbench/skills"
_LINK_PATTERN = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def _markdown_link_targets(text: str) -> list[str]:
    """Return every relative Markdown link target in *text*, in file order."""
    targets: list[str] = []
    for raw_target in _LINK_PATTERN.findall(text):
        target = raw_target.split(" ", 1)[0].strip()
        if target.startswith("http://") or target.startswith("https://"):
            continue
        target = target.split("#", 1)[0]
        if target:
            targets.append(target)
    return targets


def check(ctx: GuardContext) -> list[Result]:
    """Check every rostered skill's SKILL.md links against its deps direct tier.

    Parameters
    ----------
    ctx : GuardContext
        Shared guard context; only ``ctx.repo_root`` is used — this guard
        checks the state at HEAD (the work tree as checked out), not a
        base-relative diff.

    Returns
    -------
    list[Result]
        One ``fail`` per SKILL.md link that resolves to a tracked file
        absent from that skill's deps direct tier.
    """
    results: list[Result] = []
    for skill in ROSTERED_SKILLS:
        skill_dir_rel = f"{_SKILLS_ROOT}/{skill}"
        skill_md_path = ctx.repo_root / skill_dir_rel / "SKILL.md"
        deps_path = ctx.repo_root / "evals" / skill / "deps"
        if not skill_md_path.exists() or not deps_path.exists():
            continue

        deps = parse_deps(deps_path.read_text(encoding="utf-8"))
        covered = set(expand_paths(deps["direct"], ref="HEAD", repo=ctx.repo_root))

        skill_md_text = skill_md_path.read_text(encoding="utf-8")
        for link in _markdown_link_targets(skill_md_text):
            resolved = posixpath.normpath(posixpath.join(skill_dir_rel, link))
            tracked = expand_paths([resolved], ref="HEAD", repo=ctx.repo_root)
            if not tracked:
                # Not a tracked file (e.g. an external or generated path) —
                # nothing for the direct tier to cover.
                continue
            if resolved not in covered:
                results.append(
                    Result(
                        level="fail",
                        guard=_GUARD_NAME,
                        message=(
                            f"{skill}: SKILL.md links {link} ({resolved}) which is "
                            f"not covered by evals/{skill}/deps' direct tier"
                        ),
                    )
                )
    return results
