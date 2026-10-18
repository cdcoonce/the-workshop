#!/usr/bin/env python3
"""Preflight and dispatch generator for a ``/cold-read`` reader.

Incident: on 2026-10-10 a cold reader whose scratch directory could not be
created spent 174,751 tokens and about nine minutes on a read that could not
probe, and said so only in its report. A read that cannot do the one thing it
exists for should stop at its first command, at the cost of one tool call. The
reader's first command is this script's ``preflight``, supplied by the
conductor in the dispatch; ``build`` generates that dispatch.

Usage::

    python3 "<engine>/cold_read_dispatch.py" preflight --scratch DIR
    python3 "<engine>/cold_read_dispatch.py" build --repo OWNER/NAME --issue N
        --checkout DIR --scratch-root DIR --out DIR --spec FILE --afk-project DIR
        --comments-json FILE [--expect-body HEX12] [--fork-branch BRANCH]
        [--detector5-ref REF] [--vault-root DIR] [--teeth-check FILE] [--json]

``preflight`` creates a uniquely named sentinel file in DIR, writes a value to
it, reads the value back and removes the sentinel, then runs ``git --version``
and ``uv --version``. It prints exactly one line to stdout and nothing to
stderr::

    PREFLIGHT ok scratch=<DIR> git=<version> uv=<version>
    PREFLIGHT failed cause=<scratch-missing|scratch-unwritable|git-missing|uv-missing>

Each version is the first line of that program's ``--version`` output. A
failure names the first failing cause in the order shown: a directory that is
not there is ``scratch-missing``; a sentinel that cannot be created, written,
read back or removed, or that reads back a different value, is
``scratch-unwritable``; a program that cannot be started, times out or exits
non-zero is missing. It deletes nothing but its own sentinel.

Exit codes: 0 ok, 1 failed, 2 usage error (a missing ``--scratch``: argparse
writes its usage message to stderr and ``main`` raises ``SystemExit(2)``).

``git`` and ``uv`` run only through the module-level ``_run_tool`` seam and the
sentinel round trip only through ``_roundtrip_sentinel``, so tests inject
fakes with no process and no filesystem.

``build`` is procedure step 1 of the gate as a command (the-workshop#1178). It
fetches the issue body, resolves the fork point from ``origin`` (never from a
remote-tracking ref), archives it into a new scratch directory, runs detectors
5 and 10, and writes ``reader.md`` (the reader's whole prompt), ``manifest.json``
and the evidence files into ``--out``. Every path in its output derives from its
arguments or from this script's own location. Exit codes: 0 built, 2 usage or
unreadable input, 3 ``--expect-body`` mismatch, 4 a value could not be resolved
(fork SHA, archive, spec section, teeth path, detector start), 5 the assembled
prompt breaks the reader contract. ``gh``, ``git`` and the detectors run only
through ``_run_gh``, ``_run_git`` and ``_run_detector``. The body hash and the
verdict title come from ``cold_read_stamp`` and ``cold_read_ledger``; nothing
else here hashes or classifies. Stdlib only, apart from those two siblings.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from cold_read_ledger import VERDICT_TITLE  # noqa: E402
from cold_read_stamp import body_hash  # noqa: E402

SENTINEL_PREFIX = ".cold-read-preflight-"


def _run_tool(argv: list[str], timeout: float = 30) -> tuple[int, str, str] | None:
    """Run *argv*, returning ``(exit_code, stdout, stderr)`` or ``None``.

    Parameters
    ----------
    argv : list[str]
        The program and its arguments (e.g. ``["git", "--version"]``).
    timeout : float
        Seconds to wait before giving up.

    Returns
    -------
    tuple[int, str, str] | None
        The process result, or ``None`` when the program cannot be started
        (``OSError``) or outlives *timeout*.
    """
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.returncode, result.stdout, result.stderr


def _roundtrip_sentinel(directory: str, value: str) -> str:
    """Write *value* to a new sentinel file in *directory*, read it back and remove it.

    The sentinel gets an exclusive, uniquely named file, so an entry already in
    *directory* is never truncated, and it is the only thing removed.

    Parameters
    ----------
    directory : str
        An existing directory.
    value : str
        Text to write.

    Returns
    -------
    str
        The text read back from the sentinel.

    Raises
    ------
    OSError
        On any failure to create, write, read or remove the sentinel.
    """
    descriptor, path = tempfile.mkstemp(prefix=SENTINEL_PREFIX, dir=directory)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(value)
        with open(path, encoding="utf-8", errors="replace", newline="") as handle:
            return handle.read()
    finally:
        os.unlink(path)


def _first_line(text: str) -> str:
    return text.split("\n", 1)[0].rstrip("\r")


def _tool_version(argv: list[str]) -> str | None:
    """The first line of the program's output, or ``None`` when it counts as missing."""
    result = _run_tool(argv)
    if result is None or result[0] != 0:
        return None
    return _first_line(result[1])


