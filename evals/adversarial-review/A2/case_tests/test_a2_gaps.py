"""A2's only write to shared per-skill data: lines appended to ``gaps.md``.

Whatever sat in ``gaps.md`` at the resolved ref (recorded in
``provenance.toml``) must still be there, untouched and in order; A2's own
lines come after it, one guarded behavior per line (the heading set below is exact), in the ``- <behavior>:
<reason>`` format #996 pins. Lines another child appends in between (A1 or A3)
are not this test's business, so nothing here pins the file's total length.
"""

from __future__ import annotations

import re
import tomllib

_ENTRY = re.compile(r"^- [^:]+: \S.*$")
_NONE = re.compile(r"^- none: \S.*$")
_A2_BEHAVIORS = (
    "refutation pass over surviving lens findings",
    "freeze the tree before dispatching the lenses",
    "zero findings read against the run journal",
    "inverted bias for credential-exposure findings",
)


def _current(case_dir) -> list[str]:
    return (case_dir.parent / "gaps.md").read_text(encoding="utf-8").splitlines()


def _at_resolved_ref(case_dir, git) -> list[str]:
    provenance = tomllib.loads((case_dir / "provenance.toml").read_text(encoding="utf-8"))
    return git("show", f"{provenance['resolved_ref']}:evals/adversarial-review/gaps.md").splitlines()


def test_existing_gaps_lines_are_untouched_and_in_order(case_dir, git):
    before = _at_resolved_ref(case_dir, git)
    # Lines that sat in gaps.md at the resolved ref survive, in order, as a subsequence
    # of today's file (a sibling's appended lines may sit between them and A2's).
    now = iter(_current(case_dir))
    for line in before:
        assert any(line == candidate for candidate in now), f"gaps.md lost or reordered {line!r}"


def _mine(case_dir) -> list[str]:
    prefixes = tuple(f"- {behavior}:" for behavior in _A2_BEHAVIORS)
    return [line for line in _current(case_dir) if line.startswith(prefixes)]


def test_every_line_a2_added_is_a_wellformed_entry(case_dir):
    """Only A2's own lines: a sibling's lines (A1, A3) and the header are not this child's to judge."""
    mine = _mine(case_dir)
    assert len(mine) == len(_A2_BEHAVIORS)
    for line in mine:
        assert _ENTRY.match(line), line


def test_a_wellformedness_check_over_a2_lines_goes_red_on_a_reasonless_line():
    assert not _ENTRY.match("- inverted bias for credential-exposure findings:")
    assert not _ENTRY.match("- inverted bias for credential-exposure findings: ")


def test_a2_appended_one_line_per_behavior_it_cannot_exercise(case_dir):
    lines = _current(case_dir)
    for behavior in _A2_BEHAVIORS:
        matching = [line for line in lines if line.startswith(f"- {behavior}:")]
        assert len(matching) == 1, (behavior, matching)
        assert _ENTRY.match(matching[0])


def test_a2_lines_come_after_everything_that_was_there_at_the_resolved_ref(case_dir, git):
    before = [line for line in _at_resolved_ref(case_dir, git) if line.strip()]
    lines = _current(case_dir)
    last_old = max(lines.index(line) for line in before)
    first_mine = min(
        index for index, line in enumerate(lines) if line.startswith(tuple(f"- {b}:" for b in _A2_BEHAVIORS))
    )
    assert first_mine > last_old


def test_a2_lines_keep_their_relative_order(case_dir):
    lines = _current(case_dir)
    positions = [
        next(index for index, line in enumerate(lines) if line.startswith(f"- {behavior}:"))
        for behavior in _A2_BEHAVIORS
    ]
    assert positions == sorted(positions)


def test_a_none_entry_is_never_mixed_with_real_a2_behaviors(case_dir):
    """``- none: ...`` means there is no unexercised behavior; A2 has four, so it must not appear among them."""
    mine = [line for line in _current(case_dir) if line.startswith(tuple(f"- {b}:" for b in _A2_BEHAVIORS))]
    assert mine and not any(_NONE.match(line) for line in mine)
