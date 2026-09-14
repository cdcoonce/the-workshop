#!/usr/bin/env python3
"""Deterministic collector for /cold-read detector 5 — unresolvable evidence.

Detector 5 requires every path, ref, SHA and note a spec names to resolve, in
either role it plays: evidence (cited as proof of existing state) or
destination (named as where the slice will create something new). Today that
is "one unpiped command each" for every such token, run by hand. This script
extracts those tokens from an issue body, resolves each against the target
repo's git object store at a pinned ref (never the working tree) and, for
wikilinks, against a vault via graphmark, and returns a compact verdict table
so the /cold-read subagent judges only the rows that need judgment.

Read-only: no repo or vault code is ever executed. Repo content is read
through ``git cat-file`` / ``git ls-tree`` / ``git show`` / ``git grep``
only; wikilinks are resolved via ``graph_cli.build`` exactly as
``wrap_up_audit.py`` does, scope-pinned to ``--vault-root``.

``gh`` is called through the module-level ``_run_gh`` seam so tests can
inject a fake runner with no network.
"""

from __future__ import annotations

import argparse
import json
import posixpath
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from vault_utils import WIKILINK_CAPTURE_RE, find_vault_root  # noqa: E402

VERDICT_EXIT_CODES = {"RESOLVED": 0, "NEEDS_JUDGMENT": 0, "BLOCKING": 1, "INCOMPLETE": 2}

# --------------------------------------------------------------------------- #
# extraction regexes
# --------------------------------------------------------------------------- #

FENCE_RE = re.compile(r"^(```|~~~)")
BACKTICK_RE = re.compile(r"`([^`\n]+)`")
ISSUE_URL_RE = re.compile(r"https://github\.com/([\w.-]+/[\w.-]+?)/(?:issues|pull)/(\d+)\b")
OWNER_REPO_ISSUE_RE = re.compile(r"(?<![\w/.#])([\w.-]+/[\w.-]+)#(\d+)\b")
BARE_ISSUE_RE = re.compile(r"(?<![\w#/.])#(\d+)\b")
SHA_CANDIDATE_RE = re.compile(r"\b[0-9a-fA-F]{7,40}\b")

PATH_EXTENSIONS = (
    ".py", ".md", ".toml", ".json", ".yml", ".yaml", ".sh", ".sql",
    ".txt", ".cfg", ".ini", ".ts", ".tsx", ".js",
)
WHITESPACE_RE = re.compile(r"\s")
TEMPLATE_RE = re.compile(r"<[^<>]*>")
GLOB_CHARS = frozenset("*?[")
PATH_LINE_RE = re.compile(r"^(?P<path>.+):(?P<start>\d+)(?:-(?P<end>\d+))?$")
SYMBOL_RE = re.compile(r"^[A-Za-z_][\w.]*$")
HEX_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")
SHA_LETTERS = frozenset("abcdefABCDEF")

MAX_LINE_TEXT_ROWS = 3
MAX_LINE_TEXT_CHARS = 160


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
    if any(c in GLOB_CHARS for c in token):
        return "GLOB"
    m = PATH_LINE_RE.match(token)
    if m:
        path_part = m.group("path")
        if "/" in path_part or _has_known_extension(path_part):
            return "PATH_LINE"
    if "/" in token or _has_known_extension(token) or token.endswith("/"):
        return "PATH"
    if _is_sha_shaped(token):
        return "SHA"
    if SYMBOL_RE.match(token):
        return "SYMBOL"
    return "SKIP_OTHER"


# --------------------------------------------------------------------------- #
# extraction
# --------------------------------------------------------------------------- #

def _mask_fenced_code(text: str) -> str:
    """Blank fenced code block lines (delimiters included), preserving line offsets."""
    lines = text.split("\n")
    out: list[str] = []
    in_fence = False
    fence_marker = ""
    for line in lines:
        stripped = line.strip()
        m = FENCE_RE.match(stripped)
        if m:
            marker = m.group(1)
            if not in_fence:
                in_fence = True
                fence_marker = marker
                out.append("")
                continue
            if stripped.startswith(fence_marker):
                in_fence = False
                fence_marker = ""
                out.append("")
                continue
        out.append("" if in_fence else line)
    return "\n".join(out)


