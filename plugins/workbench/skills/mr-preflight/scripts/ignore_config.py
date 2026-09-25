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
        return any(fnmatchcase(path, pattern) for pattern in self.paths)


def parse_config(text: str) -> IgnoreConfig:
    """Parse the text of ``.mr-preflight.toml``."""
    data = tomllib.loads(text)
    return IgnoreConfig(
        paths=tuple(data.get("ignore_paths", ())),
        tokens=frozenset(data.get("ignore_tokens", ())),
    )
