"""Contract for the `build-review-land` skill (#1157).

The per-PR cycle (builder, blind mutation reviewer, RED-confirm fixer, pinned
landing) was composed by hand in chat about ten times. These pins keep the
skill's size and description inside the repo's caps, keep every `<slot>` named in
SKILL.md present in the reference template that consumes it, and keep the
verbatim ledger columns and result vocabulary the reviewer and fixer comments
are graded against. String pins cannot see paraphrase; review covers the rest.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS = REPO_ROOT / "plugins" / "workbench" / "skills"
SKILL_DIR = SKILLS / "build-review-land"
SKILL = SKILL_DIR / "SKILL.md"
REVIEWER = SKILL_DIR / "references" / "reviewer.md"
FIXER = SKILL_DIR / "references" / "fixer.md"

LEDGER_COLUMNS = "# | behavior | mutation | predicted test | result | red line"
RESULT_VOCABULARY = "RED-predicted | RED-other | GREEN | UNANCHORED | CONTROL"
FIXER_LEDGER_COLUMNS = (
    "# | test | mutation it must red | as proposed | as landed | why changed | red line"
)


def _flat(text: str) -> str:
    """Collapse whitespace so phrase pins survive formatter re-wrapping."""
    return " ".join(text.split())


def _frontmatter_description() -> str:
    text = SKILL.read_text()
    block = text.split("---", 2)[1]
    lines = block.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("description:"))
    parts = [lines[start].split(":", 1)[1]]
    for ln in lines[start + 1 :]:
        if ln and not ln[0].isspace():
            break
        parts.append(ln)
    return _flat(" ".join(parts)).strip(">").strip().strip('"')


def _slots(used_by: set[str]) -> list[str]:
    """`<token>`s from SKILL.md's `## Slots` table whose row is in `used_by`."""
    text = SKILL.read_text()
    start = text.index("## Slots")
    end = text.find("\n## ", start + 1)
    section = text[start : end if end != -1 else len(text)]
    tokens: list[str] = []
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3 or cells[1] not in {"reviewer", "fixer", "both"}:
            continue
        if cells[1] in used_by:
            tokens.extend(re.findall(r"<[^<>`]+>", cells[0]))
    assert tokens, f"no slots parsed for {used_by}"
    return tokens


def test_skill_md_under_100_lines() -> None:
    assert len(SKILL.read_text().splitlines()) < 100


def test_description_under_250_chars() -> None:
    assert len(_frontmatter_description()) < 250


def test_description_carries_trigger_phrases() -> None:
    description = _frontmatter_description()
    assert "worker-per-PR + mutation review" in description
    assert "build this PR with a worker and a reviewer" in description


def test_reviewer_carries_every_slot() -> None:
    reviewer = REVIEWER.read_text()
    missing = [s for s in _slots({"reviewer", "both"}) if s not in reviewer]
    assert not missing, f"reviewer.md lacks slots: {missing}"


def test_fixer_carries_every_slot() -> None:
    fixer = FIXER.read_text()
    missing = [s for s in _slots({"fixer", "both"}) if s not in fixer]
    assert not missing, f"fixer.md lacks slots: {missing}"


def test_ledger_columns_in_skill_and_reviewer() -> None:
    assert LEDGER_COLUMNS in _flat(SKILL.read_text())
    assert LEDGER_COLUMNS in _flat(REVIEWER.read_text())


def test_result_vocabulary_in_skill_and_reviewer() -> None:
    assert RESULT_VOCABULARY in _flat(SKILL.read_text())
    assert RESULT_VOCABULARY in _flat(REVIEWER.read_text())


def test_fixer_ledger_columns() -> None:
    assert FIXER_LEDGER_COLUMNS in _flat(FIXER.read_text())


def test_drain_queue_points_here() -> None:
    assert "build-review-land" in (SKILLS / "drain-queue" / "SKILL.md").read_text()


def test_detector_teeth_check_points_here() -> None:
    text = (SKILLS / "detector-teeth-check" / "SKILL.md").read_text()
    assert "build-review-land" in text


def test_skill_references_both_templates() -> None:
    text = SKILL.read_text()
    assert "references/reviewer.md" in text
    assert "references/fixer.md" in text


def test_fixer_forbids_changing_the_mutation() -> None:
    assert "may not change the mutation" in _flat(FIXER.read_text())


def test_reviewer_never_hand_mutates() -> None:
    assert "never edits source by hand" in _flat(REVIEWER.read_text()).lower()


def test_land_command_names_the_real_script() -> None:
    text = SKILL.read_text()
    assert "pr_land.py land" in _flat(text)
    for line in text.splitlines():
        if "scripts/pr_land.py" in line:
            assert "github-pr-land" in line, f"path does not name its skill: {line!r}"
    assert (SKILLS / "github-pr-land" / "scripts" / "pr_land.py").is_file()


def test_skill_stops_on_ambiguous_anchor() -> None:
    assert "ambiguous anchor" in _flat(SKILL.read_text())
