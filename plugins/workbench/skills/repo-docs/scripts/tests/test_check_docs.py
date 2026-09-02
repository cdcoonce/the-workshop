"""Tests for check_docs.

Every check runs against real files in a scratch directory, and the
changed-source check against a real git repository, because the failure modes
this script exists to catch are filesystem and git facts: a covered path that
moved, a relative link whose target is gone, a how-to filed under
docs/reference/, a README that outgrew its landing-page bar. A mock would only
re-assert the checker's own assumptions.

The checker is stdlib only and fails open on its own errors; the CLI's exit
code is the CI verdict (0 clean, 1 findings).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import check_docs  # noqa: E402

NEW = "<!-- repo-docs: mode={mode} baseline={baseline} covers={covers} -->\n"
LEGACY = "<!-- repo-reference-docs: baseline={baseline} covers={covers} -->\n"
README_GEN = "<!-- readme-generator: baseline={baseline} covers={covers} -->\n"


def _write(path: Path, body: str, footer: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body + ("\n" + footer if footer else ""), encoding="utf-8")
    return path


def _kinds(findings: list[check_docs.Finding]) -> set[tuple[str, str]]:
    """(basename, kind) pairs; ``Finding.doc`` itself is the repo-relative path."""
    return {(Path(f.doc).name, f.kind) for f in findings}


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repo root with a source file every test can cover."""
    _write(tmp_path / "src" / "here.py", "x = 1\n")
    return tmp_path


def _check(repo: Path, **kwargs) -> list[check_docs.Finding]:
    readme = repo / "README.md"
    return check_docs.check_docs(
        repo / "docs", repo_root=repo, readme=readme if readme.is_file() else None, **kwargs
    )


# --------------------------------------------------------------------------
# Footer parsing and provenance
# --------------------------------------------------------------------------


def test_stamped_doc_in_its_own_mode_directory_is_clean(repo: Path) -> None:
    _write(
        repo / "docs" / "how-to" / "deploy.md",
        "# How to deploy\n\nSteps.\n",
        NEW.format(mode="how-to", baseline="abc123", covers="src/here.py"),
    )
    assert _check(repo) == []


def test_legacy_repo_reference_docs_footer_is_accepted(repo: Path) -> None:
    """Docs already stamped in IQ and OneStream must keep being checked, not skipped."""
    _write(
        repo / "docs" / "reference" / "architecture.md",
        "# Arch\n",
        LEGACY.format(baseline="abc123", covers="src/gone.py"),
    )
    assert ("architecture.md", "missing-path") in _kinds(_check(repo))


def test_legacy_readme_generator_footer_is_accepted(repo: Path) -> None:
    _write(repo / "README.md", "# Proj\n", README_GEN.format(baseline="abc123", covers="pyproject.toml"))
    assert ("README.md", "missing-path") in _kinds(_check(repo))


def test_missing_covered_path_is_reported_and_present_path_is_not(repo: Path) -> None:
    _write(
        repo / "docs" / "reference" / "module-map.md",
        "# Modules\n",
        NEW.format(mode="reference", baseline="abc123", covers="src/gone.py,src/here.py"),
    )
    findings = _check(repo)
    assert any(f.kind == "missing-path" and "gone.py" in f.detail for f in findings)
    assert all("here.py" not in f.detail for f in findings)


