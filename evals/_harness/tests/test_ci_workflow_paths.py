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

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CI_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
# A YAML comment starts at a `#` that begins the line or follows whitespace.
_COMMENT_PATTERN = re.compile(r"(^|\s)#.*$", re.MULTILINE)
# The key may be a block key at line start, follow whitespace or a `- ` dash
# (`- paths: [a]`), or follow a flow-mapping `{` or `,` (`{push: {paths: [a]}}`,
# `{a: 1,paths: [x]}`); it may be quoted. PyYAML is not a dependency of the
# `test-evals` environment, so this stays a regex.
_PATH_FILTER_KEY_PATTERN = re.compile(
    r"(?:^|[\s{,\[])[\"']?paths(?:-ignore)?[\"']?\s*:", re.MULTILINE
)


def _strip_comments(text: str) -> str:
    return _COMMENT_PATTERN.sub(lambda match: match.group(1), text)


def _has_path_filter_key(text: str) -> bool:
    """Return whether *text* declares a `paths` or `paths-ignore` trigger key."""
    return bool(_PATH_FILTER_KEY_PATTERN.search(_strip_comments(text)))


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


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("on:\n  push:\n    branches: [main]\n    paths: ['a']\n", id="block-paths"),
        pytest.param("paths-ignore:\n  - a\n", id="top-level-block-key"),
        pytest.param("on:\n  push: {paths: [a]}\n", id="flow-mapping-after-brace"),
        pytest.param("on:\n  push: {branches: [main],paths-ignore: [a]}\n", id="flow-after-comma"),
        pytest.param("on: {push: {paths: ['a']}}\n", id="fully-flow-style"),
        pytest.param('on:\n  push:\n    "paths":\n      - a\n', id="double-quoted-key"),
        pytest.param("on:\n  push:\n    'paths-ignore':\n      - a\n", id="single-quoted-key"),
        pytest.param("on:\n  - push\n  - paths: [a]\n", id="inline-after-dash"),
        pytest.param("on:\n  push:\n    paths  :\n      - a\n", id="space-before-colon"),
        pytest.param("on:\n  push:\n    paths: [a]  # only these\n", id="trailing-comment"),
    ],
)
def test_detects_every_yaml_spelling_of_a_path_filter_key(text):
    assert _has_path_filter_key(text)


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("# paths: x\n", id="comment-line"),
        pytest.param("on:\n  push:\n    # paths-ignore: ['docs/**']\n    branches: [main]\n", id="indented-comment"),
        pytest.param("on:\n  push:\n    branches: [main]  # no paths: filter here\n", id="trailing-comment"),
        pytest.param("env:\n  filepaths: x\n  subpaths-ignore: y\n", id="key-merely-ending-in-paths"),
        pytest.param("jobs:\n  t:\n    steps:\n      - run: make test\n", id="no-key"),
    ],
)
def test_does_not_flag_text_that_is_not_a_path_filter_key(text):
    assert not _has_path_filter_key(text)
