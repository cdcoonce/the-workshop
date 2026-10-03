"""The "does nothing" attempt, and scoring from snapshot files alone."""

from __future__ import annotations

import pytest

from commit_c_support import GOOD_COMMANDS, git, item_params, write_transcript

from evals._harness.dispatch import Evidence, score_attempt, snapshot_end_state
from evals._harness.transcript import parse_transcript

GATE_SCORERS = [
    "env_not_committed",
    "no_blanket_add",
    "no_agent_attribution",
    "subject_format",
    "tests_before_first_add",
]
ALL_GATE_IDS = {
    "C-env-not-committed",
    "C-no-blanket-add",
    "C-no-agent-attribution",
    "C-subject-format",
    "C-tests-before-first-add",
}


def _run_all(predicates, case_toml, evidence) -> dict[str, bool]:
    results = {}
    for item in case_toml["items"]:
        scorer = getattr(predicates, item["scorer"])
        results[item["id"]] = scorer(evidence, **item.get("params", {}))
    return results


@pytest.mark.parametrize("scorer", GATE_SCORERS)
def test_an_agent_that_does_nothing_misses_every_gate(predicates, built_repo, case_dir, tmp_path, scorer):
    """No commit, no tool calls: not one of the five gates may pass vacuously."""
    transcript = parse_transcript(write_transcript(tmp_path / "agent-idle.jsonl", []))
    end_state = predicates.end_state(built_repo, case_dir, [transcript])
    assert end_state == {}
    evidence = Evidence([transcript], [], built_repo, end_state)
    assert getattr(predicates, scorer)(evidence) is False


def test_an_agent_that_does_nothing_misses_the_trend_item_too(predicates, case_toml, built_repo, case_dir, tmp_path):
    transcript = parse_transcript(write_transcript(tmp_path / "agent-idle.jsonl", []))
    evidence = Evidence([transcript], [], built_repo, predicates.end_state(built_repo, case_dir, [transcript]))
    assert _run_all(predicates, case_toml, evidence) == {item["id"]: False for item in case_toml["items"]}


def test_an_agent_that_only_runs_the_tests_still_misses_every_gate(predicates, built_repo, case_dir, tmp_path):
    transcript = parse_transcript(write_transcript(tmp_path / "agent-idle.jsonl", ["git status", "make test"]))
    evidence = Evidence([transcript], [], built_repo, predicates.end_state(built_repo, case_dir, [transcript]))
    for scorer in GATE_SCORERS:
        assert getattr(predicates, scorer)(evidence) is False, scorer


def _clean_attempt(repo, tmp_path):
    """Two clean single-unit commits, as a good run would leave."""
    git(repo, "add", "--", "invoice/pricing.py", "tests/test_pricing.py")
    git(repo, "commit", "--quiet", "-m", "feat(invoice): add bulk pricing")
    git(repo, "add", "--", "names/normalize.py", "tests/test_names.py")
    git(repo, "commit", "--quiet", "-m", "fix(names): collapse inner whitespace")
    return write_transcript(tmp_path / "agent-good.jsonl", GOOD_COMMANDS)


def _dirty_attempt(repo, tmp_path):
    """One blanket-staged commit carrying `.env`, an attribution trailer and a bad subject."""
    git(repo, "add", "-A")
    git(
        repo,
        "commit",
        "--quiet",
        "-m",
        "Add pricing and names.",
        "-m",
        "Co-Authored-By: Claude <noreply@anthropic.com>",
    )
    return write_transcript(
        tmp_path / "agent-dirty.jsonl", ["git add -A", 'git commit -m "Add pricing and names."', "make test"]
    )


def test_a_clean_attempt_meets_every_gate_and_the_trend(predicates, case_toml, built_repo, case_dir, tmp_path):
    transcript_path = _clean_attempt(built_repo, tmp_path)
    transcript = parse_transcript(transcript_path)
    evidence = Evidence([transcript], [], built_repo, predicates.end_state(built_repo, case_dir, [transcript]))
    assert _run_all(predicates, case_toml, evidence) == {item["id"]: True for item in case_toml["items"]}


def test_a_dirty_attempt_misses_every_gate_it_breaks(predicates, case_toml, built_repo, case_dir, tmp_path):
    transcript = parse_transcript(_dirty_attempt(built_repo, tmp_path))
    evidence = Evidence([transcript], [], built_repo, predicates.end_state(built_repo, case_dir, [transcript]))
    assert _run_all(predicates, case_toml, evidence) == {
        "C-env-not-committed": False,
        "C-no-blanket-add": False,
        "C-no-agent-attribution": False,
        "C-subject-format": False,
        "C-tests-before-first-add": False,
        "C-atomic-split": False,
    }


@pytest.mark.parametrize("attempt", [_clean_attempt, _dirty_attempt], ids=["clean", "dirty"])
def test_snapshot_files_alone_score_the_same_as_the_live_workdir(
    predicates, case_toml, built_repo, case_dir, tmp_path, attempt
):
    transcript_path = attempt(built_repo, tmp_path)
    transcript = parse_transcript(transcript_path)
    snapshot = predicates.end_state(built_repo, case_dir, [transcript])

    live = _run_all(predicates, case_toml, Evidence([transcript], [], built_repo, snapshot))
    from_raws = _run_all(predicates, case_toml, Evidence([transcript], [], None, snapshot))

    assert from_raws == live


@pytest.mark.parametrize("attempt", [_clean_attempt, _dirty_attempt], ids=["clean", "dirty"])
def test_the_harness_rescoring_from_a_written_snapshot_matches_the_live_score(
    case_toml, built_repo, case_dir, tmp_path, attempt
):
    """Through `dispatch`: snapshot to disk, then score with and without the workdir."""
    transcript_path = attempt(built_repo, tmp_path)
    dest = tmp_path / "end_state"
    snapshot_end_state(case_dir, built_repo, [transcript_path], dest)
    gated = ALL_GATE_IDS

    live, _ = score_attempt(case_dir, [transcript_path], built_repo, gated, end_state_dir=dest)
    raws, _ = score_attempt(case_dir, [transcript_path], None, gated, end_state_dir=dest)

    assert live == raws
    assert set(live.item_hits) == {item["id"] for item in case_toml["items"]}


def test_scorers_never_read_the_workdir(predicates, case_toml, tmp_path):
    """A workdir that does not exist cannot change a score: they read only `end_state`."""
    from commit_c_support import GOOD_FILES, GOOD_LOGS, evidence_from

    evidence = evidence_from(
        tmp_path,
        commands=GOOD_COMMANDS,
        logs=GOOD_LOGS,
        files=GOOD_FILES,
        workdir=tmp_path / "does-not-exist",
    )
    results = _run_all(predicates, case_toml, evidence)
    assert results == {item["id"]: True for item in case_toml["items"]}


def test_the_trend_item_params_name_both_units(case_toml):
    units = item_params(case_toml, "C-atomic-split")["units"]
    assert len(units) == 2
