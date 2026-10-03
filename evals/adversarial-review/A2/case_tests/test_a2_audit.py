"""Matcher development and the cross-match audit, run over the experiment's saved lens replies.

``ab_raws/`` holds the 18 verbatim lens replies from the terse-lens-contract A/B
(arms ``a``, ``b``, ``a2``; three lenses; two replicates). They are used here,
and only here, to develop the matchers and audit them: they are NEVER calibration
data -- nothing in ``predicates.py``, ``case.toml`` or the prompt reads them, and
admission of a gated item happens only through the hand-run issue #989 executing
this case itself (see ``test_the_ab_raws_are_never_read_as_calibration_input``).

The audit pins which findings each repaired matcher credits (so loosening or
tightening a matcher shows up as a diff against the table), checks that no finding
credits two items (a cross-match would mean a matcher steals a sibling's defect),
and shows the two artifacts of the experiment's disjunctive rule the repair retires.
"""

from __future__ import annotations

import re
from pathlib import Path


from evals._harness.dispatch import Evidence
from evals._harness.matchers import extract_findings

_LENSES = ("domain", "test_veracity", "spec_conformance")

# (arm, replicate, lens, line, item): every credit the repaired matchers give over the 18 raws.
_EXPECTED_CREDITS = [
    ('a', 1, 'domain', 115, 'A2-D1'),
    ('a', 1, 'domain', 207, 'A2-D2'),
    ('a', 1, 'domain', 168, 'A2-D5'),
    ('a', 1, 'spec_conformance', 207, 'A2-D2'),
    ('a', 1, 'spec_conformance', 115, 'A2-D1'),
    ('a', 1, 'spec_conformance', 233, 'A2-D5'),
    ('a', 1, 'spec_conformance', 3, 'A2-D4'),
    ('a', 2, 'domain', 207, 'A2-D2'),
    ('a', 2, 'domain', 115, 'A2-D1'),
    ('a', 2, 'spec_conformance', 3, 'A2-D4'),
    ('a', 2, 'spec_conformance', 115, 'A2-D1'),
    ('a', 2, 'spec_conformance', 158, 'A2-D5'),
    ('b', 1, 'domain', 115, 'A2-D1'),
    ('b', 1, 'domain', 207, 'A2-D2'),
    ('b', 1, 'domain', 168, 'A2-D5'),
    ('b', 1, 'test_veracity', 115, 'A2-D1'),
    ('b', 1, 'test_veracity', 207, 'A2-D2'),
    ('b', 1, 'spec_conformance', 207, 'A2-D2'),
    ('b', 1, 'spec_conformance', 115, 'A2-D1'),
    ('b', 1, 'spec_conformance', 168, 'A2-D5'),
    ('b', 1, 'spec_conformance', 3, 'A2-D4'),
    ('b', 2, 'domain', 115, 'A2-D1'),
    ('b', 2, 'domain', 207, 'A2-D2'),
    ('b', 2, 'test_veracity', 127, 'A2-D5'),
    ('b', 2, 'test_veracity', 3, 'A2-D4'),
    ('b', 2, 'test_veracity', 151, 'A2-D3'),
    ('b', 2, 'spec_conformance', 3, 'A2-D4'),
    ('a2', 1, 'test_veracity', 115, 'A2-D1'),
    ('a2', 1, 'test_veracity', 207, 'A2-D2'),
    ('a2', 1, 'spec_conformance', 153, 'A2-D5'),
    ('a2', 1, 'spec_conformance', 3, 'A2-D4'),
    ('a2', 2, 'domain', 115, 'A2-D1'),
    ('a2', 2, 'domain', 207, 'A2-D2'),
    ('a2', 2, 'spec_conformance', 234, 'A2-D5'),
    ('a2', 2, 'spec_conformance', 3, 'A2-D4'),
]


def _raw_findings(case_dir: Path):
    for arm in ("a", "b", "a2"):
        for rep in (1, 2):
            for lens in _LENSES:
                text = (case_dir / "ab_raws" / arm / f"{lens}-r{rep}.txt").read_text(encoding="utf-8")
                findings, _ok = extract_findings(text)
                for finding in findings:
                    yield arm, rep, lens, finding


