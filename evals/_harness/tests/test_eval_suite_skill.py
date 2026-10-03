"""Tests that the eval-suite conductor skill documents its full contract.

``.claude/skills/eval-suite/SKILL.md`` is a repo-local Claude Code skill: it
is loaded and followed by hand, never executed by any script, CI job, or afk
child. These tests only check that its documented content covers what #995's
acceptance criteria require it to cover — they never invoke the skill.
"""

from __future__ import annotations

import ast
import copy
import importlib
import inspect
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import jsonschema
import pytest

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


# ---------------------------------------------------------------------------
# the skill's claims about the harness are checked against the harness itself
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CALL_SPAN = re.compile(r"`evals\._harness\.(\w+)\.(\w+)\((.*?)\)(?: -> [^`]*)?`")


def _harness_function(module_name: str, function_name: str):
    module = importlib.import_module(f"evals._harness.{module_name}")
    function = getattr(module, function_name, None)
    assert callable(function), f"evals._harness.{module_name}.{function_name} does not exist"
    return function


def _split_arguments(text: str) -> list[str]:
    arguments, depth, current = [], 0, ""
    for char in text:
        if char in "<([{":
            depth += 1
        elif char in ">)]}":
            depth -= 1
        if char == "," and depth == 0:
            arguments.append(current.strip())
            current = ""
        else:
            current += char
    if current.strip():
        arguments.append(current.strip())
    return arguments


def _cited_calls() -> list[tuple[str, str, list[str]]]:
    return [
        (module, function, _split_arguments(arguments))
        for module, function, arguments in _CALL_SPAN.findall(_normalize(_skill_text()))
    ]


def test_the_skill_cites_at_least_every_entry_point_it_calls():
    cited = {f"{module}.{function}" for module, function, _ in _cited_calls()}
    assert {
        "dispatch.build_dispatch_prompt",
        "dispatch.snapshot_end_state",
        "dispatch.score_attempt",
        "scorer.should_retry",
        "scorer.compute_verdict",
        "calibration.fixture_fingerprint",
        "ledger.write_run",
        "report.write_report",
        "activation.parse_checks_manifest",
        "fingerprint.compute_fingerprint",
        "deps.parse_deps",
    } <= cited


def test_every_required_entry_point_exists_and_is_callable():
    for entry_point in _REQUIRED_ENTRY_POINTS:
        module_name, function_name = entry_point.split(".")
        _harness_function(module_name, function_name)


def test_every_harness_call_the_skill_cites_matches_the_real_signature():
    for module_name, function_name, arguments in _cited_calls():
        function = _harness_function(module_name, function_name)
        parameters = list(inspect.signature(function).parameters)
        for position, argument in enumerate(arguments):
            if argument in ("...", "") or argument.startswith("<"):
                continue
            if "=" in argument:
                name = argument.split("=", 1)[0].strip()
                assert name in parameters, f"{function_name}: no parameter {name!r}"
            else:
                assert position < len(parameters), f"{function_name}: too many arguments cited"
                assert parameters[position] == argument, (
                    f"{function_name}: argument {position} is documented as {argument!r} "
                    f"but the parameter is {parameters[position]!r}"
                )


def test_every_documented_should_retry_example_returns_what_the_skill_says():
    text = _normalize(_skill_text())
    matches = re.findall(r"`should_retry\((\{.*?\}), (\d+), (\d+)\)` is `(True|False)`", text)
    assert len(matches) >= 2, "the skill must show the reserve example and the no-gated-items example"
    should_retry = _harness_function("scorer", "should_retry")
    for item_states, counted, reserve, documented in matches:
        assert should_retry(ast.literal_eval(item_states), int(counted), int(reserve)) is (
            documented == "True"
        ), f"should_retry({item_states}, {counted}, {reserve})"


def test_the_documented_retry_caps_are_the_real_boundaries():
    section = _section("5")
    counted_cap = int(re.search(r"counted_attempts reaches (\d+),", section).group(1))
    execution_cap = int(re.search(r"counted_attempts \+ reserve_used reaches (\d+)", section).group(1))
    should_retry = _harness_function("scorer", "should_retry")
    unmet = {"a": False}

    assert should_retry(unmet, counted_cap - 1, 0) is True
    assert should_retry(unmet, counted_cap, 0) is False
    assert should_retry(unmet, 0, execution_cap - 1) is True
    assert should_retry(unmet, 0, execution_cap) is False


