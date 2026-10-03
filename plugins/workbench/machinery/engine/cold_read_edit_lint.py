#!/usr/bin/env python3
"""Lint a cold-read spec (Markdown) edit: compare a body before and after.

Incident: while rewriting a ``/cold-read`` spec in a published GitHub issue,
the conductor deleted a trailing sentence from a list item using an ``Edit``
whose replacement was empty. The deleted span included the newline, so item 5
fused onto the end of the bullet above (``...(no new error code).5.
**Read-only...``). The published body rendered that way and five independent
readers passed over it. This script is the deterministic check the conductor
runs on the body BEFORE and AFTER a rewrite edit.

Usage::

    cold_read_edit_lint.py --before FILE --after FILE
                           [--expect-deletion-only] [--json]

Exit codes: 0 clean, 1 findings (at least one ``error``), 2 usage/input error.
``info`` findings (``TRUNCATED_LINE``, a negative ``ITEM_COUNT_DELTA``) are
printed but do not change the exit code.

Checks
------
``FUSED_ITEM`` (always)
    A list marker glued to the end of the previous sentence, mid-line,
    outside fenced code and inline code spans. Two shapes:
    a numbered marker ``[)`:]\\d{1,2}\\. \\S`` or ``(?<=[^\\d\\s.]\\.)\\d{1,2}\\. \\S``,
    and a checkbox marker ``[.)`:]- \\[[ xX]\\]``. Tradeoff: a ``.`` terminator
    only counts when the character before it is not a digit or whitespace or
    another dot, so version-like text (``v1.2. 3 files``, ``3.5. Next``) does
    not fire. The cost is a missed fusion when the sentence itself ends in a
    digit (``costs $5.5. Next``); that is accepted because those shapes are
    far commoner in prose than real fusions. Numbers are capped at two digits
    for the same reason. Plain ``- text`` fusions are not detected.

``ITEM_COUNT_DELTA`` (always)
    List items (``-``, ``- [ ]``, ``- [x]``, ``N.``, optionally indented)
    outside fenced code, before vs after. Always printed as info; it is an
    error only under ``--expect-deletion-only`` when the delta is positive.

``--expect-deletion-only`` adds:

``ADDED_LINE`` / ``ADDED_ITEM``
    Every non-blank line of ``after`` (whitespace-normalized) must match a
    line of ``before`` as a subsequence, in order, greedily. A line that is
    a strict prefix of its matching before-line is ``TRUNCATED_LINE`` (info).
    Anything else is ``ADDED_LINE`` (error); if it looks like a list item it
    is also reported as ``ADDED_ITEM``. A fused line is not a prefix of any
    before line, so it surfaces here too.

``DANGLING_REFERENCE``
    Tokens are backticked spans and ``#NNN`` issue refs. A token is
    *defined* by a deleted line when its first occurrence in ``before``
    lies in deleted text (a wholly unmatched line, or the removed tail of a
    truncated line). If a defined token still appears in ``after`` that is
    reported with the ``after`` line. Heuristic limits, honestly: it only
    sees literal tokens, not prose such as "see the section above" or
    "the second option"; a token legitimately re-introduced elsewhere in
    ``after`` and one pointing at deleted content look the same; greedy
    alignment can mis-assign deleted lines when ``before`` has duplicates.
    Treat a clean result as "no known dangling shape", not proof.

Every finding is followed by ``CONTEXT`` lines (``sed -n``-style) from the
file the finding points at. No network, stdlib only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

CONTEXT = 3

FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
LIST_ITEM_RE = re.compile(r"^\s*(?:-\s|\d+\.\s)")
LIST_MARKER_RE = re.compile(r"^\s*(?:- \[[ xX]\]\s*|-\s+|\d+\.\s+)")
INLINE_CODE_RE = re.compile(r"`+[^`\n]*`+")
FUSED_NUMBERED_RE = re.compile(r"(?:(?<=[)`:])|(?<=[^\d\s.]\.))\d{1,2}\. \S")
FUSED_CHECKBOX_RE = re.compile(r"(?<=[.)`:])- \[[ xX]\]")
TOKEN_RE = re.compile(r"`([^`\n]+)`|(#\d+)(?!\d)")


@dataclass(frozen=True)
class Finding:
    """One lint result. ``line`` is 1-based in ``file`` ('before'/'after')."""

    code: str
    severity: str  # "error" | "info"
    file: str
    line: int
    message: str


def _norm(line: str) -> str:
    return " ".join(line.split())


def code_fence_mask(lines: list[str]) -> list[bool]:
    """Return per-line flags: True when the line is inside (or is) a fence."""
    mask: list[bool] = []
    fence: tuple[str, int] | None = None
    for line in lines:
        m = FENCE_RE.match(line)
        if fence is None:
            if m:
                fence = (m.group(1)[0], len(m.group(1)))
                mask.append(True)
            else:
                mask.append(False)
        else:
            mask.append(True)
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= fence[1] \
                    and not m.group(2).strip():
                fence = None
    return mask


def _mask_inline_code(line: str) -> str:
    """Blank out inline-code contents but keep the backtick delimiters."""
    def repl(m: re.Match[str]) -> str:
        s = m.group(0)
        n = len(s) - len(s.lstrip("`"))
        k = len(s) - len(s.rstrip("`"))
        return s[:n] + "x" * (len(s) - n - k) + s[len(s) - k:]
    return INLINE_CODE_RE.sub(repl, line)


def check_fused_items(lines: list[str]) -> list[Finding]:
    """FUSED_ITEM: a list marker glued mid-line onto the previous sentence."""
    out: list[Finding] = []
    fenced = code_fence_mask(lines)
    for i, line in enumerate(lines):
        if fenced[i]:
            continue
        masked = _mask_inline_code(line)
        for rx in (FUSED_NUMBERED_RE, FUSED_CHECKBOX_RE):
            m = rx.search(masked)
            if m:
                out.append(Finding(
                    "FUSED_ITEM", "error", "after", i + 1,
                    f"list marker fused onto previous text at column {m.start() + 1}",
                ))
                break
    return out


def list_items(lines: list[str]) -> list[tuple[int, str]]:
    """Return ``(1-based line, normalized text)`` for list items outside fences."""
    fenced = code_fence_mask(lines)
    return [
        (i + 1, _norm(LIST_MARKER_RE.sub("", line, count=1)))
        for i, line in enumerate(lines)
        if not fenced[i] and LIST_ITEM_RE.match(line)
    ]


def check_item_count(before: list[str], after: list[str],
                     deletion_only: bool = False) -> tuple[list[Finding], int, int]:
    """ITEM_COUNT_DELTA. Returns ``(findings, before_count, after_count)``."""
    b, a = len(list_items(before)), len(list_items(after))
    delta = a - b
    sev = "error" if (deletion_only and delta > 0) else "info"
    msg = f"list items before={b} after={a} delta={delta:+d}"
    return [Finding("ITEM_COUNT_DELTA", sev, "after", 1, msg)], b, a


def align_deletion(before: list[str], after: list[str]) -> tuple[
        list[tuple[int, int, bool]], list[int]]:
    """Greedy subsequence alignment of non-blank normalized lines.

    Returns ``(matches, added)``: ``matches`` is ``(after_idx, before_idx,
    truncated)`` over raw line indices; ``added`` lists after indices that
    matched nothing.
    """
    bl = [(i, _norm(x)) for i, x in enumerate(before) if x.strip()]
    matches: list[tuple[int, int, bool]] = []
    added: list[int] = []
    cur = 0
    for ai, raw in enumerate(after):
        if not raw.strip():
            continue
        text = _norm(raw)
        for j in range(cur, len(bl)):
            bi, btext = bl[j]
            if btext == text:
                matches.append((ai, bi, False))
                cur = j + 1
                break
            if btext.startswith(text):
                matches.append((ai, bi, True))
                cur = j + 1
                break
        else:
            added.append(ai)
    return matches, added


def check_deletion_only(before: list[str], after: list[str]) -> list[Finding]:
    """ADDED_LINE, ADDED_ITEM and TRUNCATED_LINE."""
    matches, added = align_deletion(before, after)
    out: list[Finding] = []
    for ai, bi, trunc in matches:
        if trunc:
            out.append(Finding(
                "TRUNCATED_LINE", "info", "after", ai + 1,
                f"line is a prefix-shortened form of before line {bi + 1}"))
    for ai in added:
        out.append(Finding("ADDED_LINE", "error", "after", ai + 1,
                           "line not found in before (not a deletion)"))
        if LIST_ITEM_RE.match(after[ai]):
            out.append(Finding("ADDED_ITEM", "error", "after", ai + 1,
                               "list item not present in before"))
    return out


def _tokens(text: str) -> list[tuple[int, str]]:
    return [(m.start(), m.group(1) or m.group(2)) for m in TOKEN_RE.finditer(text)]


def check_dangling(before: list[str], after: list[str]) -> list[Finding]:
    """DANGLING_REFERENCE: token defined only in deleted text, still in after."""
    matches, _ = align_deletion(before, after)
    kept = {bi: (_norm(after[ai]), trunc) for ai, bi, trunc in matches}
    defined: set[str] = set()
    seen: set[str] = set()
    for bi, raw in enumerate(before):
        if not raw.strip():
            continue
        text = _norm(raw)
        if bi in kept:
            retained = kept[bi][0] if kept[bi][1] else text
            cut = len(retained)
        else:
            cut = 0
        for pos, tok in _tokens(text):
            if tok in seen:
                continue
            seen.add(tok)
            if pos >= cut:
                defined.add(tok)
    out: list[Finding] = []
    for ai, raw in enumerate(after):
        for _, tok in _tokens(_norm(raw)):
            if tok in defined:
                out.append(Finding(
                    "DANGLING_REFERENCE", "error", "after", ai + 1,
                    f"token {tok!r} was defined in deleted text but still appears here"))
    return out


def lint(before_text: str, after_text: str, deletion_only: bool = False) -> tuple[
        list[Finding], dict[str, int]]:
    """Run every check; return ``(findings, counts)``."""
    before = before_text.split("\n")
    after = after_text.split("\n")
    findings = check_fused_items(after)
    count_f, b, a = check_item_count(before, after, deletion_only)
    findings += count_f
    if deletion_only:
        findings += check_deletion_only(before, after)
        findings += check_dangling(before, after)
    return findings, {"before_items": b, "after_items": a, "delta": a - b}


def context_lines(lines: list[str], line: int, width: int = CONTEXT) -> list[str]:
    """``sed -n``-style window of *width* lines each side, marking the hit."""
    lo = max(1, line - width)
    hi = min(len(lines), line + width)
    return [f"{'>' if n == line else ' '}{n:5d}| {lines[n - 1]}" for n in range(lo, hi + 1)]


def _read_text(path: str) -> str:
    """Seam: read *path* as UTF-8 text (tests may monkeypatch)."""
    return Path(path).read_text(encoding="utf-8")


def format_report(findings: list[Finding], before: list[str], after: list[str]) -> list[str]:
    lines: list[str] = []
    for f in findings:
        lines.append(f"{f.severity.upper()} {f.code} {f.file}:{f.line}: {f.message}")
        src = after if f.file == "after" else before
        if f.code != "ITEM_COUNT_DELTA":
            lines.extend(context_lines(src, f.line))
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--before", required=True, help="Markdown body before the edit")
    parser.add_argument("--after", required=True, help="Markdown body after the edit")
    parser.add_argument("--expect-deletion-only", action="store_true",
                        help="after must be a pure deletion of before")
    parser.add_argument("--json", action="store_true",
                        help="also print one JSON summary line")
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0
    try:
        before_text = _read_text(args.before)
        after_text = _read_text(args.after)
    except (OSError, UnicodeDecodeError) as e:
        print(f"cold_read_edit_lint: cannot read input: {e}", file=sys.stderr)
        return 2
    findings, counts = lint(before_text, after_text, args.expect_deletion_only)
    for line in format_report(findings, before_text.split("\n"), after_text.split("\n")):
        print(line)
    errors = [f for f in findings if f.severity == "error"]
    if args.json:
        print(json.dumps({"clean": not errors, **counts,
                          "findings": [asdict(f) for f in findings]}))
    if not errors:
        print("OK: no findings")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
