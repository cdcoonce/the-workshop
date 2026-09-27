"""Tests for the deps/checks.manifest/retired.md/gaps.md scaffolding this issue creates.

Covers the four per-skill files for every rostered skill: ``deps``,
``checks.manifest``, ``retired.md``, ``gaps.md``. All four must exist and be
in the format the issue pins. "Created empty" (checks.manifest, retired.md)
and "created inactive" describe the state at scaffolding time, not an
ongoing invariant this suite may keep pinning: #989 and later calibration
children are expected to admit gated IDs, and a test that demands the
manifest stay forever empty would turn `make test` red at the very first
admission. So these files are checked for FORMAT validity, not emptiness —
every non-comment manifest line must be `<id> <description>` with a
grammar-valid id, and every retired.md block must carry a well-formed date,
reason and evidence. A synthetic fixture with one valid gated ID, or one
well-formed retired entry, must still pass every check here.
"""

from __future__ import annotations

import posixpath
import re
from pathlib import Path

import pytest

from evals._harness.activation import ROSTERED_SKILLS, parse_retired_entries
from evals._harness.deps import expand_paths, parse_deps
from evals._harness.guards.deps_completeness import _markdown_link_targets

# evals/_harness/tests/test_scaffolding.py -> tests -> _harness -> evals -> repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_SKILLS_ROOT = "plugins/workbench/skills"

_GAPS_HEADER_LINES = [
    "# Gaps",
    "",
    "Guarded behaviors that cannot be exercised as a single-prompt case, one line of reason each.",
]
_GAPS_ENTRY_PATTERN = re.compile(r"^- [^:]+: \S.*$")

_MANIFEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

_RETIRED_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RETIRED_REASON_PATTERN = re.compile(r"^(noise|upkeep|removed-by-design|superseded-by:.+)$")

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


# --- gaps.md ---------------------------------------------------------------


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


def test_check_gaps_flags_an_entry_with_an_empty_reason_no_space():
    """I8: '- x:' (no space, no reason) must go red per the pinned regex."""
    header = "\n".join(_GAPS_HEADER_LINES) + "\n"
    bad = header + "- x:\n"
    assert _gaps_problems(bad) != []


def test_check_gaps_flags_an_entry_with_an_empty_reason_trailing_space():
    """I8: '- x: ' (colon, space, nothing) must go red per the pinned regex."""
    header = "\n".join(_GAPS_HEADER_LINES) + "\n"
    bad = header + "- x: \n"
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


# --- checks.manifest ---------------------------------------------------------


def _checks_manifest_problems(text: str) -> list[str]:
    """Return why *text* is not a well-formed checks.manifest body; empty if it is."""
    problems = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split(maxsplit=1)
        if len(parts) < 2:
            problems.append(f"missing description: {line!r}")
            continue
        candidate_id, _description = parts
        if not _MANIFEST_ID_PATTERN.match(candidate_id):
            problems.append(f"id fails the grammar: {line!r}")
    return problems


def test_check_manifest_flags_a_line_missing_a_description():
    assert _checks_manifest_problems("gated.one\n") != []


def test_check_manifest_flags_a_line_whose_id_fails_the_grammar():
    assert _checks_manifest_problems("-bad-start A description\n") != []


def test_check_manifest_accepts_comments_blank_lines_and_a_wellformed_id():
    text = "# a leading comment\n\ngated.one A description\n"
    assert _checks_manifest_problems(text) == []


@pytest.mark.parametrize("skill", ROSTERED_SKILLS)
def test_checks_manifest_exists_and_is_well_formed(skill):
    path = _REPO_ROOT / "evals" / skill / "checks.manifest"
    assert path.exists(), f"{path} is missing"
    assert _checks_manifest_problems(path.read_text(encoding="utf-8")) == []


# --- retired.md ---------------------------------------------------------


def _retired_problems(text: str) -> list[str]:
    """Return why *text* is not a well-formed retired.md body; empty if it is."""
    problems = []
    for entry in parse_retired_entries(text):
        entry_id = entry.get("id", "<unknown>")
        date = entry.get("date")
        if not date or not _RETIRED_DATE_PATTERN.match(date):
            problems.append(f"{entry_id}: bad or missing date {date!r}")
        reason = entry.get("reason")
        if not reason or not _RETIRED_REASON_PATTERN.match(reason):
            problems.append(f"{entry_id}: bad or missing reason {reason!r}")
        if not entry.get("evidence"):
            problems.append(f"{entry_id}: missing evidence")
    return problems


