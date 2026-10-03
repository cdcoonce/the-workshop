"""Shared guarded glab helpers for the compact GitLab scripts.

Every call collapses any failure shape (nonzero exit, empty stdout, bad JSON)
to None, so a caller reports "unavailable" instead of crashing or, worse,
reading a failure as an empty result. The project is derived from the remote
URL and passed explicitly, so glab's own remote inference (alphabetically
first when several gitlab.com remotes exist) never picks the wrong repo.
"""

from __future__ import annotations

import json
import subprocess
import urllib.parse
from typing import NoReturn

GREEN = 0
RED = 1
INDETERMINATE = 2

PAGE_SIZE = 100
MAX_PAGES = 10


def say(message: str) -> None:
    """Print one line to stdout, flushed."""
    print(message, flush=True)


def fail_setup(message: str) -> NoReturn:
    """Exit INDETERMINATE: a run that never got an answer is not a verdict."""
    say(message)
    raise SystemExit(INDETERMINATE)


def run(args: list[str]) -> tuple[int, str, str]:
    """Run a command and return (exit code, stdout, stderr), stripped."""
    result = subprocess.run(args, capture_output=True, text=True)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def glab_raw(path: str) -> str | None:
    """Raw text of one API call, or None on any failure."""
    code, stdout, _stderr = run(["glab", "api", path])
    if code != 0 or not stdout:
        return None
    return stdout


def glab_json(path: str) -> object | None:
    """Parsed JSON of one API call, or None on any failure."""
    raw = glab_raw(path)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def glab_list(path: str) -> list[dict] | None:
    """Every page of a list endpoint, or None if any page fails or pages run out.

    An incomplete listing returns None rather than a partial list: callers
    must never mistake "I only saw the first pages" for "that is everything".
    """
    separator = "&" if "?" in path else "?"
    entries: list[dict] = []
    for page in range(1, MAX_PAGES + 1):
        data = glab_json(f"{path}{separator}per_page={PAGE_SIZE}&page={page}")
        if not isinstance(data, list):
            return None
        entries.extend(data)
        if len(data) < PAGE_SIZE:
            return entries
    return None


def parse_project_path(url: str) -> str | None:
    """Namespace path from a GitLab remote URL (ssh scp-form, ssh://, https)."""
    if "://" in url:
        path = urllib.parse.urlsplit(url).path
    elif ":" in url:
        path = url.split(":", 1)[1]
    else:
        return None
    path = path.strip("/")
    if path.endswith(".git"):
        path = path[: -len(".git")]
    return path or None


def resolve_project(remote: str, override: str | None) -> str:
    """URL-encoded project path for the API, from --project or the remote URL."""
    if override:
        return urllib.parse.quote(override, safe="")
    code, url, stderr = run(["git", "remote", "get-url", remote])
    if code != 0:
        fail_setup(f"cannot read remote {remote!r}: {stderr}")
    path = parse_project_path(url)
    if path is None:
        fail_setup(f"cannot derive a project path from remote URL {url!r}; pass --project")
    return urllib.parse.quote(path, safe="")
