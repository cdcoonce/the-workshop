from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(SCRIPTS_DIR))

import cold_read_edit_lint as lint_mod  # noqa: E402
from cold_read_edit_lint import (  # noqa: E402
    check_dangling,
    check_deletion_only,
    check_fused_items,
    check_item_count,
    context_lines,
    list_items,
    main,
)


def L(text: str) -> list[str]:
    return text.split("\n")


def codes(findings, severity=None):
    return [f.code for f in findings if severity is None or f.severity == severity]


# ---- 1. FUSED_ITEM -------------------------------------------------------- #

@pytest.mark.parametrize("text", [
    "- Do the thing (no new error code).5. **Read-only** mode",
    "- Do the thing.5. **Read-only** mode",
    "- See this:5. **Next**",
    "- Use `foo`5. **Next**",
    "- Done.- [ ] next task",
    "- Done)- [x] next task",
])
def test_fused_item_fires(text):
    f = check_fused_items(L(text))
    assert codes(f) == ["FUSED_ITEM"]
    assert f[0].line == 1


@pytest.mark.parametrize("text", [
    "5. **Read-only** mode",                 # real item at line start
    "- Item one.",                            # normal
    "Upgrade to v1.2. 3 files changed",       # version-like, digit before dot
    "See section 3.5. Next we go",            # 3.5. Next
    "Sentence. 5. Not fused (space)",
    "- Use `a.5. b` literally",               # inline code span
    "- Use `x`. Then 5. later",
])
def test_fused_item_does_not_fire(text):
    assert check_fused_items(L(text)) == []


def test_fused_item_ignores_fenced_code():
    text = "```\nend.5. **x**\n```\nok"
    assert check_fused_items(L(text)) == []


def test_fused_item_fires_after_fence_closes():
    text = "```\nx\n```\nend.5. **x**"
    assert [f.line for f in check_fused_items(L(text))] == [4]


# ---- 2. ITEM_COUNT_DELTA / deletion-only ---------------------------------- #

BEFORE = "\n".join([
    "# Spec",
    "- one",
    "  - [ ] two",
    "3. three. Extra sentence.",
    "```",
    "- not an item",
    "```",
    "",
    "tail",
])


def test_list_items_counts_outside_fences():
    items = list_items(L(BEFORE))
    assert [t for _, t in items] == ["one", "two", "three. Extra sentence."]


def test_item_count_delta_reports_counts():
    after = BEFORE.replace("- one\n", "")
    f, b, a = check_item_count(L(BEFORE), L(after))
    assert (b, a) == (3, 2)
    assert f[0].code == "ITEM_COUNT_DELTA" and f[0].severity == "info"
    assert "delta=-1" in f[0].message


def test_item_count_positive_delta_errors_only_in_deletion_mode():
    after = BEFORE + "\n- new"
    assert check_item_count(L(BEFORE), L(after))[0][0].severity == "info"
    assert check_item_count(L(BEFORE), L(after), True)[0][0].severity == "error"


def test_pure_deletion_is_clean():
    after = BEFORE.replace("- one\n", "").replace("tail", "")
    assert codes(check_deletion_only(L(BEFORE), L(after)), "error") == []


def test_added_line_flagged():
    after = BEFORE + "\nbrand new line"
    f = check_deletion_only(L(BEFORE), L(after))
    assert codes(f) == ["ADDED_LINE"]


def test_added_list_item_flagged_both_codes():
    after = BEFORE + "\n- brand new item"
    assert sorted(codes(check_deletion_only(L(BEFORE), L(after)))) == [
        "ADDED_ITEM", "ADDED_LINE"]


def test_whitespace_normalization_not_an_addition():
    after = BEFORE.replace("- one", "-   one ")
    assert codes(check_deletion_only(L(BEFORE), L(after))) == []


def test_reordered_lines_flagged():
    after = "tail\n# Spec"
    assert "ADDED_LINE" in codes(check_deletion_only(L(BEFORE), L(after)))