def _failed(cause: str) -> int:
    print(f"PREFLIGHT failed cause={cause}")
    return 1


def _preflight(scratch: str) -> int:
    if not os.path.isdir(scratch):
        return _failed("scratch-missing")
    value = os.urandom(8).hex()
    try:
        read_back = _roundtrip_sentinel(scratch, value)
    except OSError:
        return _failed("scratch-unwritable")
    if read_back != value:
        return _failed("scratch-unwritable")
    git = _tool_version(["git", "--version"])
    if git is None:
        return _failed("git-missing")
    uv = _tool_version(["uv", "--version"])
    if uv is None:
        return _failed("uv-missing")
    print(f"PREFLIGHT ok scratch={scratch} git={git} uv={uv}")
    return 0


GRAPHMARK_PIN = "graphmark>=0.11,<0.12"
DETECTOR_TIMEOUT = 600
GIT_TIMEOUT = 300
DEFAULT_BRANCH = "main"
HAND_BUILT_LINE = "Build path: hand-built under the `drain-queue` skill"
TARGET_LINE_RE = re.compile(r"^Target:\s*(afk/epic-\d+)\s*$")
BRANCH_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._/@+-]*")
SHA_RE = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
GIVEN_BULLET = "What the reader is given."
CONTRACT_NEEDLES = ("--comments", "step 2", "read-only")
NO_COMMENTS = "No comments other than cold-read verdicts."
CHECKOUT_PLACEHOLDER = "<checkout>"
SUBAGENT_TYPE = "general-purpose"
MODEL = "sonnet"
_TAR_FILTER = {"filter": "tar"} if hasattr(tarfile, "data_filter") else {}


class _Fail(Exception):
    """A build that cannot go on: the exit code and the line for stderr."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _execute(argv: list[str], cwd: str | None, timeout: float) -> tuple[int, str, str]:
    """Run *argv* in *cwd* and return ``(exit_code, stdout, stderr)`` as text.

    Raises
    ------
    OSError
        When the program cannot be started.
    subprocess.TimeoutExpired
        When it outlives *timeout* seconds.
    """
    completed = subprocess.run(
        argv,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdin=subprocess.DEVNULL,
        timeout=timeout,
    )
    return completed.returncode, completed.stdout, completed.stderr


def _run_gh(args: list[str], timeout: int = 30) -> tuple[int, str, str] | None:
    """Run ``gh`` with *args*; ``(exit_code, stdout, stderr)``, or ``None`` when it cannot run.

    The call shape ``cold_read_stamp.py`` uses: ``gh api`` only, never
    ``gh issue view``. Tests fake the seam; nothing else here runs ``gh``.
    """
    try:
        return _execute(["gh", *args], None, timeout)
    except (subprocess.TimeoutExpired, OSError):
        return None


def _run_git(args: list[str], cwd: str | None = None, timeout: int = 30) -> tuple[int, str, str] | None:
    """Run ``git`` with *args* in *cwd*; ``(exit_code, stdout, stderr)``, or ``None`` when it cannot run."""
    try:
        return _execute(["git", *args], cwd, timeout)
    except (subprocess.TimeoutExpired, OSError):
        return None


def _run_detector(argv: list[str], cwd: str | None, timeout: float) -> tuple[int, str, str]:
    """Run a detector command in *cwd*; ``(exit_code, stdout, stderr)``.

    A non-zero exit is the detector's finding, so it is returned, not raised.
    A command that cannot be started raises ``OSError`` and one that outlives
    *timeout* raises ``subprocess.TimeoutExpired``; ``build`` exits 4 on both.
    """
    return _execute(argv, cwd, timeout)


def _read_text(path: str, what: str) -> str:
    try:
        return Path(path).read_bytes().decode("utf-8", errors="replace")
    except OSError as error:
        raise _Fail(2, f"cannot read the {what} {path}: {error.strerror or error}") from error


def _fetch_body(repo: str, issue: int) -> str:
    """The issue body, from ``gh api repos/<repo>/issues/<issue>`` (exit 4 on any failure)."""
    call = f"gh api repos/{repo}/issues/{issue}"
    result = _run_gh(["api", f"repos/{repo}/issues/{issue}"])
    if result is None:
        raise _Fail(4, f"{call} could not be run")
    code, stdout, stderr = result
    if code != 0:
        raise _Fail(4, f"{call} failed (exit {code}): {stderr.strip()}")
    try:
        data = json.loads(stdout)
    except ValueError as error:
        raise _Fail(4, f"{call} returned invalid JSON: {error}") from error
    if not isinstance(data, dict) or "body" not in data:
        raise _Fail(4, f"{call} returned no 'body' field")
    body = data["body"]
    if body is None:
        return ""
    if not isinstance(body, str):
        raise _Fail(4, f"{call} returned a 'body' that is not text")
    return body


def _read_settings(checkout: str) -> dict:
    """``<checkout>/.afk/config.toml`` as a dict; an absent file contributes no keys."""
    path = Path(checkout) / ".afk" / "config.toml"
    if not path.is_file():
        return {}
    import tomllib

    try:
        return tomllib.loads(_read_text(str(path), "afk settings file"))
    except tomllib.TOMLDecodeError as error:
        raise _Fail(2, f"cannot parse {path}: {error}") from error


def _setting(settings: dict, key: str) -> str | None:
    value = settings.get(key)
    return value if isinstance(value, str) and value else None


def _opens_hand_built(body: str) -> bool:
    """Whether the body's first non-blank line is exactly the hand-built line."""
    for line in body.split("\n"):
        text = line[:-1] if line.endswith("\r") else line
        if text.strip():
            return text == HAND_BUILT_LINE
    return False


