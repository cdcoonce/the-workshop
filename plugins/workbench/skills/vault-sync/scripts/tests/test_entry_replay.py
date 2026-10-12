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
  entries present, the session's entry where the session put it;
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
    compare_texts,
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


def _branch_or_none(repo: Path) -> str | None:
    """HEAD's short branch name, or None when HEAD is detached."""
    result = subprocess.run(
        ["git", "symbolic-ref", "--short", "-q", "HEAD"],
        cwd=repo,
        env=_env(),
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


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


def _assert_untouched(local: Path, head_before: str, branch_before: str | None) -> None:
    """``branch_before`` is None for a session that started on a detached HEAD."""
    assert _head(local) == head_before, "a refusal must not move HEAD"
    assert _branch_or_none(local) == branch_before, "a refusal must not switch branches"
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
    # The session's entry is OLDER than the peer's, but it sat at the top of the
    # session's block: placement is positional, so it lands directly under the
    # preamble and the peer's entry stays below it (the #874 ordering-drift
    # detector, not the replay, is the order tooth).
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
    assert dates == ["2026-09-18", "2026-09-20", "2026-09-15", "2026-09-10"]
    # The replay commit sits on origin's head, so the push is a fast-forward.
    assert _git(local, "rev-parse", "HEAD^") == origin_head
    assert _branch(local) == "main"
    assert _git(local, "status", "--porcelain") == ""
    assert report["files"][DECISIONS]["inserted"] == 1


def _add_session_worktree(local: Path, tmp_path: Path, branch: str = "claude/clever-benz") -> Path:
    """The desktop app's layout: a linked worktree on an unpublished session
    branch cut from local ``main``, with no upstream and no remote namesake."""
    worktree = tmp_path / "worktree"
    _git(local, "worktree", "add", "-q", "-b", branch, str(worktree), "main")
    return worktree


def test_worktree_session_branch_replays_onto_origin_default_branch(tmp_path: Path) -> None:
    """The vault's 2026-09-24 wrap-up: a desktop-app worktree on an unpublished
    ``claude/*`` branch hit a routine hub conflict, and the replay refused
    because it fetched ``origin claude/...``, which does not exist. It must
    replay onto origin's default branch, move only the session's own branch,
    and leave local ``main`` -- the primary checkout's branch -- alone."""
    _remote, local, peer, base = _make_vault(tmp_path)
    worktree = _add_session_worktree(local, tmp_path)
    peer_chunk = decisions_entry("2026-09-24", "Peer session decision", "**Decided:** peer thing.")
    _write(peer, DECISIONS, insert_under(_read(peer, DECISIONS), "## Recent", peer_chunk))
    origin_head = _peer_push(peer)
    session_chunk = decisions_entry(
        "2026-09-23", "Worktree session decision", "**Decided:** session thing."
    )
    _write(worktree, DECISIONS, insert_under(_read(worktree, DECISIONS), "## Recent", session_chunk))
    _commit_all(worktree, "vault wrap-up 2026-09-24")
    local_main_before = _git(local, "rev-parse", "main")

    report = _run_replay(worktree, base, *_health_args(tmp_path, HEALTH_OK))

    assert report["action"] == "replayed", report["reason"]
    assert report["branch"] == "claude/clever-benz"
    assert report["target"] == "main"
    assert report["origin_head"] == origin_head
    merged = _read(worktree, DECISIONS)
    assert peer_chunk in merged, "origin's concurrent entry must survive"
    assert session_chunk in merged, "the session's entry must be re-inserted"
    assert _branch(worktree) == "claude/clever-benz"
    assert _git(worktree, "rev-parse", "HEAD^") == origin_head
    assert _git(local, "rev-parse", "main") == local_main_before, (
        "local main belongs to the primary checkout and must not move"
    )
    _git(worktree, "push", "-q", "origin", "HEAD:main")  # raises unless a fast-forward


def _add_detached_worktree(local: Path, tmp_path: Path) -> Path:
    """Codex's layout: a linked worktree on a detached HEAD cut from local
    ``main`` -- no branch at all, so no branch name can say where work goes."""
    worktree = tmp_path / "codex-worktree"
    _git(local, "worktree", "add", "-q", "--detach", str(worktree), "main")
    return worktree


def _local_branches(repo: Path) -> str:
    """Every local branch and its tip -- shared by all of a repo's worktrees."""
    return _git(repo, "for-each-ref", "--format=%(refname) %(objectname)", "refs/heads")


def test_detached_worktree_session_replays_and_stays_detached(tmp_path: Path) -> None:
    """Codex runs vault sessions on a detached HEAD in a linked worktree, and
    the replay once refused there outright, forcing routine hub conflicts to
    be resolved by hand. It must replay onto origin's default branch and
    leave HEAD detached at the replay commit: no local branch is created,
    moved, or left behind."""
    _remote, local, peer, base = _make_vault(tmp_path)
    worktree = _add_detached_worktree(local, tmp_path)
    peer_chunk = decisions_entry("2026-09-24", "Peer session decision", "**Decided:** peer thing.")
    _write(peer, DECISIONS, insert_under(_read(peer, DECISIONS), "## Recent", peer_chunk))
    origin_head = _peer_push(peer)
    session_chunk = decisions_entry(
        "2026-09-23", "Codex session decision", "**Decided:** session thing."
    )
    _write(worktree, DECISIONS, insert_under(_read(worktree, DECISIONS), "## Recent", session_chunk))
    tip = _commit_all(worktree, "vault wrap-up 2026-09-24")
    branches_before = _local_branches(local)

    report = _run_replay(worktree, base, *_health_args(tmp_path, HEALTH_OK))

    assert report["action"] == "replayed", report["reason"]
    assert report["branch"] is None
    assert report["target"] == "main"
    assert report["target_source"] == "remote-default"
    assert report["old_head"] == tip
    merged = _read(worktree, DECISIONS)
    assert peer_chunk in merged, "origin's concurrent entry must survive"
    assert session_chunk in merged, "the session's entry must be re-inserted"
    assert _branch_or_none(worktree) is None, "a detached session must stay detached"
    assert _head(worktree) == report["new_head"]
    assert _git(worktree, "rev-parse", "HEAD^") == origin_head
    assert _git(worktree, "status", "--porcelain") == ""
    assert _local_branches(local) == branches_before, (
        "a detached replay must not create, move, or leave behind any local branch"
    )
    _git(worktree, "push", "-q", "origin", "HEAD:main")  # raises unless a fast-forward


def test_equal_dates_keep_session_entry_above_origin_entry(tmp_path: Path) -> None:
    _remote, local, peer, base = _make_vault(tmp_path)
    peer_chunk = decisions_entry(
        "2026-09-20",
        "Peer same-day decision",
        "**Decided:** keep the nightly probe on the spare laptop until the UI is worth sharing.",
    )
    _write(peer, DECISIONS, insert_under(_read(peer, DECISIONS), "## Recent", peer_chunk))
    _peer_push(peer)
    session_chunk = decisions_entry(
        "2026-09-20",
        "Session same-day decision",
        "**Decided:** pin graphmark below 0.9 until the parity gate lands.",
    )
    _write(local, DECISIONS, insert_under(_read(local, DECISIONS), "## Recent", session_chunk))
    _commit_all(local, "vault wrap-up 2026-09-20")

    _run_replay(local, base, *_health_args(tmp_path, HEALTH_OK))

    merged = _read(local, DECISIONS)
    assert merged.index("Session same-day decision") < merged.index("Peer same-day decision")


def test_replay_keeps_origin_order_even_when_origin_drifted(tmp_path: Path) -> None:
    """Origin's entries keep their exact order -- drift included. Only the
    session's new entry is placed, directly under the preamble where the session put it."""
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
    assert dates == ["2026-09-17", "2026-09-15", "2026-09-10", "2026-09-19"]


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


def test_session_edit_of_entry_origin_also_edited_refuses(tmp_path: Path) -> None:
    _remote, local, peer, base = _make_vault(tmp_path)
    # Origin corrected the 2026-09-15 entry one way...
    _write(
        peer,
        DECISIONS,
        _read(peer, DECISIONS).replace(
            "collapse unpushed session commits", "collapse only unpushed session commits"
        ),
    )
    _peer_push(peer)
    # ...and the session corrected the same entry another way (the 2455bf8c
    # shape) -- a real semantic conflict, so escalate.
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
    assert "edited or removed on origin" in report["reason"]
    assert "Adopt the sync-boundary squash" in report["reason"]
    _assert_untouched(local, head_before, branch_before)


def test_in_place_edit_of_an_entry_origin_left_alone_replays(tmp_path: Path) -> None:
    """The session corrects an entry in place plus inserts one; origin only
    inserted elsewhere. The per-replaced-entry assertion holds, so it replays."""
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

    report = _run_replay(local, base, *_health_args(tmp_path, HEALTH_OK))

    assert report["action"] == "replayed"
    merged = _read(local, GOTCHAS)
    assert "Corrected body of the bytecode gotcha." in merged
    assert "\nBody of the bytecode gotcha." not in merged
    assert "Peer body." in merged and "Session body." in merged
    detail = report["files"][GOTCHAS]
    assert detail["inserted"] == 1
    assert detail["replaced"] == 1


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
    assert "deleted" in report["reason"]
    assert "Pin graphmark below 0.8" in report["reason"]
    _assert_untouched(local, head_before, branch_before)


# ---------------------------------------------------------------------------
# Tooth 3 -- an origin-side edit inside a replaced span fires the assertion.
# ---------------------------------------------------------------------------


def test_origin_correction_of_an_untouched_entry_is_preserved(tmp_path: Path) -> None:
    """The session is a pure insertion; origin corrected an existing entry in
    the same block. The assertion covers only entries the replay replaces, so
    origin's copy of the untouched entry simply wins."""
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

    report = _run_replay(local, base, *_health_args(tmp_path, HEALTH_OK))

    assert report["action"] == "replayed"
    merged = _read(local, DECISIONS)
    assert "pin it, with TWO parity gates." in merged
    assert "pin it, with a parity gate." not in merged
    assert "Session decision" in merged


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


def test_bisect_in_progress_refuses(tmp_path: Path) -> None:
    """A bisect detaches HEAD at a commit under test. Once the replay stopped
    refusing every detached HEAD, it must still recognize this one as an
    operation in flight: replaying would move HEAD out from under the bisect."""
    _remote, local, peer, base = _make_vault(tmp_path)
    _write(
        peer,
        DECISIONS,
        insert_under(
            _read(peer, DECISIONS),
            "## Recent",
            decisions_entry("2026-09-24", "Peer decision", "**Decided:** peer."),
        ),
    )
    _peer_push(peer)
    _write(
        local,
        DECISIONS,
        insert_under(
            _read(local, DECISIONS),
            "## Recent",
            decisions_entry("2026-09-23", "Session decision", "**Decided:** mine."),
        ),
    )
    _commit_all(local, "session commit 1")
    _write(local, "personal/projects/proj-a.md", NOTE_SEED + "\nsession note\n")
    tip = _commit_all(local, "session commit 2")
    _git(local, "bisect", "start", tip, base)
    under_test = _head(local)
    assert under_test != tip and _branch_or_none(local) is None, "fixture must be mid-bisect"

    report = _run_replay(local, base, expect_rc=1)

    assert report["action"] == "refused"
    assert "in progress" in report["reason"]
    _assert_untouched(local, under_test, None)
    assert (local / ".git" / "BISECT_LOG").exists(), "the bisect must survive the refusal"


def test_detached_refusal_restores_the_original_detached_commit(tmp_path: Path) -> None:
    """A refusal after the replay branch is cut must come back to exactly
    where a detached session started: HEAD detached at its own tip, not on
    the replay branch, not at origin's head, and no branch left behind."""
    _remote, local, peer, base = _make_vault(tmp_path)
    worktree = _add_detached_worktree(local, tmp_path)
    _write(
        peer,
        DECISIONS,
        insert_under(
            _read(peer, DECISIONS),
            "## Recent",
            decisions_entry("2026-09-24", "Peer decision", "**Decided:** peer."),
        ),
    )
    _peer_push(peer)
    _write(
        worktree,
        DECISIONS,
        insert_under(
            _read(worktree, DECISIONS),
            "## Recent",
            decisions_entry("2026-09-23", "Codex session decision", "**Decided:** mine."),
        ),
    )
    tip = _commit_all(worktree, "vault wrap-up 2026-09-24")
    branches_before = _local_branches(local)

    report = _run_replay(worktree, base, *_health_args(tmp_path, HEALTH_FAIL), expect_rc=1)

    assert report["action"] == "refused"
    assert report["health"] == "failed"
    assert report["replay_branch"], "the refusal must come after the replay branch was cut"
    assert report["restored"] is True
    _assert_untouched(worktree, tip, None)
    assert _local_branches(local) == branches_before


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
    # Only the rolling digests: a dotted stem is a backup or variant, not a digest
    # (the vault tracks a stale `.brain/handoff-personal.prev.md` with no frontmatter).
    assert not is_allowlisted(".brain/handoff-personal.prev.md")
    assert not is_allowlisted(".brain/handoff-.md")
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


def test_ledger_merge_refuses_origin_edit_of_a_replaced_entry() -> None:
    base = GOTCHAS_SEED
    tip = base.replace("Body of the bytecode gotcha.", "Session edited this body.")
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
    tip = base.replace("date: 2026-09-15", "date: 2026-09-20")
    origin = base.replace("date: 2026-09-15", "date: 2026-09-21")
    with pytest.raises(RefusalError):
        handoff_merge(base, tip, origin, HANDOFF)


# ---------------------------------------------------------------------------
# R1 -- trailing-date heading grammar accepts a qualifier after the date.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("suffix", "expected_date"),
    [
        ("(2026-10-10)", "2026-10-10"),
        ("(2026-10-10, [[apipulse]])", "2026-10-10"),
        ("(2026-10-10, [[a]], [[b]])", "2026-10-10"),
        ("(2026-09-27, night)", "2026-09-27"),
        ("(2026-10-02, corrected 2026-10-03)", "2026-10-02"),
        ("(2026-09-14 onward, [[x]])", "2026-09-14"),
    ],
)
def test_trailing_date_heading_accepts_qualifiers(suffix: str, expected_date: str) -> None:
    started = parse_entry_start(f"### Some title {suffix}")
    assert started == ("heading", 3, expected_date)


@pytest.mark.parametrize(
    "suffix",
    [
        "(see 2026-10-10)",
        "(2026-10-10) trailing text",
        "(2026-13-40, x)",
        "(2026-10-10, nested (parens))",
    ],
)
def test_trailing_date_heading_rejects_non_dates(suffix: str) -> None:
    assert parse_entry_start(f"### Some title {suffix}") is None


# ---------------------------------------------------------------------------
# R2 -- entry-kind precedence: dated headings make dated bullets body text.
# ---------------------------------------------------------------------------

BULLET_BODY_GOTCHA = (
    "### Gotcha with a dated bullet in its body (2026-09-12)\n"
    "\n"
    "Intro line.\n"
    "\n"
    "- **2026-09-12 detail** a dated bullet that is body text, not an entry.\n"
    "- plain bullet\n"
)


def test_dated_bullet_inside_a_heading_entry_is_body_text() -> None:
    base = insert_under(GOTCHAS_SEED, "## Technical", BULLET_BODY_GOTCHA)
    new_session = gotchas_entry("Session gotcha", "2026-09-20", "Session body.")
    new_origin = gotchas_entry("Origin gotcha", "2026-09-19", "Origin body.")
    tip = insert_under(base, "## Technical", new_session)
    origin = insert_under(base, "## Technical", new_origin)

    merged, detail = ledger_merge(base, tip, origin, GOTCHAS)

    assert BULLET_BODY_GOTCHA in merged, "the bullet must stay inside its entry"
    assert new_session in merged and new_origin in merged
    assert detail["inserted"] == 1


def test_blocks_without_a_dated_heading_keep_bullet_entries() -> None:
    new_win = brag_entry("2026-09-20", "Session win")
    tip = insert_under(BRAG_SEED, "### Wins", new_win)
    origin_win = brag_entry("2026-09-18", "Origin win")
    origin = insert_under(BRAG_SEED, "### Wins", origin_win)

    merged, detail = ledger_merge(BRAG_SEED, tip, origin, BRAG)

    assert new_win in merged and origin_win in merged
    wins_dates = _entry_dates_under(merged, "### Wins", "### Growth")
    assert wins_dates == sorted(wins_dates, reverse=True)
    assert detail["inserted"] == 1


def test_bullet_inserted_above_the_first_heading_entry_refuses() -> None:
    """A bullet-shaped insertion into a heading-entry block is not an entry
    insertion: it lands in the block preamble, which must not change."""
    base = GOTCHAS_SEED
    bullet = "- **2026-09-20 ([[x]]) — A bullet parked in a heading block.** Detail.\n"
    tip = insert_under(base, "## Technical", bullet)
    with pytest.raises(RefusalError, match="preamble"):
        ledger_merge(base, tip, base, GOTCHAS)


def test_bullet_and_heading_entries_across_the_two_sides_refuse() -> None:
    base = "# Doc\n\n## Empty\n\n## Other\n\nProse.\n"
    tip = base.replace("## Empty\n", "## Empty\n\n- **2026-09-20 — a bullet entry.** Detail.\n", 1)
    origin = base.replace(
        "## Empty\n", "## Empty\n\n### Heading entry (2026-09-19)\n\nBody.\n", 1
    )
    with pytest.raises(RefusalError, match="mix shapes"):
        ledger_merge(base, tip, origin, "brain/Gotchas.md")


# ---------------------------------------------------------------------------
# R3 -- entry-level ledger merge.
# ---------------------------------------------------------------------------

BYTECODE_ENTRY = "### Bytecode cache hides a mutation (2026-09-10)\n\nBody of the bytecode gotcha.\n"


def test_ledger_merge_in_place_edit_accepted_when_origin_left_it_alone() -> None:
    base = GOTCHAS_SEED
    tip = base.replace("Body of the bytecode gotcha.", "Corrected bytecode body.")
    origin_chunk = gotchas_entry("Origin gotcha", "2026-09-18", "Origin body.")
    origin = insert_under(base, "## Technical", origin_chunk)

    merged, detail = ledger_merge(base, tip, origin, GOTCHAS)

    assert "Corrected bytecode body." in merged
    assert "Body of the bytecode gotcha." not in merged
    assert origin_chunk in merged
    assert detail["replaced"] == 1
    assert detail["inserted"] == 0


def test_ledger_merge_in_place_edit_refused_when_origin_edited_it_too() -> None:
    base = GOTCHAS_SEED
    tip = base.replace("Body of the bytecode gotcha.", "Session body.")
    origin = base.replace("Body of the bytecode gotcha.", "Origin body.")
    with pytest.raises(RefusalError, match="Bytecode cache hides a mutation") as info:
        ledger_merge(base, tip, origin, GOTCHAS)
    assert "edited or removed on origin" in str(info.value)


def test_ledger_merge_in_place_edit_refused_when_origin_removed_it() -> None:
    base = GOTCHAS_SEED
    tip = base.replace("Body of the bytecode gotcha.", "Session body.")
    origin = base.replace(BYTECODE_ENTRY + "\n", "")
    assert origin != base
    with pytest.raises(RefusalError, match="edited or removed on origin"):
        ledger_merge(base, tip, origin, GOTCHAS)


def test_ledger_merge_edit_plus_two_adjacent_inserts_in_one_opcode() -> None:
    """difflib sees one ``replace`` of 1 base entry by 3 tip entries."""
    base = GOTCHAS_SEED
    one = gotchas_entry("Inserted one", "2026-09-09", "First new body.")
    two = gotchas_entry("Inserted two", "2026-09-08", "Second new body.")
    tip = base.replace(
        BYTECODE_ENTRY,
        "### Bytecode cache hides a mutation (2026-09-10)\n\nEdited bytecode body.\n\n"
        + one
        + "\n"
        + two,
    )
    assert tip != base
    origin_chunk = gotchas_entry("Origin gotcha", "2026-09-18", "Origin body.")
    origin = insert_under(base, "## Technical", origin_chunk)

    merged, detail = ledger_merge(base, tip, origin, GOTCHAS)

    assert "Edited bytecode body." in merged
    assert "Body of the bytecode gotcha." not in merged
    assert one in merged and two in merged and origin_chunk in merged
    assert detail["replaced"] == 1
    assert detail["inserted"] == 2


def test_ledger_merge_heading_line_edit_accepted() -> None:
    base = GOTCHAS_SEED
    tip = base.replace(
        "### Bytecode cache hides a mutation (2026-09-10)",
        "### Bytecode cache hides a mutation (2026-09-10, [[graphmark]])",
    )
    origin_chunk = gotchas_entry("Origin gotcha", "2026-09-18", "Origin body.")
    origin = insert_under(base, "## Technical", origin_chunk)

    merged, detail = ledger_merge(base, tip, origin, GOTCHAS)

    assert "### Bytecode cache hides a mutation (2026-09-10, [[graphmark]])" in merged
    assert "(2026-09-10)\n" not in merged
    assert origin_chunk in merged
    assert detail["replaced"] == 1


def test_ledger_merge_in_place_edit_refused_when_origin_holds_two_copies() -> None:
    """"Exactly once": an edit cannot be placed when origin holds the entry twice."""
    base = GOTCHAS_SEED
    tip = base.replace("Body of the bytecode gotcha.", "Session body.")
    origin = base.replace(BYTECODE_ENTRY, BYTECODE_ENTRY + "\n" + BYTECODE_ENTRY)
    assert origin != base
    with pytest.raises(RefusalError, match="edited or removed on origin"):
        ledger_merge(base, tip, origin, GOTCHAS)


def test_ledger_merge_entry_deletion_refused() -> None:
    base = GOTCHAS_SEED
    tip = base.replace(BYTECODE_ENTRY + "\n", "")
    assert tip != base
    with pytest.raises(RefusalError, match="deleted") as info:
        ledger_merge(base, tip, base, GOTCHAS)
    assert "Bytecode cache hides a mutation" in str(info.value)


