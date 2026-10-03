"""Tests for evals._harness.guards.fingerprint_match.

Every repo here is a synthetic git repo built under ``tmp_path``. A synthetic
case commits its fixture (and builder) BEFORE any fingerprint is computed:
``deps.tree_hash`` reads HEAD blobs, so a fingerprint taken from an
uncommitted fixture would be vacuous.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from evals._harness.calibration import compute_input_hash, fixture_fingerprint
from evals._harness.guards import GuardContext
from evals._harness.guards import calibration_staleness
from evals._harness.guards.fingerprint_match import check

_SKILL = "example-skill"
_HEX = "a" * 64

_BUILDER = """\
import sys
from pathlib import Path

dest = Path(sys.argv[1])
dest.mkdir(parents=True, exist_ok=True)
seed = (Path(__file__).resolve().parent / "seed.txt").read_text(encoding="utf-8")
(dest / "out.txt").write_text(seed, encoding="utf-8")
"""


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def _write(repo: Path, rel_path: str, text: str) -> None:
    path = repo / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _commit(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    return repo


def _write_case(
    repo: Path,
    case: str,
    *,
    skill: str = _SKILL,
    items: tuple[str, ...] = ("item-a",),
    fixture: str | None = "fixture v1\n",
    builder_seed: str | None = None,
    prompt: str = "do it\n",
) -> Path:
    """Write one synthetic case directory (not committed) and return its path."""
    case_dir = repo / "evals" / skill / case
    lines = ['mode = "subagent"', 'prompt = "prompt.md"']
    for item in items:
        lines += ["", "[[items]]", f'id = "{item}"', 'kind = "gate-candidate"', 'scorer = "marker"']
    _write(repo, f"evals/{skill}/{case}/case.toml", "\n".join(lines) + "\n")
    _write(repo, f"evals/{skill}/{case}/prompt.md", prompt)
    _write(repo, f"evals/{skill}/{case}/predicates.py", "def marker(evidence):\n    return True\n")
    if fixture is not None:
        _write(repo, f"evals/{skill}/{case}/fixture/input.txt", fixture)
    if builder_seed is not None:
        _write(repo, f"evals/{skill}/{case}/build_fixture.py", _BUILDER)
        _write(repo, f"evals/{skill}/{case}/seed.txt", builder_seed)
    return case_dir


def _write_manifest(repo: Path, *ids: str, skill: str = _SKILL) -> None:
    _write(repo, f"evals/{skill}/checks.manifest", "".join(f"{i} described\n" for i in ids))


def _run_file(cases: list[dict]) -> str:
    return json.dumps(
        {
            "skill": _SKILL,
            "verdict": "green",
            "fingerprint": {
                "direct_tier_hash": "d",
                "injection_tier_hash": "i",
                "plugin_version": "1.0.0",
                "claude_code_version": "2.0.0",
                "run_date": "2026-01-01",
            },
            "tokens": 0,
            "wall_time_s": 0,
            "cases": cases,
        }
    )


def _recorded(case: str, fingerprint: str) -> dict:
    return {
        "case": case,
        "fixture_fingerprint": fingerprint,
        "gated_items": ["item-a"],
        "model_ids": [],
        "attempts": [],
    }


def _write_run(repo: Path, stamp: str, cases: list[dict], *, skill: str = _SKILL) -> None:
    _write(repo, f"evals/{skill}/runs/{stamp}-aaaaaaaa.json", _run_file(cases))


def _write_calibration(repo: Path, case_dir: Path, item: str = "item-a") -> None:
    record = {
        "n": 6,
        "hits": 6,
        "audited_hits": 6,
        "cross_match_result": "pass",
        "no_skill_arm_result": {"n": 3, "hits": 0, "replacements": 0},
        "gate_or_trend_status": "gate",
        "input_hash": compute_input_hash(case_dir),
        "audit": [],
    }
    _write(repo, f"{case_dir.relative_to(repo)}/calibration.json", json.dumps({item: record}))


def _gated_repo(tmp_path: Path, **case_kwargs) -> tuple[Path, Path]:
    """A repo with one committed gated case ``case-a``; no run file yet."""
    repo = _init_repo(tmp_path)
    _write_manifest(repo, "item-a")
    case_dir = _write_case(repo, "case-a", **case_kwargs)
    _commit(repo, "a gated case")
    return repo, case_dir


def _record_run(repo: Path, case_dir: Path, stamp: str = "20260101T000000Z") -> str:
    """Commit a run file recording *case_dir*'s CURRENT fingerprint; return it."""
    fingerprint = fixture_fingerprint(case_dir)
    _write_run(repo, stamp, [_recorded(case_dir.name, fingerprint)])
    _commit(repo, f"run {stamp}")
    return fingerprint


def _run(repo: Path):
    return check(GuardContext(base="unused", repo_root=repo))