def test_check_retired_flags_a_malformed_date():
    text = "## old.id\n- date: 01-02-2026\n- reason: noise\n- evidence: flaked\n"
    assert _retired_problems(text) != []


def test_check_retired_flags_an_unrecognized_reason():
    text = "## old.id\n- date: 2026-01-02\n- reason: because\n- evidence: flaked\n"
    assert _retired_problems(text) != []


def test_check_retired_flags_missing_evidence():
    text = "## old.id\n- date: 2026-01-02\n- reason: noise\n"
    assert _retired_problems(text) != []


def test_check_retired_accepts_a_wellformed_entry():
    text = "## old.id\n- date: 2026-01-02\n- reason: superseded-by:new.id\n- evidence: replaced\n"
    assert _retired_problems(text) == []


@pytest.mark.parametrize("skill", ROSTERED_SKILLS)
def test_retired_md_exists_and_is_well_formed(skill):
    path = _REPO_ROOT / "evals" / skill / "retired.md"
    assert path.exists(), f"{path} is missing"
    assert _retired_problems(path.read_text(encoding="utf-8")) == []


# --- deps ---------------------------------------------------------


@pytest.mark.parametrize("skill", ROSTERED_SKILLS)
def test_deps_file_declares_the_shared_injection_tier(skill):
    path = _REPO_ROOT / "evals" / skill / "deps"
    assert path.exists(), f"{path} is missing"
    deps = parse_deps(path.read_text(encoding="utf-8"))
    assert deps["injection"] == _EXPECTED_INJECTION_TIER


def _direct_tier_problems(skill: str, direct: list[str]) -> list[str]:
    """Return why *direct* doesn't cover the skill dir and its SKILL.md's outside links.

    Not a word-for-word pin of the direct list (that broke the moment a
    SKILL.md gained a new outside link and fought deps_completeness, which
    already owns full link coverage) — just the two structural facts the
    issue's own definition promises: the skill's own directory is always a
    member, and every link SKILL.md makes to a tracked file outside that
    directory is too.
    """
    problems: list[str] = []
    skill_dir_rel = f"{_SKILLS_ROOT}/{skill}"
    if skill_dir_rel not in direct:
        problems.append(f"{skill}: direct tier missing the skill directory {skill_dir_rel!r}")

    skill_md_path = _REPO_ROOT / skill_dir_rel / "SKILL.md"
    text = skill_md_path.read_text(encoding="utf-8") if skill_md_path.exists() else ""
    for link in _markdown_link_targets(text):
        resolved = posixpath.normpath(posixpath.join(skill_dir_rel, link))
        if resolved == skill_dir_rel or resolved.startswith(skill_dir_rel + "/"):
            continue  # inside the skill dir; covered by the dir itself
        tracked = expand_paths([resolved], ref="HEAD", repo=_REPO_ROOT)
        if not tracked:
            continue  # not a tracked file; nothing for direct to cover
        if resolved not in direct:
            problems.append(f"{skill}: outside link {link!r} -> {resolved} missing from direct tier")
    return problems


def test_direct_tier_problems_flags_a_missing_skill_dir():
    assert _direct_tier_problems("commit", []) != []


def test_direct_tier_problems_flags_a_missing_outside_link():
    # tdd's SKILL.md links ../../docs/tdd.md outside its own directory; a
    # direct list holding only the skill dir must be flagged as incomplete.
    assert _direct_tier_problems("tdd", [f"{_SKILLS_ROOT}/tdd"]) != []


def test_direct_tier_problems_accepts_the_skill_dir_alone_when_there_is_no_outside_link():
    assert _direct_tier_problems("commit", [f"{_SKILLS_ROOT}/commit"]) == []


@pytest.mark.parametrize("skill", ROSTERED_SKILLS)
def test_deps_file_direct_tier_covers_the_skill_dir_and_outside_links(skill):
    path = _REPO_ROOT / "evals" / skill / "deps"
    deps = parse_deps(path.read_text(encoding="utf-8"))
    assert _direct_tier_problems(skill, deps["direct"]) == []
