"""Tests for evals._harness.guards.rescore.

Every repo here is a synthetic git repo built under ``tmp_path``. The synthetic
``evals/_harness/*.py`` files are stand-ins that only fire the guard's trigger:
re-scoring itself runs the REAL harness (``dispatch.score_attempt`` and
``scorer.compute_verdict``) over synthetic cases, raws and run files, so a
stand-in's content can never change what is scored. No model is ever invoked.

A case's recorded outcomes and its raws are chosen to disagree, which is what
makes a re-score flip: e.g. a run file recording a ``hit`` for an attempt whose
raw transcript does not hold the scorer's marker word re-scores to ``miss``.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from evals._harness.guards import GuardContext
from evals._harness.guards.rescore import check

_SKILL = "example-skill"
_CASE = "case-a"
_STAMP = "20260101T000000Z-aaaaaaaa"
_RUN_REL = f"evals/{_SKILL}/runs/{_STAMP}.json"

_PREDICATES = """\
def no_workdir(evidence):
    return evidence.workdir is None


def marker(evidence, word):
    return any(word in t.final_text for t in evidence.transcripts)


def state_ready(evidence):
    return "READY" in evidence.end_state.get("state.txt", "")
"""

_RAW_TEXT = {"hit": "found HIT here", "miss": "nothing relevant"}


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def _write(repo: Path, rel_path: str, text: str) -> None:
    path = repo / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _new_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    for name in ("scorer", "matchers", "transcript", "dispatch", "ledger"):
        _write(repo, f"evals/_harness/{name}.py", f"# stand-in {name}\n")
    return repo


def _add_case(
    repo: Path,
    *,
    skill: str = _SKILL,
    case: str = _CASE,
    items: tuple[str, ...] = ("item-a",),
    predicates: str = _PREDICATES,
) -> None:
    lines = ['mode = "subagent"', 'prompt = "prompt.md"']
    for item in items:
        scorer = {"item-s": "state_ready", "item-w": "no_workdir"}.get(item, "marker")
        lines += ["", "[[items]]", f'id = "{item}"', 'kind = "gate-candidate"', f'scorer = "{scorer}"']
        if scorer == "marker":
            lines.append('params = { word = "HIT" }')
    _write(repo, f"evals/{skill}/{case}/case.toml", "\n".join(lines) + "\n")
    _write(repo, f"evals/{skill}/{case}/prompt.md", "do it\n")
    _write(repo, f"evals/{skill}/{case}/predicates.py", predicates)
    _write(repo, f"evals/{skill}/{case}/fixture/input.txt", "fixture\n")
    _write(repo, f"evals/{skill}/checks.manifest", "".join(f"{item} described\n" for item in items))


def _transcript_line(text: str) -> str:
    return json.dumps(
        {"type": "assistant", "message": {"model": "claude-test", "content": [{"type": "text", "text": text}]}}
    )


def _attempt(
    recorded: str | dict[str, str] = "hit",
    raw: str | None = "hit",
    *,
    classification: str = "counted",
    end_state: str | None = None,
) -> dict:
    """One synthetic attempt: what the run file RECORDS, and what its raw holds.

    ``raw`` is ``"hit"``/``"miss"`` (a valid transcript without/with the marker
    word), ``"bad"`` (an unparseable transcript line), or ``None`` (no raw
    directory at all).
    """
    return {
        "recorded": recorded if isinstance(recorded, dict) else {"item-a": recorded},
        "raw": raw,
        "classification": classification,
        "end_state": end_state,
    }


def _add_run(
    repo: Path,
    attempts: list[dict],
    *,
    skill: str = _SKILL,
    case: str = _CASE,
    stamp: str = _STAMP,
    verdict: str = "void",
) -> str:
    """Write one run file and its raws; return the run file's repo-relative path."""
    recorded_attempts = []
    for number, attempt in enumerate(attempts, start=1):
        raw_rel = f"{stamp}/{case}/attempt-{number}/"
        raw_dir = f"evals/{skill}/runs/{raw_rel}"
        if attempt["raw"] == "bad":
            _write(repo, f"{raw_dir}transcript.jsonl", "this is not json\n")
        elif attempt["raw"] is not None:
            _write(repo, f"{raw_dir}transcript.jsonl", _transcript_line(_RAW_TEXT[attempt["raw"]]) + "\n")
        if attempt["end_state"] is not None:
            _write(repo, f"{raw_dir}end_state/state.txt", attempt["end_state"])
        recorded_attempts.append(
            {
                "attempt": number,
                "classification": attempt["classification"],
                "items": attempt["recorded"],
                "parse_error": False,
                "unmatched_findings": 0,
                "reserve_used": 0,
                "raw": raw_rel,
            }
        )
    gated = sorted({item for attempt in attempts for item in attempt["recorded"]})
    run = {
        "skill": skill,
        "verdict": verdict,
        "fingerprint": {
            "direct_tier_hash": "d",
            "injection_tier_hash": "i",
            "plugin_version": "1.0.0",
            "claude_code_version": "2.0.0",
            "run_date": "2026-01-01",
        },
        "tokens": 0,
        "wall_time_s": 0,
        "cases": [
            {
                "case": case,
                "fixture_fingerprint": "a" * 64,
                "gated_items": gated,
                "model_ids": ["claude-test"],
                "attempts": recorded_attempts,
            }
        ],
    }
    run_rel = f"evals/{skill}/runs/{stamp}.json"
    _write(repo, run_rel, json.dumps(run, indent=2))
    return run_rel


