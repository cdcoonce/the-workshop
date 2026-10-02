"""D1, D2, D4 and D5 are gate candidates scored by #992's conjunctive matcher; D3 is a trend item.

Every test scores a real attempt: synthetic lens transcripts go through
``dispatch.score_attempt`` against this case's own ``case.toml`` and
``predicates.py``, so the wiring (item params -> scorer -> ``review_match``) is
what is under test, not a re-implementation of it.

A gated item credits only when BOTH its location (a line window, or the file
suffix alone for a file-level item) AND its regex hit. An agent that does
nothing -- an empty reply, an unparseable reply, findings about something else
-- is never credited.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals._harness.dispatch import score_attempt

SYNC_SCRIPT = "plugins/workbench/skills/vault-wrap-up/scripts/sync_boundary_squash.py"
SYNC_TESTS = "plugins/workbench/skills/vault-wrap-up/scripts/tests/test_sync_boundary_squash.py"
VAULT_SYNC_COMMAND = "plugins/workbench/skills/vault-sync/references/command.md"
WRAP_UP_COMMAND = "plugins/workbench/skills/vault-wrap-up/references/command.md"

GATED = ("A2-D1", "A2-D2", "A2-D4", "A2-D5")
TREND = ("A2-D3",)
ALL_ITEMS = GATED + TREND
WINDOWED = ("A2-D1", "A2-D2", "A2-D3")
FILE_LEVEL = ("A2-D4", "A2-D5")

# For each item: a finding that must credit it, a finding in the right place whose
# text addresses something else, a finding with the right text in the wrong file,
# and (for a windowed item) the right text and file on a line outside the window.
_CASES = {
    "A2-D1": dict(
        file=SYNC_SCRIPT,
        line=115,
        description="classify_pushed_prefix returns first_unpushed + 1, an off-by-one: the first unpushed commit is treated as pushed.",
        neutral="The report dict never records the squash base's author, which makes later audits harder.",
        wrong_file=SYNC_TESTS,
        outside_line=40,
    ),
    "A2-D2": dict(
        file=SYNC_SCRIPT,
        line=207,
        description="_is_ancestor(remote_head, sha) has its arguments swapped, so pushed-ness is inverted for every session commit.",
        neutral="The report dict never records the squash base's author, which makes later audits harder.",
        wrong_file=SYNC_TESTS,
        outside_line=40,
    ),
    "A2-D3": dict(
        file=SYNC_TESTS,
        line=151,
        description="assert len(session) >= 1 cannot fail on any history, so the exactly-one collapse is never asserted.",
        neutral="The fixture helper hardcodes the author email, which reads oddly.",
        wrong_file=SYNC_SCRIPT,
        outside_line=40,
    ),
    "A2-D4": dict(
        file=VAULT_SYNC_COMMAND,
        line=3,
        description="The diff edits vault-sync/references/command.md although the spec says vault-sync is untouched.",
        neutral="This edit is outside the scope the pull request description gives.",
        wrong_file=WRAP_UP_COMMAND,
        outside_line=None,
    ),
    "A2-D5": dict(
        file=SYNC_SCRIPT,
        line=168,
        description="squash() never checks for staged-but-uncommitted changes before rewriting history, although the spec lists that guard.",
        neutral="squash() reads HEAD twice, which costs an extra subprocess call.",
        wrong_file=SYNC_TESTS,
        outside_line=None,
    ),
}

_OFF_TOPIC = dict(
    file="plugins/workbench/skills/vault-wrap-up/references/command.md",
    line=11,
    description="Step 10 wording is unclear about retries.",
)


def _finding(item: str, **overrides) -> dict:
    case = _CASES[item]
    base = dict(file=case["file"], line=case["line"], description=case["description"])
    return {**base, **overrides}


def _write_transcript(path: Path, text: str) -> Path:
    path.write_text(
        json.dumps(
            {
                "type": "assistant",
                "message": {"model": "claude-test", "content": [{"type": "text", "text": text}]},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def score(case_dir, tmp_path):
    """Score one inline attempt whose lens agents reply with the given findings lists."""

    def run(*lens_findings: list[dict], raw_replies: list[str] | None = None):
        replies = raw_replies or [json.dumps({"findings": findings}) for findings in lens_findings]
        paths = [_write_transcript(tmp_path / f"lens-{index}.jsonl", text) for index, text in enumerate(replies)]
        attempt, _unmatched = score_attempt(case_dir, paths, None, set(GATED))
        return attempt

    return run


def _hits(attempt) -> set[str]:
    return {item for item, outcome in attempt.item_hits.items() if outcome == "hit"}


# --- wiring ---------------------------------------------------------------------


def test_the_case_declares_exactly_the_five_items(items):
    assert set(items) == set(ALL_ITEMS)


@pytest.mark.parametrize("item", GATED)
def test_d1_d2_d4_d5_are_gate_candidates(items, item):
    assert items[item]["kind"] == "gate-candidate"


def test_d3_is_a_trend_item_never_gated(items):
    assert items["A2-D3"]["kind"] == "trend"
    assert [i for i, spec in items.items() if spec["kind"] == "trend"] == ["A2-D3"]


@pytest.mark.parametrize("item", ALL_ITEMS)
def test_each_item_names_a_scorer_predicates_defines(items, predicates, item):
    scorer = getattr(predicates, items[item]["scorer"], None)
    assert callable(scorer)


def test_every_item_has_its_own_scorer_function(items):
    scorers = [spec["scorer"] for spec in items.values()]
    assert len(set(scorers)) == len(scorers)


# --- every item credits its own defect, and only its own -------------------------


@pytest.mark.parametrize("item", ALL_ITEMS)
def test_a_finding_that_addresses_the_defect_credits_exactly_that_item(score, item):
    attempt = score([_finding(item)])
    assert _hits(attempt) == {item}


def test_one_attempt_credits_each_defect_found_by_a_different_lens(score):
    attempt = score(
        [_finding("A2-D1"), _finding("A2-D2")],
        [_finding("A2-D3")],
        [_finding("A2-D4"), _finding("A2-D5")],
    )
    assert _hits(attempt) == set(ALL_ITEMS)


# --- the agent does nothing: never credited ---------------------------------------


def test_an_empty_findings_list_credits_no_item(score):
    assert _hits(score([], [], [])) == set()


def test_every_lens_returning_nothing_is_a_miss_for_every_item_not_a_hit(score):
    attempt = score([], [], [])
    assert attempt.item_hits == {item: "miss" for item in ALL_ITEMS}


def test_a_reply_with_no_findings_envelope_credits_no_item(score):
    attempt = score(raw_replies=["I read the diff and everything looks fine to me."])
    assert _hits(attempt) == set()
    assert attempt.parse_error is True


def test_findings_about_something_else_credit_no_item(score):
    assert _hits(score([_OFF_TOPIC], [_OFF_TOPIC])) == set()


# --- conjunct 1 (location) and conjunct 2 (regex), one negative test each ----------


@pytest.mark.parametrize("item", ALL_ITEMS)
def test_right_text_in_the_wrong_file_does_not_credit(score, item):
    attempt = score([_finding(item, file=_CASES[item]["wrong_file"])])
    assert item not in _hits(attempt)


@pytest.mark.parametrize("item", ALL_ITEMS)
def test_right_location_with_text_that_does_not_address_the_defect_does_not_credit(score, item):
    attempt = score([_finding(item, description=_CASES[item]["neutral"])])
    assert item not in _hits(attempt)


@pytest.mark.parametrize("item", WINDOWED)
def test_right_file_and_text_outside_the_line_window_does_not_credit(score, item):
    attempt = score([_finding(item, line=_CASES[item]["outside_line"])])
    assert item not in _hits(attempt)


@pytest.mark.parametrize("item", WINDOWED)
def test_a_windowed_item_needs_a_line_number(score, item):
    finding = _finding(item)
    del finding["line"]
    assert item not in _hits(score([finding]))


@pytest.mark.parametrize("item", FILE_LEVEL)
def test_a_file_level_item_ignores_the_line_number(score, item):
    for line in (1, 9999):
        assert item in _hits(score([_finding(item, line=line)]))
    finding = _finding(item)
    del finding["line"]
    assert item in _hits(score([finding]))


@pytest.mark.parametrize("item", WINDOWED)
def test_the_window_edges_are_inclusive_and_one_past_either_edge_is_out(score, items, item):
    low, high = items[item]["params"]["line_window"]
    assert item in _hits(score([_finding(item, line=low)]))
    assert item in _hits(score([_finding(item, line=high)]))
    assert item not in _hits(score([_finding(item, line=low - 1)]))
    assert item not in _hits(score([_finding(item, line=high + 1)]))


def test_the_file_level_items_declare_no_line_window(items):
    for item in FILE_LEVEL:
        assert "line_window" not in items[item]["params"]


def test_the_windowed_items_declare_a_two_integer_window(items):
    for item in WINDOWED:
        window = items[item]["params"]["line_window"]
        assert len(window) == 2 and all(isinstance(edge, int) for edge in window) and window[0] < window[1]


# --- path matching is segment-aligned and separator-normalised ----------------------


@pytest.mark.parametrize("item", ALL_ITEMS)
def test_a_path_that_only_ends_with_the_suffix_text_does_not_credit(score, items, item):
    suffix = items[item]["params"]["file_suffix"]
    lookalike = "legacy_" + suffix
    assert item not in _hits(score([_finding(item, file=lookalike)]))
    assert item not in _hits(score([_finding(item, file="legacy/" + suffix.replace("/", "_"))]))


@pytest.mark.parametrize("item", ALL_ITEMS)
def test_backslash_separators_are_normalised(score, item):
    finding = _finding(item)
    finding["file"] = finding["file"].replace("/", "\\")
    assert item in _hits(score([finding]))


@pytest.mark.parametrize("item", ALL_ITEMS)
def test_a_diff_style_prefix_on_the_path_still_credits(score, item):
    finding = _finding(item)
    finding["file"] = "b/" + finding["file"]
    assert item in _hits(score([finding]))


@pytest.mark.parametrize("item", ALL_ITEMS)
def test_a_bare_filename_cannot_satisfy_a_suffix_with_a_directory_part(score, items, item):
    suffix = items[item]["params"]["file_suffix"]
    finding = _finding(item, file=suffix.rsplit("/", 1)[-1])
    assert item not in _hits(score([finding]))
