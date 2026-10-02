"""A1's only write to shared per-skill data: appended lines in ``gaps.md``."""

from __future__ import annotations

import re

_HEADER = [
    "# Gaps",
    "",
    "Guarded behaviors that cannot be exercised as a single-prompt case, one line of reason each.",
]
_ENTRY = re.compile(r"^- [^:]+: \S.*$")


def _lines(case_dir) -> list[str]:
    return (case_dir.parent / "gaps.md").read_text(encoding="utf-8").splitlines()


def test_gaps_md_keeps_its_header_and_every_line_is_well_formed(case_dir):
    lines = _lines(case_dir)
    assert lines[:3] == _HEADER
    body = [line for line in lines[3:] if line.strip()]
    assert body, "A1 appends at least one line (or a '- none: <reason>' line)"
    for line in body:
        assert _ENTRY.match(line), line


def test_a1_appended_the_behaviors_a_single_prompt_cannot_exercise(case_dir):
    text = "\n".join(_lines(case_dir))
    assert "- three-attempt ceiling" in text
    assert "- refusing an author's pressure" in text