def _line_no(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _mask_span(text: str, start: int, end: int) -> str:
    """Replace text[start:end] with spaces of the same length (newlines preserved)."""
    span = text[start:end]
    blanked = "".join(c if c == "\n" else " " for c in span)
    return text[:start] + blanked + text[end:]


def extract_tokens(body: str) -> list[dict[str, Any]]:
    """Extract evidence tokens per the four corpus extraction rules, in body order.

    Each token dict carries ``text``, ``cls`` (bucket/class), ``line``, and —
    for ``ISSUE_REF`` only — ``repo`` (explicit owner/repo, or None for
    ``--repo``) and ``number``.
    """
    masked = _mask_fenced_code(body)
    tokens: list[dict[str, Any]] = []

    # 1. backtick spans (classified via the rule table)
    plain = masked
    for m in BACKTICK_RE.finditer(masked):
        content = m.group(1)
        line = _line_no(masked, m.start())
        tokens.append({"text": content, "cls": classify_token(content), "line": line})
        plain = _mask_span(plain, m.start(), m.end())

    # 2. wikilinks
    for m in WIKILINK_CAPTURE_RE.finditer(plain):
        raw = m.group(1)
        target = raw.split("|")[0].split("#")[0].strip()
        if not target:
            continue
        line = _line_no(plain, m.start())
        tokens.append({"text": target, "cls": "WIKILINK", "line": line})
    plain = WIKILINK_CAPTURE_RE.sub(lambda m: _blank(m.group(0)), plain)

    # 3. issue/PR refs — URL form, then owner/repo#N, then bare #N, masking as we go
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

    # 4. bare commit SHAs
    for m in SHA_CANDIDATE_RE.finditer(plain):
        candidate = m.group(0)
        if _is_sha_shaped(candidate):
            line = _line_no(plain, m.start())
            tokens.append({"text": candidate, "cls": "SHA", "line": line})

    tokens.sort(key=lambda t: t["line"])
    return _dedupe_tokens(tokens)


def _blank(s: str) -> str:
    return "".join(c if c == "\n" else " " for c in s)


def _dedupe_tokens(tokens: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    out: list[dict[str, Any]] = []
    for t in tokens:
        key = (t["cls"], t["text"], t.get("repo"))
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out


# --------------------------------------------------------------------------- #
# git plumbing — reads the object store at <ref>, never the working tree
# --------------------------------------------------------------------------- #

def _run_git(repo_dir: Path, args: list[str], timeout: int = 30) -> tuple[int, str, str] | None:
    try:
        result = subprocess.run(
            ["git", *args], cwd=repo_dir, capture_output=True, text=True, timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.returncode, result.stdout, result.stderr


def _file_exists(repo_dir: Path, ref: str, path: str) -> bool:
    result = _run_git(repo_dir, ["cat-file", "-e", f"{ref}:{path}"])
    return result is not None and result[0] == 0


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
    # git grep <rev> emits "<rev>:<path>:<lineno>:<text>"; report path:line: text.
    parts = lines[0].split(":", 3)
    if len(parts) == 4:
        _rev, path, lineno, text = parts
        detail = f"{path}:{lineno}: {text.strip()}"
    else:
        detail = lines[0]
    return detail[:MAX_LINE_TEXT_CHARS]


def _resolve_path(repo_dir: Path, ref: str, token: str) -> tuple[str, str | None]:
    """Returns (result, detail). detail is set only for REFERENCED_ONLY."""
    is_dir_token = token.endswith("/")
    bare = token.rstrip("/")
    if not is_dir_token and _file_exists(repo_dir, ref, token):
        return "RESOLVES", None
    if bare and _dir_exists(repo_dir, ref, bare):
        return "RESOLVES", None
    # Neither a file nor a directory exists at <ref>. A directory-shaped
    # token gets one more check before falling to PARENT_ONLY/UNRESOLVED:
    # is its name established as a quoted string literal in code, typically
    # a runtime `.mkdir()` target that git's tree never records? That is
    # real evidence the path is correct, not absent — the reader still has
    # to weigh it (severity JUDGMENT), but it must not read as a flat
    # UNRESOLVED/BLOCKING the way an invented or stale path does.
    if _is_directory_shaped(token):
        detail = _referenced_only_detail(repo_dir, ref, bare)
        if detail is not None:
            return "REFERENCED_ONLY", detail
    parent = posixpath.dirname(bare)
    if parent and _dir_exists(repo_dir, ref, parent):
        return "PARENT_ONLY", None
    return "UNRESOLVED", None


def _read_ref_file_lines(repo_dir: Path, ref: str, path: str) -> list[str] | None:
    result = _run_git(repo_dir, ["show", f"{ref}:{path}"])
    if result is None or result[0] != 0:
        return None
    return result[1].splitlines()


def _resolve_path_line(
    repo_dir: Path, ref: str, path: str, start: int, end: int | None,
) -> tuple[str, list[str] | None]:
    base, _base_detail = _resolve_path(repo_dir, ref, path)
    if base != "RESOLVES":
        return base, None
    lines = _read_ref_file_lines(repo_dir, ref, path)
    if lines is None:
        return "UNRESOLVED", None
    n = len(lines)
    real_end = end if end is not None else start
    if start < 1 or real_end > n or start > real_end:
        return "LINE_OUT_OF_RANGE", None
    selected = lines[start - 1:real_end][:MAX_LINE_TEXT_ROWS]
    trimmed = [line[:MAX_LINE_TEXT_CHARS] for line in selected]
    return "RESOLVES", trimmed


def _first_special_index(token: str) -> int:
    indices = [token.index(c) for c in ("<", "*", "?", "[") if c in token]
    return min(indices) if indices else len(token)


def _prefix_resolves(repo_dir: Path, ref: str, token: str) -> bool:
    idx = _first_special_index(token)
    prefix = token[:idx]
    dir_prefix = prefix.rsplit("/", 1)[0] if "/" in prefix else ""
    if dir_prefix == "":
        return True  # empty prefix = repo root, which trivially exists at a resolved ref
    return _dir_exists(repo_dir, ref, dir_prefix)


def _grep_word(repo_dir: Path, ref: str, term: str) -> bool:
    result = _run_git(repo_dir, ["grep", "-w", "-F", "-q", term, ref])
    return result is not None and result[0] == 0


def _resolve_symbol(repo_dir: Path, ref: str, token: str) -> str:
    parts = token.split(".")
    last = parts[-1]
    if _grep_word(repo_dir, ref, last):
        return "FOUND"
    if len(parts) > 1:
        joined = "/".join(parts)
        candidates = [f"{joined}.py", f"{joined}/__init__.py", f"src/{joined}.py", f"src/{joined}/__init__.py"]
        for c in candidates:
            if _file_exists(repo_dir, ref, c):
                return "FOUND"
    return "ABSENT"


def _resolve_sha(repo_dir: Path, sha: str) -> str | None:
    result = _run_git(repo_dir, ["cat-file", "-e", f"{sha}^{{commit}}"])
    if result is None:
        return None
    return "COMMIT_EXISTS" if result[0] == 0 else "COMMIT_MISSING"


# --------------------------------------------------------------------------- #
# gh seam
# --------------------------------------------------------------------------- #

def _run_gh(args: list[str], timeout: int = 30) -> tuple[int, str, str] | None:
    try:
        result = subprocess.run(
            ["gh", *args], capture_output=True, text=True, timeout=timeout,
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


def _resolve_issue_ref(default_repo: str, owner_repo: str | None, number: int) -> str | None:
    repo = owner_repo or default_repo
    result = _run_gh(["api", f"repos/{repo}/issues/{number}"])
    if result is None:
        return None
    rc, stdout, stderr = result
    if rc == 0:
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            return None
        pr = data.get("pull_request")
        if pr:
            if pr.get("merged_at"):
                return "MERGED"
            return "OPEN" if data.get("state") == "open" else "CLOSED"
        return "OPEN" if data.get("state") == "open" else "CLOSED"
    if "404" in stderr or "Not Found" in stderr:
        return "NOT_FOUND"
    return None


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
    import os  # noqa: PLC0415

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


def _resolve_wikilinks(vault_root: Path, displays: list[str]) -> tuple[dict[str, str], str | None]:
    """Returns ({display: bucket}, error). On error the dict is empty."""
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
# severity
# --------------------------------------------------------------------------- #

_SEVERITY: dict[tuple[str, str], str] = {
    ("PATH", "RESOLVES"): "OK",
    ("PATH", "PARENT_ONLY"): "JUDGMENT",
    ("PATH", "UNRESOLVED"): "BLOCKING",
    ("PATH", "REFERENCED_ONLY"): "JUDGMENT",
    ("PATH_LINE", "RESOLVES"): "JUDGMENT",
    ("PATH_LINE", "PARENT_ONLY"): "JUDGMENT",
    ("PATH_LINE", "UNRESOLVED"): "BLOCKING",
    ("PATH_LINE", "REFERENCED_ONLY"): "JUDGMENT",
    ("PATH_LINE", "LINE_OUT_OF_RANGE"): "BLOCKING",
    ("TEMPLATED", "PREFIX_RESOLVES"): "OK",
    ("TEMPLATED", "PREFIX_UNRESOLVED"): "BLOCKING",
    ("GLOB", "PREFIX_RESOLVES"): "OK",
    ("GLOB", "PREFIX_UNRESOLVED"): "BLOCKING",
    ("SYMBOL", "FOUND"): "OK",
    ("SYMBOL", "ABSENT"): "JUDGMENT",
    ("SHA", "COMMIT_EXISTS"): "OK",
    ("SHA", "COMMIT_MISSING"): "BLOCKING",
    ("ISSUE_REF", "OPEN"): "OK",
    ("ISSUE_REF", "CLOSED"): "OK",
    ("ISSUE_REF", "MERGED"): "OK",
    ("ISSUE_REF", "NOT_FOUND"): "BLOCKING",
    ("WIKILINK", "NOTE_RESOLVES"): "OK",
    ("WIKILINK", "NOTE_AMBIGUOUS"): "JUDGMENT",
    ("WIKILINK", "NOTE_UNRESOLVED"): "BLOCKING",
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
        "elided": 0,
        "limit": limit,
    }


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
            body = body_file.read_text(encoding="utf-8") if body_file else None
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

    unique_tokens = _dedupe_tokens(tokens)

    # --- resolution ---
    counts: dict[str, int] = {}
    rows: list[dict[str, Any]] = []

    def _count(cls: str, result: str) -> None:
        key = f"{cls}:{result}"
        counts[key] = counts.get(key, 0) + 1

    def _emit(token: dict[str, Any], cls: str, result: str, detail: str | None = None,
               line_text: list[str] | None = None) -> None:
        _count(cls, result)
        severity = _SEVERITY.get((cls, result), "OK")
        if severity == "OK":
            return
        row: dict[str, Any] = {
            "token": token["text"], "class": cls, "result": result,
            "line": token["line"], "severity": severity,
        }
        if detail is not None:
            row["detail"] = detail
        if line_text is not None:
            row["line_text"] = line_text
        rows.append(row)

    # Batch by class so gh/graphmark failures degrade the whole class once,
    # rather than retrying a doomed call per token.
    issue_tokens = [t for t in unique_tokens if t["cls"] == "ISSUE_REF"]
    wikilink_tokens = [t for t in unique_tokens if t["cls"] == "WIKILINK"]

    issue_results: dict[tuple[str | None, int], str | None] = {}
    if issue_tokens:
        first = issue_tokens[0]
        first_result = _resolve_issue_ref(repo, first.get("repo"), first["number"])
        if first_result is None:
            not_run.append({"class": "issue_ref", "reason": "gh api call failed or gh is unavailable"})
        else:
            issue_results[(first.get("repo"), first["number"])] = first_result
            for t in issue_tokens[1:]:
                issue_results[(t.get("repo"), t["number"])] = _resolve_issue_ref(repo, t.get("repo"), t["number"])

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

        if cls in ("SKIP_COMMAND", "SKIP_FLAG", "SKIP_OTHER", "LOCAL"):
            counts[f"{cls}:(none)"] = counts.get(f"{cls}:(none)", 0) + 1
            continue

        if cls == "PATH":
            result, path_detail = _resolve_path(repo_dir, resolved_ref, text)
            detail = path_detail if path_detail is not None else (result if result != "RESOLVES" else None)
            _emit(token, cls, result, detail=detail)
            continue

        if cls == "PATH_LINE":
            m = PATH_LINE_RE.match(text)
            path = m.group("path")
            start = int(m.group("start"))
            end = int(m.group("end")) if m.group("end") else None
            result, line_text = _resolve_path_line(repo_dir, resolved_ref, path, start, end)
            detail = None if line_text is not None else result
            _emit(token, cls, result, detail=detail, line_text=line_text)
            continue

        if cls in ("TEMPLATED", "GLOB"):
            ok = _prefix_resolves(repo_dir, resolved_ref, text)
            result = "PREFIX_RESOLVES" if ok else "PREFIX_UNRESOLVED"
            _emit(token, cls, result, detail=None if ok else f"literal prefix not found at {resolved_ref}")
            continue

        if cls == "SYMBOL":
            result = _resolve_symbol(repo_dir, resolved_ref, text)
            _emit(token, cls, result, detail=None if result == "FOUND" else "not found via grep or module path")
            continue

        if cls == "SHA":
            result = _resolve_sha(repo_dir, text)
            if result is None:
                not_run.append({"class": "sha", "reason": f"could not check commit {text}"})
                continue
            _emit(token, cls, result, detail=None if result == "COMMIT_EXISTS" else "no such commit at this ref")
            continue

        if cls == "ISSUE_REF":
            result = issue_results.get((token.get("repo"), token["number"]))
            if result is None:
                continue  # already recorded as not_run above
            display_repo = token.get("repo") or repo
            _emit(token, cls, result, detail=None if result != "NOT_FOUND" else f"{display_repo}#{token['number']} not found")
            continue

        if cls == "WIKILINK":
            result = wikilink_results.get(text)
            if result is None:
                continue  # already recorded as not_run above
            _emit(token, cls, result, detail=None if result == "NOTE_RESOLVES" else f"graphmark: {result}")
            continue

    blocking = [r for r in rows if r["severity"] == "BLOCKING"]
    judgment = [r for r in rows if r["severity"] == "JUDGMENT"]

    if not_run:
        verdict = "INCOMPLETE"
    elif blocking:
        verdict = "BLOCKING"
    elif judgment:
        verdict = "NEEDS_JUDGMENT"
    else:
        verdict = "RESOLVED"

    rows.sort(key=lambda r: r["line"])
    capped_rows, elided = (rows, 0) if limit <= 0 or len(rows) <= limit else (rows[:limit], len(rows) - limit)

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
        "rows": capped_rows,
        "elided": elided,
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
        lines.append("### Findings (BLOCKING and JUDGMENT only)")
        for r in report["rows"]:
            detail = r.get("detail") or ""
            if r.get("line_text"):
                detail = " | ".join(r["line_text"])
            lines.append(f"- `{r['token']}` | {r['class']} | {r['result']} | line {r['line']} | {detail}")
        if report["elided"]:
            lines.append(f"- ... {report['elided']} more")
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
    parser.add_argument("--limit", type=int, default=20, help="Max finding rows in output.")
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
    """Wraps ``_main`` so any uncaught exception exits 2 (INCOMPLETE), never 1 (BLOCKING)."""
    try:
        return _main(argv)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - last-resort guard; report and degrade, never crash-as-BLOCKING
        print(f"ERROR: cold_read_evidence crashed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return VERDICT_EXIT_CODES["INCOMPLETE"]


if __name__ == "__main__":
    raise SystemExit(main())