def _entry(run_rel: str = _RUN_REL, item: str = "item-a", old: str = "green", new: str = "void") -> dict:
    return {"run_file": run_rel, "item": item, "old_verdict": old, "new_verdict": new}


def _declare(repo: Path, entries: object, *, skill: str = _SKILL) -> None:
    _write(repo, f"evals/{skill}/rescore-declarations.json", json.dumps(entries, indent=2))


def _touch(repo: Path, rel_path: str) -> None:
    path = repo / rel_path
    path.write_text(path.read_text(encoding="utf-8") + "# changed\n", encoding="utf-8")


def _scenario(tmp_path: Path, attempts: list[dict], **run_kwargs) -> tuple[Path, str]:
    """A repo with one case and one run file; returns ``(repo, run file path)``, uncommitted."""
    repo = _new_repo(tmp_path)
    _add_case(repo)
    run_rel = _add_run(repo, attempts, **run_kwargs)
    return repo, run_rel


def _flipping_attempts() -> list[dict]:
    """One recorded ``hit`` whose raw re-scores to ``miss``: green -> void."""
    return [_attempt("hit", raw="miss")]


def _run(repo: Path, base: str):
    return check(GuardContext(base=base, repo_root=repo))


def _commit_base_then_touch(repo: Path, rel_path: str = "evals/_harness/scorer.py") -> str:
    base = _commit(repo, "base")
    _touch(repo, rel_path)
    _commit(repo, f"change {rel_path}")
    return base


# ---------------------------------------------------------------------------
# the trigger, and the core flip -> declaration rule
# ---------------------------------------------------------------------------


def test_fails_when_a_predicates_change_flips_a_recorded_verdict_with_no_declaration(tmp_path):
    repo, _ = _scenario(tmp_path, [_attempt("hit", raw="hit")])
    base = _commit(repo, "a recorded hit whose raw holds the marker")
    _write(
        repo,
        f"evals/{_SKILL}/{_CASE}/predicates.py",
        _PREDICATES.replace("any(word in", "any(word + 'NEVER' in"),
    )
    _commit(repo, "tighten the scorer: the raw no longer scores a hit")

    results = _run(repo, base)

    assert len(results) == 1
    assert results[0].level == "fail"
    assert results[0].guard == "rescore"
    assert _RUN_REL in results[0].message
    assert "item-a" in results[0].message
    assert "green" in results[0].message and "void" in results[0].message


@pytest.mark.parametrize("name", ["scorer", "matchers", "transcript", "dispatch"])
def test_fails_when_only_a_scoring_harness_file_changes_and_a_recorded_outcome_re_scores_differently(
    tmp_path, name
):
    repo, _ = _scenario(tmp_path, _flipping_attempts())
    base = _commit_base_then_touch(repo, f"evals/_harness/{name}.py")

    results = _run(repo, base)

    assert len(results) == 1
    assert results[0].level == "fail"


def test_passes_when_the_flip_has_a_matching_declaration_at_head(tmp_path):
    repo, run_rel = _scenario(tmp_path, _flipping_attempts())
    base = _commit(repo, "base")
    _touch(repo, "evals/_harness/scorer.py")
    _declare(repo, [_entry(run_rel)])
    _commit(repo, "change the scorer and declare the flip")

    assert _run(repo, base) == []