def test_truncated_line_is_info_not_error():
    after = BEFORE.replace("3. three. Extra sentence.", "3. three.")
    f = check_deletion_only(L(BEFORE), L(after))
    assert codes(f) == ["TRUNCATED_LINE"]
    assert f[0].severity == "info"


def test_incident_fusion_is_caught_in_both_checks():
    before = "- Do it (no new error code). Extra.\n5. **Read-only** mode\n"
    after = "- Do it (no new error code).5. **Read-only** mode\n"
    assert codes(check_fused_items(L(after))) == ["FUSED_ITEM"]
    assert "ADDED_LINE" in codes(check_deletion_only(L(before), L(after)))


# ---- 3. DANGLING_REFERENCE ------------------------------------------------ #

def test_dangling_token_defined_in_deleted_line():
    before = "- Defines `foo_bar` here\n- Uses it\n- Later mentions `foo_bar` again"
    after = "- Uses it\n- Later mentions `foo_bar` again"
    f = check_dangling(L(before), L(after))
    assert codes(f) == ["DANGLING_REFERENCE"] and f[0].line == 2


def test_dangling_issue_ref():
    before = "Blocked by #123 per plan\nkeep\nsee #123"
    after = "keep\nsee #123"
    assert codes(check_dangling(L(before), L(after))) == ["DANGLING_REFERENCE"]


def test_token_only_in_deleted_lines_is_fine():
    before = "- Defines `foo` here\n- keep"
    assert check_dangling(L(before), L("- keep")) == []


def test_token_defined_in_retained_line_is_fine():
    before = "- Defines `foo` here\n- Removed mentions `foo`\n- keep `foo`"
    after = "- Defines `foo` here\n- keep `foo`"
    assert check_dangling(L(before), L(after)) == []


def test_issue_ref_prefix_not_confused():
    before = "drop #12 here\nkeep #123"
    after = "keep #123"
    assert check_dangling(L(before), L(after)) == []


def test_token_defined_in_truncated_tail_is_dangling():
    before = "- Intro. Then `tail_tok` defined.\n- uses `tail_tok`"
    after = "- Intro.\n- uses `tail_tok`"
    assert codes(check_dangling(L(before), L(after))) == ["DANGLING_REFERENCE"]


# ---- 4. context + CLI ----------------------------------------------------- #

def test_context_lines_window_and_marker():
    lines = [f"l{i}" for i in range(1, 11)]
    out = context_lines(lines, 5)
    assert len(out) == 7 and out[3].startswith(">") and "l5" in out[3]
    assert len(context_lines(lines, 1)) == 4


def _files(tmp_path, before, after):
    b, a = tmp_path / "b.md", tmp_path / "a.md"
    b.write_text(before, encoding="utf-8")
    a.write_text(after, encoding="utf-8")
    return ["--before", str(b), "--after", str(a)]


def test_cli_clean_exit_0(tmp_path, capsys):
    assert main(_files(tmp_path, "- a\n- b\n", "- a\n")) == 0
    assert "OK" in capsys.readouterr().out


def test_cli_findings_exit_1_with_context(tmp_path, capsys):
    rc = main(_files(tmp_path, "- a\n", "- a.5. **x**\n"))
    out = capsys.readouterr().out
    assert rc == 1 and "FUSED_ITEM" in out and ">    1|" in out


def test_cli_expect_deletion_only(tmp_path, capsys):
    args = _files(tmp_path, "- a\n", "- a\n- b\n")
    assert main(args) == 0
    assert main(args + ["--expect-deletion-only"]) == 1


def test_cli_json_line(tmp_path, capsys):
    main(_files(tmp_path, "- a\n- b\n", "- a\n") + ["--json"])
    last = capsys.readouterr().out.strip().splitlines()
    data = json.loads([x for x in last if x.startswith("{")][0])
    assert data["clean"] is True and data["delta"] == -1


def test_cli_missing_file_exit_2(tmp_path, capsys):
    assert main(["--before", str(tmp_path / "nope"), "--after", str(tmp_path / "nope")]) == 2


