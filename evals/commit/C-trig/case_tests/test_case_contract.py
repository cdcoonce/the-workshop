"""Contract tests for the commit/C-trig case: its files, wiring, fixture and prompt."""

from __future__ import annotations

import os
import re
import subprocess
import sys

from evals._harness import calibration
from evals._harness.fingerprint import builder_output_fingerprint
from evals._harness.dispatch import build_dispatch_prompt, find_acceptance_leaks, find_invalid_modes

# Words that belong to the commit discipline itself. A prompt carrying them would hand the
# case-agent the method, and triggering would stop measuring whether the skill fires.
_DISCIPLINE_VOCABULARY = (
    "conventional",
    "atomic",
    "imperative",
    "subject line",
    "scope",
    "feat(",
    "fix(",
    "staged",
    "stage ",
    "separate",
    "one logical",
)
_PINNED = "Fixture|fixture@local|2026-01-02T03:04:05Z"  # git prints UTC as Z
_CASE_KEYS = {"mode", "prompt", "items"}  # no `builder`: the case-local build_fixture.py is the builder
_ITEM_KEYS = {"id", "kind", "scorer", "params"}


def test_case_declares_subagent_mode_and_a_prompt_file(case_toml, case_dir):
    assert case_toml["mode"] == "subagent"
    assert case_toml["prompt"] == "prompt.md"
    assert find_invalid_modes([case_dir]) == []


def test_case_has_exactly_one_item_and_it_is_a_triggering_item(case_toml):
    assert len(case_toml["items"]) == 1
    item = case_toml["items"][0]
    assert item["kind"] == "triggering"
    assert item["id"] == "C-trig"


def test_the_item_names_the_rostered_skill_and_a_scorer_that_exists(case_toml, predicates, rostered_skill):
    item = case_toml["items"][0]
    assert item["params"] == {"skill": rostered_skill}
    assert callable(getattr(predicates, item["scorer"]))


def test_case_carries_no_calibration_key_and_no_calibration_record(case_toml, case_dir):
    assert set(case_toml) <= _CASE_KEYS
    assert set(case_toml["items"][0]) <= _ITEM_KEYS
    assert "envelope" not in case_toml
    assert not (case_dir / "calibration.json").exists()


def test_triggering_kind_selects_the_skill_arm_only_admission_branch(case_toml):
    kind = case_toml["items"][0]["kind"]
    common = {"item_id": "C-trig", "kind": kind, "skill_n": 6, "audited_hits": 5, "audit": [], "input_hash": "0" * 64}
    admitted = calibration.compute_calibration_record(skill_hits=5, no_skill_attempts=None, **common)
    assert admitted["gate_or_trend_status"] == "gate"
    assert admitted["n"] == 6
    assert admitted["no_skill_arm_result"] is None
    short = calibration.compute_calibration_record(
        skill_hits=4, no_skill_attempts=None, **{**common, "audited_hits": 4}
    )
    assert short["gate_or_trend_status"] == "trend"


def test_case_ships_prompt_acceptance_predicates_and_a_builder_but_no_fixture_tree(case_dir):
    for name in ("prompt.md", "acceptance.md", "predicates.py", "build_fixture.py"):
        assert (case_dir / name).is_file(), name
    assert not (case_dir / "fixture").exists()


def test_case_has_no_builder_key_and_no_provenance(case_toml, case_dir):
    assert "builder" not in case_toml
    assert not (case_dir / "provenance.toml").exists()


