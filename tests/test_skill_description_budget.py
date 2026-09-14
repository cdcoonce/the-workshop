"""Listing budget: model-invocable workbench skill descriptions must stay short.

Claude Code loads every skill's name and description into a listing capped at a
share of the model's context window (`skillListingBudgetFraction`, default 1%).
When the listing overflows it keeps every name but drops descriptions, starting
with the least-invoked skills — and a name-only skill almost never triggers on
its own. On 2026-09-14 a fresh Opus session still received 17 of 55
model-invocable workbench skills name-only: the listing sat at its ~30k-char cap,
and workbench's descriptions got ~13.6k chars of it while asking for ~19k.

Two guards follow. A per-skill cap stops any one description from crowding out
the rest, and pushes the key trigger to the front because a long tail no longer
fits. A plugin total keeps the sum inside the share workbench actually receives,
so adding a model-invocable skill forces a trim (or `disable-model-invocation:
true`) instead of silently evicting another skill's description.

Skills flagged `disable-model-invocation: true` are exempt: they are absent from
the listing, so their descriptions cost nothing.

Lengths are measured on the parsed frontmatter string with whitespace collapsed
(block scalars fold to single spaces), which is what the listing carries — not
raw file bytes.
"""

from __future__ import annotations

from pathlib import Path

from tests.test_skill_invocation_chains import Skill, _discover_skills, _is_flagged

# Per-skill ceiling. At 250, all 55 listed workbench descriptions total ~13.2k.
MAX_DESCRIPTION_CHARS = 250

# Share of the listing workbench descriptions received in the 2026-09-14 session
# (13,583 chars, other plugins enabled). The real share depends on what else is
# installed, so this is a tripwire for growth, not an exact fit.
WORKBENCH_DESCRIPTION_BUDGET = 13_500


def _description(skill: Skill) -> str:
    value = skill.frontmatter.get("description")
    return " ".join(value.split()) if isinstance(value, str) else ""


def listed_skills(skills: dict[str, Skill], plugin: str = "workbench") -> list[Skill]:
    """Skills of `plugin` that appear in the model's listing (not flagged)."""
    return [s for s in skills.values() if s.plugin == plugin and not _is_flagged(s)]


def over_cap(skills: list[Skill], cap: int) -> dict[str, int]:
    return {
        s.slug: len(_description(s)) for s in skills if len(_description(s)) > cap
    }


def total_chars(skills: list[Skill]) -> int:
    return sum(len(_description(s)) for s in skills)


def test_every_listed_workbench_skill_has_a_description():
    """An absent description measures 0 and would pass both caps vacuously."""
    listed = listed_skills(_discover_skills())
    assert listed, "discovered no model-invocable workbench skills"
    missing = sorted(s.slug for s in listed if not _description(s))
    assert not missing, f"model-invocable skills without a description: {missing}"


def test_every_listed_workbench_description_fits_the_per_skill_cap():
    over = over_cap(listed_skills(_discover_skills()), MAX_DESCRIPTION_CHARS)
    report = ", ".join(f"{slug} ({n})" for slug, n in sorted(over.items(), key=lambda kv: -kv[1]))
    assert not over, (
        f"{len(over)} description(s) exceed {MAX_DESCRIPTION_CHARS} chars — lead with the "
        f"key trigger and cut the rest, or flag the skill disable-model-invocation: {report}"
    )


def test_listed_workbench_descriptions_fit_the_plugin_budget():
    total = total_chars(listed_skills(_discover_skills()))
    assert total <= WORKBENCH_DESCRIPTION_BUDGET, (
        f"model-invocable workbench descriptions total {total} chars, over the "
        f"{WORKBENCH_DESCRIPTION_BUDGET}-char share of the skill listing; trim descriptions "
        f"or flag an explicit-invoke skill disable-model-invocation"
    )


def _synthetic(slug: str, description: str, flag: object | None) -> Skill:
    frontmatter: dict = {"name": slug, "description": description}
    if flag is not None:
        frontmatter["disable-model-invocation"] = flag
    return Skill(slug=slug, plugin="workbench", dir=Path(slug), frontmatter=frontmatter)


def test_only_a_true_flag_exempts_a_skill_from_both_guards():
    long_text = "x " * 450
    skills = {
        "flagged": _synthetic("flagged", long_text, "true"),
        "opted-out": _synthetic("opted-out", long_text, "false"),
        "plain": _synthetic("plain", "short trigger", None),
    }
    listed = listed_skills(skills)
    assert sorted(s.slug for s in listed) == ["opted-out", "plain"]
    assert set(over_cap(listed, MAX_DESCRIPTION_CHARS)) == {"opted-out"}
    assert total_chars(listed) == len(" ".join(long_text.split())) + len("short trigger")
