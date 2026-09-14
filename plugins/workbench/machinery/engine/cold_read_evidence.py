#!/usr/bin/env python3
"""Deterministic collector for /cold-read detector 5 — unresolvable evidence.

Detector 5 requires every path, ref, SHA and note a spec names to resolve, in
either role it plays: evidence (cited as proof of existing state) or
destination (named as where the slice will create something new). Today that
is "one unpiped command each" for every such token, run by hand. This script
extracts those tokens from an issue body and resolves each against the
target repo's git object store at a pinned ref (never the working tree),
plus GitHub for issue/PR/repo refs and a vault (via graphmark) for
wikilinks, and returns a compact table so the /cold-read subagent verifies
only the rows the resolver could not trust outright.

Read-only against the target repo: repo content is read through
``git cat-file`` / ``git ls-tree`` / ``git show`` / ``git grep`` /
``git merge-base`` only, never executed. Wikilink resolution DOES load
vault code as data: ``graph_cli.build`` (via graphmark) reads
``<vault>/.vault/config/vault_scope.py`` to resolve the vault's scope
config, exactly as ``wrap_up_audit.py`` does, scope-pinned to
``--vault-root``. That one file is imported, not executed as an action —
no vault mutation ever happens — but it is not accurate to say "no vault
code is ever executed" when a caller supplies an untrusted vault root.

``gh`` is called through the module-level ``_run_gh`` seam so tests can
inject a fake runner with no network.

Corpus review (2026-09-14, 41 real cold-read issues, pre-cold-read
revisions): an earlier BLOCKING/JUDGMENT/OK severity model scored ~2%
precision on BLOCKING (166 rows, ~3-4 real) — mostly path-resolution
false positives a text-only resolver cannot rule out (subtree-relative
paths, cross-repo citations, branch names, prose-only line citations,
pytest node ids, and more). No rule set makes an authoritative BLOCKING
trustworthy, so the model changed: **a hint the resolver is confident
about becomes OK (trusted, no re-check); everything else becomes CHECK
(the reader verifies with one command before it counts as a finding)**.
The resolver is asymmetric by design — trusted in the direction where a
positive match is strong evidence (a path really does exist at the
pinned ref), never trusted to declare a negative authoritative.
"""

from __future__ import annotations

import argparse
import builtins
import json
import keyword
import os
import posixpath
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from vault_utils import WIKILINK_CAPTURE_RE, find_vault_root  # noqa: E402

VERDICT_EXIT_CODES = {"ALL_RESOLVED": 0, "CHECK_REQUIRED": 1, "INCOMPLETE": 2}

# --------------------------------------------------------------------------- #
# extraction regexes
# --------------------------------------------------------------------------- #

HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
FENCE_OPEN_RE = re.compile(r"^(`{3,}|~{3,})\s*\S*\s*$")
ISSUE_URL_RE = re.compile(r"https://github\.com/([\w.-]+/[\w.-]+?)/(?:issues|pull)/(\d+)\b")
OWNER_REPO_ISSUE_RE = re.compile(r"(?<![\w/.#])([\w.-]+/[\w.-]+)#([1-9]\d*)\b")
BARE_ISSUE_RE = re.compile(r"(?<![\w#/.])#([1-9]\d*)\b")
# A short identifier immediately followed by #N, where the identifier is a
# single segment (no "/") — the corpus shorthand `bms#235`. Applied only
# after owner/repo#N and URL forms have already been extracted and masked,
# so it never fires on those. `(?<![\w/])` keeps it off the tail of a real
# owner/repo pair whose masking left residual characters, and off `#0`
# (matched by requiring [1-9]\d*, same as the other issue-ref patterns).
ALIAS_ISSUE_RE = re.compile(r"(?<![\w/.#])([A-Za-z][\w-]*)#([1-9]\d*)\b")
SHA_CANDIDATE_RE = re.compile(r"\b[0-9a-fA-F]{7,40}\b")

PATH_EXTENSIONS = (
    ".py", ".md", ".toml", ".json", ".yml", ".yaml", ".sh", ".sql",
    ".txt", ".cfg", ".ini", ".ts", ".tsx", ".js",
)
# A bare extension with nothing else: a leading dot, no slash, no other dot
# (`.py`, `.sql`) — a real citation never names evidence this way; it is a
# fragment of prose ("rename the .py file") the extractor must not treat as
# a path. Checked before the general PATH rule.
BARE_EXTENSION_RE = re.compile(r"^\.[A-Za-z0-9]{1,10}$")
WHITESPACE_RE = re.compile(r"\s")
TEMPLATE_RE = re.compile(r"<[^<>]*>")
BRACE_RE = re.compile(r"\{[^{}]*\}")
GLOB_CHARS = frozenset("*?[")
# Trailing punctuation a sentence commonly appends to a citation: strip
# before classifying so `norms.py:171,` and `secret_scan.py:57-64.` resolve
# like their bare forms.
TRAILING_PUNCT_RE = re.compile(r"[.,;:)]+$")
# `path#L1-L2` / `path#L1` (GitHub permalink line-anchor style).
HASH_L_LINE_RE = re.compile(r"^(?P<path>.+)#L(?P<start>\d+)(?:-L?(?P<end>\d+))?$")
# `path:line:col` — the column is ignored, matched before the simpler
# single-number PATH_LINE_RE so it isn't misread as a `path:line` with the
# rest trailing.
PATH_LINE_COL_RE = re.compile(r"^(?P<path>.+):(?P<start>\d+):(?P<col>\d+)$")
PATH_LINE_RE = re.compile(r"^(?P<path>.+):(?P<start>\d+)(?:-(?P<end>\d+))?$")
# pytest node id: `tests/x.py::test_y` (optionally `[param]`) -> PATH only.
PYTEST_NODE_RE = re.compile(r"^(?P<path>[\w./-]+\.py)::[\w:\[\]-]+$")
SYMBOL_RE = re.compile(r"^[A-Za-z_][\w.]*$")
HEX_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")
SHA_LETTERS = frozenset("abcdefABCDEF")
# Prose line citations near a backtick token in the same sentence:
# "lines 316-346" or "L316-346" / "L316-L346".
PROSE_LINE_RE = re.compile(r"\blines?\s+(\d+)(?:\s*-\s*(\d+))?\b|\bL(\d+)-L?(\d+)\b", re.IGNORECASE)
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n{2,}")

MAX_LINE_TEXT_ROWS = 3
MAX_LINE_TEXT_CHARS = 160
MAX_AMBIGUOUS_CANDIDATES = 5


# --------------------------------------------------------------------------- #
# classify_token — the backtick-token rule table (order matters)
# --------------------------------------------------------------------------- #

def _has_known_extension(s: str) -> bool:
    return any(s.lower().endswith(ext) for ext in PATH_EXTENSIONS)


def _is_sha_shaped(token: str) -> bool:
    if not HEX_RE.match(token):
        return False
    has_digit = any(c.isdigit() for c in token)
    has_letter = any(c in SHA_LETTERS for c in token)
    return has_digit and has_letter


_BUILTIN_NAMES = frozenset(dir(builtins))


def _is_keyword_or_builtin(token: str) -> bool:
    """True for a bare Python keyword or builtin name (`return`, `len`,
    `None`) — never evidence, always noise if extracted as a bare SYMBOL.
    Only applied to non-dotted tokens: `os.path` legitimately dots through
    a builtin-shadowing-looking segment and must still resolve normally."""
    return keyword.iskeyword(token) or token in _BUILTIN_NAMES


def normalize_backtick_token(raw: str) -> str:
    """Strip trailing sentence punctuation a citation commonly picks up
    (`norms.py:171,` -> `norms.py:171`). Applied before classification so
    every downstream rule sees the clean form."""
    return TRAILING_PUNCT_RE.sub("", raw)


def classify_token(token: str) -> str:
    """Classify one backticked token per the corpus rule table. First match wins."""
    if WHITESPACE_RE.search(token):
        return "SKIP_COMMAND"
    if token.startswith("-"):
        return "SKIP_FLAG"
    if token.startswith("~/") or token.startswith("/"):
        return "LOCAL"
    if TEMPLATE_RE.search(token):
        return "TEMPLATED"
    if BRACE_RE.search(token) and '"' not in token and "'" not in token:
        # A brace placeholder in a filename convention (`day-{day:04d}.md`,
        # `{name}.toml`) is TEMPLATED like `<...>`. Excluded when the token
        # carries a quote character: that is a code/string-literal snippet
        # (`f"{x}"`, `{"check": POLICY}`), not a path convention, and must
        # fall through to SYMBOL/SKIP_OTHER instead. A token with actual
        # whitespace (`{"check": POLICY}`) is already routed to
        # SKIP_COMMAND above this check, so the quote guard here is only
        # load-bearing for the no-whitespace case (`f"{x}"`).
        return "TEMPLATED"
    if any(c in GLOB_CHARS for c in token):
        return "GLOB"
    if BARE_EXTENSION_RE.match(token):
        return "SKIP_BARE_EXTENSION"
    m = PATH_LINE_COL_RE.match(token) or HASH_L_LINE_RE.match(token) or PATH_LINE_RE.match(token)
    if m:
        path_part = m.group("path")
        if "/" in path_part or _has_known_extension(path_part):
            return "PATH_LINE"
    if "/" in token or _has_known_extension(token) or token.endswith("/"):
        return "PATH"
    if _is_sha_shaped(token):
        return "SHA"
    if SYMBOL_RE.match(token):
        if "." not in token and _is_keyword_or_builtin(token):
            return "SKIP_KEYWORD"
        return "SYMBOL"
    return "SKIP_OTHER"


