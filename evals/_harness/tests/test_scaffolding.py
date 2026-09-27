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
import subprocess
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


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _write(repo: Path, rel_path: str, content: str) -> None:
    path = repo / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _build_skill_repo(
    tmp_path: Path, skill: str, skill_md_text: str, *, extra_files: dict[str, str] | None = None
) -> Path:
    """Build a synthetic git repo with one rostered skill's SKILL.md at *skill*'s path.

    Never reads the real repo's SKILL.md content — a legitimate edit to a
    real skill's docs (an added outside link with its matching deps entry,
    or a dropped one) must never turn ``_direct_tier_problems``'s own unit
    tests red; only the parametrized real-repo test below exercises the
    actual committed files.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, f"{_SKILLS_ROOT}/{skill}/SKILL.md", skill_md_text)
    for rel_path, content in (extra_files or {}).items():
        _write(repo, rel_path, content)
    _commit(repo, "initial")
    return repo


def _direct_tier_problems(skill: str, direct: list[str], *, repo_root: Path) -> list[str]:
    """Return why *direct* doesn't cover the skill dir and its SKILL.md's outside links.

    Not a word-for-word pin of the direct list (that broke the moment a
    SKILL.md gained a new outside link and fought deps_completeness, which
    already owns full link coverage) — just the two structural facts the
    issue's own definition promises: the skill's own directory is always a
    member, and every link SKILL.md makes to a tracked file outside that
    directory is too.

    Compares EXPANDED file sets (via ``expand_paths``, the same expansion
    ``deps_completeness``/#993's ``deps.py`` uses), never raw path strings —
    a parent-directory entry, or a trailing ``/`` on an entry, is accepted
    in *direct* exactly when ``deps_completeness`` would accept it.

    *repo_root* is the git repository *direct* and the skill's SKILL.md are
    resolved against — the real repo for the scaffolding invariant this
    module pins below, or a synthetic temporary repo in this module's own
    unit tests.
    """
    problems: list[str] = []
    skill_dir_rel = f"{_SKILLS_ROOT}/{skill}"
    covered = set(expand_paths(direct, ref="HEAD", repo=repo_root))

    skill_dir_files = set(expand_paths([skill_dir_rel], ref="HEAD", repo=repo_root))
    if skill_dir_files - covered:
        problems.append(f"{skill}: direct tier missing the skill directory {skill_dir_rel!r}")

    skill_md_path = repo_root / skill_dir_rel / "SKILL.md"
    text = skill_md_path.read_text(encoding="utf-8") if skill_md_path.exists() else ""
    for link in _markdown_link_targets(text):
        resolved = posixpath.normpath(posixpath.join(skill_dir_rel, link))
        if resolved == skill_dir_rel or resolved.startswith(skill_dir_rel + "/"):
            continue  # inside the skill dir; covered by the skill dir's own files above
        tracked = set(expand_paths([resolved], ref="HEAD", repo=repo_root))
        if not tracked:
            continue  # not a tracked file; nothing for direct to cover
        if tracked - covered:
            problems.append(f"{skill}: outside link {link!r} -> {resolved} missing from direct tier")
    return problems


def test_direct_tier_problems_flags_a_missing_skill_dir(tmp_path):
    repo = _build_skill_repo(tmp_path, "commit", "No outside links here.\n")
    assert _direct_tier_problems("commit", [], repo_root=repo) != []


def test_direct_tier_problems_accepts_the_skill_dir_alone_when_there_is_no_outside_link(tmp_path):
    repo = _build_skill_repo(tmp_path, "commit", "No outside links here.\n")
    direct = [f"{_SKILLS_ROOT}/commit"]
    assert _direct_tier_problems("commit", direct, repo_root=repo) == []


def test_direct_tier_problems_accepts_a_trailing_slash_on_the_skill_dir_entry(tmp_path):
    """A trailing '/' on the skill dir entry is accepted, matching
    ``expand_paths`` (and so ``deps_completeness``), which strips it before
    resolving tracked files — never a literal string match.
    """
    repo = _build_skill_repo(tmp_path, "commit", "No outside links here.\n")
    direct = [f"{_SKILLS_ROOT}/commit/"]
    assert _direct_tier_problems("commit", direct, repo_root=repo) == []


def test_direct_tier_problems_flags_a_missing_outside_link(tmp_path):
    # An outside link, mirroring the real tdd SKILL.md's `../../docs/tdd.md`
    # link: a direct list holding only the skill dir must be flagged as
    # incomplete.
    repo = _build_skill_repo(
        tmp_path,
        "tdd",
        "See [the tdd doc](../../docs/tdd.md) for details.\n",
        extra_files={"plugins/workbench/docs/tdd.md": "tdd doc\n"},
    )
    direct = [f"{_SKILLS_ROOT}/tdd"]
    assert _direct_tier_problems("tdd", direct, repo_root=repo) != []


def test_direct_tier_problems_accepts_the_outside_link_covered_by_its_own_path(tmp_path):
    repo = _build_skill_repo(
        tmp_path,
        "tdd",
        "See [the tdd doc](../../docs/tdd.md) for details.\n",
        extra_files={"plugins/workbench/docs/tdd.md": "tdd doc\n"},
    )
    direct = [f"{_SKILLS_ROOT}/tdd", "plugins/workbench/docs/tdd.md"]
    assert _direct_tier_problems("tdd", direct, repo_root=repo) == []


def test_direct_tier_problems_accepts_a_parent_directory_entry_covering_the_outside_link(tmp_path):
    """A parent-directory entry that covers the outside link must be
    accepted exactly as ``deps_completeness`` accepts it, not just the
    outside link's own literal path.
    """
    repo = _build_skill_repo(
        tmp_path,
        "tdd",
        "See [the tdd doc](../../docs/tdd.md) for details.\n",
        extra_files={"plugins/workbench/docs/tdd.md": "tdd doc\n"},
    )
    direct = [f"{_SKILLS_ROOT}/tdd", "plugins/workbench/docs"]
    assert _direct_tier_problems("tdd", direct, repo_root=repo) == []


@pytest.mark.parametrize("skill", ROSTERED_SKILLS)
def test_deps_file_direct_tier_covers_the_skill_dir_and_outside_links(skill):
    path = _REPO_ROOT / "evals" / skill / "deps"
    deps = parse_deps(path.read_text(encoding="utf-8"))
    assert _direct_tier_problems(skill, deps["direct"], repo_root=_REPO_ROOT) == []