def test_the_documented_item_states_rule_is_any_counted_attempt_hit():
    section = _section("5")
    assert re.search(r"maps each \*gated\* item id to whether any counted attempt has hit it so far", section)
    should_retry = _harness_function("scorer", "should_retry")

    assert should_retry({"a": True, "b": False}, 1, 0) is True
    assert should_retry({"a": True, "b": True}, 1, 0) is False


def test_the_documented_verdict_precedence_is_the_real_one():
    section = _section("5")
    assert re.search(r"red beat(?:s)? void beat(?:s)? green", section)
    compute_verdict = _harness_function("scorer", "compute_verdict")
    red = (True, ["miss", "miss", "miss"])
    void = (True, ["indeterminate"])
    green = (True, ["hit"])

    assert compute_verdict({"r": red, "v": void, "g": green}) == "red"
    assert compute_verdict({"v": void, "g": green}) == "void"
    assert compute_verdict({"g": green}) == "green"
    assert compute_verdict({"t": (False, ["miss", "miss", "miss"]), "g": green}) == "green"


def test_the_skill_says_compute_verdict_is_called_once_per_run_not_per_case():
    section = _section("5")
    assert re.search(r"called once with every case's items merged into one mapping", section)
    assert not re.search(r"averag", section)


def test_the_documented_manifest_format_matches_parse_checks_manifest():
    section = _section("2")
    assert re.search(r"one `<id> <one-line description>` per line, `#` comments and blank lines ignored", section)
    assert re.search(r"takes the file's text and returns the gated ids in file order", section)
    parse = _harness_function("activation", "parse_checks_manifest")
    assert list(inspect.signature(parse).parameters) == ["text"]

    assert parse("# a comment\n\nitem-a first item\n  # indented comment\nitem-b second\n") == [
        "item-a",
        "item-b",
    ]


def test_the_skill_says_an_unmatched_manifest_id_is_a_conductor_error_to_surface():
    section = _section("2")
    assert re.search(r"manifest id that names no item in any case of the skill is a conductor error", section)
    assert re.search(r"surface it and stop", section)


def test_score_attempt_really_ignores_gated_ids_of_sibling_cases_as_the_skill_says(tmp_path):
    assert re.search(r"`score_attempt` ignores ids that belong to a sibling case", _section("2"))
    case_dir = tmp_path / "skill-x" / "case-a"
    case_dir.mkdir(parents=True)
    (case_dir / "prompt.md").write_text("Do it.\n", encoding="utf-8")
    (case_dir / "predicates.py").write_text("def scorer_a(evidence):\n    return True\n", encoding="utf-8")
    (case_dir / "case.toml").write_text(
        'mode = "subagent"\nprompt = "prompt.md"\n\n[[items]]\nid = "a"\nkind = "trend"\nscorer = "scorer_a"\n',
        encoding="utf-8",
    )
    transcript = tmp_path / "t.jsonl"
    transcript.write_text(
        json.dumps({"type": "assistant", "message": {"model": "m", "content": [{"type": "text", "text": "ok"}]}})
        + "\n",
        encoding="utf-8",
    )

    attempt, _ = _harness_function("dispatch", "score_attempt")(case_dir, [transcript], None, {"a", "from-a-sibling"})

    assert attempt.item_hits == {"a": "hit"}


def test_the_skill_says_each_case_is_one_prompt_with_zero_user_turns():
    text = _normalize(_skill_text())
    assert "Every case is a single prompt with zero user turns, regardless of mode." in text
    assert not re.search(r"follow-up user turns", text)