def test_passes_a_later_scoring_change_when_the_identical_flip_was_declared_at_the_base(tmp_path):
    repo, run_rel = _scenario(tmp_path, _flipping_attempts())
    _declare(repo, [_entry(run_rel)])
    base = _commit(repo, "a flip declared once, committed")
    _touch(repo, "evals/_harness/scorer.py")
    _commit(repo, "change the scorer again")

    assert _run(repo, base) == []


def test_fails_when_the_only_declaration_on_the_base_is_for_a_different_flip(tmp_path):
    repo, run_rel = _scenario(tmp_path, _flipping_attempts())
    _declare(repo, [_entry(run_rel, new="red")])
    base = _commit(repo, "a different flip is declared")
    _touch(repo, "evals/_harness/scorer.py")
    _commit(repo, "change the scorer")

    assert len(_run(repo, base)) == 1


@pytest.mark.parametrize("missing", ["run_file", "item", "old_verdict", "new_verdict"])
def test_fails_when_the_only_declaration_is_missing_one_of_the_four_fields(tmp_path, missing):
    repo, run_rel = _scenario(tmp_path, _flipping_attempts())
    base = _commit(repo, "base")
    entry = _entry(run_rel)
    del entry[missing]
    _touch(repo, "evals/_harness/scorer.py")
    _declare(repo, [entry])
    _commit(repo, "declare it, missing a field")

    assert len(_run(repo, base)) == 1


def test_fails_when_the_only_declaration_carries_a_fifth_key(tmp_path):
    repo, run_rel = _scenario(tmp_path, _flipping_attempts())
    base = _commit(repo, "base")
    _touch(repo, "evals/_harness/scorer.py")
    _declare(repo, [{**_entry(run_rel), "reason": "intentional"}])
    _commit(repo, "declare it with an extra key")

    assert len(_run(repo, base)) == 1


@pytest.mark.parametrize(
    "different",
    [
        {"run_file": f"evals/{_SKILL}/runs/20260202T000000Z-bbbbbbbb.json"},
        {"item": "item-other"},
        {"old_verdict": "red"},
        {"new_verdict": "red"},
    ],
    ids=["run_file", "item", "old_verdict", "new_verdict"],
)
def test_a_declaration_that_differs_in_any_one_field_is_a_different_flip(tmp_path, different):
    repo, run_rel = _scenario(tmp_path, _flipping_attempts())
    base = _commit(repo, "base")
    _touch(repo, "evals/_harness/scorer.py")
    _declare(repo, [{**_entry(run_rel), **different}])
    _commit(repo, "declare a flip that differs in one field")

    assert len(_run(repo, base)) == 1


@pytest.mark.parametrize("value", [None, 1, ["green"]])
def test_a_declaration_whose_value_is_not_the_exact_verdict_string_matches_nothing(tmp_path, value):
    repo, run_rel = _scenario(tmp_path, _flipping_attempts())
    base = _commit(repo, "base")
    _touch(repo, "evals/_harness/scorer.py")
    _declare(repo, [{**_entry(run_rel), "old_verdict": value}])
    _commit(repo, "declare it with a non-string verdict")

    assert len(_run(repo, base)) == 1


def test_ignores_junk_declarations_and_declarations_for_other_flips(tmp_path):
    repo, run_rel = _scenario(tmp_path, _flipping_attempts())
    base = _commit(repo, "base")
    _touch(repo, "evals/_harness/scorer.py")
    _declare(repo, ["junk", 7, None, _entry(run_rel, item="item-other"), _entry(run_rel)])
    _commit(repo, "a messy but sufficient declarations file")

    assert _run(repo, base) == []


@pytest.mark.parametrize("content", ["{not json", '{"not": "an array"}', '"text"'])
def test_a_malformed_declarations_file_satisfies_nothing(tmp_path, content):
    repo, _ = _scenario(tmp_path, _flipping_attempts())
    base = _commit(repo, "base")
    _touch(repo, "evals/_harness/scorer.py")
    _write(repo, f"evals/{_SKILL}/rescore-declarations.json", content)
    _commit(repo, "a malformed declarations file")

    assert len(_run(repo, base)) == 1


