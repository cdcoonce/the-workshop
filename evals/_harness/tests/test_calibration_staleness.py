"""Tests for evals._harness.guards.calibration_staleness.

Every repo here is a synthetic git repo built under ``tmp_path``. A synthetic
case commits its fixture (and builder) BEFORE any hash is computed: the hashes
read HEAD blobs, so one taken from an uncommitted fixture would be vacuous.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from evals._harness.activation import ROSTERED_SKILLS
from evals._harness.calibration import compute_input_hash
from evals._harness.deps import tree_hash
from evals._harness.guards import GuardContext
from evals._harness.guards import direct_tier
from evals._harness.guards.calibration_staleness import check

_SKILL = "example-skill"

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


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


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
    kind: str = "gate-candidate",
    param: str = "one",
    fixture: str | None = "fixture v1\n",
    builder_seed: str | None = None,
    prompt: str = "do it\n",
) -> Path:
    case_dir = repo / "evals" / skill / case
    lines = ['mode = "subagent"', 'prompt = "prompt.md"']
    for item in items:
        lines += [
            "",
            "[[items]]",
            f'id = "{item}"',
            f'kind = "{kind}"',
            'scorer = "marker"',
            f'params = {{ word = "{param}" }}',
        ]
    _write(repo, f"evals/{skill}/{case}/case.toml", "\n".join(lines) + "\n")
    _write(repo, f"evals/{skill}/{case}/prompt.md", prompt)
    _write(repo, f"evals/{skill}/{case}/predicates.py", "def marker(evidence, word):\n    return True\n")
    if fixture is not None:
        _write(repo, f"evals/{skill}/{case}/fixture/input.txt", fixture)
    if builder_seed is not None:
        _write(repo, f"evals/{skill}/{case}/build_fixture.py", _BUILDER)
        _write(repo, f"evals/{skill}/{case}/seed.txt", builder_seed)
    return case_dir


def _write_manifest(repo: Path, *ids: str, skill: str = _SKILL) -> None:
    _write(repo, f"evals/{skill}/checks.manifest", "".join(f"{i} described\n" for i in ids))


def _record(input_hash: str) -> dict:
    return {
        "n": 6,
        "hits": 6,
        "audited_hits": 6,
        "cross_match_result": "pass",
        "no_skill_arm_result": {"n": 3, "hits": 0, "replacements": 0},
        "gate_or_trend_status": "gate",
        "input_hash": input_hash,
        "audit": [],
    }


def _calibrate(repo: Path, case_dir: Path, *items: str) -> None:
    """Write (uncommitted) records for *items* at the case's CURRENT input hash.

    The hash is computed from HEAD blobs, so the case must already be committed.
    """
    input_hash = compute_input_hash(case_dir)
    records = {item: _record(input_hash) for item in (items or ("item-a",))}
    _write(repo, f"{case_dir.relative_to(repo)}/calibration.json", json.dumps(records))


def _calibrated_repo(tmp_path: Path, **case_kwargs) -> tuple[Path, Path]:
    """A repo with one committed gated case ``case-a`` and a fresh calibration."""
    repo = _init_repo(tmp_path)
    _write_manifest(repo, "item-a")
    case_dir = _write_case(repo, "case-a", **case_kwargs)
    _commit(repo, "a gated case")
    _calibrate(repo, case_dir)
    _commit(repo, "calibrate it")
    return repo, case_dir


def _run(repo: Path):
    return check(GuardContext(base="unused", repo_root=repo))


# ---------------------------------------------------------------------------
# a record must exist
# ---------------------------------------------------------------------------


def test_fails_a_gated_case_with_no_calibration_record_at_all(tmp_path):
    repo = _init_repo(tmp_path)
    _write_manifest(repo, "item-a")
    _write_case(repo, "case-a")
    _commit(repo, "a gated case, never calibrated")

    results = _run(repo)

    assert len(results) == 1
    assert results[0].level == "fail"
    assert results[0].guard == "calibration_staleness"
    assert "case-a" in results[0].message
    assert "item-a" in results[0].message


def test_fails_a_gated_item_missing_from_an_existing_calibration_file(tmp_path):
    repo = _init_repo(tmp_path)
    _write_manifest(repo, "item-a", "item-b")
    case_dir = _write_case(repo, "case-a", items=("item-a", "item-b"))
    _commit(repo, "a case with two gated items")
    _calibrate(repo, case_dir, "item-a")
    _commit(repo, "calibrate only the first")

    results = _run(repo)

    assert len(results) == 1
    assert "item-b" in results[0].message


def test_passes_when_every_gated_item_has_a_fresh_record(tmp_path):
    repo = _init_repo(tmp_path)
    _write_manifest(repo, "item-a", "item-b")
    case_dir = _write_case(repo, "case-a", items=("item-a", "item-b"))
    _commit(repo, "a case with two gated items")
    _calibrate(repo, case_dir, "item-a", "item-b")
    _commit(repo, "calibrate both")

    assert _run(repo) == []


def test_does_not_fail_a_case_with_no_item_in_the_manifest_and_no_record(tmp_path):
    repo = _init_repo(tmp_path)
    _write_manifest(repo, "item-z")
    _write_case(repo, "case-a", items=("item-a",))
    _commit(repo, "an uncalibrated trend-only case")

    assert _run(repo) == []


def test_does_not_check_an_ungated_items_record(tmp_path):
    repo = _init_repo(tmp_path)
    _write_manifest(repo, "item-a")
    case_dir = _write_case(repo, "case-a", items=("item-a", "item-t"))
    _commit(repo, "a case with a gated and a trend item")
    _calibrate(repo, case_dir, "item-a")
    records = json.loads((case_dir / "calibration.json").read_text(encoding="utf-8"))
    records["item-t"] = _record("0" * 64)
    _write(repo, "evals/example-skill/case-a/calibration.json", json.dumps(records))
    _commit(repo, "the trend item's record is stale; the gated one is fresh")

    assert _run(repo) == []


def test_does_not_read_the_calibration_file_of_a_case_with_no_gated_item(tmp_path):
    """An ungated case's calibration.json is not this guard's concern (the schema
    guard owns its shape): even a garbled one must not fail here.
    """
    repo = _init_repo(tmp_path)
    _write_manifest(repo, "item-z")
    _write_case(repo, "case-a", items=("item-a",))
    _write(repo, "evals/example-skill/case-a/calibration.json", "{not json")
    _commit(repo, "a trend-only case with a garbled calibration file")

    assert _run(repo) == []


def test_another_skills_manifest_does_not_make_a_case_gated(tmp_path):
    repo = _init_repo(tmp_path)
    _write_manifest(repo, "item-z")
    _write_manifest(repo, "item-a", skill="other-skill")
    _write_case(repo, "case-a")
    _commit(repo, "item-a is gated only in another skill")

    assert _run(repo) == []


def test_checks_every_skill(tmp_path):
    repo, _ = _calibrated_repo(tmp_path)
    _write_manifest(repo, "item-q", skill="other-skill")
    _write_case(repo, "case-q", skill="other-skill", items=("item-q",))
    _commit(repo, "a second, uncalibrated gated skill")

    results = _run(repo)

    assert len(results) == 1
    assert "case-q" in results[0].message


def test_checks_every_gated_case_of_a_skill(tmp_path):
    repo, _ = _calibrated_repo(tmp_path)
    _write_manifest(repo, "item-a", "item-b")
    _write_case(repo, "case-b", items=("item-b",), fixture="b\n")
    _commit(repo, "a second, uncalibrated gated case")

    results = _run(repo)

    assert len(results) == 1
    assert "case-b" in results[0].message


# ---------------------------------------------------------------------------
# the stored hash must match a fresh recomputation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("what", "edit"),
    [
        ("the prompt", lambda repo: _write(repo, "evals/example-skill/case-a/prompt.md", "different\n")),
        (
            "the fixture tree",
            lambda repo: _write(repo, "evals/example-skill/case-a/fixture/input.txt", "fixture v2\n"),
        ),
        (
            "a new fixture file",
            lambda repo: _write(repo, "evals/example-skill/case-a/fixture/extra.txt", "more\n"),
        ),
        (
            "predicates.py",
            lambda repo: _write(
                repo,
                "evals/example-skill/case-a/predicates.py",
                "def marker(evidence, word):\n    return False\n",
            ),
        ),
        (
            "an item's scorer params",
            lambda repo: _write(
                repo,
                "evals/example-skill/case-a/case.toml",
                (repo / "evals/example-skill/case-a/case.toml")
                .read_text(encoding="utf-8")
                .replace('word = "one"', 'word = "two"'),
            ),
        ),
        (
            "an item's kind",
            lambda repo: _write(
                repo,
                "evals/example-skill/case-a/case.toml",
                (repo / "evals/example-skill/case-a/case.toml")
                .read_text(encoding="utf-8")
                .replace("gate-candidate", "triggering"),
            ),
        ),
        (
            "the item ids",
            lambda repo: _write(
                repo,
                "evals/example-skill/case-a/case.toml",
                (repo / "evals/example-skill/case-a/case.toml")
                .read_text(encoding="utf-8")
                + '\n[[items]]\nid = "item-extra"\nkind = "trend"\nscorer = "marker"\n',
            ),
        ),
    ],
)
def test_fails_when_a_calibrated_input_changed(tmp_path, what, edit):
    repo, _ = _calibrated_repo(tmp_path)
    edit(repo)
    _commit(repo, f"change {what}")

    results = _run(repo)

    assert len(results) == 1, what
    assert results[0].level == "fail"
    assert "case-a" in results[0].message


def test_fails_a_builder_case_when_the_builders_output_changed(tmp_path):
    repo, _ = _calibrated_repo(tmp_path, fixture=None, builder_seed="seed-1\n")
    _write(repo, "evals/example-skill/case-a/seed.txt", "seed-2\n")
    _commit(repo, "change what the builder emits")

    assert len(_run(repo)) == 1


def test_fails_a_builder_case_when_only_the_builder_script_changed_with_the_same_output(tmp_path):
    """Hashing only the builder's output fingerprint would miss this: the edit
    leaves the output byte-identical, but the builder script itself is an input.
    """
    repo, _ = _calibrated_repo(tmp_path, fixture=None, builder_seed="seed-1\n")
    _write(repo, "evals/example-skill/case-a/build_fixture.py", _BUILDER + "# a comment\n")
    _commit(repo, "reword the builder, output unchanged")

    assert len(_run(repo)) == 1


def test_passes_a_builder_case_whose_record_matches(tmp_path):
    repo, _ = _calibrated_repo(tmp_path, fixture=None, builder_seed="seed-1\n")

    assert _run(repo) == []


def test_passes_a_fresh_record(tmp_path):
    repo, _ = _calibrated_repo(tmp_path)

    assert _run(repo) == []


def test_does_not_read_a_run_files_fixture_fingerprint(tmp_path):
    """Guard 3's concern, not this guard's: a run file whose recorded fixture
    fingerprint is wrong must not make a fresh calibration stale.
    """
    repo, _ = _calibrated_repo(tmp_path)
    _write(
        repo,
        "evals/example-skill/runs/20260101T000000Z-aaaaaaaa.json",
        json.dumps({"cases": [{"case": "case-a", "fixture_fingerprint": "f" * 64}]}),
    )
    _commit(repo, "a run recording some other fixture fingerprint")

    assert _run(repo) == []


def test_fails_when_the_stored_hash_differs_in_only_one_character(tmp_path):
    repo, case_dir = _calibrated_repo(tmp_path)
    records = json.loads((case_dir / "calibration.json").read_text(encoding="utf-8"))
    stored = records["item-a"]["input_hash"]
    records["item-a"]["input_hash"] = stored[:-1] + ("0" if stored[-1] != "0" else "1")
    _write(repo, "evals/example-skill/case-a/calibration.json", json.dumps(records))
    _commit(repo, "corrupt the stored hash")

    assert len(_run(repo)) == 1


def test_fails_when_one_of_two_gated_items_records_a_stale_hash(tmp_path):
    repo = _init_repo(tmp_path)
    _write_manifest(repo, "item-a", "item-b")
    case_dir = _write_case(repo, "case-a", items=("item-a", "item-b"))
    _commit(repo, "a case with two gated items")
    _calibrate(repo, case_dir, "item-a", "item-b")
    records = json.loads((case_dir / "calibration.json").read_text(encoding="utf-8"))
    records["item-b"]["input_hash"] = "0" * 64
    _write(repo, "evals/example-skill/case-a/calibration.json", json.dumps(records))
    _commit(repo, "the second item's record is stale")

    results = _run(repo)

    assert len(results) == 1
    assert "item-b" in results[0].message


# ---------------------------------------------------------------------------
# fail closed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("content", ["{not json", "[1, 2]", '"text"'])
def test_fails_a_calibration_file_that_is_not_a_map(tmp_path, content):
    repo, _ = _calibrated_repo(tmp_path)
    _write(repo, "evals/example-skill/case-a/calibration.json", content)
    _commit(repo, "break calibration.json")

    results = _run(repo)

    assert len(results) == 1
    assert "case-a" in results[0].message


@pytest.mark.parametrize("record", [5, None, {}, {"input_hash": None}])
def test_fails_a_record_that_stores_no_input_hash(tmp_path, record):
    repo, _ = _calibrated_repo(tmp_path)
    _write(repo, "evals/example-skill/case-a/calibration.json", json.dumps({"item-a": record}))
    _commit(repo, "a record with no usable hash")

    assert len(_run(repo)) == 1


def test_fails_closed_when_the_input_hash_cannot_be_recomputed(tmp_path):
    repo, _ = _calibrated_repo(tmp_path)
    _git(repo, "rm", "-q", "-r", "evals/example-skill/case-a/fixture")
    _commit(repo, "remove the fixture without replacing it")

    results = _run(repo)

    assert len(results) == 1
    assert results[0].level == "fail"
    assert "case-a" in results[0].message


def test_fails_closed_on_an_unparseable_case_toml(tmp_path):
    repo, _ = _calibrated_repo(tmp_path)
    _write(repo, "evals/example-skill/case-a/case.toml", "mode = \n")
    _commit(repo, "break case.toml")

    results = _run(repo)

    assert len(results) == 1
    assert "case-a" in results[0].message


def test_passes_a_repo_with_no_evals_directory(tmp_path):
    repo = _init_repo(tmp_path)
    _write(repo, "README.md", "hello\n")
    _commit(repo, "no evals at all")

    assert _run(repo) == []


def test_passes_a_skill_with_an_empty_or_absent_manifest(tmp_path):
    repo = _init_repo(tmp_path)
    _write_manifest(repo)
    _write_case(repo, "case-a")
    _write_case(repo, "case-b", skill="no-manifest-skill")
    _commit(repo, "cases in skills that gate nothing")

    assert _run(repo) == []


# ---------------------------------------------------------------------------
# composition with direct_tier: this guard blocks even when direct_tier passes
# ---------------------------------------------------------------------------

_ROSTERED = ROSTERED_SKILLS[0]
_TIER_FILE = f"plugins/workbench/skills/{_ROSTERED}/SKILL.md"


def _rostered_repo(tmp_path: Path) -> tuple[Path, str]:
    """A rostered skill with a deps file and a freshly calibrated gated case; return base."""
    repo = _init_repo(tmp_path)
    _write(repo, _TIER_FILE, "skill v1\n")
    _write(repo, f"evals/{_ROSTERED}/deps", f'direct = ["{_TIER_FILE}"]\ninjection = []\n')
    _write_manifest(repo, "item-a", skill=_ROSTERED)
    case_dir = _write_case(repo, "case-a", skill=_ROSTERED)
    _commit(repo, "a rostered skill with a gated case")
    _calibrate(repo, case_dir)
    base = _commit(repo, "calibrate it")
    return repo, base


def _green_run(direct_tier_hash: str) -> str:
    return json.dumps(
        {
            "skill": _ROSTERED,
            "verdict": "green",
            "fingerprint": {
                "direct_tier_hash": direct_tier_hash,
                "injection_tier_hash": "i",
                "plugin_version": "1.0.0",
                "claude_code_version": "2.0.0",
                "run_date": "2026-01-01",
            },
            "tokens": 0,
            "wall_time_s": 0,
            "cases": [],
        }
    )


def test_blocks_a_direct_tier_change_with_a_stale_record_even_though_direct_tier_passes(tmp_path):
    """The composite effect wanted at the ``make test`` level: a direct-tier
    change whose case has a stale calibration record fails overall, because THIS
    guard fails even though ``direct_tier`` (which never reads calibration
    records) is satisfied by a matching green run file. No change to
    ``direct_tier``'s own contract is involved.
    """
    repo, base = _rostered_repo(tmp_path)
    _write(repo, _TIER_FILE, "skill v2\n")
    _write(repo, f"evals/{_ROSTERED}/case-a/prompt.md", "a reworded prompt\n")
    _commit(repo, "change the direct tier, and with it a calibrated input")
    tier_hash = tree_hash([_TIER_FILE], ref="HEAD", repo=repo)
    run_path = f"evals/{_ROSTERED}/runs/20260101T000000Z-aaaaaaaa.json"
    _write(repo, run_path, _green_run(tier_hash))
    _commit(repo, "add a green run for the new tier")
    ctx = GuardContext(base=base, repo_root=repo)

    stale = check(ctx)
    assert len(stale) == 1
    assert stale[0].level == "fail"
    assert direct_tier.check(ctx) == []

    # Positive control: without the green run file, direct_tier itself fails on
    # the very same diff, so the empty result above is its real verdict.
    _git(repo, "rm", "-q", run_path)
    _commit(repo, "remove the green run")

    control = direct_tier.check(ctx)
    assert len(control) == 1
    assert control[0].level == "fail"
    assert len(check(ctx)) == 1


def test_does_not_read_the_case_toml_of_a_skill_that_gates_nothing(tmp_path):
    """No manifest id means no case can be gated, so a case.toml of such a skill
    is never parsed: a broken one must not fail this guard.
    """
    repo = _init_repo(tmp_path)
    _write(repo, "evals/no-manifest-skill/case-b/case.toml", "mode = \n")
    _commit(repo, "a broken case.toml in a skill with no manifest")

    assert _run(repo) == []