# ---------------------------------------------------------------------------
# the core comparison
# ---------------------------------------------------------------------------


def test_passes_when_the_recorded_fingerprint_matches_the_current_fixture(tmp_path):
    repo, case_dir = _gated_repo(tmp_path)
    _record_run(repo, case_dir)

    assert _run(repo) == []


def test_fails_when_the_fixture_tree_changed_after_the_run(tmp_path):
    repo, case_dir = _gated_repo(tmp_path)
    _record_run(repo, case_dir)
    _write(repo, "evals/example-skill/case-a/fixture/input.txt", "fixture v2\n")
    _commit(repo, "edit the fixture")

    results = _run(repo)

    assert len(results) == 1
    assert results[0].level == "fail"
    assert results[0].guard == "fingerprint_match"
    assert "case-a" in results[0].message
    assert "20260101T000000Z-aaaaaaaa.json" in results[0].message


def test_fails_when_a_new_file_is_added_to_the_fixture_tree(tmp_path):
    repo, case_dir = _gated_repo(tmp_path)
    _record_run(repo, case_dir)
    _write(repo, "evals/example-skill/case-a/fixture/extra.txt", "more\n")
    _commit(repo, "grow the fixture")

    assert len(_run(repo)) == 1


def test_fails_when_the_recorded_fingerprint_is_not_the_fixtures(tmp_path):
    repo, _ = _gated_repo(tmp_path)
    _write_run(repo, "20260101T000000Z", [_recorded("case-a", _HEX)])
    _commit(repo, "a run recording some other fingerprint")

    assert len(_run(repo)) == 1


def test_passes_a_builder_case_when_the_builder_output_matches(tmp_path):
    repo, case_dir = _gated_repo(tmp_path, fixture=None, builder_seed="seed-1\n")
    _record_run(repo, case_dir)

    assert _run(repo) == []


def test_fails_a_builder_case_when_the_builders_output_changed(tmp_path):
    """The comparison is the builder-OUTPUT fingerprint: the builder script is
    untouched here; only the seed it reads changed, and so did its output.
    """
    repo, case_dir = _gated_repo(tmp_path, fixture=None, builder_seed="seed-1\n")
    _record_run(repo, case_dir)
    _write(repo, "evals/example-skill/case-a/seed.txt", "seed-2\n")
    _commit(repo, "change what the builder emits")

    assert len(_run(repo)) == 1


def test_passes_a_builder_case_when_only_the_builder_script_changed_but_its_output_did_not(tmp_path):
    """Fixture drift only: an edit to the builder that leaves its output
    fingerprint unchanged is not drift this guard sees (the input hash is
    calibration_staleness's concern).
    """
    repo, case_dir = _gated_repo(tmp_path, fixture=None, builder_seed="seed-1\n")
    _record_run(repo, case_dir)
    _write(repo, "evals/example-skill/case-a/build_fixture.py", _BUILDER + "# a comment\n")
    _commit(repo, "reword the builder")

    assert _run(repo) == []


# ---------------------------------------------------------------------------
# distinct from calibration_staleness
# ---------------------------------------------------------------------------


def test_a_prompt_only_change_does_not_fail_this_guard_but_does_fail_calibration_staleness(tmp_path):
    repo, case_dir = _gated_repo(tmp_path)
    _record_run(repo, case_dir)
    _write_calibration(repo, case_dir)
    _commit(repo, "calibrate the case at its current inputs")
    ctx = GuardContext(base="unused", repo_root=repo)
    assert check(ctx) == []
    assert calibration_staleness.check(ctx) == []

    _write(repo, "evals/example-skill/case-a/prompt.md", "do something else\n")
    _commit(repo, "reword only the prompt")

    assert check(ctx) == []
    stale = calibration_staleness.check(ctx)
    assert len(stale) == 1
    assert stale[0].level == "fail"


def test_a_predicates_only_change_does_not_fail_this_guard(tmp_path):
    repo, case_dir = _gated_repo(tmp_path)
    _record_run(repo, case_dir)
    _write(repo, "evals/example-skill/case-a/predicates.py", "def marker(evidence):\n    return False\n")
    _commit(repo, "change only predicates.py")

    assert _run(repo) == []


def test_never_reads_the_calibration_records_input_hash(tmp_path):
    repo, case_dir = _gated_repo(tmp_path)
    _record_run(repo, case_dir)
    _write(
        repo,
        "evals/example-skill/case-a/calibration.json",
        json.dumps({"item-a": {"input_hash": "0" * 64}}),
    )
    _commit(repo, "a calibration record whose hash is wrong")

    assert _run(repo) == []


# ---------------------------------------------------------------------------
# which run file is compared
# ---------------------------------------------------------------------------


