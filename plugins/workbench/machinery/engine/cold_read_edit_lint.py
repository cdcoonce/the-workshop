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

``STALE_COUNT_CLAIM`` (always)
    The ``## Budget`` section states a count of new tests or criteria, the
    ``## Acceptance criteria`` items changed, and the sentence did not. Incident:
    a rewrite added criteria while "one guard, one replaced test and eight new
    tests" stayed byte-identical, and the next reader filed a blocking
    "stale count" finding, twice on one issue. A lint cannot recompute the
    true number of tests from free-prose criteria, so this detects the
    SITUATION, not the right number. Claims are ``<number> new|added|extra
    test(s)`` (TEST family) and ``<number> [acceptance] checkbox(es)|criteria|
    criterion`` (CRITERIA family) inside the Budget section, outside fenced
    and inline code; numbers are digits or ``one``..``twenty``, and a number glued
    to a hyphen, comma or period (``twenty-one``, ``1,200``, ``2.5``) is not a
    claim. "a"/"an" and "replaced" test counts are ignored. A claim present verbatim (case-
    insensitive) in both Budgets is stale when its family's delta is nonzero:
    TEST uses the change in Acceptance items mentioning ``test(s)``, CRITERIA
    uses the change in total Acceptance items. Heuristic limits: an item that
    mentions "test" is not necessarily one new test (and a test may hide in an
    item that never says so), so it can fire on a count that still holds and
    miss one that went stale; the message asks for "update or confirm". Both
    headings must exist (Budget in ``after``), else nothing is emitted. Severity
    is ``error``; under ``--expect-deletion-only`` it is ``info`` (a deletion
    applies no new text, so the number is fixed in the next edit).

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
HEADING_RE = re.compile(r"^(#{1,6})\s+\S")
ACCEPTANCE_RE = re.compile(r"^#{1,6}\s+Acceptance criteria\b", re.IGNORECASE)
BUDGET_RE = re.compile(r"^#{1,6}\s+Budget\b", re.IGNORECASE)
TEST_ITEM_RE = re.compile(r"\btests?\b", re.IGNORECASE)
_NUMBER = (r"(?<![\w.,-])(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven"
           r"|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen"
           r"|twenty)")
CLAIM_RES = {
    "test": re.compile(rf"{_NUMBER}\s+(?:new|added|extra)\s+tests?\b", re.IGNORECASE),
    "criteria": re.compile(
        rf"{_NUMBER}\s+(?:acceptance\s+)?(?:checkboxes|checkbox|criteria|criterion)\b",
        re.IGNORECASE),
}


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


def _section_span(lines: list[str], heading_rx: re.Pattern[str]) -> tuple[int, int] | None:
    """Return the 1-based ``(first, last)`` body lines of the first matching section.

    The section runs from the matching heading to the next heading of the same
    or higher level (fewer or equal ``#``), outside fenced code. ``None`` when
    no heading matches.
    """
    fenced = code_fence_mask(lines)
    start = level = None
    for i, line in enumerate(lines):
        if fenced[i]:
            continue
        m = HEADING_RE.match(line)
        if start is None:
            if m and heading_rx.match(line):
                start, level = i, len(m.group(1))
        elif m and len(m.group(1)) <= level:
            return start + 2, i
    return None if start is None else (start + 2, len(lines))


def _acceptance_deltas(before: list[str], after: list[str]) -> tuple[int, int] | None:
    """Return ``(d_all, d_test)`` over Acceptance-criteria items, after minus before."""
    counts = []
    for lines in (before, after):
        span = _section_span(lines, ACCEPTANCE_RE)
        if span is None:
            return None
        items = [t for n, t in list_items(lines) if span[0] <= n <= span[1]]
        counts.append((len(items), sum(1 for t in items if TEST_ITEM_RE.search(t))))
    return counts[1][0] - counts[0][0], counts[1][1] - counts[0][1]


def _budget_claims(lines: list[str]) -> dict[tuple[str, str], int]:
    """Map ``(family, lowercased claim text)`` to the first 1-based line it appears on."""
    span = _section_span(lines, BUDGET_RE)
    claims: dict[tuple[str, str], int] = {}
    if span is None:
        return claims
    fenced = code_fence_mask(lines)
    for n in range(span[0], span[1] + 1):
        if fenced[n - 1]:
            continue
        masked = _mask_inline_code(lines[n - 1])
        for family, rx in CLAIM_RES.items():
            for m in rx.finditer(masked):
                claims.setdefault((family, _norm(m.group(0)).lower()), n)
    return claims


def check_stale_counts(before: list[str], after: list[str],
                       deletion_only: bool = False) -> list[Finding]:
    """STALE_COUNT_CLAIM: a Budget count survived unchanged while criteria changed."""
    deltas = _acceptance_deltas(before, after)
    if deltas is None:
        return []
    d_all, d_test = deltas
    delta_for = {"test": d_test, "criteria": d_all}
    wording = {"test": "acceptance items mentioning tests",
               "criteria": "acceptance criteria items"}
    before_claims = _budget_claims(before)
    out: list[Finding] = []
    for (family, text), line in _budget_claims(after).items():
        delta = delta_for[family]
        if (family, text) not in before_claims or delta == 0:
            continue
        msg = (f'Budget states "{text}", unchanged from before, but '
               f"{wording[family]} changed by {delta:+d}; update the number "
               "or confirm it still holds")
        if deletion_only:
            msg += " (deletion edits add no new text; fix the number in the next edit)"
        out.append(Finding("STALE_COUNT_CLAIM", "info" if deletion_only else "error",
                           "after", line, msg))
    return out


def lint(before_text: str, after_text: str, deletion_only: bool = False) -> tuple[
        list[Finding], dict[str, int]]:
    """Run every check; return ``(findings, counts)``."""
    before = before_text.split("\n")
    after = after_text.split("\n")
    findings = check_fused_items(after)
    count_f, b, a = check_item_count(before, after, deletion_only)
    findings += count_f
    findings += check_stale_counts(before, after, deletion_only)
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