def test_cli_usage_error_exit_2(capsys):
    assert main([]) == 2


def test_cli_non_utf8_exit_2(tmp_path):
    b = tmp_path / "b.md"
    b.write_bytes(b"\xff\xfe\x00bad")
    assert main(["--before", str(b), "--after", str(b)]) == 2


def test_read_seam_injectable(monkeypatch, capsys):
    monkeypatch.setattr(lint_mod, "_read_text", lambda p: "- a\n")
    assert main(["--before", "x", "--after", "y"]) == 0


# ---- 5. STALE_COUNT_CLAIM ------------------------------------------------- #

def spec(items, budget, extra=""):
    """Build a spec body: Acceptance criteria items, Budget, then ``extra``."""
    body = ["# Spec", "", "## Acceptance criteria", ""]
    body += [f"- [ ] {t}" for t in items]
    body += ["", "## Budget", "", budget, ""]
    if extra:
        body += ["## Notes", "", extra]
    return "\n".join(body)


STALE_BUDGET = "One guard, one replaced test and nine new tests."


def stale(findings):
    return [f for f in findings if f.code == "STALE_COUNT_CLAIM"]


def test_stale_test_claim_flagged_as_error():
    before = spec(["a test of x", "b"], STALE_BUDGET)
    after = spec(["a test of x", "b", "another test of y"], STALE_BUDGET)
    f = stale(lint_mod.lint(before, after)[0])
    assert len(f) == 1
    assert f[0].severity == "error" and f[0].file == "after"
    assert f[0].line == after.split("\n").index(STALE_BUDGET) + 1
    assert '"nine new tests"' in f[0].message and "+1" in f[0].message
    assert "one replaced test" not in f[0].message


def test_stale_claim_exit_1_through_main(tmp_path, capsys):
    before = spec(["a test of x"], STALE_BUDGET)
    after = spec(["a test of x", "another test of y"], STALE_BUDGET)
    assert main(_files(tmp_path, before, after)) == 1
    out = capsys.readouterr().out
    assert "ERROR STALE_COUNT_CLAIM after:" in out and ">" in out


def test_claim_updated_in_same_edit_is_clean():
    before = spec(["a test of x"], STALE_BUDGET)
    after = spec(["a test of x", "another test of y"],
                 "One guard, one replaced test and ten new tests.")
    assert stale(lint_mod.lint(before, after)[0]) == []


def test_no_criteria_delta_is_clean():
    before = spec(["a test of x", "b"], STALE_BUDGET)
    after = spec(["a test of x, reworded", "b"], STALE_BUDGET)
    assert stale(lint_mod.lint(before, after)[0]) == []


def test_added_non_test_item_does_not_flag_test_claim():
    before = spec(["a test of x"], STALE_BUDGET)
    after = spec(["a test of x", "docs updated"], STALE_BUDGET)
    assert stale(lint_mod.lint(before, after)[0]) == []


def test_removed_test_item_flags_test_claim_with_negative_delta():
    before = spec(["a test of x", "tests for y"], STALE_BUDGET)
    after = spec(["a test of x"], STALE_BUDGET)
    f = stale(lint_mod.lint(before, after)[0])
    assert len(f) == 1 and "-1" in f[0].message


def test_criteria_claim_flags_on_total_item_delta():
    budget = "Covers 5 acceptance criteria in total."
    before = spec(["a", "b"], budget)
    after = spec(["a", "b", "c"], budget)
    f = stale(lint_mod.lint(before, after)[0])
    assert len(f) == 1 and '"5 acceptance criteria"' in f[0].message
    assert "+1" in f[0].message


@pytest.mark.parametrize("budget", [
    "Seven checkboxes.", "three criteria", "one criterion", "4 checkbox"])
def test_criteria_claim_shapes(budget):
    before = spec(["a"], budget)
    after = spec(["a", "b"], budget)
    assert len(stale(lint_mod.lint(before, after)[0])) == 1