def test_compares_the_newest_run_that_records_the_case_not_the_newest_run_of_the_skill(tmp_path):
    repo, case_dir = _gated_repo(tmp_path)
    _write_run(repo, "20260101T000000Z", [_recorded("case-a", _HEX)])
    _write_run(repo, "20260201T000000Z", [_recorded("some-other-case", fixture_fingerprint(case_dir))])
    _commit(repo, "an older run with a stale fingerprint, and a newer run of another case")

    results = _run(repo)

    assert len(results) == 1
    assert "20260101T000000Z" in results[0].message


def test_finds_the_case_when_it_is_not_the_first_entry_of_the_newest_run_file(tmp_path):
    repo, _ = _gated_repo(tmp_path)
    _write_run(
        repo,
        "20260101T000000Z",
        [_recorded("some-other-case", _HEX), _recorded("case-a", _HEX)],
    )
    _commit(repo, "a run whose second entry is case-a, with a stale fingerprint")

    results = _run(repo)

    assert len(results) == 1
    assert "case-a" in results[0].message


def test_an_older_stale_run_does_not_fail_when_the_newest_run_matches(tmp_path):
    repo, case_dir = _gated_repo(tmp_path)
    _write_run(repo, "20260101T000000Z", [_recorded("case-a", _HEX)])
    _write_run(repo, "20260201T000000Z", [_recorded("case-a", fixture_fingerprint(case_dir))])
    _commit(repo, "a stale older run and a matching newer one")

    assert _run(repo) == []


def test_a_newer_stale_run_fails_even_when_an_older_run_matches(tmp_path):
    repo, case_dir = _gated_repo(tmp_path)
    _write_run(repo, "20260101T000000Z", [_recorded("case-a", fixture_fingerprint(case_dir))])
    _write_run(repo, "20260201T000000Z", [_recorded("case-a", _HEX)])
    _commit(repo, "a matching older run and a stale newer one")

    results = _run(repo)

    assert len(results) == 1
    assert "20260201T000000Z" in results[0].message


def test_orders_run_files_by_their_filename_timestamp_not_by_commit_order(tmp_path):
    repo, case_dir = _gated_repo(tmp_path)
    # Written (and committed) first, yet the newer by filename timestamp.
    _write_run(repo, "20260301T000000Z", [_recorded("case-a", fixture_fingerprint(case_dir))])
    _commit(repo, "the newest run, committed first")
    _write_run(repo, "20260101T000000Z", [_recorded("case-a", _HEX)])
    _commit(repo, "an older run, committed last")

    assert _run(repo) == []


def test_skips_an_unreadable_run_file_and_falls_back_to_the_next_newest(tmp_path):
    repo, _ = _gated_repo(tmp_path)
    _write_run(repo, "20260101T000000Z", [_recorded("case-a", _HEX)])
    _write(repo, "evals/example-skill/runs/20260301T000000Z-aaaaaaaa.json", "{not json")
    _commit(repo, "a garbled newest run file")

    results = _run(repo)

    assert len(results) == 1
    assert "20260101T000000Z" in results[0].message


def test_only_a_json_file_directly_under_runs_is_a_run_file(tmp_path):
    repo, case_dir = _gated_repo(tmp_path)
    _write_run(repo, "20260101T000000Z", [_recorded("case-a", _HEX)])
    # Sorts after every run file by name, and would "match": but it is a raw.
    _write(
        repo,
        "evals/example-skill/runs/20260101T000000Z-aaaaaaaa/case-a/attempt-1/zzzz.json",
        _run_file([_recorded("case-a", fixture_fingerprint(case_dir))]),
    )
    _commit(repo, "a stale run and a raw that looks like a matching run")

    assert len(_run(repo)) == 1


def test_only_the_skills_own_run_files_are_consulted(tmp_path):
    repo, case_dir = _gated_repo(tmp_path)
    _write_run(repo, "20260101T000000Z", [_recorded("case-a", _HEX)])
    _write_run(
        repo,
        "20260201T000000Z",
        [_recorded("case-a", fixture_fingerprint(case_dir))],
        skill="other-skill",
    )
    _commit(repo, "another skill's newer run of a same-named case")

    assert len(_run(repo)) == 1


# ---------------------------------------------------------------------------
# which cases are checked
# ---------------------------------------------------------------------------


def test_does_not_check_a_case_with_no_item_in_the_manifest(tmp_path):
    repo, _ = _gated_repo(tmp_path)
    ungated = _write_case(repo, "case-b", items=("item-b",), fixture="fixture b v1\n")
    _commit(repo, "a case whose item is a trend item")
    _write_run(repo, "20260101T000000Z", [_recorded("case-b", fixture_fingerprint(ungated))])
    _commit(repo, "a run recording case-b")
    _write(repo, "evals/example-skill/case-b/fixture/input.txt", "fixture b v2\n")
    _commit(repo, "change the ungated case's fixture")

    assert _run(repo) == []


