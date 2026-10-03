"""Contract for the `vault-cold-read` gate.

Probe builds, the rewrite loop and stamped verdicts: a reader settles
empirical questions by running them, applied replacement text never reaches
`cold-read:pass` without a fresh read, and every promote checks the stamp.
String pins cannot see paraphrase, so the value-level checks below pin what
steps 7 and 8 must never say, and the PR line-list review covers the rest.

The coverage pass: a decomposed parent's children are cold-read one at a time, and the
source-fidelity pass checks each child against the parent's body. Neither can
see the set: whether the children together carry every parent criterion, and
whether two of them prescribe incompatible versions of the same thing. The
coverage pass is the one read that does, and it gates the promotion of every
child. Each assertion pins a part a later rewrite could quietly drop while the
prose still reads as complete.
"""

import re
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


def test_narrowed_anti_scope_is_judged_per_prohibition() -> None:
    """A parent may let each child carry a narrowed anti-scope. Then no
    byte comparison applies, so each parent prohibition is judged in
    substance, and one the child weakens or drops blocks. Only the parent's
    own text can allow narrowing: the executor never sees a brief."""
    section = _coverage()
    for name in ("`kept`", "`narrowed`", "`weaker`", "`dropped`"):
        assert name in section, f"narrowed-AS class {name} is not defined"
    assert "A `weaker` or `dropped` prohibition blocks" in section
    assert "authorized in the parent's text" in section


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
    assert "body= field" in section
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


# --- Probe builds, the rewrite loop and stamped verdicts (#1037) -----------

PROBE_HEADING = "## Probe builds"
GATE_HEADING = "## Gate contract with /dispatch"
EXEMPTION_MARK = "byte-identical to replacement text"


def _cold_section(heading: str) -> str:
    return _flat(_section(COLD_READ.read_text(), heading))


def _step(n: int) -> str:
    """Procedure step n: the text from `\\nn. ` to `\\n(n+1). ` inside
    `## Procedure`, flattened."""
    procedure = _section(COLD_READ.read_text(), "## Procedure")
    start = procedure.index(f"\n{n}. ")
    end = procedure.index(f"\n{n + 1}. ", start + 1)
    return _flat(procedure[start:end])


def _sentences(flat: str) -> list[str]:
    return re.split(r"(?<=\.)\s+(?=[^a-z\s-])", flat)


def test_probe_builds_section_follows_the_cold_constraint() -> None:
    text = COLD_READ.read_text()
    assert PROBE_HEADING in text, "command.md has no probe-builds section"
    after_constraint = text.index("\n## ", text.index("## The cold constraint") + 1)
    assert text.index(PROBE_HEADING) == after_constraint + 1


def test_probe_builds_fork_point_baseline_and_scratch_dir() -> None:
    """A git archive has no .git, parallel readers collided on a fixed path,
    and afk forks an epic child from its epic branch."""
    section = _cold_section(PROBE_HEADING)
    for phrase in (
        "integration_target",
        "outside every checkout",
        "git init",
        "Target: afk/epic-N",
        "DEFAULT_INTEGRATION_TARGET",
        "mktemp -d",
        "test_command",
    ):
        assert phrase in section, f"probe builds lacks {phrase!r}"
    order = [
        section.index("Target: afk/epic-N"),
        section.index("integration_target"),
        section.index("DEFAULT_INTEGRATION_TARGET"),
    ]
    assert order == sorted(order), "fork-point precedence is out of order"


def test_probe_builds_detectors_run_their_named_builds() -> None:
    section = _cold_section(PROBE_HEADING)
    for phrase in (
        "teeth_check.py",
        "runs the violating build",
        "runs the faithful build",
        "MEASURED",
        "REASONED",
        "experiments run and skipped",
        "degraded",
    ):
        assert phrase in section, f"probe builds lacks {phrase!r}"


