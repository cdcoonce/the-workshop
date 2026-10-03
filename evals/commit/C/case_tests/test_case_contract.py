"""commit/C satisfies the case-directory contract and stays inside its lane."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from commit_c_support import REPO_ROOT

from evals._harness.dispatch import (
    build_dispatch_prompt,
    build_no_skill_prompt,
    find_acceptance_leaks,
    find_duplicate_item_ids,
    find_invalid_modes,
)
from evals._harness.transcript import parse_transcript

GATE_SCORERS = [
    "env_not_committed",
    "no_blanket_add",
    "no_agent_attribution",
    "subject_format",
    "tests_before_first_add",
]
COMMIT_SKILL = REPO_ROOT / "plugins" / "workbench" / "skills" / "commit" / "SKILL.md"
GAPS_ENTRY = re.compile(r"^- [^:]+: \S.*$")


def test_the_case_declares_subagent_mode_and_a_prompt_file(case_toml, case_dir):
    assert case_toml["mode"] == "subagent"
    assert case_toml["prompt"] == "prompt.md"
    assert (case_dir / "prompt.md").is_file()
    assert (case_dir / "acceptance.md").is_file()


def test_five_gate_candidates_and_one_trend_item(case_toml):
    items = {item["id"]: item for item in case_toml["items"]}
    assert len(case_toml["items"]) == 6
    gates = [item for item in case_toml["items"] if item["kind"] == "gate-candidate"]
    trends = [item for item in case_toml["items"] if item["kind"] == "trend"]
    assert [item["scorer"] for item in gates] == GATE_SCORERS
    assert [item["scorer"] for item in trends] == ["atomic_split"]
    assert items["C-atomic-split"]["kind"] == "trend"


def test_every_item_scorer_is_a_function_in_predicates(case_toml, predicates):
    for item in case_toml["items"]:
        assert callable(getattr(predicates, item["scorer"], None)), item["id"]
    assert callable(predicates.end_state)


def test_the_case_is_valid_to_the_harness(case_dir):
    assert find_invalid_modes([case_dir]) == []
    assert find_duplicate_item_ids(case_dir.parent) == set()


def test_the_dispatch_prompt_leaks_nothing_from_acceptance(case_dir):
    prompt = build_dispatch_prompt(case_dir)
    assert prompt == (case_dir / "prompt.md").read_text(encoding="utf-8")
    assert find_acceptance_leaks(case_dir, prompt) == []
    assert find_acceptance_leaks(case_dir, build_no_skill_prompt(case_dir)) == []


def test_the_prompt_does_not_hint_at_the_gates(case_dir):
    prompt = (case_dir / "prompt.md").read_text(encoding="utf-8").lower()
    for hint in (".env", "co-authored", "attribution", "git add", "make test", "subject", "lowercase"):
        assert hint not in prompt, hint








def test_gaps_md_has_the_appended_entries_in_the_pinned_format():
    lines = (REPO_ROOT / "evals" / "commit" / "gaps.md").read_text(encoding="utf-8").splitlines()
    entries = [line for line in lines[3:] if line.strip()]
    assert entries, "this child must append at least one line"
    for line in entries:
        assert GAPS_ENTRY.match(line), line


def test_the_subject_pattern_names_exactly_the_skills_nine_types(predicates):
    text = COMMIT_SKILL.read_text(encoding="utf-8")
    skill_types = re.findall(r"^\| `([a-z]+)`\s*\|", text, flags=re.MULTILINE)
    assert len(skill_types) == 9
    pattern_types = re.match(r"\^\(([^)]*)\)", predicates.SUBJECT_PATTERN).group(1).split("|")
    assert pattern_types == skill_types


def test_the_committed_synthetic_transcripts_are_complete_envelopes(case_dir):
    for path in sorted((case_dir / "case_tests" / "transcripts").glob("*.jsonl")):
        transcript = parse_transcript(path)
        assert transcript.status == "complete", path.name
        assert transcript.final_text, path.name
        first = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
        assert first["type"] in {"user", "assistant"}
        assert "message" in first


def test_the_committed_good_transcript_runs_the_tests_first(case_dir):
    transcript = parse_transcript(case_dir / "case_tests" / "transcripts" / "good_run.jsonl")
    commands = [event.input["command"] for event in transcript.events if event.name == "Bash"]
    assert commands.index("make test") < min(i for i, c in enumerate(commands) if c.startswith("git add"))




@pytest.mark.parametrize(
    "spec",
    [
        "env_not_committed",
        "no_blanket_add",
        "no_agent_attribution",
        "subject_format",
        "tests_before_first_add",
        "atomic_split",
    ],
)
def test_every_scorer_has_a_teeth_spec_with_a_does_nothing_mutant(case_dir, spec):
    path = case_dir / f"{spec}.teeth.json"
    assert path.is_file(), path.name
    body = json.loads(path.read_text(encoding="utf-8"))
    labels = [mutant["label"] for mutant in body["mutants"]]
    assert any(label.startswith("[does-nothing]") for label in labels), labels
    assert all(mutant["file"] == "predicates.py" for mutant in body["mutants"])
    assert any(mutant.get("expect") == "survived" for mutant in body["mutants"]), "no control row"


def test_the_teeth_specs_cover_the_named_mutations(case_dir):
    text = " ".join(path.read_text(encoding="utf-8") for path in case_dir.glob("*.teeth.json"))
    for needle in (
        "`.env` committed",
        "git add -A",
        "Co-Authored-By",
        "trailing capital",
        "trailing period",
        "make test after the first git add",
        "does nothing",
    ):
        assert needle in text, needle




def test_the_fixture_file_set_matches_the_documented_layout(case_dir):
    top = {path.name for path in (case_dir / "fixture").iterdir()}
    assert top == {"base", "pending"}
    assert Path(case_dir / "fixture" / "base" / "Makefile").is_file()
