"""The committed ``.mr-preflight.toml``: noise a repo ignores once, for good.

Pure: no git, no filesystem. The caller reads the file from the head tree and
hands its text here, so every rule is testable against a string.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from fnmatch import fnmatchcase

CONFIG_NAME = ".mr-preflight.toml"
KEYS = ("ignore_paths", "ignore_tokens")


class ConfigError(ValueError):
    """The config cannot be read as written: a setup error, never "no ignores"."""


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
    """Parse the text of ``.mr-preflight.toml``.

    Raises
    ------
    ConfigError
        On invalid TOML, an unknown key (a misspelt one would otherwise ignore
        nothing, silently), or a value that is not a list of strings (a bare
        string would otherwise iterate into one-character globs).
    """
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(str(error)) from error
    unknown = sorted(set(data) - set(KEYS))
    if unknown:
        raise ConfigError(f"unknown key(s) {', '.join(unknown)}; expected {' and '.join(KEYS)}")
    for key in KEYS:
        value = data.get(key, [])
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ConfigError(f"{key} must be a list of strings")
    return IgnoreConfig(
        paths=tuple(data.get("ignore_paths", [])),
        tokens=frozenset(data.get("ignore_tokens", [])),
    )
