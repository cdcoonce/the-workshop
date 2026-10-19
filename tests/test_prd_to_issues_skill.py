"""Contract for the `prd-to-issues` oracle-population rule (#1255).

A slice whose deliverable is an oracle drawn from history must count the real
items per class before choosing the oracle's shape. Each assertion is scoped to
the one bullet or acceptance-criteria block it pins, never the whole file.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / "plugins" / "workbench" / "skills" / "prd-to-issues"
SKILL = SKILL_DIR / "SKILL.md"
PLAN_TEMPLATE = SKILL_DIR / "references" / "plan-template.md"

HINT = (
    "- [ ] (oracle slices) Population per class: <source>, <counts>; "
    "seeded defects named if the scarce class is below the bar"
)


def _flat(text: str) -> str:
    """Collapse whitespace so phrase pins survive formatter re-wrapping."""
    return " ".join(text.split())


def _oracle_bullet() -> str:
    text = SKILL.read_text()
    start = text.index("<vertical-slice-rules>")
    end = text.index("</vertical-slice-rules>", start)
    block = text[start:end]
    # A bullet is one logical line; continuation lines are indented.
    lines = block.splitlines()
    idx = next(
        (i for i, ln in enumerate(lines) if ln.startswith("- Oracle slices:")), None
    )
    assert idx is not None, "no '- Oracle slices:' bullet in <vertical-slice-rules>"
    parts = [lines[idx]]
    for ln in lines[idx + 1 :]:
        if not ln.startswith("  "):
            break
        parts.append(ln)
    return _flat(" ".join(parts))


def _ac_block(text: str, heading: str) -> str:
    start = text.index(heading)
    end = text.find("\n## ", start + len(heading))
    end2 = text.find("\n### ", start + len(heading))
    ends = [e for e in (end, end2) if e != -1]
    # Also stop at a comment/closing tag line that ends the template.
    for marker in ("\n<!--", "\n</plan-template>"):
        m = text.find(marker, start + len(heading))
        if m != -1:
            ends.append(m)
    return _flat(text[start : min(ends) if ends else len(text)])


def test_vertical_slice_rules_carry_the_oracle_population_bullet() -> None:
    bullet = _oracle_bullet()
    assert bullet.startswith("- Oracle slices:")
    assert "count the real items in each class before choosing the oracle's shape" in bullet


def test_oracle_bullet_requires_source_and_count_in_the_body() -> None:
    assert "name the source and the count in the body" in _oracle_bullet()


def test_oracle_bullet_defaults_to_seeded_defects_below_the_bar() -> None:
    bullet = _oracle_bullet()
    assert "default to seeded defects" in bullet
    assert "real known-good items with one named mechanical defect each" in bullet
    assert "keep any real negatives as cited cases" in bullet


def test_curated_only_oracle_below_the_bar_is_hitl() -> None:
    bullet = _oracle_bullet()
    assert "mark it HITL" in bullet
    assert "curated-only" in bullet


def test_issue_template_acceptance_criteria_carry_the_population_hint() -> None:
    text = SKILL.read_text()
    start = text.index("<issue-template>")
    end = text.index("</issue-template>", start)
    assert HINT in _ac_block(text[start:end], "## Acceptance criteria")


def test_plan_template_acceptance_criteria_carry_the_population_hint() -> None:
    assert HINT in _ac_block(PLAN_TEMPLATE.read_text(), "### Acceptance criteria")