def test_criteria_claim_not_flagged_when_only_total_unchanged():
    budget = "Covers 5 criteria."
    before = spec(["a", "b"], budget)
    after = spec(["a", "c"], budget)
    assert stale(lint_mod.lint(before, after)[0]) == []


def test_claim_outside_budget_section_ignored():
    before = spec(["a test of x"], "Nothing numeric.", "Elsewhere: nine new tests.")
    after = spec(["a test of x", "another test"], "Nothing numeric.",
                 "Elsewhere: nine new tests.")
    assert stale(lint_mod.lint(before, after)[0]) == []


def test_claim_in_fenced_block_in_budget_ignored():
    budget = "Budget:\n\n```\nnine new tests\n```"
    before = spec(["a test of x"], budget)
    after = spec(["a test of x", "another test"], budget)
    assert stale(lint_mod.lint(before, after)[0]) == []


def test_claim_in_inline_code_ignored():
    budget = "The literal `nine new tests` is a string."
    before = spec(["a test of x"], budget)
    after = spec(["a test of x", "another test"], budget)
    assert stale(lint_mod.lint(before, after)[0]) == []


@pytest.mark.parametrize("budget", [
    "A new test and a replaced test.",
    "an extra test",
    "Three replaced tests.",
    "one replaced test",
])
def test_article_and_replaced_counts_never_flagged(budget):
    before = spec(["a test of x"], budget)
    after = spec(["a test of x", "another test"], budget)
    assert stale(lint_mod.lint(before, after)[0]) == []


def test_digit_form_claim_flagged():
    before = spec(["a test of x"], "Adds 2 new tests.")
    after = spec(["a test of x", "another test"], "Adds 2 new tests.")
    f = stale(lint_mod.lint(before, after)[0])
    assert len(f) == 1 and '"2 new tests"' in f[0].message


def test_claim_identity_is_case_insensitive():
    before = spec(["a test"], "Adds Two New Tests.")
    after = spec(["a test", "b test"], "Adds two new tests.")
    assert len(stale(lint_mod.lint(before, after)[0])) == 1


def test_claim_new_in_after_budget_not_stale():
    before = spec(["a test"], "Adds two new tests.")
    after = spec(["a test", "b test"], "Adds three added tests.")
    assert stale(lint_mod.lint(before, after)[0]) == []


def test_repeated_claim_reported_once():
    budget = "Adds two new tests.\n\nAgain: two new tests."
    before = spec(["a test"], budget)
    after = spec(["a test", "b test"], budget)
    assert len(stale(lint_mod.lint(before, after)[0])) == 1


def test_deletion_only_severity_is_info_and_exit_0(tmp_path, capsys):
    before = spec(["a test of x", "another test"], STALE_BUDGET)
    after = spec(["a test of x"], STALE_BUDGET)
    f = stale(lint_mod.lint(before, after, True)[0])
    assert len(f) == 1 and f[0].severity == "info"
    assert "next edit" in f[0].message
    assert main(_files(tmp_path, before, after) + ["--expect-deletion-only"]) == 0
    assert "INFO STALE_COUNT_CLAIM" in capsys.readouterr().out


def test_same_stale_input_is_error_without_deletion_flag(tmp_path):
    before = spec(["a test of x", "another test"], STALE_BUDGET)
    after = spec(["a test of x"], STALE_BUDGET)
    assert stale(lint_mod.lint(before, after)[0])[0].severity == "error"
    assert main(_files(tmp_path, before, after)) == 1


def test_missing_acceptance_heading_emits_nothing():
    plain = "# Spec\n\n- a test\n\n## Budget\n\nnine new tests\n"
    grown = plain.replace("- a test\n", "- a test\n- b test\n")
    assert stale(lint_mod.lint(plain, grown)[0]) == []
    with_ac = spec(["a test"], STALE_BUDGET)
    assert stale(lint_mod.lint(with_ac, grown)[0]) == []
    assert stale(lint_mod.lint(grown, with_ac)[0]) == []