def _credits(case_dir, items, predicates) -> list[tuple]:
    credited = []
    for arm, rep, lens, finding in _raw_findings(case_dir):
        evidence = Evidence(transcripts=[], findings=[finding], workdir=None, end_state={})
        for item_id, item in items.items():
            if getattr(predicates, item["scorer"])(evidence, **item["params"]):
                credited.append((arm, rep, lens, int(finding["line"]), item_id))
    return credited


def test_the_raws_are_the_eighteen_saved_replies(case_dir):
    assert len(list((case_dir / "ab_raws").rglob("*.txt"))) == 18


def test_the_repaired_matchers_credit_exactly_the_pinned_findings(case_dir, items, predicates):
    assert _credits(case_dir, items, predicates) == _EXPECTED_CREDITS


def test_no_finding_credits_two_items(case_dir, items, predicates):
    seen: dict[tuple, str] = {}
    for arm, rep, lens, line, item_id in _credits(case_dir, items, predicates):
        key = (arm, rep, lens, line)
        assert key not in seen, f"{key} credits both {seen[key]} and {item_id}"
        seen[key] = item_id


def test_every_gated_defect_is_credited_in_every_arm(case_dir, items, predicates):
    credits = _credits(case_dir, items, predicates)
    for item_id in ("A2-D1", "A2-D2", "A2-D4", "A2-D5"):
        for arm in ("a", "b", "a2"):
            assert any(c[0] == arm and c[4] == item_id for c in credits), (item_id, arm)


def _experiment_rule(finding: dict, defect: dict) -> bool:
    """The experiment's ``score_arm.finding_matches``, re-stated: a disjunctive rule.

    A window item credits on ``in_window or regex``; a window-less item drops the file
    requirement altogether and runs the regex over description plus file path.
    """
    file_str = str(finding.get("file", ""))
    description = str(finding.get("description", ""))
    regex = re.compile(defect["regex"], re.IGNORECASE)
    window = defect.get("line_window")
    if window is None:
        return bool(regex.search(description + " " + file_str))
    if not file_str.endswith(defect["file_suffix"]):
        return False
    line = finding.get("line")
    in_window = isinstance(line, (int, float)) and window[0] <= int(line) <= window[1]
    return in_window or bool(regex.search(description))


def test_the_disjunctive_rule_credited_a_passing_mention_the_repair_retires(case_dir, defects, items, predicates):
    """a2 r2 spec_conformance line 153 only lists ``staged-but-uncommitted`` among the spec's guards."""
    (finding,) = [
        f
        for arm, rep, lens, f in _raw_findings(case_dir)
        if (arm, rep, lens, int(f["line"])) == ("a2", 2, "spec_conformance", 153)
    ]
    assert _experiment_rule(finding, defects["D5"]) is True
    assert not any(c[:4] == ("a2", 2, "spec_conformance", 153) for c in _credits(case_dir, items, predicates))


def test_the_disjunctive_rule_credited_a_line_window_collision_the_repair_retires(case_dir, defects, items, predicates):
    """a r2 test_veracity line 148 is a D1 consequence that merely lands inside D3's line window."""
    (finding,) = [
        f
        for arm, rep, lens, f in _raw_findings(case_dir)
        if (arm, rep, lens, int(f["line"])) == ("a", 2, "test_veracity", 148)
    ]
    assert _experiment_rule(finding, defects["D3"]) is True
    assert not any(c[:4] == ("a", 2, "test_veracity", 148) for c in _credits(case_dir, items, predicates))


def test_every_genuine_d5_finding_is_credited_and_no_passing_mention_is(case_dir, items, predicates):
    """The audit counts on the 18 raws: 8 genuine absence findings, 2 passing mentions, all on the script."""
    genuine = {
        ("a", 1, "domain", 168), ("a", 1, "spec_conformance", 233), ("a", 2, "spec_conformance", 158),
        ("b", 1, "domain", 168), ("b", 1, "spec_conformance", 168), ("b", 2, "test_veracity", 127),
        ("a2", 1, "spec_conformance", 153), ("a2", 2, "spec_conformance", 234),
    }
    passing = {("a2", 1, "spec_conformance", 118), ("a2", 2, "spec_conformance", 153)}
    credited = {c[:4] for c in _credits(case_dir, items, predicates) if c[4] == "A2-D5"}
    assert genuine <= credited, sorted(genuine - credited)
    assert not (passing & credited), sorted(passing & credited)
    assert credited == genuine
