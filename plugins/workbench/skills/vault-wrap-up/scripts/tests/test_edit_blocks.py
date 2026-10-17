"""Tests for edit_blocks: splitting a file diff into independently stageable blocks."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from edit_blocks import apply_blocks, split_blocks  # noqa: E402

KD_BASE = (
    "# Key Decisions\n"
    "\n"
    "## Recent\n"
    "\n"
    "### 2026-10-15 — older entry\n"
    "\n"
    "**Decided:** old.\n"
)

OWN_ENTRY = (
    "### 2026-10-16 — own entry\n"
    "\n"
    "**Decided:** mine.\n"
    "\n"
    "**Why:** reasons.\n"
    "\n"
)

FOREIGN_ENTRY = (
    "### 2026-10-16 — foreign entry\n"
    "\n"
    "**Decided:** theirs.\n"
    "\n"
)


def _lines(text: str) -> list[str]:
    return text.splitlines(keepends=True)


def _two_sessions_under_recent() -> tuple[list[str], list[str]]:
    """Two sessions each inserted an entry directly under ``## Recent``."""
    old = _lines(KD_BASE)
    new = _lines(KD_BASE.replace("## Recent\n\n", "## Recent\n\n" + FOREIGN_ENTRY + OWN_ENTRY))
    return old, new


def test_adjacent_entries_under_one_anchor_split_into_one_block_each() -> None:
    old, new = _two_sessions_under_recent()
    blocks = split_blocks(old, new)
    assert [b.first_line for b in blocks] == [
        "### 2026-10-16 — foreign entry",
        "### 2026-10-16 — own entry",
    ]


def test_staging_only_own_block_excludes_the_foreign_entry() -> None:
    old, new = _two_sessions_under_recent()
    own = [b.id for b in split_blocks(old, new) if "own entry" in b.first_line]
    staged = "".join(apply_blocks(old, split_blocks(old, new), own))
    assert staged == KD_BASE.replace("## Recent\n\n", "## Recent\n\n" + OWN_ENTRY)
    assert "foreign entry" not in staged


def test_apply_all_reproduces_new_and_none_reproduces_old() -> None:
    old, new = _two_sessions_under_recent()
    blocks = split_blocks(old, new)
    assert apply_blocks(old, blocks, [b.id for b in blocks]) == new
    assert apply_blocks(old, blocks, []) == old


def test_adjacent_bullets_split_per_list_item() -> None:
    old = _lines("## Open threads\n\n- a\n- b\n")
    new = _lines("## Open threads\n\n- a\n- mine\n- theirs\n- b\n")
    blocks = split_blocks(old, new)
    assert [b.first_line for b in blocks] == ["- mine", "- theirs"]


def test_status_paragraphs_without_headings_split_per_paragraph() -> None:
    old = _lines("## Current Status\n\n**old:** status.\n")
    new = _lines("## Current Status\n\n**mine:** a.\n\n**theirs:** b.\n\n**old:** status.\n")
    blocks = split_blocks(old, new)
    assert [b.first_line for b in blocks] == ["**mine:** a.", "**theirs:** b."]


def test_equal_length_replacement_splits_per_line() -> None:
    old = _lines("- one: old\n- two: old\n")
    new = _lines("- one: mine\n- two: theirs\n")
    blocks = split_blocks(old, new)
    assert [b.kind for b in blocks] == ["replace", "replace"]
    mine = [b.id for b in blocks if "mine" in b.first_line]
    assert apply_blocks(old, blocks, mine) == _lines("- one: mine\n- two: old\n")


def test_unequal_replacement_stays_one_block() -> None:
    old = _lines("a\nb\n")
    new = _lines("x\n")
    blocks = split_blocks(old, new)
    assert len(blocks) == 1
    assert blocks[0].kind == "replace"


def test_deletion_block() -> None:
    old = _lines("a\nb\nc\n")
    new = _lines("a\nc\n")
    (block,) = split_blocks(old, new)
    assert block.kind == "delete"
    assert block.first_line == "b"
    assert apply_blocks(old, [block], [block.id]) == new


def test_ids_are_content_derived_and_survive_an_unrelated_edit() -> None:
    old, new = _two_sessions_under_recent()
    before = {b.first_line: b.id for b in split_blocks(old, new)}
    # The third session's edit lands ABOVE both entries, so an ordinal id
    # ("the second block") would now name a different block.
    later = new[:1] + ["added by a third session\n"] + new[1:]
    after = {b.first_line: b.id for b in split_blocks(old, later)}
    assert after["### 2026-10-16 — own entry"] == before["### 2026-10-16 — own entry"]


def test_identical_blocks_get_distinct_ids() -> None:
    # Same anchor, same content: only the occurrence suffix tells them apart.
    old = _lines("a\n")
    new = _lines("a\n- x\n- x\n")
    blocks = split_blocks(old, new)
    ids = [b.id for b in blocks]
    assert len(ids) == 2
    assert len(set(ids)) == 2
    assert apply_blocks(old, blocks, ids[:1]) == _lines("a\n- x\n")


def test_unknown_id_is_rejected() -> None:
    old, new = _two_sessions_under_recent()
    blocks = split_blocks(old, new)
    try:
        apply_blocks(old, blocks, ["nope"])
    except ValueError as exc:
        assert "nope" in str(exc)
    else:
        raise AssertionError("an unknown block id must raise")


def test_crlf_and_missing_final_newline_round_trip() -> None:
    old = _lines("a\r\nb")
    new = _lines("a\r\nnew\r\nb")
    blocks = split_blocks(old, new)
    assert apply_blocks(old, blocks, [b.id for b in blocks]) == new
