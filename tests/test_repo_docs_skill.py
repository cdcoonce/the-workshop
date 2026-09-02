"""Ownership, boundary, and retirement coverage for `repo-docs`.

`repo-docs` replaces `repo-reference-docs`. One skill owns every human-facing
documentation surface of a repository: the root README landing page and the
four Diátaxis mode directories under `docs/` (tutorials, how-to, reference,
explanation). It is the same consolidation `repo-reference-docs` made when it
absorbed `readme-generator`: one pass keeps the front door and the deep set
consistent instead of two skills policing a lane boundary, and the trigger
overlap lint exists because that boundary misrouted requests once already.

The flat plugin tree has no build step: the skill lives at
`plugins/workbench/skills/repo-docs/`, which *is* what ships.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS = REPO_ROOT / "plugins" / "workbench" / "skills"
SKILL_DIR = SKILLS / "repo-docs"
SKILL_MD = SKILL_DIR / "SKILL.md"

# Skills that produce or police repo documentation and must hand structural
# doc work to repo-docs rather than teach their own layout.
CONSUMERS = ("daa-code-review", "data-discovery", "prd-to-plan", "project-context", "walkthrough")
# Skills repo-docs must name as its own hand-offs (teach-me requests, the
# Claude-facing project.md).
HANDOFFS = ("walkthrough", "repo-crash-course", "project-context")
CARRIED_REFERENCES = (
    "readme-structure.md",
    "badge-reference.md",
    "mermaid-guidelines.md",
    "generated-erd.md",
    "analysis-phases.md",
)
MODE_REFERENCES = (
    "compass.md",
    "mode-tutorial.md",
    "mode-how-to.md",
    "mode-reference.md",
    "mode-explanation.md",
    "layout.md",
    "workflow.md",
)


def _normalized(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def _frontmatter(path: Path) -> str:
    return path.read_text(encoding="utf-8").split("---", 2)[1]


# --------------------------------------------------------------------------
# Ownership and retirement
# --------------------------------------------------------------------------


def test_skill_is_owned_by_workbench() -> None:
    """Universal capability, so workbench owns the slug and nothing else ships it."""
    assert SKILL_MD.is_file()
    assert not any(
        p for p in (REPO_ROOT / "plugins").glob("*/skills/repo-docs") if "workbench" not in p.parts
    )


def test_replaced_skills_are_gone() -> None:
    """Neither the replaced skill nor the one it had absorbed may survive as installable."""
    for slug in ("repo-reference-docs", "readme-generator"):
        assert not any((REPO_ROOT / "plugins").glob(f"*/skills/{slug}")), slug


def test_stays_within_progressive_disclosure_budget() -> None:
    """SKILL.md is the router; mode guides, layout, and workflow live in references/."""
    assert len(SKILL_MD.read_text(encoding="utf-8").splitlines()) < 100


@pytest.mark.parametrize("name", CARRIED_REFERENCES)
def test_carried_reference_survived_the_replacement(name: str) -> None:
    """README, badge, diagram, ERD, and deep-analysis guidance moved in, not away."""
    assert (SKILL_DIR / "references" / name).is_file()


@pytest.mark.parametrize("name", MODE_REFERENCES)
def test_mode_reference_exists(name: str) -> None:
    """Each Diátaxis mode, the compass, the layout, and the loop have a home."""
    assert (SKILL_DIR / "references" / name).is_file()


def test_ships_behavioral_contract() -> None:
    """A discipline skill ships tests.md with a pressure scenario and a RED baseline."""
    text = (SKILL_DIR / "tests.md").read_text(encoding="utf-8")
    assert "## Pressure Scenario" in text
    assert "## RED Baseline" in text


def test_checker_ships_its_own_test_suite() -> None:
    """Behavioral coverage rides the auto-discovered skill-script gate."""
    assert any((SKILL_DIR / "scripts" / "tests").glob("test_*.py"))


# --------------------------------------------------------------------------
# Triggers and routes
# --------------------------------------------------------------------------


def test_description_claims_the_readme_lane() -> None:
    """README requests must route here; no other skill answers them."""
    header = _frontmatter(SKILL_MD).lower()
    assert "readme" in header
    assert "use when" in header
    assert "repo-reference-docs" not in header


@pytest.mark.parametrize("skill", CONSUMERS)
def test_consumer_routes_to_repo_docs(skill: str) -> None:
    """A skill nobody routes to does not run; repo-reference-docs had zero inbound routes."""
    assert "repo-docs" in _normalized(SKILLS / skill / "SKILL.md"), (
        f"{skill} touches repo documentation but never routes to repo-docs"
    )


@pytest.mark.parametrize("skill", CONSUMERS + HANDOFFS)
def test_repo_docs_names_each_route(skill: str) -> None:
    """The reverse direction: repo-docs says where it hands off and who hands to it."""
    assert skill in _normalized(SKILL_MD), f"repo-docs does not mention {skill}"


# --------------------------------------------------------------------------
# The discipline itself
# --------------------------------------------------------------------------


def test_skill_states_the_single_mode_law() -> None:
    """The law is one unconditional sentence, visible every time the skill fires."""
    assert "no document serves two modes" in _normalized(SKILL_MD).lower()


def test_skill_forbids_empty_mode_directories() -> None:
    """Diátaxis' own rule: structure emerges from content, never from scaffolding."""
    assert "never create an empty mode directory" in _normalized(SKILL_MD).lower()


