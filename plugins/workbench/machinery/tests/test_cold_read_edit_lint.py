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