def test_the_skill_names_where_transcripts_and_python_come_from():
    skill = _normalize(_skill_text())
    transcript_doc = _normalize(importlib.import_module("evals._harness.transcript").__doc__)
    assert "`<session>/subagents/agent-<id>.jsonl`" in skill
    assert "<session>/subagents/agent-<id>.jsonl" in transcript_doc
    assert "uv run --with pytest --with jsonschema python" in skill
    makefile = (_REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    assert "uv run --with jsonschema python -m evals._harness.guards" in makefile
    assert (
        "uv run --with pytest --with jsonschema python -m pytest" in makefile
    ), "the skill claims to mirror `make test-evals`, which runs pytest"
    assert re.search(r"from the checkout root", skill)


def test_every_harness_invocation_in_the_skill_has_pytest_available():
    # A case's end_state snapshot shells out to `sys.executable -m pytest`, so
    # a harness interpreter without pytest silently records a miss per attempt.
    invocations = re.findall(r"uv run [^`\n]*?python", _skill_text())
    assert invocations, "the skill documents no `uv run ... python` invocation"
    for invocation in invocations:
        assert "--with pytest" in invocation, invocation


def test_the_skill_names_where_run_dict_scalars_and_versions_come_from():
    section = _section("6")
    schema = json.loads(_RUN_SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["properties"]["tokens"]["type"] == "integer"
    assert schema["properties"]["wall_time_s"]["type"] == "number"
    assert re.search(r"`tokens` \(an integer: the total tokens", section)
    assert re.search(r"`wall_time_s` \(a number: the run's wall-clock seconds[,)]", section)
    assert re.search(r"`plugin_version` is the `version` in `plugins/<plugin>/\.claude-plugin/plugin\.json`", section)
    assert re.search(r"`claude_code_version` is the output of `claude --version`", section)
    assert re.search(r"all five fingerprint keys are required", section)
    plugin_json = json.loads((_REPO_ROOT / "plugins/workbench/.claude-plugin/plugin.json").read_text(encoding="utf-8"))
    assert "version" in plugin_json


def test_the_skill_states_the_builder_key_beats_a_local_build_fixture_script():
    section = _section("1")
    assert re.search(r"`builder` key wins over a case-local `build_fixture.py`", section)


def test_the_skill_says_reserve_used_is_recorded_after_the_replacement_draw():
    section = _section("5")
    assert re.search(
        r"`reserve_used` counts how many of the fixture's indeterminate reserve of 2 have been drawn", section
    )
    assert re.search(r"Record an attempt's `reserve_used` after that step", section)
    assert re.search(r"an indeterminate attempt's own record carries the count including the draw that replaces it", section)


def test_the_skill_says_gated_items_is_the_cases_own_gated_ids_recorded_verbatim():
    section = _section("2")
    assert re.search(r"recorded verbatim as the case's `gated_items` field in the run file", section)
    assert re.search(r"list of that case's gated item ids from step 2, recorded verbatim", _section("6"))
    assert "entire manifest" not in _section("6")


def test_the_skill_says_the_snapshot_dest_must_be_fresh():
    section = _section("4")
    assert re.search(r"`dest` must be a fresh, empty `end_state/` directory", section)
    assert re.search(r"a populated one is refused", section)


def test_snapshot_end_state_really_refuses_a_populated_dest_as_the_skill_says(tmp_path):
    case_dir = tmp_path / "skill-x" / "case-a"
    case_dir.mkdir(parents=True)
    (case_dir / "case.toml").write_text('mode = "subagent"\nprompt = "prompt.md"\n', encoding="utf-8")
    (case_dir / "predicates.py").write_text("def end_state(w, c, t):\n    return {'a.txt': 'x'}\n", encoding="utf-8")
    dest = tmp_path / "end_state"
    dest.mkdir()
    (dest / "stale.txt").write_text("old", encoding="utf-8")

    with pytest.raises(ValueError):
        _harness_function("dispatch", "snapshot_end_state")(case_dir, tmp_path, [], dest)


# ---------------------------------------------------------------------------
# the documented run dict, built exactly as shown and run through the real writers
# ---------------------------------------------------------------------------

_FIXED_NOW = datetime(2026, 9, 30, 12, 0, 0, tzinfo=timezone.utc)


def _documented_run() -> dict:
    section_text = re.split(r"^## +", _skill_text(), flags=re.MULTILINE)
    section = next(part for part in section_text if part.startswith("6."))
    blocks = re.findall(r"```json\n(.*?)```", section, flags=re.DOTALL)
    assert len(blocks) == 1, "section 6 must hold exactly one fenced json run example"
    return json.loads(blocks[0])


def _raw_sources_for(run: dict, base: Path) -> dict[str, Path]:
    sources: dict[str, Path] = {}
    for case in run["cases"]:
        for attempt in case["attempts"]:
            source = base / attempt["raw"].strip("/").replace("/", "_")
            (source / "end_state").mkdir(parents=True, exist_ok=True)
            (source / "end_state" / "note.txt").write_text("snapshot", encoding="utf-8")
            (source / "agent-0001.jsonl").write_text(
                json.dumps({"type": "assistant", "message": {"model": "claude-test", "content": [{"type": "text", "text": "done"}]}})
                + "\n",
                encoding="utf-8",
            )
            sources[attempt["raw"]] = source
    return sources


def test_the_documented_run_example_has_exactly_the_keys_the_schema_requires():
    schema = json.loads(_RUN_SCHEMA_PATH.read_text(encoding="utf-8"))
    run = _documented_run()
    case_schema = schema["properties"]["cases"]["items"]
    attempt_schema = case_schema["properties"]["attempts"]["items"]

    assert set(run) == set(schema["required"])
    assert set(run["fingerprint"]) == set(schema["properties"]["fingerprint"]["required"])
    for case in run["cases"]:
        assert set(case) == set(case_schema["required"]) - {"model_ids"}
        for attempt in case["attempts"]:
            assert set(attempt) == set(attempt_schema["required"])


def test_the_documented_run_example_is_written_by_the_real_write_run_and_validates(tmp_path):
    run = _documented_run()
    runs_dir = tmp_path / "evals" / "example-skill" / "runs"
    ledger_write_run = _harness_function("ledger", "write_run")

    run_file = ledger_write_run(runs_dir, copy.deepcopy(run), _raw_sources_for(run, tmp_path / "raw"), now=_FIXED_NOW)

    written = json.loads(run_file.read_text(encoding="utf-8"))
    jsonschema.validate(written, json.loads(_RUN_SCHEMA_PATH.read_text(encoding="utf-8")))
    assert written["cases"][0]["model_ids"] == ["claude-test"]
    assert all(attempt["raw"].startswith(f"{run_file.stem}/") for attempt in written["cases"][0]["attempts"])
    assert run_file.parent == runs_dir


def test_write_run_refuses_to_overwrite_an_existing_run_file_as_the_skill_says(tmp_path):
    assert re.search(r"refuses to overwrite an existing run file", _section("6"))
    run = _documented_run()
    runs_dir = tmp_path / "runs"
    ledger_write_run = _harness_function("ledger", "write_run")
    ledger_write_run(runs_dir, copy.deepcopy(run), _raw_sources_for(run, tmp_path / "raw"), now=_FIXED_NOW)

    with pytest.raises(FileExistsError):
        ledger_write_run(runs_dir, copy.deepcopy(run), _raw_sources_for(run, tmp_path / "raw2"), now=_FIXED_NOW)


def test_a_transcript_in_a_subdirectory_of_the_raw_directory_is_never_seen_as_the_skill_says(tmp_path):
    assert re.search(r"a transcript placed in a subdirectory is never seen", _section("6"))
    run = _documented_run()
    sources = _raw_sources_for(run, tmp_path / "raw")
    for source in sources.values():
        (source / "transcripts").mkdir()
        (source / "agent-0001.jsonl").rename(source / "transcripts" / "agent-0001.jsonl")

    run_file = _harness_function("ledger", "write_run")(tmp_path / "runs", copy.deepcopy(run), sources, now=_FIXED_NOW)

    assert json.loads(run_file.read_text(encoding="utf-8"))["cases"][0]["model_ids"] == []


def test_the_documented_fingerprint_keys_are_what_compute_fingerprint_returns():
    fingerprint = _harness_function("fingerprint", "compute_fingerprint")(
        direct_paths=[],
        injection_paths=[],
        plugin_version="1.0.0",
        claude_code_version="2.0.0",
        run_date="2026-09-30",
    )

    assert set(fingerprint) == set(_documented_run()["fingerprint"])


def test_write_report_on_a_documented_red_run_writes_a_report(tmp_path):
    run = _documented_run()
    run["verdict"] = "red"
    run_file = _harness_function("ledger", "write_run")(
        tmp_path / "runs", run, _raw_sources_for(run, tmp_path / "raw"), now=_FIXED_NOW
    )

    report_path = _harness_function("report", "write_report")(run_file)

    assert report_path is not None and report_path.is_file()


def test_the_skill_says_dispatch_error_is_the_only_status_override_and_score_attempt_enforces_it(tmp_path):
    assert re.search(r"it accepts no other value", _section("4"))
    case_dir = tmp_path / "skill-x" / "case-a"
    case_dir.mkdir(parents=True)
    (case_dir / "case.toml").write_text('mode = "subagent"\nprompt = "prompt.md"\n', encoding="utf-8")
    (case_dir / "prompt.md").write_text("Do it.\n", encoding="utf-8")

    score_attempt = _harness_function("dispatch", "score_attempt")
    attempt, _ = score_attempt(case_dir, [], None, set(), transcript_status="dispatch_error")
    assert attempt.classification == "indeterminate"
    with pytest.raises(ValueError):
        score_attempt(case_dir, [], None, set(), transcript_status="complete")


# ---------------------------------------------------------------------------
# round-4 statements, each pinned by executing the real call
# ---------------------------------------------------------------------------


def test_the_skill_says_to_skip_the_snapshot_for_a_dispatch_error_attempt(tmp_path):
    section = _section("4")
    assert re.search(r"Skip this step for an attempt that ended in `dispatch_error`", section)
    assert re.search(r"no transcripts and may have no workdir", section)
    assert re.search(r"`score_attempt` runs no scorers for it", section)

    case_dir = tmp_path / "skill-x" / "case-a"
    case_dir.mkdir(parents=True)
    (case_dir / "prompt.md").write_text("Do it.\n", encoding="utf-8")
    (case_dir / "case.toml").write_text(
        'mode = "subagent"\nprompt = "prompt.md"\n\n[[items]]\nid = "a"\nkind = "trend"\nscorer = "scorer_a"\n',
        encoding="utf-8",
    )
    (case_dir / "predicates.py").write_text(
        "def scorer_a(evidence):\n    raise AssertionError('scorer ran')\n\n"
        "def end_state(workdir, case_dir, transcripts):\n"
        "    return {'x.txt': (workdir / 'result.txt').read_text(encoding='utf-8')}\n",
        encoding="utf-8",
    )
    # With no workdir to read, snapshotting fails: that is why the step is skipped.
    with pytest.raises(ValueError):
        _harness_function("dispatch", "snapshot_end_state")(case_dir, tmp_path / "no-workdir", [], tmp_path / "end_state")
    # And scoring the dispatch_error attempt needs neither a workdir nor a snapshot nor any scorer.
    attempt, _ = _harness_function("dispatch", "score_attempt")(
        case_dir, [], None, set(), transcript_status="dispatch_error"
    )
    assert attempt.classification == "indeterminate"


def test_the_skill_says_a_resnapshot_needs_a_fresh_end_state_directory(tmp_path):
    section = _section("4")
    assert re.search(r"use a new `end_state/` directory for every attempt", section, re.IGNORECASE)
    assert re.search(r"Re-snapshotting an attempt .{0,60}needs a new path, or the old `end_state/` deleted first", section, re.IGNORECASE)

    case_dir = tmp_path / "skill-x" / "case-a"
    case_dir.mkdir(parents=True)
    (case_dir / "case.toml").write_text('mode = "subagent"\nprompt = "prompt.md"\n', encoding="utf-8")
    (case_dir / "predicates.py").write_text("def end_state(w, c, t):\n    return {'a.txt': 'x'}\n", encoding="utf-8")
    snapshot_end_state = _harness_function("dispatch", "snapshot_end_state")
    dest = tmp_path / "end_state"

    snapshot_end_state(case_dir, tmp_path, [], dest)
    with pytest.raises(ValueError):
        snapshot_end_state(case_dir, tmp_path, [], dest)
    import shutil

    shutil.rmtree(dest)
    snapshot_end_state(case_dir, tmp_path, [], dest)
    snapshot_end_state(case_dir, tmp_path, [], tmp_path / "another" / "end_state")


def test_the_skill_says_a_case_with_no_gated_items_is_never_retried():
    section = _section("5")
    assert re.search(r"A case with no gated items makes `should_retry` return `False` at once", section)
    assert re.search(r"an indeterminate first attempt .{0,40}is not replaced", section)
    assert _harness_function("scorer", "should_retry")({}, 0, 0) is False


def test_the_skill_says_how_to_run_a_conductor_script_and_that_it_is_true(tmp_path):
    text = _normalize(_skill_text())
    assert re.search(r"`python -c` or `python -m`, or with `PYTHONPATH=\.`, from the checkout root", text)
    assert "No module named 'evals'" in text

    import os
    import subprocess
    import sys

    environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    script = tmp_path / "conductor.py"
    script.write_text("import evals._harness.dispatch\nprint('imported')\n", encoding="utf-8")

    inline = subprocess.run(
        [sys.executable, "-c", "import evals._harness.dispatch; print('imported')"],
        cwd=_REPO_ROOT, env=environment, capture_output=True, text=True,
    )
    outside = subprocess.run(
        [sys.executable, str(script)], cwd=tmp_path, env=environment, capture_output=True, text=True
    )
    with_path = subprocess.run(
        [sys.executable, str(script)], cwd=_REPO_ROOT,
        env={**environment, "PYTHONPATH": str(_REPO_ROOT)}, capture_output=True, text=True,
    )

    assert inline.returncode == 0 and "imported" in inline.stdout
    assert outside.returncode != 0 and "No module named 'evals'" in outside.stderr
    assert with_path.returncode == 0 and "imported" in with_path.stdout
