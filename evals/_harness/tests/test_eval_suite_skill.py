"""Tests that the eval-suite conductor skill documents its full contract.

``.claude/skills/eval-suite/SKILL.md`` is a repo-local Claude Code skill: it
is loaded and followed by hand, never executed by any script, CI job, or afk
child. These tests only check that its documented content covers what #995's
acceptance criteria require it to cover — they never invoke the skill.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_SKILL_PATH = (
    Path(__file__).resolve().parents[3] / ".claude" / "skills" / "eval-suite" / "SKILL.md"
)

_RUN_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1] / "schemas" / "run-file.schema.json"
)

_REQUIRED_ENTRY_POINTS = {
    "dispatch.snapshot_end_state",
    "dispatch.score_attempt",
    "scorer.classify_attempt",
    "scorer.should_retry",
    "scorer.compute_verdict",
    "calibration.fixture_fingerprint",
    "ledger.write_run",
    "report.write_report",
}


def _skill_text() -> str:
    return _SKILL_PATH.read_text(encoding="utf-8")


def _backticked_table_cells(text: str) -> set[str]:
    """Every backticked first-column cell of a markdown table row in *text*."""
    cells: set[str] = set()
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        row_cells = [cell.strip() for cell in line.strip("|").split("|")]
        if not row_cells:
            continue
        first = row_cells[0]
        if first.startswith("`") and first.endswith("`") and len(first) > 2:
            cells.add(first.strip("`"))
    return cells


def _normalize(text: str) -> str:
    """Collapse every whitespace run to one space so assertions survive reflow."""
    return " ".join(text.split())


def _sections() -> dict[str, str]:
    """Whitespace-normalised body of every ``## `` section, keyed by its leading number.

    Numbered sections (``## 1. ...``) are keyed ``"1"``..``"7"``; the others by
    their heading text. A mutant that removes a section's rule removes it from
    that section's body, so a rule asserted against its own section cannot be
    satisfied by an incidental mention elsewhere in the document.
    """
    sections: dict[str, str] = {}
    parts = re.split(r"^## +(.+)$", _skill_text(), flags=re.MULTILINE)
    for heading, body in zip(parts[1::2], parts[2::2]):
        numbered = re.match(r"(\d+)\.", heading)
        sections[numbered.group(1) if numbered else heading.strip()] = _normalize(body)
    return sections


def _section(key: str) -> str:
    sections = _sections()
    assert key in sections, f"SKILL.md has no section {key!r}; has {sorted(sections)}"
    return sections[key]


def _assert_in_order(text: str, *needles: str) -> None:
    positions = []
    for needle in needles:
        assert needle in text, f"missing {needle!r}"
        positions.append(text.index(needle))
    assert positions == sorted(positions), f"{needles} are out of order"


def test_skill_file_exists():
    assert _SKILL_PATH.is_file()


def test_skill_has_every_numbered_section_and_the_entry_point_table():
    sections = _sections()
    assert {"1", "2", "3", "4", "5", "6", "7"} <= set(sections)
    assert "Harness entry points, by module and function" in sections


def test_skill_documents_fixture_preparation():
    section = _section("1")
    assert "fixture_fingerprint(case_dir)" in section
    assert "not-yet-existing" in section
    assert "pre-existing" not in section
    assert "python <builder> <dest>" in section
    assert re.search(r"only a committed `fixture/` tree: copy `fixture/` into `<dest>`", section)
    assert re.search(r"Before the fixture's \*first\* attempt", section)
    assert "cases[].fixture_fingerprint" in section


def test_skill_derives_gated_items_from_the_manifest_with_the_right_polarity():
    section = _section("2")
    assert "checks.manifest" in section
    assert "gated iff its id appears there" in section
    assert re.search(r"id is absent is a trend item", section)
    # The inverted rule must not be stated anywhere in the section.
    assert "gated iff its id is absent" not in section
    assert not re.search(r"every listed id is a trend", section)


def test_skill_says_the_conductor_reads_the_manifest_and_the_scorer_never_does():
    section = _section("2")
    assert re.search(r"conductor is the only reader of this file", section)
    assert re.search(r"scorer.{0,40}never reads it itself", section)
    assert not re.search(r"scorer reads (?:it|the manifest)", section)


def test_skill_routes_the_gated_set_to_all_three_places():
    section = _section("2")
    assert re.search(r"passed as `score_attempt`'s `gated_ids` argument", section)
    assert re.search(r"passed as each item's `gated` flag inside `compute_verdict`'s `items`", section)
    assert re.search(r"recorded verbatim as the case's `gated_items` field in the run file", section)


def test_skill_dispatches_subagent_cases_with_the_built_prompt_outside_the_checkout():
    section = _section("3")
    assert re.search(r"`mode = \"subagent\"`.{0,120}case-agent as a subagent", section)
    assert "build_dispatch_prompt(case_dir)" in section
    assert "build_no_skill_prompt(case_dir)" in section
    assert re.search(r"never inside the-workshop checkout", section)


def test_skill_assigns_lens_agent_dispatch_to_the_conductor_for_inline_mode():
    section = _section("3")
    assert re.search(r"`mode = \"inline\"`.{0,80}`A2`", section)
    assert re.search(r"conductor plays adversarial-review's own conductor role itself", section)
    assert re.search(r"does not dispatch a subagent that then dispatches lens agents", section)
    assert re.search(r"dispatches each lens agent directly", section)
    assert re.search(r"collects one transcript per lens agent", section)


def test_skill_snapshots_end_state_before_scoring_every_attempt():
    section = _section("4")
    assert re.search(r"After every attempt .{0,40}, before scoring it", section)
    _assert_in_order(section, "snapshot_end_state(", "score_attempt(")
    assert "end_state_dir=<the end_state/ directory just snapshotted>" in section
    assert re.search(r"re-scored later from raws alone", section)
    assert '`transcript_status="dispatch_error"` only when the attempt never produced a transcript' in section


def test_skill_states_the_retry_rule_exactly():
    section = _section("5")
    assert "evals._harness.scorer.should_retry(item_states, counted_attempts, reserve_used)" in section
    assert re.search(r"counted_attempts counts only non-indeterminate", section)
    assert "reserve of 2" in section
    assert "counted_attempts reaches 3," in section
    assert "counted_attempts + reserve_used reaches 5" in section
    assert re.search(r"5 is therefore the hard execution cap per fixture", section)
    assert re.search(r"never increments counted_attempts", section)


def test_skill_computes_the_verdict_from_per_execution_outcomes():
    section = _section("5")
    assert "compute_verdict(items)" in section
    assert re.search(r"`\"hit\"`/`\"miss\"`/`\"indeterminate\"` per execution", section)


def test_skill_writes_the_run_file_and_the_red_report():
    section = _section("6")
    assert "ledger.write_run(runs_dir, run, raw_sources)" in section
    assert re.search(r'verdict is `"red"`.{0,80}report.write_report\(run_file\)', section)
    assert re.search(r"never edits `scorer.py`, `ledger.py`, `report.py`", section)


def test_skill_lands_the_run_as_a_test_evals_pr_into_dev_and_leaves_campaigns_by_hand():
    section = _section("7")
    assert re.search(r"own `test\(evals\):` PR into `dev`", section)
    assert "riding along with the skill PR that triggered it" in section
    assert "improve-skill" in section
    assert re.search(r"started by hand, never automatically", section)


def test_skill_documents_every_named_harness_entry_point():
    """Checks the entry-points table specifically, not prose elsewhere.

    A table-scoped check survives incidental prose redundancy: a mutant that
    drops one row from the table is still caught, even if that function is
    also mentioned in passing somewhere else in the document.
    """
    table_cells = _backticked_table_cells(_skill_text())
    missing = _REQUIRED_ENTRY_POINTS - table_cells
    assert missing == set()


def test_skill_states_it_executes_nothing_itself_and_is_never_run_by_afk_or_ci():
    text = _normalize(_skill_text())
    assert "It executes nothing on its own." in text
    assert re.search(r"never invoked by an afk child", text)
    assert "#989" in text


def test_skill_front_matter_names_the_skill():
    text = _skill_text()
    assert re.match(r"---\nname: eval-suite\n", text)


# ---------------------------------------------------------------------------
# what a conductor needs in order to build the run file without guessing
# ---------------------------------------------------------------------------


def _backticked_names(section: str) -> set[str]:
    return set(re.findall(r"`([A-Za-z_][A-Za-z0-9_.\[\]]*)`", section))


def test_skill_names_every_run_file_key_the_schema_requires():
    schema = json.loads(_RUN_SCHEMA_PATH.read_text(encoding="utf-8"))
    case_schema = schema["properties"]["cases"]["items"]
    attempt_schema = case_schema["properties"]["attempts"]["items"]
    required = (
        set(schema["required"]) | set(case_schema["required"]) | set(attempt_schema["required"])
    )
    documented = _backticked_names(_section("6"))
    assert required - documented == set()


def test_skill_says_write_run_computes_model_ids_and_rewrites_raw():
    section = _section("6")
    assert re.search(r"`model_ids`.{0,120}computed by\s*`write_run`", section)
    assert re.search(r"`raw`.{0,160}key into `raw_sources`", section)
    assert re.search(r"`write_run` .{0,40}overwrites? .{0,40}`raw`", section)


def test_skill_says_runs_dir_is_the_skills_runs_directory():
    assert re.search(r"`runs_dir` is `evals/<skill>/runs/`", _section("6"))


def test_skill_says_the_fingerprint_comes_from_compute_fingerprint():
    section = _section("6")
    assert "evals._harness.fingerprint.compute_fingerprint(" in section
    assert re.search(r"`run\[\"fingerprint\"\]`", section)
    for keyword in ("direct_paths", "injection_paths", "plugin_version", "claude_code_version", "run_date"):
        assert f"{keyword}=" in section, keyword
    assert "evals._harness.deps.parse_deps" in section


def test_skill_says_the_verdict_comes_from_compute_verdict():
    section = _section("6")
    assert re.search(r"`run\[\"verdict\"\]` is the result of `compute_verdict`", section)


def test_skill_maps_each_attempt_field_to_its_source():
    section = _section("6")
    assert re.search(r"`items`.{0,80}`Attempt.item_hits`", section)
    assert re.search(r"`classification`.{0,80}`Attempt.classification`", section)
    assert re.search(r"`parse_error`.{0,80}`Attempt.parse_error`", section)
    assert re.search(r"`unmatched_findings`.{0,100}second", section)
    assert re.search(r"`attempt`.{0,100}1-based", section)
    assert re.search(r"`reserve_used`.{0,160}running (?:count|total)", section)


def test_skill_states_the_raw_directory_layout():
    section = _section("6")
    assert re.search(r"transcripts?.{0,60}`\*\.jsonl`.{0,80}root", section)
    assert re.search(r"beside .{0,30}`end_state/`", section)
    assert re.search(r"`ledger.write_run` globs `\*\.jsonl` at that root to compute `model_ids`", section)


def test_skill_tells_the_inline_conductor_to_hand_lens_agents_the_built_prompt():
    section = _section("3")
    inline = section[section.index('`mode = "inline"`'):]
    assert re.search(r"lens agent.{0,200}build_dispatch_prompt\(case_dir\)", inline)


def test_skill_says_the_conductor_enforces_the_reserve_because_should_retry_does_not():
    section = _section("5")
    assert re.search(r"`should_retry` does not enforce the reserve", section)
    assert re.search(r"conductor (?:itself )?must stop", section)
    assert re.search(r"reserve_used.{0,60}(?:reaches|is) 2", section)


def test_skill_defines_a_fixture_as_a_directory_containing_case_toml():
    section = _section("1")
    assert re.search(
        r"every directory under `evals/<skill>/` that contains a `case.toml`", section, re.IGNORECASE
    )
    assert "directly under" not in section
    assert re.search(r"`runs/`", section)


def test_skill_names_the_manifest_parser():
    section = _section("2")
    assert "evals._harness.activation.parse_checks_manifest(text)" in section
    assert re.search(r"rather than hand-parsing it", section)
