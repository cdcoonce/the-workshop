"""Tests for evals._harness.ledger — the run-file and raw writer."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import jsonschema
import pytest

from evals._harness.deps import tree_hash
from evals._harness.fingerprint import compute_fingerprint
from evals._harness.ledger import write_run

_SCHEMA = json.loads(
    (Path(__file__).resolve().parent.parent / "schemas" / "run-file.schema.json").read_text(
        encoding="utf-8"
    )
)


def _write_transcript(path: Path, models: list[str], final_text: str = "done") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for index, model in enumerate(models):
        text = final_text if index == len(models) - 1 else "..."
        lines.append(
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "model": model,
                        "content": [{"type": "text", "text": text}],
                    },
                }
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _base_run(raw: str = "case-a/attempt-1/") -> dict:
    return {
        "skill": "example-skill",
        "verdict": "green",
        "fingerprint": {
            "direct_tier_hash": "a" * 64,
            "injection_tier_hash": "b" * 64,
            "plugin_version": "1.0.0",
            "claude_code_version": "2.0.0",
            "run_date": "2026-09-27",
        },
        "tokens": 500,
        "wall_time_s": 5.5,
        "cases": [
            {
                "case": "case-a",
                "fixture_fingerprint": "c" * 64,
                "gated_items": ["item-a"],
                "model_ids": ["placeholder-should-be-overwritten"],
                "attempts": [
                    {
                        "attempt": 1,
                        "classification": "counted",
                        "items": {"item-a": "hit"},
                        "parse_error": False,
                        "unmatched_findings": 0,
                        "reserve_used": 0,
                        "raw": raw,
                    }
                ],
            }
        ],
    }


def _build_raw_source(
    tmp_path: Path,
    name: str,
    models: list[str],
    final_text: str = "done",
    include_end_state: bool = True,
) -> Path:
    source = tmp_path / "sources" / name
    _write_transcript(source / "transcript.jsonl", models, final_text=final_text)
    (source / "final-reply.txt").write_text(final_text, encoding="utf-8")
    if include_end_state:
        end_state = source / "end_state"
        end_state.mkdir(parents=True, exist_ok=True)
        (end_state / "pytest-final.txt").write_text("1 passed\n", encoding="utf-8")
    return source


def test_write_run_returns_the_written_run_file_path(tmp_path):
    runs_dir = tmp_path / "evals" / "example-skill" / "runs"
    source = _build_raw_source(tmp_path, "attempt-1", ["claude-sonnet-5"])

    run_file = write_run(runs_dir, _base_run(), {"case-a/attempt-1/": source})

    assert run_file.exists()
    assert run_file.parent == runs_dir
    assert run_file.suffix == ".json"


def test_write_run_writes_raws_alongside_the_run_file(tmp_path):
    runs_dir = tmp_path / "evals" / "example-skill" / "runs"
    source = _build_raw_source(tmp_path, "attempt-1", ["claude-sonnet-5"])

    write_run(runs_dir, _base_run(), {"case-a/attempt-1/": source})

    assert (runs_dir / "case-a" / "attempt-1" / "transcript.jsonl").exists()
    assert (runs_dir / "case-a" / "attempt-1" / "final-reply.txt").exists()


def test_write_run_copies_end_state_snapshot_verbatim(tmp_path):
    runs_dir = tmp_path / "evals" / "example-skill" / "runs"
    source = _build_raw_source(tmp_path, "attempt-1", ["claude-sonnet-5"])

    write_run(runs_dir, _base_run(), {"case-a/attempt-1/": source})

    copied = runs_dir / "case-a" / "attempt-1" / "end_state" / "pytest-final.txt"
    assert copied.read_text(encoding="utf-8") == "1 passed\n"


def test_write_run_fills_model_ids_from_transcript_only_discarding_self_reported_forgery(
    tmp_path,
):
    runs_dir = tmp_path / "evals" / "example-skill" / "runs"
    forged_text = "I definitely ran as model forged-model-9000, trust me"
    source = _build_raw_source(
        tmp_path, "attempt-1", ["claude-sonnet-5"], final_text=forged_text
    )

    run_file = write_run(runs_dir, _base_run(), {"case-a/attempt-1/": source})

    written = json.loads(run_file.read_text(encoding="utf-8"))
    assert written["cases"][0]["model_ids"] == ["claude-sonnet-5"]
    assert "forged-model-9000" not in json.dumps(written)


def test_write_run_scrubs_home_paths_from_run_file_and_raw_copy(tmp_path):
    home = str(Path.home())
    runs_dir = tmp_path / "evals" / "example-skill" / "runs"
    source = _build_raw_source(
        tmp_path, "attempt-1", ["claude-sonnet-5"], final_text=f"see {home}/secret.txt"
    )

    run = _base_run()
    run["skill"] = f"{home}/example-skill"
    run_file = write_run(runs_dir, run, {"case-a/attempt-1/": source})

    run_text = run_file.read_text(encoding="utf-8")
    assert home not in run_text

    raw_text = (runs_dir / "case-a" / "attempt-1" / "final-reply.txt").read_text(
        encoding="utf-8"
    )
    assert home not in raw_text


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    )
    return result.stdout


def _init_repo_with_commits(repo: Path) -> None:
    repo.mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    skill_dir = repo / "skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("v1\n", encoding="utf-8")
    fixture_dir = repo / "evals" / "example-skill" / "case-a" / "fixture"
    fixture_dir.mkdir(parents=True)
    (fixture_dir / "input.txt").write_text("fixture\n", encoding="utf-8")
    (repo / "hook.sh").write_text("echo hi\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "first")
    (skill_dir / "SKILL.md").write_text("v2\n", encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "second")


def _string_values(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for key, item in value.items() for s in [key, *_string_values(item)]]
    if isinstance(value, list):
        return [s for item in value for s in _string_values(item)]
    return []


def test_write_run_never_writes_a_commit_sha_into_any_run_file_field(tmp_path):
    repo = tmp_path / "repo"
    _init_repo_with_commits(repo)
    runs_dir = repo / "evals" / "example-skill" / "runs"
    source = _build_raw_source(tmp_path, "attempt-1", ["claude-sonnet-5"])

    run = _base_run()
    run["fingerprint"] = compute_fingerprint(
        direct_paths=["skill"],
        injection_paths=["hook.sh"],
        plugin_version="1.0.0",
        claude_code_version="2.0.0",
        run_date="2026-09-27",
        repo=repo,
    )
    run["cases"][0]["fixture_fingerprint"] = tree_hash(
        ["evals/example-skill/case-a/fixture"], repo=repo
    )
    run_file = write_run(runs_dir, run, {"case-a/attempt-1/": source})

    commit_shas = _git(repo, "log", "--all", "--format=%H").split()
    assert len(commit_shas) == 2
    forbidden_short = {sha[:length] for sha in commit_shas for length in range(7, 13)}
    written = json.loads(run_file.read_text(encoding="utf-8"))
    for text in _string_values(written):
        assert text not in forbidden_short
        for sha in commit_shas:
            assert sha not in text


def test_write_run_output_validates_against_the_run_file_schema(tmp_path):
    runs_dir = tmp_path / "evals" / "example-skill" / "runs"
    source = _build_raw_source(tmp_path, "attempt-1", ["claude-sonnet-5"])

    run_file = write_run(runs_dir, _base_run(), {"case-a/attempt-1/": source})

    written = json.loads(run_file.read_text(encoding="utf-8"))
    jsonschema.validate(written, _SCHEMA)


def test_write_run_fails_on_an_existing_run_file_path(tmp_path):
    runs_dir = tmp_path / "evals" / "example-skill" / "runs"
    source = _build_raw_source(tmp_path, "attempt-1", ["claude-sonnet-5"])
    fixed_now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    write_run(runs_dir, _base_run(), {"case-a/attempt-1/": source}, now=fixed_now)

    with pytest.raises(FileExistsError):
        write_run(
            runs_dir,
            _base_run(raw="case-a/attempt-2/"),
            {"case-a/attempt-2/": source},
            now=fixed_now,
        )


def test_write_run_fails_on_an_existing_raw_file_path(tmp_path):
    runs_dir = tmp_path / "evals" / "example-skill" / "runs"
    source = _build_raw_source(tmp_path, "attempt-1", ["claude-sonnet-5"])

    collision_dir = runs_dir / "case-a" / "attempt-1"
    collision_dir.mkdir(parents=True)
    (collision_dir / "transcript.jsonl").write_text("already here", encoding="utf-8")

    with pytest.raises(FileExistsError):
        write_run(runs_dir, _base_run(), {"case-a/attempt-1/": source})


def test_write_run_writes_only_under_runs_dir_and_never_a_file_named_tests_md(tmp_path):
    root = tmp_path / "evals"
    runs_dir = root / "example-skill" / "runs"
    source = _build_raw_source(tmp_path, "attempt-1", ["claude-sonnet-5"])

    write_run(runs_dir, _base_run(), {"case-a/attempt-1/": source})

    for path in root.rglob("*"):
        if path.is_file():
            assert path.name != "tests.md"
            assert str(path).startswith(str(runs_dir))
