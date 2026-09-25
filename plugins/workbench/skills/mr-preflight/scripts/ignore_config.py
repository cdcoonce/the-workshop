"""The committed ``.mr-preflight.toml``: noise a repo ignores once, for good.

Pure: no git, no filesystem. The caller reads the file from the head tree and
hands its text here, so every rule is testable against a string.
"""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
from functools import cache

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

    ``*``, ``?`` and ``[...]`` (negated by ``!`` or ``^``) stay inside one
    segment, so ``*.md`` is the root's Markdown only; a whole ``**`` segment
    spans any number of them. A
    leading or middle ``**`` may match none, a trailing one at least one, so
    ``docs/adr/**`` is what is inside ``docs/adr``, never a file of that name.
    Memoised on positions, since each ``**`` tries every split.
    """
    segments = [_negate_like_git(segment) for segment in pattern]

    @cache
    def match(p: int, q: int) -> bool:
        if p == len(segments):
            return q == len(path)
        if segments[p] == "**":
            if p + 1 == len(segments):
                return q < len(path)
            return any(match(p + 1, skip) for skip in range(q, len(path) + 1))
        return q < len(path) and fnmatchcase(path[q], segments[p]) and match(p + 1, q + 1)

    return match(0, 0)


def _negate_like_git(segment: str) -> str:
    """Spell git's ``[^...]`` negation as ``fnmatch``'s ``[!...]``.

    ``fnmatch`` reads a leading ``^`` in a class as a literal, so ``[^0-9]``
    would ignore exactly the paths git keeps. Classes are delimited the way
    ``fnmatch`` delimits them: a ``]`` right after the opening (or after its
    negation) is literal, and an unclosed ``[`` is a literal ``[``.
    """
    out = []
    i = 0
    while i < len(segment):
        if segment[i] != "[":
            out.append(segment[i])
            i += 1
            continue
        j = i + 1
        if j < len(segment) and segment[j] in "!^":
            j += 1
        if j < len(segment) and segment[j] == "]":
            j += 1
        while j < len(segment) and segment[j] != "]":
            j += 1
        if j >= len(segment):
            out.append("[")
            i += 1
            continue
        body = segment[i + 1 : j]
        out.append("[" + ("!" + body[1:] if body.startswith("^") else body) + "]")
        i = j + 1
    return "".join(out)


def parse_config(text: str) -> IgnoreConfig:
    """Parse the text of ``.mr-preflight.toml``.

    Raises
    ------
    ConfigError
        On invalid TOML, an unknown key (a misspelt one would otherwise ignore
        nothing, silently), or a value that is not a list of strings (a bare
        string would otherwise iterate into one-character globs).
    """
    # Imported here, not at the top: `tomllib` is Python 3.11+, and a repo
    # with no config must sweep on whatever `python3` `create-mr` finds.
    try:
        import tomllib
    except ModuleNotFoundError as error:
        raise ConfigError("reading it needs Python 3.11 or newer (tomllib)") from error

    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"malformed TOML: {error}") from error
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