def _choose_branch(body: str, override: str | None, settings: dict) -> tuple[str, str]:
    """``(branch, fork_source)``: the first rule that applies."""
    if override:
        return override, "override"
    for line in body.split("\n"):
        match = TARGET_LINE_RE.search(line)
        if match:
            return match.group(1), "target-line"
    if _opens_hand_built(body):
        trunk = _setting(settings, "trunk_branch")
        if trunk:
            return trunk, "trunk_branch"
    integration = _setting(settings, "integration_target")
    if integration:
        return integration, "integration_target"
    return DEFAULT_BRANCH, "default"


def _usable_ref(name: str) -> bool:
    """A branch or ref name that cannot be read as an option and holds no ``..``."""
    return BRANCH_RE.fullmatch(name) is not None and ".." not in name


def _git_stdout(args: list[str], checkout: str, failure: str) -> str:
    """The stdout of ``git <args>`` run in the checkout; exit 4 with *failure* when it fails."""
    result = _run_git(args, checkout, GIT_TIMEOUT)
    if not result or result[0]:
        raise _Fail(4, failure)
    return result[1]


def _resolve_sha(checkout: str, branch: str) -> str:
    """The remote's SHA for *branch*, from ``git ls-remote`` and never a tracking ref."""
    ref = f"refs/heads/{branch}"
    failure = f"git ls-remote origin {ref} failed; the fork SHA could not be resolved"
    listing = _git_stdout(["ls-remote", "origin", ref], checkout, failure)
    for line in listing.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] == ref and SHA_RE.fullmatch(parts[0]):
            return parts[0]
    raise _Fail(4, f"{ref} is not on origin; the fork SHA could not be resolved")


def _archive_fork(checkout: str, branch: str, sha: str, scratch_dir: str, tree_dir: str) -> None:
    """Fetch *branch* into the checkout, then archive *sha* and extract it into *tree_dir*."""
    _git_stdout(["fetch", "origin", branch], checkout, f"git fetch origin {branch} failed in {checkout}")
    tar_path = os.path.join(scratch_dir, "fork.tar")
    failure = f"git archive of {sha} failed in {checkout}"
    _git_stdout(["archive", "--format=tar", "-o", tar_path, sha], checkout, failure)
    try:
        with tarfile.open(tar_path, "r:") as archive:
            archive.extractall(tree_dir, **_TAR_FILTER)
    except (tarfile.TarError, OSError) as error:
        raise _Fail(4, f"cannot extract the archive of {sha}: {error}") from error


