"""Tests for evals._harness.guards.uncalibrated."""

from __future__ import annotations

from pathlib import Path

from evals._harness.guards import GuardContext
from evals._harness.guards.uncalibrated import check


def _write(repo: Path, rel_path: str, content: str) -> None:
    path = repo / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_warns_on_a_synthetic_inactive_rostered_skill(tmp_path):
    _write(tmp_path, "evals/commit/checks.manifest", "")
    _write(tmp_path, "evals/commit/retired.md", "")

    results = check(GuardContext(base="HEAD", repo_root=tmp_path))

    assert len(results) == 1
    assert results[0].level == "warn"
    assert results[0].guard == "uncalibrated"
    assert "commit" in results[0].message


def test_no_result_for_a_synthetic_active_rostered_skill(tmp_path):
    _write(tmp_path, "evals/commit/checks.manifest", "gated.one A description\n")
    _write(tmp_path, "evals/commit/retired.md", "")

    results = check(GuardContext(base="HEAD", repo_root=tmp_path))

    assert results == []


def test_ignores_a_non_rostered_skill_directory(tmp_path):
    _write(tmp_path, "evals/not-rostered/checks.manifest", "")
    _write(tmp_path, "evals/not-rostered/retired.md", "")

    results = check(GuardContext(base="HEAD", repo_root=tmp_path))

    assert results == []


def test_skips_a_rostered_skill_with_no_directory_yet(tmp_path):
    results = check(GuardContext(base="HEAD", repo_root=tmp_path))

    assert results == []
