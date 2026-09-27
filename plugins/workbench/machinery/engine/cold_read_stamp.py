#!/usr/bin/env python3
"""Write and check a body-embedded ``/cold-read`` BUILD-verdict stamp.

A ``/cold-read`` BUILD verdict is recorded only as the ``cold-read:pass``
label. The label never goes stale, but the body it certifies and the
dependencies it was checked against both can: on 2026-09-27, all 7 queued
ragmark slices carried ``cold-read:pass`` on bodies rewritten after their last
read, and fresh reads found blocking defects in 4 of the 7. Separately, the
coverage pass hashed bodies with a shell recipe
(``gh issue view … -q .body | shasum -a 256``); ``jq`` appends a trailing
newline, so that recipe hashes the same body differently from every other way
of hashing it.

This script is the one canonical hasher and stamp reader/writer. ``stamp``
embeds a single HTML-comment line in the issue body recording the body's hash,
the integration target's ref and pinned SHA, and each ``Depends on`` issue's
state at stamp time. ``check`` re-fetches the body and reports whether it has
drifted from the stamp, or whether a dependency recorded as open has since
closed.

``gh`` is called only through the module-level ``_run_gh`` seam, always as
``gh api ...`` — never ``gh issue view`` — so tests can inject a fake runner
with no network. ``git`` is called only through the module-level ``_run_git``
seam, used solely to resolve the integration target's pinned SHA; ``check``
never calls it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

# A stamp line, loosely: used both to strip stamp lines before hashing and to
# count how many a body carries. Deliberately looser than the v1 grammar below
# so a future v2 line still counts as *a* stamp line for hashing/counting.
STAMP_LINE_RE = re.compile(r"<!-- cold-read-stamp: [^\n]* -->")

# A v1 stamp line's full grammar. Anything that is a stamp line (above) but
# does not fullmatch this is a stamp `check` must reject as unparseable.
V1_STAMP_RE = re.compile(
    r"<!-- cold-read-stamp: v1 "
    r"body=(?P<body>[0-9a-f]{12}) "
    r"target=(?P<target>\S+)@(?P<sha>[0-9a-f]{12}) "
    r"deps=(?P<deps>-|#\d+:(?:open|closed)(?:,#\d+:(?:open|closed))*) "
    r"-->"
)

# Copied verbatim from afk-agent-system `src/afk_driver/dependencies.py` so
# afk's auto-promote clause and this tool's `stamp` agree on which issues a
# body depends on.
DEPENDS_ON_RE = re.compile(
    r"(?im)^depends on:?\s+(#\d+(?:(?:[,\s]+(?:and\s+|&\s*)?|\s+and\s+|\s*&\s*)#\d+)*)"
)

_DEP_NUMBER_RE = re.compile(r"#(\d+)")


def _run_gh(args: list[str], timeout: int = 30) -> tuple[int, str, str] | None:
    """Run ``gh`` with *args*, returning ``(rc, stdout, stderr)`` or ``None``.

    Parameters
    ----------
    args : list[str]
        Arguments passed to ``gh`` (e.g. ``["api", "repos/o/r/issues/1"]``).
    timeout : int
        Seconds to wait before giving up.

    Returns
    -------
    tuple[int, str, str] | None
        The process result, or ``None`` if ``gh`` could not be invoked
        (``OSError``) or timed out.
    """
    try:
        result = subprocess.run(
            ["gh", *args], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.returncode, result.stdout, result.stderr


def _run_git(args: list[str], timeout: int = 30) -> tuple[int, str, str] | None:
    """Run ``git`` with *args*, returning ``(rc, stdout, stderr)`` or ``None``.

    Parameters
    ----------
    args : list[str]
        Arguments passed to ``git`` (e.g. ``["-C", "/repo", "rev-parse", ...]``).
    timeout : int
        Seconds to wait before giving up.

    Returns
    -------
    tuple[int, str, str] | None
        The process result, or ``None`` if ``git`` could not be invoked
        (``OSError``) or timed out.
    """
    try:
        result = subprocess.run(
            ["git", *args], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.returncode, result.stdout, result.stderr


def _line_pieces(text: str) -> list[tuple[str, str]]:
    """Split *text* into ``(content, terminator)`` pairs by the stamp rule.

    ``text`` is split on ``\\n`` only, never ``str.splitlines()`` — that method
    also treats a lone ``\\r``, U+2028, U+0085 and form feed as line breaks,
    which this format's line rule does not. Each piece before the last is a
    line ending in ``\\n``; if that piece ends in ``\\r``, the ``\\r`` belongs
    to the terminator (``\\r\\n``). The piece after the last ``\\n`` is a line
    with no terminator, but only when it is non-empty — an empty tail means
    ``text`` already ended in ``\\n`` and there is no further line.

    Parameters
    ----------
    text : str
        The text to split.

    Returns
    -------
    list[tuple[str, str]]
        ``(content, terminator)`` for every line, in order.
    """
    parts = text.split("\n")
    last = len(parts) - 1
    pieces: list[tuple[str, str]] = []
    for i, part in enumerate(parts):
        if i == last:
            if part == "":
                continue
            pieces.append((part, ""))
        elif part.endswith("\r"):
            pieces.append((part[:-1], "\r\n"))
        else:
            pieces.append((part, "\n"))
    return pieces


def _strip_stamp_lines(text: str) -> str:
    """Return *text* with every stamp line, and its terminator, removed.

    Nothing else is removed or normalized — no line-ending or whitespace
    normalization of any kind.

    Parameters
    ----------
    text : str
        The text to strip.

    Returns
    -------
    str
        *text* with every stamp line and its terminator removed.
    """
    kept = []
    for content, terminator in _line_pieces(text):
        if STAMP_LINE_RE.fullmatch(content):
            continue
        kept.append(content + terminator)
    return "".join(kept)


def _count_stamp_lines(text: str) -> int:
    """Count stamp lines in *text*, by the exact rule ``body_hash`` strips by.

    Parameters
    ----------
    text : str
        The text to scan.

    Returns
    -------
    int
        The number of stamp lines.
    """
    return sum(1 for content, _ in _line_pieces(text) if STAMP_LINE_RE.fullmatch(content))


def _stamp_line_contents(text: str) -> list[str]:
    """Return every stamp line's content (without its terminator), in order.

    Parameters
    ----------
    text : str
        The text to scan.

    Returns
    -------
    list[str]
        Each stamp line's content, in order of appearance.
    """
    return [content for content, _ in _line_pieces(text) if STAMP_LINE_RE.fullmatch(content)]


def body_hash(body: str) -> str:
    """Return the canonical sha256 hex digest of *body*, stamp lines removed.

    Parameters
    ----------
    body : str
        The issue body (or any text using the same line/stamp rules).

    Returns
    -------
    str
        The sha256 hex digest of the UTF-8 bytes of *body* with every stamp
        line (and its terminator) removed.
    """
    return hashlib.sha256(_strip_stamp_lines(body).encode("utf-8")).hexdigest()


def _parse_depends_on(body: str) -> list[int]:
    """Return the issue numbers named by every ``Depends on`` line in *body*.

    Every matching line counts (``finditer`` over the whole body, as afk
    does), numbers are deduplicated in declaration order, and ``#0`` (not
    ``> 0``) is dropped.

    Parameters
    ----------
    body : str
        The issue body to scan.

    Returns
    -------
    list[int]
        Dependency issue numbers, deduplicated, in declaration order.
    """
    numbers: list[int] = []
    seen: set[int] = set()
    for match in DEPENDS_ON_RE.finditer(body):
        for num_match in _DEP_NUMBER_RE.finditer(match.group(1)):
            number = int(num_match.group(1))
            if number > 0 and number not in seen:
                seen.add(number)
                numbers.append(number)
    return numbers


def _fetch_body(repo: str, number: int) -> tuple[str | None, str | None]:
    """Fetch issue *number*'s body from *repo* via ``gh api``.

    Never ``gh issue view``, and no ``--jq``/``-q`` — the raw JSON is parsed
    with ``json.loads`` so the exact fetched body is available untouched.

    Parameters
    ----------
    repo : str
        ``owner/name``.
    number : int
        The issue number.

    Returns
    -------
    tuple[str | None, str | None]
        ``(body, None)`` on success (``body`` is ``""`` when the field is
        JSON ``null``), or ``(None, error)`` naming the failure.
    """
    result = _run_gh(["api", f"repos/{repo}/issues/{number}"])
    if result is None:
        return None, f"gh api repos/{repo}/issues/{number} could not be invoked"
    rc, stdout, stderr = result
    if rc != 0:
        return None, f"gh api repos/{repo}/issues/{number} failed: {stderr.strip() or rc}"
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return None, f"gh api repos/{repo}/issues/{number} returned invalid JSON: {exc}"
    body = data.get("body")
    if body is None:
        body = ""
    return body, None


def _issue_state(repo: str, number: int) -> tuple[str | None, str | None]:
    """Fetch issue *number*'s ``state`` from *repo* via ``gh api``.

    Parameters
    ----------
    repo : str
        ``owner/name``.
    number : int
        The issue number.

    Returns
    -------
    tuple[str | None, str | None]
        ``(state, None)`` on success, or ``(None, error)`` naming the failure.
    """
    result = _run_gh(["api", f"repos/{repo}/issues/{number}"])
    if result is None:
        return None, f"gh api repos/{repo}/issues/{number} could not be invoked"
    rc, stdout, stderr = result
    if rc != 0:
        return None, f"gh api repos/{repo}/issues/{number} failed: {stderr.strip() or rc}"
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return None, f"gh api repos/{repo}/issues/{number} returned invalid JSON: {exc}"
    state = data.get("state")
    if state not in ("open", "closed"):
        return None, f"gh api repos/{repo}/issues/{number} response has no usable 'state'"
    return state, None


def _resolve_deps(repo: str, body: str) -> tuple[list[tuple[int, str]] | None, str | None]:
    """Parse and resolve every ``Depends on`` issue number in *body*.

    Parameters
    ----------
    repo : str
        ``owner/name`` the dependency numbers resolve against.
    body : str
        The issue body to scan for ``Depends on`` lines.

    Returns
    -------
    tuple[list[tuple[int, str]] | None, str | None]
        ``(resolved, None)`` — ``(number, state)`` pairs in declaration order
        — on success, or ``(None, error)`` naming the first lookup failure.
    """
    resolved: list[tuple[int, str]] = []
    for number in _parse_depends_on(body):
        state, err = _issue_state(repo, number)
        if err is not None:
            return None, f"dependency #{number} lookup failed: {err}"
        resolved.append((number, state))
    return resolved, None


def _format_deps(resolved: list[tuple[int, str]]) -> str:
    """Render resolved dependencies as the stamp line's ``deps=`` value.

    Parameters
    ----------
    resolved : list[tuple[int, str]]
        ``(number, state)`` pairs in declaration order.

    Returns
    -------
    str
        ``"-"`` when *resolved* is empty, else comma-separated ``#N:state``.
    """
    if not resolved:
        return "-"
    return ",".join(f"#{number}:{state}" for number, state in resolved)


def _build_stamp_line(body_h12: str, target: str, sha12: str, deps: str) -> str:
    """Assemble a v1 stamp line from its already-formatted fields.

    Parameters
    ----------
    body_h12 : str
        First 12 hex characters of the body's hash.
    target : str
        The integration-target branch name.
    sha12 : str
        First 12 hex characters of the target's commit SHA.
    deps : str
        The rendered ``deps=`` value (``-`` or comma-separated ``#N:state``).

    Returns
    -------
    str
        The complete stamp line.
    """
    return f"<!-- cold-read-stamp: v1 body={body_h12} target={target}@{sha12} deps={deps} -->"


def cmd_stamp(repo: str, issue: int, repo_dir: Path, target: str, apply: bool) -> int:
    """Compute and print a stamp line for *issue*, optionally writing it back.

    Parameters
    ----------
    repo : str
        ``owner/name``.
    issue : int
        The issue number to stamp.
    repo_dir : Path
        Local checkout of *repo*, used only to resolve *target*'s pinned SHA.
    target : str
        The integration-target branch name.
    apply : bool
        When true, PATCH the computed stamp into the issue body and verify
        the round trip.

    Returns
    -------
    int
        0 on success; 2 on any ``gh``/``git`` failure, including a
        dependency lookup failure or a failed round-trip verification.
    """
    body, err = _fetch_body(repo, issue)
    if err is not None:
        print(f"ERROR: {err}", file=sys.stderr)
        return 2

    resolved, err = _resolve_deps(repo, body)
    if err is not None:
        print(f"ERROR: {err}", file=sys.stderr)
        return 2
    deps = _format_deps(resolved)

    git_result = _run_git(["-C", str(repo_dir), "rev-parse", "--verify", f"origin/{target}"])
    if git_result is None or git_result[0] != 0:
        stderr = git_result[2] if git_result is not None else "git could not be invoked"
        print(f"ERROR: git rev-parse --verify origin/{target} failed: {stderr.strip()}", file=sys.stderr)
        return 2
    sha12 = git_result[1].strip()[:12]

    stripped = _strip_stamp_lines(body)
    b_text = stripped if stripped.endswith("\n") else stripped + "\n"

    body_h12 = body_hash(b_text)[:12]
    stamp_line = _build_stamp_line(body_h12, target, sha12, deps)
    print(stamp_line)

    if not apply:
        return 0

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="", delete=False
        ) as handle:
            handle.write(b_text)
            handle.write(stamp_line)
            handle.write("\n")
            tmp_path = handle.name

        patch_result = _run_gh(
            ["api", "-X", "PATCH", f"repos/{repo}/issues/{issue}", "-F", f"body=@{tmp_path}"]
        )
        if patch_result is None or patch_result[0] != 0:
            stderr = patch_result[2] if patch_result is not None else "gh could not be invoked"
            print(f"ERROR: gh api PATCH repos/{repo}/issues/{issue} failed: {stderr.strip()}", file=sys.stderr)
            return 2

        refetched, err = _fetch_body(repo, issue)
        if err is not None:
            print(f"ERROR: re-fetch after apply failed: {err}", file=sys.stderr)
            return 2

        if body_hash(refetched) != body_hash(b_text):
            print("ERROR: re-fetched body hash does not match the applied body", file=sys.stderr)
            return 2

        refetched_stamps = _stamp_line_contents(refetched)
        if len(refetched_stamps) != 1 or refetched_stamps[0] != stamp_line:
            print("ERROR: re-fetched body does not contain exactly one matching stamp line", file=sys.stderr)
            return 2
    finally:
        if tmp_path is not None:
            Path(tmp_path).unlink(missing_ok=True)

    return 0


def cmd_check(repo: str, issue: int) -> int:
    """Check *issue*'s stamp against its current body and dependency states.

    Makes no ``git`` call — the stamp's ``target`` field is informational and
    never compared.

    Parameters
    ----------
    repo : str
        ``owner/name``.
    issue : int
        The issue number to check.

    Returns
    -------
    int
        0 when the stamp is fresh; 1 when the body changed or an open
        dependency has closed (reasons printed to stdout); 2 on a fetch
        failure, a missing/duplicate/unparseable stamp line, or a
        dependency-lookup failure (cause named on stderr).
    """
    body, err = _fetch_body(repo, issue)
    if err is not None:
        print(f"ERROR: {err}", file=sys.stderr)
        return 2

    stamps = _stamp_line_contents(body)
    if len(stamps) == 0:
        print("ERROR: no cold-read-stamp line found in body", file=sys.stderr)
        return 2
    if len(stamps) > 1:
        print(f"ERROR: {len(stamps)} cold-read-stamp lines found in body; expected exactly one", file=sys.stderr)
        return 2

    match = V1_STAMP_RE.fullmatch(stamps[0])
    if match is None:
        print(f"ERROR: cold-read-stamp line does not parse as v1: {stamps[0]!r}", file=sys.stderr)
        return 2

    stamp_body_h12 = match.group("body")
    deps_field = match.group("deps")
    stamp_deps: list[tuple[int, str]] = []
    if deps_field != "-":
        for part in deps_field.split(","):
            number = int(part[1:part.index(":")])
            state = part[part.index(":") + 1 :]
            stamp_deps.append((number, state))

    reasons: list[str] = []
    if body_hash(body)[:12] != stamp_body_h12:
        reasons.append("body changed since stamp")

    for number, state in stamp_deps:
        if state != "open":
            continue
        current_state, err = _issue_state(repo, number)
        if err is not None:
            print(f"ERROR: dependency #{number} lookup failed: {err}", file=sys.stderr)
            return 2
        if current_state == "closed":
            reasons.append(f"dependency #{number} closed since stamp; re-read against shipped code")

    if reasons:
        for reason in reasons:
            print(reason)
        return 1

    return 0


def _main(argv: list[str] | None) -> int:
    parser = argparse.ArgumentParser(
        description="Write and check a body-embedded /cold-read stamp with one canonical hasher."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    stamp_parser = subparsers.add_parser("stamp", help="Compute (and optionally write) a stamp line.")
    stamp_parser.add_argument("--repo", required=True, help="OWNER/REPO the issue lives in.")
    stamp_parser.add_argument("--issue", required=True, type=int, help="Issue number to stamp.")
    stamp_parser.add_argument("--repo-dir", required=True, type=Path, help="Local checkout used to resolve --target.")
    stamp_parser.add_argument("--target", required=True, help="Integration-target branch name.")
    stamp_parser.add_argument("--apply", action="store_true", help="Write the stamp back to the issue body.")

    check_parser = subparsers.add_parser("check", help="Check an issue's existing stamp.")
    check_parser.add_argument("--repo", required=True, help="OWNER/REPO the issue lives in.")
    check_parser.add_argument("--issue", required=True, type=int, help="Issue number to check.")

    args = parser.parse_args(argv)

    if args.command == "stamp":
        return cmd_stamp(args.repo, args.issue, args.repo_dir, args.target, args.apply)
    return cmd_check(args.repo, args.issue)


def main(argv: list[str] | None = None) -> int:
    """Wraps ``_main`` so any uncaught exception exits 2, never crashes."""
    try:
        return _main(argv)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - last-resort guard; report and exit 2
        print(f"ERROR: cold_read_stamp crashed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
