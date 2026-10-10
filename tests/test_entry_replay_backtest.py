"""Smoke test for the entry-replay backtest rig, against a synthetic vault.

The real measurement needs a real vault, so it is run by hand (see the
module docstring of ``scripts/entry_replay_backtest.py``). What is cheap to
pin here is the plumbing: a conflicted, aborted rebase leaves a
``rebase (start)`` reflog line, the rig finds it, runs the baseline and the
working-tree module as two separate instances, and counts the event.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts import entry_replay_backtest as backtest

LEDGER = """\
# Gotchas

## Technical

### Old gotcha (2026-09-01)

Old body.
"""


def _git(repo: Path, *args: str, check: bool = True) -> None:
    subprocess.run(["git", *args], cwd=repo, check=check, capture_output=True, text=True)


def _entry(title: str, day: str) -> str:
    return f"### {title} ({day})\n\n{title} body.\n\n"


def _isolate_git(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in {
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }.items():
        monkeypatch.setenv(key, value)


def test_isolated_instances_are_distinct_modules() -> None:
    first = backtest.load_candidate()
    second = backtest.load_candidate()
    assert first is not second
    assert first.RefusalError is not second.RefusalError


def test_backtest_counts_a_concurrent_hub_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _isolate_git(monkeypatch)
    vault = tmp_path / "vault"
    vault.mkdir()
    _git(vault, "init", "-q", "-b", "main")
    ledger = vault / "brain" / "Gotchas.md"
    ledger.parent.mkdir()
    ledger.write_text(LEDGER, encoding="utf-8")
    _git(vault, "add", "-A")
    _git(vault, "commit", "-q", "-m", "seed")

    _git(vault, "switch", "-q", "-c", "session")
    ledger.write_text(
        LEDGER.replace("### Old", _entry("Session gotcha", "2026-09-20") + "### Old"),
        encoding="utf-8",
    )
    _git(vault, "commit", "-qam", "session wrap-up")

    _git(vault, "switch", "-q", "main")
    ledger.write_text(
        LEDGER.replace("### Old", _entry("Origin gotcha", "2026-09-19") + "### Old"),
        encoding="utf-8",
    )
    _git(vault, "commit", "-qam", "origin wrap-up")

    _git(vault, "switch", "-q", "session")
    _git(vault, "rebase", "main", check=False)  # conflicts on the hub file
    _git(vault, "rebase", "--abort")

    rc = backtest.main(
        ["--vault", str(vault), "--since", "2020-01-01", "--baseline-ref", "HEAD", "--ref", "main"]
    )

    out = capsys.readouterr().out
    assert rc == 0
    assert "hub-only-events" in out
    assert "events accepted" in out
    assert "1/1" in out
    assert "invariant violations" in out
