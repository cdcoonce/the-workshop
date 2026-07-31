"""Ownership and discipline contract for the `adversarial-review` skill.

The capability is attacking finished work: enumerating what the work claims and
trying to disprove each claim, rather than reading it and pronouncing it sound.
That is universal to any repo, so `core/` is the canonical owner.

Membership is the part worth pinning. `workbench` takes `core.skills: "all"`, so
existence under `core/` is sufficient for it to ship — and every *explicit*
manifest must leave it alone, or the skill lands in two plugins and the
one-plugin-per-skill direction erodes silently the first time someone adds it to
a second list "just to have it there".

The rest of these tests pin the machinery that makes the skill adversarial rather
than merely another reviewer. A review skill degrades in one direction only: it
reads the work, finds it plausible, and reports a clean bill of health. Each
assertion below guards one of the load-bearing parts that failure routes around.
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SLUG = "adversarial-review"
SKILL_DIR = REPO_ROOT / "core" / "skills" / SLUG

SIBLING_REVIEWERS = (
    "plan-ceo-review",
    "security-review",
    "daa-code-review",
    "detector-teeth-check",
)


def _skill_text() -> str:
    return (SKILL_DIR / "SKILL.md").read_text()


def _description() -> str:
    """The frontmatter description — the only thing the router matches on."""
    text = _skill_text()
    assert text.startswith("---"), f"{SLUG}: no frontmatter"
    frontmatter = text.split("---", 2)[1]
    body: list[str] = []
    for line in frontmatter.splitlines():
        if line.startswith("description:"):
            body.append(line.split(":", 1)[1].strip())
        elif body and line.startswith((" ", "\t")):
            body.append(line.strip())
        elif body:
            break
    assert body, f"{SLUG}: frontmatter has no description"
    return " ".join(part for part in body if part not in {">", "|"})


def test_skill_is_owned_by_core() -> None:
    """Universal capability: core owns it, and `workbench` ships it via
    `core.skills: "all"` without a manifest edit."""
    assert (SKILL_DIR / "SKILL.md").is_file()


def test_no_explicit_preset_manifest_also_ships_it() -> None:
    """One skill, one plugin. Any preset that lists `core.skills` explicitly must
    not name this skill, or it ships from two packages at once."""
    for manifest_path in sorted(REPO_ROOT.glob("presets/*/manifest.json")):
        manifest = json.loads(manifest_path.read_text())
        core_skills = manifest.get("core", {}).get("skills", [])
        if core_skills == "all":
            continue
        assert SLUG not in core_skills, (
            f"{manifest_path.parent.name} lists {SLUG} explicitly; it already "
            "ships via workbench's core.skills: all"
        )


def test_skill_md_stays_under_the_line_budget() -> None:
    """Progressive disclosure: the invocation-loaded file stays readable."""
    line_count = len(_skill_text().splitlines())
    assert line_count < 100, f"SKILL.md is {line_count} lines"


def test_description_is_trigger_only() -> None:
    """The description is a retrieval index, not a spec. An agent that reads a
    workflow-bearing description executes the lossy summary instead of the body."""
    description = _description()
    assert len(description) < 1024
    assert "use when" in description.lower()
    assert "→" not in description, "description narrates a step chain"
    assert "phase" not in description.lower(), "description leaks phase structure"


def test_every_referenced_file_exists() -> None:
    """A dangling reference link silently drops the part of the skill it points at."""
    text = _skill_text()
    for reference in (SKILL_DIR / "references").glob("*.md"):
        assert reference.name in text, (
            f"{reference.name} exists but SKILL.md never links to it"
        )
    for line in text.splitlines():
        if "references/" not in line:
            continue
        fragment = line.split("references/", 1)[1]
        name = fragment.split(")")[0].split("]")[0].split(" ")[0].split("#")[0]
        assert (SKILL_DIR / "references" / name).is_file(), f"missing references/{name}"


def test_references_are_one_level_deep() -> None:
    """Never nest a references directory inside another."""
    assert not list((SKILL_DIR / "references").glob("*/*"))


def test_carries_the_iron_law_without_a_nuance_clause() -> None:
    """An Iron Law with an exception clause is not a law — every future
    rationalization routes through the clause instead of confronting the law."""
    text = _skill_text()
    law = "NO CLAIM PASSES WITHOUT A DISPROOF ATTEMPT THAT COULD HAVE FAILED IT."
    assert law in text, "the Iron Law is missing or reworded"
    line = next(line for line in text.splitlines() if law in line)
    for hedge in ("unless", "except", "when practical", "if time"):
        assert hedge not in line.lower(), f"Iron Law carries a nuance clause: {hedge!r}"


def test_requires_an_unverified_coverage_section() -> None:
    """The clean-bill-of-health failure. An empty findings list means nothing
    unless the review also states what it could not reach, so the omission has to
    be visible as a blank template slot rather than a silent gap."""
    text = _skill_text().lower()
    assert "could not verify" in text
    assert "required" in text, "the report slots are not marked required"


def test_separates_reproduced_findings_from_argued_ones() -> None:
    """Reasoning promoted to evidence is where AI reviewers generate confident
    noise. A finding without a concrete trigger is capped, not asserted."""
    text = _skill_text().lower()
    assert "plausible" in text
    assert "confirmed" in text
    assert "refuted" in text


def test_sets_an_escalation_threshold_as_a_number() -> None:
    """Vague thresholds ('if it's taking too long') do not trigger; a number does."""
    text = _skill_text().lower()
    assert "3 " in text or "three " in text, "no numeric escalation threshold"


def test_is_read_only() -> None:
    """A reviewer that starts fixing stops reviewing, and its findings become
    unauditable because the evidence moved underneath them."""
    text = _skill_text().lower()
    assert "read-only" in text or "never fix" in text or "does not fix" in text


def test_names_its_boundary_against_every_sibling_reviewer() -> None:
    """Four review-shaped skills already exist. Without an explicit boundary the
    router fires two of them at the same request."""
    text = _skill_text()
    for sibling in SIBLING_REVIEWERS:
        assert sibling in text, f"SKILL.md never distinguishes itself from {sibling}"


def test_does_not_claim_a_sibling_reviewers_quoted_trigger() -> None:
    """`smoke_test` lints this globally; pinning it here keeps the failure legible."""
    description = _description().lower()
    for stolen in ('"code review"', '"security review"', '"plan review"'):
        assert stolen not in description


def test_ships_pressure_scenarios_with_a_recorded_red_baseline() -> None:
    """A discipline skill written from guesses about what needs preventing encodes
    the author's assumptions. Only scenarios with an observed no-skill failure
    earn a place in the suite."""
    tests_md = (SKILL_DIR / "tests.md").read_text().lower()
    assert "no-skill" in tests_md or "no skill" in tests_md
    assert tests_md.count("observed no-skill red") >= 2, (
        "fewer than 2 scenarios have an observed no-skill failure recorded"
    )
    assert "discarded" in tests_md, (
        "scenarios the no-skill baseline already passed must be recorded as "
        "discarded, or someone re-derives them"
    )