def test_requires_one_declaration_per_flip_and_names_the_undeclared_one(tmp_path):
    repo, run_rel = _scenario(tmp_path, _flipping_attempts())
    second_rel = _add_run(repo, _flipping_attempts(), stamp="20260202T000000Z-bbbbbbbb")
    base = _commit(repo, "two runs that will flip")
    _touch(repo, "evals/_harness/scorer.py")
    _declare(repo, [_entry(run_rel)])
    _commit(repo, "declare only the first")

    results = _run(repo, base)

    assert len(results) == 1
    assert second_rel in results[0].message
    assert run_rel not in results[0].message


def test_requires_a_declaration_for_each_flipping_item(tmp_path):
    repo = _new_repo(tmp_path)
    _add_case(repo, items=("item-a", "item-s"))
    run_rel = _add_run(
        repo,
        [_attempt({"item-a": "hit", "item-s": "hit"}, raw="miss", end_state="not ready")],
    )
    base = _commit(repo, "a run with two items, both of which will flip")
    _touch(repo, "evals/_harness/scorer.py")
    _declare(repo, [_entry(run_rel, item="item-a")])
    _commit(repo, "declare only item-a")

    results = _run(repo, base)

    assert len(results) == 1
    assert "item-s" in results[0].message


def test_a_declaration_in_another_skills_file_does_not_satisfy_this_skills_flip(tmp_path):
    repo, run_rel = _scenario(tmp_path, _flipping_attempts())
    base = _commit(repo, "base")
    _touch(repo, "evals/_harness/scorer.py")
    _declare(repo, [_entry(run_rel)], skill="other-skill")
    _commit(repo, "the declaration sits in another skill's file")

    assert len(_run(repo, base)) == 1


def test_re_scores_every_skills_run_files(tmp_path):
    repo, _ = _scenario(tmp_path, [_attempt("hit", raw="hit")])
    _add_case(repo, skill="other-skill")
    other_rel = _add_run(repo, _flipping_attempts(), skill="other-skill")
    base = _commit(repo, "a clean run in one skill, a flipping run in another")
    _touch(repo, "evals/_harness/scorer.py")
    _commit(repo, "change the scorer")

    results = _run(repo, base)

    assert len(results) == 1
    assert other_rel in results[0].message


# ---------------------------------------------------------------------------
# each side of a flip is derived from every recorded attempt
# ---------------------------------------------------------------------------


def test_derives_both_verdicts_from_every_attempt_not_from_the_run_files_verdict(tmp_path):
    """Three recorded misses re-score to miss, hit, miss: old red, new green, with
    the run file's top-level verdict set to void.
    """
    attempts = [_attempt("miss", raw="miss"), _attempt("miss", raw="hit"), _attempt("miss", raw="miss")]
    repo, run_rel = _scenario(tmp_path, attempts, verdict="void")
    base = _commit(repo, "base")
    _touch(repo, "evals/_harness/scorer.py")
    _declare(repo, [_entry(run_rel, old="red", new="green")])
    _commit(repo, "declare red -> green")

    assert _run(repo, base) == []


def test_a_declaration_built_from_the_run_files_top_level_verdict_does_not_match(tmp_path):
    attempts = [_attempt("miss", raw="miss"), _attempt("miss", raw="hit"), _attempt("miss", raw="miss")]
    repo, run_rel = _scenario(tmp_path, attempts, verdict="void")
    base = _commit(repo, "base")
    _touch(repo, "evals/_harness/scorer.py")
    _declare(repo, [_entry(run_rel, old="void", new="green")])
    _commit(repo, "declare void -> green")

    assert len(_run(repo, base)) == 1


def test_an_indeterminate_re_score_is_not_a_miss(tmp_path):
    """Three recorded misses re-score to indeterminate, miss, miss: two misses never
    make red, so the item flips red -> void and needs an entry.
    """
    attempts = [_attempt("miss", raw="bad"), _attempt("miss", raw="miss"), _attempt("miss", raw="miss")]
    repo, _ = _scenario(tmp_path, attempts)
    base = _commit_base_then_touch(repo)

    results = _run(repo, base)

    assert len(results) == 1
    assert "red" in results[0].message and "void" in results[0].message