def _build(case_dir, dest, env=None):
    result = subprocess.run(
        [sys.executable, "build_fixture.py", str(dest)],
        cwd=case_dir,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return dest


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


def test_builder_makes_a_repo_with_exactly_one_commit_and_no_remote(case_dir, tmp_path):
    repo = _build(case_dir, tmp_path / "built")
    assert _git(repo, "rev-list", "--all", "--count").strip() == "1"
    assert _git(repo, "remote").strip() == ""
    assert _git(repo, "branch", "--show-current").strip() == "main"


def test_the_one_commit_pins_author_and_committer_name_email_and_date(case_dir, tmp_path):
    repo = _build(case_dir, tmp_path / "built")
    author = _git(repo, "log", "-1", "--format=%an|%ae|%aI").strip()
    committer = _git(repo, "log", "-1", "--format=%cn|%ce|%cI").strip()
    assert author == _PINNED
    assert committer == _PINNED


def test_the_built_tree_has_uncommitted_modified_and_untracked_changes_and_nothing_staged(case_dir, tmp_path):
    repo = _build(case_dir, tmp_path / "built")
    status = [line for line in _git(repo, "status", "--porcelain").splitlines() if line]
    assert any(line.startswith(" M ") for line in status), status
    assert any(line.startswith("?? ") for line in status), status
    assert not any(line[0] != " " and not line.startswith("??") for line in status), status
    assert _git(repo, "diff", "--cached", "--name-only").strip() == ""


def test_the_uncommitted_changes_span_more_than_one_concern(case_dir, tmp_path):
    repo = _build(case_dir, tmp_path / "built")
    paths = {line[3:] for line in _git(repo, "status", "--porcelain", "-uall").splitlines() if line}
    assert len(paths) >= 3
    assert any(path.endswith(".md") for path in paths)
    assert any(path.startswith("src/") for path in paths)


def test_the_built_tree_suite_passes(case_dir, tmp_path):
    repo = _build(case_dir, tmp_path / "built")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
        cwd=repo,
        capture_output=True,
        text=True,
        env={"PYTHONDONTWRITEBYTECODE": "1", "PATH": ""},
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_two_builds_give_the_same_commit_and_the_same_builder_output_fingerprint(case_dir, tmp_path):
    first = _build(case_dir, tmp_path / "one")
    second = _build(case_dir, tmp_path / "two")
    assert _git(first, "rev-parse", "HEAD") == _git(second, "rev-parse", "HEAD")
    assert builder_output_fingerprint(first) == builder_output_fingerprint(second)
    assert builder_output_fingerprint(first) == calibration.fixture_fingerprint(case_dir)


def test_the_built_repo_carries_a_local_identity_so_an_agent_can_commit_in_it(case_dir, tmp_path):
    repo = _build(case_dir, tmp_path / "built")
    assert _git(repo, "config", "--local", "user.name").strip() == "Fixture"
    assert _git(repo, "config", "--local", "user.email").strip() == "fixture@local"


def test_a_builder_run_under_hostile_git_settings_still_builds_the_same_commit(case_dir, tmp_path):
    clean = _build(case_dir, tmp_path / "clean")
    home = tmp_path / "home"
    hooks = home / "hooks"
    hooks.mkdir(parents=True)
    hook = hooks / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    (home / ".gitconfig").write_text(
        "[user]\n\tname = Someone Else\n\temail = else@example.com\n"
        "[init]\n\tdefaultBranch = trunk\n"
        "[i18n]\n\tcommitEncoding = ISO-8859-1\n"
        "[commit]\n\tgpgsign = true\n[gpg]\n\tprogram = /usr/bin/false\n"
        f"[core]\n\thooksPath = {hooks}\n",
        encoding="utf-8",
    )
    env = {
        **os.environ,
        "HOME": str(home),
        "GIT_DIR": str(tmp_path / "elsewhere.git"),
        "GIT_AUTHOR_NAME": "Other",
        "GIT_AUTHOR_EMAIL": "other@example.com",
        "GIT_AUTHOR_DATE": "2030-05-05T05:05:05+00:00",
        "GIT_COMMITTER_NAME": "Other",
        "GIT_COMMITTER_EMAIL": "other@example.com",
        "GIT_COMMITTER_DATE": "2030-05-05T05:05:05+00:00",
    }
    hostile = _build(case_dir, tmp_path / "hostile", env=env)
    assert not (tmp_path / "elsewhere.git").exists()
    assert _git(clean, "rev-parse", "HEAD") == _git(hostile, "rev-parse", "HEAD")
    assert builder_output_fingerprint(clean) == builder_output_fingerprint(hostile)


def test_builder_refuses_an_existing_destination(case_dir, tmp_path):
    dest = tmp_path / "taken"
    dest.mkdir()
    (dest / "keep.txt").write_text("mine\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "build_fixture.py", str(dest)], cwd=case_dir, capture_output=True, text=True
    )
    assert result.returncode != 0
    assert (dest / "keep.txt").read_text(encoding="utf-8") == "mine\n"
    assert not (dest / ".git").exists()


def test_fixture_fingerprint_is_a_sha256_hex_digest(case_dir):
    assert re.fullmatch(r"[0-9a-f]{64}", calibration.fixture_fingerprint(case_dir))


def test_prompt_is_a_natural_request_to_save_the_working_tree_changes_with_no_user_turns(case_dir):
    prompt = build_dispatch_prompt(case_dir)
    assert re.search(r"working tree", prompt, re.IGNORECASE)
    assert re.search(r"\bpush", prompt, re.IGNORECASE)
    assert not re.search(r"^\s*(?:human|user|assistant)\s*:", prompt, re.IGNORECASE | re.MULTILINE)
    assert "\n---" not in prompt


def test_prompt_does_not_smuggle_the_discipline(case_dir):
    prompt = build_dispatch_prompt(case_dir).lower()
    for needle in _DISCIPLINE_VOCABULARY:
        assert needle not in prompt, needle


def test_prompt_leaks_nothing_from_acceptance(case_dir):
    prompt = (case_dir / "prompt.md").read_text(encoding="utf-8")
    assert find_acceptance_leaks(case_dir, prompt) == []
    assert build_dispatch_prompt(case_dir) == prompt


def test_acceptance_records_real_criteria(case_dir):
    acceptance = (case_dir / "acceptance.md").read_text(encoding="utf-8")
    assert "C-trig" in acceptance
    assert "Skill" in acceptance
