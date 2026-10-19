"""Pins the raw frontmatter step shared by smoke_test and dev_cycle_validate.

Both readers once carried their own copy of the delimiter rules, and each
edge case below was a bug fixed in one copy but not the other. The cases run
through the shared extractor *and* through both callers, so a regression in
either adapter or in the shared step goes red here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts._frontmatter import extract_block
from scripts.dev_cycle_validate import parse_state_file
from scripts.smoke_test import _parse_frontmatter

_STATE_BODY = "feature: demo\nstatus: in_progress\ncurrent_phase: plan\n"


def _state(tmp_path: Path, extra: str = "") -> object:
    path = tmp_path / "demo.state.md"
    path.write_text(f"---\n{_STATE_BODY}{extra}---\n\n# Demo\n")
    return parse_state_file(path)


# --- #123: a '#' only starts a comment after whitespace ----------------------


def test_hash_without_leading_space_is_part_of_the_value_in_both_callers(tmp_path):
    assert _state(tmp_path, "branch: fix/issue-#123\n").branch == "fix/issue-#123"
    assert _parse_frontmatter("---\nbranch: fix/issue-#123\n---\n") == {
        "branch": "fix/issue-#123"
    }


def test_hash_after_whitespace_is_a_comment_in_both_callers(tmp_path):
    assert _state(tmp_path, "branch: fix/x # note\n").branch == "fix/x"
    assert _parse_frontmatter("---\nbranch: fix/x # note\n---\n") == {"branch": "fix/x"}


# --- multiline: the closing '---' must sit on its own line -------------------


def test_a_dashed_fragment_inside_a_value_does_not_close_the_block(tmp_path):
    text = "---\nname: a\nnote: b\n---trailing\nrole: r\n---\nbody\n"
    assert extract_block(text) == "\nname: a\nnote: b\n---trailing\nrole: r"
    assert extract_block(text, strict_open=True) == "name: a\nnote: b\n---trailing\nrole: r"
    assert _parse_frontmatter(text)["role"] == "r"
    state = _state(tmp_path, "branch: x\n---trailing\n")
    assert state.branch == "x"


def test_closing_delimiter_may_carry_trailing_whitespace_or_end_the_text():
    assert extract_block("---\na: b\n---  ") == "\na: b"
    assert extract_block("---\na: b\n---\n") == "\na: b"


# --- shape: what is and is not a block ---------------------------------------


@pytest.mark.parametrize("text", ["# heading\n", "", "--\na: b\n---\n", "---\na: b\n"])
def test_no_opener_or_no_closer_is_none_in_both_modes(text):
    assert extract_block(text) is None
    assert extract_block(text, strict_open=True) is None


def test_modes_differ_exactly_where_the_callers_always_differed():
    # smoke_test accepted any '---' prefix and an empty block; the state-file
    # reader required '---\n' and at least one character of content.
    assert extract_block("---x\na: b\n---\n") is not None
    assert extract_block("---x\na: b\n---\n", strict_open=True) is None
    assert extract_block("---\n---\n") == ""
    assert extract_block("---\n---\n", strict_open=True) is None
    assert extract_block("---\n\n---\n") == "\n"
    assert extract_block("---\n\n---\n", strict_open=True) is None
    # An empty lenient block does not fall through to a later '---' line.
    assert extract_block("---\n---\nfoo: 1\n---\n") == ""
    assert extract_block("---\n---\nfoo: 1\n---\n", strict_open=True) == "---\nfoo: 1"


def test_both_callers_reject_a_missing_block(tmp_path):
    assert _parse_frontmatter("no frontmatter\n") is None
    path = tmp_path / "bad.state.md"
    path.write_text("no frontmatter\n")
    with pytest.raises(ValueError, match="No YAML frontmatter"):
        parse_state_file(path)