def test_skill_stands_down_in_the_vault() -> None:
    """The vault has its own taxonomy and write hook; the skill must detect it and stop."""
    text = _normalized(SKILL_MD)
    assert ".vault/vault.json" in text or ".vault-context" in text


def test_skill_keeps_the_hand_written_readme_guardrail() -> None:
    """An unstamped README is someone's work; confirm before overwriting it."""
    text = _normalized(SKILL_MD).lower()
    assert "unstamped" in text
    assert "confirm" in text


# --------------------------------------------------------------------------
# Checker contract (full behavior lives in scripts/tests/test_check_docs.py)
# --------------------------------------------------------------------------


def _load_checker():
    spec = importlib.util.spec_from_file_location(
        "check_docs", SKILL_DIR / "scripts" / "check_docs.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_checker_accepts_legacy_footers(tmp_path: Path) -> None:
    """Docs stamped by repo-reference-docs (IQ, OneStream) must not read as unstamped."""
    checker = _load_checker()
    docs = tmp_path / "docs" / "reference"
    docs.mkdir(parents=True)
    (docs / "architecture.md").write_text(
        "# Arch\n\nBody.\n\n<!-- repo-reference-docs: baseline=abc123 covers=src/gone.py -->\n"
    )
    (tmp_path / "README.md").write_text(
        "# Proj\n\nBody.\n\n<!-- readme-generator: baseline=abc123 covers=pyproject.toml -->\n"
    )
    findings = checker.check_docs(tmp_path / "docs", repo_root=tmp_path, readme=tmp_path / "README.md")
    kinds = {(f.doc, f.kind) for f in findings}
    assert ("docs/reference/architecture.md", "missing-path") in kinds
    assert ("README.md", "missing-path") in kinds


def test_checker_reports_a_doc_in_the_wrong_mode_directory(tmp_path: Path) -> None:
    """A how-to filed under docs/reference/ is the drift this skill exists to stop."""
    checker = _load_checker()
    docs = tmp_path / "docs" / "reference"
    docs.mkdir(parents=True)
    (docs / "deployment-runbook.md").write_text(
        "# How to deploy\n\nSteps.\n\n<!-- repo-docs: mode=how-to baseline=abc123 covers=README.md -->\n"
    )
    (tmp_path / "README.md").write_text("# Proj\n")
    findings = checker.check_docs(tmp_path / "docs", repo_root=tmp_path)
    assert any(f.kind == "mode-mismatch" and "deployment-runbook.md" in f.doc for f in findings)