def test_missing_budget_emits_nothing():
    nb = "# Spec\n\n## Acceptance criteria\n\n- a test\n"
    nb2 = nb + "- b test\n"
    assert stale(lint_mod.lint(nb, nb2)[0]) == []
    with_budget = spec(["a test"], STALE_BUDGET)
    assert stale(lint_mod.lint(with_budget, nb2)[0]) == []


def test_json_output_includes_finding(tmp_path, capsys):
    before = spec(["a test"], STALE_BUDGET)
    after = spec(["a test", "b test"], STALE_BUDGET)
    main(_files(tmp_path, before, after) + ["--json"])
    out = capsys.readouterr().out.splitlines()
    data = json.loads([x for x in out if x.startswith("{")][0])
    assert data["clean"] is False
    assert [f["code"] for f in data["findings"] if f["severity"] == "error"] == [
        "STALE_COUNT_CLAIM"]


def test_info_finding_keeps_json_clean(tmp_path, capsys):
    before = spec(["a test", "b test"], STALE_BUDGET)
    after = spec(["a test"], STALE_BUDGET)
    rc = main(_files(tmp_path, before, after) + ["--expect-deletion-only", "--json"])
    out = capsys.readouterr().out.splitlines()
    data = json.loads([x for x in out if x.startswith("{")][0])
    assert rc == 0 and data["clean"] is True
    assert any(f["code"] == "STALE_COUNT_CLAIM" for f in data["findings"])


def test_section_ends_at_same_or_higher_heading():
    # Items under a later same-level heading are not acceptance criteria.
    before = ("## Acceptance criteria\n- a test\n## Notes\n- x test\n"
              "## Budget\nnine new tests\n")
    after = before.replace("- x test\n", "- x test\n- y test\n")
    assert stale(lint_mod.lint(before, after)[0]) == []


def test_subheadings_stay_inside_section():
    before = ("## Acceptance criteria\n- a test\n### Sub\n- b test\n"
              "## Budget\nnine new tests\n")
    after = before.replace("- b test\n", "- b test\n- c test\n")
    assert len(stale(lint_mod.lint(before, after)[0])) == 1


def test_heading_inside_fence_does_not_end_section():
    before = ("## Acceptance criteria\n- a test\n```\n## Not a heading\n```\n"
              "- b test\n## Budget\nnine new tests\n")
    after = before.replace("- b test\n", "- b test\n- c test\n")
    assert len(stale(lint_mod.lint(before, after)[0])) == 1


def test_headings_are_case_insensitive_and_any_level():
    before = "# acceptance CRITERIA\n- a test\n### budget\nnine new tests\n"
    after = before.replace("- a test\n", "- a test\n- b test\n")
    assert len(stale(lint_mod.lint(before, after)[0])) == 1


def test_regression_two_new_tests_unchanged_while_criteria_doubled():
    budget = "One guard in `drain_slices`, one replaced test and two new tests."
    before = spec([f"criterion {i}" for i in range(6)], budget)
    after = spec([f"criterion {i}" for i in range(6)]
                 + [f"test that case {i}" for i in range(6)], budget)
    f = stale(lint_mod.lint(before, after)[0])
    assert len(f) == 1
    assert '"two new tests"' in f[0].message and "+6" in f[0].message
    assert "replaced" not in f[0].message


# ---- 6. STALE_COUNT_CLAIM: section edges, claim shapes, message ----------- #

def test_budget_claim_on_first_line_after_heading_is_seen():
    before = "## Acceptance criteria\n- a test\n## Budget\nnine new tests\n## Tail\nx\n"
    after = before.replace("- a test\n", "- a test\n- b test\n")
    assert len(stale(lint_mod.lint(before, after)[0])) == 1


def test_budget_claim_on_last_line_before_next_heading_is_seen():
    before = "## Acceptance criteria\n- a test\n## Budget\nintro\nnine new tests\n## Tail\nx\n"
    after = before.replace("- a test\n", "- a test\n- b test\n")
    assert len(stale(lint_mod.lint(before, after)[0])) == 1