def test_probe_builds_carry_the_executor_contract() -> None:
    """The executor cannot write the PR body or the commit message, and the
    reviewer never sees .afk/notes.md."""
    section = _cold_section(PROBE_HEADING)
    for phrase in (
        ".afk/notes.md",
        "cannot write the PR body, the commit message",
        "detector-9 finding",
        "gradable from the diff",
    ):
        assert phrase in section, f"probe builds lacks {phrase!r}"


def test_probe_builds_check_dependencies_against_shipped_code() -> None:
    section = _cold_section(PROBE_HEADING)
    assert "checked against the shipped code" in section
    assert "provisional" in section


def test_cold_constraint_admits_probe_builds_and_keeps_archaeology_clause() -> None:
    section = _cold_section("## The cold constraint")
    assert "probe builds" in section
    assert "It may not go code-archaeologing to reconstruct intent" in section


def test_anti_rubber_stamp_treats_probe_builds_as_instruments() -> None:
    section = _cold_section("## Anti-rubber-stamp")
    assert "instruments, not proposals" in section


def test_step_8_is_the_closed_rewrite_loop() -> None:
    step = _step(8)
    for phrase in (
        "cold-read:rewrite, never pass",
        EXEMPTION_MARK,
        "produced and measured",
        "Any conductor addition voids",
        "third fresh read",
        "NOT-DISPATCH-READY",
    ):
        assert phrase in step, f"step 8 lacks {phrase!r}"


def test_step_7_stamps_a_build() -> None:
    assert "cold_read_stamp.py stamp" in _step(7)


def test_steps_7_and_8_reach_pass_only_through_the_exemption() -> None:
    """Applied replacement text must not reach `cold-read:pass` by any
    sentence of steps 7 or 8 other than the exemption."""
    step7, step8 = _step(7), _step(8)
    assert "cold-read:pass" not in step7
    pass_sentences = [s for s in _sentences(step8) if "cold-read:pass" in s]
    assert pass_sentences, "step 8 never states how the exemption ends"
    for sentence in pass_sentences:
        assert EXEMPTION_MARK in sentence, f"non-exempt path to pass: {sentence!r}"


def test_gate_contract_checks_the_stamp() -> None:
    contract = _cold_section(GATE_HEADING)
    for phrase in (
        "cold_read_stamp.py check",
        "exit 1: re-read",
        "cold_read_current",
        "stamp only on that read's BUILD",
        "A REWRITE clears the gate only through a fresh reader's BUILD",
        "userContentEdits",
        "require_cold_read_stamp",
    ):
        assert phrase in contract, f"gate contract lacks {phrase!r}"


def test_old_rewrite_and_anti_code_sentences_are_gone() -> None:
    text = _flat(COLD_READ.read_text())
    for phrase in (
        "A REWRITE resolved by editing the body clears the gate",
        "re-state the verdict as BUILD",
        "Do not fix the code. Do not propose an implementation.",
        "shasum -a 256",
    ):
        assert phrase not in text, f"command.md still says {phrase!r}"
    lowered = text.lower()
    for phrase in ("re-state", "restate", "rewrite resolved", "fixed by editing the body"):
        assert phrase not in lowered, f"command.md still says {phrase!r}"


def test_dispatch_promotes_only_after_a_fresh_build_and_a_stamp_check() -> None:
    text = _flat(DISPATCH.read_text())
    assert "resolved by editing the body." not in text
    assert "resolved by editing the body and a fresh reader's BUILD on it" in text
    assert "promote only on exit 0" in text
    promoting = [s for s in _sentences(text) if "afk-driver" in s]
    assert promoting, "dispatch names no promote command"
    for sentence in promoting:
        assert "cold_read_stamp.py check" in sentence, (
            f"promotes without a stamp check: {sentence!r}"
        )
        assert sentence.index("cold_read_stamp.py check") < sentence.index(
            "afk-driver"
        ), f"stamp check does not come first: {sentence!r}"


# --- Review fixes: stamp only what was read (#1037) --------------------------


