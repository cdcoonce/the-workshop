"""Ownership and discipline contract for the `wayfinder` skill.

The capability is charting an effort too big for one agent session as a shared
map of decision tickets on the repo's issue tracker, then resolving them one
per session until the way to the destination is clear. Planning at that scale
is universal to any repo, so `core/` is the canonical owner and `workbench`
ships it via `core.skills: "all"` without a manifest edit.

The rest of these tests pin the machinery that keeps the skill a planner
rather than a builder. A planning skill degrades in two directions: it starts
executing the work it was meant to chart, or it quietly drops the shared-state
discipline (claims, blocking edges, the decision index) that makes the map
safe for concurrent sessions. Each assertion guards a part that one of those
failures routes around.
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SLUG = "wayfinder"
SKILL_DIR = REPO_ROOT / "core" / "skills" / SLUG

SIBLING_PLANNERS = ("brainstorm", "grill-me", "write-a-prd", "prd-to-plan")

# The vault-linkage prose names Index headings that the vault's session-start
# digest scrapes by exact name (DIGEST_BUCKETS). Both sides live in this repo,
# so drift between them is testable — and silent if untested.
DIGEST_HEADINGS = ("Active Projects", "Side Projects", "Courses")
CONTEXT_LOADER = (
    REPO_ROOT / "presets" / "vault-ops" / "machinery" / "engine" / "context_loader.py"
)

REMOTE_TRACKERS = ("tracker-github.md", "tracker-gitlab.md")


def _skill_text() -> str:
    return (SKILL_DIR / "SKILL.md").read_text()


def _flat(text: str) -> str:
    """Collapse whitespace so phrase pins survive formatter re-wrapping."""
    return " ".join(text.split())


def _reference(name: str) -> str:
    return (SKILL_DIR / "references" / name).read_text()


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
    """One skill, one plugin. Any preset that lists `core.skills` explicitly
    must not name this skill, or it ships from two packages at once. vault-ops
    co-membership was considered and permanently rejected (2026-08-01)."""
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


def test_description_is_trigger_only_and_explicit_invocation() -> None:
    """The description is a retrieval index, not a spec — and upstream's
    `disable-model-invocation` frontmatter cannot be carried here, so the
    explicit `/wayfinder` trigger is the description's job."""
    description = _description()
    assert len(description) < 1024
    assert "use when" in description.lower()
    assert "/wayfinder" in description, "explicit invocation trigger missing"
    assert "→" not in description, "description narrates a step chain"
    assert "phase" not in description.lower(), "description leaks structure"


def test_every_referenced_file_exists() -> None:
    """A dangling reference link silently drops the part of the skill it
    points at."""
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
        assert (SKILL_DIR / "references" / name).is_file(), (
            f"missing references/{name}"
        )


def test_references_are_one_level_deep() -> None:
    """Never nest a references directory inside another."""
    assert not list((SKILL_DIR / "references").glob("*/*"))


def test_carries_the_planning_law_without_a_nuance_clause() -> None:
    """The skill's one-direction failure is sliding from deciding into doing.
    A law with an exception clause is not a law — every rationalization routes
    through the clause. (The Notes-override upstream allows lives elsewhere,
    never on the law line.)"""
    text = _skill_text()
    law = "PRODUCE DECISIONS, NOT DELIVERABLES."
    assert law in text, "the planning law is missing or reworded"
    line = next(line for line in text.splitlines() if law in line)
    for hedge in ("unless", "except", "when practical", "if time"):
        assert hedge not in line.lower(), f"law carries a nuance clause: {hedge!r}"


def test_claim_comes_before_any_work() -> None:
    """Claim-by-assignee is what makes concurrent sessions safe. A session
    that starts resolving before claiming races every other session."""
    text = _flat(_skill_text()).lower()
    assert "claim" in text
    assert "before any work" in text, "claim-first ordering is not stated"


def test_one_ticket_per_session_with_research_exception() -> None:
    """The sizing contract: tickets are one-session-sized, so a session that
    resolves two has stopped planning and started sprinting."""
    text = _flat(_skill_text()).lower()
    assert "one ticket per session" in text
    assert "research" in text, "the research exception is missing"


