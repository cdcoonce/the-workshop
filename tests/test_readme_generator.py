"""Tests for readme-generator's lane boundary and its README drift checker."""

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / "core" / "skills" / "readme-generator"


def _read_skill() -> str:
    return (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")


def test_description_defers_deep_docs_to_repo_reference_docs() -> None:
    """The front-door README skill must point multi-file reference docs elsewhere."""
    text = _read_skill().lower()
    assert "repo-reference-docs" in text


def test_description_drops_colliding_broad_triggers() -> None:
    """Broad phrases that collide with repo-reference-docs are removed from triggers."""
    # Only inspect the frontmatter description block.
    header = _read_skill().split("---", 2)[1].lower()
    assert "write docs for this repo" not in header
    assert "document this project" not in header


def _load_checker():
    spec = importlib.util.spec_from_file_location(
        "check_readme", SKILL_DIR / "scripts" / "check_readme.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_checker_flags_missing_anchor(tmp_path: Path) -> None:
    """A README whose provenance anchor was deleted is reported stale."""
    checker = _load_checker()
    (tmp_path / "README.md").write_text(
        "# Proj\n\nBody.\n\n"
        "<!-- readme-generator: baseline=abc123 "
        "covers=pyproject.toml,src/main.py -->\n"
    )
    (tmp_path / "pyproject.toml").write_text("[project]\n")
    findings = checker.check_readme(tmp_path / "README.md", repo_root=tmp_path)
    assert any("src/main.py" in f.detail for f in findings)
    assert all("pyproject.toml" not in f.detail for f in findings)


def test_checker_passes_when_anchors_exist(tmp_path: Path) -> None:
    """No findings when every front-door anchor still exists."""
    checker = _load_checker()
    (tmp_path / "README.md").write_text(
        "# Proj\n\nBody.\n\n"
        "<!-- readme-generator: baseline=abc123 covers=pyproject.toml -->\n"
    )
    (tmp_path / "pyproject.toml").write_text("[project]\n")
    findings = checker.check_readme(tmp_path / "README.md", repo_root=tmp_path)
    assert findings == []