def test_changed_source_is_reported_against_a_real_git_baseline(repo: Path) -> None:
    _git(repo, "init", "-q")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "baseline")
    baseline = _git(repo, "rev-parse", "HEAD")
    _write(
        repo / "docs" / "reference" / "module-map.md",
        "# Modules\n",
        NEW.format(mode="reference", baseline=baseline, covers="src/here.py"),
    )
    assert _check(repo) == []
    _write(repo / "src" / "here.py", "x = 2\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "change source")
    assert ("module-map.md", "changed-source") in _kinds(_check(repo))


# --------------------------------------------------------------------------
# Relative link integrity
# --------------------------------------------------------------------------


def test_dangling_relative_link_is_reported(repo: Path) -> None:
    _write(repo / "docs" / "how-to" / "deploy.md", "See [the schema](../reference/nope.md).\n")
    findings = _check(repo)
    assert any(f.kind == "broken-link" and "nope.md" in f.detail for f in findings)


def test_resolving_relative_link_with_anchor_passes(repo: Path) -> None:
    _write(repo / "docs" / "reference" / "schema.md", "# Schema\n\n## Entities\n")
    _write(repo / "docs" / "how-to" / "deploy.md", "See [entities](../reference/schema.md#entities).\n")
    assert _check(repo) == []


def test_root_relative_link_resolves_from_the_repo_root(repo: Path) -> None:
    """From a nested doc, so a doc-relative resolution would look for docs/how-to/docs/…"""
    _write(repo / "docs" / "reference" / "schema.md", "# Schema\n")
    _write(repo / "docs" / "how-to" / "deploy.md", "See [schema](/docs/reference/schema.md).\n")
    assert _check(repo) == []


def test_root_readme_may_only_declare_landing(repo: Path) -> None:
    _write(repo / "README.md", "# Proj\n", NEW.format(mode="reference", baseline="abc123", covers="src/here.py"))
    assert ("README.md", "mode-mismatch") in _kinds(_check(repo))


def test_external_mailto_and_anchor_only_links_are_ignored(repo: Path) -> None:
    _write(
        repo / "docs" / "explanation" / "why.md",
        "[site](https://diataxis.fr/) [mail](mailto:a@b.c) [top](#why) [ftp](ftp://x/y.md)\n",
    )
    assert _check(repo) == []


def test_links_inside_fenced_code_blocks_are_ignored(repo: Path) -> None:
    """Templates carry example links; a fence is the author saying 'not a real link'."""
    _write(
        repo / "docs" / "reference" / "conventions.md",
        "# Conventions\n\n```markdown\nSee [example](../how-to/not-real.md).\n```\n\n~~~\n[also](./ghost.md)\n~~~\n",
    )
    assert _check(repo) == []


def test_unstamped_docs_are_link_checked_but_never_mode_checked(repo: Path) -> None:
    _write(repo / "docs" / "reference" / "hand-written.md", "See [gone](./gone.md).\n")
    findings = _check(repo)
    assert {f.kind for f in findings} == {"broken-link"}


def test_the_readme_is_link_checked(repo: Path) -> None:
    _write(repo / "README.md", "See [docs](docs/README.md).\n")
    assert ("README.md", "broken-link") in _kinds(_check(repo))


# --------------------------------------------------------------------------
# Mode versus directory
# --------------------------------------------------------------------------


def test_how_to_filed_under_reference_is_a_mode_mismatch(repo: Path) -> None:
    _write(
        repo / "docs" / "reference" / "deployment-runbook.md",
        "# How to deploy\n",
        NEW.format(mode="how-to", baseline="abc123", covers="src/here.py"),
    )
    findings = _check(repo)
    assert any(f.kind == "mode-mismatch" and "docs/how-to" in f.detail for f in findings)


def test_stamped_mode_outside_any_mode_directory_is_a_mode_mismatch(repo: Path) -> None:
    _write(
        repo / "docs" / "notes.md",
        "# Notes\n",
        NEW.format(mode="reference", baseline="abc123", covers="src/here.py"),
    )
    assert ("notes.md", "mode-mismatch") in _kinds(_check(repo))


def test_unknown_mode_value_is_a_mode_mismatch(repo: Path) -> None:
    _write(
        repo / "docs" / "reference" / "x.md",
        "# X\n",
        NEW.format(mode="runbook", baseline="abc123", covers="src/here.py"),
    )
    assert ("x.md", "mode-mismatch") in _kinds(_check(repo))


@pytest.mark.parametrize(
    "rel",
    ["README.md", "docs/README.md", "docs/how-to/README.md"],
)
def test_landing_mode_is_valid_on_any_readme(repo: Path, rel: str) -> None:
    _write(repo / rel, "# Landing\n", NEW.format(mode="landing", baseline="abc123", covers="src/here.py"))
    assert _check(repo) == []


def test_landing_mode_on_a_non_readme_is_a_mode_mismatch(repo: Path) -> None:
    _write(
        repo / "docs" / "how-to" / "guide.md",
        "# Guide\n",
        NEW.format(mode="landing", baseline="abc123", covers="src/here.py"),
    )
    assert ("guide.md", "mode-mismatch") in _kinds(_check(repo))


def test_mode_directory_readme_may_declare_its_own_mode(repo: Path) -> None:
    _write(
        repo / "docs" / "how-to" / "README.md",
        "# How-to guides\n",
        NEW.format(mode="how-to", baseline="abc123", covers="src/here.py"),
    )
    assert _check(repo) == []


def test_a_mode_directory_passed_as_docs_dir_still_resolves_modes_from_its_parent(repo: Path) -> None:
    """The old flag default was docs/reference; modes must not all read as 'outside docs/'."""
    _write(
        repo / "docs" / "reference" / "deployment-runbook.md",
        "# How to deploy\n",
        NEW.format(mode="how-to", baseline="abc123", covers="src/here.py"),
    )
    findings = check_docs.check_docs(repo / "docs" / "reference", repo_root=repo)
    assert any(f.kind == "mode-mismatch" and "docs/reference/" in f.detail for f in findings)


def test_legacy_footer_under_reference_skips_the_mode_check(repo: Path) -> None:
    """A legacy footer carries no mode; the doc is re-stamped on its next rewrite, not failed now."""
    _write(
        repo / "docs" / "reference" / "deployment-runbook.md",
        "# How to deploy\n",
        LEGACY.format(baseline="abc123", covers="src/here.py"),
    )
    assert _check(repo) == []


# --------------------------------------------------------------------------
# Exemptions
# --------------------------------------------------------------------------


@pytest.mark.parametrize("folder", ["plans", "archive", "code_reviews", "security-reviews", "dev-cycle"])
def test_process_directories_are_exempt_from_every_check(repo: Path, folder: str) -> None:
    _write(
        repo / "docs" / folder / "thing.md",
        "See [gone](./gone.md).\n",
        NEW.format(mode="how-to", baseline="abc123", covers="src/gone.py"),
    )
    assert _check(repo) == []


def test_extra_exempt_directories_can_be_supplied(repo: Path) -> None:
    _write(repo / "docs" / "notebooks" / "x.md", "See [gone](./gone.md).\n")
    assert _check(repo) != []
    assert _check(repo, exempt=("notebooks",)) == []


# --------------------------------------------------------------------------
# README landing bar
# --------------------------------------------------------------------------


def test_readme_over_the_landing_bar_is_reported(repo: Path) -> None:
    _write(repo / "README.md", "# Proj\n" + "line\n" * 200)
    findings = _check(repo)
    assert any(f.kind == "readme-length" and "150" in f.detail for f in findings)


def test_readme_under_the_landing_bar_is_clean(repo: Path) -> None:
    _write(repo / "README.md", "# Proj\n" + "line\n" * 100)
    assert _check(repo) == []


def test_readme_bar_can_be_raised_or_disabled(repo: Path) -> None:
    _write(repo / "README.md", "# Proj\n" + "line\n" * 200)
    assert _check(repo, readme_max_lines=300) == []
    assert _check(repo, readme_max_lines=0) == []


# --------------------------------------------------------------------------
# CLI contract
# --------------------------------------------------------------------------


def _cli(repo: Path, *extra: str) -> int:
    return check_docs.main(
        [
            "--docs-dir",
            str(repo / "docs"),
            "--repo-root",
            str(repo),
            "--readme",
            str(repo / "README.md"),
            *extra,
        ]
    )


def test_cli_exits_zero_when_clean(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write(repo / "README.md", "# Proj\n", NEW.format(mode="landing", baseline="abc123", covers="src/here.py"))
    assert _cli(repo) == 0
    assert "consistent" in capsys.readouterr().out


def test_cli_exits_one_on_findings_and_names_each_kind(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(repo / "README.md", "See [gone](docs/gone.md).\n" + "line\n" * 200)
    assert _cli(repo) == 1
    out = capsys.readouterr().out
    assert "[broken-link]" in out
    assert "[readme-length]" in out


def test_cli_flags_reach_the_checker(repo: Path) -> None:
    _write(repo / "README.md", "# Proj\n" + "line\n" * 200)
    _write(repo / "docs" / "notebooks" / "x.md", "See [gone](./gone.md).\n")
    assert _cli(repo, "--readme-max-lines", "0", "--exempt", "qa_reports,notebooks") == 0


def test_cli_with_nothing_to_check_exits_zero(tmp_path: Path) -> None:
    assert _cli(tmp_path) == 0


def test_cli_runs_with_a_readme_but_no_docs_directory(repo: Path) -> None:
    """README-only repos are a supported scope; the CLI must not bail early on them."""
    _write(repo / "README.md", "# Proj\n", NEW.format(mode="landing", baseline="abc123", covers="src/gone.py"))
    assert _cli(repo) == 1


def test_cli_resolves_relative_docs_and_readme_against_repo_root(
    repo: Path, tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The skill runs the checker from its own base directory with --repo-root pointing
    at the target repo; the default docs/ and README.md must resolve there, not in the
    cwd, where they do not exist and would read as "nothing to check": a false green."""
    _write(repo / "README.md", "See [gone](docs/gone.md).\n")
    monkeypatch.chdir(tmp_path_factory.mktemp("elsewhere"))
    assert check_docs.main(["--repo-root", str(repo)]) == 1


def test_example_footer_inside_a_fence_is_not_provenance(repo: Path) -> None:
    """A template that quotes a footer must not make the file read as stamped."""
    _write(
        repo / "docs" / "reference" / "conventions.md",
        "# Conventions\n\n```markdown\n<!-- repo-docs: mode=landing baseline=abc123 covers=src/gone.py -->\n```\n",
    )
    assert _check(repo) == []


def test_the_real_footer_wins_over_a_quoted_one(repo: Path) -> None:
    _write(
        repo / "docs" / "reference" / "conventions.md",
        "# Conventions\n\n```markdown\n<!-- repo-docs: mode=how-to baseline=abc123 covers=src/gone.py -->\n```\n",
        NEW.format(mode="reference", baseline="abc123", covers="src/here.py"),
    )
    assert _check(repo) == []


def test_the_last_unfenced_footer_is_the_doc_s_provenance(repo: Path) -> None:
    """A stale footer left mid-document (a bad merge) must not outrank the one on the last line."""
    _write(
        repo / "docs" / "reference" / "conventions.md",
        "# Conventions\n\n"
        + NEW.format(mode="how-to", baseline="abc123", covers="src/gone.py")
        + "\nBody continues.\n",
        NEW.format(mode="reference", baseline="abc123", covers="src/here.py"),
    )
    assert _check(repo) == []