def test_step_7_stamps_only_the_body_the_reader_was_given() -> None:
    """The stamp hashes the body at stamp time, so a body edited during the
    read, or a stamp left from an earlier BUILD under a later REWRITE or
    NOT-DISPATCH-READY, would certify text no reader passed."""
    assert "Record the body= field" in _step(1)
    step = _step(7)
    for phrase in (
        "On BUILD, stamp",
        "not the one step 1 recorded, the body changed during the read",
        "On any other verdict, remove the pass label and delete any stamp line",
    ):
        assert phrase in step, f"step 7 lacks {phrase!r}"


def test_step_8_exemption_binds_the_whole_read() -> None:
    step = _step(8)
    for phrase in (
        "made to the body that reader read, its body= field unchanged since step 1",
        "covering every blocking finding of that read",
        "degraded or provisional whenever that read's record makes it so",
    ):
        assert phrase in step, f"step 8 lacks {phrase!r}"


def test_gate_contract_legacy_passes_and_degraded_builds() -> None:
    """A legacy pass read against an open dependency's body must not be
    stamped once that dependency has closed, and a later non-BUILD read
    must not be skipped over for an older BUILD comment."""
    contract = _cold_section(GATE_HEADING)
    for phrase in (
        "comment is a BUILD, that comment is newer than its last body edit",
        "no dependency it names has closed since that comment",
        "A degraded BUILD blocks auto-promote",
    ):
        assert phrase in contract, f"gate contract lacks {phrase!r}"
    assert "detector-3, 9 or 11 criterion was only REASONED" in _cold_section(
        PROBE_HEADING
    )


def test_no_sentence_forbids_the_reader_to_execute() -> None:
    """A keyword net, not a proof: paraphrase still needs the line-list review."""
    lowered = _flat(COLD_READ.read_text()).lower()
    for phrase in ("never execute", "not execute", "never run code", "read-only"):
        assert phrase not in lowered, f"command.md forbids execution: {phrase!r}"


# --- Guard criteria under a teeth check (afk-agent-system#1552) --------------


def _detector(n: int) -> str:
    """Detector n: the text from `\\nn. ` to the next numbered detector,
    flattened."""
    text = COLD_READ.read_text()
    start = text.index(f"\n{n}. **")
    end = text.index(f"\n{n + 1}. **", start + 1)
    return _flat(text[start:end])


def test_probe_builds_run_the_new_tests_on_the_baseline_of_teeth_checked_repos() -> None:
    """afk's F3 loop reverts any epoch whose added tests already pass on the
    base tree, so a reader must measure which new tests are guard tests."""
    section = _cold_section(PROBE_HEADING)
    for phrase in (
        "Baseline run of the new tests (teeth-checked repos)",
        'autonomy_frontier = "F3"',
        "`[loop]` table",
        "ONLY the build's new tests against the UNCHANGED baseline source",
        "Every new test that passes there is a guard test",
        "passing test ids",
    ):
        assert phrase in section, f"probe builds lacks {phrase!r}"


def test_detector_3_rejects_guard_criteria_on_teeth_checked_repos() -> None:
    """A criterion that requires a test green on the base tree can never land
    through F3; the fix is a diff-shape check, never a required new test."""
    detector = _detector(3)
    for phrase in (
        "Guard criterion under a teeth check",
        "can never land",
        "BLOCKING",
        "git diff -U0 origin/main...HEAD",
        "no new test is required: already true on the current tree",
        "never as a required new test",
        "must-flip criterion",
        "hand-built",
    ):
        assert phrase in detector, f"detector 3 lacks {phrase!r}"


def test_a_build_on_a_teeth_checked_repo_states_the_baseline_run() -> None:
    section = _cold_section("## Anti-rubber-stamp")
    for phrase in (
        "baseline run",
        "how many new tests it ran and how many passed there (0 required)",
        "makes the BUILD degraded",
    ):
        assert phrase in section, f"anti-rubber-stamp lacks {phrase!r}"


