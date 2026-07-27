"""Presets that a user installs side by side must not ship the same skill twice.

Claude Code registers every installed plugin's skills into one flat namespace, so
a slug shipped by two presets shows up twice in the picker (`workbench:commit` and
`workshop-maintainer:commit`) and both copies compete for the same trigger. The
cost is routing ambiguity plus a doubled context load, and neither preset's
manifest can see the collision on its own — only a cross-preset check can.

Some collisions are load-bearing. A Claude Code plugin is self-contained — an
agent's `skills.add` reference must resolve inside its own plugin (enforced by
`scripts/smoke_test.py`) — so a preset whose agents depend on a core skill has to
ship its own copy even when another installed preset already ships it. Those cases
are recorded in `ACCEPTED_COLLISIONS` with the reason. The allowlist is asserted
*exactly*, so a new collision fails here and a resolved one has to be removed
rather than lingering as cover for the next accident.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PRESETS_DIR = REPOSITORY_ROOT / "presets"
CORE_SKILLS_DIR = REPOSITORY_ROOT / "core/skills"

# slug -> (shipping presets, why the duplicate is required)
ACCEPTED_COLLISIONS: dict[str, tuple[tuple[str, ...], str]] = {
    # inject-skill-router.py reads skills/using-workflow/SKILL.md from its own
    # CLAUDE_PLUGIN_ROOT, so every preset carrying that hook must carry the skill.
    # The hook claims the router body once per session_id so only one copy of the
    # body reaches context; each preset still contributes its own conventions.
    "using-workflow": (
        ("vault-ops", "workbench", "workshop-maintainer"),
        "required in-plugin by inject-skill-router.py",
    ),
    "tdd": (
        ("workbench", "workshop-maintainer"),
        "workshop-maintainer's skill-builder agent lists it in skills.add",
    ),
    "commit": (
        ("workbench", "workshop-maintainer"),
        "workshop-maintainer's skill-builder agent lists it in skills.add",
    ),
    "daa-code-review": (
        ("workbench", "workshop-maintainer"),
        "workshop-maintainer's skill-reviewer agent lists it in skills.add",
    ),
    "grill-me": (
        ("workbench", "workshop-maintainer"),
        "workshop-maintainer pairs it with skill-inventory for design stress-tests",
    ),
}


def _all_core_skill_names() -> list[str]:
    return sorted(p.name for p in CORE_SKILLS_DIR.iterdir() if (p / "SKILL.md").is_file())


def _shipped_skills(manifest: dict) -> set[str]:
    """Resolve a manifest's shipped skill slugs, expanding the `"all"` shorthand."""
    core = manifest.get("core", {}).get("skills", [])
    names = set(_all_core_skill_names()) if core == "all" else set(core)
    names |= set(manifest.get("preset_skills", []))
    return names - set(manifest.get("exclude", []))


def _manifests() -> dict[str, dict]:
    return {
        path.parent.name: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(PRESETS_DIR.glob("*/manifest.json"))
    }


def _collisions() -> dict[str, tuple[str, ...]]:
    owners: dict[str, list[str]] = defaultdict(list)
    for preset, manifest in _manifests().items():
        for slug in _shipped_skills(manifest):
            owners[slug].append(preset)
    return {
        slug: tuple(sorted(presets))
        for slug, presets in owners.items()
        if len(presets) > 1
    }


def test_no_unaccounted_skill_slug_is_shipped_by_two_presets() -> None:
    """A slug in two presets registers twice in one session — that needs a reason."""
    unexpected = {
        slug: presets
        for slug, presets in _collisions().items()
        if slug not in ACCEPTED_COLLISIONS
    }
    assert not unexpected, (
        "these skill slugs are shipped by more than one preset and will register "
        "twice in one Claude Code session, competing for the same trigger: "
        f"{json.dumps({k: list(v) for k, v in unexpected.items()}, indent=2)}\n"
        "Give one preset sole ownership, or add an entry to ACCEPTED_COLLISIONS "
        "explaining why the duplicate is structurally required."
    )


def test_accepted_collisions_match_the_presets_that_actually_ship_them() -> None:
    """A stale allowlist entry would silently excuse a future, unrelated collision."""
    observed = _collisions()
    for slug, (presets, reason) in ACCEPTED_COLLISIONS.items():
        assert slug in observed, (
            f"{slug!r} is allowlisted ({reason}) but is no longer shipped by two "
            "presets — remove the entry so it stops excusing new collisions"
        )
        assert observed[slug] == presets, (
            f"{slug!r} is now shipped by {list(observed[slug])}, not the "
            f"allowlisted {list(presets)}"
        )


def test_router_skill_accompanies_the_router_hook() -> None:
    """A preset running `inject-skill-router.py` must ship the skill the hook reads."""
    for preset, manifest in _manifests().items():
        hooks = manifest.get("core", {}).get("hooks", [])
        if "inject-skill-router.py" not in hooks:
            continue
        assert "using-workflow" in _shipped_skills(manifest), (
            f"preset {preset!r} runs inject-skill-router.py but does not ship "
            "using-workflow, so the hook would inject conventions with no router"
        )
