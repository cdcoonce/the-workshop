"""Shared fixtures: a fake `glab` on PATH routed by API-path substring.

Process-boundary behaviour (stderr noise, nonzero exits, raw non-JSON traces)
is what these scripts must survive, so glab is faked as a binary, not mocked.
Routes live in routes.json as {substring: response}; the longest matching
substring wins. A response is {"json": ...}, {"raw": "text"}, or
{"exit": N}. Every argv is appended to calls.log for call assertions.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

FAKE_GLAB = '''#!/usr/bin/env python3
import json, os, sys

state = os.environ["FAKE_GLAB_DIR"]
with open(os.path.join(state, "calls.log"), "a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")

path = sys.argv[2] if len(sys.argv) > 2 else ""
with open(os.path.join(state, "routes.json")) as fh:
    routes = json.load(fh)
matches = [key for key in routes if key in path]
if not matches:
    sys.stderr.write("fake glab: no route for %s\\n" % path)
    sys.exit(70)
response = routes[max(matches, key=len)]
if "exit" in response:
    sys.stderr.write("fake glab: scripted failure\\n")
    sys.exit(response["exit"])
if "raw" in response:
    sys.stdout.write(response["raw"])
else:
    sys.stdout.write(json.dumps(response["json"]))
'''

REMOTE = "git@gitlab.com:group/project.git"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "feat/thing")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "file.txt").write_text("content\n")
    _git(repo, "add", "file.txt")
    _git(repo, "commit", "-q", "-m", "initial")
    _git(repo, "remote", "add", "origin", REMOTE)
    return repo


class FakeGlab:
    def __init__(self, state: Path, env: dict[str, str], repo: Path) -> None:
        self.state = state
        self.env = env
        self.repo = repo

    def route(self, **routes: dict) -> None:
        """Routes keyed by substring; `__` in a kwarg stands for `/`."""
        table = {key.replace("__", "/"): value for key, value in routes.items()}
        (self.state / "routes.json").write_text(json.dumps(table))

    def calls(self) -> list[list[str]]:
        text = (self.state / "calls.log").read_text()
        return [json.loads(line) for line in text.splitlines()]

    def run(self, script: str, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCRIPTS / script), *args],
            cwd=self.repo,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=60,
        )


@pytest.fixture
def glab(tmp_path: Path, repo: Path) -> FakeGlab:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "glab"
    fake.write_text(FAKE_GLAB)
    fake.chmod(0o755)
    state = tmp_path / "glab-state"
    state.mkdir()
    (state / "calls.log").write_text("")
    (state / "routes.json").write_text("{}")
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "FAKE_GLAB_DIR": str(state),
    }
    return FakeGlab(state, env, repo)
