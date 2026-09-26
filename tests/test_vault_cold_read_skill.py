"""Contract for the `vault-cold-read` gate's coverage pass.

A decomposed parent's children are cold-read one at a time, and the
source-fidelity pass checks each child against the parent's body. Neither can
see the set: whether the children together carry every parent criterion, and
whether two of them prescribe incompatible versions of the same thing. The
coverage pass is the one read that does, and it gates the promotion of every
child. Each assertion pins a part a later rewrite could quietly drop while the
prose still reads as complete.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS = REPO_ROOT / "plugins" / "workbench" / "skills"
COLD_READ = SKILLS / "vault-cold-read" / "references" / "command.md"
DISPATCH = SKILLS / "vault-dispatch" / "references" / "command.md"

COVERAGE_HEADING = "## The coverage pass"
BLOCKING_CLASSES = ("dropped", "weakened", "prose-only", "conflicted")


def _flat(text: str) -> str:
    """Collapse whitespace so phrase pins survive formatter re-wrapping."""
    return " ".join(text.split())


def _section(text: str, heading: str) -> str:
    """The body under an exact `## ` heading, up to the next `## ` heading."""
    start = text.index(heading)
    end = text.find("\n## ", start + len(heading))
    return text[start : end if end != -1 else len(text)]


def _coverage() -> str:
    text = COLD_READ.read_text()
    assert COVERAGE_HEADING in text, "command.md has no coverage-pass section"
    heading_line = next(
        line for line in text.splitlines() if line.startswith(COVERAGE_HEADING)
    )
    return _flat(_section(text, heading_line))


def test_coverage_pass_is_a_set_read_that_is_not_cold() -> None:
    """The coverage reader must see the parent and every child at once, so it
    cannot be cold; findings crossing into a cold reader would break the
    constraint the whole gate rests on."""
    section = _coverage()
    assert "once per parent" in section
    assert "not cold" in section
    assert "never reach" in section and "cold reader" in section


def test_child_set_and_criteria_are_enumerated_by_command() -> None:
    """A child missing from the enumeration, or a criterion missing from the
    count, is never classified; both counts come from the record, and the
    decomposer's own `## Decomposed into` checklist is not a criterion."""
    section = _coverage()
    assert "sub_issues" in section
    assert "exclude the `## Decomposed into` checklist" in section
    assert "Part of #" in section


def test_whole_set_obligations_bind_every_child() -> None:
    """An executor sees only its own child, so the parent's anti-scope,
    Budget and gate must reach every child, not at least one."""
    section = _coverage()
    for row in ("`AS`", "`BU`", "`GA`"):
        assert row in section, f"whole-set obligation {row} is not named"
    assert "every child" in section
    assert "byte-identical" in section


def test_gate_carriage_matches_the_whole_command() -> None:
    """A probe for a word the anti-scope block also contains reads the gate
    as carried in children that never name it."""
    section = _coverage()
    assert "Match the whole command, never a word from it" in section
    assert "outside the pasted `AS` block" in section


def test_every_short_class_blocks_every_child() -> None:
    """A single gap withholds the whole set: a promoted child's body is
    frozen, so a dropped criterion would have no home but a new child."""
    section = _coverage()
    for name in BLOCKING_CLASSES:
        assert f"`{name}`" in section, f"class {name} is not defined"
    assert "withholds every child" in section


def test_record_maps_parent_criterion_to_child_checkbox() -> None:
    """The record's unit is the parent criterion, and a row points at the
    child checkbox that goes red on its violating build."""
    section = _coverage()
    assert "## Coverage — CLEAN" in section
    assert "## Coverage — BLOCKED" in section
    assert "| Parent criterion | Class | Child | Checkbox | Default |" in section


def test_record_is_stamped_to_every_body_it_read() -> None:
    """A child edited after the pass, including by a later cold-read rewrite,
    may drop what the record says it carries."""
    section = _coverage()
    assert "shasum -a 256" in section
    assert "stale" in section


def test_gate_contract_withholds_children_until_coverage_is_clean() -> None:
    text = COLD_READ.read_text()
    contract = _flat(_section(text, "## Gate contract with /dispatch"))
    assert "Coverage — CLEAN" in contract
    assert "every child" in contract


def test_per_child_fidelity_leaves_unclaimed_criteria_to_coverage() -> None:
    """Without this, a per-child fidelity pass sourced from the parent files
    every criterion the child does not own as `missing`."""
    text = _flat(COLD_READ.read_text())
    assert "out of its slice" in text


def test_one_issue_per_run_names_its_one_exception() -> None:
    text = COLD_READ.read_text()
    constraints = _flat(_section(text, "## Constraints"))
    assert "coverage pass" in constraints


def test_dispatch_routes_child_promotion_through_the_coverage_pass() -> None:
    """Children of a plain decomposed parent are promoted one at a time with
    `--promote <child>`; that step is where the block has to be visible."""
    text = DISPATCH.read_text()
    clause = next(
        _flat(line) for line in text.splitlines() if "Children wait for" in line
    )
    assert "--promote <child>" in clause and "--promote-epic" in clause
    assert "## Coverage — CLEAN" in clause
    assert "#the-coverage-pass-decomposed-parents" in clause