def _render_comments(path: str) -> str:
    """``comments.md``: every comment that is not a cold-read verdict, with its author."""
    try:
        data = json.loads(_read_text(path, "comments file"))
    except ValueError as error:
        raise _Fail(2, f"{path} is not valid JSON: {error}") from error
    comments = data.get("comments") if isinstance(data, dict) else None
    if not isinstance(comments, list):
        raise _Fail(2, f"{path} has no 'comments' list")
    kept = []
    for comment in comments:
        if not isinstance(comment, dict):
            continue
        body = comment.get("body")
        body = body if isinstance(body, str) else ""
        if body.lstrip().startswith(VERDICT_TITLE):
            continue
        author = comment.get("author")
        login = author.get("login") if isinstance(author, dict) else None
        created = comment.get("createdAt")
        login = login if isinstance(login, str) and login else "unknown"
        created = created if isinstance(created, str) and created else "unknown"
        kept.append(f"### Comment by {login} at {created}\n\n{body}\n")
    return "\n".join(kept) if kept else NO_COMMENTS + "\n"


def _given_names(spec: str) -> list[str]:
    """The backticked section names of the spec's ``What the reader is given.`` bullet."""
    lines = spec.split("\n")
    for index, line in enumerate(lines):
        if line.lstrip().startswith(f"- **{GIVEN_BULLET}**"):
            bullet = [line]
            for follow in lines[index + 1 :]:
                if not follow.strip() or follow.lstrip().startswith(("- ", "#")):
                    break
                bullet.append(follow)
            names = re.findall(r"`([^`]+)`", " ".join(bullet))
            if names:
                return list(dict.fromkeys(names))
            break
    raise _Fail(4, f"the spec has no '{GIVEN_BULLET}' bullet naming a backticked section")


def _sections(spec: str) -> list[tuple[str, str]]:
    """``(name, text)`` for every ``## `` section in file order; a fenced ``## `` is not a heading."""
    found: list[tuple[str, list[str]]] = []
    fence = None
    for line in spec.split("\n"):
        if fence is not None:
            if line.startswith(fence) and not line.strip("`"):
                fence = None
        else:
            opening = re.match(r"`{3,}", line)
            if opening:
                fence = opening.group(0)
            elif line.startswith("## "):
                found.append((line[3:].strip(), []))
        if found:
            found[-1][1].append(line)
    return [(name, "\n".join(lines).rstrip("\n")) for name, lines in found]


def _select_sections(spec: str) -> list[tuple[str, str]]:
    """The sections the bullet names, in file order; a missing one exits 4 naming it."""
    wanted = _given_names(spec)
    chosen: list[tuple[str, str]] = []
    for name, text in _sections(spec):
        if name in wanted and name not in [done for done, _ in chosen]:
            chosen.append((name, text))
    for name in wanted:
        if name not in [done for done, _ in chosen]:
            raise _Fail(4, f"the spec has no '## {name}' section")
    return chosen


def _expand(text: str, values: dict[str, str]) -> str:
    """Replace each placeholder in *values* by its value, in one pass."""
    pattern = "|".join(re.escape(token) for token in values)
    return re.sub(pattern, lambda match: values[match.group(0)], text)


def _fence(text: str) -> str:
    """A backtick fence one longer than the longest backtick run in *text* (four at least)."""
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    return "`" * max(4, longest + 1)


def _fenced(text: str) -> str:
    fence = _fence(text)
    return f"{fence}\n{text}\n{fence}\n"


def _checkout_forms(given: str, absolute: str) -> list[str]:
    """Every spelling of the checkout path a detector might echo, longest first."""
    forms = {absolute, os.path.realpath(absolute)}
    if os.path.isabs(given):
        forms.add(given.rstrip("/"))
    return sorted((form for form in forms if form not in ("", "/")), key=len, reverse=True)


def _hide_checkout(text: str, forms: list[str]) -> str:
    for form in forms:
        text = text.replace(form, CHECKOUT_PLACEHOLDER)
    return text


def _detector(number: int, argv: list[str], cwd: str, forms: list[str]) -> tuple[int, str, str]:
    """Run one detector: ``(exit_code, stdout, command)``, the checkout path hidden in the last two."""
    command = shlex.join(argv)
    try:
        code, stdout, _stderr = _run_detector(argv, cwd, DETECTOR_TIMEOUT)
    except (subprocess.TimeoutExpired, OSError) as error:
        what = "timed out" if isinstance(error, subprocess.TimeoutExpired) else "could not be started"
        raise _Fail(4, f"detector {number} {what}: {command}") from error
    return code, _hide_checkout(stdout, forms), _hide_checkout(command, forms)


