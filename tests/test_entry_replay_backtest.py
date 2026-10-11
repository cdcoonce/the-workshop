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


# ---------------------------------------------------------------------------
# Grading an accepted merge: "same lines" is not "success"
# ---------------------------------------------------------------------------

_BASE = "# L\n\n## T\n\n### A (2026-09-03)\n\nbody a\n\n### B (2026-09-01)\n\nbody b\n"
_ORIGIN = _BASE.replace("### A", "### O (2026-09-05)\n\nbody o\n\n### A", 1)
_TIP = _BASE.replace("### B", "### N1 (2026-09-02)\n\nbody n1\n\n### N2 (2026-09-02)\n\nbody n2\n\n### B", 1)
_EXPECTED = _ORIGIN.replace("### B", "### N1 (2026-09-02)\n\nbody n1\n\n### N2 (2026-09-02)\n\nbody n2\n\n### B", 1)


def _grade(merged: str) -> tuple[str, dict[str, bool]]:
    return backtest.classify_merge(merged, _EXPECTED, _BASE, _TIP, _ORIGIN)


def test_classify_exact() -> None:
    bucket, flags = _grade(_EXPECTED)
    assert bucket == "exact" and not any(flags.values())


def test_classify_blank_line_damage_is_order_preserving_but_flagged() -> None:
    glued = _EXPECTED.replace("body n1\n\n### N2", "body n1\n### N2")
    bucket, flags = _grade(glued)
    assert bucket == "order-preserving"
    assert flags["blank_damaged"] and not flags["relocated"] and not flags["lines_differ"]


def test_classify_a_relocated_entry_is_flagged_even_though_the_orders_hold() -> None:
    moved = _ORIGIN + "\n### N1 (2026-09-02)\n\nbody n1\n\n### N2 (2026-09-02)\n\nbody n2\n"
    bucket, flags = _grade(moved)
    assert bucket == "order-preserving" and flags["relocated"]


def test_classify_the_sessions_own_lines_reordered_is_not_order_preserving() -> None:
    swapped = _EXPECTED.replace("### N1 (2026-09-02)\n\nbody n1\n\n", "@@").replace(
        "### N2 (2026-09-02)\n\nbody n2\n\n", "### N2 (2026-09-02)\n\nbody n2\n\n### N1 (2026-09-02)\n\nbody n1\n\n"
    ).replace("@@", "")
    bucket, flags = _grade(swapped)
    assert bucket == "blank-structure-equal" and flags["relocated"]


def test_classify_a_lost_line_is_other() -> None:
    bucket, flags = _grade(_EXPECTED.replace("body n2\n", ""))
    assert bucket == "other" and flags["lines_differ"]


def test_classify_origins_lines_reordered_is_not_order_preserving() -> None:
    reordered = _EXPECTED.replace("### O (2026-09-05)\n\nbody o\n\n", "").replace(
        "### B (2026-09-01)\n\nbody b\n", "### B (2026-09-01)\n\nbody b\n\n### O (2026-09-05)\n\nbody o\n"
    )
    # O moves below B: origin's own line order (O before A before B) is broken.
    bucket, _flags = _grade(reordered)
    assert bucket == "blank-structure-equal"


# ---------------------------------------------------------------------------
# Self-replay: origin == base must give back the commit byte for byte
# ---------------------------------------------------------------------------


def test_self_replay_counts_a_hub_commit_as_exact(
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
    ledger.write_text(
        LEDGER.replace("### Old", _entry("Session gotcha", "2026-09-20") + "### Old"),
        encoding="utf-8",
    )
    _git(vault, "commit", "-qam", "session wrap-up")

    rc = backtest.main(
        ["--vault", str(vault), "--since", "2020-01-01", "--baseline-ref", "HEAD", "--ref", "main"]
    )

    out = capsys.readouterr().out
    assert rc == 0
    assert "self-replay (origin == base)" in out
    section = out.split("self-replay (origin == base)", 1)[1]
    assert "hub-file commits" in section and "brain/Gotchas.md" in section
    exact_row = next(line for line in section.splitlines() if line.strip().startswith("exact"))
    assert exact_row.split()[-1] == "1"  # the candidate (last column) reproduces the commit
    inexact_row = next(line for line in section.splitlines() if line.strip().startswith("inexact"))
    assert inexact_row.split()[-1] == "0"
