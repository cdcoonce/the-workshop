#!/usr/bin/env python3
"""Read the ``/cold-read`` gate's machine-readable ledger off an issue.

Incident: a census of 188 gated issues had to guess each read's verdict and
the number of reads from free-text ``## Cold read`` comments, and 18 rows
disagreed between two passes over the same issues. No comment recorded what a
read cost, or whether a finding was later re-found by the independent
mutation (teeth) pass. Each verdict comment now ends with one invisible
HTML-comment ledger line, and this script is the one parser and aggregator.

Ledger line (a verdict comment, ``## Cold read — <verdict>``, ends with
exactly one)::

    <!-- cold-read-ledger: v=1 read=<int> verdict=<BUILD|REWRITE|NOT-DISPATCH-READY|BUILD-exempt> body=<12 hex> blocking=<int> rule_born=<int|na> advisory=<int> mutants=<int|na> survivors=<int|na> tokens=<int|na> seconds=<int|na> -->

Tokens are ``key=value`` separated by single spaces; a value never contains a
space. Required keys: ``v`` (must be ``1``), ``read``, ``verdict``, ``body``
(the 12-hex body hash ``cold_read_stamp.py`` prints), ``blocking``. Every
other key is optional on read, and an unknown extra key is kept and ignored.
``tokens`` and ``seconds`` come from the reader subagent's Agent-tool result
(its token count and duration); a writer records ``na`` when unavailable and
never omits the key. ``na`` parses to ``None``.

Post-merge record (one comment, written when the slice's PR merges)::

    <!-- cold-read-ledger: v=1 event=landed pr=<int> source_lines=<int> test_lines=<int> teeth_gaps=<int> teeth_gaps_raised=<int> -->

``teeth_gaps`` is the number of test gaps the independent mutation pass found
after the BUILD verdict; ``teeth_gaps_raised`` is how many of those a prior
cold read had already raised (blocking or advisory); ``source_lines`` and
``test_lines`` are the production and test lines the PR changed. All five are
required.

Parsing rules: a ledger line is a whole line (``<!--`` form only, nothing
else on the line) outside fenced code blocks, so a comment that quotes the
format in a fence does not ledger itself. A malformed line (missing required
key, non-integer where an integer is required, unknown ``v``, bad verdict,
bad body hash, a token with no ``=``, a repeated key, an unknown ``event``)
is returned as a record with an ``error`` key and never raises. The key name
``error`` is therefore reserved and may not appear in a ledger line.

Usage::

    cold_read_ledger.py --repo OWNER/NAME --issue N [--issue M ...]
                        [--comments-json FILE] [--json]

Without ``--comments-json`` each issue's comments are fetched with
``gh issue view N --repo OWNER/NAME --json comments``. With it, the file holds
one issue's comments (either ``gh``'s ``{"comments": [...]}`` object or a bare
list) and exactly one ``--issue`` is allowed. The default output is a compact
per-issue table plus a totals footer; ``--json`` prints one JSON document
instead.

Exit codes: 0 success, 2 usage / fetch / unreadable-input error. A malformed
ledger line is data, not an error: it is counted and reported, and the exit
code stays 0. ``gh`` is called only through the module-level
``_fetch_comments`` seam, so tests inject a fake with no network. Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

VERDICTS = frozenset({"BUILD", "REWRITE", "NOT-DISPATCH-READY", "BUILD-exempt"})
SUPPORTED_VERSION = 1

# Required on a verdict (read) line; every other known key is optional.
READ_REQUIRED = ("v", "read", "verdict", "body", "blocking")
# Optional int keys on a read line. ``na`` is allowed for all but ``advisory``.
READ_OPTIONAL_INT = ("advisory",)
READ_OPTIONAL_INT_OR_NA = ("rule_born", "mutants", "survivors", "tokens", "seconds")
LANDED_REQUIRED_INT = ("pr", "source_lines", "test_lines", "teeth_gaps", "teeth_gaps_raised")

LEDGER_LINE_RE = re.compile(r"^\s*<!--\s+cold-read-ledger:\s*(?P<fields>.*?)\s*-->\s*$")
FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
INT_RE = re.compile(r"[0-9]+")
BODY_RE = re.compile(r"[0-9a-f]{12}")
VERDICT_TITLE = "## Cold read"


class FetchError(Exception):
    """Raised by ``_fetch_comments`` when an issue's comments cannot be read."""


