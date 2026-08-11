"""One plugin per slug, globally — no exceptions, no allowlist.

Claude Code registers every installed plugin's skills into one flat namespace,
so a slug shipped by two plugins shows up twice in the picker
(`workbench:commit` and `workshop-maintainer:commit`) and both copies compete
for the same trigger. The cost is routing ambiguity plus a doubled context load.

This file used to carry an `ACCEPTED_COLLISIONS` allowlist, because under the
composition build a duplicate was sometimes structurally required: a plugin was
a closed bundle, so an agent's `skills.add` had to resolve inside its own
plugin, and a plugin whose agents leaned on a shared skill had to ship a copy.
The flat reorg removed the closure — `scripts/smoke_test.py` now resolves a
skill reference across the whole `plugins/` tree — so every entry on that
allowlist became a duplicate with no remaining justification. The allowlist is
gone with them, and the invariant is absolute.

That absoluteness is what `improve-skill` depends on: it resolves a skill by a
flat `plugins/*/skills/<slug>/` glob and treats a second hit as a repo defect,
because with two copies it would edit one and ship the other.

`scripts/stamp.py` fails on a duplicate at generation time. This file checks the
committed tree independently, so the invariant survives someone bypassing the
stamper.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PLUGINS_DIR = REPOSITORY_ROOT / "plugins"


def _owners() -> dict[str, list[str]]:
    """slug -> every plugin directory shipping it."""
    owners: dict[str, list[str]] = defaultdict(list)
    for skill_md in sorted(PLUGINS_DIR.glob("*/skills/*/SKILL.md")):
        owners[skill_md.parent.name].append(skill_md.parents[2].name)
    return owners


def test_no_skill_slug_is_shipped_by_two_plugins() -> None:
    """A slug in two plugins registers twice in one session and splits its trigger."""
    collisions = {
        slug: sorted(plugins)
        for slug, plugins in _owners().items()
        if len(plugins) > 1
    }
    assert not collisions, (
        "these skill slugs are shipped by more than one plugin and will register "
        "twice in one Claude Code session, competing for the same trigger:\n"
        f"{json.dumps(collisions, indent=2)}\n"
        "Give one plugin sole ownership. There is no allowlist: an agent in "
        "another plugin can reference the skill by slug without a local copy."
    )


def test_every_skill_directory_is_a_real_skill() -> None:
    """A skills/ subdirectory with no SKILL.md is invisible to the picker.

    It also slips past the collision check above, which keys on SKILL.md — so a
    half-migrated skill could sit in two plugins and be caught by neither.
    """
    empty = [
        d.relative_to(REPOSITORY_ROOT).as_posix()
        for d in sorted(PLUGINS_DIR.glob("*/skills/*"))
        if d.is_dir() and not (d / "SKILL.md").is_file()
    ]
    assert not empty, f"skill directories with no SKILL.md: {empty}"


def test_the_router_skill_ships_beside_the_router_hook() -> None:
    """`inject-skill-router.py` reads using-workflow from its OWN plugin root.

    The hook resolves `skills/using-workflow/SKILL.md` relative to the plugin it
    ships in, not across the tree — so unlike an agent's `skills.add`, this
    coupling did NOT relax when plugins stopped being closed bundles. A plugin
    that runs the router without the skill injects conventions with no router.
    """
    for hook in sorted(PLUGINS_DIR.glob("*/hooks/scripts/inject-skill-router.py")):
        plugin = hook.parents[2]
        assert (plugin / "skills" / "using-workflow" / "SKILL.md").is_file(), (
            f"plugin {plugin.name!r} runs inject-skill-router.py but does not "
            "ship using-workflow, so the hook would inject conventions with no "
            "router body"
        )
