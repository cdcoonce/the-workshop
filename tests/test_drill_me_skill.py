"""Ownership and discipline contract for the `drill-me` skill.

The capability is closed-book multiple-choice drilling that tells a recall gap
apart from a comprehension gap. Assessing someone against material is universal
to any repo and any subject, so `workbench` is the canonical owner; plugin
membership follows from directory presence, not a manifest edit.

The rest of these tests pin the machinery that keeps a drill diagnostic rather
than decorative. A drill degrades in three specific directions, each observed:
the correct option drifts to a fixed slot and the results stop meaning anything;
a missed item is re-asked verbatim, so the retest measures memory of the option
text instead of the concept; or only the correct option gets a written-through
rationale, which makes it guessable without reading the stem. Each assertion
guards a part that one of those failures routes around.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SLUG = "drill-me"
SKILL_DIR = REPO_ROOT / "plugins" / "workbench" / "skills" / SLUG
SKILL_MD = SKILL_DIR / "SKILL.md"


def _skill_text() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def _all_text() -> str:
    return "\n".join(
        p.read_text(encoding="utf-8") for p in sorted(SKILL_DIR.rglob("*.md"))
    )


def _description() -> str:
    lines = _skill_text().splitlines()
    assert lines[0] == "---", "SKILL.md must open with a frontmatter fence"
    end = lines.index("---", 1)
    block, collecting = [], False
    for line in lines[1:end]:
        if line.startswith("description:"):
            collecting = True
            continue
        if collecting:
            if line and not line[0].isspace():
                break
            block.append(line.strip())
    return " ".join(part for part in block if part)


def test_skill_is_owned_by_workbench() -> None:
    """Membership is the filesystem; one slug lives in exactly one plugin."""
    assert SKILL_MD.is_file(), f"{SKILL_MD} is missing"
    twins = [
        p
        for p in REPO_ROOT.glob(f"plugins/*/skills/{SLUG}/SKILL.md")
        if "worktrees" not in p.parts
    ]
    assert len(twins) == 1, f"slug {SLUG} shipped by {len(twins)} plugins"


def test_skill_md_stays_under_the_line_budget() -> None:
    """Progressive disclosure: the invocation-loaded file stays readable."""
    line_count = len(_skill_text().splitlines())
    assert line_count < 100, f"SKILL.md is {line_count} lines"


def test_description_is_trigger_only_and_explicit_invocation() -> None:
    """The description is a retrieval index, not a spec.

    This repo's SKILL.md frontmatter cannot carry `disable-model-invocation`,
    so the explicit `/drill-me` trigger is the description's job.
    """
    description = _description()
    assert len(description) < 1024
    assert "use when" in description.lower()
    assert "/drill-me" in description, "explicit invocation trigger missing"
    assert "→" not in description, "description narrates a step chain"
    assert "phase" not in description.lower(), "description leaks structure"


def test_position_randomization_survives_on_the_skill_file_alone() -> None:
    """The failure this skill exists to prevent, pinned where it is always read.

    Authoring option order by judgment parked the correct answer in slot one on
    eight consecutive questions, which made every result uninterpretable. A
    reference file is progressive disclosure and may never be loaded, so the
    mandate has to hold on SKILL.md by itself.
    """
    body = _skill_text().lower()
    assert "random" in body, "no randomization mandate on SKILL.md"
    assert "position" in body, "randomization mandate does not name positions"


def test_retest_after_a_miss_forbids_reusing_the_question() -> None:
    """A verbatim retest measures option-text recall, not understanding."""
    assert "verbatim" in _all_text().lower(), "no rule against reusing a missed item"


def test_every_referenced_file_exists() -> None:
    """smoke_test validates this repo-wide; failing here localizes the break."""
    for ref in SKILL_DIR.glob("references/*.md"):
        assert f"references/{ref.name}" in _skill_text(), f"{ref.name} is orphaned"
