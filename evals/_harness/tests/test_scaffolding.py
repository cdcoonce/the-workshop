"""Tests for the deps/checks.manifest/retired.md/gaps.md scaffolding this issue creates.

Covers the four per-skill files for every rostered skill: ``deps``,
``checks.manifest``, ``retired.md``, ``gaps.md``. All four must exist, in
the format the issue pins, and every rostered skill must be inactive at
scaffolding time (no gated IDs, no retired entries yet).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from evals._harness.activation import ROSTERED_SKILLS, is_active, parse_checks_manifest, parse_retired_entries
from evals._harness.deps import parse_deps

# evals/_harness/tests/test_scaffolding.py -> tests -> _harness -> evals -> repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]

_GAPS_HEADER_LINES = [
    "# Gaps",
    "",
    "Guarded behaviors that cannot be exercised as a single-prompt case, one line of reason each.",
]
_GAPS_ENTRY_PATTERN = re.compile(r"^- [^:]+: \S.*$")

_EXPECTED_INJECTION_TIER = [
    "plugins/workbench/hooks/hooks.json",
    "plugins/workbench/hooks/run-hook.sh",
    "plugins/workbench/hooks/run-vault-hook.sh",
    "plugins/workbench/hooks/scripts/inject-skill-router.py",
    "plugins/workbench/hooks/scripts/vault-session-start.py",
    "plugins/workbench/hooks/scripts/snapshot-subagent-start.py",
    "plugins/workbench/hooks/scripts/suggest-handoff-on-context.py",
    "plugins/workbench/hooks/scripts/vault-skill-alias.py",
    "plugins/workbench/skills/using-workflow/SKILL.md",
]

_EXPECTED_DIRECT_TIER = {
    "adversarial-review": ["plugins/workbench/skills/adversarial-review"],
    "tdd": ["plugins/workbench/docs/tdd.md", "plugins/workbench/skills/tdd"],
    "commit": ["plugins/workbench/skills/commit"],
}


def _gaps_problems(text: str) -> list[str]:
    """Return why *text* is not a well-formed gaps.md body; empty if it is."""
    lines = text.splitlines()
    if lines[:3] != _GAPS_HEADER_LINES:
        return ["missing or altered header"]
    problems = []
    for line in lines[3:]:
        if not line.strip():
            continue
        if not _GAPS_ENTRY_PATTERN.match(line):
            problems.append(f"malformed entry: {line!r}")
    return problems


def test_check_gaps_flags_an_entry_missing_a_reason():
    header = "\n".join(_GAPS_HEADER_LINES) + "\n"
    bad = header + "- some behavior without a colon reason\n"
    assert _gaps_problems(bad) != []


def test_check_gaps_flags_a_missing_or_altered_header():
    assert _gaps_problems("# Not Gaps\n\nwrong header entirely\n") != []


def test_check_gaps_accepts_a_wellformed_entry():
    header = "\n".join(_GAPS_HEADER_LINES) + "\n"
    good = header + "- retry backoff timing: cannot be timed within a single prompt\n"
    assert _gaps_problems(good) == []


@pytest.mark.parametrize("skill", ROSTERED_SKILLS)
def test_gaps_md_exists_with_header_and_wellformed_entries(skill):
    path = _REPO_ROOT / "evals" / skill / "gaps.md"
    assert path.exists(), f"{path} is missing"
    assert _gaps_problems(path.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize("skill", ROSTERED_SKILLS)
def test_checks_manifest_exists_and_is_empty_of_gated_ids(skill):
    path = _REPO_ROOT / "evals" / skill / "checks.manifest"
    assert path.exists(), f"{path} is missing"
    assert parse_checks_manifest(path.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize("skill", ROSTERED_SKILLS)
def test_retired_md_exists_and_has_no_entries(skill):
    path = _REPO_ROOT / "evals" / skill / "retired.md"
    assert path.exists(), f"{path} is missing"
    assert parse_retired_entries(path.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize("skill", ROSTERED_SKILLS)
def test_rostered_skill_is_inactive_at_scaffolding_time(skill):
    assert is_active(_REPO_ROOT / "evals" / skill) is False


@pytest.mark.parametrize("skill", ROSTERED_SKILLS)
def test_deps_file_declares_the_shared_injection_tier(skill):
    path = _REPO_ROOT / "evals" / skill / "deps"
    assert path.exists(), f"{path} is missing"
    deps = parse_deps(path.read_text(encoding="utf-8"))
    assert deps["injection"] == _EXPECTED_INJECTION_TIER


@pytest.mark.parametrize("skill", ROSTERED_SKILLS)
def test_deps_file_declares_the_expected_direct_tier(skill):
    path = _REPO_ROOT / "evals" / skill / "deps"
    deps = parse_deps(path.read_text(encoding="utf-8"))
    assert sorted(deps["direct"]) == sorted(_EXPECTED_DIRECT_TIER[skill])
