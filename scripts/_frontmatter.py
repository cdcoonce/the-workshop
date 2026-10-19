"""Shared raw frontmatter extraction for the repo's two frontmatter readers.

``smoke_test._parse_frontmatter`` (a hand-rolled YAML subset: lists, nested
maps, folded scalars) and ``dev_cycle_validate`` (flat ``key: value`` scalars)
used to carry their own copies of the delimiter rules, and a fix to one
(the closing ``---`` must sit on its own line) had to be re-derived in the
other. This module owns that one raw step: find the block between the
delimiters and hand back its text. Each caller keeps a thin adapter that turns
the block into the shape it needs.

Stdlib only.
"""

from __future__ import annotations

import re

# The closing delimiter must sit on its own line (optionally followed by
# trailing whitespace, then a newline or end-of-string). Without that anchor a
# frontmatter value containing a literal ``\n---`` fragment closes the block
# early.
_CLOSING_RE = re.compile(r"\n---[ \t]*(?:\n|\Z)")


def extract_block(text: str, *, strict_open: bool = False) -> str | None:
    """Return the raw text between the opening and closing ``---`` delimiters.

    Parameters
    ----------
    text
        Full markdown text that may begin with ``---`` delimited frontmatter.
    strict_open
        When False, any text starting with ``---`` opens the block and an
        empty block is allowed (the leniency ``smoke_test`` always had). When
        True, the opening delimiter must be ``---`` plus a newline and the
        block must hold at least one character (the rule
        ``dev_cycle_validate`` always had).

    Returns
    -------
    str | None
        The block, unstripped (for the lenient form it begins with the newline
        that ends the opening line), or None when there is no closed block.
    """
    if strict_open:
        if not text.startswith("---\n"):
            return None
        closing = _CLOSING_RE.search(text, 5)
        return None if closing is None else text[4 : closing.start()]
    if not text.startswith("---"):
        return None
    closing = _CLOSING_RE.search(text, 3)
    return None if closing is None else text[3 : closing.start()]