def test_hitl_contract_forbids_self_answering() -> None:
    """A grilling agent that answers its own questions has broken the
    human-in-the-loop contract — the failure mode that makes HITL tickets
    silently worthless."""
    text = _flat(_skill_text() + _reference("map-and-tickets.md")).lower()
    assert "hitl" in text
    assert "never" in text and "own" in text, (
        "the self-answering prohibition is missing"
    )


def test_work_flow_disambiguates_the_empty_frontier() -> None:
    """'No tickets' is the success terminal state and 'all blocked' is a
    wiring defect; a skill that cannot tell them apart misreports one as the
    other."""
    text = _flat(_skill_text()).lower()
    assert "all blocked" in text
    assert "all claimed" in text
    assert "cycle" in text, "dependency-cycle outcome is not named"


def test_names_its_boundary_against_every_sibling_planner() -> None:
    """Planning-shaped skills already exist. Without an explicit boundary the
    router fires two of them at the same request."""
    text = _skill_text()
    for sibling in SIBLING_PLANNERS:
        assert sibling in text, (
            f"SKILL.md never distinguishes itself from {sibling}"
        )


def test_remote_trackers_carry_the_positive_label_guard() -> None:
    """afk's pickers scan labels positively (`proposed`, `decompose:ready`),
    and wayfinder maps can share a repo with afk's backlog. The guard must be
    stated positively — wayfinder labels only — so future afk vocabulary stays
    excluded by construction."""
    for tracker in REMOTE_TRACKERS:
        text = _flat(_reference(tracker))
        assert "only `wayfinder:" in text.lower(), (
            f"{tracker}: labels-only guard missing"
        )
        assert "proposed" in text, (
            f"{tracker}: the named afk example labels are missing"
        )


def test_vault_linkage_headings_match_the_digest_scraper() -> None:
    """The map stub surfaces only via an Index bullet under a heading the
    vault's session-start digest scrapes by exact name. Both sides live in
    this repo; this is the drift check."""
    linkage = _reference("map-and-tickets.md")
    scraper = CONTEXT_LOADER.read_text()
    for heading in DIGEST_HEADINGS:
        assert heading in linkage, (
            f"map-and-tickets.md never names the '{heading}' Index heading"
        )
        assert heading in scraper, (
            f"context_loader.py DIGEST_BUCKETS no longer scrapes '{heading}' "
            "— the wayfinder vault-linkage prose is now stale"
        )


def test_vault_linkage_never_fails_silent() -> None:
    """Charting from a non-vault cwd (project repos are vault siblings) must
    leave a visible pending marker, not silently skip the stub."""
    linkage = _flat(_reference("map-and-tickets.md"))
    assert "Vault linkage: pending" in linkage


def test_research_findings_are_reviewed_before_closing() -> None:
    """A research subagent's output auto-closing its ticket would let garbage
    findings become recorded decisions."""
    text = _flat(_reference("map-and-tickets.md")).lower()
    assert "reviews the findings" in text
    assert "never auto-close" in text


def test_local_tracker_keeps_school_maps_under_school() -> None:
    """The vault's attention ledger attributes by path; a school map filed
    elsewhere hides the drop in building time it causes."""
    text = _reference("tracker-local.md")
    assert "school/" in text


def test_ships_pressure_scenarios_with_a_recorded_red_baseline() -> None:
    """A discipline skill written from guesses about what needs preventing
    encodes the author's assumptions. Only scenarios with an observed no-skill
    failure earn a place in the suite."""
    tests_md = (SKILL_DIR / "tests.md").read_text().lower()
    assert "no-skill" in tests_md or "no skill" in tests_md
    assert tests_md.count("observed no-skill red") >= 2, (
        "fewer than 2 scenarios have an observed no-skill failure recorded"
    )
    assert "discarded" in tests_md, (
        "scenarios the no-skill baseline already passed must be recorded as "
        "discarded, or someone re-derives them"
    )