def parse_path_line_token(token: str) -> tuple[str, int, int | None] | None:
    """Parse a PATH_LINE-classified token into (path, start, end),
    normalizing the three citation shapes classify_token recognizes as
    PATH_LINE: `path:N(-M)`, `path#LN(-LM)`, and `path:N:col` (column
    dropped). Returns None if the token doesn't actually parse (shouldn't
    happen for a token classify_token already called PATH_LINE)."""
    m = PATH_LINE_COL_RE.match(token)
    if m:
        return m.group("path"), int(m.group("start")), None
    m = HASH_L_LINE_RE.match(token)
    if m:
        end = int(m.group("end")) if m.group("end") else None
        return m.group("path"), int(m.group("start")), end
    m = PATH_LINE_RE.match(token)
    if m:
        end = int(m.group("end")) if m.group("end") else None
        return m.group("path"), int(m.group("start")), end
    return None


def normalize_path_segments(path: str) -> tuple[str, bool]:
    """Normalize `.` and `..` segments in a repo-relative path. Returns
    (normalized_path, escapes_root) — escapes_root is True when a leading
    `..` would walk above the repo root (`src/../../README.md`), which the
    caller reports as OUTSIDE_REPO rather than silently resolving it (or
    worse, handing it to git as a pathspec)."""
    parts = path.split("/")
    out: list[str] = []
    for part in parts:
        if part in ("", "."):
            continue
        if part == "..":
            if out:
                out.pop()
            else:
                return path, True
        else:
            out.append(part)
    return "/".join(out), False


# --------------------------------------------------------------------------- #
# masking — fenced code, HTML comments, indented code blocks
# --------------------------------------------------------------------------- #

def _blank_line(line: str) -> str:
    return ""


def _mask_fenced_code(text: str) -> str:
    """Blank fenced code block lines (delimiters included), preserving line
    offsets. Supports ``` and ~~~ fences of 3+ characters; a fence closes
    only on a run of the SAME character at least as long as the opener
    (CommonMark), so a nested shorter/different-character run inside a
    longer fence does not prematurely close it."""
    lines = text.split("\n")
    out: list[str] = []
    in_fence = False
    fence_char = ""
    fence_len = 0
    for line in lines:
        stripped = line.strip()
        if not in_fence:
            m = FENCE_OPEN_RE.match(stripped)
            if m:
                marker = m.group(1)
                in_fence = True
                fence_char = marker[0]
                fence_len = len(marker)
                out.append("")
                continue
            out.append(line)
        else:
            # Closing fence: a run of fence_char, length >= fence_len, and
            # nothing else on the line (CommonMark: only whitespace allowed
            # around a closing fence).
            run = 0
            for c in stripped:
                if c == fence_char:
                    run += 1
                else:
                    break
            if run >= fence_len and run == len(stripped):
                in_fence = False
                out.append("")
                continue
            out.append("")
    return "\n".join(out)


def _mask_html_comments(text: str) -> str:
    """Blank ``<!-- ... -->`` spans, preserving line offsets. ``<details>``
    content is deliberately NOT masked here — it renders, and a citation
    inside it is real evidence."""
    return HTML_COMMENT_RE.sub(lambda m: _blank(m.group(0)), text)


def _mask_indented_code_blocks(text: str) -> str:
    """Approximate CommonMark's indented-code-block rule: a line indented
    4+ spaces (or starting with a tab), directly following a blank line,
    starts an indented code block that continues through further
    4+-indented (or blank) lines. This is a conservative approximation —
    it does not track list-item continuation context (CommonMark exempts
    an indented line that is really a continuation of a list item's own
    hanging indent), so a deeply indented continuation line inside a list
    can be masked when it should not be. Tested both ways."""
    lines = text.split("\n")
    out: list[str] = []
    in_block = False
    prev_blank = True  # start-of-document counts as preceded by "blank"
    for line in lines:
        stripped = line.strip()
        is_blank = stripped == ""
        is_indented = line.startswith("    ") or line.startswith("\t")
        if not in_block and is_indented and prev_blank and not is_blank:
            in_block = True
        elif in_block and not is_indented and not is_blank:
            in_block = False
        out.append("" if in_block else line)
        prev_blank = is_blank
    return "\n".join(out)


def _mask_all(body: str) -> str:
    masked = _mask_fenced_code(body)
    masked = _mask_html_comments(masked)
    masked = _mask_indented_code_blocks(masked)
    return masked


# --------------------------------------------------------------------------- #
# backtick-span extraction — CommonMark run-length pairing
# --------------------------------------------------------------------------- #

def find_backtick_spans(text: str) -> list[tuple[int, int, str]]:
    """(start, end, content) for each single-line code span, pairing
    backtick runs by CommonMark's rule: a run of N backticks opens; it
    closes only at the next run of EXACTLY N backticks on the same line. A
    run with no same-length partner on its line is not a delimiter at all
    — skip past just that run and keep scanning; it must never swallow (or
    shift the position of) a later, properly paired span."""
    spans: list[tuple[int, int, str]] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] != "`":
            i += 1
            continue
        j = i
        while j < n and text[j] == "`":
            j += 1
        run_len = j - i
        line_end = text.find("\n", j)
        if line_end == -1:
            line_end = n
        k = j
        close_start = -1
        while k < line_end:
            if text[k] == "`":
                m = k
                while m < line_end and text[m] == "`":
                    m += 1
                if m - k == run_len:
                    close_start = k
                    break
                k = m
            else:
                k += 1
        if close_start == -1:
            i = j
            continue
        spans.append((i, close_start + run_len, text[j:close_start]))
        i = close_start + run_len
    return spans


# --------------------------------------------------------------------------- #
# extraction
# --------------------------------------------------------------------------- #