def test_checks_a_case_when_only_one_of_its_items_is_gated(tmp_path):
    repo = _init_repo(tmp_path)
    _write_manifest(repo, "item-b")
    case_dir = _write_case(repo, "case-a", items=("item-a", "item-b"))
    _commit(repo, "a case with a trend item and a gated item")
    _record_run(repo, case_dir)
    _write(repo, "evals/example-skill/case-a/fixture/input.txt", "fixture v2\n")
    _commit(repo, "edit the fixture")

    assert len(_run(repo)) == 1


def test_another_skills_manifest_does_not_make_this_skills_case_gated(tmp_path):
    repo = _init_repo(tmp_path)
    _write_manifest(repo, "item-a", skill="other-skill")
    _write_manifest(repo, "item-z")
    case_dir = _write_case(repo, "case-a")
    _commit(repo, "item-a is gated only in another skill")
    _write_run(repo, "20260101T000000Z", [_recorded("case-a", fixture_fingerprint(case_dir))])
    _commit(repo, "a run")
    _write(repo, "evals/example-skill/case-a/fixture/input.txt", "fixture v2\n")
    _commit(repo, "edit the fixture")

    assert _run(repo) == []


def test_does_not_check_a_gated_case_that_no_run_file_records(tmp_path):
    repo, _ = _gated_repo(tmp_path)
    _write_run(repo, "20260101T000000Z", [_recorded("some-other-case", _HEX)])
    _commit(repo, "a run of a different case")

    assert _run(repo) == []


def test_does_not_check_a_gated_case_in_a_skill_with_no_runs_directory(tmp_path):
    repo, _ = _gated_repo(tmp_path)

    assert _run(repo) == []


def test_does_not_fingerprint_a_gated_case_no_run_records_even_when_it_has_no_fixture(tmp_path):
    repo = _init_repo(tmp_path)
    _write_manifest(repo, "item-a")
    _write_case(repo, "case-a", fixture=None)
    _commit(repo, "a gated case with neither a fixture nor a builder")

    assert _run(repo) == []


def test_checks_every_skill(tmp_path):
    repo, case_dir = _gated_repo(tmp_path)
    _write_manifest(repo, "item-q", skill="other-skill")
    other = _write_case(repo, "case-q", skill="other-skill", items=("item-q",))
    _commit(repo, "a second gated skill")
    _record_run(repo, case_dir)
    _write_run(repo, "20260101T000000Z", [_recorded("case-q", fixture_fingerprint(other))], skill="other-skill")
    _commit(repo, "a run of the second skill")
    _write(repo, "evals/other-skill/case-q/fixture/input.txt", "changed\n")
    _commit(repo, "drift only in the second skill")

    results = _run(repo)

    assert len(results) == 1
    assert "case-q" in results[0].message


def test_fails_closed_when_a_recorded_gated_case_can_no_longer_be_fingerprinted(tmp_path):
    repo, case_dir = _gated_repo(tmp_path)
    _record_run(repo, case_dir)
    _git(repo, "rm", "-q", "-r", "evals/example-skill/case-a/fixture")
    _commit(repo, "remove the fixture without replacing it")

    results = _run(repo)

    assert len(results) == 1
    assert results[0].level == "fail"
    assert "case-a" in results[0].message


def test_fails_closed_on_a_gated_skills_case_whose_case_toml_is_unparseable(tmp_path):
    repo, _ = _gated_repo(tmp_path)
    _write(repo, "evals/example-skill/case-a/case.toml", "mode = \n")
    _commit(repo, "break case.toml")

    results = _run(repo)

    assert len(results) == 1
    assert results[0].level == "fail"
    assert "case-a" in results[0].message


def test_passes_a_repo_with_no_evals_directory(tmp_path):
    repo = _init_repo(tmp_path)
    _write(repo, "README.md", "hello\n")
    _commit(repo, "no evals at all")

    assert _run(repo) == []


def test_passes_a_skill_whose_manifest_is_empty_or_absent(tmp_path):
    repo = _init_repo(tmp_path)
    _write_manifest(repo)
    _write_case(repo, "case-a")
    _write_case(repo, "case-b", skill="no-manifest-skill")
    _commit(repo, "cases in skills that gate nothing")

    assert _run(repo) == []


def test_does_not_read_the_case_toml_of_a_skill_that_gates_nothing(tmp_path):
    """No manifest id means no case can be gated, so a case.toml of such a skill
    is never parsed: a broken one must not fail this guard.
    """
    repo = _init_repo(tmp_path)
    _write(repo, "evals/no-manifest-skill/case-b/case.toml", "mode = \n")
    _commit(repo, "a broken case.toml in a skill with no manifest")

    assert _run(repo) == []