def test_passes_when_recorded_indeterminate_miss_miss_re_scores_to_indeterminate_hit_miss(tmp_path):
    attempts = [
        _attempt("indeterminate", raw="bad", classification="indeterminate"),
        _attempt("miss", raw="hit"),
        _attempt("miss", raw="miss"),
    ]
    repo, run_rel = _scenario(tmp_path, attempts)
    base = _commit(repo, "base")
    _touch(repo, "evals/_harness/scorer.py")
    _declare(repo, [_entry(run_rel, old="void", new="green")])
    _commit(repo, "declare void -> green")

    assert _run(repo, base) == []


def test_a_one_hit_early_stopped_run_re_scored_to_a_miss_is_void_not_red(tmp_path):
    repo, run_rel = _scenario(tmp_path, [_attempt("hit", raw="miss")])
    base = _commit(repo, "base")
    _touch(repo, "evals/_harness/scorer.py")
    _declare(repo, [_entry(run_rel, old="green", new="red")])
    _commit(repo, "declare green -> red (wrong: the early-stopped run is void)")

    assert len(_run(repo, base)) == 1


def test_re_scores_an_attempt_recorded_indeterminate_whose_raw_is_present(tmp_path):
    repo, run_rel = _scenario(
        tmp_path, [_attempt("indeterminate", raw="hit", classification="indeterminate")]
    )
    base = _commit_base_then_touch(repo)

    results = _run(repo, base)

    assert len(results) == 1
    assert "void" in results[0].message and "green" in results[0].message


def test_re_scores_an_end_state_item_from_the_raws_end_state_snapshot(tmp_path):
    """The scorer reads only ``evidence.end_state`` (``workdir`` is ``None``): the
    recorded hit is reproduced from ``end_state/state.txt``, so no verdict flips.
    """
    repo = _new_repo(tmp_path)
    _add_case(repo, items=("item-s",))
    _add_run(repo, [_attempt({"item-s": "hit"}, raw="miss", end_state="state: READY\n")])
    base = _commit_base_then_touch(repo)

    assert _run(repo, base) == []


def test_an_end_state_item_whose_snapshot_lacks_the_evidence_flips(tmp_path):
    repo = _new_repo(tmp_path)
    _add_case(repo, items=("item-s",))
    _add_run(repo, [_attempt({"item-s": "hit"}, raw="miss", end_state="state: broken\n")])
    base = _commit_base_then_touch(repo)

    assert len(_run(repo, base)) == 1


def test_re_scores_with_no_workdir(tmp_path):
    """Re-scoring from raws alone passes ``workdir=None``: a scorer that is True
    only when it sees no workdir reproduces its recorded hit.
    """
    repo = _new_repo(tmp_path)
    _add_case(repo, items=("item-w",))
    _add_run(repo, [_attempt({"item-w": "hit"}, raw="miss")])
    base = _commit_base_then_touch(repo)

    assert _run(repo, base) == []


def test_checks_every_case_of_a_run_file(tmp_path):
    repo, _ = _scenario(tmp_path, [_attempt("hit", raw="hit")])
    _add_case(repo, case="case-b")
    second_rel = _add_run(repo, _flipping_attempts(), case="case-b", stamp="20260202T000000Z-bbbbbbbb")
    run_path = repo / _RUN_REL
    merged = json.loads(run_path.read_text(encoding="utf-8"))
    merged["cases"] += json.loads((repo / second_rel).read_text(encoding="utf-8"))["cases"]
    run_path.write_text(json.dumps(merged), encoding="utf-8")
    (repo / second_rel).unlink()
    base = _commit_base_then_touch(repo)

    results = _run(repo, base)

    assert len(results) == 1
    assert "case-b" in results[0].message


# ---------------------------------------------------------------------------
# fail closed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("declared", [False, True])
def test_fails_closed_on_a_missing_raw_directory_for_a_counted_attempt(tmp_path, declared):
    repo, run_rel = _scenario(tmp_path, [_attempt("hit", raw=None)])
    base = _commit(repo, "a counted attempt whose raw directory is absent")
    _touch(repo, "evals/_harness/scorer.py")
    if declared:
        _declare(repo, [_entry(run_rel)])
    _commit(repo, "change the scorer")

    results = _run(repo, base)

    assert len(results) >= 1
    assert all(result.level == "fail" for result in results)
    assert any("raw" in result.message for result in results)