def _error(raw: str, message: str) -> dict:
    return {"error": message, "raw": raw}


def _as_int(value: str) -> int | None:
    return int(value) if INT_RE.fullmatch(value) else None


def _parse_fields(fields: str) -> dict[str, str] | str:
    """Split ``key=value`` tokens; return the dict, or an error message string."""
    pairs: dict[str, str] = {}
    for token in fields.split():
        key, eq, value = token.partition("=")
        if not eq or not key:
            return f"token {token!r} is not key=value"
        if key == "error":
            return "key 'error' is reserved for malformed-line records"
        if key in pairs:
            return f"repeated key {key!r}"
        pairs[key] = value
    return pairs


def _int_or_na(pairs: dict[str, str], key: str, allow_na: bool) -> tuple[int | None, str | None]:
    """Parse optional ``key``; return (value, error). Absent and ``na`` are None."""
    if key not in pairs:
        return None, None
    raw = pairs[key]
    if allow_na and raw == "na":
        return None, None
    value = _as_int(raw)
    if value is None:
        return None, f"{key} must be an integer{' or na' if allow_na else ''}, got {raw!r}"
    return value, None


def _parse_one(raw: str, fields: str) -> dict:
    """Turn one ledger line's field text into a record (or an ``error`` record)."""
    pairs = _parse_fields(fields)
    if isinstance(pairs, str):
        return _error(raw, pairs)
    if "v" not in pairs:
        return _error(raw, "missing required key 'v'")
    if _as_int(pairs["v"]) != SUPPORTED_VERSION:
        return _error(raw, f"v: unsupported version {pairs['v']!r}")
    if "event" in pairs:
        return _parse_event(raw, pairs)
    for key in READ_REQUIRED:
        if key not in pairs:
            return _error(raw, f"missing required key {key!r}")
    record: dict = dict(pairs)
    record["v"] = SUPPORTED_VERSION
    for key in ("read", "blocking"):
        value = _as_int(pairs[key])
        if value is None:
            return _error(raw, f"{key} must be an integer, got {pairs[key]!r}")
        record[key] = value
    if pairs["verdict"] not in VERDICTS:
        return _error(raw, f"verdict {pairs['verdict']!r} is not one of {sorted(VERDICTS)}")
    if not BODY_RE.fullmatch(pairs["body"]):
        return _error(raw, f"body must be 12 lowercase hex characters, got {pairs['body']!r}")
    for allow_na, keys in ((False, READ_OPTIONAL_INT), (True, READ_OPTIONAL_INT_OR_NA)):
        for key in keys:
            value, problem = _int_or_na(pairs, key, allow_na)
            if problem:
                return _error(raw, problem)
            record[key] = value
    return record


def _parse_event(raw: str, pairs: dict[str, str]) -> dict:
    """Parse a ``event=...`` record. Only ``landed`` is defined."""
    if pairs["event"] != "landed":
        return _error(raw, f"event {pairs['event']!r} is not a known event")
    record: dict = dict(pairs)
    record["v"] = SUPPORTED_VERSION
    for key in LANDED_REQUIRED_INT:
        if key not in pairs:
            return _error(raw, f"missing required key {key!r}")
        value = _as_int(pairs[key])
        if value is None:
            return _error(raw, f"{key} must be an integer, got {pairs[key]!r}")
        record[key] = value
    return record