def test_ledger_merge_origin_correction_of_untouched_entry_is_preserved() -> None:
    base = GOTCHAS_SEED
    chunk = gotchas_entry("Session gotcha", "2026-09-20", "Session body.")
    tip = insert_under(base, "## Technical", chunk)
    origin = base.replace("Body of the bytecode gotcha.", "Origin corrected this body.")

    merged, detail = ledger_merge(base, tip, origin, GOTCHAS)

    assert "Origin corrected this body." in merged
    assert chunk in merged
    assert detail["inserted"] == 1
    assert detail["replaced"] == 0


def test_ledger_merge_session_edit_outside_the_blocks_refused() -> None:
    base = GOTCHAS_SEED
    tip = base.replace("Recurring pitfalls.", "Recurring pitfalls, reworded.")
    with pytest.raises(RefusalError, match="outside"):
        ledger_merge(base, tip, base, GOTCHAS)


def test_ledger_merge_session_edit_of_block_preamble_refused() -> None:
    base = BRAG_SEED.replace("### Wins\n\n- **2026-09-15", "### Wins\n\nPreamble prose.\n\n- **2026-09-15", 1)
    tip = base.replace("Preamble prose.", "Preamble prose, reworded.")
    with pytest.raises(RefusalError, match="preamble"):
        ledger_merge(base, tip, base, BRAG)


def test_ledger_merge_origin_preamble_change_refused() -> None:
    base = BRAG_SEED.replace("### Wins\n\n- **2026-09-15", "### Wins\n\nPreamble prose.\n\n- **2026-09-15", 1)
    new_win = brag_entry("2026-09-20", "Session win")
    tip = base.replace("Preamble prose.\n\n", "Preamble prose.\n\n" + new_win + "\n", 1)
    assert tip != base
    origin = base.replace("Preamble prose.", "Origin reworded the preamble.")
    with pytest.raises(RefusalError, match="preamble"):
        ledger_merge(base, tip, origin, BRAG)


def test_ledger_merge_sorts_each_subsection_separately() -> None:
    """Wins and Growth share a quarter; a newer Growth entry must not climb
    into the Wins list."""
    growth = brag_entry("2026-09-25", "Newer growth entry")
    tip = insert_under(BRAG_SEED, "### Growth", growth)
    merged, _detail = ledger_merge(BRAG_SEED, tip, BRAG_SEED, BRAG)
    wins = merged.split("### Wins\n", 1)[1].split("### Growth\n", 1)[0]
    growth_block = merged.split("### Growth\n", 1)[1].split("## Q2 2026", 1)[0]
    assert "Newer growth entry" not in wins
    assert "Newer growth entry" in growth_block


def test_ledger_merge_reports_replaced_and_duplicates() -> None:
    base = GOTCHAS_SEED
    chunk = gotchas_entry("Shared gotcha", "2026-09-20", "Same body.")
    tip = insert_under(base, "## Technical", chunk)
    origin = insert_under(base, "## Technical", chunk)
    _merged, detail = ledger_merge(base, tip, origin, GOTCHAS)
    assert detail["duplicates_skipped"] == 1
    assert detail["inserted"] == 0
    assert detail["replaced"] == 0
    assert detail["rule"] == "ledger"


# ---------------------------------------------------------------------------
# R4 -- handoff item-level replay inside touched sections.
# ---------------------------------------------------------------------------


def test_handoff_two_sessions_editing_different_bullets_of_one_section() -> None:
    base = HANDOFF_SEED
    tip = base.replace("- [[proj-a]]: watch the deploy.", "- [[proj-a]]: deploy watched, green.")
    origin = base.replace(
        "- [[proj-b]]: close the parity ticket.", "- [[proj-b]]: parity ticket closed."
    )

    merged, detail = handoff_merge(base, tip, origin, HANDOFF)

    assert "- [[proj-a]]: deploy watched, green." in merged
    assert "- [[proj-b]]: parity ticket closed." in merged
    assert "watch the deploy" not in merged and "close the parity ticket" not in merged
    assert detail["rule"] == "handoff"
    assert detail["sections_replaced"] == ["Open threads"]
    assert detail["items_replaced"] == 1
    assert detail["items_inserted"] == 0


def test_handoff_same_bullet_edited_by_both_sides_refuses() -> None:
    base = HANDOFF_SEED
    tip = base.replace("- [[proj-a]]: watch the deploy.", "- [[proj-a]]: session wording.")
    origin = base.replace("- [[proj-a]]: watch the deploy.", "- [[proj-a]]: origin wording.")
    with pytest.raises(RefusalError, match="Open threads") as info:
        handoff_merge(base, tip, origin, HANDOFF)
    assert "- [[proj-a]]: watch the deploy." in str(info.value)
    assert "byte-identical" in str(info.value)


def test_handoff_origin_duplicating_the_edited_item_refuses_as_a_twin() -> None:
    base = HANDOFF_SEED
    tip = base.replace("- [[proj-a]]: watch the deploy.", "- [[proj-a]]: session wording.")
    origin = base.replace(
        "- [[proj-a]]: watch the deploy.\n",
        "- [[proj-a]]: watch the deploy.\n- [[proj-a]]: watch the deploy.\n",
    )
    with pytest.raises(RefusalError, match="twin"):
        handoff_merge(base, tip, origin, HANDOFF)


def test_handoff_insertion_after_an_item_origin_removed_refuses() -> None:
    base = HANDOFF_SEED
    tip = base.replace(
        "- [[proj-a]]: watch the deploy.",
        "- [[proj-a]]: watch the deploy.\n- [[proj-c]]: session's insert.",
    )
    origin = base.replace("- [[proj-a]]: watch the deploy.\n", "")
    with pytest.raises(RefusalError, match="insertion"):
        handoff_merge(base, tip, origin, HANDOFF)


def test_handoff_session_edit_of_a_bullet_origin_removed_refuses() -> None:
    base = HANDOFF_SEED
    tip = base.replace("- [[proj-a]]: watch the deploy.", "- [[proj-a]]: session wording.")
    origin = base.replace("- [[proj-a]]: watch the deploy.\n", "")
    with pytest.raises(RefusalError, match="Open threads"):
        handoff_merge(base, tip, origin, HANDOFF)


def test_handoff_session_insert_while_origin_edits_another_bullet() -> None:
    base = HANDOFF_SEED
    tip = base.replace(
        "- [[proj-b]]: close the parity ticket.",
        "- [[proj-b]]: close the parity ticket.\n- [[proj-c]]: session's new thread.",
    )
    origin = base.replace("- [[proj-a]]: watch the deploy.", "- [[proj-a]]: origin reworded.")

    merged, detail = handoff_merge(base, tip, origin, HANDOFF)

    assert "- [[proj-a]]: origin reworded." in merged
    assert "- [[proj-c]]: session's new thread." in merged
    assert merged.index("close the parity ticket") < merged.index("session's new thread")
    assert detail["items_inserted"] == 1


def test_handoff_both_sides_append_to_the_end_of_one_section() -> None:
    """Two wrap-ups appending to the same section's tail must both survive."""
    base = HANDOFF_SEED
    tip = base.replace(
        "- [[proj-b]]: close the parity ticket.",
        "- [[proj-b]]: close the parity ticket.\n- [[proj-c]]: session's tail thread.",
    )
    origin = base.replace(
        "- [[proj-b]]: close the parity ticket.",
        "- [[proj-b]]: close the parity ticket.\n- [[proj-d]]: origin's tail thread.",
    )

    merged, _detail = handoff_merge(base, tip, origin, HANDOFF)

    assert "session's tail thread." in merged and "origin's tail thread." in merged
    assert merged.index("close the parity ticket") < merged.index("tail thread")


def test_handoff_session_insert_mid_section_lands_after_its_anchor_bullet() -> None:
    base = HANDOFF_SEED
    tip = base.replace(
        "- [[proj-a]]: watch the deploy.",
        "- [[proj-a]]: watch the deploy.\n- [[proj-c]]: inserted between.",
    )
    origin = base.replace(
        "- [[proj-b]]: close the parity ticket.",
        "- [[proj-b]]: close the parity ticket.\n- [[proj-d]]: origin's tail thread.",
    )

    merged, detail = handoff_merge(base, tip, origin, HANDOFF)

    order = [
        merged.index(text)
        for text in ("watch the deploy", "inserted between", "close the parity", "tail thread")
    ]
    assert order == sorted(order)
    assert detail["items_inserted"] == 1
    assert detail["items_replaced"] == 0


def test_handoff_edits_to_two_paragraphs_of_one_section_merge() -> None:
    base = HANDOFF_SEED.replace(
        "[[proj-a]]: continue the rollout from the squash landing.\n",
        "[[proj-a]]: continue the rollout from the squash landing.\n\n"
        "[[proj-b]]: second paragraph about the parity gate.\n",
    )
    tip = base.replace("continue the rollout", "finish the rollout")
    origin = base.replace("second paragraph about", "second paragraph, reworded, about")

    merged, _detail = handoff_merge(base, tip, origin, HANDOFF)

    assert "finish the rollout" in merged
    assert "second paragraph, reworded, about" in merged


def test_handoff_bullet_continuation_lines_travel_with_their_bullet() -> None:
    base = HANDOFF_SEED.replace(
        "- [[proj-a]]: watch the deploy.\n",
        "- [[proj-a]]: watch the deploy.\n  continuation of proj-a.\n",
    )
    tip = base.replace("continuation of proj-a.", "continuation, rewritten by the session.")
    origin = base.replace("close the parity ticket.", "ticket closed.")

    merged, _detail = handoff_merge(base, tip, origin, HANDOFF)

    assert "continuation, rewritten by the session." in merged
    assert "ticket closed." in merged


def _with_stamp(text: str, stamp: str) -> str:
    return text.replace("_Updated 2026-09-15._", stamp)


def test_handoff_stamp_only_origin_changed_takes_origins() -> None:
    base = HANDOFF_SEED
    tip = base.replace("- [[proj-a]]: watch the deploy.", "- [[proj-a]]: session wording.")
    origin = _with_stamp(base, "_Updated 2026-09-21 (origin)._")
    merged, _detail = handoff_merge(base, tip, origin, HANDOFF)
    assert "_Updated 2026-09-21 (origin)._" in merged
    assert "_Updated 2026-09-15._" not in merged
    assert "session wording." in merged


def test_handoff_stamp_only_session_changed_takes_sessions() -> None:
    base = HANDOFF_SEED
    tip = _with_stamp(base, "_Updated 2026-09-20 (session)._")
    origin = base.replace("- [[proj-b]]: close the parity ticket.", "- [[proj-b]]: origin edit.")
    merged, _detail = handoff_merge(base, tip, origin, HANDOFF)
    assert "_Updated 2026-09-20 (session)._" in merged
    assert "origin edit." in merged


def test_handoff_stamp_changed_on_both_sides_session_wins() -> None:
    base = HANDOFF_SEED
    tip = _with_stamp(base, "_Updated 2026-09-20 (session)._").replace(
        "- [[proj-a]]: watch the deploy.", "- [[proj-a]]: session wording."
    )
    origin = _with_stamp(base, "_Updated 2026-09-21 (origin)._")
    merged, _detail = handoff_merge(base, tip, origin, HANDOFF)
    assert "_Updated 2026-09-20 (session)._" in merged
    assert "(origin)" not in merged
    assert "session wording." in merged


def test_handoff_non_stamp_preamble_divergence_refuses() -> None:
    base = HANDOFF_SEED.replace(
        "_Updated 2026-09-15._\n", "_Updated 2026-09-15._\n\nPreamble prose.\n"
    )
    tip = base.replace("Preamble prose.", "Session preamble prose.")
    origin = base.replace("Preamble prose.", "Origin preamble prose.")
    with pytest.raises(RefusalError, match="preamble"):
        handoff_merge(base, tip, origin, HANDOFF)


def test_handoff_stamp_divergence_does_not_mask_other_preamble_divergence() -> None:
    base = HANDOFF_SEED
    tip = _with_stamp(base, "_Updated 2026-09-20._").replace("date: 2026-09-15", "date: 2026-09-20")
    origin = _with_stamp(base, "_Updated 2026-09-21._").replace(
        "date: 2026-09-15", "date: 2026-09-21"
    )
    with pytest.raises(RefusalError, match="preamble"):
        handoff_merge(base, tip, origin, HANDOFF)


def test_handoff_concurrent_wrap_ups_on_one_section_replay(tmp_path: Path) -> None:
    """The reflog shape: every wrap-up edits its own bullet in the same sections."""
    _remote, local, peer, base = _make_vault(tmp_path)
    _write(
        peer,
        HANDOFF,
        _read(peer, HANDOFF).replace(
            "- [[proj-b]]: close the parity ticket.", "- [[proj-b]]: parity ticket closed."
        ),
    )
    _peer_push(peer)
    _write(
        local,
        HANDOFF,
        _read(local, HANDOFF).replace(
            "- [[proj-a]]: watch the deploy.", "- [[proj-a]]: deploy watched, green."
        ),
    )
    _commit_all(local, "vault wrap-up 2026-09-20")

    report = _run_replay(local, base, *_health_args(tmp_path, HEALTH_OK))

    assert report["action"] == "replayed"
    merged = _read(local, HANDOFF)
    assert "- [[proj-a]]: deploy watched, green." in merged
    assert "- [[proj-b]]: parity ticket closed." in merged
    assert report["files"][HANDOFF]["items_replaced"] == 1


# ---------------------------------------------------------------------------
# R5 -- every refusal is reported, not just the first.
# ---------------------------------------------------------------------------


def test_every_refusing_file_is_listed_in_the_report(tmp_path: Path) -> None:
    _remote, local, peer, base = _make_vault(tmp_path)
    _write(
        peer,
        DECISIONS,
        _read(peer, DECISIONS).replace(
            "collapse unpushed session commits", "collapse only unpushed session commits"
        ),
    )
    _write(
        peer,
        HANDOFF,
        _read(peer, HANDOFF).replace("Nothing unattended.", "Nothing unattended right now."),
    )
    _peer_push(peer)
    _write(
        local,
        DECISIONS,
        _read(local, DECISIONS).replace(
            "collapse unpushed session commits", "collapse ALL session commits"
        ),
    )
    _write(local, HANDOFF, _read(local, HANDOFF) + "\n## Brand new section\n\nBody.\n")
    _commit_all(local, "vault wrap-up 2026-09-20")
    head_before, branch_before = _head(local), _branch(local)

    report = _run_replay(local, base, *_health_args(tmp_path, HEALTH_OK), expect_rc=1)

    assert report["action"] == "refused"
    by_path = {item["path"]: item["reason"] for item in report["refusals"]}
    assert set(by_path) == {DECISIONS, HANDOFF}
    assert "edited or removed on origin" in by_path[DECISIONS]
    assert "sections" in by_path[HANDOFF]
    assert report["reason"] == report["refusals"][0]["reason"]
    _assert_untouched(local, head_before, branch_before)


def test_outside_allowlist_refusal_does_not_hide_the_hub_file_refusals(tmp_path: Path) -> None:
    _remote, local, peer, base = _make_vault(tmp_path)
    _write(peer, "personal/projects/proj-a.md", NOTE_SEED + "\nPeer line.\n")
    _write(
        peer,
        DECISIONS,
        _read(peer, DECISIONS).replace(
            "collapse unpushed session commits", "collapse only unpushed session commits"
        ),
    )
    _peer_push(peer)
    _write(local, "personal/projects/proj-a.md", NOTE_SEED + "\nSession line.\n")
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
    assert report["outside_allowlist"] == ["personal/projects/proj-a.md"]
    paths = [item["path"] for item in report["refusals"]]
    assert paths == ["personal/projects/proj-a.md", DECISIONS]
    assert "allowlist" in report["reason"]
    _assert_untouched(local, head_before, branch_before)


def test_a_clean_replay_reports_no_refusals(tmp_path: Path) -> None:
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

    report = _run_replay(local, base, *_health_args(tmp_path, HEALTH_OK))

    assert report["action"] == "replayed"
    assert report["refusals"] == []


# ---------------------------------------------------------------------------
# R6 -- --lint: does every ledger block / handoff parse under the replay grammar?
# ---------------------------------------------------------------------------


