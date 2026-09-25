"""Pure coverage for `description_blocks`: fenced sections of an MR description.

The author's prose is the one thing these tools must never rewrite, so every
test here asserts on exact text, not on the presence of a phrase.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from description_blocks import BlockError, Waiver, parse_waivers, replace_block  # noqa: E402

SWEEP_BEGIN = "<!-- mr-preflight:sweep:begin -->"
SWEEP_END = "<!-- mr-preflight:sweep:end -->"
RECORD_BEGIN = "<!-- mr-preflight:record:begin -->"
RECORD_END = "<!-- mr-preflight:record:end -->"

ABOVE = "## What this does\n\nRenames the schema.  \nTrailing spaces stay.\n\n"
BETWEEN = "\n## Between the blocks\n\n- a list the author wrote\n\n"
BELOW = "\n## Below\n\nLast line has no newline"


def test_replacing_the_sweep_block_keeps_every_byte_outside_it() -> None:
    record = f"{RECORD_BEGIN}\nrecord body the sweep must not touch\n{RECORD_END}\n"
    before = (
        f"{ABOVE}{SWEEP_BEGIN}\nold sweep body\n{SWEEP_END}\n"
        f"{BETWEEN}{record}{BELOW}"
    )

    after = replace_block(before, "sweep", "new sweep body\n")

    assert after == (
        f"{ABOVE}{SWEEP_BEGIN}\nnew sweep body\n{SWEEP_END}\n"
        f"{BETWEEN}{record}{BELOW}"
    )


def test_a_description_with_no_block_gets_one_appended_after_its_prose() -> None:
    prose = f"{ABOVE}{BELOW}"

    after = replace_block(prose, "sweep", "sweep body\n")

    assert after == f"{prose}\n\n{SWEEP_BEGIN}\nsweep body\n{SWEEP_END}\n"


@pytest.mark.parametrize(
    "broken",
    [
        f"{SWEEP_BEGIN}\nno end marker\n",  # begin, never closed
        f"no begin marker\n{SWEEP_END}\n",  # end, never opened
        f"{SWEEP_END}\nbackwards\n{SWEEP_BEGIN}\n",  # end before begin
        f"{SWEEP_BEGIN}\na\n{SWEEP_END}\n{SWEEP_BEGIN}\nb\n{SWEEP_END}\n",  # two blocks
    ],
)
def test_broken_markers_are_an_error_not_a_fresh_block(broken: str) -> None:
    """Appending a new block beside a broken one would leave two sweeps in
    the MR, and whichever one holds the waivers might not be the one read."""
    with pytest.raises(BlockError, match="mr-preflight:sweep"):
        replace_block(broken, "sweep", "body\n")


def test_waiver_lines_parse_into_token_path_and_reason() -> None:
    body = (
        "Renamed: `LEGACY_SCHEMA` -> `LEGACY_SCHEMA_RAW`\n"
        "- [ ] `sql/audit.sql:1` `LEGACY_SCHEMA`\n"
        "- waive LEGACY_SCHEMA CHANGELOG.md: historical entry\n"
        "- waive LEGACY_SCHEMA sql/a:b.sql: kept for the v1 replay\n"
        "- waive `load_curves` `docs/My Notes.md`: quoted from the 2025 design\n"
    )

    waivers, malformed = parse_waivers(body)

    assert waivers == [
        Waiver(token="LEGACY_SCHEMA", path="CHANGELOG.md", reason="historical entry"),
        Waiver(token="LEGACY_SCHEMA", path="sql/a:b.sql", reason="kept for the v1 replay"),
        Waiver(token="load_curves", path="docs/My Notes.md", reason="quoted from the 2025 design"),
    ]
    assert malformed == []


@pytest.mark.parametrize(
    "line",
    [
        "- waive LEGACY_SCHEMA",  # no path, no reason
        "- waive LEGACY_SCHEMA CHANGELOG.md",  # no reason
        "- waive LEGACY_SCHEMA CHANGELOG.md historical entry",  # no `: `
        "- waive LEGACY_SCHEMA CHANGELOG.md:",  # empty reason
        "- waive LEGACY_SCHEMA CHANGELOG.md:    ",  # blank reason
        "- waive",  # nothing at all
    ],
)
def test_a_malformed_waiver_line_is_reported_not_skipped(line: str) -> None:
    waivers, malformed = parse_waivers(f"intro\n{line}\n- [ ] a to-do line\n")

    assert waivers == []
    assert malformed == [line]


def test_words_that_merely_start_with_waive_are_not_waiver_lines() -> None:
    waivers, malformed = parse_waivers("- waiver policy: see the skill\n- waived above\n")

    assert (waivers, malformed) == ([], [])
