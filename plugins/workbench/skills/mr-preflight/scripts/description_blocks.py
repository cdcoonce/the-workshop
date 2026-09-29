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
    """A per-MR disposition: every hit of ``token`` in ``path`` is intended.

    A ``path`` of ``None`` is the token-wide form: ``token`` is intended in
    every path.
    """

    token: str
    path: str | None
    reason: str


# `- waive TOKEN path: reason`. Either field may be backticked, which is how a
# path holding a space is written. A bare path may hold `:`, so the path ends
# at the last `: ` before the reason, never the first colon.
WAIVER = re.compile(
    r"^- waive (?P<token>`[^`]+`|\S+) (?P<path>`[^`]+`|\S+): (?P<reason>\S.*)$"
)
# `- waive TOKEN: reason`, no path: the token is intended everywhere. The colon
# sits right after the token, which a path-form line never has (a space
# follows its token), so the two forms cannot be confused, and the reason may
# hold colons of its own.
WAIVER_TOKEN_WIDE = re.compile(r"^- waive (?P<token>`[^`]+`|[^\s:`]+): (?P<reason>\S.*)$")
# A line with the exact `- waive` prefix is always held to the form: a typo
# silently read as prose would leave the author believing a hit was waived.
WAIVER_INTENT = re.compile(r"^- waive(?:\s|$)")
# A near miss on the prefix (another bullet, other spacing, other case) is
# held to it only when the rest is a valid waiver, so an English sentence
# that happens to start with the word is left alone.
NEAR_MISS = re.compile(r"^[-*+]\s*waive\s+", re.IGNORECASE)


def _match_waiver(line: str) -> Waiver | None:
    """The waiver ``line`` spells exactly, in either form, or ``None``."""
    wide = WAIVER_TOKEN_WIDE.match(line)
    if wide:
        return Waiver(token=wide["token"].strip("`"), path=None, reason=wide["reason"])
    match = WAIVER.match(line)
    if match:
        return Waiver(
            token=match["token"].strip("`"),
            path=match["path"].strip("`"),
            reason=match["reason"],
        )
    return None


def _starts_like_a_waiver(line: str) -> bool:
    if WAIVER_INTENT.match(line):
        return True
    return bool(NEAR_MISS.match(line) and _match_waiver(NEAR_MISS.sub("- waive ", line, count=1)))


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
        waiver = _match_waiver(line.strip())
        if waiver is None:
            malformed.append(line)
        else:
            waivers.append(waiver)
    return waivers, malformed


FENCE = re.compile(r"^\s*(```|~~~)")


def stray_waivers(text: str, name: str) -> list[str]:
    """Well-formed waiver lines written outside section ``name``'s body.

    Only the block is read for waivers, so these waive nothing; the author
    likely put them under an ordinary heading. Lines inside a code fence,
    indented, or not spelled as a waiver are quotes or prose and are left out.

    Raises
    ------
    BlockError
        When the markers for ``name`` are unbalanced or repeated.
    """
    block = find_block(text, name)
    stray = []
    fenced = False
    for offset, raw in _lines(text):
        line = raw.rstrip("\r\n")
        if FENCE.match(line):
            fenced = not fenced
        elif not fenced and _match_waiver(line):
            if block is None or not block.start <= offset < block.end:
                stray.append(line)
    return stray