def test_budget_claim_on_last_line_of_file_without_trailing_newline_is_seen():
    before = "## Acceptance criteria\n- a test\n## Budget\nintro\nnine new tests"
    after = before.replace("- a test\n", "- a test\n- b test\n")
    assert len(stale(lint_mod.lint(before, after)[0])) == 1


def test_sole_first_line_acceptance_item_removal_is_a_delta():
    before = "## Acceptance criteria\n- a test\n## Budget\nnine new tests\n"
    after = "## Acceptance criteria\n## Budget\nnine new tests\n"
    f = stale(lint_mod.lint(before, after)[0])
    assert len(f) == 1 and "-1" in f[0].message


def test_reordering_acceptance_items_is_no_delta_before_next_heading():
    # The last body line differs between the bodies; dropping it from the
    # section (off by one) would turn a reorder into a +1 test delta.
    before = ("## Acceptance criteria\n- note\n- the test\n## Budget\nnine new tests\n")
    after = ("## Acceptance criteria\n- the test\n- note\n## Budget\nnine new tests\n")
    assert stale(lint_mod.lint(before, after)[0]) == []


def test_reordering_acceptance_items_is_no_delta_at_end_of_file():
    before = "## Budget\nnine new tests\n## Acceptance criteria\n- note\n- the test"
    after = "## Budget\nnine new tests\n## Acceptance criteria\n- the test\n- note"
    assert stale(lint_mod.lint(before, after)[0]) == []


def test_next_heading_text_is_not_part_of_budget():
    before = spec(["a test"], "None here.").rstrip("\n") + "\n## Adds nine new tests\n"
    after = before.replace("- [ ] a test\n", "- [ ] a test\n- [ ] b test\n")
    assert stale(lint_mod.lint(before, after)[0]) == []


def test_higher_level_heading_ends_acceptance_section():
    before = ("## Acceptance criteria\n- a test\n# Appendix\n- x test\n"
              "## Budget\nnine new tests\n")
    after = before.replace("- x test\n", "- x test\n- y test\n")
    assert stale(lint_mod.lint(before, after)[0]) == []


def test_higher_level_heading_ends_budget_section():
    before = ("## Acceptance criteria\n- a test\n## Budget\nnine new tests\n"
              "# Appendix\nten new tests\n")
    after = before.replace("- a test\n", "- a test\n- b test\n")
    f = stale(lint_mod.lint(before, after)[0])
    assert [x for x in f if "ten new tests" in x.message] == []
    assert len(f) == 1


def test_issue_ref_at_line_start_is_not_a_heading():
    before = ("## Acceptance criteria\n- a test\n#1234 landed first\n- b test\n"
              "## Budget\nnine new tests\n")
    after = before.replace("- b test\n", "- b test\n- c test\n")
    assert len(stale(lint_mod.lint(before, after)[0])) == 1


def test_heading_names_need_a_word_boundary_but_allow_suffix_text():
    base = spec(["a test"], STALE_BUDGET)
    grown = spec(["a test", "b test"], STALE_BUDGET)
    for old, new in [("## Budget", "## Budgeting"),
                     ("## Acceptance criteria", "## Acceptance criteriaish")]:
        assert stale(lint_mod.lint(base.replace(old, new),
                                   grown.replace(old, new))[0]) == []
    for old, new in [("## Budget", "## Budget (v2)"),
                     ("## Acceptance criteria", "## Acceptance criteria (v2)")]:
        assert len(stale(lint_mod.lint(base.replace(old, new),
                                       grown.replace(old, new))[0])) == 1


def test_list_items_before_the_acceptance_heading_are_not_counted():
    before = ("# Spec\n\n- intro test\n\n## Acceptance criteria\n- a test\n\n"
              "## Budget\nnine new tests\n")
    after = before.replace("- intro test\n", "- intro test\n- more test\n")
    assert stale(lint_mod.lint(before, after)[0]) == []


def test_test_item_needs_the_whole_word():
    before = spec(["a test of x"], STALE_BUDGET)
    for text in ("latest docs", "contest rules", "testing notes", "attests"):
        after = spec(["a test of x", text], STALE_BUDGET)
        assert stale(lint_mod.lint(before, after)[0]) == [], text


