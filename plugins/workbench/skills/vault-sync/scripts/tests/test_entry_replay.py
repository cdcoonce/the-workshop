"""End-to-end tests for entry_replay.py against real git repositories.

Every integration scenario builds a bare "remote" plus two clones -- ``local``
is the session's vault, ``peer`` stands in for the other same-day sessions and
the second machine whose pushes moved origin/main. The peer pushes first, the
local session commits its wrap-up, and the script runs as a subprocess from
the local root, exactly as /sync's conflict fallback does (issue #893).

The assertions are about repository state and file content, not script
output: which entries the merged ledger holds and in what date order, which
handoff sections came from which side, whether a refused run left the vault
byte-for-byte untouched on its original branch.

Fail-closed is the contract under test: ``replayed`` and ``none`` exit 0,
every refusal exits 1 and restores the repository, and the three teeth from
issue #893 each have a named test here:

- concurrent disjoint inserts under one anchor -> replay succeeds, both
  entries present, dates newest-first;
- a semantic overlap (the session edited an existing entry) -> refused;
- an origin-side edit inside a replaced span -> the per-entry / per-section
  base assertion fires.

Git environment is isolated (no global/system config) so results do not
depend on the developer's gpgsign, hooks path, or default branch settings.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))

from entry_replay import (  # noqa: E402
    RefusalError,
    handoff_merge,
    is_allowlisted,
    ledger_merge,
    merge_descriptions,
    parse_entry_start,
)

SCRIPT = SCRIPTS_DIR / "entry_replay.py"

GOTCHAS = "brain/Gotchas.md"
DECISIONS = "brain/Key Decisions.md"
BRAG = "perf/Brag Doc.md"
HANDOFF = ".brain/handoff-personal.md"


# ---------------------------------------------------------------------------
# Seed vault content -- miniature but shape-faithful copies of the four hubs.
# ---------------------------------------------------------------------------

GOTCHAS_SEED = """\
---
date: 2026-04-04
description: "Pitfalls and things that burned you before"
tags:
  - gotchas
---

# Gotchas

Recurring pitfalls. Link to [[Memories]].

## Technical

### Stale tracking refs lie after a push (2026-09-15)

Body of the tracking-ref gotcha.
Second line of that body.

### Bytecode cache hides a mutation (2026-09-10)

Body of the bytecode gotcha.

## Process

### Review packets retired (2026-09-01)

Body of the process gotcha.
"""

DECISIONS_SEED = """\
---
date: 2026-04-04
description: "Log of significant decisions"
tags:
  - decisions
---

# Key Decisions

Significant decisions. Link to [[Memories]].

## Recent

### 2026-09-15 — Adopt the sync-boundary squash

**Decided:** collapse unpushed session commits at the boundary.

**Why:** a conflicted rebase should replay one commit, not six.

### 2026-09-10 — Pin graphmark below 0.8

**Decided:** pin it, with a parity gate.
"""

BRAG_SEED = """\
---
date: 2026-04-04
description: "Running log of impact and wins"
tags:
  - brag-doc
---

# Brag Doc

Running log of impact. See [[North Star]].

## Q3 2026

### Wins

- **2026-09-15 ([[proj-a]]) — Shipped the boundary squash.** One commit rides
  the rebase now, with the guard teeth to prove it.
- **2026-09-10 ([[proj-b]]) — Fixed the parity gate.** Counted the tests.

### Growth

- **2026-09-05 — Learned the fetch-objects path.** Notes on ls-remote.

## Q2 2026

### Wins

- **2026-06-15 — Old quarter win.** Kept for archive shape.
"""

HANDOFF_SEED = """\
---
date: 2026-09-15
description: "Personal digest; proj-a shipped the squash 2026-09-15; proj-b parity gate is green"
tags: [handoff]
---
# Orchestrator Handoff — Personal

_Updated 2026-09-15._

## Resume from here

[[proj-a]]: continue the rollout from the squash landing.

## What's running

Nothing unattended.

## Open threads

- [[proj-a]]: watch the deploy.
- [[proj-b]]: close the parity ticket.

## Mode

