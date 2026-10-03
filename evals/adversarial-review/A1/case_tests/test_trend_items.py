"""The three planted defects are wired as trend items, scored location AND regex.

Each scorer credits a defect only when one paragraph (or list item) of the
case-agent's reply names the defect's file AND matches the defect's regex —
#992's ``review_match`` applied to prose segments.
"""

from __future__ import annotations

import pytest

_DEFECTS = {
    "A1-defect-decimal-from-float": "defect_decimal_from_float",
    "A1-defect-tests-no-teeth": "defect_tests_no_teeth",
    "A1-defect-missed-call-site": "defect_missed_call_site",
}

_HITS = {
    "A1-defect-decimal-from-float": (
        "`src/settlement/rounding.py`: `Decimal(amount)` is built from a float, so Decimal(1.005) is "
        "1.00499... and the half-up fix is a no-op."
    ),
    "A1-defect-tests-no-teeth": (
        "tests/test_rounding.py: restoring main's rounding.py leaves all six tests green; "
        "test_rounds_half_cent_up asserts == 1.00, contradicting its name."
    ),
    "A1-defect-missed-call-site": (
        "src/settlement/invoice.py::line_total still calls bare round(), so it never routes "
        "through round_amount."
    ),
}


def _item(case_toml: dict, item_id: str) -> dict:
    return next(item for item in case_toml["items"] if item["id"] == item_id)


def _score(predicates, case_toml, evidence_for, item_id: str, reply: str) -> bool:
    item = _item(case_toml, item_id)
    scorer = getattr(predicates, item["scorer"])
    return scorer(evidence_for(reply), **item.get("params", {}))


@pytest.mark.parametrize("item_id", sorted(_DEFECTS))
def test_each_defect_is_a_trend_item_scored_by_its_own_scorer(case_toml, item_id):
    item = _item(case_toml, item_id)
    assert item["kind"] == "trend"
    assert item["scorer"] == _DEFECTS[item_id]


@pytest.mark.parametrize("item_id", sorted(_HITS))
def test_a_paragraph_naming_the_file_and_the_defect_is_credited(
    predicates, case_toml, evidence_for, item_id
):
    reply = "## Findings\n\n" + _HITS[item_id] + "\n\n## Verdict\nNo.\n"
    assert _score(predicates, case_toml, evidence_for, item_id, reply) is True


@pytest.mark.parametrize("item_id", sorted(_HITS))
def test_the_does_nothing_reply_credits_no_defect(predicates, case_toml, evidence_for, item_id):
    assert _score(predicates, case_toml, evidence_for, item_id, "Looks fine, ready to merge.") is False
    assert _score(predicates, case_toml, evidence_for, item_id, "") is False


@pytest.mark.parametrize("item_id", sorted(_HITS))
def test_the_defect_description_without_its_file_is_not_credited(
    predicates, case_toml, evidence_for, item_id
):
    import re

    stripped = re.sub(r"[\w./-]+\.py(::\w+)?", "the module", _HITS[item_id])
    assert _score(predicates, case_toml, evidence_for, item_id, stripped) is False


@pytest.mark.parametrize("item_id", sorted(_HITS))
def test_the_file_without_the_defect_regex_is_not_credited(predicates, case_toml, evidence_for, item_id):
    files = {
        "A1-defect-decimal-from-float": "src/settlement/rounding.py",
        "A1-defect-tests-no-teeth": "tests/test_rounding.py",
        "A1-defect-missed-call-site": "src/settlement/invoice.py",
    }
    reply = f"{files[item_id]} was reviewed and looks tidy.\n"
    assert _score(predicates, case_toml, evidence_for, item_id, reply) is False


def test_file_and_defect_in_different_paragraphs_is_not_credited(predicates, case_toml, evidence_for):
    reply = "src/settlement/invoice.py was read.\n\nline_total still calls bare round().\n"
    assert _score(predicates, case_toml, evidence_for, "A1-defect-missed-call-site", reply) is False


def test_rounding_module_and_its_test_file_are_not_confused(predicates, case_toml, evidence_for):
    float_defect_in_tests = "tests/test_rounding.py builds Decimal(1.005) from a float."
    assert (
        _score(predicates, case_toml, evidence_for, "A1-defect-decimal-from-float", float_defect_in_tests)
        is False
    )
    no_teeth_in_source = "src/settlement/rounding.py: restoring main leaves all six tests green."
    assert (
        _score(predicates, case_toml, evidence_for, "A1-defect-tests-no-teeth", no_teeth_in_source) is False
    )


def test_a_bare_basename_names_the_file(predicates, case_toml, evidence_for):
    reply = "- invoice.py: line_total still calls bare round().\n"
    assert _score(predicates, case_toml, evidence_for, "A1-defect-missed-call-site", reply) is True


def test_list_items_are_separate_segments(predicates, case_toml, evidence_for):
    reply = "- invoice.py was read.\n- line_total still calls bare round().\n"
    assert _score(predicates, case_toml, evidence_for, "A1-defect-missed-call-site", reply) is False


def test_a_json_findings_envelope_is_not_required(case_toml):
    assert "envelope" not in case_toml