def parse_ledger_lines(text: str) -> list[dict]:
    """Parse every ledger comment line in a comment body.

    Parameters
    ----------
    text : str
        One comment's body.

    Returns
    -------
    list of dict
        One record per ledger line, in order. A valid verdict line carries
        ``v``, ``read``, ``verdict``, ``body``, ``blocking``, ``advisory``,
        ``rule_born``, ``mutants``, ``survivors``, ``tokens`` and ``seconds``
        (``None`` for ``na`` or an absent optional key) plus any unknown extra
        keys as strings. A valid ``event=landed`` line carries ``event`` and
        its five integer fields. A malformed line is ``{"error": ..., "raw":
        ...}``. Never raises.
    """
    records: list[dict] = []
    fence: tuple[str, int] | None = None
    for raw in text.splitlines():
        marker = FENCE_RE.match(raw)
        if fence is None:
            if marker:
                fence = (marker.group(1)[0], len(marker.group(1)))
                continue
        else:
            # Only a marker of the same character, at least as long and with no
            # info string closes the fence; anything else is quoted content.
            if (marker and marker.group(1)[0] == fence[0]
                    and len(marker.group(1)) >= fence[1] and not marker.group(2).strip()):
                fence = None
            continue
        match = LEDGER_LINE_RE.match(raw)
        if match:
            records.append(_parse_one(raw.strip(), match.group("fields")))
    return records


def _is_verdict_comment(body: str) -> bool:
    return body.lstrip().startswith(VERDICT_TITLE)


def _total(values: list[int | None]) -> tuple[int | None, int]:
    """Sum the ints; ``None`` when every value is na. Also count the na values."""
    present = [v for v in values if v is not None]
    return (sum(present) if present else None), len(values) - len(present)


def summarize(comments: list[dict]) -> dict:
    """Aggregate one issue's gate ledger from its comments.

    Parameters
    ----------
    comments : list of dict
        Comments as ``gh issue view N --json comments`` returns them; each
        needs ``body`` and ``createdAt`` (ISO-8601 UTC, ordered as text).

    Returns
    -------
    dict
        ``reads`` (verdict comments, i.e. those whose first line starts with
        ``## Cold read``); ``unledgered`` (verdict comments with no valid
        ledger line, so a census can see its own blind spot); parallel
        per-read lists ``verdicts``, ``bodies``, ``blocking``, ``rule_born``,
        ``advisory``, ``mutants``, ``survivors``, ``tokens``, ``seconds``
        (``None`` for an ``na`` or for an unledgered read); ``tokens_total``
        and ``seconds_total`` (``None`` when every value is na) with
        ``tokens_na`` and ``seconds_na`` (an unledgered read counts as na);
        ``multi_ledger`` (verdict comments carrying more than one valid line,
        of which the first is used); ``errors`` (one entry per malformed
        ledger line in a verdict comment); and ``landed`` (the latest
        ``event=landed`` record from any comment, else ``None``).
    """
    ordered = sorted(comments, key=lambda c: c.get("createdAt") or "")
    per_read: dict[str, list] = {
        k: [] for k in ("verdicts", "bodies", "blocking", "rule_born", "advisory",
                        "mutants", "survivors", "tokens", "seconds")
    }
    field_for = {"verdicts": "verdict", "bodies": "body"}
    errors: list[dict] = []
    unledgered = 0
    multi_ledger = 0
    landed: dict | None = None
    reads = 0
    for comment in ordered:
        body = comment.get("body") or ""
        records = parse_ledger_lines(body)
        for rec in records:
            if rec.get("event") == "landed" and "error" not in rec:
                landed = rec
        if not _is_verdict_comment(body):
            continue
        reads += 1
        errors.extend({"read_index": reads, **r} for r in records if "error" in r)
        valid = [r for r in records if "error" not in r and "event" not in r]
        if len(valid) > 1:
            multi_ledger += 1
        chosen = valid[0] if valid else None
        if chosen is None:
            unledgered += 1
        for key, values in per_read.items():
            values.append(chosen.get(field_for.get(key, key)) if chosen else None)
    tokens_total, tokens_na = _total(per_read["tokens"])
    seconds_total, seconds_na = _total(per_read["seconds"])
    return {
        "reads": reads,
        "unledgered": unledgered,
        **per_read,
        "tokens_total": tokens_total,
        "tokens_na": tokens_na,
        "seconds_total": seconds_total,
        "seconds_na": seconds_na,
        "multi_ledger": multi_ledger,
        "errors": errors,
        "landed": landed,
    }


