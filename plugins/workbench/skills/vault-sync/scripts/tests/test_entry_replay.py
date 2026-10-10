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
    tip = insert_under(base, "### Wins", brag_entry("2026-09-20", "Session win"))
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
    bad = tmp_path / "scratch" / "Ledger.md"
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
    ledger = tmp_path / "Ledger.md"
    ledger.write_text(GOTCHAS_SEED, encoding="utf-8")
    result = _lint(tmp_path, "--json", str(ledger), str(tmp_path / "missing.md"))
    assert result.returncode == 0, result.stdout
    assert json.loads(result.stdout)["ok"] is True


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