def _teeth_path(given: str | None) -> str:
    if given:
        path = os.path.abspath(given)
    else:
        parts = [str(SCRIPTS_DIR), "..", "..", "skills", "detector-teeth-check", "scripts", "teeth_check.py"]
        path = os.path.normpath(os.path.join(*parts))
    if not os.path.isfile(path):
        raise _Fail(4, f"teeth_check.py is not at {path}; pass --teeth-check FILE")
    return path


def _write(path: str, text: str) -> None:
    Path(path).write_bytes(text.encode("utf-8"))


def _run_build(args: argparse.Namespace) -> int:
    given_checkout = args.checkout
    checkout = os.path.abspath(given_checkout)
    scratch_root = os.path.abspath(args.scratch_root)
    out = os.path.abspath(args.out)
    afk = os.path.abspath(args.afk_project)
    vault = os.path.abspath(args.vault_root) if args.vault_root else None
    for flag, directory in (("--scratch-root", scratch_root), ("--checkout", checkout)):
        if not os.path.isdir(directory):
            raise _Fail(2, f"{flag} {directory} is not a directory")
    for flag, ref in (("--fork-branch", args.fork_branch), ("--detector5-ref", args.detector5_ref)):
        if ref and not _usable_ref(ref):
            raise _Fail(2, f"{flag} {ref!r} is not a usable ref name")
    spec = _read_text(args.spec, "spec file").replace("\r\n", "\n")
    comments_md = _render_comments(args.comments_json)
    settings = _read_settings(checkout)
    teeth = _teeth_path(args.teeth_check)

    body = _fetch_body(args.repo, args.issue)
    digest = body_hash(body)[:12]
    if args.expect_body is not None and args.expect_body != digest:
        raise _Fail(3, f"--expect-body {args.expect_body} does not match the body hash {digest}")

    try:
        os.makedirs(out, exist_ok=True)
    except OSError as error:
        raise _Fail(2, f"cannot create --out {out}: {error.strerror or error}") from error
    for name in ("reader.md", "manifest.json"):
        (Path(out) / name).unlink(missing_ok=True)
    body_path = os.path.join(out, "body.md")
    comments_path = os.path.join(out, "comments.md")
    _write(body_path, body)
    _write(comments_path, comments_md)

    sections = _select_sections(spec)
    branch, source = _choose_branch(body, args.fork_branch, settings)
    if not _usable_ref(branch):
        raise _Fail(4, f"the {source} branch {branch!r} is not a usable branch name")
    sha = _resolve_sha(checkout, branch)
    scratch_dir = tempfile.mkdtemp(prefix=f"cold-read-{args.issue}-", dir=scratch_root)
    tree_dir = os.path.join(scratch_dir, "tree")
    os.mkdir(tree_dir)
    _archive_fork(checkout, branch, sha, scratch_dir, tree_dir)

    ref = args.detector5_ref or sha
    forms = _checkout_forms(given_checkout, checkout)
    argv5 = [
        "uv", "run", "--with", GRAPHMARK_PIN, "--with", "pyyaml", "python",
        os.path.join(str(SCRIPTS_DIR), "cold_read_evidence.py"),
        "--repo", args.repo, "--repo-dir", checkout, "--body-file", body_path,
    ]
    if vault and "[[" in body:
        argv5 += ["--vault-root", vault]
    argv5 += ["--json", "--ref", ref]
    argv10 = [
        "uv", "run", "afk-driver", "--project", afk, "--repo", args.repo,
        "--deny-surface-check", str(args.issue), "--json",
    ]
    exit5, stdout5, command5 = _detector(5, argv5, scratch_dir, forms)
    exit10, stdout10, command10 = _detector(10, argv10, afk, forms)
    detector5_path = os.path.join(out, "detector5.json")
    detector10_path = os.path.join(out, "detector10.json")
    _write(detector5_path, stdout5)
    _write(detector10_path, stdout10)

    engine = str(SCRIPTS_DIR)
    preflight = f'python3 "{engine}/cold_read_dispatch.py" preflight --scratch {shlex.quote(scratch_dir)}'
    values = {
        "<engine>": engine,
        "<path-to-afk-agent-system>": afk,
        "<local checkout>": tree_dir,
        "<fork point SHA>": ref,
    }
    if vault:
        values["<absolute vault path>"] = vault
    spec_text = "\n\n".join(_expand(text, values) for _, text in sections) + "\n"
    dispatch = "\n".join(
        [
            "## This dispatch",
            "",
            f"- Repository: {args.repo}",
            f"- Issue: #{args.issue}",
            f"- Fork point: {branch} at {sha}",
            f"- Scratch directory: {scratch_dir}",
            f"- Tree directory: {tree_dir}",
            f"- Engine directory: {engine}",
            f"- teeth_check.py: {teeth}",
            f"- Comments file: {comments_path}",
            f"- Preflight command: {preflight}",
            "",
            "Set on every teeth_check.py run:",
            f"TEETH_CHECK_STATE_DIR={scratch_dir}/teeth-state",
            "",
        ]
    )
    lowered = (dispatch + "\n" + spec_text).lower()
    for needle in CONTRACT_NEEDLES:
        if needle in lowered:
            raise _Fail(5, f"the assembled prompt breaks the reader contract: it contains {needle!r}")

    prompt = "\n".join(
        [
            f"# Cold read of {args.repo}#{args.issue}",
            "",
            dispatch,
            "## Detector 5 command and output",
            "",
            f"Command: {command5}",
            f"Exit code: {exit5}",
            "",
            _fenced(stdout5),
            "## Detector 10 command and output",
            "",
            f"Command: {command10}",
            f"Exit code: {exit10}",
            "",
            _fenced(stdout10),
            "## Comments",
            "",
            _fenced(comments_md),
            "## Issue body",
            "",
            f"Body hash: {digest}",
            "",
            _fenced(body),
            spec_text,
        ]
    )
    prompt_path = os.path.join(out, "reader.md")
    _write(prompt_path, prompt)
    manifest = {
        "subagent_type": SUBAGENT_TYPE,
        "model": MODEL,
        "prompt_file": prompt_path,
        "body_hash": digest,
        "fork_branch": branch,
        "fork_source": source,
        "fork_sha": sha,
        "scratch_dir": scratch_dir,
        "tree_dir": tree_dir,
        "detector5": {"command": command5, "exit": exit5, "file": detector5_path},
        "detector10": {"command": command10, "exit": exit10, "file": detector10_path},
        "comments_file": comments_path,
        "preflight_command": preflight,
        "spec_sections": [name for name, _ in sections],
    }
    text = json.dumps(manifest, indent=2)
    _write(os.path.join(out, "manifest.json"), text + "\n")
    if args.json:
        print(text)
    else:
        print(f"DISPATCH issue={args.issue} body={digest} fork={branch}@{sha[:12]}")
        print(f"SCRATCH {scratch_dir}")
        print(f"PROMPT {prompt_path}")
    return 0


