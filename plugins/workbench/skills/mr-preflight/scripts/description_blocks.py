"""Own a fenced section of an MR description without touching the prose around it.

Pure: text in, text out. A section sits between two HTML comment markers,
``<!-- mr-preflight:NAME:begin -->`` and ``<!-- mr-preflight:NAME:end -->``,
each alone on its line. GitLab renders neither, so the reviewer sees only
what is between them. ``sweep`` holds the reference sweep and its waivers;
``record`` is reserved for the promotion record.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


class BlockError(ValueError):
    """The description's markers for a section are unbalanced or repeated."""


def _marker(name: str, edge: str) -> str:
    return f"<!-- mr-preflight:{name}:{edge} -->"


@dataclass(frozen=True)
class Block:
    """Where a section's body sits: ``text[start:end]`` is everything between
    the end of the begin-marker line and the start of the end-marker line."""

    start: int
    end: int


def _lines(text: str) -> list[tuple[int, str]]:
    """Each line's offset and content, line ending included.

    Split at `\\n` only. `str.splitlines` also breaks at `\\r`, form feed, NEL
    and U+2028, so a marker glued to prose by one of them would read as alone
    on its line and the prose after it would be replaced as block body.
    """
    offset = 0
    lines = []
    for line in re.findall(r"[^\n]*\n|[^\n]+", text):
        lines.append((offset, line))
        offset += len(line)
    return lines


def find_block(text: str, name: str) -> Block | None:
    """Locate section ``name``, or ``None`` when the description has none.

    Raises
    ------
    BlockError
        When the markers are unbalanced, reversed or repeated. Reading such a
        description as "no section yet" would append a second one, and the
        waivers could then sit in whichever copy is not read.
    """
    begin, end = _marker(name, "begin"), _marker(name, "end")
    starts = [offset + len(line) for offset, line in _lines(text) if line.strip() == begin]
    stops = [offset for offset, line in _lines(text) if line.strip() == end]
    if not starts and not stops:
        return None
    if len(starts) != 1 or len(stops) != 1 or stops[0] < starts[0]:
        raise BlockError(
            f"the description needs exactly one {begin} line followed by one {end} line"
        )
    return Block(start=starts[0], end=stops[0])


def replace_block(text: str, name: str, body: str) -> str:
    """Return ``text`` with section ``name``'s body replaced by ``body``.

    Every byte outside the section's body is returned unchanged. A
    description with no such section gets one appended after a blank line.
    """
    block = find_block(text, name)
    if block is None:
        # One blank line between the prose and the block, whatever the prose
        # already ends with; an empty description needs none.
        trailing = len(text) - len(text.rstrip("\n"))
        gap = "\n" * max(0, 2 - trailing) if text else ""
        section = f"{_marker(name, 'begin')}\n{body}{_marker(name, 'end')}\n"
        return text + gap + section
    return text[: block.start] + body + text[block.end :]


@dataclass(frozen=True)
class Waiver:
    """A per-MR disposition: every hit of ``token`` in ``path`` is intended."""

    token: str
    path: str
    reason: str


# `- waive TOKEN path: reason`. Either field may be backticked, which is how a
# path holding a space is written. A bare path may hold `:`, so the path ends
# at the last `: ` before the reason, never the first colon.
WAIVER = re.compile(
    r"^- waive (?P<token>`[^`]+`|\S+) (?P<path>`[^`]+`|\S+): (?P<reason>\S.*)$"
)
# A line with the exact `- waive` prefix is always held to the form: a typo
# silently read as prose would leave the author believing a hit was waived.
WAIVER_INTENT = re.compile(r"^- waive(?:\s|$)")
# A near miss on the prefix (another bullet, other spacing, other case) is
# held to it only when the rest is a valid waiver, so an English sentence
# that happens to start with the word is left alone.
NEAR_MISS = re.compile(r"^[-*+]\s*waive\s+", re.IGNORECASE)


def _starts_like_a_waiver(line: str) -> bool:
    if WAIVER_INTENT.match(line):
        return True
    return bool(NEAR_MISS.match(line) and WAIVER.match(NEAR_MISS.sub("- waive ", line, count=1)))


def waiver_lines(body: str) -> list[str]:
    """Every line of ``body`` that starts like a waiver, well formed or not,
    as written minus its line ending. What ``--update`` carries forward."""
    return [line.rstrip("\r") for line in body.split("\n") if _starts_like_a_waiver(line.strip())]


def parse_waivers(body: str) -> tuple[list[Waiver], list[str]]:
    """Read the waiver lines of a sweep section's body.

    Returns
    -------
    tuple[list[Waiver], list[str]]
        The waivers in body order, and every line that starts like a waiver
        but does not match the form.
    """
    waivers: list[Waiver] = []
    malformed: list[str] = []
    for line in waiver_lines(body):
        match = WAIVER.match(line.strip())
        if not match:
            malformed.append(line)
            continue
        waivers.append(
            Waiver(
                token=match["token"].strip("`"),
                path=match["path"].strip("`"),
                reason=match["reason"],
            )
        )
    return waivers, malformed