def test_reachability_blocks_only_on_a_cited_producer_and_fails_closed() -> None:
    """A survivor on an input value blocks only when a producer is cited, an
    unrun search counts as reachable, and the carve-out never reaches the
    non-value detectors. Without the last two, the rule is a way to talk a
    real defect out of existence."""
    section = _cold_section("## Survivors and reachability")
    for phrase in (
        "Blocking needs a producer",
        "`REACHABLE: <citation>`",
        "`UNREACHABLE`",
        "Fail closed",
        "tags the finding REACHABLE and says why",
        "Reasoning that an input \"would never happen\" is not a search",
        "without the command and its output is a blocking finding",
        "A hand-crafted file does not count as a producer",
        "It never applies to a policy fork (detector 7), a false premise (detector 8)",
        "Positive controls",
    ):
        assert phrase in section, f"reachability section lacks {phrase!r}"


def test_detectors_3_and_11_defer_value_survivors_to_reachability() -> None:
    text = COLD_READ.read_text()
    detector_11 = _flat(text[text.index("\n11. **") : text.index("## Survivors and reachability")])
    for n, body in ((3, _detector(3)), (11, detector_11)):
        assert "#survivors-and-reachability" in body, f"detector {n}"


def test_size_flag_names_its_triggers_and_the_kept_whole_ruling() -> None:
    section = _cold_section("## Size flag")
    for phrase in (
        "1.5 times",
        "more than 20 acceptance checkboxes",
        "hit the read cap once",
        "kept whole by Charles",
        "the flag does not re-ask",
    ):
        assert phrase in section, f"size flag lacks {phrase!r}"
    assert "#size-flag" in _detector(6)


def test_subtract_first_is_the_default_at_the_cap_and_binds_to_traced_rules() -> None:
    section = _cold_section("## Subtract first")
    for phrase in (
        "`reader-born`",
        "`traced`",
        "Traced rules are never subtraction candidates",
        "Subtract is the default",
        "Grow is not offered",
        "Outside this contract: <case>.",
        "Charles approved it by name",
        "rule-born: N of M blocking",
    ):
        assert phrase in section, f"subtract-first lacks {phrase!r}"


def test_step_8_cap_carries_both_proposals_and_numbers_the_cap() -> None:
    step = _step(8)
    for phrase in (
        "Grow",
        "Subtract, the default",
        "`cap #k`",
        "at `cap #2` and later, Grow is not offered",
        "#size-flag",
        "#subtract-first",
    ):
        assert phrase in step, f"step 8 lacks {phrase!r}"


def test_step_8_requires_a_code_fact_search_and_the_edit_lint() -> None:
    step = _step(8)
    for phrase in (
        "run the search that confirms it",
        "A reader's suggestion is a hypothesis, not a fact",
        "cold_read_edit_lint.py",
        "--expect-deletion-only",
    ):
        assert phrase in step, f"step 8 lacks {phrase!r}"


def test_step_8_shortening_exception_is_only_an_approved_subtraction() -> None:
    step = _step(8)
    assert "never shortens acceptance criteria" in step
    assert "The one exception is a [subtraction](#subtract-first) that Charles approved by name" in step


def test_fidelity_defaults_obey_the_executor_contract() -> None:
    section = _cold_section("## The source-fidelity pass")
    for phrase in (
        "Defaults obey the executor contract",
        "the diff, the issue body and the gate report cannot grade",
    ):
        assert phrase in section, f"fidelity pass lacks {phrase!r}"


def test_digest_reports_size_flag_rule_born_and_cap_number() -> None:
    procedure = _section(COLD_READ.read_text(), "## Procedure")
    step = _flat(procedure[procedure.index("\n9. ") :])
    for phrase in ("size-flag line", "rule-born: N of M blocking", "cap number"):
        assert phrase in step, f"digest lacks {phrase!r}"