@pytest.mark.parametrize("declared", [False, True])
def test_fails_closed_on_a_missing_case_directory(tmp_path, declared):
    repo = _new_repo(tmp_path)
    run_rel = _add_run(repo, [_attempt("hit", raw="miss")], case="case-gone")
    base = _commit(repo, "a run of a case that has no directory")
    _touch(repo, "evals/_harness/scorer.py")
    if declared:
        _declare(repo, [_entry(run_rel)])
    _commit(repo, "change the scorer")

    results = _run(repo, base)

    assert len(results) >= 1
    assert any("case-gone" in result.message for result in results)


@pytest.mark.parametrize("declared", [False, True])
def test_fails_closed_when_score_attempt_raises_a_case_contract_error(tmp_path, declared):
    repo, run_rel = _scenario(tmp_path, [_attempt("hit", raw="hit")])
    base = _commit(repo, "base")
    _write(
        repo,
        f"evals/{_SKILL}/{_CASE}/predicates.py",
        "def marker(evidence, word):\n    raise RuntimeError('boom')\n",
    )
    if declared:
        _declare(repo, [_entry(run_rel), _entry(run_rel, old="green", new="red")])
    _commit(repo, "a scorer that raises")

    results = _run(repo, base)

    assert len(results) >= 1
    assert any("boom" in result.message or "raised" in result.message for result in results)


def test_fails_closed_on_a_missing_case_directory_even_when_no_attempt_has_a_raw(tmp_path):
    """The only attempt is recorded indeterminate with no raw, so nothing is ever
    scored: the missing case directory must still fail by itself.
    """
    repo = _new_repo(tmp_path)
    _add_run(
        repo,
        [_attempt("indeterminate", raw=None, classification="indeterminate")],
        case="case-gone",
    )
    base = _commit_base_then_touch(repo)

    results = _run(repo, base)

    assert len(results) == 1
    assert "case-gone" in results[0].message


def test_a_renamed_predicates_file_counts_as_a_change(tmp_path):
    """A rename must read as delete plus add: with rename detection on, git
    prints only the new name and the old ``predicates.py`` path never appears.
    """
    repo, _ = _scenario(tmp_path, [_attempt("hit", raw="hit")])
    base = _commit(repo, "base")
    _git(repo, "mv", f"evals/{_SKILL}/{_CASE}/predicates.py", f"evals/{_SKILL}/{_CASE}/scorers.py")
    _commit(repo, "rename predicates.py")

    assert len(_run(repo, base)) >= 1


def test_a_deleted_predicates_file_counts_as_a_change_and_fails_closed(tmp_path):
    repo, _ = _scenario(tmp_path, [_attempt("hit", raw="hit")])
    base = _commit(repo, "base")
    _git(repo, "rm", "-q", f"evals/{_SKILL}/{_CASE}/predicates.py")
    _commit(repo, "delete predicates.py")

    assert len(_run(repo, base)) >= 1


def test_fails_closed_on_an_unreadable_run_file(tmp_path):
    repo, _ = _scenario(tmp_path, [_attempt("hit", raw="hit")])
    _write(repo, f"evals/{_SKILL}/runs/20260303T000000Z-cccccccc.json", "{not json")
    base = _commit_base_then_touch(repo)

    results = _run(repo, base)

    assert len(results) == 1
    assert "20260303T000000Z-cccccccc.json" in results[0].message


def test_fails_closed_on_a_run_file_that_lacks_the_recorded_fields(tmp_path):
    repo, _ = _scenario(tmp_path, [_attempt("hit", raw="hit")])
    _write(repo, f"evals/{_SKILL}/runs/20260303T000000Z-cccccccc.json", json.dumps({"cases": [{"case": _CASE}]}))
    base = _commit_base_then_touch(repo)

    assert len(_run(repo, base)) == 1


def test_passes_when_the_only_attempt_is_recorded_indeterminate_and_has_no_raw_directory(tmp_path):
    repo, _ = _scenario(
        tmp_path, [_attempt("indeterminate", raw=None, classification="indeterminate")]
    )
    base = _commit_base_then_touch(repo)

    assert _run(repo, base) == []


