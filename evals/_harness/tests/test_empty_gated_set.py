"""Tests for evals._harness.guards.empty_gated_set."""

from __future__ import annotations

from pathlib import Path

from evals._harness.guards import GuardContext
from evals._harness.guards.empty_gated_set import check

_VALID_RETIRED_ENTRY = (
    "## gated.old\n"
    "- date: 2026-01-01\n"
    "- reason: noise\n"
    "- evidence: flaked in three consecutive runs\n"
)


def _write(repo: Path, rel_path: str, content: str) -> None:
    path = repo / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_fails_on_an_active_skill_with_zero_gated_ids(tmp_path):
    # Active via a retired.md entry alone — the manifest itself is empty.
    _write(tmp_path, "evals/commit/checks.manifest", "")
    _write(tmp_path, "evals/commit/retired.md", _VALID_RETIRED_ENTRY)

    results = check(GuardContext(base="unused", repo_root=tmp_path))

    assert len(results) == 1
    assert results[0].level == "fail"
    assert results[0].guard == "empty_gated_set"
    assert "commit" in results[0].message


def test_passes_when_inactive_with_zero_gated_ids(tmp_path):
    _write(tmp_path, "evals/commit/checks.manifest", "")
    _write(tmp_path, "evals/commit/retired.md", "")

    results = check(GuardContext(base="unused", repo_root=tmp_path))

    assert results == []


def test_passes_when_active_with_a_gated_id(tmp_path):
    _write(tmp_path, "evals/commit/checks.manifest", "gated.one A description\n")
    _write(tmp_path, "evals/commit/retired.md", "")

    results = check(GuardContext(base="unused", repo_root=tmp_path))

    assert results == []


def test_skips_a_skill_with_no_directory_yet(tmp_path):
    results = check(GuardContext(base="unused", repo_root=tmp_path))

    assert results == []
