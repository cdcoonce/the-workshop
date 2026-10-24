"""Shared fakes for the hold_scan tests.

``gh`` and ``glab`` never run for real: ``hold_scan._run`` is replaced by a
``Stub`` that answers scripted calls and fails the test on anything unscripted.
The stub serves at most 100 items per paged call and honours ``page=K`` only
when the endpoint asks for it, so a build that fetches page 1 alone goes red.
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hold_scan  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
NOW = datetime(2026, 10, 22, 12, 0, 0, tzinfo=timezone.utc)


def comment(body, ts="2026-08-17T00:54:25Z", url="https://x/c/1"):
    """Return a conversation-comment dict in the GitHub REST shape."""
    return {"user": {"login": "u"}, "created_at": ts, "html_url": url, "body": body}


def load(name):
    """Load a committed JSON fixture."""
    return json.loads((FIXTURES / name).read_text())


class Stub:
    """Scripted stand-in for ``hold_scan._run``."""

    def __init__(self):
        self.calls = []
        self.api = {}  # endpoint path (no query) -> full list/dict payload
        self.prs = {}  # (repo, n) -> {"closing": [..], "createdAt": .., "state": ..}
        self.issues = {}  # (repo, m) -> {"labels": [..names], "body": str}
        self.failing = []  # substrings; a call whose joined argv has one fails

    def pr(self, repo, n, closing=(), created="2026-10-20T00:00:00Z", state="OPEN"):
        self.prs[(repo, n)] = {"closing": list(closing), "createdAt": created, "state": state}

    def issue(self, repo, m, labels=(), body=""):
        self.issues[(repo, m)] = {"labels": list(labels), "body": body}

    def thread(self, repo, n, comments=(), reviews=(), inline=()):
        self.api[f"repos/{repo}/issues/{n}/comments"] = list(comments)
        self.api[f"repos/{repo}/pulls/{n}/reviews"] = list(reviews)
        self.api[f"repos/{repo}/pulls/{n}/comments"] = list(inline)

    def __call__(self, argv):
        self.calls.append(list(argv))
        joined = " ".join(argv)
        if any(f in joined for f in self.failing):
            return 1, "", "boom"
        if argv[:2] in (["gh", "api"], ["glab", "api"]):
            path, _, query = argv[2].partition("?")
            payload = self.api.get(path)
            assert payload is not None, f"unscripted api call: {argv}"
            if isinstance(payload, list) and query:
                q = dict(p.split("=") for p in query.split("&"))
                page = int(q.get("page", "1"))
                payload = payload[(page - 1) * 100 : page * 100]
            return 0, json.dumps(payload), ""
        if argv[:3] == ["gh", "pr", "view"]:
            rec = self.prs[(argv[argv.index("--repo") + 1], int(argv[3]))]
            return 0, json.dumps({
                "closingIssuesReferences": [{"number": m} for m in rec["closing"]],
                "createdAt": rec["createdAt"], "state": rec["state"],
            }), ""
        if argv[:3] == ["gh", "issue", "view"]:
            rec = self.issues[(argv[argv.index("--repo") + 1], int(argv[3]))]
            return 0, json.dumps({"labels": [{"name": n} for n in rec["labels"]], "body": rec["body"]}), ""
        raise AssertionError(f"unscripted call: {argv}")


@pytest.fixture
def stub(monkeypatch):
    s = Stub()
    monkeypatch.setattr(hold_scan, "_run", s)
    monkeypatch.setattr(hold_scan, "_now", lambda: NOW)
    return s


@pytest.fixture
def no_vault(tmp_path, monkeypatch):
    """HOME, CLAUDE_PROJECT_DIR, PWD and cwd are all empty temp dirs."""
    empty = tmp_path / "empty"
    empty.mkdir()
    for k in ("HOME", "CLAUDE_PROJECT_DIR", "PWD"):
        monkeypatch.setenv(k, str(empty))
    monkeypatch.chdir(empty)
    return empty


@pytest.fixture
def vault(tmp_path, no_vault, monkeypatch):
    """The committed fixture vault, found by walk-up, with its alias config."""
    root = tmp_path / "vault"
    shutil.copytree(FIXTURES / "vault", root)
    cfg = no_vault / ".workshop" / "hold-scan"
    cfg.mkdir(parents=True)
    shutil.copy(FIXTURES / "hold-scan.toml", cfg / "hold-scan.toml")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    return root


def scan(*argv):
    """Run main() with --json and return (exit_code, parsed output)."""
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        code = hold_scan.main([*argv, "--json"])
    return code, json.loads(buf.getvalue())


def write_note(root, rel, text):
    """Write a synthetic vault note at *rel* under *root*."""
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def gh(repo, n):
    """Return the argv tail for a GitHub scan."""
    return ("--repo", repo, "--pr", str(n))
