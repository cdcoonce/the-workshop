"""Repo-level check: the CI workflow must carry no path-filter trigger key.

A `paths`/`paths-ignore` trigger key on the workflow would let an evals-only
PR skip CI entirely, silently exempting the eval-suite guards this epic (#988)
adds from ever running. This test reads `.github/workflows/ci.yml` directly;
it is a plain pytest test picked up by `make test-evals`'s own pytest
invocation, not a `check(ctx)` guard the runner discovers.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CI_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
_PATH_FILTER_KEY_PATTERN = re.compile(r"^\s*paths(-ignore)?\s*:", re.MULTILINE)


def _has_path_filter_key(text: str) -> bool:
    """Return whether *text* declares a `paths` or `paths-ignore` trigger key."""
    return bool(_PATH_FILTER_KEY_PATTERN.search(text))


def test_ci_workflow_has_no_path_filter_key():
    text = _CI_WORKFLOW.read_text(encoding="utf-8")

    assert not _has_path_filter_key(text)


def test_detects_a_paths_trigger_key():
    text = "on:\n  push:\n    paths:\n      - 'foo'\n"

    assert _has_path_filter_key(text)


def test_detects_a_paths_ignore_trigger_key():
    text = "on:\n  push:\n    paths-ignore:\n      - 'foo'\n"

    assert _has_path_filter_key(text)


def test_does_not_flag_an_unrelated_paths_substring():
    text = "# just talking about paths casually, not a trigger key\n"

    assert not _has_path_filter_key(text)