def _line_no(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _mask_span(text: str, start: int, end: int) -> str:
    """Replace text[start:end] with spaces of the same length (newlines preserved)."""
    span = text[start:end]
    blanked = "".join(c if c == "\n" else " " for c in span)
    return text[:start] + blanked + text[end:]


def _blank(s: str) -> str:
    return "".join(c if c == "\n" else " " for c in s)


def _sentence_spans(text: str) -> list[tuple[int, int]]:
    """(start, end) character ranges for each sentence, by the same
    boundary SENTENCE_SPLIT_RE uses to join them back."""
    spans: list[tuple[int, int]] = []
    pos = 0
    for m in SENTENCE_SPLIT_RE.finditer(text):
        spans.append((pos, m.start()))
        pos = m.end()
    spans.append((pos, len(text)))
    return spans


def extract_tokens(body: str) -> list[dict[str, Any]]:
    """Extract evidence tokens per the corpus extraction rules, in body order.

    Each token dict carries ``text``, ``cls``, ``line``, and — for
    ``ISSUE_REF``/``UNKNOWN_REPO_ALIAS`` — ``repo``/``alias`` and
    ``number``.
    """
    masked = _mask_all(body)
    tokens: list[dict[str, Any]] = []
    backtick_tokens: list[dict[str, Any]] = []  # (start, end, cls, text) for prose-line pairing

    # 1. backtick spans (CommonMark-paired, normalized, classified via the
    #    rule table)
    plain = masked
    for start, end, raw_content in find_backtick_spans(masked):
        content = normalize_backtick_token(raw_content)
        if not content:
            continue
        pytest_m = PYTEST_NODE_RE.match(content)
        if pytest_m:
            content = pytest_m.group("path")
        norm_path, escapes = _maybe_normalize_path_component(content)
        line = _line_no(masked, start)
        if escapes:
            tokens.append({"text": content, "cls": "OUTSIDE_REPO_TOKEN", "line": line})
            plain = _mask_span(plain, start, end)
            continue
        content = norm_path
        cls = classify_token(content)
        tok = {"text": content, "cls": cls, "line": line, "_start": start, "_end": end}
        tokens.append(tok)
        if cls in ("PATH", "PATH_LINE", "SYMBOL"):
            backtick_tokens.append(tok)
        plain = _mask_span(plain, start, end)

    # 2. prose line citations ("lines 316-346", "L316-346") paired with the
    #    nearest preceding PATH/PATH_LINE/SYMBOL backtick token in the same
    #    sentence. A PATH token gets synthesized into PATH_LINE evidence; a
    #    SYMBOL token gets a PROSE_LINE_CITATION row (the resolver cannot
    #    verify the range actually contains the symbol from text alone).
    for sent_start, sent_end in _sentence_spans(masked):
        sentence = masked[sent_start:sent_end]
        prose_matches = list(PROSE_LINE_RE.finditer(sentence))
        if not prose_matches:
            continue
        candidates = [t for t in backtick_tokens if sent_start <= t["_start"] < sent_end]
        if not candidates:
            continue
        anchor = candidates[-1]
        for pm in prose_matches:
            if pm.group(1) is not None:
                start_n, end_n = int(pm.group(1)), (int(pm.group(2)) if pm.group(2) else None)
            else:
                start_n, end_n = int(pm.group(3)), int(pm.group(4))
            line = _line_no(masked, sent_start + pm.start())
            if anchor["cls"] == "PATH":
                pl_text = f"{anchor['text']}:{start_n}" + (f"-{end_n}" if end_n else "")
                tokens.append({"text": pl_text, "cls": "PATH_LINE", "line": line, "_prose": True})
            elif anchor["cls"] in ("PATH_LINE", "SYMBOL"):
                tokens.append({
                    "text": f"{anchor['text']} (lines {start_n}" + (f"-{end_n})" if end_n else ")"),
                    "cls": "PROSE_LINE_CITATION", "line": line,
                    "symbol": anchor["text"] if anchor["cls"] == "SYMBOL" else None,
                })

    # 3. wikilinks
    for m in WIKILINK_CAPTURE_RE.finditer(plain):
        raw = m.group(1)
        target = raw.split("|")[0].split("#")[0].strip()
        if not target:
            continue
        line = _line_no(plain, m.start())
        tokens.append({"text": target, "cls": "WIKILINK", "line": line})
    plain = WIKILINK_CAPTURE_RE.sub(lambda m: _blank(m.group(0)), plain)

    # 4. issue/PR refs — URL form, then owner/repo#N, then bare #N, then
    #    alias#N shorthand, masking as we go so later passes never
    #    re-match already-claimed text.
    for m in ISSUE_URL_RE.finditer(plain):
        line = _line_no(plain, m.start())
        tokens.append({
            "text": m.group(0), "cls": "ISSUE_REF", "line": line,
            "repo": m.group(1), "number": int(m.group(2)),
        })
    plain = ISSUE_URL_RE.sub(lambda m: _blank(m.group(0)), plain)

    for m in OWNER_REPO_ISSUE_RE.finditer(plain):
        line = _line_no(plain, m.start())
        tokens.append({
            "text": m.group(0), "cls": "ISSUE_REF", "line": line,
            "repo": m.group(1), "number": int(m.group(2)),
        })
    plain = OWNER_REPO_ISSUE_RE.sub(lambda m: _blank(m.group(0)), plain)

    for m in BARE_ISSUE_RE.finditer(plain):
        line = _line_no(plain, m.start())
        tokens.append({
            "text": m.group(0), "cls": "ISSUE_REF", "line": line,
            "repo": None, "number": int(m.group(1)),
        })
    plain = BARE_ISSUE_RE.sub(lambda m: _blank(m.group(0)), plain)

    for m in ALIAS_ISSUE_RE.finditer(plain):
        line = _line_no(plain, m.start())
        tokens.append({
            "text": m.group(0), "cls": "UNKNOWN_REPO_ALIAS", "line": line,
            "alias": m.group(1), "number": int(m.group(2)),
        })
    plain = ALIAS_ISSUE_RE.sub(lambda m: _blank(m.group(0)), plain)

    # 5. bare commit SHAs
    for m in SHA_CANDIDATE_RE.finditer(plain):
        candidate = m.group(0)
        if _is_sha_shaped(candidate):
            line = _line_no(plain, m.start())
            tokens.append({"text": candidate, "cls": "SHA", "line": line})

    for t in tokens:
        t.pop("_start", None)
        t.pop("_end", None)

    tokens.sort(key=lambda t: t["line"])
    return _dedupe_tokens(tokens)


def _maybe_normalize_path_component(content: str) -> tuple[str, bool]:
    """For a token that looks path-ish (contains `/` or `..`), normalize
    `.`/`..` segments and report whether it escapes the repo root. Tokens
    with no `/` at all are returned unchanged (nothing to normalize). A
    LOCAL-shaped token (`~/...`, or an absolute `/...`) is left untouched —
    normalize_path_segments treats a leading `/` as nothing to anchor to,
    which would silently turn an absolute path into a relative-looking one
    (and reclassify it away from LOCAL) instead of just cleaning `..`."""
    if "/" not in content or content.startswith("/") or content.startswith("~/"):
        return content, False
    # Only normalize the path PORTION for a :line / #L / ::test suffix form;
    # reuse the same parse the classifier will use.
    base = content
    suffix = ""
    m = PATH_LINE_COL_RE.match(content) or HASH_L_LINE_RE.match(content) or PATH_LINE_RE.match(content)
    if m and ("/" in m.group("path") or _has_known_extension(m.group("path"))):
        base = m.group("path")
        suffix = content[len(base):]
    if ".." not in base and not re.search(r"(^|/)\.(/|$)", base):
        return content, False
    normalized, escapes = normalize_path_segments(base)
    if escapes:
        return content, True
    return normalized + suffix, False


def _dedupe_tokens(tokens: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    out: list[dict[str, Any]] = []
    for t in tokens:
        key = (t["cls"], t["text"], t.get("repo"), t.get("alias"))
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out


# --------------------------------------------------------------------------- #
# git plumbing — reads the object store at <ref>, never the working tree
# --------------------------------------------------------------------------- #

def _run_git(repo_dir: Path, args: list[str], timeout: int = 30) -> tuple[int, str, str] | None:
    env = dict(os.environ)
    # Quote every pathspec literally: a cited path beginning with `:`
    # (rare, but real in some corpora) would otherwise be read as git
    # pathspec magic instead of a literal path.
    env["GIT_LITERAL_PATHSPECS"] = "1"
    try:
        result = subprocess.run(
            ["git", *args], cwd=repo_dir, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout, env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.returncode, result.stdout, result.stderr


def _file_exists(repo_dir: Path, ref: str, path: str) -> bool:
    """True only for a real blob (file) at <ref>:<path>. `cat-file -e`
    alone is not enough: it succeeds for ANY valid object at that path,
    tree (directory) included, so a bare directory citation without a
    trailing slash (`docs/design`, no `/`) would otherwise register as a
    file match instead of falling through to the directory check —
    exactly the confusion PATH_LINE's DIRECTORY_NOT_FILE check exists to
    report. `cat-file -t` and checking the type is "blob" is the fix."""
    result = _run_git(repo_dir, ["cat-file", "-t", f"{ref}:{path}"])
    return result is not None and result[0] == 0 and result[1].strip() == "blob"


def _dir_exists(repo_dir: Path, ref: str, dir_path: str) -> bool:
    dir_path = dir_path.rstrip("/") + "/"
    result = _run_git(repo_dir, ["ls-tree", ref, "--", dir_path])
    return result is not None and result[0] == 0 and result[1].strip() != ""


_GENERIC_EXTENSION_RE = re.compile(r"\.[A-Za-z0-9]{1,10}$")


def _is_directory_shaped(token: str) -> bool:
    """True when *token* names a directory rather than a file.

    Either it ends with ``/`` outright, or its last path segment carries no
    file-extension-shaped suffix at all (a generic ``.ext`` check, not the
    PATH classifier's known-extension list — REFERENCED_ONLY is about
    "does this look like a file", not "is this a recognized file type").
    """
    if token.endswith("/"):
        return True
    basename = token.rsplit("/", 1)[-1]
    return not _GENERIC_EXTENSION_RE.search(basename)


def _last_segment_name(token: str) -> str:
    return token.rstrip("/").rsplit("/", 1)[-1]


def _referenced_only_detail(repo_dir: Path, ref: str, token: str) -> str | None:
    """The REFERENCED_ONLY evidence line, or None if *token*'s name is never
    quoted as a string literal (single or double) in tracked files at *ref*.

    Quoted literals only — ``-F`` fixed-string search for ``"<name>"`` and
    ``'<name>'`` specifically, never a bare substring search. A bare
    substring would also demote an unrelated directory whose name merely
    appears inside a longer identifier (``chronicle`` inside
    ``write_chronicle``), which is exactly the false-recall failure this
    rule must not introduce.
    """
    name = _last_segment_name(token)
    if not name:
        return None
    result = _run_git(
        repo_dir, ["grep", "-n", "-F", "-e", f'"{name}"', "-e", f"'{name}'", ref],
    )
    if result is None or result[0] != 0:
        return None
    lines = [line for line in result[1].splitlines() if line]
    if not lines:
        return None
    parts = lines[0].split(":", 3)
    if len(parts) == 4:
        _rev, path, lineno, text = parts
        detail = f"{path}:{lineno}: {text.strip()}"
    else:
        detail = lines[0]
    return detail[:MAX_LINE_TEXT_CHARS]


# --------------------------------------------------------------------------- #
# path-suffix resolution — one tree listing per invocation, cached
# --------------------------------------------------------------------------- #

class TreeIndex:
    """Every tracked path at <ref>: the flat file list (for suffix
    matching) plus basename indexes for files and the directories implied
    by their parents. Built once per ``collect()`` call (only when a
    no-slash, or otherwise unresolved, PATH/PATH_LINE token needs it) and
    reused for every such token, never one ``git`` call per token."""

    __slots__ = ("files", "dirs", "files_by_basename", "dirs_by_basename")

    def __init__(
        self, files: list[str], dirs: list[str],
        files_by_basename: dict[str, list[str]], dirs_by_basename: dict[str, list[str]],
    ) -> None:
        self.files = files
        self.dirs = dirs
        self.files_by_basename = files_by_basename
        self.dirs_by_basename = dirs_by_basename


def _build_tree_index(repo_dir: Path, ref: str) -> TreeIndex | None:
    result = _run_git(repo_dir, ["ls-tree", "-r", "-z", "--name-only", ref])
    if result is None or result[0] != 0:
        return None
    files = [p for p in result[1].split("\0") if p]

    files_by_basename: dict[str, list[str]] = {}
    dirs_by_basename: dict[str, list[str]] = {}
    seen_dirs: set[str] = set()
    for f in files:
        name = f.rsplit("/", 1)[-1]
        files_by_basename.setdefault(name, []).append(f)
        parts = f.split("/")
        for i in range(1, len(parts)):
            d = "/".join(parts[:i])
            if d in seen_dirs:
                continue
            seen_dirs.add(d)
            dirs_by_basename.setdefault(parts[i - 1], []).append(d)

    for lst in files_by_basename.values():
        lst.sort()
    for lst in dirs_by_basename.values():
        lst.sort()
    return TreeIndex(files, sorted(seen_dirs), files_by_basename, dirs_by_basename)


def _suffix_matches(paths: list[str], suffix: str) -> list[str]:
    """Segment-boundary suffix match: *suffix* must align with whole path
    segments (`sync_manager.py` matches `.../engine/sync_manager.py` but
    `_manager.py` does not)."""
    needle = "/" + suffix if not suffix.startswith("/") else suffix
    return [p for p in paths if p == suffix or p.endswith(needle)]


def _resolve_by_suffix(
    tree_index: TreeIndex, name: str, is_dir_shaped: bool,
) -> tuple[str, Any] | None:
    """Generalizes the basename match to any segment-boundary suffix —
    `engine/sync_manager.py` matches `plugins/foo/machinery/engine/
    sync_manager.py`, not just a bare basename. Returns (result,
    detail_payload) or None for zero matches (fall through unchanged).

    ``detail_payload`` is the single matching path for RESOLVES_BY_SUFFIX,
    or ``(total_count, candidate_paths[:5])`` for AMBIGUOUS_SUFFIX.
    """
    if "/" not in name:
        table = tree_index.dirs_by_basename if is_dir_shaped else tree_index.files_by_basename
        matches = table.get(name) or []
    else:
        pool = tree_index.dirs if is_dir_shaped else tree_index.files
        matches = _suffix_matches(pool, name)
    if not matches:
        return None
    if len(matches) == 1:
        return "RESOLVES_BY_SUFFIX", matches[0]
    return "AMBIGUOUS_SUFFIX", (len(matches), matches[:MAX_AMBIGUOUS_CANDIDATES])


def _format_ambiguous_detail(count: int, candidates: list[str]) -> str:
    return f"{count} candidates: " + ", ".join(candidates)


def _suffix_eligible(token: str) -> str | None:
    """The name/suffix to search for, or None if *token* is empty."""
    bare = token.rstrip("/") if token.endswith("/") else token
    return bare or None


def _path_kind_at_ref(repo_dir: Path, ref: str, path: str) -> str | None:
    """'file', 'dir', or None (neither exists at <ref>)."""
    if _file_exists(repo_dir, ref, path):
        return "file"
    if _dir_exists(repo_dir, ref, path):
        return "dir"
    return None


def _resolve_path(
    repo_dir: Path, ref: str, token: str, tree_index: TreeIndex | None = None,
) -> tuple[str, str | None]:
    """Returns (result, detail). detail is set for REFERENCED_ONLY and
    AMBIGUOUS_SUFFIX (a formatted string); None otherwise."""
    is_dir_token = token.endswith("/")
    bare = token.rstrip("/")

    if not is_dir_token and _file_exists(repo_dir, ref, token):
        return "RESOLVES", None
    if bare and _dir_exists(repo_dir, ref, bare):
        return "RESOLVES", None

    if tree_index is not None:
        name = _suffix_eligible(token)
        if name is not None:
            suffix_result = _resolve_by_suffix(tree_index, name, _is_directory_shaped(token))
            if suffix_result is not None:
                result, payload = suffix_result
                if result == "AMBIGUOUS_SUFFIX":
                    count, candidates = payload
                    return result, _format_ambiguous_detail(count, candidates)
                return result, payload  # RESOLVES_BY_SUFFIX: payload is the full path

    # Neither a file nor a directory exists at <ref>, and no suffix match.
    # A directory-shaped token gets one more check before falling to
    # PARENT_ONLY/UNRESOLVED: is its name established as a quoted string
    # literal in code, typically a runtime `.mkdir()` target that git's
    # tree never records? That is real evidence the path is correct, not
    # absent.
    if _is_directory_shaped(token):
        detail = _referenced_only_detail(repo_dir, ref, bare)
        if detail is not None:
            return "REFERENCED_ONLY", detail
    parent = posixpath.dirname(bare)
    if parent and _dir_exists(repo_dir, ref, parent):
        return "PARENT_ONLY", None
    return "UNRESOLVED", None


def _read_ref_file_lines(repo_dir: Path, ref: str, path: str) -> tuple[list[str] | None, bool]:
    """Returns (lines, is_binary). lines is None if the show itself failed;
    is_binary is True when the content contains a NUL byte (a real binary
    file misread as text under errors="replace" corrupts, but never
    crashes, the decode — NUL detection catches the case cleanly)."""
    result = _run_git(repo_dir, ["show", f"{ref}:{path}"])
    if result is None or result[0] != 0:
        return None, False
    if "\x00" in result[1]:
        return None, True
    return result[1].splitlines(), False


def _extract_line_result(
    repo_dir: Path, ref: str, path: str, start: int, end: int | None, resolved_result: str,
) -> tuple[str, list[str] | None, str | None]:
    """Shared by the direct-path and suffix-matched RESOLVES cases: slice
    the requested line range out of *path* at *ref*, or report
    LINE_OUT_OF_RANGE / BINARY_FILE. ``resolved_result`` is the success
    bucket name to report (RESOLVES or RESOLVES_BY_SUFFIX)."""
    kind = _path_kind_at_ref(repo_dir, ref, path)
    if kind == "dir":
        return "DIRECTORY_NOT_FILE", None, None
    lines, is_binary = _read_ref_file_lines(repo_dir, ref, path)
    if is_binary:
        return "BINARY_FILE", None, None
    if lines is None:
        return "UNRESOLVED", None, None
    n = len(lines)
    real_end = end if end is not None else start
    if start < 1 or real_end > n or start > real_end:
        return "LINE_OUT_OF_RANGE", None, None
    selected = lines[start - 1:real_end][:MAX_LINE_TEXT_ROWS]
    trimmed = [line[:MAX_LINE_TEXT_CHARS] for line in selected]
    return resolved_result, trimmed, None


def _resolve_path_line(
    repo_dir: Path, ref: str, path: str, start: int, end: int | None,
    tree_index: TreeIndex | None = None,
) -> tuple[str, list[str] | None, str | None]:
    """Returns (result, line_text, detail). line_text is set only on a
    resolved (possibly suffix-matched) file; detail carries the
    AMBIGUOUS_SUFFIX candidate list when that applies."""
    kind = _path_kind_at_ref(repo_dir, ref, path)
    if kind == "file":
        return _extract_line_result(repo_dir, ref, path, start, end, "RESOLVES")
    if kind == "dir":
        return "DIRECTORY_NOT_FILE", None, None

    if tree_index is not None:
        name = _suffix_eligible(path)
        if name is not None:
            suffix_result = _resolve_by_suffix(tree_index, name, False)  # PATH_LINE always targets a file
            if suffix_result is not None:
                result, payload = suffix_result
                if result == "AMBIGUOUS_SUFFIX":
                    count, candidates = payload
                    return result, None, _format_ambiguous_detail(count, candidates)
                return _extract_line_result(repo_dir, ref, payload, start, end, "RESOLVES_BY_SUFFIX")

    base, _base_detail = _resolve_path(repo_dir, ref, path, tree_index)
    return base, None, None


def _first_special_index(token: str) -> int:
    indices = [token.index(c) for c in ("<", "{", "*", "?", "[") if c in token]
    return min(indices) if indices else len(token)


def _prefix_resolves(repo_dir: Path, ref: str, token: str) -> tuple[bool, bool]:
    """Returns (prefix_exists, no_prefix). no_prefix is True when there is
    nothing before the first placeholder/glob character to check at all
    (e.g. `day-{day:04d}.md`, `<project>/...`'s own leading `<project>`) —
    the caller decides what bucket that becomes; this function only reports
    the fact."""
    idx = _first_special_index(token)
    prefix = token[:idx]
    dir_prefix = prefix.rsplit("/", 1)[0] if "/" in prefix else ""
    if dir_prefix == "":
        return True, True
    return _dir_exists(repo_dir, ref, dir_prefix), False


def _is_doc_or_test_path(path: str) -> bool:
    return (
        path.lower().endswith(".md")
        or path.startswith(("docs/", "tests/", "test/"))
        or "/tests/" in path or "/test/" in path
    )


def _resolve_symbol(repo_dir: Path, ref: str, token: str) -> tuple[str, str | None]:
    """Returns (result, detail). A symbol found ONLY in docs/*.md/tests is
    a weak positive (a spec can say a name without the code existing) —
    CHECK, with the file shown; found in real code is OK. Scoping is done
    in Python over ``git grep -l``'s file list rather than a git magic
    exclude-pathspec, since ``_run_git`` forces GIT_LITERAL_PATHSPECS=1 for
    every call (citation paths must never be read as pathspec magic), which
    would otherwise defeat an exclude pattern like `:!docs/**` too."""
    parts = token.split(".")
    last = parts[-1]
    result = _run_git(repo_dir, ["grep", "-w", "-F", "-l", last, ref])
    if result is not None and result[0] == 0 and result[1].strip():
        files = [line.split(":", 1)[-1] for line in result[1].splitlines() if line]
        code_files = [f for f in files if not _is_doc_or_test_path(f)]
        if code_files:
            return "FOUND", None
        return "FOUND_IN_DOCS_OR_TESTS", files[0]
    if len(parts) > 1:
        joined = "/".join(parts)
        candidates = [f"{joined}.py", f"{joined}/__init__.py", f"src/{joined}.py", f"src/{joined}/__init__.py"]
        for c in candidates:
            if _file_exists(repo_dir, ref, c):
                return "FOUND", None
    return "ABSENT", None


def _resolve_sha(repo_dir: Path, sha: str, ref: str) -> tuple[str | None, str | None]:
    """Returns (result, detail). None result means "could not check"
    (not_run). A commit that exists but is reachable from neither <ref> nor
    any remote-tracking ref is COMMIT_EXISTS_UNREACHABLE (CHECK) — the
    object is real, but not evidence this repo state actually contains it."""
    result = _run_git(repo_dir, ["cat-file", "-e", f"{sha}^{{commit}}"])
    if result is None:
        return None, None
    if result[0] != 0:
        return "COMMIT_MISSING", None

    anc = _run_git(repo_dir, ["merge-base", "--is-ancestor", sha, ref])
    if anc is not None and anc[0] == 0:
        return "COMMIT_EXISTS", None

    refs_result = _run_git(repo_dir, ["for-each-ref", "--format=%(refname)", "refs/remotes/"])
    if refs_result is not None and refs_result[0] == 0:
        for refname in refs_result[1].splitlines():
            refname = refname.strip()
            if not refname:
                continue
            anc2 = _run_git(repo_dir, ["merge-base", "--is-ancestor", sha, refname])
            if anc2 is not None and anc2[0] == 0:
                return "COMMIT_EXISTS", f"reachable from {refname}, not {ref}"

    return "COMMIT_EXISTS_UNREACHABLE", f"not reachable from {ref} or any remote-tracking ref"


# --------------------------------------------------------------------------- #
# REF / REPO — resolved as a second-chance reclassification when normal
# PATH/SYMBOL resolution comes up empty, never as a competing classify_token
# branch (a branch/tag name and a repo-relative path are shape-indistinguishable
# from the token text alone; only asking git/gh disambiguates them).
# --------------------------------------------------------------------------- #

_OWNER_REPO_SHAPE_RE = re.compile(r"^[\w.-]+/[\w.-]+$")


def _list_remote_refs(repo_dir: Path) -> set[str] | None:
    result = _run_git(repo_dir, ["ls-remote", "--heads", "--tags", "origin"])
    if result is None or result[0] != 0:
        return None
    names: set[str] = set()
    for line in result[1].splitlines():
        parts = line.split("\t")
        if len(parts) != 2:
            continue
        ref = parts[1]
        if ref.startswith("refs/heads/"):
            names.add(ref[len("refs/heads/"):])
        elif ref.startswith("refs/tags/"):
            names.add(ref[len("refs/tags/"):])
    return names


def _looks_like_ref_name(token: str) -> bool:
    """Branch/tag name shape: no whitespace (already excluded upstream), no
    leading '/', not obviously a file (known extension), and — critically —
    no trailing '/'. A trailing slash is an explicit directory marker in
    this corpus (`chronicle/`); real branch names are never written that
    way in prose, and treating one as REF-eligible would silently
    reclassify a genuine broken-directory citation as REF_UNRESOLVED
    instead of UNRESOLVED, losing the distinction for no benefit."""
    if token.endswith("/"):
        return False
    if _has_known_extension(token):
        return False
    return bool(re.match(r"^[\w][\w./-]*$", token))


def _resolve_ref_name(remote_refs: set[str] | None, token: str) -> str | None:
    if remote_refs is None:
        return None
    name = token[len("origin/"):] if token.startswith("origin/") else token
    if name in remote_refs or token in remote_refs:
        return "REF_RESOLVES"
    return "REF_UNRESOLVED"


def _resolve_repo_ref(default_repo: str, owner_name: str) -> str | None:
    result = _run_gh(["api", f"repos/{owner_name}"])
    if result is None:
        return None
    rc, _stdout, stderr = result
    if rc == 0:
        return "REPO_RESOLVES"
    if "404" in stderr or "Not Found" in stderr:
        return "REPO_UNRESOLVED"
    return None


# --------------------------------------------------------------------------- #
# gh seam
# --------------------------------------------------------------------------- #

def _run_gh(args: list[str], timeout: int = 30) -> tuple[int, str, str] | None:
    try:
        result = subprocess.run(
            ["gh", *args], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.returncode, result.stdout, result.stderr


def _fetch_issue_body(repo: str, number: int) -> tuple[str | None, str | None]:
    result = _run_gh(["issue", "view", str(number), "--repo", repo, "--json", "body"])
    if result is None:
        return None, f"gh issue view {number} --repo {repo} could not be invoked"
    rc, stdout, stderr = result
    if rc != 0:
        return None, f"gh issue view {number} --repo {repo} failed: {stderr.strip() or rc}"
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return None, f"gh issue view {number} returned invalid JSON: {exc}"
    body = data.get("body")
    if body is None:
        return None, f"gh issue view {number} response has no 'body' field"
    return body, None


def _resolve_issue_ref(default_repo: str, owner_repo: str | None, number: int) -> tuple[str | None, str | None]:
    """Returns (result, error). error is set (result None) for any non-404
    gh failure — a rate limit, an auth error, a 403/410/500 — which must
    never be read as NOT_FOUND (a 404 cannot even distinguish "private"
    from "does not exist," so it is itself a hint, never authoritative)."""
    repo = owner_repo or default_repo
    result = _run_gh(["api", f"repos/{repo}/issues/{number}"])
    if result is None:
        return None, "gh api call could not be invoked"
    rc, stdout, stderr = result
    if rc == 0:
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError as exc:
            return None, f"gh api returned invalid JSON: {exc}"
        pr = data.get("pull_request")
        if pr:
            if pr.get("merged_at"):
                return "MERGED", None
            return ("OPEN" if data.get("state") == "open" else "CLOSED"), None
        return ("OPEN" if data.get("state") == "open" else "CLOSED"), None
    if "404" in stderr or "Not Found" in stderr:
        return "NOT_FOUND", None
    return None, f"gh api repos/{repo}/issues/{number} failed (not a 404): {stderr.strip() or rc}"


# --------------------------------------------------------------------------- #
# vault-root pinning + wikilinks (same pattern as wrap_up_audit.py)
# --------------------------------------------------------------------------- #

_PINNED_MODULE_NAMES = (
    "vault_scope", "vault_scope_resolved", "vault_scope_defaults",
    "frontmatter_engine", "vault_audit", "graph_cli",
)


def _pin_vault_root(vault_root: Path) -> Callable[[], None]:
    """Anchor vault_scope_resolved's owner-config resolution to *vault_root*.

    Identical pattern to ``wrap_up_audit._pin_vault_root``: sets
    ``CLAUDE_PROJECT_DIR`` and evicts the vault_scope_resolved-derived
    modules from ``sys.modules`` before this process resolves any of them, so
    ``--vault-root`` (not cwd) is authoritative. The caller MUST call the
    returned ``restore`` in a ``finally``, on both success and exception, so
    this process-global state does not outlive one resolution and does not
    poison another vault root's later resolution in the same process (this
    test suite included).
    """
    had_env = "CLAUDE_PROJECT_DIR" in os.environ
    prior_env = os.environ.get("CLAUDE_PROJECT_DIR")
    prior_modules = {name: sys.modules.get(name) for name in _PINNED_MODULE_NAMES}

    os.environ["CLAUDE_PROJECT_DIR"] = str(vault_root)
    for name in _PINNED_MODULE_NAMES:
        sys.modules.pop(name, None)

    def _restore() -> None:
        if had_env:
            os.environ["CLAUDE_PROJECT_DIR"] = prior_env  # type: ignore[assignment]
        else:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        for name, mod in prior_modules.items():
            if mod is not None:
                sys.modules[name] = mod
            else:
                sys.modules.pop(name, None)

    return _restore


def _looks_like_vault_root(vault_root: Path) -> bool:
    """The same marker ``vault_utils.find_vault_root`` walks up for. A
    caller-supplied ``--vault-root`` that isn't actually a vault must go to
    ``not_run`` (INCOMPLETE), never silently build an empty graph and
    report every wikilink NOTE_UNRESOLVED."""
    return (vault_root / ".vault" / "vault.json").is_file()


def _resolve_wikilinks(vault_root: Path, displays: list[str]) -> tuple[dict[str, str], str | None]:
    """Returns ({display: bucket}, error). On error the dict is empty."""
    if not _looks_like_vault_root(vault_root):
        return {}, f"{vault_root} does not look like a vault (no .vault/vault.json)"

    restore = _pin_vault_root(vault_root)
    try:
        import graph_cli  # noqa: PLC0415

        graph, _cfg = graph_cli.build(vault_root)
        results: dict[str, str] = {}
        for display in displays:
            diag = graph_cli.diagnose(graph, display, suggest=0)
            if diag.reason == "resolved":
                results[display] = "NOTE_RESOLVES"
            elif diag.reason == "ambiguous":
                results[display] = "NOTE_AMBIGUOUS"
            elif diag.reason == "out-of-scope-note":
                results[display] = "OUTSIDE_GRAPH_SCOPE"
            else:
                results[display] = "NOTE_UNRESOLVED"
        return results, None
    except Exception as exc:  # noqa: BLE001 - degrade to not_run, never crash the whole resolver
        return {}, f"{type(exc).__name__}: {exc}"
    finally:
        restore()


# --------------------------------------------------------------------------- #
# repo-dir / fetch / ref preflight
# --------------------------------------------------------------------------- #

_ORIGIN_REPO_RE = re.compile(r"[:/]([\w.-]+/[\w.-]+?)(\.git)?/?$")


def _origin_matches_repo(url: str, repo: str) -> bool:
    m = _ORIGIN_REPO_RE.search(url)
    return bool(m) and m.group(1).lower() == repo.lower()


def _validate_repo_dir(repo_dir: Path, repo: str) -> str | None:
    result = _run_git(repo_dir, ["rev-parse", "--git-dir"])
    if result is None or result[0] != 0:
        return f"--repo-dir {repo_dir} is not a git repository"
    result = _run_git(repo_dir, ["remote", "get-url", "origin"])
    if result is None or result[0] != 0:
        return f"--repo-dir {repo_dir} has no 'origin' remote"
    url = result[1].strip()
    if not _origin_matches_repo(url, repo):
        return f"--repo-dir {repo_dir}'s origin ({url}) does not match --repo {repo}"
    return None


def _fetch(repo_dir: Path) -> str | None:
    result = _run_git(repo_dir, ["fetch", "origin"])
    if result is None or result[0] != 0:
        stderr = result[2].strip() if result else "git fetch origin could not be invoked"
        return f"git fetch origin failed: {stderr}"
    return None


def _default_branch_ref(repo_dir: Path) -> tuple[str | None, str | None]:
    result = _run_git(repo_dir, ["ls-remote", "--symref", "origin", "HEAD"])
    if result is None or result[0] != 0:
        return None, "git ls-remote --symref origin HEAD failed"
    m = re.search(r"^ref:\s+refs/heads/(\S+)\s+HEAD", result[1], re.MULTILINE)
    if not m:
        return None, "could not parse default branch from git ls-remote --symref origin HEAD"
    return f"origin/{m.group(1)}", None


def _resolve_ref_sha(repo_dir: Path, ref: str) -> tuple[str | None, str | None]:
    result = _run_git(repo_dir, ["rev-parse", f"{ref}^{{commit}}"])
    if result is None or result[0] != 0:
        return None, f"--ref {ref} does not resolve to a commit"
    return result[1].strip(), None


# --------------------------------------------------------------------------- #
# severity — OK (trusted, no re-check) or CHECK (verify with one command
# before it counts as a detector-5 finding)
# --------------------------------------------------------------------------- #

_SEVERITY: dict[tuple[str, str], str] = {
    ("PATH", "RESOLVES"): "OK",
    ("PATH", "PARENT_ONLY"): "CHECK",
    ("PATH", "UNRESOLVED"): "CHECK",
    ("PATH", "REFERENCED_ONLY"): "CHECK",
    ("PATH", "RESOLVES_BY_SUFFIX"): "OK",
    ("PATH", "AMBIGUOUS_SUFFIX"): "CHECK",
    ("PATH", "OUTSIDE_REPO"): "CHECK",
    # PATH_LINE success buckets are OK but routed to `evidence_lines`, not
    # `rows` — the reader still skims line_text, just not as a CHECK item.
    ("PATH_LINE", "RESOLVES"): "OK",
    ("PATH_LINE", "RESOLVES_BY_SUFFIX"): "OK",
    ("PATH_LINE", "PARENT_ONLY"): "CHECK",
    ("PATH_LINE", "UNRESOLVED"): "CHECK",
    ("PATH_LINE", "REFERENCED_ONLY"): "CHECK",
    ("PATH_LINE", "LINE_OUT_OF_RANGE"): "CHECK",
    ("PATH_LINE", "AMBIGUOUS_SUFFIX"): "CHECK",
    ("PATH_LINE", "DIRECTORY_NOT_FILE"): "CHECK",
    ("PATH_LINE", "BINARY_FILE"): "CHECK",
    ("PATH_LINE", "OUTSIDE_REPO"): "CHECK",
    ("TEMPLATED", "PREFIX_RESOLVES"): "OK",
    ("TEMPLATED", "PREFIX_UNRESOLVED"): "CHECK",
    ("TEMPLATED", "TEMPLATED_NO_PREFIX"): "OK",
    ("GLOB", "PREFIX_RESOLVES"): "OK",
    ("GLOB", "PREFIX_UNRESOLVED"): "CHECK",
    ("SYMBOL", "FOUND"): "OK",
    ("SYMBOL", "FOUND_IN_DOCS_OR_TESTS"): "CHECK",
    ("SYMBOL", "ABSENT"): "CHECK",
    ("SHA", "COMMIT_EXISTS"): "OK",
    ("SHA", "COMMIT_EXISTS_UNREACHABLE"): "CHECK",
    ("SHA", "COMMIT_MISSING"): "CHECK",
    ("ISSUE_REF", "OPEN"): "OK",
    ("ISSUE_REF", "CLOSED"): "OK",
    ("ISSUE_REF", "MERGED"): "OK",
    ("ISSUE_REF", "NOT_FOUND"): "CHECK",
    ("WIKILINK", "NOTE_RESOLVES"): "OK",
    ("WIKILINK", "NOTE_AMBIGUOUS"): "CHECK",
    ("WIKILINK", "NOTE_UNRESOLVED"): "CHECK",
    ("WIKILINK", "OUTSIDE_GRAPH_SCOPE"): "CHECK",
    ("REF", "REF_RESOLVES"): "OK",
    ("REF", "REF_UNRESOLVED"): "CHECK",
    ("REPO", "REPO_RESOLVES"): "OK",
    ("REPO", "REPO_UNRESOLVED"): "CHECK",
    ("PROSE_LINE_CITATION", "PROSE_LINE_CITATION"): "CHECK",
    ("UNKNOWN_REPO_ALIAS", "UNKNOWN_REPO_ALIAS"): "CHECK",
    ("OUTSIDE_REPO_TOKEN", "OUTSIDE_REPO"): "CHECK",
    ("ERROR", "ERROR"): "CHECK",
}


# --------------------------------------------------------------------------- #
# orchestration
# --------------------------------------------------------------------------- #

def _incomplete_report(
    input_errors: list[str],
    not_run: list[dict[str, str]],
    resolved_ref: str | None,
    resolved_sha: str | None,
    repo: str,
    repo_dir: Path,
    limit: int,
) -> dict[str, Any]:
    return {
        "verdict": "INCOMPLETE",
        "exit_code": VERDICT_EXIT_CODES["INCOMPLETE"],
        "repo": repo,
        "repo_dir": str(repo_dir),
        "resolved_ref": resolved_ref,
        "resolved_sha": resolved_sha,
        "input_errors": input_errors,
        "not_run": not_run,
        "counts": {},
        "rows": [],
        "evidence_lines": [],
        "assumed_repo_refs": [],
        "elided": 0,
        "evidence_elided": 0,
        "limit": limit,
    }


def _other_repos_mentioned(body: str, default_repo: str) -> bool:
    """True if the body names any owner/repo other than --repo (an
    explicit issue-URL/owner-repo#N reference, or a bare `owner/name`
    backtick token) — the signal that promotes a bare #N to CHECK, since a
    multi-repo body makes "assume --repo" a real guess, not a safe default."""
    for m in OWNER_REPO_ISSUE_RE.finditer(body):
        if m.group(1).lower() != default_repo.lower():
            return True
    for m in ISSUE_URL_RE.finditer(body):
        if m.group(1).lower() != default_repo.lower():
            return True
    return False


def collect(
    *,
    repo: str,
    repo_dir: Path,
    issue: int | None,
    body_file: Path | None,
    ref: str | None,
    no_fetch: bool,
    vault_root: Path | None,
    limit: int = 20,
) -> dict[str, Any]:
    input_errors: list[str] = []
    not_run: list[dict[str, str]] = []

    # --- body acquisition ---
    if issue is not None:
        body, err = _fetch_issue_body(repo, issue)
    else:
        try:
            body = body_file.read_text(encoding="utf-8", errors="replace") if body_file else None
            err = None if body_file else "neither --issue nor --body-file was given"
        except OSError as exc:
            body, err = None, f"--body-file {body_file} could not be read: {exc}"

    if err:
        input_errors.append(err)
        body = body or ""
    elif not body.strip():
        input_errors.append("empty body")

    # --- repo-dir / fetch / ref preflight ---
    resolved_ref: str | None = None
    resolved_sha: str | None = None
    repo_dir_err = _validate_repo_dir(repo_dir, repo)
    if repo_dir_err:
        input_errors.append(repo_dir_err)
    else:
        if not no_fetch:
            fetch_err = _fetch(repo_dir)
            if fetch_err:
                input_errors.append(fetch_err)
        candidate_ref = ref
        if candidate_ref is None:
            candidate_ref, branch_err = _default_branch_ref(repo_dir)
            if branch_err:
                input_errors.append(branch_err)
        if candidate_ref is not None:
            sha, sha_err = _resolve_ref_sha(repo_dir, candidate_ref)
            if sha_err:
                input_errors.append(sha_err)
            else:
                resolved_ref, resolved_sha = candidate_ref, sha

    if input_errors:
        return _incomplete_report(input_errors, not_run, resolved_ref, resolved_sha, repo, repo_dir, limit)

    # --- extraction ---
    tokens = extract_tokens(body)
    if not tokens:
        input_errors.append("body has no extractable tokens")
        return _incomplete_report(input_errors, not_run, resolved_ref, resolved_sha, repo, repo_dir, limit)

    unique_tokens = tokens
    other_repos = _other_repos_mentioned(body, repo)

    # --- resolution ---
    counts: dict[str, int] = {}
    check_rows: list[dict[str, Any]] = []
    evidence_lines: list[dict[str, Any]] = []
    assumed_repo_refs: list[dict[str, Any]] = []

    def _count(cls: str, result: str) -> None:
        key = f"{cls}:{result}"
        counts[key] = counts.get(key, 0) + 1

    def _row(token: dict[str, Any], cls: str, result: str, detail: str | None = None) -> dict[str, Any]:
        row: dict[str, Any] = {"token": token["text"], "class": cls, "result": result, "line": token["line"]}
        if detail is not None:
            row["detail"] = detail
        return row

    def _emit(token: dict[str, Any], cls: str, result: str, detail: str | None = None,
               line_text: list[str] | None = None) -> None:
        _count(cls, result)
        severity = _SEVERITY.get((cls, result), "CHECK")
        if severity == "OK":
            if line_text is not None:
                r = _row(token, cls, result, detail)
                r["line_text"] = line_text
                evidence_lines.append(r)
            return
        row = _row(token, cls, result, detail)
        if line_text is not None:
            row["line_text"] = line_text
        row["severity"] = "CHECK"
        check_rows.append(row)

    def _emit_error(token: dict[str, Any], cls: str, exc: Exception) -> None:
        counts["ERROR:ERROR"] = counts.get("ERROR:ERROR", 0) + 1
        row = _row(token, cls, "ERROR", f"{type(exc).__name__}: {exc}")
        row["severity"] = "CHECK"
        check_rows.append(row)

    # Batch by class so gh/graphmark failures degrade the whole class once,
    # rather than retrying a doomed call per token.
    issue_tokens = [t for t in unique_tokens if t["cls"] == "ISSUE_REF"]
    wikilink_tokens = [t for t in unique_tokens if t["cls"] == "WIKILINK"]

    def _token_needs_tree_index(t: dict[str, Any]) -> bool:
        if t["cls"] == "PATH":
            return True
        if t["cls"] == "PATH_LINE":
            return parse_path_line_token(t["text"]) is not None
        return False

    tree_index: TreeIndex | None = None
    if any(_token_needs_tree_index(t) for t in unique_tokens):
        tree_index = _build_tree_index(repo_dir, resolved_ref)

    issue_gh_failed = False
    issue_results: dict[tuple[str | None, int], str | None] = {}
    for t in issue_tokens:
        key = (t.get("repo"), t["number"])
        if key in issue_results:
            continue
        result, err_reason = _resolve_issue_ref(repo, t.get("repo"), t["number"])
        if result is None:
            issue_gh_failed = True
            not_run.append({"class": "issue_ref", "reason": err_reason or "gh api call failed or gh is unavailable"})
            break
        issue_results[key] = result

    remote_refs: set[str] | None = None
    repo_gh_failed = False

    wikilink_results: dict[str, str] = {}
    if wikilink_tokens:
        if vault_root is None:
            not_run.append({"class": "wikilink", "reason": "--vault-root not given and no vault root found"})
        else:
            wikilink_results, wiki_err = _resolve_wikilinks(vault_root, [t["text"] for t in wikilink_tokens])
            if wiki_err:
                not_run.append({"class": "wikilink", "reason": wiki_err})

    for token in unique_tokens:
        cls = token["cls"]
        text = token["text"]
        try:
            if cls in ("SKIP_COMMAND", "SKIP_FLAG", "SKIP_OTHER", "LOCAL", "SKIP_BARE_EXTENSION", "SKIP_KEYWORD"):
                counts[f"{cls}:(none)"] = counts.get(f"{cls}:(none)", 0) + 1
                continue

            if cls == "PATH":
                result, path_detail = _resolve_path(repo_dir, resolved_ref, text, tree_index)
                if (
                    result == "UNRESOLVED" and _OWNER_REPO_SHAPE_RE.match(text)
                    and "." not in text and not text.startswith("origin/")
                ):
                    repo_result = _resolve_repo_ref(repo, text)
                    if repo_result is None:
                        repo_gh_failed = True
                        not_run.append({"class": "repo_ref", "reason": f"gh api repos/{text} could not be invoked"})
                    else:
                        _emit(token, "REPO", repo_result, detail=None if repo_result == "REPO_RESOLVES" else f"{text} not found on GitHub")
                        continue
                bare_no_slash = "/" not in text.rstrip("/")
                looks_like_origin_ref = text.startswith("origin/") and "/" not in text[len("origin/"):]
                if result == "UNRESOLVED" and _looks_like_ref_name(text) and (bare_no_slash or looks_like_origin_ref):
                    if remote_refs is None:
                        remote_refs = _list_remote_refs(repo_dir)
                    ref_result = _resolve_ref_name(remote_refs, text)
                    if ref_result is not None:
                        _emit(token, "REF", ref_result, detail=None if ref_result == "REF_RESOLVES" else "not a remote branch or tag")
                        continue
                detail = path_detail if path_detail is not None else (result if result != "RESOLVES" else None)
                _emit(token, cls, result, detail=detail)
                continue

            if cls == "PATH_LINE":
                parsed = parse_path_line_token(text)
                if parsed is None:
                    _emit(token, cls, "UNRESOLVED", detail="could not parse path:line")
                    continue
                path, start, end = parsed
                result, line_text, extra_detail = _resolve_path_line(repo_dir, resolved_ref, path, start, end, tree_index)
                detail = extra_detail if extra_detail is not None else (None if line_text is not None else result)
                _emit(token, cls, result, detail=detail, line_text=line_text)
                continue

            if cls == "OUTSIDE_REPO_TOKEN":
                _emit(token, "PATH", "OUTSIDE_REPO", detail="path segments escape the repo root")
                continue

            if cls == "PROSE_LINE_CITATION":
                hint = (
                    f"verify the cited range contains {token['symbol']}" if token.get("symbol")
                    else "verify the cited range supports the claim"
                )
                _emit(token, cls, cls, detail=hint)
                continue

            if cls == "UNKNOWN_REPO_ALIAS":
                _emit(token, cls, cls, detail=f"alias '{token['alias']}' is not a known owner/repo; resolve by hand")
                continue

            if cls in ("TEMPLATED", "GLOB"):
                ok, no_prefix = _prefix_resolves(repo_dir, resolved_ref, text)
                if no_prefix and cls == "TEMPLATED":
                    result = "TEMPLATED_NO_PREFIX"
                else:
                    result = "PREFIX_RESOLVES" if ok else "PREFIX_UNRESOLVED"
                _emit(token, cls, result, detail=None if ok else f"literal prefix not found at {resolved_ref}")
                continue

            if cls == "SYMBOL":
                # Deliberately no REF fallback here (unlike the PATH
                # branch): a bare branch name's shape (word chars, dots,
                # dashes) overlaps almost completely with a Python
                # identifier's, so checking every ABSENT symbol against
                # remote_refs would misclassify ordinary absent symbols
                # (`_expense_fraud`) as REF_UNRESOLVED far more often than
                # it would ever correctly catch a real branch name typed
                # bare. A branch name written as `origin/<branch>` is
                # already PATH-classified (has a "/") and gets the REF
                # check there; a bare branch name with no `origin/` prefix
                # stays ABSENT here -- same CHECK severity either way.
                result, sym_detail = _resolve_symbol(repo_dir, resolved_ref, text)
                detail = sym_detail if sym_detail is not None else (
                    "not found via grep or module path" if result == "ABSENT" else None
                )
                _emit(token, cls, result, detail=detail)
                continue

            if cls == "SHA":
                result, sha_detail = _resolve_sha(repo_dir, text, resolved_ref)
                if result is None:
                    not_run.append({"class": "sha", "reason": f"could not check commit {text}"})
                    continue
                _emit(token, cls, result, detail=sha_detail)
                continue

            if cls == "ISSUE_REF":
                is_bare = token.get("repo") is None
                result = issue_results.get((token.get("repo"), token["number"]))
                if result is None:
                    continue  # gh failure already recorded in not_run above
                display_repo = token.get("repo") or repo
                if is_bare and result != "NOT_FOUND":
                    assumed_repo_refs.append({
                        "token": text, "state": result, "detail": f"resolved against {repo}",
                    })
                    if other_repos:
                        row = _row(token, cls, result, detail="body mentions other repos; confirm target")
                        row["severity"] = "CHECK"
                        check_rows.append(row)
                        counts[f"{cls}:{result}"] = counts.get(f"{cls}:{result}", 0) + 1
                    continue
                _emit(token, cls, result, detail=None if result != "NOT_FOUND" else f"{display_repo}#{token['number']} not found")
                continue

            if cls == "WIKILINK":
                result = wikilink_results.get(text)
                if result is None:
                    continue  # already recorded as not_run above
                _emit(token, cls, result, detail=None if result == "NOTE_RESOLVES" else f"graphmark: {result}")
                continue
        except Exception as exc:  # noqa: BLE001 - one token's crash becomes a CHECK row, never a whole-run crash
            _emit_error(token, cls, exc)
            continue

    check_rows.sort(key=lambda r: r["line"])
    evidence_lines.sort(key=lambda r: r["line"])

    if issue_gh_failed or repo_gh_failed:
        pass  # already in not_run

    if not_run:
        verdict = "INCOMPLETE"
    elif check_rows:
        verdict = "CHECK_REQUIRED"
    else:
        verdict = "ALL_RESOLVED"

    # `--limit` applies only to OK/evidence listings; CHECK rows are never
    # elided (afk#1378: a real finding at row 26 of 36 must never disappear
    # behind a default --limit 20).
    capped_evidence, evidence_elided = (
        (evidence_lines, 0) if limit <= 0 or len(evidence_lines) <= limit
        else (evidence_lines[:limit], len(evidence_lines) - limit)
    )

    return {
        "verdict": verdict,
        "exit_code": VERDICT_EXIT_CODES[verdict],
        "repo": repo,
        "repo_dir": str(repo_dir),
        "resolved_ref": resolved_ref,
        "resolved_sha": resolved_sha,
        "input_errors": input_errors,
        "not_run": not_run,
        "counts": counts,
        "rows": check_rows,
        "evidence_lines": capped_evidence,
        "assumed_repo_refs": assumed_repo_refs,
        "elided": 0,
        "evidence_elided": evidence_elided,
        "limit": limit,
    }


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #

def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"## Cold-Read Evidence Resolver — {report['verdict']}",
        "",
        f"- repo: {report['repo']}",
        f"- repo-dir: {report['repo_dir']}",
        f"- resolved ref: {report['resolved_ref']} ({report['resolved_sha']})",
        "",
    ]
    if report["input_errors"]:
        lines.append("### Input Errors")
        for e in report["input_errors"]:
            lines.append(f"- {e}")
        lines.append("")

    if report["counts"]:
        lines.append("### Counts")
        for key in sorted(report["counts"]):
            lines.append(f"- {key}: {report['counts'][key]}")
        lines.append("")

    if report["rows"]:
        lines.append("### CHECK — verify each with one command before treating it as a finding")
        for r in report["rows"]:
            detail = r.get("detail") or ""
            if r.get("line_text"):
                detail = " | ".join(r["line_text"])
            lines.append(f"- `{r['token']}` | {r['class']} | {r['result']} | line {r['line']} | {detail}")
        lines.append("")

    if report.get("evidence_lines"):
        lines.append("### Evidence Lines — compare against the claim")
        for r in report["evidence_lines"]:
            text = " | ".join(r.get("line_text") or [])
            lines.append(f"- `{r['token']}` | line {r['line']} | {text}")
        if report.get("evidence_elided"):
            lines.append(f"- ... {report['evidence_elided']} more")
        lines.append("")

    if report.get("assumed_repo_refs"):
        lines.append("### Assumed Repo Refs — bare #N resolved against --repo")
        for r in report["assumed_repo_refs"]:
            lines.append(f"- `{r['token']}`: {r['state']} ({r['detail']})")
        lines.append("")

    if report["not_run"]:
        lines.append("### Not Run")
        for nr in report["not_run"]:
            lines.append(f"- {nr['class']}: {nr['reason']}")
        lines.append("")

    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _main(argv: list[str] | None) -> int:
    parser = argparse.ArgumentParser(
        description="Deterministic /cold-read detector-5 evidence resolver."
    )
    parser.add_argument("--repo", required=True, help="OWNER/REPO the body's evidence resolves against.")
    parser.add_argument("--repo-dir", required=True, type=Path, help="Local checkout of --repo.")
    body_group = parser.add_mutually_exclusive_group(required=True)
    body_group.add_argument("--issue", type=int, help="Issue number; body fetched via gh issue view.")
    body_group.add_argument("--body-file", type=Path, help="Read the body from this file instead.")
    parser.add_argument("--ref", default=None, help="Ref to resolve against. Defaults to the remote default branch.")
    parser.add_argument("--no-fetch", action="store_true", help="Skip 'git fetch origin' before resolving.")
    parser.add_argument("--vault-root", type=Path, default=None, help="Vault root for wikilink resolution.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of Markdown.")
    parser.add_argument("--limit", type=int, default=20, help="Max evidence-line rows in output (CHECK rows are never limited).")
    args = parser.parse_args(argv)

    vault_root = args.vault_root.resolve() if args.vault_root else find_vault_root()

    report = collect(
        repo=args.repo,
        repo_dir=args.repo_dir,
        issue=args.issue,
        body_file=args.body_file,
        ref=args.ref,
        no_fetch=args.no_fetch,
        vault_root=vault_root,
        limit=args.limit,
    )
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(render_markdown(report))

    return report["exit_code"]


def main(argv: list[str] | None = None) -> int:
    """Wraps ``_main`` so any uncaught exception exits 2 (INCOMPLETE), never 1 (CHECK_REQUIRED)."""
    try:
        return _main(argv)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - last-resort guard; report and degrade, never crash-as-CHECK_REQUIRED
        print(f"ERROR: cold_read_evidence crashed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return VERDICT_EXIT_CODES["INCOMPLETE"]


if __name__ == "__main__":
    raise SystemExit(main())