def _fetch_comments(repo: str, issue: int) -> list[dict]:
    """Seam: fetch an issue's comments with ``gh`` (tests monkeypatch)."""
    cmd = ["gh", "issue", "view", str(issue), "--repo", repo, "--json", "comments"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except OSError as e:
        raise FetchError(f"cannot run gh: {e}") from e
    if proc.returncode != 0:
        raise FetchError(f"gh issue view {issue} failed: {proc.stderr.strip()}")
    try:
        return _comments_from_json(json.loads(proc.stdout))
    except (json.JSONDecodeError, ValueError) as e:
        raise FetchError(f"gh issue view {issue} returned unreadable output: {e}") from e


def _comments_from_json(data: object) -> list[dict]:
    """Validate ``gh``'s object (or a bare list) and return the comment list."""
    comments = data.get("comments") if isinstance(data, dict) else data
    if not isinstance(comments, list):
        raise ValueError("expected a comment list or an object with a 'comments' list")
    for c in comments:
        if not isinstance(c, dict) or not isinstance(c.get("body", ""), str):
            raise ValueError("every comment must be an object with a string 'body'")
    return comments


def _read_text(path: str) -> str:
    """Seam: read *path* as UTF-8 text (tests may monkeypatch)."""
    return Path(path).read_text(encoding="utf-8")


def _cell(values: list, sep: str = ",") -> str:
    return sep.join("-" if v is None else str(v) for v in values) or "-"


def format_table(rows: list[tuple[int, dict]], totals: dict) -> list[str]:
    """Render the compact per-issue table and the totals footer."""
    header = ("issue", "reads", "unledgered", "verdicts", "blocking", "tokens", "landed")
    body = []
    for issue, s in rows:
        landed = f"PR#{s['landed']['pr']}" if s["landed"] else "-"
        tokens = "-" if s["tokens_total"] is None else str(s["tokens_total"])
        body.append((f"#{issue}", str(s["reads"]), str(s["unledgered"]),
                     _cell(s["verdicts"], ">"), _cell(s["blocking"]), tokens, landed))
    widths = [max(len(r[i]) for r in [header, *body]) for i in range(len(header))]
    lines = ["  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip() for r in [header, *body]]
    tokens = "none" if totals["tokens_total"] is None else totals["tokens_total"]
    lines.append(
        f"Totals: issues={totals['issues']} reads={totals['reads']} "
        f"unledgered={totals['unledgered']} tokens={tokens} (na={totals['tokens_na']})"
    )
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--repo", required=True, help="OWNER/NAME")
    parser.add_argument("--issue", required=True, type=int, action="append",
                        help="issue number (repeatable)")
    parser.add_argument("--comments-json", help="read one issue's comments from FILE, "
                        "not from gh (needs exactly one --issue)")
    parser.add_argument("--json", action="store_true", help="print one JSON document")
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0
    if args.comments_json and len(args.issue) != 1:
        print("cold_read_ledger: --comments-json needs exactly one --issue", file=sys.stderr)
        return 2
    rows: list[tuple[int, dict]] = []
    for issue in args.issue:
        try:
            if args.comments_json:
                comments = _comments_from_json(json.loads(_read_text(args.comments_json)))
            else:
                comments = _fetch_comments(args.repo, issue)
        except (OSError, UnicodeDecodeError, ValueError, FetchError) as e:
            print(f"cold_read_ledger: cannot read input for #{issue}: {e}", file=sys.stderr)
            return 2
        rows.append((issue, summarize(comments)))
    tokens_total, tokens_na = _total([v for _, s in rows for v in s["tokens"]])
    totals = {
        "issues": len(rows),
        "reads": sum(s["reads"] for _, s in rows),
        "unledgered": sum(s["unledgered"] for _, s in rows),
        "tokens_total": tokens_total,
        "tokens_na": tokens_na,
    }
    if args.json:
        print(json.dumps({"repo": args.repo,
                          "issues": [{"issue": i, **s} for i, s in rows],
                          "totals": totals}))
    else:
        for out in format_table(rows, totals):
            print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
