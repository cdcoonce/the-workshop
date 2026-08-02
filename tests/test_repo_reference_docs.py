"""Tests for the repo-reference-docs core skill and its staleness checker.

This skill absorbed `readme-generator`: one skill now owns the root README *and*
`docs/reference/`, so a single pass keeps the front door and the deep set
consistent instead of two skills policing a lane boundary.
"""

import importlib.util
import sys
from pathlib import Path

from scripts.build_preset import build_preset

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / "core" / "skills" / "repo-reference-docs"


def _read_skill() -> str:
    return (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")


def test_repo_reference_docs_is_core_skill() -> None:
    """The skill is owned by core/skills so it flows into workbench via core.skills=all."""
    assert (SKILL_DIR / "SKILL.md").is_file()


def test_workbench_ships_repo_reference_docs(tmp_path: Path) -> None:
    """workbench (core.skills: 'all') includes the skill in its built plugin."""
    dist_path = build_preset("workbench", repo_root=REPO_ROOT, dist_root=tmp_path)
    assert (dist_path / "skills" / "repo-reference-docs" / "SKILL.md").is_file()


def test_readme_generator_is_gone() -> None:
    """The folded-in skill must not survive anywhere as an installable skill."""
    assert not (REPO_ROOT / "core" / "skills" / "readme-generator").exists()
    assert not (REPO_ROOT / "dist" / "workbench" / "skills" / "readme-generator").exists()


def test_skill_claims_the_readme_lane() -> None:
    """Triggers must catch README requests, since no other skill answers them now."""
    header = _read_skill().split("---", 2)[1].lower()
    assert "readme" in header
    assert "readme-generator" not in header


def test_skill_no_longer_defers_the_readme_to_another_skill() -> None:
    """The old lane guardrail would stop the skill touching the file it now owns."""
    body = _read_skill().lower()
    assert "never edit `readme.md`" not in body
    assert "do not touch files outside `docs/reference/`" not in body


def test_readme_authoring_references_survived_the_fold() -> None:
    """Badge, diagram, and section-template guidance moved in, not away."""
    refs = SKILL_DIR / "references"
    for name in ("readme-structure.md", "badge-reference.md", "mermaid-guidelines.md"):
        assert (refs / name).is_file(), f"{name} missing from repo-reference-docs references"


def _load_checker():
    spec = importlib.util.spec_from_file_location(
        "check_docs", SKILL_DIR / "scripts" / "check_docs.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_checker_flags_missing_covered_path(tmp_path: Path) -> None:
    """A doc whose provenance lists a now-deleted path is reported stale."""
    checker = _load_checker()
    doc = tmp_path / "architecture.md"
    doc.write_text(
        "# Architecture\n\nBody.\n\n"
        "<!-- repo-reference-docs: baseline=abc123 "
        "covers=src/gone.py,src/here.py -->\n"
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "here.py").write_text("x = 1\n")
    findings = checker.check_docs(tmp_path, repo_root=tmp_path)
    assert any("gone.py" in f.detail for f in findings)
    assert all("here.py" not in f.detail for f in findings)


def test_checker_passes_when_all_covered_paths_exist(tmp_path: Path) -> None:
    """No findings when every covered path still exists."""
    checker = _load_checker()
    doc = tmp_path / "module-map.md"
    doc.write_text(
        "# Modules\n\nBody.\n\n"
        "<!-- repo-reference-docs: baseline=abc123 covers=src/here.py -->\n"
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "here.py").write_text("x = 1\n")
    findings = checker.check_docs(tmp_path, repo_root=tmp_path)
    assert findings == []


def test_checker_covers_the_root_readme(tmp_path: Path) -> None:
    """The README is checked alongside docs/reference, not by a separate script."""
    checker = _load_checker()
    docs_dir = tmp_path / "docs" / "reference"
    docs_dir.mkdir(parents=True)
    (tmp_path / "README.md").write_text(
        "# Proj\n\nBody.\n\n"
        "<!-- repo-reference-docs: baseline=abc123 covers=pyproject.toml -->\n"
    )
    findings = checker.check_docs(docs_dir, repo_root=tmp_path, readme=tmp_path / "README.md")
    assert any("pyproject.toml" in f.detail for f in findings)
    assert all(f.doc == "README.md" for f in findings)


def test_checker_reads_the_legacy_readme_generator_footer(tmp_path: Path) -> None:
    """READMEs stamped by the old skill must not read as unstamped and get clobbered."""
    checker = _load_checker()
    docs_dir = tmp_path / "docs" / "reference"
    docs_dir.mkdir(parents=True)
    (tmp_path / "README.md").write_text(
        "# Proj\n\nBody.\n\n"
        "<!-- readme-generator: baseline=abc123 covers=pyproject.toml -->\n"
    )
    findings = checker.check_docs(docs_dir, repo_root=tmp_path, readme=tmp_path / "README.md")
    assert any("pyproject.toml" in f.detail for f in findings)


def test_checker_runs_with_a_readme_but_no_reference_docs(tmp_path: Path) -> None:
    """README-only repos are a supported mode; the CLI must not bail early on them."""
    checker = _load_checker()
    (tmp_path / "README.md").write_text(
        "# Proj\n\nBody.\n\n"
        "<!-- repo-reference-docs: baseline=abc123 covers=pyproject.toml -->\n"
    )
    exit_code = checker.main(
        [
            "--docs-dir",
            str(tmp_path / "docs" / "reference"),
            "--repo-root",
            str(tmp_path),
            "--readme",
            str(tmp_path / "README.md"),
        ]
    )
    assert exit_code == 1