def _build(args: argparse.Namespace) -> int:
    try:
        return _run_build(args)
    except _Fail as failure:
        print(f"cold_read_dispatch: {failure.message}", file=sys.stderr)
        return failure.code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    preflight = commands.add_parser(
        "preflight",
        help="check the scratch directory, git and uv, and print one result line",
    )
    preflight.add_argument(
        "--scratch",
        required=True,
        metavar="DIR",
        help="the read's scratch directory",
    )
    build = commands.add_parser(
        "build",
        help="generate the reader's prompt and manifest for one issue",
    )
    for flag, metavar, help_text in (
        ("--repo", "OWNER/NAME", "the repository the issue is in"),
        ("--checkout", "DIR", "a local checkout of that repository; only fetched into"),
        ("--scratch-root", "DIR", "an existing directory to make the read's scratch directory in"),
        ("--out", "DIR", "where reader.md, manifest.json and the evidence files are written"),
        ("--spec", "FILE", "the /cold-read command.md the reader's sections come from"),
        ("--afk-project", "DIR", "the afk-agent-system checkout detector 10 runs in"),
        ("--comments-json", "FILE", "the issue's comments as gh issue view --json comments prints them"),
    ):
        build.add_argument(flag, required=True, metavar=metavar, help=help_text)
    build.add_argument("--issue", required=True, type=int, metavar="N", help="the issue number")
    build.add_argument("--expect-body", metavar="HEX12", help="the body hash the conductor recorded")
    build.add_argument("--fork-branch", metavar="BRANCH", help="fork from this branch of origin")
    build.add_argument("--detector5-ref", metavar="REF", help="the ref detector 5 resolves against")
    build.add_argument("--vault-root", metavar="DIR", help="the vault, for wikilink resolution")
    build.add_argument("--teeth-check", metavar="FILE", help="teeth_check.py, when not at its derived path")
    build.add_argument("--json", action="store_true", help="print the manifest instead of three lines")
    args = parser.parse_args(argv)
    if args.command == "build":
        return _build(args)
    return _preflight(args.scratch)


if __name__ == "__main__":
    raise SystemExit(main())