def _lint(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return _run_raw(cwd, "--lint", *args)


def _write_vault_files(root: Path) -> None:
    _write(root, GOTCHAS, GOTCHAS_SEED)
    _write(root, DECISIONS, DECISIONS_SEED)
    _write(root, BRAG, BRAG_SEED)
    _write(root, HANDOFF, HANDOFF_SEED)


def test_lint_clean_default_set_exits_zero(tmp_path: Path) -> None:
    _write_vault_files(tmp_path)
    _write(tmp_path, ".brain/handoff-work.md", HANDOFF_SEED)
    result = _lint(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr


def test_lint_default_set_skips_handoff_backups(tmp_path: Path) -> None:
    _write_vault_files(tmp_path)
    _write(tmp_path, ".brain/handoff-personal.prev.md", "# stale backup, no frontmatter\n")
    result = _lint(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "prev.md" not in result.stdout


def test_lint_needs_no_git_and_skips_missing_files(tmp_path: Path) -> None:
    _write(tmp_path, GOTCHAS, GOTCHAS_SEED)
    result = _lint(tmp_path)  # tmp_path is not a repository; most files are absent
    assert result.returncode == 0, result.stdout + result.stderr


def test_lint_reports_an_undated_heading_at_entry_level(tmp_path: Path) -> None:
    _write_vault_files(tmp_path)
    _write(
        tmp_path,
        GOTCHAS,
        GOTCHAS_SEED.replace(
            "### Bytecode cache hides a mutation (2026-09-10)",
            "### Bytecode cache hides a mutation (sometime)",
        ),
    )
    result = _lint(tmp_path)
    assert result.returncode == 1
    assert GOTCHAS in result.stdout
    assert "undated heading" in result.stdout
    assert "Bytecode cache hides a mutation (sometime)" in result.stdout


def test_lint_reports_mixed_entry_heading_levels(tmp_path: Path) -> None:
    _write_vault_files(tmp_path)
    _write(
        tmp_path,
        DECISIONS,
        DECISIONS_SEED.replace(
            "### 2026-09-10 — Pin graphmark below 0.8", "#### 2026-09-10 — Pin graphmark below 0.8"
        ),
    )
    result = _lint(tmp_path)
    assert result.returncode == 1
    assert DECISIONS in result.stdout
    assert "levels" in result.stdout


def test_lint_reports_a_dated_entry_outside_every_anchor_block(tmp_path: Path) -> None:
    _write_vault_files(tmp_path)
    orphaned = "# Doc\n\n## A\n\n### Undated opener\n\n### Orphan entry (2026-09-10)\n\nBody.\n"
    _write(tmp_path, GOTCHAS, orphaned)
    result = _lint(tmp_path)
    assert result.returncode == 1
    assert "outside" in result.stdout
    assert "Orphan entry" in result.stdout


def test_lint_reports_handoff_frontmatter_and_duplicate_sections(tmp_path: Path) -> None:
    _write_vault_files(tmp_path)
    _write(tmp_path, ".brain/handoff-work.md", "# no frontmatter\n")
    _write(tmp_path, HANDOFF, HANDOFF_SEED + "\n## Mode\n\nDuplicate.\n")
    result = _lint(tmp_path)
    assert result.returncode == 1
    assert ".brain/handoff-work.md" in result.stdout
    assert "frontmatter" in result.stdout
    assert HANDOFF in result.stdout
    assert "duplicate" in result.stdout


def test_lint_json_lists_findings_and_explicit_paths(tmp_path: Path) -> None:
    bad = tmp_path / "scratch" / "Gotchas.md"
    bad.parent.mkdir()
    bad.write_text("# T\n\n## A\n\n### Entry (2026-09-10)\n\nBody.\n\n### Undated\n", encoding="utf-8")
    result = _lint(tmp_path, "--json", str(bad))
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert [item["path"] for item in payload["findings"]] == [str(bad)]
    assert "undated heading" in payload["findings"][0]["message"]


def test_lint_explicit_clean_paths_exit_zero(tmp_path: Path) -> None:
    good = tmp_path / "handoff-x.md"
    good.write_text(HANDOFF_SEED, encoding="utf-8")
    ledger = tmp_path / "Gotchas.md"
    ledger.write_text(GOTCHAS_SEED, encoding="utf-8")
    result = _lint(tmp_path, "--json", str(ledger), str(good))
    assert result.returncode == 0, result.stdout
    assert json.loads(result.stdout)["ok"] is True


def test_lint_explicit_missing_path_is_a_finding(tmp_path: Path) -> None:
    ledger = tmp_path / "Gotchas.md"
    ledger.write_text(GOTCHAS_SEED, encoding="utf-8")
    missing = tmp_path / "Key Decisions.md"
    result = _lint(tmp_path, "--json", str(ledger), str(missing))
    assert result.returncode == 1, result.stdout
    findings = json.loads(result.stdout)["findings"]
    assert [item["path"] for item in findings] == [str(missing)]
    assert "missing" in findings[0]["message"]


def test_lint_explicit_non_hub_path_is_a_finding_not_linted_as_a_ledger(tmp_path: Path) -> None:
    stray = tmp_path / "Notes.md"
    stray.write_text(GOTCHAS_SEED, encoding="utf-8")
    result = _lint(tmp_path, "--json", str(stray))
    assert result.returncode == 1, result.stdout
    payload = json.loads(result.stdout)
    assert [item["path"] for item in payload["findings"]] == [str(stray)]
    assert "not a hub file" in payload["findings"][0]["message"]
    assert payload["checked"] == []


def test_lint_with_nothing_to_check_fails(tmp_path: Path) -> None:
    result = _lint(tmp_path)  # an empty directory: no hub files at all
    assert result.returncode == 1
    assert "no hub files found" in result.stdout


# ---------------------------------------------------------------------------
# R7 -- --verify: did a hand rebuild keep both sides' additions, invent nothing?
# ---------------------------------------------------------------------------


def _verify_setup(tmp_path: Path) -> tuple[Path, str, str, str]:
    """A session edit and an origin edit of one handoff; returns (repo, base, tip, origin)."""
    _remote, local, peer, base = _make_vault(tmp_path)
    _write(
        peer,
        HANDOFF,
        _read(peer, HANDOFF).replace(
            "- [[proj-b]]: close the parity ticket.",
            "- [[proj-b]]: parity ticket closed by origin.",
        ),
    )
    _peer_push(peer)
    _write(
        local,
        HANDOFF,
        _read(local, HANDOFF).replace(
            "- [[proj-a]]: watch the deploy.",
            "- [[proj-a]]: deploy watched. Session sentence.",
        ),
    )
    tip = _commit_all(local, "vault wrap-up 2026-09-20")
    _git(local, "fetch", "-q", "origin")
    origin = _git(local, "rev-parse", "origin/main")
    return local, base, tip, origin


def _commit_result(local: Path, origin: str, edit) -> str:
    """Commit ``edit(handoff_text)`` on a branch from origin; return the commit."""
    _git(local, "switch", "-q", "-c", "hand-rebuild", origin)
    _write(local, HANDOFF, edit(_read(local, HANDOFF)))
    result = _commit_all(local, "hand rebuild")
    _git(local, "switch", "-q", "main")
    return result


def _verify(local: Path, base: str, tip: str, origin: str, result: str) -> subprocess.CompletedProcess[str]:
    return _run_raw(
        local, "--verify", "--base", base, "--tip", tip, "--origin", origin,
        "--result", result, "--json",
    )


def test_verify_passes_a_correct_hand_merge(tmp_path: Path) -> None:
    local, base, tip, origin = _verify_setup(tmp_path)
    result = _commit_result(
        local,
        origin,
        lambda text: text.replace(
            "- [[proj-a]]: watch the deploy.", "- [[proj-a]]: deploy watched. Session sentence."
        ),
    )
    proc = _verify(local, base, tip, origin, result)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["files"][HANDOFF]["missing"] == []
    assert payload["files"][HANDOFF]["extra"] == []


def test_verify_fails_a_duplicated_sentence_inside_a_session_modified_line(tmp_path: Path) -> None:
    local, base, tip, origin = _verify_setup(tmp_path)
    result = _commit_result(
        local,
        origin,
        lambda text: text.replace(
            "- [[proj-a]]: watch the deploy.",
            "- [[proj-a]]: deploy watched. Session sentence. Session sentence.",
        ),
    )
    proc = _verify(local, base, tip, origin, result)
    assert proc.returncode == 1
    entry = json.loads(proc.stdout)["files"][HANDOFF]
    assert "- [[proj-a]]: deploy watched. Session sentence." in entry["missing"]
    assert "- [[proj-a]]: deploy watched. Session sentence. Session sentence." in entry["extra"]


def test_verify_fails_a_result_missing_an_origin_added_line(tmp_path: Path) -> None:
    local, base, tip, origin = _verify_setup(tmp_path)
    result = _commit_result(
        local,
        origin,
        lambda text: text.replace(
            "- [[proj-a]]: watch the deploy.", "- [[proj-a]]: deploy watched. Session sentence."
        ).replace("- [[proj-b]]: parity ticket closed by origin.", "- [[proj-b]]: close the parity ticket."),
    )
    proc = _verify(local, base, tip, origin, result)
    assert proc.returncode == 1
    entry = json.loads(proc.stdout)["files"][HANDOFF]
    assert "- [[proj-b]]: parity ticket closed by origin." in entry["missing"]


def test_verify_does_not_fail_lines_both_sides_added(tmp_path: Path) -> None:
    _remote, local, peer, base = _make_vault(tmp_path)
    shared = "- [[proj-c]]: both sides added this exact line."
    for repo in (peer, local):
        _write(
            repo,
            HANDOFF,
            _read(repo, HANDOFF).replace(
                "- [[proj-b]]: close the parity ticket.",
                "- [[proj-b]]: close the parity ticket.\n" + shared,
            ),
        )
    _peer_push(peer)
    tip = _commit_all(local, "vault wrap-up")
    _git(local, "fetch", "-q", "origin")
    origin = _git(local, "rev-parse", "origin/main")
    result = origin  # one copy of the shared line, which is what either side holds
    proc = _verify(local, base, tip, origin, result)
    assert proc.returncode == 0, proc.stdout
    assert json.loads(proc.stdout)["files"][HANDOFF]["ambiguous"] == [shared]


def test_verify_truncates_long_lines_in_text_output(tmp_path: Path) -> None:
    local, base, tip, origin = _verify_setup(tmp_path)
    long_line = "- [[proj-a]]: " + "x" * 300
    result = _commit_result(
        local, origin, lambda text: text.replace("- [[proj-a]]: watch the deploy.", long_line)
    )
    proc = _run_raw(
        local, "--verify", "--base", base, "--tip", tip, "--origin", origin, "--result", result
    )
    assert proc.returncode == 1
    assert "x" * 300 not in proc.stdout
    assert HANDOFF in proc.stdout


# ---------------------------------------------------------------------------
# Round 2 -- adversarial-review findings, one test group per finding.
# ---------------------------------------------------------------------------

# F1 -- compare_texts / --verify must see lost untouched content ---------------


def test_compare_texts_reports_an_untouched_line_the_result_lost() -> None:
    verdict = compare_texts("a\nb\n", "a\nb\nc\n", "a\nb\n", "a\nc\n")
    assert verdict["missing"] == ["b"]
    assert verdict["extra"] == []


def test_compare_texts_empty_result_fails() -> None:
    verdict = compare_texts("a\nb\n", "a\nb\nc\n", "a\nb\nd\n", "")
    assert set(verdict["missing"]) == {"a", "b", "c", "d"}


def test_compare_texts_clean_merge_passes() -> None:
    verdict = compare_texts("a\nb\n", "a\nb\nc\n", "a\nb\nd\n", "d\na\nb\nc\n")
    assert verdict["missing"] == [] and verdict["extra"] == []


def test_compare_texts_both_sides_added_line_may_appear_once_or_twice() -> None:
    base, tip, origin = "a\n", "a\nx\n", "a\nx\n"
    for copies, ok in ((0, False), (1, True), (2, True), (3, False)):
        result = "a\n" + "x\n" * copies
        verdict = compare_texts(base, tip, origin, result)
        assert (not verdict["missing"] and not verdict["extra"]) is ok, copies
        assert verdict["ambiguous"] == ["x"]


def test_compare_texts_a_correct_stamp_resolution_passes() -> None:
    base = "---\ndescription: \"d\"\n---\n_Updated 1._\n- a\n"
    tip = "---\ndescription: \"d\"\n---\n_Updated 2._\n- a\n- s\n"
    origin = "---\ndescription: \"d\"\n---\n_Updated 3._\n- a\n- o\n"
    # the session changed its stamp, so the session's is the one resolution
    stamp = "_Updated 2._"
    result = f"---\ndescription: \"d\"\n---\n{stamp}\n- a\n- s\n- o\n"
    verdict = compare_texts(base, tip, origin, result, HANDOFF)
    assert verdict["missing"] == [] and verdict["extra"] == [], stamp
    assert stamp in verdict["resolved"]


def test_compare_texts_an_invented_stamp_or_a_dropped_stamp_fails() -> None:
    base = "_Updated 1._\n- a\n"
    tip = "_Updated 2._\n- a\n"
    origin = "_Updated 3._\n- a\n"
    invented = compare_texts(base, tip, origin, "_Updated 9._\n- a\n", HANDOFF)
    assert invented["extra"] == ["_Updated 9._"]
    dropped = compare_texts(base, tip, origin, "- a\n", HANDOFF)
    assert dropped["missing"] and dropped["resolved"] == []


def test_compare_texts_accepts_the_merged_description_clause_set() -> None:
    def doc(desc: str) -> str:
        return f'---\ndescription: "{desc}"\n---\n- a\n'

    base, tip, origin = doc("x; y"), doc("x; y; s"), doc("x; y; o")
    merged = doc("x; y; o; s")
    verdict = compare_texts(base, tip, origin, merged, HANDOFF)
    assert verdict["missing"] == [] and verdict["extra"] == []
    assert verdict["resolved"] == ['description: "x; y; o; s"']
    wrong = compare_texts(base, tip, origin, doc("x; y; o; s; s"), HANDOFF)
    assert wrong["extra"] == ['description: "x; y; o; s; s"']


# F2 -- handoff items align positionally, never by content search ---------------

DUP_LINKS_BASE = HANDOFF_SEED.replace(
    "- [[proj-a]]: watch the deploy.\n- [[proj-b]]: close the parity ticket.\n",
    "- A topic\n- Links: [[x]]\n- B topic\n- Links: [[x]]\n",
)


def _second_links(text: str, new: str) -> str:
    head, _sep, tail = text.rpartition("- Links: [[x]]")
    return head + new + tail


def test_handoff_duplicate_items_edited_on_both_sides_refuse() -> None:
    assert DUP_LINKS_BASE != HANDOFF_SEED
    tip = _second_links(DUP_LINKS_BASE, "- Links: [[x]], [[z]]")
    origin = _second_links(DUP_LINKS_BASE, "- Links: [[x]], [[y]]")
    with pytest.raises(RefusalError, match="Open threads"):
        handoff_merge(DUP_LINKS_BASE, tip, origin, HANDOFF)


def test_handoff_insert_after_a_duplicate_item_origin_edited_refuses() -> None:
    tip = _second_links(DUP_LINKS_BASE, "- Links: [[x]]\n- Inserted item")
    origin = _second_links(DUP_LINKS_BASE, "- Links: [[x]], [[y]]")
    with pytest.raises(RefusalError, match="Open threads"):
        handoff_merge(DUP_LINKS_BASE, tip, origin, HANDOFF)


def test_handoff_duplicate_items_with_an_origin_edit_elsewhere_refuse_as_twins() -> None:
    """P4: the session edits one of two byte-identical items while origin also
    changed the section -- the twin cannot be told apart, so refuse."""
    tip = _second_links(DUP_LINKS_BASE, "- Links: [[x]], [[z]]")
    origin = DUP_LINKS_BASE.replace("- B topic", "- B topic, origin-edited")
    with pytest.raises(RefusalError, match="twin"):
        handoff_merge(DUP_LINKS_BASE, tip, origin, HANDOFF)


def test_handoff_duplicate_items_with_origin_unchanged_still_replay() -> None:
    tip = _second_links(DUP_LINKS_BASE, "- Links: [[x]], [[z]]")
    merged, _detail = handoff_merge(DUP_LINKS_BASE, tip, DUP_LINKS_BASE, HANDOFF)
    assert merged == tip


def test_handoff_prepend_to_a_middle_section_with_origin_unchanged_accepts() -> None:
    base = HANDOFF_SEED
    tip = base.replace("- [[proj-a]]: watch the deploy.", "- [[proj-new]]: first.\n- [[proj-a]]: watch the deploy.")
    merged, detail = handoff_merge(base, tip, base, HANDOFF)
    assert merged == tip
    assert detail["items_inserted"] == 1


def test_handoff_prepend_while_origin_edited_a_different_item_accepts() -> None:
    base = HANDOFF_SEED
    tip = base.replace("- [[proj-a]]: watch the deploy.", "- [[proj-new]]: first.\n- [[proj-a]]: watch the deploy.")
    origin = base.replace("- [[proj-b]]: close the parity ticket.", "- [[proj-b]]: origin edit.")
    merged, _detail = handoff_merge(base, tip, origin, HANDOFF)
    assert merged.index("proj-new") < merged.index("proj-a]]: watch")
    assert "- [[proj-b]]: origin edit." in merged


# F3 -- no whole-block re-sort: origin's order stays, new entries are placed ----

UNSORTED_BASE = (
    "# Gotchas\n\n## Technical\n\n"
    + gotchas_entry("Oldest first one", "2026-09-01", "Body one.")
    + "\n"
    + gotchas_entry("Oldest first two", "2026-09-05", "Body two with a tpyo.")
    + "\n"
    + gotchas_entry("Oldest first three", "2026-09-10", "Body three.")
)


def _changed_lines(a: str, b: str) -> int:
    import difflib

    return sum(1 for line in difflib.ndiff(a.splitlines(), b.splitlines()) if line[0] in "+-")


def test_typo_fix_in_an_oldest_first_block_changes_exactly_one_line() -> None:
    tip = UNSORTED_BASE.replace("tpyo", "typo")
    merged, detail = ledger_merge(UNSORTED_BASE, tip, UNSORTED_BASE, GOTCHAS)
    assert detail["replaced"] == 1
    assert merged == tip
    assert _changed_lines(UNSORTED_BASE, merged) == 2  # one line out, one line in


def test_insertion_into_an_unsorted_block_moves_no_existing_entry() -> None:
    """Scanning from the top, 09-07 meets 09-01 first (strictly older), so it lands
    above it; origin's three entries keep their exact oldest-first order."""
    new = gotchas_entry("New entry", "2026-09-07", "New body.")
    tip = insert_under(UNSORTED_BASE, "## Technical", new)
    merged, _detail = ledger_merge(UNSORTED_BASE, tip, UNSORTED_BASE, GOTCHAS)
    titles = [line for line in merged.splitlines() if line.startswith("### ")]
    assert titles[0] == "### New entry (2026-09-07)"
    assert titles[1:] == [
        "### Oldest first one (2026-09-01)",
        "### Oldest first two (2026-09-05)",
        "### Oldest first three (2026-09-10)",
    ]


def test_new_entry_the_session_placed_last_goes_to_the_end() -> None:
    base = GOTCHAS_SEED
    new = gotchas_entry("Ancient entry", "2026-01-01", "Old body.")
    tip = base.replace("## Process", new + "\n## Process")
    merged, _detail = ledger_merge(base, tip, base, GOTCHAS)
    technical = merged.split("## Process")[0]
    assert technical.rstrip().endswith("Old body.")


def test_same_date_new_entry_goes_above_origins_same_date_entry() -> None:
    base = GOTCHAS_SEED
    new = gotchas_entry("Same day newcomer", "2026-09-15", "New body.")
    tip = insert_under(base, "## Technical", new)
    merged, _detail = ledger_merge(base, tip, base, GOTCHAS)
    assert merged.index("Same day newcomer") < merged.index("Stale tracking refs lie")


def test_multiple_new_entries_keep_the_sessions_relative_order() -> None:
    base = GOTCHAS_SEED
    first = gotchas_entry("Session first", "2026-09-20", "One.")
    second = gotchas_entry("Session second", "2026-09-20", "Two.")
    tip = insert_under(base, "## Technical", first + "\n" + second)
    merged, _detail = ledger_merge(base, tip, base, GOTCHAS)
    assert merged.index("Session first") < merged.index("Session second")
    assert merged.index("Session second") < merged.index("Stale tracking refs lie")


def test_an_edited_entry_keeps_its_origin_position_in_an_unsorted_block() -> None:
    tip = UNSORTED_BASE.replace(
        "Oldest first two (2026-09-05)", "Oldest first two (2026-09-05, [[x]])"
    )
    merged, detail = ledger_merge(UNSORTED_BASE, tip, UNSORTED_BASE, GOTCHAS)
    assert detail["replaced"] == 1
    titles = [line for line in merged.splitlines() if line.startswith("### ")]
    assert titles[1] == "### Oldest first two (2026-09-05, [[x]])"


# F4 -- CommonMark fences ------------------------------------------------------

FENCED_ENTRY = (
    "### Entry holding a four-backtick fence (2026-09-12)\n"
    "\n"
    "````md\n"
    "```\n"
    "\n"
    "\n"
    "### Inner fake (2026-09-01)\n"
    "```\n"
    "````\n"
    "\n"
    "After the fence.\n"
)


def test_a_four_backtick_fence_is_not_closed_by_an_inner_three_backtick_line() -> None:
    base = insert_under(GOTCHAS_SEED, "## Technical", FENCED_ENTRY)
    # 09-11 lands before "Bytecode ... (2026-09-10)"; had the fake "Inner fake
    # (2026-09-01)" heading counted as an entry it would land inside the fence.
    tip = insert_under(base, "## Technical", gotchas_entry("New one", "2026-09-11", "New."))
    merged, detail = ledger_merge(base, tip, base, GOTCHAS)
    assert FENCED_ENTRY in merged, "the fence content (two blank lines included) must be intact"
    assert merged.index("### New one") < merged.index("### Bytecode cache hides")
    assert detail["inserted"] == 1 and detail["replaced"] == 0
    assert merged.count("Stale tracking refs lie") == 1


def test_a_tilde_fence_is_not_closed_by_backticks_and_needs_a_long_enough_closer() -> None:
    entry = (
        "### Tilde fence entry (2026-09-12)\n\n~~~~\n````\n### Inner fake (2026-09-01)\n"
        "### Inner undated heading\n~~~\n### Undated after a short closer\n\n"
        "still inside\n~~~~\n\nAfter.\n"
    )
    base = insert_under(GOTCHAS_SEED, "## Technical", entry)
    tip = insert_under(base, "## Technical", gotchas_entry("New one", "2026-09-11", "New."))
    merged, detail = ledger_merge(base, tip, base, GOTCHAS)
    assert entry in merged
    assert merged.index("### New one") < merged.index("### Bytecode cache hides")
    assert detail["inserted"] == 1


# F5 -- an overwrite is a deletion, not an edit -------------------------------


def test_overwriting_an_entry_with_a_new_one_refuses_as_a_deletion() -> None:
    base = GOTCHAS_SEED.replace(
        "### Review packets retired (2026-09-01)\n\nBody of the process gotcha.\n",
        "### Review packets retired (2026-10-05)\n\nBody of the process gotcha.\n",
    )
    tip = base.replace(
        "### Review packets retired (2026-10-05)\n\nBody of the process gotcha.\n",
        "### Entirely different newcomer (2026-10-10)\n\nA brand new unrelated body.\n",
    )
    assert tip != base
    with pytest.raises(RefusalError, match="deleted"):
        ledger_merge(base, tip, base, GOTCHAS)


def test_a_heading_only_rename_of_the_same_entry_still_pairs() -> None:
    base = GOTCHAS_SEED
    tip = base.replace(
        "### Bytecode cache hides a mutation (2026-09-10)",
        "### Bytecode caches can hide a mutation (2026-09-10)",
    )
    merged, detail = ledger_merge(base, tip, base, GOTCHAS)
    assert detail["replaced"] == 1
    assert "Bytecode caches can hide a mutation" in merged
    assert "### Bytecode cache hides a mutation" not in merged


def test_same_date_rewrite_with_a_similar_body_pairs_but_a_dissimilar_one_does_not() -> None:
    base = GOTCHAS_SEED
    tip = base.replace(
        "### Bytecode cache hides a mutation (2026-09-10)\n\nBody of the bytecode gotcha.",
        "### Renamed bytecode entry (2026-09-10)\n\nBody of the bytecode gotcha, extended a bit.",
    )
    _merged, detail = ledger_merge(base, tip, base, GOTCHAS)
    assert detail["replaced"] == 1
    unrelated = base.replace(
        "### Bytecode cache hides a mutation (2026-09-10)\n\nBody of the bytecode gotcha.",
        "### Something else entirely (2026-09-10)\n\nZzz qqq www xxx 123 completely unrelated text.",
    )
    with pytest.raises(RefusalError, match="deleted"):
        ledger_merge(base, unrelated, base, GOTCHAS)


# F6 -- an item both sides inserted appears once -------------------------------


def test_handoff_item_both_sides_inserted_is_not_duplicated() -> None:
    base = HANDOFF_SEED
    both = "- [[proj-a]]: watch the deploy.\n- Same new item."
    tip = base.replace("- [[proj-a]]: watch the deploy.", both)
    origin = base.replace("- [[proj-a]]: watch the deploy.", both)
    origin = origin.replace("- [[proj-b]]: close the parity ticket.", "- [[proj-b]]: origin edit.")
    merged, detail = handoff_merge(base, tip, origin, HANDOFF)
    assert merged.count("- Same new item.") == 1
    assert "origin edit." in merged
    assert detail["items_inserted"] == 0


# F7 -- description clauses origin already holds are not appended --------------


def test_merge_descriptions_does_not_append_a_clause_origin_already_has() -> None:
    assert merge_descriptions("a; b", "a; b; c", "a; b2; c") == "a; b2; c"


# F8 -- handoff items are fence-aware -----------------------------------------


def test_handoff_blank_and_bullet_lines_inside_a_fence_stay_in_their_item() -> None:
    fenced = "- [[proj-a]]: run this:\n```\n- inside one\n\n- inside two\n```"
    base = HANDOFF_SEED.replace("- [[proj-a]]: watch the deploy.", fenced)
    tip = base.replace("- inside one", "- inside one, session")
    origin = base.replace("- inside two", "- inside two, origin")
    with pytest.raises(RefusalError, match="Open threads"):
        handoff_merge(base, tip, origin, HANDOFF)


def test_handoff_a_fence_opening_after_a_blank_still_starts_its_own_item() -> None:
    base = HANDOFF_SEED.replace(
        "- [[proj-a]]: watch the deploy.",
        "- [[proj-a]]: watch the deploy.\n\n```\ncode\n```",
    )
    tip = base.replace("- [[proj-a]]: watch the deploy.", "- [[proj-a]]: session wording.")
    origin = base.replace("code", "code, origin")
    merged, _detail = handoff_merge(base, tip, origin, HANDOFF)
    assert "session wording." in merged and "code, origin" in merged


def test_handoff_replace_run_with_an_origin_insertion_between_its_items_refuses() -> None:
    """The session replaced two adjacent items by one; origin slipped an item
    between them, so the base run is not contiguous on origin."""
    base = HANDOFF_SEED
    tip = base.replace(
        "- [[proj-a]]: watch the deploy.\n- [[proj-b]]: close the parity ticket.\n",
        "- [[proj-ab]]: merged thread.\n",
    )
    origin = base.replace(
        "- [[proj-a]]: watch the deploy.\n",
        "- [[proj-a]]: watch the deploy.\n- [[proj-o]]: origin slipped this in.\n",
    )
    assert tip != base and origin != base
    with pytest.raises(RefusalError, match="Open threads"):
        handoff_merge(base, tip, origin, HANDOFF)


def test_redating_an_entry_heading_is_a_deletion_even_with_the_same_body() -> None:
    base = GOTCHAS_SEED
    tip = base.replace(
        "### Bytecode cache hides a mutation (2026-09-10)",
        "### Bytecode cache hides a mutation (2026-09-11)",
    )
    with pytest.raises(RefusalError, match="deleted"):
        ledger_merge(base, tip, base, GOTCHAS)


# ---------------------------------------------------------------------------
# Round 3 -- the second adversarial pass: architecture (A1, A2) and points.
# ---------------------------------------------------------------------------

_H_FM = '---\ntitle: h\ndescription: "a; b"\n---\n_Updated 2026-10-10_\n\n'


def _hd(body: str) -> str:
    return _H_FM + body


def _lossless(base: str, tip: str, origin: str, merged: str) -> None:
    verdict = compare_texts(base, tip, origin, merged)
    assert verdict["missing"] == [] and verdict["extra"] == [], verdict


# A1 -- self-verification inside the replay -----------------------------------


def test_compare_texts_both_sides_deleting_a_repeated_line_is_ambiguous() -> None:
    base, tip, origin = "a\nx\nx\n", "a\nx\n", "a\nx\n"
    for copies, ok in ((0, True), (1, True), (2, False)):
        verdict = compare_texts(base, tip, origin, "a\n" + "x\n" * copies)
        assert (not verdict["missing"] and not verdict["extra"]) is ok, copies
    assert compare_texts(base, tip, origin, "a\nx\n")["ambiguous"] == ["x"]


def _in_process_replay(local: Path, base: str, monkeypatch: pytest.MonkeyPatch):
    import entry_replay

    for key, value in _env().items():
        monkeypatch.setenv(key, value)
    monkeypatch.chdir(local)
    return entry_replay.replay(base, "origin", None)


def _concurrent_decisions(tmp_path: Path) -> tuple[Path, str]:
    _remote, local, peer, base = _make_vault(tmp_path)
    peer_chunk = decisions_entry("2026-09-20", "Peer decision", "**Decided:** peer.")
    _write(peer, DECISIONS, insert_under(_read(peer, DECISIONS), "## Recent", peer_chunk))
    _peer_push(peer)
    chunk = decisions_entry("2026-09-21", "Session decision", "**Decided:** mine.")
    _write(local, DECISIONS, insert_under(_read(local, DECISIONS), "## Recent", chunk))
    _commit_all(local, "vault wrap-up")
    return local, base


def test_replay_self_check_refuses_a_merge_that_drops_a_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import entry_replay

    local, base = _concurrent_decisions(tmp_path)
    head_before, branch_before = _head(local), _branch(local)
    real = entry_replay.ledger_merge

    def lossy(base_text: str, tip_text: str, origin_text: str, path: str):
        merged, detail = real(base_text, tip_text, origin_text, path)
        return merged.replace("**Decided:** peer.\n", "", 1), detail

    monkeypatch.setattr(entry_replay, "ledger_merge", lossy)
    report = _in_process_replay(local, base, monkeypatch)

    assert report.action == "refused"
    assert "self-check" in report.reason
    assert "**Decided:** peer." in report.reason
    assert [item["path"] for item in report.refusals] == [DECISIONS]
    _assert_untouched(local, head_before, branch_before)


def test_replay_self_check_refuses_a_merge_that_duplicates_a_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import entry_replay

    local, base = _concurrent_decisions(tmp_path)
    real = entry_replay.ledger_merge

    def doubling(base_text: str, tip_text: str, origin_text: str, path: str):
        merged, detail = real(base_text, tip_text, origin_text, path)
        return merged.replace("**Decided:** mine.\n", "**Decided:** mine.\n**Decided:** mine.\n", 1), detail

    monkeypatch.setattr(entry_replay, "ledger_merge", doubling)
    report = _in_process_replay(local, base, monkeypatch)
    assert report.action == "refused" and "self-check" in report.reason


def test_replay_self_check_passes_the_real_merge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local, base = _concurrent_decisions(tmp_path)
    report = _in_process_replay(local, base, monkeypatch)
    assert report.action == "replayed", report.reason
    assert report.refusals == []


# A2 -- splice, don't re-serialize ----------------------------------------------


def _removed_lines(origin: str, merged: str) -> list[str]:
    import difflib

    return [
        line[1:]
        for line in difflib.unified_diff(origin.splitlines(), merged.splitlines(), lineterm="", n=0)
        if line.startswith("-") and not line.startswith("---")
    ]


QUIRKY_ORIGIN = (
    "# Gotchas\n\n## Technical\n\nNote that stays.\n\n"
    "### Entry one (2026-09-10)\n\nBody one.\n\n\n"
    "### Entry two (2026-09-05)\n\nBody two.   \n\n\n\n"
    "### Entry three (2026-09-01)\n\nBody three.\n\n## Process\n\nProse.\n"
)


def test_splice_leaves_every_untouched_origin_line_byte_identical() -> None:
    new = gotchas_entry("Session entry", "2026-09-07", "Session body.")
    tip = QUIRKY_ORIGIN.replace("### Entry two", new + "\n### Entry two")
    assert tip != QUIRKY_ORIGIN
    merged, detail = ledger_merge(QUIRKY_ORIGIN, tip, QUIRKY_ORIGIN, GOTCHAS)
    assert detail["inserted"] == 1
    assert _removed_lines(QUIRKY_ORIGIN, merged) == []
    assert "### Session entry (2026-09-07)\n\nSession body.\n" in merged
    assert merged.index("Session body.") < merged.index("### Entry two")


def test_splice_replaced_entry_keeps_origin_trailing_blanks_and_nothing_else_moves() -> None:
    tip = QUIRKY_ORIGIN.replace("Body two.   ", "Body two, fixed.")
    merged, detail = ledger_merge(QUIRKY_ORIGIN, tip, QUIRKY_ORIGIN, GOTCHAS)
    assert detail["replaced"] == 1
    assert _removed_lines(QUIRKY_ORIGIN, merged) == ["Body two.   "]
    assert "Body two, fixed.\n\n\n\n### Entry three" in merged


def test_splice_preserves_the_block_preamble_and_a_second_replay_still_accepts() -> None:
    base = "# G\n\n## Technical\n\nNewest first.\n\n### a (2026-10-01)\n\nA\n"
    tip = base.replace("Newest first.\n\n", "Newest first.\n\n### s (2026-10-10)\n\nS\n\n")
    origin = base.replace("A\n", "A fixed\n")
    out, _detail = ledger_merge(base, tip, origin, GOTCHAS)
    assert out.startswith("# G\n\n## Technical\n\nNewest first.\n\n### s (2026-10-10)")
    second = base.replace("### a (2026-10-01)", "### c (2026-10-05)\n\nC\n\n### a (2026-10-01)")
    merged, _detail = ledger_merge(base, second, out, GOTCHAS)
    assert "### c (2026-10-05)" in merged and "### s (2026-10-10)" in merged


def test_splice_keeps_a_tight_bullet_list_tight() -> None:
    base = "# B\n\n## Q\n\n### Wins\n\n- **2026-09-15 a** x\n- **2026-09-10 b** y\n"
    tip = base.replace("- **2026-09-15 a** x\n", "- **2026-09-20 s** s\n- **2026-09-15 a** x\n")
    merged, _detail = ledger_merge(base, tip, base, BRAG)
    assert merged == tip
    tail = base.replace("- **2026-09-10 b** y\n", "- **2026-09-10 b** y\n")
    tip_end = tail + "- **2026-09-01 z** z\n"
    merged_end, _detail = ledger_merge(base, tip_end, base, BRAG)
    assert merged_end == tip_end


def test_splice_loose_list_at_end_of_file_stays_loose() -> None:
    base = "# B\n\n## Q\n\n### Wins\n\n- **2026-09-15 a** x\n\n- **2026-09-10 b** y\n"
    tip = base + "\n- **2026-09-01 z** z\n"
    merged, _detail = ledger_merge(base, tip, base, BRAG)
    assert merged == tip


def test_splice_new_entry_into_an_empty_block() -> None:
    base = "# G\n\n## Empty\n\n## Other\n\nProse.\n"
    tip = base.replace("## Empty\n", "## Empty\n\n### New (2026-09-20)\n\nBody.\n", 1)
    merged, _detail = ledger_merge(base, tip, base, GOTCHAS)
    assert "### New (2026-09-20)\n\nBody.\n\n## Other" in merged


# P1 -- the handoff 'already present' filter ------------------------------------


def test_p1_reorder_never_loses_an_item() -> None:
    b = _hd("## Next\n\n- A\n- B\n- C\n\n## Other\n\nx\n")
    t = _hd("## Next\n\n- B\n- A\n- C\n\n## Other\n\nx\n")
    o = _hd("## Next\n\n- A\n- B\n- C2\n\n## Other\n\nx\n")
    try:
        merged, _detail = handoff_merge(b, t, o, HANDOFF)
    except RefusalError:
        return
    _lossless(b, t, o, merged)
    for item in ("- A\n", "- B\n", "- C2\n"):
        assert merged.count(item) == 1


def test_p1_move_to_the_end_never_loses_an_item() -> None:
    b = _hd("## Next\n\n- A\n- B\n- C\n\n## Other\n\nx\n")
    t = _hd("## Next\n\n- B\n- C\n- A\n\n## Other\n\nx\n")
    o = _hd("## Next\n\n- A\n- B\n- C\n\n## Other\n\nx2\n")
    merged, _detail = handoff_merge(b, t, o, HANDOFF)
    _lossless(b, t, o, merged)
    assert merged.count("- A\n") == 1 and merged.count("x2") == 1


def test_p1_a_new_item_identical_to_an_existing_one_is_kept() -> None:
    b = _hd("## Topics\n\n### alpha\n\n- Links: [[x]]\n\n### beta\n\n- note\n")
    t = _hd("## Topics\n\n### alpha\n\n- Links: [[x]]\n\n### beta\n\n- note\n- Links: [[x]]\n")
    o = _hd("## Topics\n\n### alpha\n\n- Links: [[x]]\n- new origin\n\n### beta\n\n- note\n")
    merged, _detail = handoff_merge(b, t, o, HANDOFF)
    assert merged.count("- Links: [[x]]") == 2 and "- new origin" in merged


def test_p1_an_item_both_sides_added_inside_a_replace_appears_once() -> None:
    b = _hd("## S\n\n- A\n- B\n- C\n")
    o = _hd("## S\n\n- A\n- Q\n- B\n- C\n")
    t = _hd("## S\n\n- A\n- Q\n- B2\n- C\n")
    merged, _detail = handoff_merge(b, t, o, HANDOFF)
    assert merged == _hd("## S\n\n- A\n- Q\n- B2\n- C\n")


def test_p1_each_origin_added_item_absorbs_at_most_one_session_duplicate() -> None:
    b = _hd("## S\n\n- A\n")
    o = _hd("## S\n\n- A\n- Q\n")
    t = _hd("## S\n\n- A\n- Q\n- Q\n")
    merged, _detail = handoff_merge(b, t, o, HANDOFF)
    assert merged.count("- Q\n") == 2


# P2 -- unclosed fences ---------------------------------------------------------

F_ENTRY = "### F (2026-10-10)\n\n- step:\n    ```bash\n    echo hi\n  ```\n- then done\n\n"
F_BASE = "# Gotchas\n\n## Technical\n\n### b (2026-10-09)\n\nbody b\n\n## Process\n\n### c (2026-10-08)\n\nc\n"


def test_p2_origin_ending_in_an_open_fence_refuses() -> None:
    origin = F_BASE.replace("### b (2026-10-09)", F_ENTRY + "### b (2026-10-09)")
    tip = F_BASE.replace("body b\n", "body b\n\n### N (2026-10-01)\n\nnew\n")
    with pytest.raises(RefusalError, match="unclosed or unrecognized code fence"):
        ledger_merge(F_BASE, tip, origin, GOTCHAS)


def test_p2_a_session_or_base_with_an_open_fence_refuses() -> None:
    bad = F_BASE.replace("body b\n", "body b\n\n```\nunclosed\n")
    tip = bad.replace("c\n", "c\n\n### N (2026-10-01)\n\nnew\n")
    with pytest.raises(RefusalError, match="unclosed or unrecognized code fence"):
        ledger_merge(bad, tip, bad, GOTCHAS)


def test_p2_handoff_with_an_open_fence_refuses() -> None:
    bad = _hd("## A\n\n```\n- a\n\n## B\n\n- b\n")
    with pytest.raises(RefusalError, match="unclosed or unrecognized code fence"):
        handoff_merge(bad, bad.replace("- b", "- b2"), bad, HANDOFF)


# P3 -- bodyless same-date entries ----------------------------------------------

_PRE = "# Brag Doc\n\n## Q4 2026\n\n### Wins\n\n"
_TAIL = "\n### Growth\n\n- g\n"
_X = "- **2026-10-10: Shipped apipulse to prod.** PR #31.\n"
_Y = "- **2026-10-10: Wrote a talk on SQL.** Slides at x.\n"
_Z = "- **2026-10-09: Older win.** z\n"
_O = "- **2026-10-10: Origin win.** o\n"


def test_p3_overwriting_a_bodyless_bullet_with_an_unrelated_one_refuses() -> None:
    b = _PRE + _X + _Z + _TAIL
    t = _PRE + _Y + _Z + _TAIL
    o = _PRE + _O + _X + _Z + _TAIL
    with pytest.raises(RefusalError, match="deleted"):
        ledger_merge(b, t, o, BRAG)


# P4 -- twin ambiguity ----------------------------------------------------------


def test_p4_twin_when_origin_deleted_one_copy_refuses() -> None:
    b = _hd("## S\n\n- A\n- L\n- L\n- Z\n")
    o = _hd("## S\n\n- A\n- L\n- Z\n")
    t = _hd("## S\n\n- A\n- L2\n- L\n- Z\n")
    with pytest.raises(RefusalError, match="twin"):
        handoff_merge(b, t, o, HANDOFF)


def test_p4_twin_session_edits_second_copy_origin_deleted_second_refuses() -> None:
    b = _hd("## S\n\n- A\n- L\n- L\n- Z\n")
    o = _hd("## S\n\n- A\n- L\n- Z\n")
    t = _hd("## S\n\n- A\n- L\n- L2\n- Z\n")
    with pytest.raises(RefusalError):
        handoff_merge(b, t, o, HANDOFF)


def test_p4_twin_of_an_insertion_predecessor_refuses_when_origin_changed() -> None:
    b = _hd("## S\n\n- A\n- L\n- L\n- Z\n")
    o = _hd("## S\n\n- A\n- L\n- L\n- Z\n- O\n")
    t = _hd("## S\n\n- A\n- L\n- L\n- ins\n- Z\n")
    with pytest.raises(RefusalError, match="twin"):
        handoff_merge(b, t, o, HANDOFF)


def test_p4_origin_removed_the_topic_the_session_edits_refuses() -> None:
    b = _hd("## Open threads\n\n- Topic A: x\n- Links: [[x]]\n- Topic B: y\n- Links: [[x]]\n- tail\n")
    o = _hd("## Open threads\n\n- Topic B: y\n- Links: [[x]]\n- tail\n")
    t = _hd(
        "## Open threads\n\n- Topic A: x\n- Links: [[x]], [[a]]\n- Topic B: y\n- Links: [[x]]\n- tail\n"
    )
    with pytest.raises(RefusalError):
        handoff_merge(b, t, o, HANDOFF)


# P5 -- real-use cases that must ACCEPT ------------------------------------------


def test_p5a_start_line_edit_plus_a_new_same_date_entry_above_accepts() -> None:
    b = _PRE + _X + _Z + _TAIL
    xp = "- **2026-10-10: Shipped apipulse live on rammingspeed.** PR #31.\n"
    n = "- **2026-10-10: New thing.** n\n"
    t = _PRE + n + xp + _Z + _TAIL
    o = _PRE + _O + _X + _Z + _TAIL
    merged, detail = ledger_merge(b, t, o, BRAG)
    _lossless(b, t, o, merged)
    assert detail["replaced"] == 1 and detail["inserted"] == 1
    assert xp in merged and n in merged and _X not in merged and _O in merged


def test_p5a_a_base_entry_with_no_unique_match_refuses() -> None:
    b = "# G\n\n## Technical\n\n### One (2026-10-10)\n\nSame body here.\n\n### Two (2026-10-10)\n\nSame body here.\n"
    t = "# G\n\n## Technical\n\n### Uno (2026-10-10)\n\nSame body here.\n\n### Dos (2026-10-10)\n\nSame body here.\n"
    with pytest.raises(RefusalError, match="deleted"):
        ledger_merge(b, t, b, GOTCHAS)


def test_p5b_both_sides_deleting_the_same_item_is_not_a_conflict() -> None:
    b = _hd("## S\n\n- A\n- stale\n- C\n")
    o = _hd("## S\n\n- O\n- A\n- C\n")
    t = _hd("## S\n\n- A\n- C\n- T\n")
    merged, _detail = handoff_merge(b, t, o, HANDOFF)
    _lossless(b, t, o, merged)
    assert "- stale" not in merged and "- O" in merged and "- T" in merged


def test_p5b_both_sides_making_the_identical_edit_is_not_a_conflict() -> None:
    b = _hd("## S\n\n- A\n- B\n- C\n")
    o = _hd("## S\n\n- A\n- B2\n- C\n- O\n")
    t = _hd("## S\n\n- A\n- B2\n- C\n")
    merged, _detail = handoff_merge(b, t, o, HANDOFF)
    _lossless(b, t, o, merged)
    assert merged.count("- B2") == 1 and "- O" in merged


def test_p5c_loose_list_both_sides_appending_a_bullet_accepts() -> None:
    b = _hd("## Where\n\n- a\n\n- b\n\n## Next\n\n- n\n")
    t = _hd("## Where\n\n- a\n\n- b\n\n- s\n\n## Next\n\n- n\n")
    o = _hd("## Where\n\n- a\n\n- b\n\n- o\n\n## Next\n\n- n\n")
    merged, _detail = handoff_merge(b, t, o, HANDOFF)
    _lossless(b, t, o, merged)
    assert "- s" in merged and "- o" in merged
    assert merged == _hd("## Where\n\n- a\n\n- b\n\n- s\n\n- o\n\n## Next\n\n- n\n")


def test_p5_moving_a_bullet_between_sections_never_loses_it() -> None:
    b = _hd("## Resume\n\n- A\n- B\n\n## Done\n\n- D\n")
    t = _hd("## Resume\n\n- B\n\n## Done\n\n- A\n- D\n")
    o = _hd("## Resume\n\n- A\n- B\n- O\n\n## Done\n\n- D\n")
    try:
        merged, _detail = handoff_merge(b, t, o, HANDOFF)
    except RefusalError:
        return
    _lossless(b, t, o, merged)


# P6 -- more lint ----------------------------------------------------------------


def test_p6_lint_reports_a_duplicated_anchor_path(tmp_path: Path) -> None:
    dup = (
        "# Brag Doc\n\n## Q4 2026\n\n### Wins\n\n- **2026-10-10: a** x\n\n"
        "## Q4 2026\n\n### Wins\n\n- **2026-10-09: b** y\n"
    )
    _write(tmp_path, BRAG, dup)
    result = _lint(tmp_path, "--json", str(tmp_path / BRAG))
    assert result.returncode == 1
    assert any("appears 2 times" in item["message"] for item in json.loads(result.stdout)["findings"])


def test_p6_lint_reports_an_unclosed_fence_in_a_ledger_and_a_handoff(tmp_path: Path) -> None:
    unclosed = "# Gotchas\n\n## Technical\n\n### a (2026-10-10)\n\nbody\n```bash\necho\n\n### b (2026-10-09)\n\nb\n"
    _write(tmp_path, GOTCHAS, unclosed)
    hand = "---\ndescription: \"x\"\n---\n_Updated 1_\n\n## A\n\n```\n- a\n\n## B\n\n- b\n## B\n"
    _write(tmp_path, ".brain/handoff-x.md", hand)
    result = _lint(tmp_path, "--json", str(tmp_path / GOTCHAS), str(tmp_path / ".brain/handoff-x.md"))
    assert result.returncode == 1
    messages = [item["message"] for item in json.loads(result.stdout)["findings"]]
    assert sum("unclosed or unrecognized code fence" in m for m in messages) == 2
    assert any("duplicate handoff section" in m for m in messages)


# P7 -- --verify covers every path the result touches ---------------------------


def test_p7_verify_reports_a_file_the_hand_rebuild_reformatted(tmp_path: Path) -> None:
    local, base, tip, origin = _verify_setup(tmp_path)
    git_branch = "hand-rebuild-extra"
    _git(local, "switch", "-q", "-c", git_branch, origin)
    _write(
        local,
        HANDOFF,
        _read(local, HANDOFF).replace(
            "- [[proj-a]]: watch the deploy.", "- [[proj-a]]: deploy watched. Session sentence."
        ),
    )
    _write(local, "personal/projects/proj-a.md", NOTE_SEED + "\nReformatted in the rebuild.\n")
    result = _commit_all(local, "hand rebuild touching another file")
    _git(local, "switch", "-q", "main")
    proc = _verify(local, base, tip, origin, result)
    assert proc.returncode == 1
    files = json.loads(proc.stdout)["files"]
    assert "personal/projects/proj-a.md" in files
    assert "Reformatted in the rebuild." in files["personal/projects/proj-a.md"]["extra"][0]


# ---------------------------------------------------------------------------
# Round 3 -- granularity findings (G1-G5), one test group per finding.
# ---------------------------------------------------------------------------

# G1 -- a mid-session push must not leave a stale three-way base --------------

PUSHED_GOTCHA = gotchas_entry("Session gotcha", "2026-09-18", "Wrong number 42.")
PEER_GOTCHA = gotchas_entry("Peer gotcha", "2026-09-19", "Peer body.")


def _mid_session_push(tmp_path: Path) -> tuple[Path, Path, str, str]:
    """Session pushes Gotcha N + a handoff item mid-session; the peer then moves origin.

    Returns ``(local, peer, base, pushed)`` -- ``base`` is the pre-session
    commit, ``pushed`` the session's first (already-published) commit.
    """
    _remote, local, peer, base = _make_vault(tmp_path)
    _write(local, GOTCHAS, insert_under(_read(local, GOTCHAS), "## Technical", PUSHED_GOTCHA))
    _write(
        local,
        HANDOFF,
        _read(local, HANDOFF).replace(
            "- [[proj-b]]: close the parity ticket.",
            "- [[proj-b]]: close the parity ticket.\n- [[proj-x]]: pushed mid-session.",
        ),
    )
    pushed = _commit_all(local, "vault wrap-up (mid-session)")
    _git(local, "push", "-q")
    _git(peer, "pull", "-q", "--ff-only")
    return local, peer, base, pushed


def test_g1_a_pushed_entry_later_corrected_is_not_replayed_next_to_its_correction(
    tmp_path: Path,
) -> None:
    local, peer, base, pushed = _mid_session_push(tmp_path)
    _write(peer, GOTCHAS, insert_under(_read(peer, GOTCHAS), "## Technical", PEER_GOTCHA))
    _write(
        peer,
        HANDOFF,
        _read(peer, HANDOFF)
        .replace("_Updated 2026-09-15._", "_Updated 2026-09-19._")
        .replace("- [[proj-x]]: pushed mid-session.", "- [[proj-x]]: reworded by the peer."),
    )
    _peer_push(peer)
    _write(local, GOTCHAS, _read(local, GOTCHAS).replace("Wrong number 42.", "Corrected number 41."))
    _write(
        local,
        HANDOFF,
        _read(local, HANDOFF).replace(
            "- [[proj-a]]: watch the deploy.", "- [[proj-a]]: deploy watched."
        ),
    )
    _commit_all(local, "vault wrap-up (end of session)")

    report = _run_replay(local, base, *_health_args(tmp_path, HEALTH_OK))

    assert report["action"] == "replayed", report
    assert report["merge_base"] == pushed
    gotchas = _read(local, GOTCHAS)
    assert gotchas.count("### Session gotcha (2026-09-18)") == 1
    assert "Corrected number 41." in gotchas and "Wrong number 42." not in gotchas
    assert "### Peer gotcha (2026-09-19)" in gotchas
    handoff = _read(local, HANDOFF)
    assert "- [[proj-x]]: reworded by the peer." in handoff
    assert "pushed mid-session" not in handoff, "a pushed item origin reworded must not come back"
    assert "- [[proj-a]]: deploy watched." in handoff
    assert "_Updated 2026-09-19._" in handoff


def test_g1_the_same_correction_made_on_both_sides_accepts(tmp_path: Path) -> None:
    local, peer, base, _pushed = _mid_session_push(tmp_path)
    _write(
        peer,
        GOTCHAS,
        insert_under(
            _read(peer, GOTCHAS).replace("Wrong number 42.", "Corrected number 41."),
            "## Technical",
            PEER_GOTCHA,
        ),
    )
    _peer_push(peer)
    _write(local, GOTCHAS, _read(local, GOTCHAS).replace("Wrong number 42.", "Corrected number 41."))
    _commit_all(local, "vault wrap-up (end of session)")

    report = _run_replay(local, base, *_health_args(tmp_path, HEALTH_OK))

    assert report["action"] == "replayed", report
    gotchas = _read(local, GOTCHAS)
    assert gotchas.count("### Session gotcha (2026-09-18)") == 1
    assert gotchas.count("Corrected number 41.") == 1 and "Wrong number 42." not in gotchas
    assert "### Peer gotcha (2026-09-19)" in gotchas


def test_g1_a_base_older_than_the_published_history_is_still_accepted_as_an_ancestor(
    tmp_path: Path,
) -> None:
    """--base two commits back, with the first already pushed: merge-base moves up to it."""
    local, peer, base, pushed = _mid_session_push(tmp_path)
    _write(peer, GOTCHAS, insert_under(_read(peer, GOTCHAS), "## Technical", PEER_GOTCHA))
    _peer_push(peer)
    _write(local, DECISIONS, _read(local, DECISIONS).replace("**Decided:** pin it", "**Decided:** pin it hard"))
    _commit_all(local, "vault wrap-up (end of session)")
    report = _run_replay(local, base, *_health_args(tmp_path, HEALTH_OK))
    assert report["action"] in ("replayed", "none"), report
    assert report["merge_base"] == pushed
    assert base != report["merge_base"]


def test_g1_a_base_that_is_not_an_ancestor_of_the_merge_base_refuses(tmp_path: Path) -> None:
    """--base after the shared history (an unpublished commit) cannot be attributed."""
    _remote, local, peer, base = _make_vault(tmp_path)
    _write(peer, GOTCHAS, insert_under(_read(peer, GOTCHAS), "## Technical", PEER_GOTCHA))
    _peer_push(peer)
    _write(local, DECISIONS, _read(local, DECISIONS).replace("**Decided:** pin it", "**Decided:** pin it hard"))
    first = _commit_all(local, "unpublished predecessor")
    _write(local, GOTCHAS, insert_under(_read(local, GOTCHAS), "## Technical", PUSHED_GOTCHA))
    _commit_all(local, "session")
    head_before, branch_before = _head(local), _branch(local)

    report = _run_replay(local, first, expect_rc=1)

    assert report["action"] == "refused"
    assert "not an ancestor" in report["reason"]
    _assert_untouched(local, head_before, branch_before)


def test_g1_verify_uses_the_merge_base_when_origin_holds_later_session_commits(
    tmp_path: Path,
) -> None:
    local, peer, base, _pushed = _mid_session_push(tmp_path)
    _write(peer, GOTCHAS, insert_under(_read(peer, GOTCHAS), "## Technical", PEER_GOTCHA))
    _peer_push(peer)
    _write(local, GOTCHAS, _read(local, GOTCHAS).replace("Wrong number 42.", "Corrected number 41."))
    tip = _commit_all(local, "vault wrap-up (end of session)")
    _git(local, "fetch", "-q", "origin")
    origin = _git(local, "rev-parse", "origin/main")
    # A correct hand rebuild: origin's file with the correction applied in place.
    _git(local, "switch", "-q", "-c", "hand-rebuild", origin)
    _write(local, GOTCHAS, _read(local, GOTCHAS).replace("Wrong number 42.", "Corrected number 41."))
    result = _commit_all(local, "hand rebuild")
    _git(local, "switch", "-q", "main")

    proc = _verify(local, base, tip, origin, result)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    # ...and the rebuild that keeps BOTH the pushed entry and its correction fails.
    _git(local, "switch", "-q", "-c", "double-rebuild", origin)
    _write(
        local,
        GOTCHAS,
        insert_under(
            _read(local, GOTCHAS),
            "## Technical",
            gotchas_entry("Session gotcha", "2026-09-18", "Corrected number 41."),
        ),
    )
    double = _commit_all(local, "double rebuild")
    _git(local, "switch", "-q", "main")
    assert _verify(local, base, tip, origin, double).returncode == 1


# G2 -- inserted handoff items keep the session's own blank separators ----------


def _section(items_text: str, tail: str = "## Mode\n\nVault first.\n") -> str:
    return _hd("## Notes\n" + items_text + "\n" + tail)


def test_g2_a_paragraph_appended_at_a_sections_end_keeps_its_blank_line() -> None:
    base = _section("\nPara one is here.\n")
    tip = _section("\nPara one is here.\n\nPara two added by session.\n")
    origin = base.replace("_Updated 2026-10-10_", "_Updated 2026-10-11_")
    merged, _detail = handoff_merge(base, tip, origin, HANDOFF)
    assert "Para one is here.\n\nPara two added by session.\n" in merged
    assert merged == tip.replace("_Updated 2026-10-10_", "_Updated 2026-10-11_")


def test_g2_a_closing_paragraph_after_bullets_is_not_a_lazy_continuation() -> None:
    base = _section("\n- a\n- b\n")
    tip = _section("\n- a\n- b\n\nClosing paragraph.\n")
    origin = base.replace("_Updated 2026-10-10_", "_Updated 2026-10-11_")
    merged, _detail = handoff_merge(base, tip, origin, HANDOFF)
    assert "- b\n\nClosing paragraph.\n" in merged


def test_g2_tight_bullets_inserted_after_a_loose_paragraph_stay_tight() -> None:
    base = _section("\nIntro paragraph.\n")
    tip = _section("\nIntro paragraph.\n\n- n1\n- n2\n- n3\n")
    origin = base.replace("_Updated 2026-10-10_", "_Updated 2026-10-11_")
    merged, _detail = handoff_merge(base, tip, origin, HANDOFF)
    assert "Intro paragraph.\n\n- n1\n- n2\n- n3\n" in merged


def test_g2_an_insertion_mid_section_leaves_origins_other_items_untouched() -> None:
    base = _section("\n- a\n\n- b\n- c\n")
    tip = _section("\n- a\n\n- n1\n- n2\n\n- b\n- c\n")
    origin = _section("\n- a\n\n- b\n- c\n- origin-added\n")
    merged, _detail = handoff_merge(base, tip, origin, HANDOFF)
    assert merged.split("## Notes\n", 1)[1].startswith(
        "\n- a\n\n- n1\n- n2\n\n- b\n- c\n- origin-added\n"
    )


def test_g2_an_insertion_after_the_leading_blank_keeps_the_sessions_tight_list() -> None:
    base = _section("\n- a\n- b\n")
    tip = _section("\n- n\n- a\n- b\n")
    merged, _detail = handoff_merge(base, tip, base, HANDOFF)
    assert merged == tip


# G3 -- ledger placement is positional: after the session's predecessor entry ---


def _gotcha_titles(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith("### ")]


def test_g3_an_entry_appended_at_the_bottom_of_an_oldest_first_block_lands_at_the_bottom() -> None:
    new = gotchas_entry("Newest, appended last", "2026-09-20", "New body.")
    tip = UNSORTED_BASE + "\n" + new
    merged, _detail = ledger_merge(UNSORTED_BASE, tip, UNSORTED_BASE, GOTCHAS)
    assert merged == tip
    assert _gotcha_titles(merged)[-1] == "### Newest, appended last (2026-09-20)"


def test_g3_an_entry_inserted_mid_block_lands_after_its_predecessor_despite_origins_insert() -> None:
    base = GOTCHAS_SEED
    new = gotchas_entry("Session mid entry", "2026-01-01", "Mid body.")
    tip = base.replace(
        "### Bytecode cache hides a mutation (2026-09-10)", new + "\n### Bytecode cache hides a mutation (2026-09-10)"
    )
    peer = gotchas_entry("Origin top entry", "2026-09-20", "Peer body.")
    origin = insert_under(base, "## Technical", peer)
    merged, _detail = ledger_merge(base, tip, origin, GOTCHAS)
    assert _gotcha_titles(merged)[:4] == [
        "### Origin top entry (2026-09-20)",
        "### Stale tracking refs lie after a push (2026-09-15)",
        "### Session mid entry (2026-01-01)",
        "### Bytecode cache hides a mutation (2026-09-10)",
    ]


def test_g3_a_top_insertion_lands_at_the_top_whatever_its_date() -> None:
    base = GOTCHAS_SEED
    new = gotchas_entry("Session top entry", "2026-01-01", "Old but first.")
    tip = insert_under(base, "## Technical", new)
    merged, _detail = ledger_merge(base, tip, base, GOTCHAS)
    assert merged == tip
    assert _gotcha_titles(merged)[0] == "### Session top entry (2026-01-01)"


def test_g3_both_sides_inserting_at_the_top_keeps_both_with_the_sessions_under_the_preamble() -> None:
    base = GOTCHAS_SEED
    mine = gotchas_entry("Session top entry", "2026-09-18", "Mine.")
    theirs = gotchas_entry("Origin top entry", "2026-09-20", "Theirs.")
    tip = insert_under(base, "## Technical", mine)
    origin = insert_under(base, "## Technical", theirs)
    merged, _detail = ledger_merge(base, tip, origin, GOTCHAS)
    assert _gotcha_titles(merged)[:3] == [
        "### Session top entry (2026-09-18)",
        "### Origin top entry (2026-09-20)",
        "### Stale tracking refs lie after a push (2026-09-15)",
    ]


def test_g3_consecutive_new_entries_keep_their_tip_order_mid_block() -> None:
    base = GOTCHAS_SEED
    one = gotchas_entry("Session one", "2026-09-12", "One.")
    two = gotchas_entry("Session two", "2026-09-13", "Two.")
    tip = base.replace(
        "### Bytecode cache hides a mutation (2026-09-10)",
        one + "\n" + two + "\n### Bytecode cache hides a mutation (2026-09-10)",
    )
    merged, _detail = ledger_merge(base, tip, base, GOTCHAS)
    assert merged == tip


def test_g3_a_predecessor_origin_edited_falls_back_to_the_successor() -> None:
    base = GOTCHAS_SEED
    new = gotchas_entry("Session mid entry", "2026-09-12", "Mid body.")
    tip = base.replace(
        "### Bytecode cache hides a mutation (2026-09-10)", new + "\n### Bytecode cache hides a mutation (2026-09-10)"
    )
    origin = base.replace("Second line of that body.", "Second line, corrected on origin.")
    merged, _detail = ledger_merge(base, tip, origin, GOTCHAS)
    assert _gotcha_titles(merged)[:3] == [
        "### Stale tracking refs lie after a push (2026-09-15)",
        "### Session mid entry (2026-09-12)",
        "### Bytecode cache hides a mutation (2026-09-10)",
    ]
    assert "corrected on origin" in merged


def test_g3_neither_neighbour_surviving_on_origin_refuses() -> None:
    base = GOTCHAS_SEED
    new = gotchas_entry("Session mid entry", "2026-09-12", "Mid body.")
    tip = base.replace(
        "### Bytecode cache hides a mutation (2026-09-10)", new + "\n### Bytecode cache hides a mutation (2026-09-10)"
    )
    origin = base.replace("Second line of that body.", "Corrected A.").replace(
        "Body of the bytecode gotcha.", "Corrected B."
    )
    with pytest.raises(RefusalError, match="placement"):
        ledger_merge(base, tip, origin, GOTCHAS)


def test_g3_an_entry_after_a_session_edited_predecessor_lands_after_that_entry() -> None:
    base = GOTCHAS_SEED
    new = gotchas_entry("Session mid entry", "2026-09-12", "Mid body.")
    tip = base.replace(
        "### Bytecode cache hides a mutation (2026-09-10)", new + "\n### Bytecode cache hides a mutation (2026-09-10)"
    ).replace("Second line of that body.", "Second line, edited by the session.")
    merged, detail = ledger_merge(base, tip, base, GOTCHAS)
    assert merged == tip
    assert detail["replaced"] == 1 and detail["inserted"] == 1


# G4 -- the self-check's `resolved` exemptions apply to one side, one place -----


def _hand(desc: str, stamp: str, body: str = "- a\n") -> str:
    return f'---\ndescription: "{desc}"\n---\n_Updated {stamp}._\n\n## Open\n\n{body}'


def test_g4_a_merge_that_drops_a_session_only_description_change_fails_the_self_check() -> None:
    base = _hand("d", "1")
    tip = _hand("d; session clause", "1", "- a\n- s\n")
    origin = _hand("d", "1", "- a\n- o\n")
    dropped = _hand("d", "1", "- a\n- s\n- o\n")
    verdict = compare_texts(base, tip, origin, dropped, HANDOFF)
    assert verdict["missing"] == ['description: "d; session clause"']
    assert verdict["extra"] == ['description: "d"']
    kept = _hand("d; session clause", "1", "- a\n- s\n- o\n")
    ok = compare_texts(base, tip, origin, kept, HANDOFF)
    assert ok["missing"] == [] and ok["extra"] == []


def test_g4_an_origin_only_description_change_must_survive() -> None:
    base = _hand("d", "1")
    tip = _hand("d", "1", "- a\n- s\n")
    origin = _hand("d; origin clause", "1")
    reverted = _hand("d", "1", "- a\n- s\n")
    verdict = compare_texts(base, tip, origin, reverted, HANDOFF)
    assert verdict["missing"] or verdict["extra"]


def test_g4_a_both_sides_description_change_must_be_the_clause_merge() -> None:
    base = _hand("x; y", "1")
    tip = _hand("x; y; s", "1")
    origin = _hand("x; y; o", "1")
    assert compare_texts(base, tip, origin, _hand("x; y; o; s", "1"), HANDOFF)["extra"] == []
    for wrong in ("x; y; s", "x; y; o"):
        verdict = compare_texts(base, tip, origin, _hand(wrong, "1"), HANDOFF)
        assert verdict["missing"] or verdict["extra"], wrong


def test_g4_the_stamp_must_be_the_sessions_when_the_session_changed_it() -> None:
    base, tip, origin = _hand("d", "1"), _hand("d", "2"), _hand("d", "3")
    assert compare_texts(base, tip, origin, _hand("d", "2"), HANDOFF)["extra"] == []
    # origin's stamp is NOT acceptable when the session changed its own
    verdict = compare_texts(base, tip, origin, _hand("d", "3"), HANDOFF)
    assert verdict["extra"] == ["_Updated 3._"]


def test_g4_the_stamp_must_be_origins_when_only_origin_changed_it() -> None:
    base, tip, origin = _hand("d", "1"), _hand("d", "1", "- a\n- s\n"), _hand("d", "3")
    assert compare_texts(base, tip, origin, _hand("d", "3", "- a\n- s\n"), HANDOFF)["extra"] == []
    verdict = compare_texts(base, tip, origin, _hand("d", "1", "- a\n- s\n"), HANDOFF)
    assert verdict["extra"] == ["_Updated 1._"]


def test_g4_a_fenced_description_line_in_a_ledger_body_is_counted_like_any_line() -> None:
    fence = 'Example:\n\n```\ndescription: "x"\n```\n'
    base = f'---\ndescription: "g"\n---\n\n# Gotchas\n\n{fence}'
    tip = base + '\nAnother:\n\n```\ndescription: "x"\n```\n'
    verdict = compare_texts(base, tip, base, base, GOTCHAS)
    assert 'description: "x"' in verdict["missing"]
    # ...while a description change in a LEDGER's frontmatter is plain line arithmetic too
    changed = tip.replace('description: "g"', 'description: "g2"', 1)
    plain = compare_texts(base, changed, base, base, GOTCHAS)
    assert 'description: "g2"' in plain["missing"]


def test_g4_a_description_or_stamp_line_inside_a_handoff_section_is_counted() -> None:
    base = _hand("d", "1", '- a\n```\ndescription: "x"\n```\n')
    tip = _hand("d", "1", '- a\n```\ndescription: "x"\n```\n- b\n```\ndescription: "x"\n```\n_Updated 9._\n')
    verdict = compare_texts(base, tip, base, base, HANDOFF)
    assert 'description: "x"' in verdict["missing"] and "_Updated 9._" in verdict["missing"]


# G5 -- both sides renaming a handoff section identically is not a structure change


RENAMED = "## Open threads — carried forward unless noted"


def test_g5_both_sides_renaming_a_section_identically_replays_by_position() -> None:
    base = HANDOFF_SEED
    tip = base.replace("## Open threads", RENAMED).replace(
        "- [[proj-a]]: watch the deploy.", "- [[proj-a]]: deploy watched."
    )
    origin = base.replace("## Open threads", RENAMED).replace(
        "- [[proj-b]]: close the parity ticket.", "- [[proj-b]]: parity ticket closed."
    )
    merged, detail = handoff_merge(base, tip, origin, HANDOFF)
    assert RENAMED in merged and "## Open threads\n" not in merged
    assert "- [[proj-a]]: deploy watched." in merged
    assert "- [[proj-b]]: parity ticket closed." in merged
    assert detail["sections_replaced"] == ["Open threads — carried forward unless noted"]
    _lossless(base, tip, origin, merged)


def test_g5_a_rename_on_one_side_only_still_refuses() -> None:
    base = HANDOFF_SEED
    tip = base.replace("## Open threads", RENAMED)
    with pytest.raises(RefusalError, match="sections"):
        handoff_merge(base, tip, base, HANDOFF)


def test_g5_different_renames_on_the_two_sides_still_refuse() -> None:
    base = HANDOFF_SEED
    tip = base.replace("## Open threads", RENAMED)
    origin = base.replace("## Open threads", "## Open threads, renamed elsewhere")
    with pytest.raises(RefusalError, match="sections"):
        handoff_merge(base, tip, origin, HANDOFF)


def test_g5_a_reorder_or_an_added_section_that_origin_also_made_still_refuses() -> None:
    base = HANDOFF_SEED
    swapped = base.replace("## What's running\n\nNothing unattended.\n\n", "").replace(
        "## Mode\n", "## What's running\n\nNothing unattended.\n\n## Mode\n"
    )
    with pytest.raises(RefusalError, match="sections"):
        handoff_merge(base, swapped, swapped, HANDOFF)
    added = base + "\n## Extra\n\nNew.\n"
    with pytest.raises(RefusalError, match="sections"):
        handoff_merge(base, added, added, HANDOFF)
    dropped = base.replace("## Mode\n\nVault first, implementation in repository.\n", "")
    with pytest.raises(RefusalError, match="sections"):
        handoff_merge(base, dropped, dropped, HANDOFF)


def test_g5_a_swap_of_two_section_names_is_a_reorder_not_a_rename() -> None:
    base = HANDOFF_SEED
    tip = (
        base.replace("## Resume from here", "## @@")
        .replace("## What's running", "## Resume from here")
        .replace("## @@", "## What's running")
    )
    with pytest.raises(RefusalError, match="sections"):
        handoff_merge(base, tip, tip, HANDOFF)


# Extra pins found by the teeth run ----------------------------------------------


def test_g1_a_path_the_session_pushed_and_origin_later_edited_is_not_a_conflict(
    tmp_path: Path,
) -> None:
    """Only changes since the merge-base count as the session's: a pushed note that a
    peer edited later must not trip the outside-the-allowlist refusal."""
    _remote, local, peer, base = _make_vault(tmp_path)
    note = "personal/projects/proj-a.md"
    _write(local, note, NOTE_SEED + "\nSession paragraph.\n")
    _commit_all(local, "mid-session note edit")
    _git(local, "push", "-q")
    _git(peer, "pull", "-q", "--ff-only")
    _write(peer, note, _read(peer, note) + "\nPeer paragraph.\n")
    _write(peer, GOTCHAS, insert_under(_read(peer, GOTCHAS), "## Technical", PEER_GOTCHA))
    _peer_push(peer)
    _write(local, GOTCHAS, insert_under(_read(local, GOTCHAS), "## Technical", PUSHED_GOTCHA))
    _commit_all(local, "vault wrap-up (end of session)")

    report = _run_replay(local, base, *_health_args(tmp_path, HEALTH_OK))

    assert report["action"] == "replayed", report
    assert report["conflicts"] == [GOTCHAS]
    assert "Peer paragraph." in _read(local, note)


def test_g3_a_predecessor_duplicated_on_origin_falls_back_to_the_successor() -> None:
    base = GOTCHAS_SEED
    new = gotchas_entry("Session mid entry", "2026-09-12", "Mid body.")
    tip = base.replace(
        "### Bytecode cache hides a mutation (2026-09-10)", new + "\n### Bytecode cache hides a mutation (2026-09-10)"
    )
    first = gotchas_entry("Stale tracking refs lie after a push", "2026-09-15", "Body of the tracking-ref gotcha.\nSecond line of that body.")
    origin = insert_under(base, "## Technical", first)  # a second, byte-identical copy
    merged, _detail = ledger_merge(base, tip, origin, GOTCHAS)
    titles = _gotcha_titles(merged)
    assert titles.index("### Session mid entry (2026-09-12)") == titles.index(
        "### Bytecode cache hides a mutation (2026-09-10)"
    ) - 1


def test_g3_an_entry_after_an_edited_predecessor_stays_directly_after_it_despite_an_origin_insert() -> None:
    base = GOTCHAS_SEED
    new = gotchas_entry("Session mid entry", "2026-09-12", "Mid body.")
    tip = base.replace(
        "### Bytecode cache hides a mutation (2026-09-10)", new + "\n### Bytecode cache hides a mutation (2026-09-10)"
    ).replace("Second line of that body.", "Second line, edited by the session.")
    peer = gotchas_entry("Origin middle entry", "2026-09-13", "Peer body.")
    origin = base.replace(
        "### Bytecode cache hides a mutation (2026-09-10)", peer + "\n### Bytecode cache hides a mutation (2026-09-10)"
    )
    merged, _detail = ledger_merge(base, tip, origin, GOTCHAS)
    assert _gotcha_titles(merged)[:4] == [
        "### Stale tracking refs lie after a push (2026-09-15)",
        "### Session mid entry (2026-09-12)",
        "### Origin middle entry (2026-09-13)",
        "### Bytecode cache hides a mutation (2026-09-10)",
    ]
    assert "edited by the session" in merged


def test_g2_the_last_inserted_item_keeps_the_sessions_separator_to_the_same_next_item() -> None:
    """The session wrote n2 tight against b; origin still follows a with b, so the
    session's separator is authoritative (backtest pair 6e450eec..c8a4cca2)."""
    base = _section("\n- a\n\n- b\n")
    tip = _section("\n- a\n\n- n1\n- n2\n- b\n")
    merged, _detail = handoff_merge(base, tip, base, HANDOFF)
    assert "\n- a\n\n- n1\n- n2\n- b\n" in merged


def test_g2_the_last_inserted_item_takes_origins_anchor_separator_when_origin_inserted_after_it() -> None:
    """Origin put o1 after a, so n1 is now followed by o1, not by the b the session
    wrote against: it takes the separator origin's anchor had."""
    base = _section("\n- a\n\n- b\n")
    origin = _section("\n- a\n\n- o1\n\n- b\n")
    tip = _section("\n- a\n\n- n1\n- b\n")
    merged, _detail = handoff_merge(base, tip, origin, HANDOFF)
    assert "\n- a\n\n- n1\n\n- o1\n\n- b\n" in merged


def test_g4_a_ledgers_frontmatter_description_is_plain_line_arithmetic() -> None:
    """In a ledger there is no rule-resolved line: dropping the session's description
    change is a missing line, and origin's description is simply origin's addition."""

    def ledger(desc: str) -> str:
        return f'---\ndescription: "{desc}"\n---\n\n# Gotchas\n'

    verdict = compare_texts(ledger("g"), ledger("g2"), ledger("g3"), ledger("g3"), GOTCHAS)
    assert verdict["missing"] == ['description: "g2"']
    assert verdict["extra"] == []
    assert verdict["resolved"] == []


def test_g4_a_stamp_line_inside_a_section_is_not_part_of_the_stamp_rule() -> None:
    base = _hand("d", "1")
    tip = _hand("d", "1", "- a\n- b\n_Updated 9._\n")
    origin = _hand("d", "3")
    result = _hand("d", "3", "- a\n- b\n_Updated 9._\n")
    verdict = compare_texts(base, tip, origin, result, HANDOFF)
    assert verdict["missing"] == [] and verdict["extra"] == []
    assert "_Updated 3._" in verdict["resolved"] and "_Updated 9._" not in verdict["resolved"]


# ---------------------------------------------------------------------------
# Round 4 -- the fourth adversarial pass: two structural invariants (S1, S2)
# that close the class "the line-level self-check cannot see it", then the
# point fixes P-a..P-e.
# ---------------------------------------------------------------------------

import random  # noqa: E402

from entry_replay import _merge_hub_file  # noqa: E402

_NOTES_TAIL = "\n## Mode\n\nVault first.\n"


def _notes(body: str) -> str:
    """A handoff whose only touched section is ``## Notes`` with ``body`` as its text."""
    return _hd("## Notes\n" + body + _NOTES_TAIL)


def _with_origin_stamp(text: str) -> str:
    return text.replace("_Updated 2026-10-10_", "_Updated 2026-10-11_")


# S1 -- origin did not change a unit => the merged unit is the session's, byte for byte

S1_HANDOFF_CASES = {
    "insert mid tight list": ("\n- a\n- b\n- c\n", "\n- a\n- n\n- b\n- c\n"),
    "insert into a loose list": ("\n- a\n\n- b\n", "\n- a\n\n- n\n\n- b\n"),
    "insert at the top": ("\n- a\n- b\n", "\n- n\n- a\n- b\n"),
    "append a bullet": ("\n- a\n- b\n", "\n- a\n- b\n- n\n"),
    "paragraph after a tight list": ("\n- a\n- b\n", "\n- a\n- b\n\nClosing paragraph.\n"),
    "paragraph after a paragraph": ("\nOne.\n", "\nOne.\n\nTwo.\n"),
    "bullets after a paragraph stay tight": ("\nIntro.\n", "\nIntro.\n\n- n1\n- n2\n"),
    "delete a bullet before a paragraph": (
        "\n- a open\n- b resolved\n\nCarried paragraph.\n",
        "\n- a open\n\nCarried paragraph.\n",
    ),
    "delete a bullet between paragraphs": (
        "\nIntro.\n\n- x\n\nOutro.\n",
        "\nIntro.\n\nOutro.\n",
    ),
    "delete the last bullet": ("\n- a\n- b\n", "\n- a\n"),
    "delete the first bullet": ("\n- a\n\n- b\n", "\n- b\n"),
    "delete every item": ("\n- a\n- b\n", "\n"),
    "replace a bullet with a paragraph": (
        "\n- a\n- b\n- c\n",
        "\n- a\n\nb is now a paragraph.\n- c\n",
    ),
    "replace a paragraph with a bullet": (
        "\n- a\n\nPara.\n\n- c\n",
        "\n- a\n- Para as a bullet.\n\n- c\n",
    ),
    "replace one bullet with two": ("\n- a\n- b\n- c\n", "\n- a\n- b1\n- b2\n- c\n"),
    "reword the last bullet": ("\n- a\n- b\n", "\n- a\n- b reworded\n"),
    "reword an item with a continuation": (
        "\n- a\n  continued\n- b\n",
        "\n- a\n  continued, reworded\n- b\n",
    ),
    "tighten a loose list": ("\n- a\n\n- b\n\n- c\n", "\n- a\n- b\n- c\n"),
    "loosen a tight list": ("\n- a\n- b\n- c\n", "\n- a\n\n- b\n\n- c\n"),
    "a double blank collapses": ("\n- a\n\n\n- b\n", "\n- a\n\n- b\n"),
    "insert and delete in one section": (
        "\n- a\n- b\n\nTail.\n",
        "\n- n\n- a\n\nTail.\n\n- m\n",
    ),
    "delete a fenced item": (
        "\n- a\n- f\n  ```\n  code\n\n  more\n  ```\n- c\n\nTail.\n",
        "\n- a\n- c\n\nTail.\n",
    ),
    "insert a fenced paragraph": (
        "\n- a\n\nTail.\n",
        "\n- a\n\n```\ncode\n\n- not a bullet\n```\n\nTail.\n",
    ),
    "a repeated Links bullet": (
        "\n**A** a.\n- Links: [[x]]\n\n**B** b.\n- Links: [[x]]\n",
        "\n**A** a.\n- Links: [[x]]\n\n**B** b.\n- Links: [[x]]\n\n**C** c.\n- Links: [[x]]\n",
    ),
}


@pytest.mark.parametrize("case", sorted(S1_HANDOFF_CASES))
def test_s1_handoff_reproduces_the_session_when_origin_did_not_change_the_section(case: str) -> None:
    base_body, tip_body = S1_HANDOFF_CASES[case]
    base, tip = _notes(base_body), _notes(tip_body)
    origin = _with_origin_stamp(base)  # origin only moved the stamp
    merged, _detail = handoff_merge(base, tip, origin, HANDOFF)
    assert merged == _with_origin_stamp(tip), case
    # ...and with origin == base the whole file is the session's, byte for byte.
    assert handoff_merge(base, tip, base, HANDOFF)[0] == tip, case


def _random_handoff_pair(seed: int) -> tuple[str, str]:
    """A base ``## Notes`` section and a session edit of it: random items, separators and edits."""
    rng = random.Random(seed)
    counter = [0]

    def item() -> tuple[str, list[str]]:
        counter[0] += 1
        n = counter[0]
        kind = rng.choice(
            ["bullet", "bullet", "bullet", "para", "cont", "links", "fence", "fenced-para", "spaced"]
        )
        return {
            "bullet": ("b", [f"- item {n}"]),
            "cont": ("b", [f"- item {n}", f"  continued {n}"]),
            "links": ("b", ["- Links: [[x]]"]),
            "para": ("p", [f"Paragraph {n}."]),
            "fence": ("b", [f"- fenced {n}", "  ```", f"  code {n}", "", "  more", "  ```"]),
            "fenced-para": ("p", ["```", f"code {n}", "", "- not a bullet", "```"]),
            "spaced": ("b", [f"- spaced {n}", "  "]),
        }[kind]

    def render(items: list[tuple[str, list[str]]], seps: list[int]) -> str:
        seps = [
            max(sep, 1) if pos + 1 < len(items) and items[pos + 1][0] == "p" else sep
            for pos, sep in enumerate(seps)
        ]
        lines = [""]
        for (_kind, body), sep in zip(items, seps, strict=True):
            lines.extend(body)
            lines.extend([""] * sep)
        while lines and lines[-1] == "":
            lines.pop()
        return "\n".join([*lines, ""]) + "\n"

    items = [item() for _ in range(rng.randint(1, 6))]
    seps = [rng.choice([0, 0, 1, 1, 2]) for _ in items]
    tip_items, tip_seps = list(items), list(seps)
    for _ in range(rng.randint(1, 3)):
        op = rng.choice(["insert", "insert", "delete", "replace", "separator"])
        if op == "insert":
            at = rng.randint(0, len(tip_items))
            new = [item() for _ in range(rng.randint(1, 3))]
            tip_items[at:at] = new
            tip_seps[at:at] = [rng.choice([0, 0, 1, 1]) for _ in new]
        elif op == "delete" and tip_items:
            at = rng.randrange(len(tip_items))
            span = rng.randint(1, min(2, len(tip_items) - at))
            del tip_items[at : at + span], tip_seps[at : at + span]
        elif op == "replace" and tip_items:
            at = rng.randrange(len(tip_items))
            new = [item() for _ in range(rng.randint(1, 2))]
            tip_items[at : at + 1] = new
            tip_seps[at : at + 1] = [rng.choice([0, 1, 1]) for _ in new]
        elif op == "separator" and tip_seps:
            tip_seps[rng.randrange(len(tip_seps))] = rng.choice([0, 1, 2])
    return render(items, seps), render(tip_items, tip_seps)


def test_s1_random_handoff_edits_reproduce_the_session_byte_for_byte() -> None:
    checked = 0
    for seed in range(600):
        base_body, tip_body = _random_handoff_pair(seed)
        if base_body == tip_body:
            continue
        base, tip = _notes(base_body), _notes(tip_body)
        merged, _detail = handoff_merge(base, tip, base, HANDOFF)
        assert merged == tip, f"seed {seed}: {base_body!r} -> {tip_body!r} gave {merged!r}"
        checked += 1
    assert checked > 500, "the generator must produce real edits, not a vacuous pass"


def _gotchas_block(entries: str, tail: str = "") -> str:
    return f"# Gotchas\n\n## Technical\n\n{entries}{tail}"


def _brag_block(entries: str, tail: str = "") -> str:
    return f"# Brag Doc\n\n## Q3 2026\n\n### Wins\n\n{entries}{tail}"


_A = "- **2026-09-02 — A.** a detail.\n"
_B = "- **2026-09-01 — B.** b detail.\n  continued.\n"
_N = "- **2026-09-03 — N.** new detail.\n"
_M = "- **2026-09-04 — M.** more new detail.\n"
_G1 = "### One (2026-09-02)\n\nBody one.\n"
_G2 = "### Two (2026-09-01)\n\nBody two.\n"
_GN = "### New (2026-09-03)\n\nBody new.\n"

S1_LEDGER_CASES = {
    "tight list: insert mid": (_brag_block(_A + _B), _brag_block(_A + _N + _B)),
    "tight list: append": (_brag_block(_A + _B), _brag_block(_A + _B + _N)),
    "tight list: insert at top": (_brag_block(_A + _B), _brag_block(_N + _A + _B)),
    "loose list: insert mid": (_brag_block(_A + "\n" + _B), _brag_block(_A + "\n" + _N + "\n" + _B)),
    "loose list: append before another anchor": (
        _brag_block(_A + "\n" + _B + "\n", "### Growth\n\nOther.\n"),
        _brag_block(_A + "\n" + _B + "\n" + _N + "\n", "### Growth\n\nOther.\n"),
    ),
    "loose list ending the file: append keeps no trailing blank": (
        _brag_block(_A + "\n" + _B),
        _brag_block(_A + "\n" + _B + "\n" + _N),
    ),
    "loose list ending the file: insert mid": (
        _brag_block(_A + "\n" + _B),
        _brag_block(_A + "\n" + _N + "\n" + _B),
    ),
    "mixed separators: append two": (
        _brag_block(_A + _B),
        _brag_block(_A + _B + _N + "\n" + _M),
    ),
    "headings: insert at the top": (
        _gotchas_block(_G1 + "\n" + _G2), _gotchas_block(_GN + "\n" + _G1 + "\n" + _G2)
    ),
    "headings: append at the end of the file": (
        _gotchas_block(_G1 + "\n" + _G2), _gotchas_block(_G1 + "\n" + _G2 + "\n" + _GN)
    ),
    "headings with double blanks: insert mid": (
        _gotchas_block(_G1 + "\n\n" + _G2), _gotchas_block(_G1 + "\n\n" + _GN + "\n" + _G2)
    ),
    "edit in place and widen its separator": (
        _gotchas_block(_G1 + "\n" + _G2),
        _gotchas_block(_G1.replace("Body one.", "Body one, edited.") + "\n\n" + _G2),
    ),
    "only the blank lines change": (
        _brag_block(_A + _B), _brag_block(_A + "\n" + _B)
    ),
    "only the preamble spacing changes": (
        "# Brag Doc\n\n## Q3 2026\n\n### Wins\nTop note.\n" + _A,
        "# Brag Doc\n\n## Q3 2026\n\n### Wins\nTop note.\n\n\n" + _A,
    ),
    "preamble spacing and an insertion": (
        "# Brag Doc\n\n## Q3 2026\n\n### Wins\nTop note.\n" + _A,
        "# Brag Doc\n\n## Q3 2026\n\n### Wins\nTop note.\n\n" + _N + _A,
    ),
}


@pytest.mark.parametrize("case", sorted(S1_LEDGER_CASES))
def test_s1_ledger_reproduces_the_session_when_origin_did_not_change_the_block(case: str) -> None:
    base, tip = S1_LEDGER_CASES[case]
    merged, _detail = ledger_merge(base, tip, base, BRAG)
    assert merged == tip, case


def _random_ledger_pair(seed: int) -> tuple[str, str]:
    rng = random.Random(seed)
    counter = [0]
    heading = rng.random() < 0.5

    def entry() -> list[str]:
        counter[0] += 1
        n = counter[0]
        day = f"2026-09-{n:02d}"  # one entry per day: an edit pairs with its entry unambiguously
        if heading:
            second = [f"Second {n}."] if rng.random() < 0.5 else []
            return [f"### Title {n} ({day})", "", f"Body {n}.", *second]
        return [f"- **{day} — Win {n}.** Detail {n}.", *([f"  cont {n}"] if rng.random() < 0.5 else [])]

    def render(entries: list[list[str]], seps: list[int], preamble: list[str]) -> str:
        lines = ["# Doc", "", "## Technical" if heading else "### Wins", *preamble]
        for lines_of, sep in zip(entries, seps, strict=True):
            lines.extend(lines_of)
            lines.extend([""] * sep)
        if tail:
            lines.extend(["## Process" if heading else "### Growth", "", "Other."])
        return "\n".join(lines) + "\n"

    tail = rng.random() < 0.5
    entries = [entry() for _ in range(rng.randint(1, 5))]
    low = 1 if heading else 0
    seps = [rng.choice([low, 1, 1, 2]) for _ in entries]
    preamble = rng.choice([[""], [""], ["Preamble text.", ""]])
    if not tail and rng.random() < 0.7:
        seps[-1] = 0
    tip_entries, tip_seps = list(entries), list(seps)
    for _ in range(rng.randint(1, 3)):
        op = rng.choice(["insert", "insert", "edit", "separator"])
        if op == "insert":
            at = rng.randint(0, len(tip_entries))
            new = [entry() for _ in range(rng.randint(1, 2))]
            tip_entries[at:at] = new
            tip_seps[at:at] = [rng.choice([low, 1, 1]) for _ in new]
        elif op == "edit":
            at = rng.randrange(len(tip_entries))
            tip_entries[at] = [*tip_entries[at][:-1], tip_entries[at][-1] + " EDITED"]
        elif op == "separator":
            tip_seps[rng.randrange(len(tip_seps))] = rng.choice([low, 1, 2])
    return render(entries, seps, preamble), render(tip_entries, tip_seps, preamble)


def test_s1_random_ledger_edits_reproduce_the_session_byte_for_byte() -> None:
    checked = 0
    for seed in range(600):
        base, tip = _random_ledger_pair(seed)
        if base == tip:
            continue
        merged, _detail = ledger_merge(base, tip, base, GOTCHAS)
        assert merged == tip, f"seed {seed}: {base!r} -> {tip!r} gave {merged!r}"
        checked += 1
    assert checked > 500


def test_s1_assertion_refuses_a_handoff_section_that_differs_from_the_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import entry_replay

    base, tip = _notes("\n- a\n- b\n"), _notes("\n- a\n- b\n- n\n")
    monkeypatch.setattr(
        entry_replay, "_merge_section_items", lambda *args, **kwargs: ["", "- a", "- b", "", "- n"]
    )
    with pytest.raises(RefusalError, match="structural self-check: section '## Notes' differs"):
        handoff_merge(base, tip, base, HANDOFF)
    # Origin changed the section: the session's text is no longer the target, so
    # the exactness assertion stays out of the way (the item-level check owns it).
    origin = _notes("\n- a\n- b\n- o\n")
    handoff_merge(base, tip, origin, HANDOFF)


def test_s1_assertion_refuses_a_ledger_block_that_differs_from_the_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import entry_replay

    base, tip = _brag_block(_A + _B), _brag_block(_A + _N + _B)
    monkeypatch.setattr(
        entry_replay, "_splice_interior", lambda *args, **kwargs: ["", *_A.splitlines(), *_B.splitlines()]
    )
    with pytest.raises(RefusalError, match="structural self-check: block .* differs"):
        ledger_merge(base, tip, base, BRAG)
    origin = _brag_block(_A + _B + _M)
    ledger_merge(base, tip, origin, BRAG)


# S2 -- no merged item that neither side wrote

GLUE_BASE = _notes("\n- a open\n- b resolved\n\nCarried paragraph.\n")
GLUE_TIP = _notes("\n- a open\n\nCarried paragraph.\n")
GLUE_GLUED = _notes("\n- a open\nCarried paragraph.\n")


def test_s2_compare_texts_reports_a_glued_item_the_line_check_cannot_see() -> None:
    verdict = compare_texts(GLUE_BASE, GLUE_TIP, GLUE_BASE, GLUE_GLUED, HANDOFF)
    assert verdict["missing"] == [] and verdict["extra"] == []
    assert len(verdict["glued"]) == 1 and "Carried paragraph." in verdict["glued"][0]
    assert compare_texts(GLUE_BASE, GLUE_TIP, GLUE_BASE, GLUE_TIP, HANDOFF)["glued"] == []


def test_s2_an_item_beyond_what_either_side_holds_is_glued() -> None:
    base, tip = _notes("\n- a\n"), _notes("\n- a\n- n\n")
    thrice = _notes("\n- a\n- n\n- n\n- n\n")
    assert compare_texts(base, tip, base, thrice, HANDOFF)["glued"]
    both_added = compare_texts(base, tip, _notes("\n- a\n- n\n"), _notes("\n- a\n- n\n- n\n"), HANDOFF)
    assert both_added["glued"] == [], "an item both sides wrote may stand twice"


def test_s2_merge_refuses_a_glued_handoff_item(monkeypatch: pytest.MonkeyPatch) -> None:
    import entry_replay

    origin = _hd("## Other\n\n- o\n\n") + "## Notes\n- a open\n- b resolved\n\nCarried paragraph.\n"
    base = _hd("## Other\n\n- x\n\n") + "## Notes\n- a open\n- b resolved\n\nCarried paragraph.\n"
    tip = _hd("## Other\n\n- x\n\n") + "## Notes\n- a open\n\nCarried paragraph.\n"
    glued = _hd("## Other\n\n- o\n\n") + "## Notes\n- a open\nCarried paragraph.\n"
    monkeypatch.setattr(entry_replay, "handoff_merge", lambda *a, **k: (glued, {"unchanged": False}))
    with pytest.raises(RefusalError, match="structural self-check: merged section 'Notes' contains an item"):
        _merge_hub_file(HANDOFF, base, tip, origin)


def test_s2_merge_refuses_a_ledger_entry_whose_lines_landed_under_another_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every line is there, but N's continuation moved under B: the line check passes."""
    import entry_replay

    note = "- **2026-09-03 — N.** new detail.\n  n continuation.\n"
    base = _brag_block(_A + "\n" + _B)
    tip = _brag_block(_A + "\n" + note + "\n" + _B)
    origin = _brag_block(_A + "\n" + _B + "\n" + _M)
    moved = _brag_block(
        _A
        + "\n- **2026-09-03 — N.** new detail.\n\n"
        + "- **2026-09-01 — B.** b detail.\n  n continuation.\n  continued.\n"
        + "\n"
        + _M
    )
    monkeypatch.setattr(entry_replay, "ledger_merge", lambda *a, **k: (moved, {"unchanged": False}))
    with pytest.raises(RefusalError, match="structural self-check: merged block .* contains an item"):
        _merge_hub_file(BRAG, base, tip, origin)


def test_s2_real_merges_with_origin_edits_never_trip_the_glue_check() -> None:
    """A correct merge has no glued item: origin edits the same section, the check stays quiet."""
    merged_count = 0
    for seed in range(300):
        base_body, tip_body = _random_handoff_pair(seed)
        _unused, origin_body = _random_handoff_pair(seed)  # same base, an independent-looking edit
        origin_body = _random_handoff_pair(seed + 5000)[1] if False else origin_body
        base, tip, origin = _notes(base_body), _notes(tip_body), _notes(origin_body)
        try:
            _merge_hub_file(HANDOFF, base, tip, origin)
        except RefusalError as exc:
            assert "structural self-check" not in str(exc), f"seed {seed}: {exc}"
            continue
        merged_count += 1
    assert merged_count > 100


def test_s2_verify_fails_on_a_glued_rebuild(tmp_path: Path) -> None:
    _remote, local, peer, _seed_base = _make_vault(tmp_path)
    carried = _read(local, HANDOFF).replace(
        "- [[proj-b]]: close the parity ticket.\n",
        "- [[proj-b]]: close the parity ticket.\n- [[proj-c]]: resolved thread.\n\nCarried paragraph.\n",
    )
    _write(local, HANDOFF, carried)
    _commit_all(local, "seed the carried paragraph")
    _git(local, "push", "-q")
    _git(peer, "pull", "-q", "--ff-only")
    base = _head(local)
    _write(peer, HANDOFF, _read(peer, HANDOFF).replace("Nothing unattended.", "One probe running."))
    origin = _peer_push(peer)
    _write(local, HANDOFF, carried.replace("- [[proj-c]]: resolved thread.\n", ""))
    tip = _commit_all(local, "session resolves the thread")
    _git(local, "fetch", "-q", "origin")
    _git(local, "switch", "-q", "-c", "rebuild", origin)
    glued = (
        _read(local, HANDOFF)
        .replace("- [[proj-c]]: resolved thread.\n", "")
        .replace("ticket.\n\nCarried paragraph.", "ticket.\nCarried paragraph.")
    )
    _write(local, HANDOFF, glued)
    result = _commit_all(local, "glued rebuild")
    _git(local, "switch", "-q", "main")

    proc = _verify(local, base, tip, origin, result)

    assert proc.returncode == 1, proc.stdout + proc.stderr
    entry = json.loads(proc.stdout)["files"][HANDOFF]
    assert entry["glued"] and "Carried paragraph." in entry["glued"][0]
    assert entry["missing"] == [] and entry["extra"] == []
    text = _run_raw(
        local, "--verify", "--base", base, "--tip", tip, "--origin", origin, "--result", result
    ).stdout
    assert "glued:" in text and "verify: FAIL" in text


# P-a -- the item before a deleted or replaced run takes the session's separator


def test_pa_deleting_a_bullet_keeps_the_blank_line_before_the_paragraph_that_followed_it() -> None:
    base = _hd(
        "## Open threads\n\n- a open\n- b resolved\n\nCarried paragraph.\n\n## Mode\n\nVault first.\n"
    )
    tip = base.replace("- b resolved\n", "")
    origin = base.replace("Vault first.", "Vault first, and tests.")
    merged, _detail = handoff_merge(base, tip, origin, HANDOFF)
    assert "- a open\n\nCarried paragraph.\n" in merged
    assert merged == tip.replace("Vault first.", "Vault first, and tests.")


def test_pa_turning_a_tight_bullet_into_a_paragraph_keeps_it_apart_from_the_bullet_above() -> None:
    base = _hd("## Open threads\n\n- a open\n- b open\n- c open\n\n## Mode\n\nVault first.\n")
    tip = base.replace("- b open\n", "\nb is now a paragraph.\n")
    origin = base.replace("Vault first.", "Vault first, and tests.")
    merged, _detail = handoff_merge(base, tip, origin, HANDOFF)
    assert "- a open\n\nb is now a paragraph.\n- c open\n" in merged


def test_pa_a_bullet_deleted_next_to_an_item_origin_added_does_not_glue() -> None:
    base = _hd("## Open threads\n\n- a open\n- b resolved\n\nCarried paragraph.\n\n## Mode\n\nVault first.\n")
    tip = base.replace("- b resolved\n", "")
    origin = base.replace("- a open\n", "- a open\n- o added by origin\n")
    merged, _detail = handoff_merge(base, tip, origin, HANDOFF)
    assert "- o added by origin\n\nCarried paragraph.\n" in merged
    assert "- b resolved" not in merged


# P-b -- an inserted item is a duplicate only of what origin put in the same gap

TOPICS_BASE = _notes("\n**Topic A** a.\n- Links: [[x]]\n\n**Topic B** b.\n")


def test_pb_a_links_bullet_survives_an_identical_one_origin_added_elsewhere() -> None:
    tip = TOPICS_BASE.replace(_NOTES_TAIL, "\n**Topic C** c.\n- Links: [[x]]\n" + _NOTES_TAIL)
    origin = TOPICS_BASE.replace(
        "\n**Topic B** b.", "**Topic D** d.\n- Links: [[x]]\n\n**Topic B** b."
    ).replace("- Links: [[x]]\n**Topic D**", "- Links: [[x]]\n\n**Topic D**")
    merged, _detail = handoff_merge(TOPICS_BASE, tip, origin, HANDOFF)
    assert "**Topic C** c.\n- Links: [[x]]\n" in merged
    assert merged.count("- Links: [[x]]") == 3
    assert "**Topic D** d.\n- Links: [[x]]\n" in merged


def test_pb_an_item_both_sides_added_in_the_same_gap_is_still_not_inserted_twice() -> None:
    base = _notes("\n- a\n- b\n")
    tip = _notes("\n- a\n- b\n- shared\n")
    origin = _notes("\n- a\n- b\n- shared\n- o\n")
    merged, _detail = handoff_merge(base, tip, origin, HANDOFF)
    assert merged.count("- shared") == 1 and "- o" in merged


# P-c -- a new ledger entry keeps the session's own blank lines


def test_pc_a_new_entry_is_not_glued_to_a_neighbour_origin_left_without_a_blank_line() -> None:
    base = _brag_block(_A + "\n" + _B)
    tip = _brag_block(_A + "\n" + _N + "\n" + _B)
    origin = _brag_block(_A + _B)  # origin tightened the list
    merged, _detail = ledger_merge(base, tip, origin, BRAG)
    assert merged == _brag_block(_A + "\n" + _N + "\n" + _B)


def test_pc_an_entry_appended_after_the_same_predecessor_as_origins_keeps_a_blank_before_origins() -> None:
    base = _brag_block(_A)
    tip = _brag_block(_A + "\n" + _N)
    origin = _brag_block(_A + _M)  # tight, ends the file
    merged, _detail = ledger_merge(base, tip, origin, BRAG)
    assert merged == _brag_block(_A + "\n" + _N + "\n" + _M)


def test_pc_a_tight_session_list_stays_tight_when_origin_is_loose() -> None:
    base = _brag_block(_A + _B)
    tip = _brag_block(_A + _N + _B)
    origin = _brag_block(_A + "\n" + _B + "\n" + _M)
    merged, _detail = ledger_merge(base, tip, origin, BRAG)
    assert _A + _N + "\n" + _B in merged or _A + _N + _B in merged
    assert "N.** new detail.\n- **2026-09-01" in merged, "the session's tight separator after N is kept"


def test_pc_a_new_entry_at_the_top_takes_the_sessions_separator_under_the_preamble() -> None:
    base = _gotchas_block(_G1 + "\n" + _G2)
    tip = _gotchas_block(_GN + "\n" + _G1 + "\n" + _G2)
    origin = base.replace("Body two.", "Body two, edited on origin.")
    merged, _detail = ledger_merge(base, tip, origin, GOTCHAS)
    assert merged == _gotchas_block(_GN + "\n" + _G1 + "\n" + _G2.replace("Body two.", "Body two, edited on origin."))


# P-d -- the amend guard: the session re-adds an entry origin already has since the base


def test_pd_an_amended_pushed_entry_refuses(tmp_path: Path) -> None:
    _remote, local, peer, base = _make_vault(tmp_path)
    pushed = gotchas_entry("Retry budget", "2026-09-18", "The probe gives up after 3 retries.")
    _write(local, GOTCHAS, insert_under(_read(local, GOTCHAS), "## Technical", pushed))
    _commit_all(local, "vault wrap-up (mid-session)")
    _git(local, "push", "-q")
    _git(peer, "pull", "-q", "--ff-only")
    # The session amends the pushed commit: the entry now says 5 retries.
    _write(local, GOTCHAS, _read(local, GOTCHAS).replace("after 3 retries", "after 5 retries"))
    _git(local, "add", "-A")
    _git(local, "commit", "-q", "--amend", "--no-edit")
    peer_entry = gotchas_entry("Peer gotcha", "2026-09-19", "Peer body, nothing to do with retries.")
    _write(peer, GOTCHAS, insert_under(_read(peer, GOTCHAS), "## Technical", peer_entry))
    _peer_push(peer)
    head_before, branch_before = _head(local), _branch(local)

    report = _run_replay(local, base, *_health_args(tmp_path, HEALTH_OK), expect_rc=1)

    assert report["action"] == "refused"
    assert "amended or rebased" in report["reason"], report["reason"]
    _assert_untouched(local, head_before, branch_before)


def test_pd_the_guard_is_about_the_same_entry_not_every_same_day_entry() -> None:
    base = GOTCHAS_SEED
    theirs = gotchas_entry("Origin entry", "2026-09-20", "Origin explains the rate limiter in detail.")
    mine = gotchas_entry("Session entry", "2026-09-20", "A wholly separate matter: the cache warmed twice.")
    merged, detail = ledger_merge(
        base,
        insert_under(base, "## Technical", mine),
        insert_under(base, "## Technical", theirs),
        GOTCHAS,
    )
    assert detail["inserted"] == 1 and "Origin entry" in merged and "Session entry" in merged


def test_pd_the_same_entry_added_identically_on_both_sides_is_not_a_re_add() -> None:
    base = GOTCHAS_SEED
    both = gotchas_entry("Both wrote it", "2026-09-20", "Identical body.")
    merged, detail = ledger_merge(
        base, insert_under(base, "## Technical", both), insert_under(base, "## Technical", both), GOTCHAS
    )
    assert merged.count("### Both wrote it") == 1 and detail["duplicates_skipped"] == 1


# P-e -- origin already holds the session's edited version beside the base one


def test_pe_origin_holding_both_the_old_entry_and_a_copy_of_the_edit_refuses() -> None:
    base = GOTCHAS_SEED
    tip = base.replace("Second line of that body.", "Second line, corrected.")
    edited = gotchas_entry(
        "Stale tracking refs lie after a push",
        "2026-09-15",
        "Body of the tracking-ref gotcha.\nSecond line, corrected.",
    )
    origin = base.replace("### Bytecode cache hides a mutation (2026-09-10)", edited + "\n### Bytecode cache hides a mutation (2026-09-10)")
    with pytest.raises(RefusalError, match="twice"):
        ledger_merge(base, tip, origin, GOTCHAS)


def test_pe_origin_that_already_made_the_same_correction_still_accepts() -> None:
    base = GOTCHAS_SEED
    tip = base.replace("Second line of that body.", "Second line, corrected.")
    merged, detail = ledger_merge(base, tip, tip, GOTCHAS)
    assert merged == tip and detail["duplicates_skipped"] == 1


# Edges the mutation run asked for ---------------------------------------------


def test_pc_an_entry_written_before_a_neighbour_origin_removed_ends_origins_block() -> None:
    """The session wrote N before B, but origin removed B: N ends origin's block, so it
    takes origin's end-of-block separator, not the one that led into B."""
    base = _brag_block(_A + "\n" + _B)
    tip = _brag_block(_A + "\n" + _N + "\n" + _B)
    merged, _detail = ledger_merge(base, tip, _brag_block(_A), BRAG)
    assert merged == _brag_block(_A + "\n" + _N)


def test_pc_an_entry_ending_the_sessions_file_does_not_glue_to_the_next_anchor_on_origin() -> None:
    base = _brag_block(_A)
    tip = _brag_block(_A + "\n" + _N)  # the session's block ends the file
    origin = _brag_block(_A + "\n", "### Growth\n\nOther.\n")  # origin's does not
    merged, _detail = ledger_merge(base, tip, origin, BRAG)
    assert merged == _brag_block(_A + "\n" + _N + "\n", "### Growth\n\nOther.\n")


def test_pa_a_deleted_bullet_leaves_a_blank_before_a_paragraph_origin_appended() -> None:
    """The session's blank count for the item before the deletion was written against the
    end of the section; origin put a paragraph after the deleted bullet, so the blank
    that separated the bullet from it is kept."""
    base = _notes("\nPara.\n- b\n")
    tip = _notes("\nPara.\n")
    origin = _notes("\nPara.\n- b\n\nParagraph O.\n")
    merged, _detail = handoff_merge(base, tip, origin, HANDOFF)
    assert merged.split("## Notes")[1] == "\n\nPara.\n\nParagraph O.\n\n## Mode\n\nVault first.\n"


def test_s2_a_base_item_both_sides_kept_stands_once() -> None:
    base, tip = _notes("\n- a\n"), _notes("\n- a\n- n\n")
    twice = _notes("\n- a\n- a\n- n\n")
    assert compare_texts(base, tip, base, twice, HANDOFF)["glued"]
    assert compare_texts(base, tip, base, tip, HANDOFF)["glued"] == []


def test_pd_an_entry_similar_to_one_both_sides_already_had_is_not_a_re_add() -> None:
    """The guard is about entries origin ADDED since the base, not every entry on origin."""
    base = GOTCHAS_SEED
    twin = gotchas_entry(
        "Stale tracking refs lie after a push", "2026-09-15", "Body of the tracking-ref gotcha, restated."
    )
    tip = insert_under(base, "## Technical", twin)
    merged, detail = ledger_merge(base, tip, base.replace("Second line of that body.", "Edited on origin."), GOTCHAS)
    assert detail["inserted"] == 1 and merged.count("### Stale tracking refs lie after a push") == 2


def test_s1_a_ledger_separator_both_sides_changed_is_origins() -> None:
    base = _brag_block(_A + "\n" + _B)
    tip = _brag_block(_A + _B)  # the session tightened the list
    origin = _brag_block(_A + "\n\n" + _B)  # origin loosened it further
    merged, _detail = ledger_merge(base, tip, origin, BRAG)
    assert merged == origin


def test_s1_a_handoff_separator_both_sides_changed_is_origins() -> None:
    base = _notes("\n- a\n\n- b\n")
    tip = _notes("\n- a\n- b\n")
    origin = _notes("\n- a\n\n\n- b\n")
    assert handoff_merge(base, tip, origin, HANDOFF)[0] == origin


def test_s1_a_handoff_separator_is_not_carried_onto_an_item_origin_put_after_it() -> None:
    """The session tightened a against b; origin put o between them, so a's separator to o is
    origin's, not the session's."""
    base = _notes("\n- a\n\n- b\n\n- c\n")
    tip = _notes("\n- a\n- b\n\n- c\n")
    origin = _notes("\n- a\n\n- o\n\n- b\n\n- c\n")
    assert handoff_merge(base, tip, origin, HANDOFF)[0] == origin


def test_pa_an_item_origin_put_before_a_deleted_bullet_keeps_its_own_blank_line() -> None:
    base = _notes("\n- a\n- b\n- c\n")
    tip = _notes("\n- a\n- c\n")
    origin = _notes("\n- a\n- o\n\n- b\n- c\n")
    merged, _detail = handoff_merge(base, tip, origin, HANDOFF)
    assert merged.split("## Notes")[1].startswith("\n\n- a\n- o\n\n- c\n")


def test_pa_a_replacement_followed_by_something_origin_added_takes_origins_separator() -> None:
    base = _notes("\n- a\n- b\n- c\n")
    tip = _notes("\n- a\n\nPara x.\n\n- c\n")
    origin = _notes("\n- a\n- b\n- o\n- c\n")
    merged, _detail = handoff_merge(base, tip, origin, HANDOFF)
    assert merged.split("## Notes")[1].startswith("\n\n- a\n\nPara x.\n- o\n- c\n")


def test_pc_an_entry_inserted_at_the_top_takes_the_sessions_blank_lines_under_the_preamble() -> None:
    base = _brag_block(_A)
    tip = _brag_block(_N + _A)
    origin = base.replace("### Wins\n\n", "### Wins\n\n\n")  # origin widened the gap under the heading
    merged, _detail = ledger_merge(base, tip, origin, BRAG)
    assert merged == tip


# ---------------------------------------------------------------------------
# Fifth adversarial pass (H1-H5): granularity holes that accepted a content change.
# ---------------------------------------------------------------------------

import entry_replay as _er  # noqa: E402


def _items_of(merged: str) -> str:
    """The ``## Notes`` section's text of a merged ``_notes`` handoff."""
    return merged.split("## Notes")[1].split("## Mode")[0]


# H1 -- a session move+edit of a handoff item is an EDIT of that item


def test_h1a_a_moved_and_edited_item_origin_deleted_refuses() -> None:
    base = _notes("\n- A\n- X\n- B\n")
    tip = _notes("\n- X (updated)\n- A\n- B\n")
    origin = _notes("\n- A\n- B\n")
    with pytest.raises(RefusalError, match="moved and edited"):
        handoff_merge(base, tip, origin, HANDOFF)


def test_h1b_a_moved_and_edited_item_origin_also_edited_refuses() -> None:
    base = _notes("\n- a\n- x: check the gate\n- b\n")
    tip = _notes("\n- a\n- b\n- x: check the gate (session: still red)\n")
    origin = _notes("\n- a\n- b\n- x: check the gate (origin: done, green)\n")
    with pytest.raises(RefusalError, match="moved and edited"):
        handoff_merge(base, tip, origin, HANDOFF)


def test_h1_a_pure_move_of_an_item_origin_deleted_refuses() -> None:
    base = _notes("\n- A\n- X\n- B\n")
    tip = _notes("\n- X\n- A\n- B\n")
    origin = _notes("\n- A\n- B\n")
    with pytest.raises(RefusalError, match="moved and edited"):
        handoff_merge(base, tip, origin, HANDOFF)


def test_h1_a_pure_move_of_an_item_origin_left_alone_is_applied() -> None:
    base = _notes("\n- A\n- X\n- B\n")
    tip = _notes("\n- X\n- A\n- B\n")
    origin = _notes("\n- A\n- X\n- B\n- o\n")
    merged, _detail = handoff_merge(base, tip, origin, HANDOFF)
    assert _items_of(merged) == "\n\n- X\n- A\n- B\n- o\n\n"


def test_h1_a_move_with_an_edit_of_an_item_origin_left_alone_is_applied() -> None:
    base = _notes("\n- A\n- X\n- B\n")
    tip = _notes("\n- X (updated)\n- A\n- B\n")
    origin = _notes("\n- A\n- X\n- B\n- o\n")
    merged, _detail = handoff_merge(base, tip, origin, HANDOFF)
    assert _items_of(merged) == "\n\n- X (updated)\n- A\n- B\n- o\n\n"


def test_h1_the_same_move_and_edit_made_on_both_sides_is_already_applied() -> None:
    base = _notes("\n- a\n- x: check the gate\n- b\n")
    both = _notes("\n- a\n- b\n- x: check the gate (done)\n")
    merged, _detail = handoff_merge(base, both, both, HANDOFF)
    assert merged == both


def test_h1_an_unrelated_delete_and_insert_origin_also_made_are_not_a_pair() -> None:
    base = _notes("\n- a\n- x\n- b\n")
    tip = _notes("\n- a\n- b\n- wholly different\n")
    origin = _notes("\n- a\n- b\n")
    merged, _detail = handoff_merge(base, tip, origin, HANDOFF)
    assert merged == tip


# H2 -- the ledger amend guard is date-insensitive


def _retry_pair(session_day: str, session_title: str = "Retry storms need jitter", body: str | None = None):
    base = insert_under(
        GOTCHAS_SEED, "## Technical", gotchas_entry("Old thing", "2026-10-01", "Body here.")
    )
    text = (
        "Retry storms need jitter or every client retries in lockstep.\n"
        "Second line of it: the thundering herd comes back together."
    )
    origin = insert_under(
        base, "## Technical", gotchas_entry("Retry storms need jitter", "2026-10-01", text)
    )
    tip = insert_under(
        base, "## Technical", gotchas_entry(session_title, session_day, body or text)
    )
    return base, tip, origin


def test_h2_a_date_only_amend_of_a_pushed_entry_refuses() -> None:
    base, tip, origin = _retry_pair("2026-10-11")
    with pytest.raises(RefusalError, match="amended or rebased"):
        ledger_merge(base, tip, origin, GOTCHAS)


def test_h2_a_date_and_body_amend_with_the_same_heading_refuses() -> None:
    base, tip, origin = _retry_pair("2026-10-11", body="A body that was entirely rewritten.")
    with pytest.raises(RefusalError, match="amended or rebased"):
        ledger_merge(base, tip, origin, GOTCHAS)


def test_h2_a_date_changed_amend_with_a_similar_body_refuses() -> None:
    base, tip, origin = _retry_pair(
        "2026-10-11",
        session_title="Retry storms want jitter",
        body=(
            "Retry storms need jitter or every client retries in lockstep.\n"
            "Second line of it: the thundering herd comes back together, amended."
        ),
    )
    with pytest.raises(RefusalError, match="amended or rebased"):
        ledger_merge(base, tip, origin, GOTCHAS)


def test_h2_a_different_entry_on_a_different_day_is_not_an_amend() -> None:
    base, tip, origin = _retry_pair(
        "2026-10-11",
        session_title="Cache warmers double up",
        body="Nothing to do with it: the cache warmed twice at boot.",
    )
    merged, detail = ledger_merge(base, tip, origin, GOTCHAS)
    assert detail["inserted"] == 1
    assert "### Cache warmers double up (2026-10-11)" in merged
    assert "### Retry storms need jitter (2026-10-01)" in merged


def test_h2_the_edit_pairing_stays_date_sensitive() -> None:
    """``_same_entry_edited`` (the in-place-edit pairing) still needs the same date."""
    base = GOTCHAS_SEED
    tip = base.replace("(2026-09-15)", "(2026-09-16)")  # a re-dated entry is not an in-place edit
    with pytest.raises(RefusalError, match="deleted entry"):
        ledger_merge(base, tip, base.replace("Second line of that body.", "Edited."), GOTCHAS)


# H3 -- the handoff amend guard


def test_h3_a_session_item_similar_to_one_origin_inserted_in_the_same_gap_refuses() -> None:
    base = _notes("\n- a\n- b\n")
    tip = _notes("\n- a\n- foo bar\n- b\n")
    origin = _notes("\n- a\n- foo\n- b\n")
    with pytest.raises(RefusalError, match="amended or rebased"):
        handoff_merge(base, tip, origin, HANDOFF)


def test_h3_an_identical_first_line_with_a_different_continuation_refuses() -> None:
    base = _notes("\n- a\n- b\n")
    tip = _notes("\n- a\n- Next: ship it\n  with the second line\n- b\n")
    origin = _notes("\n- a\n- Next: ship it\n  and something else entirely\n- b\n")
    with pytest.raises(RefusalError, match="amended or rebased"):
        handoff_merge(base, tip, origin, HANDOFF)


def test_h3_an_identical_item_in_the_same_gap_is_still_deduped() -> None:
    base = _notes("\n- a\n- b\n")
    both = _notes("\n- a\n- foo\n- b\n")
    merged, _detail = handoff_merge(base, both, both, HANDOFF)
    assert merged == both


def test_h3_a_dissimilar_item_in_the_same_gap_is_kept_beside_origins() -> None:
    base = _notes("\n- a\n- b\n")
    tip = _notes("\n- a\n- the session wrote this\n- b\n")
    origin = _notes("\n- a\n- zzz origin wrote that\n- b\n")
    merged, _detail = handoff_merge(base, tip, origin, HANDOFF)
    assert "- the session wrote this" in merged and "- zzz origin wrote that" in merged


def test_h3_a_similar_item_origin_added_in_another_gap_is_not_an_amend() -> None:
    base = _notes("\n- a\n- b\n- c\n")
    tip = _notes("\n- a\n- foo bar\n- b\n- c\n")
    origin = _notes("\n- a\n- b\n- c\n- foo\n")
    merged, _detail = handoff_merge(base, tip, origin, HANDOFF)
    assert "- foo bar" in merged and "- foo\n" in merged


# H4 -- per-gap dedupe also consults the gap after a replaced run


def test_h4_an_item_origin_added_after_a_replaced_item_is_not_inserted_twice() -> None:
    base = _notes("\n- a\n- x\n- b\n")
    tip = _notes("\n- a\n- x2\n- y\n- b\n")
    origin = _notes("\n- a\n- x\n- y\n- b\n")
    merged, _detail = handoff_merge(base, tip, origin, HANDOFF)
    assert merged == tip


def test_h4_a_different_item_origin_added_after_the_replaced_one_is_kept() -> None:
    base = _notes("\n- a\n- x\n- b\n")
    tip = _notes("\n- a\n- x2\n- y\n- b\n")
    origin = _notes("\n- a\n- x\n- zzzz unrelated\n- b\n")
    merged, _detail = handoff_merge(base, tip, origin, HANDOFF)
    assert _items_of(merged) == "\n\n- a\n- x2\n- y\n- zzzz unrelated\n- b\n\n"


def test_h4_only_the_tail_of_a_replacement_is_deduped_against_the_next_gap() -> None:
    """A repeat that does not end the session's replacement is not origin's item: origin put
    its copy *after* the replaced run, so the session's leading copy is a deliberate one."""
    base = _notes("\n- a\n- x\n- b\n")
    tip = _notes("\n- a\n- y\n- x2\n- b\n")
    origin = _notes("\n- a\n- x\n- y\n- b\n")
    merged, _detail = handoff_merge(base, tip, origin, HANDOFF)
    assert _items_of(merged) == "\n\n- a\n- y\n- x2\n- y\n- b\n\n"


# H5 -- an unexpected exception in the merge phase is a refusal, not a traceback


def _conflicting_vault(tmp_path: Path) -> tuple[Path, str]:
    _remote, local, peer, base = _make_vault(tmp_path)
    peer_chunk = decisions_entry("2026-09-20", "Peer session decision", "**Decided:** peer thing.")
    _write(peer, DECISIONS, insert_under(_read(peer, DECISIONS), "## Recent", peer_chunk))
    _peer_push(peer)
    mine = decisions_entry("2026-09-18", "Session decision", "**Decided:** session thing.")
    _write(local, DECISIONS, insert_under(_read(local, DECISIONS), "## Recent", mine))
    _commit_all(local, "vault wrap-up")
    return local, base


def test_h5_an_internal_error_in_the_merge_phase_is_a_refusal_with_a_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    local, base = _conflicting_vault(tmp_path)
    for key, value in _env().items():
        monkeypatch.setenv(key, value)
    monkeypatch.chdir(local)

    def boom(*_args: object, **_kwargs: object) -> object:
        raise ValueError("boom")

    monkeypatch.setattr(_er, "ledger_merge", boom)
    head_before, branch_before = _head(local), _branch(local)

    rc = _er.main(["--base", base, "--json", *_health_args(tmp_path, HEALTH_OK)])

    out = json.loads(capsys.readouterr().out)
    assert rc == 1 and out["action"] == "refused"
    assert "internal error while merging brain/Key Decisions.md: ValueError: boom" in out["reason"]
    assert "escalating" in out["reason"]
    assert out["refusals"] == [{"path": DECISIONS, "reason": out["reason"]}]
    _assert_untouched(local, head_before, branch_before)


def test_h5_a_git_failure_is_still_reported_as_a_git_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local, base = _conflicting_vault(tmp_path)
    for key, value in _env().items():
        monkeypatch.setenv(key, value)
    monkeypatch.chdir(local)

    def git_boom(*_args: object, **_kwargs: object) -> object:
        raise _er.GitError("simulated")

    monkeypatch.setattr(_er, "ledger_merge", git_boom)
    report = _er.replay(_git(local, "rev-parse", base), "origin", None)
    assert report.action == "refused" and report.reason == "git failure: simulated"


def test_h2_entries_of_different_days_sharing_boilerplate_are_not_an_amend() -> None:
    base = DECISIONS_SEED
    theirs = decisions_entry("2026-09-24", "Peer session decision", "**Decided:** peer thing.")
    mine = decisions_entry("2026-09-23", "Worktree session decision", "**Decided:** session thing.")
    merged, detail = ledger_merge(
        base,
        insert_under(base, "## Recent", mine),
        insert_under(base, "## Recent", theirs),
        DECISIONS,
    )
    assert detail["inserted"] == 1 and "Peer session decision" in merged and "Worktree" in merged


def test_h2_a_one_line_bullet_with_the_same_text_on_another_day_is_an_amend() -> None:
    base = _brag_block(_A)
    pushed = "- **2026-10-01 — Shipped the thing.** All of it.\n"
    amended = "- **2026-10-11 — Shipped the thing.** All of it.\n"
    with pytest.raises(RefusalError, match="amended or rebased"):
        ledger_merge(base, _brag_block(amended + _A), _brag_block(pushed + _A), BRAG)


def test_h3_short_bullets_written_side_by_side_are_both_kept() -> None:
    base = _notes("\n- a\n")
    merged, _detail = handoff_merge(base, _notes("\n- a\n- n1\n"), _notes("\n- a\n- o1\n"), HANDOFF)
    assert "- n1" in merged and "- o1" in merged


def test_h3_the_guard_also_covers_the_gap_before_a_replaced_item() -> None:
    base = _notes("\n- a\n- x\n- b\n")
    tip = _notes("\n- a\n- foo bar\n- x2\n- b\n")
    origin = _notes("\n- a\n- foo\n- x\n- b\n")
    with pytest.raises(RefusalError, match="amended or rebased"):
        handoff_merge(base, tip, origin, HANDOFF)


def test_h3_the_guard_also_covers_the_gap_after_a_replaced_item() -> None:
    base = _notes("\n- a\n- x\n- b\n")
    tip = _notes("\n- a\n- x2\n- foo bar\n- b\n")
    origin = _notes("\n- a\n- x\n- foo\n- b\n")
    with pytest.raises(RefusalError, match="amended or rebased"):
        handoff_merge(base, tip, origin, HANDOFF)


def test_h1c_a_move_and_mid_text_edit_pairs_by_ratio_and_refuses() -> None:
    """Neither text opens the other and the first lines differ: only the similarity ratio pairs them."""
    base = _notes("\n- a\n- verify the gate is red today\n- b\n")
    tip = _notes("\n- a\n- b\n- verify the gate is green now\n")
    origin = _notes("\n- a\n- b\n- verify the gate is red today (origin)\n")
    with pytest.raises(RefusalError, match="moved and edited"):
        handoff_merge(base, tip, origin, HANDOFF)


def test_h1_a_dissimilar_new_item_is_not_a_move_of_the_deleted_one() -> None:
    base = _notes("\n- a\n- verify the gate is red today\n- b\n")
    tip = _notes("\n- a\n- b\n- ship the release notes\n")
    origin = _notes("\n- a\n- b\n")
    merged, _detail = handoff_merge(base, tip, origin, HANDOFF)
    assert merged == tip


def test_h1_the_better_match_wins_the_pairing() -> None:
    """Two deleted items, two inserted: each pairs with its own edit, so origin deleting only the
    second still refuses on the second's move+edit and not on a cross pairing."""
    base = _notes("\n- a\n- verify the gate is red today\n- alpha beta gamma delta\n- b\n")
    tip = _notes("\n- a\n- b\n- alpha beta gamma delta (done)\n- verify the gate is red today (done)\n")
    origin = _notes("\n- a\n- verify the gate is red today\n- b\n")
    with pytest.raises(RefusalError, match="alpha beta gamma delta"):
        handoff_merge(base, tip, origin, HANDOFF)


def test_h1_an_identical_move_is_preferred_to_a_merely_similar_new_item() -> None:
    """The session moved ``b`` (origin made the same move) and, elsewhere, wrote a similar new
    item: the move pairs with its identical copy, so it counts as already applied."""
    base = _notes("\n- a\n- x\n- b\n- c\n")
    tip = _notes("\n- a\n- b\n- x\n- c\n- b and more\n")
    origin = _notes("\n- a\n- b\n- x\n- c\n")
    merged, _detail = handoff_merge(base, tip, origin, HANDOFF)
    assert merged == tip


# ---------------------------------------------------------------------------
# Move residue (M1-M3): a moved handoff item the per-section, delete/insert-only
# pairing could not see, raced by the other side. Each fix only adds refusals.
# ---------------------------------------------------------------------------


def _two(notes_body: str, done_body: str) -> str:
    """A handoff with two touched-able sections, ``## Notes`` then ``## Done``."""
    return _hd("## Notes\n" + notes_body + "\n## Done\n" + done_body + _NOTES_TAIL)


def _done_of(merged: str) -> str:
    """The ``## Done`` section's text of a merged ``_two`` handoff."""
    return merged.split("## Done")[1].split("## Mode")[0]


# M1 -- origin moved an item the session deleted: the delete is not "already applied"


def test_m1_origin_moved_and_edited_an_item_the_session_deleted_refuses() -> None:
    """Origin's delete opcode is half of origin's move: matching the session's delete
    against it kept origin's moved copy and dropped the session's delete."""
    base = _notes("\n- A\n- X\n- B\n- C\n")
    tip = _notes("\n- A\n- B\n- C\n")
    origin = _notes("\n- A\n- B\n- C\n- X; CI green\n")
    with pytest.raises(RefusalError, match="in '## Notes', origin moved"):
        handoff_merge(base, tip, origin, HANDOFF)


def test_m1_origin_purely_moved_an_item_the_session_deleted_refuses() -> None:
    base = _notes("\n- A\n- X\n- B\n- C\n")
    tip = _notes("\n- A\n- B\n- C\n")
    origin = _notes("\n- A\n- B\n- C\n- X\n")
    with pytest.raises(RefusalError, match="in '## Notes', origin moved"):
        handoff_merge(base, tip, origin, HANDOFF)


def test_m1_origin_moved_an_item_the_session_deleted_into_another_section_refuses() -> None:
    base = _two("\n- A\n- X\n- B\n", "\n- D\n")
    tip = _two("\n- A\n- B\n", "\n- D\n")
    origin = _two("\n- A\n- B\n", "\n- D\n- X (done)\n")
    with pytest.raises(RefusalError, match="origin moved"):
        handoff_merge(base, tip, origin, HANDOFF)


def test_m1_an_item_both_sides_deleted_is_still_already_applied() -> None:
    """Origin's other new item is not a version of the deleted one: a real delete on both sides."""
    base = _notes("\n- A\n- X\n- B\n- C\n")
    tip = _notes("\n- A\n- B\n- C\n")
    origin = _notes("\n- A\n- B\n- C\n- wholly unrelated news\n")
    merged, _detail = handoff_merge(base, tip, origin, HANDOFF)
    assert merged == origin


# M2 -- a session move+edit into ANOTHER section is an edit of the moved item


def test_m2_a_cross_section_move_and_edit_origin_deleted_refuses() -> None:
    base = _two("\n- A\n- X\n- B\n", "\n- D\n")
    tip = _two("\n- A\n- B\n", "\n- D\n- X (done)\n")
    origin = _two("\n- A\n- B\n", "\n- D\n")
    with pytest.raises(RefusalError, match="moved and edited"):
        handoff_merge(base, tip, origin, HANDOFF)


def test_m2_a_cross_section_move_origin_moved_elsewhere_refuses() -> None:
    """Both sides moved X into ``## Done``, to different gaps with different edits: the merge
    held both versions."""
    base = _two("\n- A\n- X\n- B\n", "\n- D\n- E\n")
    tip = _two("\n- A\n- B\n", "\n- D\n- X (done)\n- E\n")
    origin = _two("\n- A\n- B\n", "\n- D\n- E\n- X (origin)\n")
    with pytest.raises(RefusalError, match="moved and edited"):
        handoff_merge(base, tip, origin, HANDOFF)


def test_m2_a_cross_section_move_origin_left_alone_is_applied() -> None:
    base = _two("\n- A\n- X\n- B\n", "\n- D\n")
    tip = _two("\n- A\n- B\n", "\n- D\n- X (done)\n")
    origin = _two("\n- A\n- X\n- B\n- o\n", "\n- D\n")
    merged, _detail = handoff_merge(base, tip, origin, HANDOFF)
    assert merged == _two("\n- A\n- B\n- o\n", "\n- D\n- X (done)\n")


def test_m2_the_same_cross_section_move_on_both_sides_is_already_applied() -> None:
    base = _two("\n- A\n- X\n- B\n", "\n- D\n")
    both = _two("\n- A\n- B\n", "\n- D\n- X (done)\n")
    merged, _detail = handoff_merge(base, both, both, HANDOFF)
    assert merged == both


# M3 -- a moved item that lands next to a session edit sits in a ``replace`` opcode


def test_m3_a_move_landing_inside_a_replace_origin_deleted_refuses() -> None:
    base = _notes("\n- A\n- X\n- B\n- C\n")
    tip = _notes("\n- A\n- B\n- X (updated)\n- C2\n")
    origin = _notes("\n- A\n- B\n- C\n")
    with pytest.raises(RefusalError, match="in '## Notes', the session moved and edited"):
        handoff_merge(base, tip, origin, HANDOFF)


def test_m3_a_move_landing_inside_a_replace_origin_left_alone_is_applied() -> None:
    base = _notes("\n- A\n- X\n- B\n- C\n")
    tip = _notes("\n- A\n- B\n- X (updated)\n- C2\n")
    origin = _notes("\n- A\n- X\n- B\n- C\n- o\n")
    merged, _detail = handoff_merge(base, tip, origin, HANDOFF)
    assert _items_of(merged) == "\n\n- A\n- B\n- X (updated)\n- C2\n- o\n\n"


def test_m2_the_same_cross_section_move_into_a_different_gap_refuses() -> None:
    """Both sides moved X into ``## Done`` with the same text but at different places: not the
    identical move, and the per-gap dedupe would keep both copies."""
    base = _two("\n- A\n- X\n- B\n", "\n- D\n- E\n")
    tip = _two("\n- A\n- B\n", "\n- D\n- X (done)\n- E\n")
    origin = _two("\n- A\n- B\n", "\n- D\n- E\n- X (done)\n")
    with pytest.raises(RefusalError, match="moved and edited"):
        handoff_merge(base, tip, origin, HANDOFF)


def test_m1_a_section_origin_renamed_alone_is_compared_with_its_base_counterpart() -> None:
    """Origin renamed ``## Done`` (the session left it alone): its items are the base's, not
    new ones, so its old note is not read as origin moving X there."""
    base = _two("\n- A\n- X\n- B\n", "\n- D\n- X note\n")
    tip = _two("\n- A\n- B\n", "\n- D\n- X note\n")
    origin = _two("\n- A\n- B\n", "\n- D\n- X note\n").replace("## Done", "## Closed")
    merged, _detail = handoff_merge(base, tip, origin, HANDOFF)
    assert merged == origin


def test_m3_the_replace_round_never_takes_a_plain_insert_pair() -> None:
    """X's identical move+edit (origin made it too) is a plain insert; a nearer, merely similar
    replacement must not steal the pairing and turn an already-applied move into a refusal."""
    base = _notes("\n- a\n- x: check the gate\n- b\n- c\n- d\n- e\n")
    tip = _notes("\n- a\n- b\n- x: check the gate again\n- d\n- e\n- x: check the gate (done)\n")
    origin = _notes("\n- a\n- b\n- c\n- d\n- e\n- x: check the gate (done)\n")
    merged, _detail = handoff_merge(base, tip, origin, HANDOFF)
    assert merged == tip


def test_m2_a_cross_section_move_origin_made_into_the_same_gap_with_other_text_refuses() -> None:
    """Same destination and gap, different edits: not the identical move, and the two texts are
    too far apart for the amend guard, so the merge held both versions."""
    base = _two("\n- A\n- X\n- B\n", "\n- D\n")
    tip = _two("\n- A\n- B\n", "\n- D\n- X (done, session)\n")
    origin = _two("\n- A\n- B\n", "\n- D\n- X (done, origin)\n")
    with pytest.raises(RefusalError, match="moved and edited"):
        handoff_merge(base, tip, origin, HANDOFF)


def test_m3_an_in_place_edit_of_an_item_alike_a_deleted_one_is_not_a_move() -> None:
    """Both sides deleted X; the session also edited C in place, and C (a bullet about the same
    project) reads as a version of X. The replacement is C's edit, not X moved: no refusal."""
    base = _notes(
        "\n- A\n- [[proj-a]]: watch the deploy on staging\n- B\n- [[proj-a]]: watch the deploy on prod\n"
    )
    tip = _notes("\n- A\n- B\n- [[proj-a]]: watch the deploy on prod (green)\n")
    origin = _notes("\n- A\n- B\n- [[proj-a]]: watch the deploy on prod\n")
    merged, _detail = handoff_merge(base, tip, origin, HANDOFF)
    assert merged == tip


def test_m2_an_in_place_edit_in_another_section_is_not_a_cross_section_move() -> None:
    """Fuzz-found: the session deleted a ``## Notes`` bullet origin also deleted, and edited a
    look-alike bullet of the same project in ``## Done`` in place."""
    base = _two(
        "\n- A\n- **[[skywatch]] (2026-10-10, two sessions):** bls landed\n- B\n",
        "\n- D\n- **[[skywatch]] (2026-10-10, new today):** page landed\n",
    )
    tip = _two("\n- A\n- B\n", "\n- D\n- ~~**[[skywatch]] (2026-10-10, new today):** page landed~~ done\n")
    origin = _two("\n- A\n- B\n", "\n- D\n- **[[skywatch]] (2026-10-10, new today):** page landed\n")
    merged, _detail = handoff_merge(base, tip, origin, HANDOFF)
    assert merged == tip
