"""The committed ``.mr-preflight.toml``: noise a repo ignores once, for good.

Pure: no git, no filesystem. The caller reads the file from the head tree and
hands its text here, so every rule is testable against a string.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from fnmatch import fnmatchcase

CONFIG_NAME = ".mr-preflight.toml"


@dataclass(frozen=True)
class IgnoreConfig:
    """Paths whose hits are dropped and tokens that are never chased."""

    paths: tuple[str, ...] = ()
    tokens: frozenset[str] = frozenset()

    def ignores_path(self, path: str) -> bool:
        """Whether a repo-relative ``path`` matches any ``ignore_paths`` glob."""
        segments = path.split("/")
        return any(_glob_match(pattern.split("/"), segments) for pattern in self.paths)


def _glob_match(pattern: list[str], path: list[str]) -> bool:
    """Match path segments the way git's path globs do.

    ``*``, ``?`` and ``[...]`` stay inside one segment, so ``*.md`` is the
    root's Markdown only; a whole ``**`` segment spans any number of them. A
    leading or middle ``**`` may match none, a trailing one at least one, so
    ``docs/adr/**`` is what is inside ``docs/adr``, never a file of that name.
    """
    if not pattern:
        return not path
    head, rest = pattern[0], pattern[1:]
    if head == "**":
        if not rest:
            return bool(path)
        return any(_glob_match(rest, path[skip:]) for skip in range(len(path) + 1))
    return bool(path) and fnmatchcase(path[0], head) and _glob_match(rest, path[1:])


def parse_config(text: str) -> IgnoreConfig:
    """Parse the text of ``.mr-preflight.toml``."""
    data = tomllib.loads(text)
    return IgnoreConfig(
        paths=tuple(data.get("ignore_paths", ())),
        tokens=frozenset(data.get("ignore_tokens", ())),
    )