Vault first, implementation in repository.
"""

NOTE_SEED = "---\ndate: 2026-09-01\n---\n\n# Project A\n\nSeed note body.\n"


def gotchas_entry(title: str, day: str, body: str) -> str:
    """A Gotchas-shaped entry chunk: trailing ``(YYYY-MM-DD)`` date."""
    return f"### {title} ({day})\n\n{body}\n"


def decisions_entry(day: str, title: str, body: str) -> str:
    """A Key-Decisions-shaped entry chunk: leading date in the heading."""
    return f"### {day} — {title}\n\n{body}\n"


def brag_entry(day: str, text: str) -> str:
    """A Brag-Doc-shaped entry chunk: dated bold bullet with continuation."""
    return f"- **{day} ([[proj-x]]) — {text}.** Detail line.\n  Indented continuation.\n"


def insert_under(text: str, anchor: str, chunk: str) -> str:
    """Insert ``chunk`` directly under ``anchor`` heading (issue #871 style)."""
    marker = f"{anchor}\n\n"
    at = text.index(marker) + len(marker)
    return text[:at] + chunk + "\n" + text[at:]


# ---------------------------------------------------------------------------
# Git fixture helpers (same isolation idiom as the #892 squash suite).
# ---------------------------------------------------------------------------


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_SYSTEM=os.devnull,
        GIT_AUTHOR_NAME="Test",
        GIT_AUTHOR_EMAIL="test@example.com",
        GIT_COMMITTER_NAME="Test",
        GIT_COMMITTER_EMAIL="test@example.com",
    )
    return env


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        env=_env(),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _write(repo: Path, rel: str, text: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _commit_all(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _read(repo: Path, rel: str) -> str:
    return (repo / rel).read_text(encoding="utf-8")


def _make_vault(tmp_path: Path) -> tuple[Path, Path, Path, str]:
    """Bare remote plus local and peer clones seeded with the four hub files.

    Returns ``(remote, local, peer, base)`` where ``base`` is the pushed seed
    commit -- the session base the wrap-up audit tracks.
    """
    remote = tmp_path / "remote.git"
    remote.mkdir()
    _git(remote, "init", "-q", "--bare", "-b", "main")
    local = tmp_path / "local"
    _git(tmp_path, "clone", "-q", str(remote), str(local))
    _git(local, "symbolic-ref", "HEAD", "refs/heads/main")
    _write(local, GOTCHAS, GOTCHAS_SEED)
    _write(local, DECISIONS, DECISIONS_SEED)
    _write(local, BRAG, BRAG_SEED)
    _write(local, HANDOFF, HANDOFF_SEED)
    _write(local, "personal/projects/proj-a.md", NOTE_SEED)
    base = _commit_all(local, "seed vault")
    _git(local, "push", "-q", "-u", "origin", "main")
    peer = tmp_path / "peer"
    _git(tmp_path, "clone", "-q", str(remote), str(peer))
    return remote, local, peer, base


def _peer_push(peer: Path, message: str = "peer wrap-up") -> str:
    sha = _commit_all(peer, message)
    _git(peer, "push", "-q")
    return sha


def _run_raw(local: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=local,
        env=_env(),
        capture_output=True,
        text=True,
    )


def _run_replay(
    local: Path, base: str, *extra: str, expect_rc: int = 0
) -> dict:
    result = _run_raw(local, "--base", base, "--json", *extra)
    assert result.returncode == expect_rc, (
        f"rc={result.returncode} stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    return json.loads(result.stdout)


def _head(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD")


def _branch(repo: Path) -> str:
    return _git(repo, "symbolic-ref", "--short", "HEAD")


def _entry_dates_under(text: str, anchor: str, next_heading: str | None) -> list[str]:
    """Dates of entry-start lines between ``anchor`` and ``next_heading``."""
    block = text.split(anchor + "\n", 1)[1]
    if next_heading is not None:
        block = block.split(next_heading + "\n", 1)[0]
    dates = []
    for line in block.splitlines():
        started = parse_entry_start(line)
        if started is not None:
            dates.append(started[2])
    return dates


def _assert_untouched(local: Path, head_before: str, branch_before: str) -> None:
    assert _head(local) == head_before, "a refusal must not move HEAD"
    assert _branch(local) == branch_before, "a refusal must not switch branches"
    assert _git(local, "status", "--porcelain") == "", "a refusal must leave the tree clean"
    branches = _git(local, "branch", "--list", "sync-entry-replay/*")
    assert branches == "", "a refusal must not leave a replay branch behind"


HEALTH_OK = "import sys\nsys.exit(0)\n"
HEALTH_RECORDING = """\
import pathlib
import subprocess
head = subprocess.run(
    ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
).stdout.strip()
ledger = pathlib.Path("brain/Key Decisions.md").read_text(encoding="utf-8")
pathlib.Path("{marker}").write_text(head + "\\n---\\n" + ledger, encoding="utf-8")
raise SystemExit(0)
"""
HEALTH_FAIL = "import sys\nsys.exit(1)\n"


def _health_args(tmp_path: Path, script_body: str) -> list[str]:
    stub = tmp_path / "health_stub.py"
    stub.write_text(script_body, encoding="utf-8")
    return ["--health-cmd", f"{sys.executable} {stub}"]


# ---------------------------------------------------------------------------
# Tooth 1 -- concurrent disjoint inserts under the same anchor replay cleanly.
# ---------------------------------------------------------------------------


def test_concurrent_disjoint_inserts_same_anchor_replay_succeeds(tmp_path: Path) -> None:
    _remote, local, peer, base = _make_vault(tmp_path)
    peer_chunk = decisions_entry("2026-09-20", "Peer session decision", "**Decided:** peer thing.")
    _write(peer, DECISIONS, insert_under(_read(peer, DECISIONS), "## Recent", peer_chunk))
    origin_head = _peer_push(peer)
    # The session's entry is OLDER than the peer's, so only the date re-sort
    # can produce the right order -- top-insertion alone would get it wrong.
    session_chunk = decisions_entry(
        "2026-09-18", "Session decision", "**Decided:** session thing."
    )
    _write(local, DECISIONS, insert_under(_read(local, DECISIONS), "## Recent", session_chunk))
    tip = _commit_all(local, "vault wrap-up 2026-09-20")

    report = _run_replay(local, base, *_health_args(tmp_path, HEALTH_OK))

    assert report["action"] == "replayed"
    assert report["old_head"] == tip
    assert report["origin_head"] == origin_head
    merged = _read(local, DECISIONS)
    assert peer_chunk in merged, "origin's concurrent entry must survive"
    assert session_chunk in merged, "the session's entry must be re-inserted"
    dates = _entry_dates_under(merged, "## Recent", None)
    assert dates == ["2026-09-20", "2026-09-18", "2026-09-15", "2026-09-10"]
    assert dates == sorted(dates, reverse=True), "entries must run newest-first"
    # The replay commit sits on origin's head, so the push is a fast-forward.
    assert _git(local, "rev-parse", "HEAD^") == origin_head
    assert _branch(local) == "main"
    assert _git(local, "status", "--porcelain") == ""
    assert report["files"][DECISIONS]["inserted"] == 1


def test_equal_dates_keep_session_entry_above_origin_entry(tmp_path: Path) -> None:
    _remote, local, peer, base = _make_vault(tmp_path)
    peer_chunk = decisions_entry("2026-09-20", "Peer same-day decision", "**Decided:** peer.")
    _write(peer, DECISIONS, insert_under(_read(peer, DECISIONS), "## Recent", peer_chunk))
    _peer_push(peer)
    session_chunk = decisions_entry("2026-09-20", "Session same-day decision", "**Decided:** me.")
    _write(local, DECISIONS, insert_under(_read(local, DECISIONS), "## Recent", session_chunk))
    _commit_all(local, "vault wrap-up 2026-09-20")

    _run_replay(local, base, *_health_args(tmp_path, HEALTH_OK))

    merged = _read(local, DECISIONS)
    assert merged.index("Session same-day decision") < merged.index("Peer same-day decision")


def test_replay_relinearizes_an_origin_block_with_ordering_drift(tmp_path: Path) -> None:
    """The date-sort is what reconciles the replay with #871: even drift that
    arrived from origin's side leaves the merged anchor newest-first."""
    _remote, local, peer, base = _make_vault(tmp_path)
    # Peer appends at the wrong end -- the exact drift #871 exists to stop.
    drifted = _read(peer, DECISIONS) + "\n" + decisions_entry(
        "2026-09-19", "Appended at the wrong end", "**Decided:** drift."
    )
    _write(peer, DECISIONS, drifted)
    _peer_push(peer)
    session_chunk = decisions_entry("2026-09-17", "Session decision", "**Decided:** mine.")
    _write(local, DECISIONS, insert_under(_read(local, DECISIONS), "## Recent", session_chunk))
    _commit_all(local, "vault wrap-up 2026-09-20")

    _run_replay(local, base, *_health_args(tmp_path, HEALTH_OK))

    dates = _entry_dates_under(_read(local, DECISIONS), "## Recent", None)
    assert dates == ["2026-09-19", "2026-09-17", "2026-09-15", "2026-09-10"]


def test_multiple_ledgers_and_anchors_replay_in_one_run(tmp_path: Path) -> None:
    _remote, local, peer, base = _make_vault(tmp_path)
    _write(
        peer,
        GOTCHAS,
        insert_under(
            _read(peer, GOTCHAS),
            "## Technical",
            gotchas_entry("Peer gotcha", "2026-09-19", "Peer body."),
        ),
    )
    _write(
        peer,
        BRAG,
        insert_under(_read(peer, BRAG), "### Wins", brag_entry("2026-09-19", "Peer win")),
    )
    _peer_push(peer)

    tech_chunk = gotchas_entry("Session tech gotcha", "2026-09-20", "Tech body.")
    proc_chunk = gotchas_entry("Session process gotcha", "2026-09-20", "Process body.")
    gotchas = insert_under(_read(local, GOTCHAS), "## Technical", tech_chunk)
    gotchas = insert_under(gotchas, "## Process", proc_chunk)
    _write(local, GOTCHAS, gotchas)
    brag_chunk = brag_entry("2026-09-20", "Session win")
    _write(local, BRAG, insert_under(_read(local, BRAG), "### Wins", brag_chunk))
    _commit_all(local, "vault wrap-up 2026-09-20")

    report = _run_replay(local, base, *_health_args(tmp_path, HEALTH_OK))

    assert report["action"] == "replayed"
    merged_gotchas = _read(local, GOTCHAS)
    assert tech_chunk in merged_gotchas
    assert proc_chunk in merged_gotchas
    assert "Peer gotcha" in merged_gotchas
    tech_dates = _entry_dates_under(merged_gotchas, "## Technical", "## Process")
    assert tech_dates == ["2026-09-20", "2026-09-19", "2026-09-15", "2026-09-10"]
    proc_dates = _entry_dates_under(merged_gotchas, "## Process", None)
    assert proc_dates == ["2026-09-20", "2026-09-01"]
    merged_brag = _read(local, BRAG)
    assert brag_chunk in merged_brag
    assert "Peer win" in merged_brag
    # The Q3 Wins block was merged; the Q2 Wins block (same heading text,
    # different heading path) is untouched.
    q3_wins = _entry_dates_under(merged_brag, "### Wins", "### Growth")
    assert q3_wins == ["2026-09-20", "2026-09-19", "2026-09-15", "2026-09-10"]
    assert "Old quarter win" in merged_brag
    assert report["files"][GOTCHAS]["inserted"] == 2
    assert report["files"][BRAG]["inserted"] == 1


def test_duplicate_entry_already_on_origin_is_skipped(tmp_path: Path) -> None:
    """Idempotency: a byte-identical entry origin already holds (a re-run, or
    the other machine replaying first) is not inserted twice."""
    _remote, local, peer, base = _make_vault(tmp_path)
    shared_chunk = decisions_entry("2026-09-20", "Shared decision", "**Decided:** same bytes.")
    peer_only = decisions_entry("2026-09-19", "Peer only decision", "**Decided:** peer.")
    peer_text = insert_under(_read(peer, DECISIONS), "## Recent", shared_chunk)
    peer_text = insert_under(peer_text, "## Recent", peer_only)
    _write(peer, DECISIONS, peer_text)
    _peer_push(peer)
    _write(local, DECISIONS, insert_under(_read(local, DECISIONS), "## Recent", shared_chunk))
    _commit_all(local, "vault wrap-up 2026-09-20")

    report = _run_replay(local, base, *_health_args(tmp_path, HEALTH_OK))

    assert report["action"] == "replayed"
    merged = _read(local, DECISIONS)
    assert merged.count("Shared decision") == 1
    assert report["files"][DECISIONS]["inserted"] == 0
    assert report["files"][DECISIONS]["duplicates_skipped"] == 1


# ---------------------------------------------------------------------------
# Tooth 2 -- a semantic overlap refuses: the session edited an existing entry.
# ---------------------------------------------------------------------------


def test_session_edit_of_existing_entry_refuses(tmp_path: Path) -> None:
    _remote, local, peer, base = _make_vault(tmp_path)
    _write(
        peer,
        DECISIONS,
        insert_under(
            _read(peer, DECISIONS),
            "## Recent",
            decisions_entry("2026-09-20", "Peer decision", "**Decided:** peer."),
        ),
    )
    _peer_push(peer)
    # Both sides now hold the 2026-09-15 entry; the session corrects it in
    # place (the 2455bf8c shape) -- a real semantic conflict, so escalate.
    _write(
        local,
        DECISIONS,
        _read(local, DECISIONS).replace(
            "collapse unpushed session commits", "collapse ALL session commits"
        ),
    )
    _commit_all(local, "vault wrap-up 2026-09-20")
    head_before, branch_before = _head(local), _branch(local)

    report = _run_replay(local, base, *_health_args(tmp_path, HEALTH_OK), expect_rc=1)

    assert report["action"] == "refused"
    assert "non-insertion" in report["reason"]
    assert DECISIONS in report["reason"] or DECISIONS in str(report.get("files", {}))
    _assert_untouched(local, head_before, branch_before)


def test_non_insertion_ledger_hunk_refuses_even_without_overlap(tmp_path: Path) -> None:
    """An in-place correction is refused on its own shape, not only when the
    other side happens to touch the same entry."""
    _remote, local, peer, base = _make_vault(tmp_path)
    _write(
        peer,
        GOTCHAS,
        insert_under(
            _read(peer, GOTCHAS),
            "## Technical",
            gotchas_entry("Peer gotcha", "2026-09-19", "Peer body."),
        ),
    )
    _peer_push(peer)
    session_text = _read(local, GOTCHAS).replace(
        "Body of the bytecode gotcha.", "Corrected body of the bytecode gotcha."
    )
    session_text = insert_under(
        session_text,
        "## Technical",
        gotchas_entry("Session gotcha", "2026-09-20", "Session body."),
    )
    _write(local, GOTCHAS, session_text)
    _commit_all(local, "vault wrap-up 2026-09-20")
    head_before, branch_before = _head(local), _branch(local)

    report = _run_replay(local, base, *_health_args(tmp_path, HEALTH_OK), expect_rc=1)

    assert report["action"] == "refused"
    assert "non-insertion" in report["reason"]
    _assert_untouched(local, head_before, branch_before)


def test_session_deleting_an_entry_refuses(tmp_path: Path) -> None:
    _remote, local, peer, base = _make_vault(tmp_path)
    _write(
        peer,
        DECISIONS,
        insert_under(
            _read(peer, DECISIONS),
            "## Recent",
            decisions_entry("2026-09-20", "Peer decision", "**Decided:** peer."),
        ),
    )
    _peer_push(peer)
    pruned = _read(local, DECISIONS).replace(
        "### 2026-09-10 — Pin graphmark below 0.8\n\n**Decided:** pin it, with a parity gate.\n",
        "",
    )
    _write(local, DECISIONS, pruned)
    _commit_all(local, "vault wrap-up 2026-09-20")
    head_before, branch_before = _head(local), _branch(local)

    report = _run_replay(local, base, *_health_args(tmp_path, HEALTH_OK), expect_rc=1)

    assert report["action"] == "refused"
    assert "non-insertion" in report["reason"]
    _assert_untouched(local, head_before, branch_before)


# ---------------------------------------------------------------------------
# Tooth 3 -- an origin-side edit inside a replaced span fires the assertion.
# ---------------------------------------------------------------------------


def test_origin_edit_of_existing_entry_fires_base_assertion(tmp_path: Path) -> None:
    """The session side is perfectly clean (pure insertion); origin corrected
    an existing entry inside the block the replay would rewrite."""
    _remote, local, peer, base = _make_vault(tmp_path)
    _write(
        peer,
        DECISIONS,
        _read(peer, DECISIONS).replace(
            "pin it, with a parity gate.", "pin it, with TWO parity gates."
        ),
    )
    _peer_push(peer)
    _write(
        local,
        DECISIONS,
        insert_under(
            _read(local, DECISIONS),
            "## Recent",
            decisions_entry("2026-09-20", "Session decision", "**Decided:** mine."),
        ),
    )
    _commit_all(local, "vault wrap-up 2026-09-20")
    head_before, branch_before = _head(local), _branch(local)

    report = _run_replay(local, base, *_health_args(tmp_path, HEALTH_OK), expect_rc=1)

    assert report["action"] == "refused"
    assert "byte-identical" in report["reason"]
    _assert_untouched(local, head_before, branch_before)


def test_origin_edit_of_touched_handoff_section_fires_base_assertion(tmp_path: Path) -> None:
    _remote, local, peer, base = _make_vault(tmp_path)
    _write(
        peer,
        HANDOFF,
        _read(peer, HANDOFF).replace(
            "[[proj-a]]: continue the rollout from the squash landing.",
            "[[proj-a]]: rollout done; origin rewrote this resume line.",
        ),
    )
    _peer_push(peer)
    _write(
        local,
        HANDOFF,
        _read(local, HANDOFF).replace(
            "[[proj-a]]: continue the rollout from the squash landing.",
            "[[proj-a]]: session rewrote the same resume line differently.",
        ),
    )
    _commit_all(local, "vault wrap-up 2026-09-20")
    head_before, branch_before = _head(local), _branch(local)

    report = _run_replay(local, base, *_health_args(tmp_path, HEALTH_OK), expect_rc=1)

    assert report["action"] == "refused"
    assert "byte-identical" in report["reason"]
    assert "Resume from here" in report["reason"]
    _assert_untouched(local, head_before, branch_before)


# ---------------------------------------------------------------------------
# Allowlist scope -- everything else still escalates to a human.
# ---------------------------------------------------------------------------


def test_conflict_outside_allowlist_refuses_and_names_the_file(tmp_path: Path) -> None:
    _remote, local, peer, base = _make_vault(tmp_path)
    _write(peer, "personal/projects/proj-a.md", NOTE_SEED + "\nPeer line.\n")
    _write(
        peer,
        DECISIONS,
        insert_under(
            _read(peer, DECISIONS),
            "## Recent",
            decisions_entry("2026-09-19", "Peer decision", "**Decided:** peer."),
        ),
    )
    _peer_push(peer)
    _write(local, "personal/projects/proj-a.md", NOTE_SEED + "\nSession line.\n")
    _write(
        local,
        DECISIONS,
        insert_under(
            _read(local, DECISIONS),
            "## Recent",
            decisions_entry("2026-09-20", "Session decision", "**Decided:** mine."),
        ),
    )
    _commit_all(local, "vault wrap-up 2026-09-20")
    head_before, branch_before = _head(local), _branch(local)

    report = _run_replay(local, base, *_health_args(tmp_path, HEALTH_OK), expect_rc=1)

    assert report["action"] == "refused"
    assert "allowlist" in report["reason"]
    assert report["outside_allowlist"] == ["personal/projects/proj-a.md"]
    _assert_untouched(local, head_before, branch_before)


def test_anchor_renamed_on_origin_refuses(tmp_path: Path) -> None:
    """The replay never guesses a new anchor (design doc failure mode)."""
    _remote, local, peer, base = _make_vault(tmp_path)
    _write(peer, DECISIONS, _read(peer, DECISIONS).replace("## Recent", "## Log"))
    _peer_push(peer)
    _write(
        local,
        DECISIONS,
        insert_under(
            _read(local, DECISIONS),
            "## Recent",
            decisions_entry("2026-09-20", "Session decision", "**Decided:** mine."),
        ),
    )
    _commit_all(local, "vault wrap-up 2026-09-20")
    head_before, branch_before = _head(local), _branch(local)

    report = _run_replay(local, base, *_health_args(tmp_path, HEALTH_OK), expect_rc=1)

    assert report["action"] == "refused"
    assert "anchor" in report["reason"]
    _assert_untouched(local, head_before, branch_before)


def test_insertion_not_under_a_recognized_anchor_refuses(tmp_path: Path) -> None:
    """A dated entry parked in the file preamble (above every ``##`` anchor)
    is not an anchored insert; the replay refuses rather than adopting it."""
    _remote, local, peer, base = _make_vault(tmp_path)
    _write(
        peer,
        GOTCHAS,
        insert_under(
            _read(peer, GOTCHAS),
            "## Technical",
            gotchas_entry("Peer gotcha", "2026-09-19", "Peer body."),
        ),
    )
    _peer_push(peer)
    stray = gotchas_entry("Stray entry", "2026-09-20", "Parked above the anchors.")
    _write(
        local,
        GOTCHAS,
        _read(local, GOTCHAS).replace(
            "## Technical\n", stray + "\n## Technical\n", 1
        ),
    )
    _commit_all(local, "vault wrap-up 2026-09-20")
    head_before, branch_before = _head(local), _branch(local)

    report = _run_replay(local, base, *_health_args(tmp_path, HEALTH_OK), expect_rc=1)

    assert report["action"] == "refused"
    _assert_untouched(local, head_before, branch_before)


# ---------------------------------------------------------------------------
# Handoff rule -- origin wins wholesale; only touched sections come back.
# ---------------------------------------------------------------------------


def test_handoff_section_scoped_reapply(tmp_path: Path) -> None:
    _remote, local, peer, base = _make_vault(tmp_path)
    peer_text = _read(peer, HANDOFF)
    peer_text = peer_text.replace(
        "- [[proj-b]]: close the parity ticket.",
        "- [[proj-b]]: close the parity ticket.\n- [[proj-c]]: origin's new thread.",
    )
    peer_text = peer_text.replace(
        'proj-b parity gate is green"',
        'proj-b parity gate is green; proj-c thread opened by origin"',
    )
    _write(peer, HANDOFF, peer_text)
    _peer_push(peer)

    local_text = _read(local, HANDOFF)
    local_text = local_text.replace(
        "[[proj-a]]: continue the rollout from the squash landing.",
        "[[proj-a]]: rollout complete; session finished the migration.",
    )
    local_text = local_text.replace(
        'proj-b parity gate is green"',
        'proj-b parity gate is green; proj-a migration finished by this session"',
    )
    _write(local, HANDOFF, local_text)
    _commit_all(local, "vault wrap-up 2026-09-20")

    report = _run_replay(local, base, *_health_args(tmp_path, HEALTH_OK))

    assert report["action"] == "replayed"
    merged = _read(local, HANDOFF)
    # The session's touched section came back...
    assert "rollout complete; session finished the migration" in merged
    # ...origin's untouched sections stand, including its new thread bullet...
    assert "origin's new thread" in merged
    assert "Nothing unattended." in merged
    # ...and the description merged additively: origin's paragraph plus the
    # session's added clause, never the session's whole rewrite.
    assert "proj-c thread opened by origin" in merged
    assert "proj-a migration finished by this session" in merged
    assert report["files"][HANDOFF]["sections_replaced"] == ["Resume from here"]


def test_handoff_description_clause_merge_drops_session_removed_clause(tmp_path: Path) -> None:
    _remote, local, peer, base = _make_vault(tmp_path)
    peer_text = _read(peer, HANDOFF).replace(
        'proj-b parity gate is green"',
        'proj-b parity gate is green; origin appended its clause"',
    )
    _write(peer, HANDOFF, peer_text)
    _peer_push(peer)
    # The session rewrites its own project's clause: old clause out, new in.
    local_text = _read(local, HANDOFF).replace(
        "proj-a shipped the squash 2026-09-15", "proj-a replay fallback landed 2026-09-20"
    )
    _write(local, HANDOFF, local_text)
    _commit_all(local, "vault wrap-up 2026-09-20")

    _run_replay(local, base, *_health_args(tmp_path, HEALTH_OK))

    merged = _read(local, HANDOFF)
    assert "proj-a replay fallback landed 2026-09-20" in merged
    assert "origin appended its clause" in merged
    assert "proj-a shipped the squash 2026-09-15" not in merged


def test_session_added_handoff_section_refuses(tmp_path: Path) -> None:
    _remote, local, peer, base = _make_vault(tmp_path)
    _write(
        peer,
        HANDOFF,
        _read(peer, HANDOFF).replace(
            "Nothing unattended.", "Nothing unattended right now."
        ),
    )
    _peer_push(peer)
    _write(local, HANDOFF, _read(local, HANDOFF) + "\n## Brand new section\n\nBody.\n")
    _commit_all(local, "vault wrap-up 2026-09-20")
    head_before, branch_before = _head(local), _branch(local)

    report = _run_replay(local, base, *_health_args(tmp_path, HEALTH_OK), expect_rc=1)

    assert report["action"] == "refused"
    assert "section" in report["reason"]
    _assert_untouched(local, head_before, branch_before)


def test_origin_added_section_elsewhere_still_replays(tmp_path: Path) -> None:
    _remote, local, peer, base = _make_vault(tmp_path)
    peer_text = _read(peer, HANDOFF).replace(
        "## Mode", "## Watch list\n\n- New origin-side section.\n\n## Mode"
    )
    _write(peer, HANDOFF, peer_text)
    _peer_push(peer)
    _write(
        local,
        HANDOFF,
        _read(local, HANDOFF).replace(
            "[[proj-a]]: continue the rollout from the squash landing.",
            "[[proj-a]]: session progress note.",
        ),
    )
    _commit_all(local, "vault wrap-up 2026-09-20")

    report = _run_replay(local, base, *_health_args(tmp_path, HEALTH_OK))

    assert report["action"] == "replayed"
    merged = _read(local, HANDOFF)
    assert "New origin-side section." in merged
    assert "session progress note" in merged


# ---------------------------------------------------------------------------
# Session-only changes ride along; the replay tree is the whole session.
# ---------------------------------------------------------------------------


def test_session_only_files_are_carried_into_the_replay(tmp_path: Path) -> None:
    _remote, local, peer, base = _make_vault(tmp_path)
    _write(
        peer,
        DECISIONS,
        insert_under(
            _read(peer, DECISIONS),
            "## Recent",
            decisions_entry("2026-09-19", "Peer decision", "**Decided:** peer."),
        ),
    )
    _peer_push(peer)
    _write(local, "personal/notes/session-note.md", "---\ndate: 2026-09-20\n---\n\n# New\n")
    _write(local, "personal/projects/proj-a.md", NOTE_SEED + "\nSession-only edit.\n")
    _write(
        local,
        DECISIONS,
        insert_under(
            _read(local, DECISIONS),
            "## Recent",
            decisions_entry("2026-09-20", "Session decision", "**Decided:** mine."),
        ),
    )
    _commit_all(local, "vault wrap-up 2026-09-20")

    report = _run_replay(local, base, *_health_args(tmp_path, HEALTH_OK))

    assert report["action"] == "replayed"
    assert (local / "personal/notes/session-note.md").exists()
    assert "Session-only edit." in _read(local, "personal/projects/proj-a.md")
    assert sorted(report["carried"]["added"]) == ["personal/notes/session-note.md"]
    assert sorted(report["carried"]["modified"]) == ["personal/projects/proj-a.md"]


def test_session_deletion_of_an_untouched_file_is_carried(tmp_path: Path) -> None:
    _remote, local, peer, base = _make_vault(tmp_path)
    _write(local, "personal/notes/scratch.md", "scratch\n")
    base2 = _commit_all(local, "pre-session note")
    _git(local, "push", "-q")
    _git(peer, "pull", "-q")
    _write(
        peer,
        DECISIONS,
        insert_under(
            _read(peer, DECISIONS),
            "## Recent",
            decisions_entry("2026-09-19", "Peer decision", "**Decided:** peer."),
        ),
    )
    _peer_push(peer)
    _git(local, "rm", "-q", "personal/notes/scratch.md")
    _write(
        local,
        DECISIONS,
        insert_under(
            _read(local, DECISIONS),
            "## Recent",
            decisions_entry("2026-09-20", "Session decision", "**Decided:** mine."),
        ),
    )
    _commit_all(local, "vault wrap-up 2026-09-20")

    report = _run_replay(local, base2, *_health_args(tmp_path, HEALTH_OK))

    assert report["action"] == "replayed"
    assert not (local / "personal/notes/scratch.md").exists()
    assert report["carried"]["deleted"] == ["personal/notes/scratch.md"]


def test_untracked_files_survive_the_replay(tmp_path: Path) -> None:
    _remote, local, peer, base = _make_vault(tmp_path)
    _write(
        peer,
        DECISIONS,
        insert_under(
            _read(peer, DECISIONS),
            "## Recent",
            decisions_entry("2026-09-19", "Peer decision", "**Decided:** peer."),
        ),
    )
    _peer_push(peer)
    _write(
        local,
        DECISIONS,
        insert_under(
            _read(local, DECISIONS),
            "## Recent",
            decisions_entry("2026-09-20", "Session decision", "**Decided:** mine."),
        ),
    )
    _commit_all(local, "vault wrap-up 2026-09-20")
    (local / "untracked-scratch.md").write_text("machine-local\n", encoding="utf-8")

    report = _run_replay(local, base, *_health_args(tmp_path, HEALTH_OK))

    assert report["action"] == "replayed"
    assert (local / "untracked-scratch.md").read_text(encoding="utf-8") == "machine-local\n"


# ---------------------------------------------------------------------------
# The health gate runs on the replayed tree, before anything is pushed.
# ---------------------------------------------------------------------------


def test_vault_health_runs_on_the_replayed_tree(tmp_path: Path) -> None:
    _remote, local, peer, base = _make_vault(tmp_path)
    peer_chunk = decisions_entry("2026-09-19", "Peer decision", "**Decided:** peer.")
    _write(peer, DECISIONS, insert_under(_read(peer, DECISIONS), "## Recent", peer_chunk))
    _peer_push(peer)
    session_chunk = decisions_entry("2026-09-20", "Session decision", "**Decided:** mine.")
    _write(local, DECISIONS, insert_under(_read(local, DECISIONS), "## Recent", session_chunk))
    _commit_all(local, "vault wrap-up 2026-09-20")
    marker = tmp_path / "health-saw.txt"
    args = _health_args(tmp_path, HEALTH_RECORDING.format(marker=marker.as_posix()))

    report = _run_replay(local, base, *args)

    assert report["action"] == "replayed"
    assert report["health"] == "passed"
    seen_head, seen_ledger = marker.read_text(encoding="utf-8").split("\n---\n", 1)
    assert seen_head == _head(local), "health must have seen the replay commit"
    assert peer_chunk in seen_ledger and session_chunk in seen_ledger, (
        "health must run on the merged tree, not either input"
    )


def test_health_failure_refuses_and_restores(tmp_path: Path) -> None:
    _remote, local, peer, base = _make_vault(tmp_path)
    _write(
        peer,
        DECISIONS,
        insert_under(
            _read(peer, DECISIONS),
            "## Recent",
            decisions_entry("2026-09-19", "Peer decision", "**Decided:** peer."),
        ),
    )
    _peer_push(peer)
    _write(
        local,
        DECISIONS,
        insert_under(
            _read(local, DECISIONS),
            "## Recent",
            decisions_entry("2026-09-20", "Session decision", "**Decided:** mine."),
        ),
    )
    tip = _commit_all(local, "vault wrap-up 2026-09-20")
    head_before, branch_before = _head(local), _branch(local)

    report = _run_replay(local, base, *_health_args(tmp_path, HEALTH_FAIL), expect_rc=1)

    assert report["action"] == "refused"
    assert "health" in report["reason"]
    assert report["health"] == "failed"
    assert report["restored"] is True
    _assert_untouched(local, head_before, branch_before)
    assert _head(local) == tip


def test_health_script_absent_proceeds(tmp_path: Path) -> None:
    """Parity with /sync's existing gate: a vault without ci/vault_health.py
    remains compatible. No --health-cmd is passed, so the default command
    would run -- the absence check must short-circuit it."""
    _remote, local, peer, base = _make_vault(tmp_path)
    _write(
        peer,
        DECISIONS,
        insert_under(
            _read(peer, DECISIONS),
            "## Recent",
            decisions_entry("2026-09-19", "Peer decision", "**Decided:** peer."),
        ),
    )
    _peer_push(peer)
    _write(
        local,
        DECISIONS,
        insert_under(
            _read(local, DECISIONS),
            "## Recent",
            decisions_entry("2026-09-20", "Session decision", "**Decided:** mine."),
        ),
    )
    _commit_all(local, "vault wrap-up 2026-09-20")

    report = _run_replay(local, base)

    assert report["action"] == "replayed"
    assert report["health"] == "absent"


# ---------------------------------------------------------------------------
# Divergence detection and guards.
# ---------------------------------------------------------------------------


def test_origin_not_diverged_is_none(tmp_path: Path) -> None:
    _remote, local, _peer, base = _make_vault(tmp_path)
    _write(
        local,
        DECISIONS,
        insert_under(
            _read(local, DECISIONS),
            "## Recent",
            decisions_entry("2026-09-20", "Session decision", "**Decided:** mine."),
        ),
    )
    tip = _commit_all(local, "vault wrap-up 2026-09-20")

    report = _run_replay(local, base)

    assert report["action"] == "none"
    assert _head(local) == tip


def test_diverged_without_file_conflicts_is_none(tmp_path: Path) -> None:
    """A plain rebase handles disjoint file sets; the replay stays out."""
    _remote, local, peer, base = _make_vault(tmp_path)
    _write(peer, "personal/notes/peer-note.md", "peer\n")
    _peer_push(peer)
    _write(
        local,
        DECISIONS,
        insert_under(
            _read(local, DECISIONS),
            "## Recent",
            decisions_entry("2026-09-20", "Session decision", "**Decided:** mine."),
        ),
    )
    tip = _commit_all(local, "vault wrap-up 2026-09-20")

    report = _run_replay(local, base)

    assert report["action"] == "none"
    assert "conflict" in report["reason"]
    assert _head(local) == tip


def test_dirty_worktree_refuses(tmp_path: Path) -> None:
    _remote, local, peer, base = _make_vault(tmp_path)
    _write(peer, DECISIONS, _read(peer, DECISIONS) + "\npeer tail\n")
    _peer_push(peer)
    _write(
        local,
        DECISIONS,
        insert_under(
            _read(local, DECISIONS),
            "## Recent",
            decisions_entry("2026-09-20", "Session decision", "**Decided:** mine."),
        ),
    )
    _commit_all(local, "vault wrap-up 2026-09-20")
    _write(local, "personal/projects/proj-a.md", NOTE_SEED + "\ndirty uncommitted edit\n")
    head_before = _head(local)

    report = _run_replay(local, base, expect_rc=1)

    assert report["action"] == "refused"
    assert "uncommitted" in report["reason"]
    assert _head(local) == head_before
    assert "dirty uncommitted edit" in _read(local, "personal/projects/proj-a.md")


def test_rebase_in_progress_refuses(tmp_path: Path) -> None:
    _remote, local, peer, base = _make_vault(tmp_path)
    _write(peer, DECISIONS, _read(peer, DECISIONS).replace("pin it", "peer pins it"))
    _peer_push(peer)
    _write(local, DECISIONS, _read(local, DECISIONS).replace("pin it", "local pins it"))
    _commit_all(local, "vault wrap-up 2026-09-20")
    rebase = subprocess.run(
        ["git", "pull", "--rebase", "-q"], cwd=local, env=_env(), capture_output=True, text=True
    )
    assert rebase.returncode != 0, "fixture must be mid-conflicted-rebase"

    report = _run_replay(local, base, expect_rc=1)

    assert report["action"] == "refused"
    assert "in progress" in report["reason"]
    subprocess.run(["git", "rebase", "--abort"], cwd=local, env=_env(), check=True)


def test_detached_head_refuses(tmp_path: Path) -> None:
    _remote, local, _peer, base = _make_vault(tmp_path)
    _git(local, "checkout", "-q", "--detach")

    report = _run_replay(local, base, expect_rc=1)

    assert report["action"] == "refused"
    assert "detached" in report["reason"]


def test_base_not_ancestor_of_head_refuses(tmp_path: Path) -> None:
    _remote, local, _peer, base = _make_vault(tmp_path)
    _git(local, "checkout", "-q", "-b", "side", base)
    _write(local, "side.md", "side\n")
    side = _commit_all(local, "side work")
    _git(local, "checkout", "-q", "main")

    report = _run_replay(local, side, expect_rc=1)

    assert report["action"] == "refused"
    assert "ancestor" in report["reason"]


def test_unknown_base_is_a_usage_error(tmp_path: Path) -> None:
    _remote, local, _peer, _base = _make_vault(tmp_path)
    result = _run_raw(local, "--base", "0" * 40, "--json")
    assert result.returncode == 2
    assert "base" in result.stderr


def test_unreachable_remote_refuses(tmp_path: Path) -> None:
    """Fail-closed where the squash script fails open: the replay cannot
    verify origin, so it must stop, not shrug."""
    _remote, local, _peer, base = _make_vault(tmp_path)
    _write(
        local,
        DECISIONS,
        insert_under(
            _read(local, DECISIONS),
            "## Recent",
            decisions_entry("2026-09-20", "Session decision", "**Decided:** mine."),
        ),
    )
    _commit_all(local, "vault wrap-up 2026-09-20")
    _git(local, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    head_before = _head(local)

    report = _run_replay(local, base, expect_rc=1)

    assert report["action"] == "refused"
    assert "fetch" in report["reason"]
    assert _head(local) == head_before


# ---------------------------------------------------------------------------
# Unit coverage for the pure pieces.
# ---------------------------------------------------------------------------


def test_is_allowlisted() -> None:
    assert is_allowlisted("brain/Gotchas.md")
    assert is_allowlisted("brain/Key Decisions.md")
    assert is_allowlisted("perf/Brag Doc.md")
    assert is_allowlisted(".brain/handoff-personal.md")
    assert is_allowlisted(".brain/handoff-work.md")
    assert not is_allowlisted("brain/Memories.md")
    assert not is_allowlisted(".brain/handoffs.md")
    assert not is_allowlisted(".brain/deep/handoff-personal.md")
    assert not is_allowlisted("personal/projects/proj-a.md")


@pytest.mark.parametrize(
    ("line", "expected_date"),
    [
        ("### 2026-09-20 — Leading date decision", "2026-09-20"),
        ("### Trailing date gotcha (2026-09-19)", "2026-09-19"),
        ("- **2026-09-18 ([[x]]) — Bullet win.** Tail", "2026-09-18"),
        ("#### 2026-09-17 deep heading", "2026-09-17"),
    ],
)
def test_parse_entry_start_recognizes_dated_shapes(line: str, expected_date: str) -> None:
    started = parse_entry_start(line)
    assert started is not None
    assert started[2] == expected_date


@pytest.mark.parametrize(
    "line",
    [
        "### Undated heading",
        "## 2026-09-20 is a level-2 heading, an anchor not an entry",
        "- plain bullet without a date",
        "- **bold bullet without a date**",
        "### Bad month (2026-13-45)",
        "body text 2026-09-20 mid-line",
    ],
)
def test_parse_entry_start_rejects_undated_shapes(line: str) -> None:
    assert parse_entry_start(line) is None


def test_merge_descriptions_appends_added_and_drops_removed() -> None:
    base = "digest; proj-a old clause; proj-b stands"
    tip = "digest; proj-a new clause; proj-b stands"
    origin = "digest; proj-a old clause; proj-b stands; proj-c origin clause"
    merged = merge_descriptions(base, tip, origin)
    assert "proj-a new clause" in merged
    assert "proj-c origin clause" in merged
    assert "proj-a old clause" not in merged


def test_merge_descriptions_keeps_origin_rewording_of_a_removed_clause() -> None:
    base = "digest; proj-a old clause"
    tip = "digest"
    origin = "digest; proj-a reworded by origin"
    merged = merge_descriptions(base, tip, origin)
    assert "proj-a reworded by origin" in merged


def test_ledger_merge_pure_insertion_roundtrip() -> None:
    base = GOTCHAS_SEED
    chunk = gotchas_entry("Fresh gotcha", "2026-09-20", "Fresh body.")
    tip = insert_under(base, "## Technical", chunk)
    origin_chunk = gotchas_entry("Origin gotcha", "2026-09-18", "Origin body.")
    origin = insert_under(base, "## Technical", origin_chunk)
    merged, detail = ledger_merge(base, tip, origin, GOTCHAS)
    assert chunk in merged
    assert origin_chunk in merged
    assert detail["inserted"] == 1


def test_ledger_merge_refuses_origin_entry_edit() -> None:
    base = GOTCHAS_SEED
    tip = insert_under(base, "## Technical", gotchas_entry("New", "2026-09-20", "Body."))
    origin = base.replace("Body of the bytecode gotcha.", "Origin edited this body.")
    with pytest.raises(RefusalError, match="byte-identical"):
        ledger_merge(base, tip, origin, GOTCHAS)


def test_handoff_merge_identical_same_day_preamble_changes_pass() -> None:
    base = HANDOFF_SEED
    bump = base.replace("date: 2026-09-15", "date: 2026-09-20").replace(
        "_Updated 2026-09-15._", "_Updated 2026-09-20._"
    )
    tip = bump.replace(
        "[[proj-a]]: continue the rollout from the squash landing.",
        "[[proj-a]]: session note.",
    )
    origin = bump.replace("Nothing unattended.", "Origin runs a job.")
    merged, detail = handoff_merge(base, tip, origin, HANDOFF)
    assert "_Updated 2026-09-20._" in merged
    assert "[[proj-a]]: session note." in merged
    assert "Origin runs a job." in merged
    assert detail["sections_replaced"] == ["Resume from here"]


def test_handoff_merge_refuses_cross_day_preamble_divergence() -> None:
    base = HANDOFF_SEED
    tip = base.replace("_Updated 2026-09-15._", "_Updated 2026-09-20._")
    origin = base.replace("_Updated 2026-09-15._", "_Updated 2026-09-21._")
    with pytest.raises(RefusalError):
        handoff_merge(base, tip, origin, HANDOFF)