def test_a_recorded_indeterminate_attempt_with_no_raw_stays_indeterminate_among_re_scored_attempts(tmp_path):
    """Recorded indeterminate (no raw), then a hit: old green. The first attempt
    stays indeterminate on re-score, so the verdict is unchanged: no flip.
    """
    attempts = [
        _attempt("indeterminate", raw=None, classification="indeterminate"),
        _attempt("hit", raw="hit"),
    ]
    repo, _ = _scenario(tmp_path, attempts)
    base = _commit_base_then_touch(repo)

    assert _run(repo, base) == []


# ---------------------------------------------------------------------------
# no false positives
# ---------------------------------------------------------------------------


def test_passes_when_every_recorded_outcome_re_scores_the_same(tmp_path):
    repo, _ = _scenario(tmp_path, [_attempt("hit", raw="hit")])
    base = _commit_base_then_touch(repo)

    assert _run(repo, base) == []


@pytest.mark.parametrize(
    "rel_path",
    [
        "evals/_harness/ledger.py",
        f"evals/{_SKILL}/{_CASE}/prompt.md",
        f"evals/{_SKILL}/gaps.md",
    ],
)
def test_passes_a_diff_that_changes_no_scoring_code(tmp_path, rel_path):
    """A flipping run file is present, so a false positive would show: only the
    trigger decides whether anything is re-scored.
    """
    repo, _ = _scenario(tmp_path, _flipping_attempts())
    _write(repo, f"evals/{_SKILL}/gaps.md", "gaps\n")
    base = _commit(repo, "base")
    _touch(repo, rel_path)
    _commit(repo, f"change only {rel_path}")

    assert _run(repo, base) == []


@pytest.mark.parametrize(
    "rel_path",
    [
        f"evals/{_SKILL}/{_CASE}/fixture/predicates.py",
        f"evals/{_SKILL}/predicates.py",
        f"evals/{_SKILL}/{_CASE}/predicates.py.bak",
        "evals/_harness/tests/scorer.py",
        "evals/_harness/guards/dispatch.py",
        f"evals/{_SKILL}/{_CASE}/scorer.py",
        "evals/_harness/predicates.py",
        "evals/_harness/x/predicates.py",
    ],
)
def test_a_look_alike_path_is_not_scoring_code(tmp_path, rel_path):
    repo, _ = _scenario(tmp_path, _flipping_attempts())
    _write(repo, rel_path, "# look-alike\n")
    base = _commit(repo, "base")
    _touch(repo, rel_path)
    _commit(repo, f"change {rel_path}")

    assert _run(repo, base) == []


def test_a_predicates_change_in_any_case_triggers_every_skills_re_score(tmp_path):
    repo, _ = _scenario(tmp_path, _flipping_attempts())
    _add_case(repo, skill="other-skill")
    base = _commit(repo, "base")
    _touch(repo, f"evals/other-skill/{_CASE}/predicates.py")
    _commit(repo, "change one case's predicates")

    assert len(_run(repo, base)) == 1


def test_passes_an_empty_diff(tmp_path):
    repo, _ = _scenario(tmp_path, _flipping_attempts())
    base = _commit(repo, "base")

    assert _run(repo, base) == []


def test_passes_a_scoring_change_when_no_run_file_exists(tmp_path):
    repo = _new_repo(tmp_path)
    _add_case(repo)
    base = _commit_base_then_touch(repo)

    assert _run(repo, base) == []


def test_passes_when_the_scoring_change_deletes_the_whole_evals_tree(tmp_path):
    repo = _new_repo(tmp_path)
    base = _commit(repo, "base")
    _git(repo, "rm", "-q", "-r", "evals")
    _commit(repo, "delete the evals tree")

    assert _run(repo, base) == []


def test_passes_a_repo_with_no_evals_skills_at_all(tmp_path):
    repo = _new_repo(tmp_path)
    base = _commit_base_then_touch(repo)

    assert _run(repo, base) == []


def test_ignores_a_scoring_change_made_only_on_the_base_via_the_three_dot_range(tmp_path):
    repo, _ = _scenario(tmp_path, _flipping_attempts())
    fork = _commit(repo, "the fork point")
    branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    _git(repo, "branch", "base-line", fork)
    _git(repo, "checkout", "-q", "base-line")
    _touch(repo, "evals/_harness/scorer.py")
    base_head = _commit(repo, "base changes the scorer after the fork")
    _git(repo, "checkout", "-q", branch)
    _write(repo, "unrelated.txt", "hello\n")
    _commit(repo, "this branch touches something else")

    assert _run(repo, base_head) == []
