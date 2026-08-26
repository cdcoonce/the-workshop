"""Ownership and discipline contract for the `dbt-manifest-facts` skill.

The capability is answering structural questions about a dbt project from its
parsed `manifest.json` instead of from model comments, README prose, or memory.
Reading a compiled artifact is a data capability that any repo with a dbt
project can use, so `workbench` is the canonical owner; plugin membership
follows from directory presence, not a manifest edit.

The rest of these tests pin the disciplines that make the skill worth invoking
at all. A verification skill degrades in two directions: it stops verifying
(reporting the remembered number rather than the derived one), or it starts
trusting a stale artifact — which is worse than having none, because a stale
manifest answers confidently about a project that no longer exists. Each
assertion guards a part that one of those failures routes around.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SLUG = "dbt-manifest-facts"
PLUGINS = REPO_ROOT / "plugins"
SKILL_DIR = PLUGINS / "workbench" / "skills" / SLUG
SKILL_MD = SKILL_DIR / "SKILL.md"
SCRIPT = SKILL_DIR / "scripts" / "manifest_facts.py"

# The neighbours this skill must not absorb, and must not be absorbed by.
# dbt-expert authors dbt; data-discovery profiles warehouse data;
# sql-deploy-precheck compares committed SQL against a live schema. This skill
# reads a compiled artifact and reports what the project declares.
NEIGHBOURS = ("dbt-expert", "data-discovery", "sql-deploy-precheck")

# The four questions the shipped script answers. Each one maps to a claim that
# prose got wrong in the session that surfaced this skill.
SUBCOMMANDS = ("summary", "orphans", "keys", "lineage")


def test_skill_is_owned_by_workbench_alone():
    """One slug, one plugin — a second copy is a repo defect, not redundancy."""
    owners = sorted(p.parent.parent.name for p in PLUGINS.glob(f"*/skills/{SLUG}"))
    assert owners == ["workbench"], f"expected workbench to own {SLUG}, found {owners}"


def test_skill_md_exists_and_is_within_the_length_guideline():
    assert SKILL_MD.is_file(), f"{SKILL_MD} is missing"
    lines = SKILL_MD.read_text().splitlines()
    assert len(lines) < 100, f"SKILL.md is {len(lines)} lines; keep it under 100"


def _description() -> str:
    text = SKILL_MD.read_text()
    assert text.startswith("---"), "SKILL.md must open with YAML frontmatter"
    front = text.split("---")[1]
    marker = "description:"
    assert marker in front, "frontmatter must carry a description"
    body = front.split(marker, 1)[1]
    # Frontmatter description runs until the next top-level key or the end.
    stop = len(body)
    for line in body.splitlines()[1:]:
        if line and not line[0].isspace():
            stop = body.index(line)
            break
    return " ".join(body[:stop].split())


def test_description_is_a_trigger_index_not_a_workflow_narration():
    """The description is the only thing an agent sees when choosing a skill.

    A description that narrates process gets executed instead of the body, so
    the retrieval index must carry triggers and nothing else.
    """
    description = _description()
    assert len(description) < 1024, f"description is {len(description)} chars"
    assert "Use when" in description, "description must carry a 'Use when' trigger"
    for banned in ("→", "phase", "pipeline", "step 1", "first,"):
        assert banned.lower() not in description.lower(), (
            f"description narrates workflow ({banned!r}); that belongs in the body"
        )


def test_skill_names_its_neighbours_so_the_boundary_survives_editing():
    """Without an explicit boundary the skill drifts into authoring or profiling."""
    text = SKILL_MD.read_text()
    for neighbour in NEIGHBOURS:
        assert neighbour in text, f"SKILL.md must name its boundary with {neighbour}"


def test_skill_prefers_dbt_parse_over_docs_generate():
    """`dbt parse` is the cheap path and needs no warehouse credentials.

    Assuming a live connection is required is what stops people reaching for
    the manifest at all, so the skill has to say which command to run.
    """
    text = SKILL_MD.read_text()
    assert "dbt parse" in text, "SKILL.md must name `dbt parse` as the way to build a manifest"


def test_skill_carries_the_staleness_discipline():
    """A stale manifest is worse than no manifest — it is confidently wrong."""
    text = SKILL_MD.read_text().lower()
    assert "stale" in text, "SKILL.md must warn that a stale manifest answers for a dead project"


def test_script_ships_and_covers_every_documented_subcommand():
    assert SCRIPT.is_file(), f"{SCRIPT} is missing"
    source = SCRIPT.read_text()
    documented = SKILL_MD.read_text()
    for sub in SUBCOMMANDS:
        assert sub in source, f"script does not implement `{sub}`"
        assert sub in documented, f"SKILL.md does not document `{sub}`"
