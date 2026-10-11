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

from tests.conftest import assert_sole_owner

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
    assert_sole_owner(REPO_ROOT, SLUG)


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


def test_position_generation_never_exceeds_the_option_count() -> None:
    """A pre-drawn position must always name a real slot.

    The protocol allows two to four options per item, so a fixed 1-4 draw hands
    a two-option question position 3 or 4 with nowhere to put the answer.
    SKILL.md is the only file guaranteed to load, so the rule lives there.
    """
    body = _skill_text()
    assert "randint(1,4)" not in body.replace(" ", ""), (
        "fixed 1-4 draw leaves undefined slots on items with fewer options"
    )
    lowered = body.lower()
    assert "option count" in lowered or "number of options" in lowered, (
        "SKILL.md does not tie the position draw to each item's option count"
    )


def test_documented_draw_stays_in_range() -> None:
    """Run the SKILL.md draw command: every draw is a valid 1..n position."""
    import ast
    import re
    import subprocess
    import sys

    block = re.search(r"```bash\n(python3 -c .*?)\n```", _skill_text(), re.DOTALL)
    assert block, "SKILL.md has no python3 draw command in a bash block"
    code = re.search(r'python3 -c "(.*)"\s*$', block.group(1)).group(1)
    counts = ast.literal_eval(re.search(r"for n in (\[[\d,\s]+\])", code).group(1))
    assert len(counts) == 12
    seen = [set() for _ in counts]
    for _ in range(200):
        out = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, check=True
        ).stdout
        draws = ast.literal_eval(out.strip())
        assert len(draws) == len(counts) == 12
        assert all(1 <= d <= n for d, n in zip(draws, counts)), (draws, counts)
        for bucket, d in zip(seen, draws):
            bucket.add(d)
    # The whole range is reachable: a draw that never lands on 1 (or n) is
    # clamped, and the correct option drifts to a fixed slot.
    for bucket, n in zip(seen, counts):
        assert bucket == set(range(1, n + 1)), (bucket, n)
