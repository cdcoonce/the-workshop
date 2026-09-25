"""Behavioural coverage for the pure `.mr-preflight.toml` rules.

`ignore_paths` globs follow git's own path-glob rules rather than `fnmatch`'s,
because under `fnmatch` a `*` crosses `/`: `*.md` written for the root
changelog would quietly ignore every Markdown file in the repository, which is
exactly the allowlist creep the config must not make easy.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ignore_config import ConfigError, parse_config  # noqa: E402


def ignored(pattern: str, path: str) -> bool:
    return parse_config(f"ignore_paths = [{pattern!r}]\n").ignores_path(path)


@pytest.mark.parametrize(
    ("pattern", "path", "expected"),
    [
        ("*.md", "CHANGELOG.md", True),
        ("*.md", "docs/notes.md", False),  # `*` never crosses `/`
        ("docs/*", "docs/a.md", True),
        ("docs/*", "docs/sub/a.md", False),
        ("a?c.md", "a/c.md", False),  # nor does `?`
        ("docs/adr/**", "docs/adr/0001.md", True),
        ("docs/adr/**", "docs/adr/archive/0000.md", True),  # `**` spans segments
        ("docs/adr/**", "docs/adr", False),  # a trailing `**` is what is inside
        ("docs/adr/**", "docs/adrs/0001.md", False),
        ("**/CHANGELOG.md", "CHANGELOG.md", True),  # a leading `**` may be empty
        ("**/CHANGELOG.md", "pkg/sub/CHANGELOG.md", True),
        ("docs/**/old.md", "docs/old.md", True),  # so may a middle one
        ("docs/**/old.md", "docs/a/b/old.md", True),
        ("CHANGELOG.md", "docs/CHANGELOG.md", False),  # the whole path matches
        ("changelog.md", "CHANGELOG.md", False),  # case-sensitive, like git
        ("sql/v[0-9].sql", "sql/v1.sql", True),
        ("sql/v[!0-9].sql", "sql/vx.sql", True),
        ("sql/v[^0-9].sql", "sql/vx.sql", True),  # git negates with `^` too
        ("sql/v[^0-9].sql", "sql/v1.sql", False),
        ("sql/v[^0-9].sql", "sql/v^.sql", True),
        ("sql/v[]^].sql", "sql/v^.sql", True),  # a `^` that is not first is literal
        ("notes:v2/*.md", "notes:v2/a.md", True),  # `:` is an ordinary character
    ],
)
def test_ignore_paths_match_like_git_path_globs(pattern: str, path: str, expected: bool) -> None:
    assert ignored(pattern, path) is expected


def test_many_double_stars_stay_linear_on_a_deep_path() -> None:
    """Each `**` tries every split, so without memoising, ten of them against
    a 21-deep path take seconds per hit, and the sweep checks every hit."""
    config = parse_config(f"ignore_paths = [{'**/' * 10 + 'nomatch.md'!r}]\n")
    path = "/".join(["d"] * 20 + ["x.md"])

    started = time.monotonic()
    assert not config.ignores_path(path)
    assert time.monotonic() - started < 1.0


@pytest.mark.parametrize("pattern", ["a\\\\*b.md", "sql/v[[:digit:]].sql"])
def test_glob_syntax_git_reads_differently_is_refused(pattern: str) -> None:
    """`fnmatch` has no `\\` escape and no `[:class:]`, so it would read these
    as something git does not, and ignore a path git would keep."""
    with pytest.raises(ConfigError, match="ignore_paths"):
        parse_config(f'ignore_paths = ["{pattern}"]\n')
