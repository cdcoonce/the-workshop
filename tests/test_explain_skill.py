"""Import contract for the `explain` skill: chat eli5 or a visual summary page.

Imported light-touch from github.com/isas1/skills (MIT) on 2026-09-20 and
merged: the upstream pair (`eli5-succinct`, `summary`) became one skill whose
first fork is the output medium. The merge moved the whole routing fence into
strings — the frontmatter description and the SKILL.md routing section — so
this suite pins those strings. Guarded, per the import's decision log: strict
lanes (vault session verbs and transcript-notes never route here), the
ambiguity-only AskUserQuestion gate, the never-write-a-file rule on the chat
path, the convention output home, and artistic mode's dropped third-party
runtime reference.
"""

from pathlib import Path

from tests.test_skill_invocation_chains import _discover_skills

REPO_ROOT = Path(__file__).resolve().parents[1]
SLUG = "explain"
SKILL_DIR = REPO_ROOT / "plugins" / "workbench" / "skills" / SLUG
SKILL_MD = SKILL_DIR / "SKILL.md"
MODES = ("eli5", "accessible", "animated", "artistic")


def _skill_text() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def _explain_skill():
    skills = _discover_skills()
    matches = [s for s in skills.values() if s.slug == SLUG]
    assert len(matches) == 1, f"expected exactly one '{SLUG}' skill, found {len(matches)}"
    return matches[0]


def test_skill_is_owned_by_workbench() -> None:
    """Membership is the filesystem; one slug lives in exactly one plugin."""
    assert SKILL_MD.is_file(), f"{SKILL_MD} is missing"
    twins = [
        p
        for p in REPO_ROOT.glob(f"plugins/*/skills/{SLUG}/SKILL.md")
        if "worktrees" not in p.relative_to(REPO_ROOT).parts
    ]
    assert len(twins) == 1, f"slug {SLUG} shipped by {len(twins)} plugins"


def test_all_mode_files_ship() -> None:
    """The chat path and the three page dressings are read-on-demand files."""
    missing = [m for m in MODES if not (SKILL_DIR / "modes" / f"{m}.md").is_file()]
    assert not missing, f"missing mode files: {missing}"


def test_description_carries_both_triggers_and_the_fences() -> None:
    """The listing description is the entire model-facing routing surface."""
    desc = " ".join(_explain_skill().frontmatter["description"].split())
    assert len(desc) <= 250, f"description is {len(desc)} chars, over the listing cap"
    lowered = desc.lower()
    for trigger in ("eli5", "summary"):
        assert trigger in lowered, f"description lost the '{trigger}' trigger"
    for fence in ("wrap-up", "handoff", "transcript-notes"):
        assert fence in lowered, f"description lost the '{fence}' fence"


def test_routing_forks_on_what_the_user_ends_up_holding() -> None:
    """The merge kept upstream's routing philosophy as the first fork."""
    text = _skill_text().lower()
    assert "what they want to end up holding" in text
    assert "modes/eli5.md" in text, "chat path must hand off to the eli5 mode file"


def test_mode_gate_asks_only_when_ambiguous() -> None:
    """One AskUserQuestion on a genuine tie; phrasing decides everything else."""
    text = _skill_text()
    assert "AskUserQuestion" in text
    lowered = text.lower()
    assert "genuinely ambiguous" in lowered
    assert "do not ask when phrasing already decides" in lowered


def test_vault_lanes_stay_fenced_in_the_body() -> None:
    """Strict lanes: session verbs and transcript work never route here."""
    text = _skill_text().lower()
    for owner in ("vault-wrap-up", "vault-handoff", "transcript-notes"):
        assert owner in text, f"SKILL.md no longer names {owner} as out of lane"


def test_chat_path_never_writes_a_file() -> None:
    """eli5's hard rule survived the merge into a mode file."""
    text = (SKILL_DIR / "modes" / "eli5.md").read_text(encoding="utf-8")
    assert "Never write a file" in text


def test_output_home_follows_the_workshop_convention() -> None:
    """Pages land in ~/.workshop/explain/, not the working directory."""
    assert "~/.workshop/explain/" in _skill_text()


def test_artistic_mode_dropped_the_runtime_reference() -> None:
    """No third-party repo is fetched at runtime from any shipped file."""
    for path in SKILL_DIR.rglob("*.md"):
        assert "forever-ai-components" not in path.read_text(encoding="utf-8"), (
            f"{path.name} still references the dropped third-party repo"
        )


def test_provenance_names_source_and_license() -> None:
    """Imported text carries its origin: repo, license, import method."""
    text = _skill_text()
    assert "github.com/isas1/skills" in text
    assert "MIT" in text