def test_test_item_match_is_case_insensitive():
    before = spec(["a test of x"], STALE_BUDGET)
    after = spec(["a test of x", "Tests for y"], STALE_BUDGET)
    assert len(stale(lint_mod.lint(before, after)[0])) == 1


def test_reported_line_is_first_occurrence_of_a_repeated_claim():
    budget = "Adds two new tests.\n\nAgain: two new tests."
    before = spec(["a test"], budget)
    after = spec(["a test", "b test"], budget)
    f = stale(lint_mod.lint(before, after)[0])
    assert f[0].line == after.split("\n").index("Adds two new tests.") + 1


@pytest.mark.parametrize("old_b, new_b, kept", [
    ("Adds two new tests.\n\nPlus four extra tests.",
     "Adds three new tests.\n\nPlus four extra tests.", "four extra tests"),
    ("Adds two new tests and four extra tests.",
     "Adds three new tests and four extra tests.", "four extra tests"),
    ("Adds two new tests.\n\nPlus five added tests.",
     "Adds three new tests.\n\nPlus five added tests.", "five added tests"),
    ("Adds two new tests and five added tests.",
     "Adds three new tests and five added tests.", "five added tests"),
])
def test_every_claim_in_the_budget_is_judged_not_just_the_first(old_b, new_b, kept):
    before = spec(["a test"], old_b)
    after = spec(["a test", "b test"], new_b)
    f = stale(lint_mod.lint(before, after)[0])
    assert len(f) == 1 and f"\"{kept}\"" in f[0].message


def test_number_must_stand_alone_not_inside_a_decimal_or_word():
    budget = "Adds 2.5 new tests and none extra tests."
    before = spec(["a test"], budget)
    after = spec(["a test", "b test"], budget)
    assert stale(lint_mod.lint(before, after)[0]) == []


@pytest.mark.parametrize("word", [
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen",
    "eighteen", "nineteen", "twenty"])
def test_every_number_word_up_to_twenty_is_a_claim(word):
    budget = f"Adds {word} new tests."
    before = spec(["a test"], budget)
    after = spec(["a test", "b test"], budget)
    f = stale(lint_mod.lint(before, after)[0])
    assert len(f) == 1 and f'"{word} new tests"' in f[0].message


def test_multi_digit_number_is_a_claim():
    budget = "Adds 12 new tests."
    before = spec(["a test"], budget)
    after = spec(["a test", "b test"], budget)
    f = stale(lint_mod.lint(before, after)[0])
    assert len(f) == 1 and '"12 new tests"' in f[0].message


def test_deletion_hint_only_in_deletion_mode():
    before = spec(["a test of x", "another test"], STALE_BUDGET)
    after = spec(["a test of x"], STALE_BUDGET)
    assert "next edit" not in stale(lint_mod.lint(before, after)[0])[0].message
    assert "next edit" in stale(lint_mod.lint(before, after, True)[0])[0].message


def test_message_names_the_family_that_changed():
    t = stale(lint_mod.lint(spec(["a test"], STALE_BUDGET),
                            spec(["a test", "b test"], STALE_BUDGET))[0])
    assert "acceptance items mentioning tests" in t[0].message
    c = stale(lint_mod.lint(spec(["a"], "Covers 5 criteria."),
                            spec(["a", "b"], "Covers 5 criteria."))[0])
    assert "acceptance criteria items" in c[0].message
    assert "mentioning tests" not in c[0].message


@pytest.mark.parametrize("old, new", [
    ("twenty-one new tests", "thirty-one new tests"),
    ("1,200 new tests", "2,200 new tests"),
])
def test_compound_numbers_updated_in_same_edit_are_clean(old, new):
    before = spec(["a test"], f"Adds {old}.")
    after = spec(["a test", "b test"], f"Adds {new}.")
    assert stale(lint_mod.lint(before, after)[0]) == []
