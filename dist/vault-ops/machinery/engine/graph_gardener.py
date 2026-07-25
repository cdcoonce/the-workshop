#!/usr/bin/env python3
"""Graph Gardener — debounced session-end graph-maintenance pass.

Rides the Stop hook (called after notebook-update.py).  Operates on the
notes touched this session only (never a full-vault sweep):

    Lane A — deterministic broken-link auto-repair (NO LLM).
        Parse [[X]] links; resolve them against existing note titles using
        case/whitespace/punctuation normalization equality ONLY.  Auto-repair
        only when display_norm exactly equals one catalog key AND that key maps
        to exactly one note.  Substring/containment matches become "did you
        mean?" hints in proposals — never auto-repairs.

    Lane B — headless cheap-model propose pass.
        Over the same touched notes, ask claude-haiku to suggest new links,
        flag orphans (>300 chars, no [[link]]), and note index drift.
        Follows the notebook-distill.py headless pattern exactly.

Output: ``.brain/gardener-<context>.md`` (gitignored) with an Applied
section (auto-repairs) and a Proposed section (Lane A proposals + Lane B
suggestions).

Fail-soft: ANY error → log to stderr, exit 0.  Never block the Stop hook.

Hook dispatch model (mirrors notebook-update.py):
    main_hook() returns in milliseconds — it records the session as gardened,
    then spawns this same script in --worker mode detached.  The worker runs
    Lane A + Lane B synchronously without touching debounce state.

Usage as Stop hook:
    bash "${CLAUDE_PROJECT_DIR:-.}"/.claude/scripts/run-hook.sh graph_gardener.py

Dry-run / standalone testing:
    python graph_gardener.py --dry-run
    python graph_gardener.py --dry-run --notes path/to/a.md path/to/b.md
    python graph_gardener.py --dry-run --skip-lane-b  (Lane A only, fast)
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from vault_utils import find_vault_root_from_env, read_vault_context, WIKILINK_CAPTURE_RE  # noqa: E402
from vault_scope import (  # noqa: E402
    GRAPH_EXCLUDED_DIRS,
    GRAPH_NOTE_DIRS,
    is_graph_excluded,
    is_graph_markdown_note,
    iter_graph_markdown_notes,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LANE_B_MODEL = "claude-haiku-4-5"
LANE_B_TIMEOUT = 90          # seconds for the headless claude call
RACE_SAFETY_SECS = 120       # skip notes modified in the last N seconds
SWEEP_BATCH = 8              # old backlog notes gardened per run (trickle sweep)
BROKEN_BATCH = 8             # notes with known broken links gardened per run (targeted)
BROKEN_SCAN_TIMEOUT = 30     # seconds; the graphmark scan is ~0.2s, this is a hang guard
MAX_NOTES_LANE_B = 20        # cap: don't send 200 notes in one prompt

ORPHAN_MIN_CHARS = 300       # notes this long with no [[link]] → orphan flag

SCOPED_DIRS = GRAPH_NOTE_DIRS
EXCLUDE_DIRS = GRAPH_EXCLUDED_DIRS

STATE_FILE_REL = Path(".claude") / "data" / "gardener-state.json"
GARDENER_LOG_REL = Path(".claude") / "data" / "gardener.log"
DISMISSED_FILE_REL = Path(".claude") / "data" / "gardener-dismissed.json"

# /garden holds this lock while applying; producer workers bail while it's fresh.
APPLY_LOCK_REL = Path(".brain") / ".garden-lock"
APPLY_LOCK_TTL_SECONDS = 1800  # 30 min — bounds how long an abandoned lock blocks

# The session-start /garden nudge goes loud past either threshold.
STALE_GARDEN_DAYS = 7         # days since last /garden apply
QUEUE_LOUD_THRESHOLD = 10     # pending proposal count

# Wikilink capture pattern is shared from vault_utils (single canonical regex) — see WIKILINK_CAPTURE_RE.


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def log(vault_root: Path, msg: str) -> None:
    """Append a timestamped line to the gardener log (best-effort)."""
    try:
        log_path = vault_root / GARDENER_LOG_REL
        log_path.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(f"[{stamp}] {msg}\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Vault context
# ---------------------------------------------------------------------------

def read_context(vault_root: Path) -> str:
    """Return 'work'|'personal' from .vault-context (canonical reader; 'unknown' if absent)."""
    return read_vault_context(vault_root)


# ---------------------------------------------------------------------------
# Debounce / state
# ---------------------------------------------------------------------------

def load_state(vault_root: Path) -> dict:
    """Load gardener state, returning empty dict on any parse failure."""
    path = vault_root / STATE_FILE_REL
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(vault_root: Path, state: dict) -> None:
    """Persist gardener state (best-effort)."""
    try:
        path = vault_root / STATE_FILE_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception:
        pass


def already_ran(state: dict, session_id: str) -> bool:
    """True if this session was already gardened."""
    return session_id in state.get("gardened_session_ids", [])


def record_run(state: dict, session_id: str) -> dict:
    """Return updated state recording this session and timestamp."""
    ids: list[str] = state.get("gardened_session_ids", [])
    if session_id not in ids:
        ids.append(session_id)
    # Keep at most the last 50 session IDs to bound file size.
    ids = ids[-50:]
    return {
        **state,
        "last_run_ts": datetime.now().isoformat(),
        "gardened_session_ids": ids,
    }


# ---------------------------------------------------------------------------
# Apply-lock — /garden holds it so detached workers don't clobber the queue
# ---------------------------------------------------------------------------

def apply_lock_active(vault_root: Path) -> bool:
    """True if a fresh /garden apply-lock is held.

    A lock older than APPLY_LOCK_TTL_SECONDS (or unparseable) is stale: it is
    removed (best-effort) and treated as absent, so an abandoned lock self-heals.
    Fail-soft: any error returns False — never block the producer.
    """
    path = vault_root / APPLY_LOCK_REL
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        started = datetime.fromisoformat(data["started"])
        if (datetime.now() - started).total_seconds() < APPLY_LOCK_TTL_SECONDS:
            return True
    except Exception:
        pass
    # Stale or malformed → self-heal and report absent.
    try:
        path.unlink()
    except OSError:
        pass
    return False


def acquire_apply_lock(vault_root: Path, session_id: str) -> None:
    """Write the /garden apply-lock (best-effort), overwriting any stale lock."""
    try:
        path = vault_root / APPLY_LOCK_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"started": datetime.now().isoformat(), "session": session_id}),
            encoding="utf-8",
        )
    except Exception:
        pass


def release_apply_lock(vault_root: Path) -> None:
    """Remove the /garden apply-lock (best-effort; safe when absent)."""
    try:
        (vault_root / APPLY_LOCK_REL).unlink()
    except OSError:
        pass


def mark_applied(vault_root: Path) -> None:
    """Record that a /garden pass just ran (stamps last_applied_ts in state).

    Drives the staleness escalation in queue_summary. Best-effort.
    """
    try:
        state = load_state(vault_root)
        state["last_applied_ts"] = datetime.now().isoformat()
        save_state(vault_root, state)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Scope detection — which notes to operate on
# ---------------------------------------------------------------------------

def _is_excluded(path: Path, vault_root: Path) -> bool:
    """True if this path falls under an excluded directory."""
    return is_graph_excluded(path, vault_root)


def _is_in_scope(path: Path, vault_root: Path) -> bool:
    """True if this path is under a scoped dir and not excluded."""
    return is_graph_markdown_note(path, vault_root)




def head_commit(vault_root: Path) -> str | None:
    """Current HEAD sha, or None on failure."""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=vault_root, capture_output=True, text=True, timeout=15,
        )
        return r.stdout.strip() or None
    except Exception:
        return None


def commit_range_changed_notes(vault_root: Path, since_commit: str | None) -> list[Path]:
    """.md notes changed in since_commit..HEAD. Empty if since_commit falsy/invalid."""
    if not since_commit:
        return []
    try:
        r = subprocess.run(
            ["git", "diff", "--name-only", f"{since_commit}..HEAD"],
            cwd=vault_root, capture_output=True, text=True, timeout=15,
        )
        if r.returncode != 0:
            return []
        return [
            vault_root / line.strip()
            for line in r.stdout.splitlines()
            if line.strip().endswith(".md")
        ]
    except Exception:
        return []


STALE_DAYS = 14


def detect_stranded_branches(
    vault_root: Path, stale_days: int = STALE_DAYS, base: str = "main"
) -> list[dict]:
    """Branches holding net-new notes absent from ``base`` — the irreversible-loss case.

    A branch is *stranded* when its tip is older than ``stale_days`` AND it adds one or
    more ``.md`` notes that do not exist on ``base`` (edits to existing notes don't count —
    those go stale, only added files strand). Excludes ``base``, the current branch, and
    ``backup/*`` snapshots. Scans local heads and remote-tracking refs.

    Returns ``[{"branch": <short name>, "files": [<rel path>, ...]}, ...]``, or ``[]`` on
    any git error (non-repo, missing base, etc.) — fail-soft, never raises.
    """
    try:
        cutoff = datetime.now().timestamp() - stale_days * 86400

        cur = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=vault_root, capture_output=True, text=True, timeout=15,
        )
        if cur.returncode != 0:
            return []
        current_branch = cur.stdout.strip()

        ref = subprocess.run(
            ["git", "for-each-ref",
             "--format=%(refname:short)\t%(committerdate:unix)",
             "refs/heads/", "refs/remotes/"],
            cwd=vault_root, capture_output=True, text=True, timeout=15,
        )
        if ref.returncode != 0:
            return []

        results: list[dict] = []
        seen: set[str] = set()
        for line in ref.stdout.splitlines():
            if "\t" not in line:
                continue
            name, ts = line.rsplit("\t", 1)
            name = name.strip()
            short = name[len("origin/"):] if name.startswith("origin/") else name
            if short in (base, "HEAD", current_branch) or short.startswith("backup/"):
                continue
            if short in seen:
                continue
            try:
                if float(ts) > cutoff:  # fresh / active WIP — not yet stranded
                    continue
            except ValueError:
                continue

            diff = subprocess.run(
                ["git", "diff", "--name-status", "--diff-filter=A", f"{base}...{name}"],
                cwd=vault_root, capture_output=True, text=True, timeout=15,
            )
            if diff.returncode != 0:
                continue
            files: list[str] = []
            for dl in diff.stdout.splitlines():
                parts = dl.split("\t")
                if len(parts) < 2:
                    continue
                path = parts[1].strip()
                if not path.endswith(".md"):
                    continue
                if path.split("/", 1)[0] in ("templates", ".obsidian", ".claude"):
                    continue
                files.append(path)
            if files:
                seen.add(short)
                results.append({"branch": short, "files": files})
        return results
    except Exception:
        return []


def detect_auto_memory_drift(vault_root: Path, _mem_base: Path | None = None) -> dict:
    """Durable facts that live ONLY in machine-local auto-memory, keyed for matching.

    Auto-memory lives at ``<_mem_base>/<slug>/memory/`` where
    ``slug = str(vault_root).replace("/", "-")`` (the Claude Code project encoding).
    Returns ``{_normalize(stem): filename}`` for every ``*.md`` there except the
    ``MEMORY.md`` index — so a broken wikilink whose normalized target matches a key is
    *drift* (a durable fact trapped outside the vault), not a generic missing note.

    Fail-soft: ``{}`` if auto-memory is absent (fresh machine — self-sufficiency holds)
    or on any error. ``_mem_base`` is injectable for tests.
    """
    try:
        mem_base = _mem_base if _mem_base is not None else (Path.home() / ".claude" / "projects")
        slug = str(vault_root).replace("/", "-")
        mem_dir = Path(mem_base) / slug / "memory"
        if not mem_dir.is_dir():
            return {}
        drift: dict[str, str] = {}
        for p in mem_dir.glob("*.md"):
            if p.name == "MEMORY.md":
                continue
            drift[_normalize(p.stem)] = p.name
        return drift
    except Exception:
        return {}


def detect_unprofiled_people(vault_root: Path) -> list[str]:
    """Names wikilinked in ``org/People & Context.md`` lacking an ``org/people/<Name>.md`` profile.

    A distinct category from generic broken links: an indexed person without a profile note is a
    people-profiler candidate, not a "create or remove the link" decision. Matching uses ``_normalize``
    so it agrees with the link catalog. Fail-soft: ``[]`` if the index is missing or on any error.
    """
    try:
        text = (vault_root / "org" / "People & Context.md").read_text(encoding="utf-8")
    except OSError:
        return []
    # Resolve against the full catalog, not just org/people/: a name that resolves to ANY existing
    # note is either already profiled or simply not a person (e.g. [[North Star]] → brain/), so it's
    # not an unprofiled person. (org/people/ is under the scoped org/ dir, so profiles are included.)
    catalog = build_note_catalog(vault_root)
    seen: set[str] = set()
    out: list[str] = []
    for m in WIKILINK_CAPTURE_RE.finditer(text):
        name = m.group(1).split("|")[0].split("#")[0].strip()
        norm = _normalize(name)
        if not norm or norm in catalog or norm in seen:
            continue
        seen.add(norm)
        out.append(name)
    return sorted(out)


def content_hash(path: Path) -> str:
    """sha1 hexdigest of file bytes; '' on read error."""
    try:
        return hashlib.sha1(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def all_in_scope_notes(vault_root: Path) -> list[str]:
    """Sorted vault-relative paths of all in-scope .md notes."""
    return [str(p.relative_to(vault_root)) for p in iter_graph_markdown_notes(vault_root)]


def settled_notes(
    candidates: list[Path],
    vault_root: Path,
    race_secs: int = RACE_SAFETY_SECS,
) -> list[Path]:
    """Filter out notes that don't exist or were modified very recently (race-safe)."""
    now = datetime.now().timestamp()
    out: list[Path] = []
    for p in candidates:
        if not p.exists():
            continue
        try:
            age = now - p.stat().st_mtime
            if age < race_secs:
                continue  # too fresh — skip for this pass
        except OSError:
            continue
        if _is_in_scope(p, vault_root):
            out.append(p)
    return out


def select_backlog_batch(
    sorted_rel: list[str],
    cursor: str | None,
    batch_size: int,
) -> tuple[list[str], str | None]:
    """Return up to batch_size rel-paths strictly after `cursor` in sorted order,
    wrapping around the end exactly once.  Returns (batch, new_cursor) where
    new_cursor is the last path selected (or the old cursor if nothing was)."""
    if not sorted_rel or batch_size <= 0:
        return [], cursor
    n = len(sorted_rel)
    if cursor is None:
        start = 0
    else:
        start = bisect.bisect_right(sorted_rel, cursor)
        if start >= n:
            start = 0
    batch: list[str] = []
    i = start
    for _ in range(min(batch_size, n)):
        batch.append(sorted_rel[i])
        i = (i + 1) % n
    return batch, (batch[-1] if batch else cursor)


def filter_unchanged(
    candidates: list[tuple[str, str]],
    gardened: dict[str, str],
) -> list[str]:
    """Return rel-paths whose current hash differs from the last gardened hash
    (never-gardened notes always qualify).  Preserves input order."""
    return [rel for rel, cur in candidates if gardened.get(rel) != cur]


def broken_links_by_note(vault_root: Path) -> dict[str, set[str]] | None:
    """rel_path → the set of raw link displays graphmark reports as broken.

    ``None`` means the scan was unavailable, which callers treat as "fall back to the
    older self-contained logic" rather than "nothing is broken" — the distinction
    matters, since an empty dict would silence every proposal.
    """
    raw = _graphmark_unresolved(vault_root)
    if raw is None:
        return None
    return {
        note: {d for d in displays if isinstance(d, str)}
        for note, displays in raw.items()
        if isinstance(displays, list)
    }


def notes_with_broken_links(vault_root: Path) -> list[str]:
    """Rel-paths of notes graphmark reports as containing broken wikilinks, sorted.

    Delegates to ``graph_cli.py --unresolved`` — the vault's graphmark seam — rather than
    re-deriving brokenness here, so the answer honors graphmark's resolution rules
    (same-note ``[[#anchor]]`` links, non-markdown targets like ``.base``, and a trailing
    ``.md``) instead of this file's older approximations.

    Fail-soft by design: this runs inside a session hook, so any failure (missing uv,
    resolver error, malformed output) returns ``[]`` and the gardener proceeds with its
    ordinary round-robin sweep.
    """
    raw = _graphmark_unresolved(vault_root)
    return sorted(raw) if raw else []


def _graphmark_unresolved(vault_root: Path) -> dict | None:
    """Raw ``graph_cli.py --unresolved`` payload, or ``None`` if the scan failed.

    One code path for both consumers, so the targeted sweep and Lane A can never
    disagree about what is broken.
    """
    script = vault_root / ".claude" / "scripts" / "graph_cli.py"
    if not script.exists():
        return None
    try:
        proc = subprocess.run(
            ["uv", "run", str(script), "--vault-root", str(vault_root), "--unresolved"],
            capture_output=True,
            text=True,
            timeout=BROKEN_SCAN_TIMEOUT,
            cwd=str(vault_root),
        )
        if proc.returncode != 0:
            return None
        data = json.loads(proc.stdout or "{}")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def collect_touched_notes(
    vault_root: Path,
    state: dict,
    override: list[Path] | None = None,
) -> tuple[list[Path], str | None]:
    """Return (settled, change-deduped in-scope notes to garden, new sweep cursor).

    Source 1 (recency): notes committed since state['last_gardened_commit'].
    Source 2 (backlog trickle): up to SWEEP_BATCH old notes after the sweep cursor.
    Source 3 (targeted): up to BROKEN_BATCH notes graphmark says have broken links.

    Sources 2 and 3 are complementary on purpose. The round-robin trickle gives every
    lane (index drift, orphans, people profiles) eventual vault-wide coverage, so it must
    not be narrowed; the targeted source just stops Lane A from waiting for the cursor to
    reach the ~15% of notes that actually have a broken link.

    All sources are settle-filtered and de-duplicated against the gardened-hash map, so a
    note never re-proposes until its content changes — which is also what drains the
    targeted source, no separate cursor required.
    """
    if override is not None:
        notes = [p for p in override if p.exists() and _is_in_scope(p, vault_root)]
        return notes, state.get("sweep_cursor")

    gardened: dict[str, str] = state.get("gardened", {})

    # Source 1 — recency (committed since last run)
    recency = commit_range_changed_notes(vault_root, state.get("last_gardened_commit"))

    # Source 2 — backlog trickle
    batch_rel, new_cursor = select_backlog_batch(
        all_in_scope_notes(vault_root), state.get("sweep_cursor"), SWEEP_BATCH
    )
    backlog = [vault_root / r for r in batch_rel]

    # Source 3 — targeted: notes that actually have broken links right now.
    targeted = [vault_root / r for r in notes_with_broken_links(vault_root)[:BROKEN_BATCH]]

    # Merge + settle
    merged = settled_notes(recency + backlog + targeted, vault_root)

    # De-duplicate by resolved path
    seen: set[Path] = set()
    unique: list[Path] = []
    for p in merged:
        rp = p.resolve()
        if rp not in seen:
            seen.add(rp)
            unique.append(p)

    # Drop notes unchanged since last gardened — EXCEPT the targeted ones.
    #
    # The unchanged filter is a cost control: don't re-scan a note whose content has not
    # moved. That is right for the trickle, but it silently neutralizes the targeted
    # source, because a note whose link broke long ago has been gardened once and will
    # never change again on its own. Measured on the source vault: only 6 of the 80 notes
    # holding a live broken link survived the filter, so 75 were suppressed permanently —
    # which is why link rot persisted despite the gardener "already reporting it".
    #
    # A currently-broken link is a verified, persistent defect rather than a stale
    # suggestion, and re-checking it costs nothing (graphmark already told us). Proposal
    # noise stays bounded by BROKEN_BATCH and by the gsig dismissal list, which is the
    # channel actually meant for "stop telling me about this one".
    targeted_rel = {str(p.relative_to(vault_root)) for p in targeted}
    cand = [(str(p.relative_to(vault_root)), content_hash(p)) for p in unique]
    keep = set(filter_unchanged(cand, gardened))
    final = [
        p
        for p in unique
        if str(p.relative_to(vault_root)) in keep
        or str(p.relative_to(vault_root)) in targeted_rel
    ]

    return final, new_cursor


# ---------------------------------------------------------------------------
# Note catalog — existing note titles/paths for link resolution
# ---------------------------------------------------------------------------

def build_note_catalog(vault_root: Path) -> dict[str, list[Path]]:
    """Return a mapping of normalized-title → list[Path] for all in-scope notes.

    Multiple notes may normalize to the same key (e.g. case-only differences).
    Preserving all paths makes normalization collisions visible to Lane A so it
    can treat them as ambiguous rather than silently overwriting one with another.

    Used by Lane A to resolve [[X]] targets.
    """
    catalog: dict[str, list[Path]] = {}
    for p in iter_graph_markdown_notes(vault_root):
        key = _normalize(p.stem)
        catalog.setdefault(key, []).append(p)
    return catalog


def _normalize(text: str) -> str:
    """Normalize a title for fuzzy-matching: lowercase, collapse whitespace/punctuation."""
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)  # punctuation → space
    text = re.sub(r"\s+", " ", text).strip()
    return text


def note_in_index(note_rel: str, index_rel: str, vault_root: Path) -> bool:
    """True if the index file already wikilinks the note (by normalized basename).

    Used to drop index-drift false positives: Lane B may flag a note as "missing
    from an index" when it is in fact already linked there. Matches by the note's
    normalized stem against each index wikilink's basename (alias/heading/path
    stripped). Fail-soft: a missing or unreadable index → False.
    """
    try:
        text = (vault_root / index_rel).read_text(encoding="utf-8")
    except OSError:
        return False
    target_stem = _normalize(Path(note_rel).stem)
    for m in WIKILINK_CAPTURE_RE.finditer(text):
        link = m.group(1).split("|")[0].split("#")[0].strip()
        base = link.split("/")[-1]
        if _normalize(base) == target_stem:
            return True
    return False


def _code_spans(text: str) -> list[tuple[int, int]]:
    """Char ranges covered by Markdown code — fenced blocks and inline spans.

    Wikilinks inside these are documentation/examples, not real links: the
    resolver skips any match that starts inside a returned range. Fenced blocks
    are delimited by lines starting with ``` or ~~~ (the fence lines included);
    inline spans are backtick runs (`` `x` ``, `` ``x`` ``).
    """
    spans: list[tuple[int, int]] = []
    pos = 0
    in_fence = False
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        is_fence = stripped.startswith("```") or stripped.startswith("~~~")
        if in_fence:
            spans.append((pos, pos + len(line)))
            if is_fence:
                in_fence = False
        elif is_fence:
            in_fence = True
            spans.append((pos, pos + len(line)))
        else:
            for m in re.finditer(r"`+[^`]*`+", line):
                spans.append((pos + m.start(), pos + m.end()))
        pos += len(line)
    return spans


def _excluded_note_stems(vault_root: Path) -> set[str]:
    """Normalized stems of ``*.md`` files that exist but are OUT of graph scope.

    A link to one of these (e.g. a build-asset under ``templates/``, a root doc, a ``.claude/`` file)
    can never resolve in-graph — but it's not a real broken link, it points at an intentionally
    graph-excluded note. The resolver suppresses these instead of flagging them. Fail-soft: ``set()``.
    """
    out: set[str] = set()
    try:
        for p in vault_root.rglob("*.md"):
            if ".git" in p.parts:
                continue
            if not _is_in_scope(p, vault_root):
                out.add(_normalize(p.stem))
    except OSError:
        pass
    return out


# ---------------------------------------------------------------------------
# Dismissal suppression — stable signatures + suppress-list
# ---------------------------------------------------------------------------

def proposal_signature(kind: str, note_rel: str, key: str = "") -> str:
    """Return a stable, deterministic signature for a proposal.

    Rationale text is NEVER included — it can vary run-to-run (LLM output).

    Formats:
      broken-link  → ``broken|<note_rel>|<normalized_target>``
                     key = the broken target display text
      missing-link → ``missing|<note_rel>|<normalized_prose>-><normalized_target>``
                     key = "<prose>-><target>" (target may include [[ ]]; stripped here)
      orphan       → ``orphan|<note_rel>``
                     key unused
      index-drift  → ``drift|<note_rel>|<index_file>``
                     key = the index file name/path (not normalized)
    """
    if kind == "broken":
        return f"broken|{note_rel}|{_normalize(key)}"
    if kind == "missing":
        # key is expected to be "<prose>-><target>" where target may be [[Target]]
        if "->" in key:
            prose_part, target_part = key.split("->", 1)
        else:
            prose_part, target_part = key, ""
        # Strip surrounding [[ ]] from the target before normalizing
        target_part = target_part.strip()
        if target_part.startswith("[[") and target_part.endswith("]]"):
            target_part = target_part[2:-2]
        return f"missing|{note_rel}|{_normalize(prose_part)}->{_normalize(target_part)}"
    if kind == "orphan":
        return f"orphan|{note_rel}"
    if kind == "drift":
        return f"drift|{note_rel}|{key}"
    if kind == "branch":
        # key = branch short name (slashes preserved); the branch IS the unit of decision
        return f"branch|{key}"
    if kind == "memdrift":
        # key = auto-memory slug; normalize so it matches the broken-link target
        return f"memdrift|{_normalize(key)}"
    if kind == "person":
        # key = the person's name; per-person (not per-link) so one dismissal sticks
        return f"unprofiled|{_normalize(key)}"
    # Fallback: unknown kind — include key as-is
    return f"{kind}|{note_rel}|{key}"


def load_dismissed(vault_root: Path) -> set[str]:
    """Load the dismissed-signature set from the suppress-list file.

    Returns an empty set on any error (missing file, bad JSON, wrong shape).
    Fail-soft — must never raise.
    """
    try:
        path = vault_root / DISMISSED_FILE_REL
        if not path.exists():
            return set()
        data = json.loads(path.read_text(encoding="utf-8"))
        dismissed = data.get("dismissed", [])
        if not isinstance(dismissed, list):
            return set()
        return set(str(s) for s in dismissed)
    except Exception:
        return set()


# ---------------------------------------------------------------------------
# Lane A — deterministic broken-link repair
# ---------------------------------------------------------------------------

class LaneAResult:
    """Accumulator for Lane A repairs and proposals."""

    def __init__(self) -> None:
        self.applied: list[str] = []   # "auto-fixed [[X]] → [[Y]] in note"
        self.proposals: list[str] = [] # "could not resolve [[X]] in note: candidates=[...]"

    def any(self) -> bool:
        return bool(self.applied or self.proposals)


def run_lane_a(
    notes: list[Path],
    vault_root: Path,
    dry_run: bool = False,
    dismissed: set[str] = frozenset(),
    broken_by_note: dict[str, set[str]] | None = None,
) -> LaneAResult:
    """Parse [[links]] in each note; repair exactly-one-match broken links.

    Args:
        notes: The settled notes to inspect.
        vault_root: Vault root (for relative path display).
        dry_run: If True, log repairs but do NOT write the file.
        dismissed: Set of proposal signatures to suppress (from suppress-list).
        broken_by_note: rel_path → the raw link displays graphmark reports as broken.
            When supplied, graphmark is the authority on brokenness and a display it
            does NOT list is never proposed — it either resolves or is out of scope
            (``[[Chart.base]]``, ``[[#Heading]]``, a trailing ``.md``). Cosmetic
            auto-repair is unaffected: it fires on links that already resolve but whose
            display text differs from the note's title, which is not a brokenness
            question. ``None`` (a failed or skipped scan) keeps the previous
            self-contained behavior.

    Returns:
        LaneAResult with applied repairs and unresolved proposals.
    """
    catalog = build_note_catalog(vault_root)
    excluded_stems = _excluded_note_stems(vault_root)
    result = LaneAResult()

    for note_path in notes:
        try:
            original = note_path.read_text(encoding="utf-8")
        except OSError:
            continue

        try:
            rel = note_path.relative_to(vault_root)
        except ValueError:
            rel = note_path

        changed = False
        content = original
        code_spans = _code_spans(original)

        for match in WIKILINK_CAPTURE_RE.finditer(original):
            # Skip [[links]] inside code spans / fenced blocks — documentation, not links.
            if any(s <= match.start() < e for s, e in code_spans):
                continue
            raw_target = match.group(1)
            # Skip within-note anchor links: [[#Section Name]] — always valid.
            if raw_target.lstrip().startswith("#"):
                continue
            # Strip pipe aliases: [[Note Title|alias]] → "Note Title"
            # Also strip heading anchors from cross-note links: [[Note#Section]] → "Note"
            display = raw_target.split("|")[0].split("#")[0].strip()

            # graphmark owns the definition of "broken". When its scan is available, a
            # display it does not report is resolvable or deliberately out of scope, so
            # it must never become a proposal — that is what stopped Lane A telling us to
            # "create or remove" working [[Chart.base]] links. Auto-repair below is not
            # gated: it acts on links that already resolve.
            graphmark_says_fine = (
                broken_by_note is not None
                and raw_target not in broken_by_note.get(str(rel), set())
            )

            # Path-qualified link ([[folder/note]]): resolve by matching the link's
            # path against note paths using unique-suffix semantics (like Obsidian).
            # The title match below is path-blind, so these MUST be handled first.
            if "/" in display:
                link_segs = [_normalize(s) for s in display.split("/") if s.strip()]
                base_key = link_segs[-1] if link_segs else ""
                matches = [
                    p
                    for p in catalog.get(base_key, [])
                    if [_normalize(s) for s in p.relative_to(vault_root).with_suffix("").parts][
                        -len(link_segs):
                    ]
                    == link_segs
                ]
                if len(matches) == 1:
                    continue  # resolved — valid path-qualified link, no action
                if not matches and base_key in excluded_stems:
                    continue  # points at a graph-excluded note (templates/ etc.) — suppress
                sig = proposal_signature("broken", str(rel), display)
                if sig not in dismissed and not graphmark_says_fine:
                    if len(matches) >= 2:
                        result.proposals.append(
                            f"`{rel}`: broken `[[{display}]]` — ambiguous path "
                            f"({len(matches)} notes match suffix): "
                            + ", ".join(f"`{p.relative_to(vault_root)}`" for p in matches[:5])
                            + (" …" if len(matches) > 5 else "")
                            + f" <!-- gsig: {sig} -->"
                        )
                    else:
                        result.proposals.append(
                            f"`{rel}`: broken `[[{display}]]` — no matching note "
                            f"(consider creating or removing)"
                            + f" <!-- gsig: {sig} -->"
                        )
                continue

            display_norm = _normalize(display)

            # 1. Exact normalized match?
            #    display_norm must equal a catalog key AND that key maps to
            #    exactly one note.  This is the ONLY condition that allows
            #    auto-repair — pure case/whitespace/punctuation normalization.
            if display_norm in catalog:
                paths_for_key = catalog[display_norm]
                if len(paths_for_key) == 1:
                    # Unambiguous exact match — no repair needed if the display
                    # text already equals the stem (link is valid as-is).
                    # Only repair when the raw display differs from the stem.
                    target_path = paths_for_key[0]
                    correct_title = target_path.stem
                    # `_normalize(correct_title) == display_norm` is always true here
                    # (target_path came out of catalog[display_norm]), so the only
                    # meaningful check is whether the raw display already equals the stem.
                    if display == correct_title:
                        continue  # link is valid — skip
                    # display normalizes to the same key but differs in
                    # case/whitespace/punctuation — safe to rewrite.
                    old_link = match.group(0)
                    if "|" in raw_target:
                        alias = raw_target.split("|", 1)[1]
                        new_link = f"[[{correct_title}|{alias}]]"
                    else:
                        # Preserve the original display only when the repair would
                        # degrade human-readable text (spaces) into a kebab slug.
                        # Case fixes and slug→readable repairs snap to the clean title.
                        degrades = (
                            " " in display
                            and "-" in correct_title
                            and " " not in correct_title
                        )
                        if degrades:
                            new_link = f"[[{correct_title}|{display}]]"
                        else:
                            new_link = f"[[{correct_title}]]"
                    content = content.replace(old_link, new_link, 1)
                    changed = True
                    msg = (
                        f"auto-fixed `{old_link}` → `{new_link}` "
                        f"in `{rel}`"
                    )
                    result.applied.append(msg)
                    log(vault_root, msg)
                else:
                    # Key maps to 2+ notes — normalization collision, ambiguous.
                    collision_names = [p.stem for p in paths_for_key]
                    sig = proposal_signature("broken", str(rel), display)
                    if sig not in dismissed and not graphmark_says_fine:
                        result.proposals.append(
                            f"`{rel}`: broken `[[{display}]]` — ambiguous "
                            f"({len(paths_for_key)} notes share normalized key): "
                            + ", ".join(f"`{n}`" for n in collision_names[:5])
                            + (" …" if len(collision_names) > 5 else "")
                            + f" <!-- gsig: {sig} -->"
                        )
                continue  # handled above — don't fall through to hint search

            # Suppress links to intentionally graph-excluded notes (templates/, root docs, .claude/…).
            if display_norm in excluded_stems:
                continue

            # 2. No exact normalized match — search for substring hints only.
            #    These NEVER trigger auto-repair; they only enrich the proposal.
            hints = [
                p.stem
                for norm_key, paths in catalog.items()
                for p in paths
                if display_norm and (
                    display_norm in norm_key or norm_key in display_norm
                )
            ]

            if hints:
                hint_str = ", ".join(f"`{h}`" for h in hints[:5])
                hint_str += " …" if len(hints) > 5 else ""
                sig = proposal_signature("broken", str(rel), display)
                if sig not in dismissed and not graphmark_says_fine:
                    result.proposals.append(
                        f"`{rel}`: broken `[[{display}]]` — no exact match; "
                        f"did you mean {hint_str}?"
                        + f" <!-- gsig: {sig} -->"
                    )
            else:
                sig = proposal_signature("broken", str(rel), display)
                if sig not in dismissed and not graphmark_says_fine:
                    result.proposals.append(
                        f"`{rel}`: broken `[[{display}]]` — no matching note "
                        f"(consider creating or removing)"
                        + f" <!-- gsig: {sig} -->"
                    )

        if changed and not dry_run:
            try:
                note_path.write_text(content, encoding="utf-8")
            except OSError as exc:
                # Roll back the in-memory change and move the entry to proposals
                result.applied = [
                    a for a in result.applied if f"in `{rel}`" not in a
                ]
                result.proposals.append(
                    f"`{rel}`: repair attempted but write failed: {exc}"
                )

    return result


# ---------------------------------------------------------------------------
# Lane B — headless cheap-model propose pass (follows notebook-distill.py)
# ---------------------------------------------------------------------------

def build_lane_b_prompt(notes_content: list[tuple[str, str]]) -> str:
    """Build the prompt for the headless cross-linker pass.

    Args:
        notes_content: List of (rel_path, content) tuples.
    """
    notes_block = ""
    for rel, content in notes_content:
        # Cap per note to avoid blowing the prompt budget
        snippet = content[:2000]
        if len(content) > 2000:
            snippet += "\n…[truncated]"
        notes_block += f"\n\n### {rel}\n{snippet}"

    return f"""\
You are a vault graph reviewer. Review these recently-changed notes and suggest:

1. MISSING LINKS — prose that names a person, project, concept, or note title that
   should be a [[wikilink]] but isn't yet. Only suggest links to things that LIKELY
   have a vault note (people, projects, tools, brain concepts). Do NOT flag common
   English words.

2. ORPHAN FLAGS — notes longer than {ORPHAN_MIN_CHARS} chars that have NO [[wikilinks]]
   at all. List the note path and a one-line reason it needs linking.

3. INDEX DRIFT — if a note title, status, or project seems like it should appear in
   an index (work/Index.md, personal/Index.md, brain/Memories.md) but likely doesn't
   yet, flag it briefly.

OUTPUT FORMAT — respond with valid JSON only, no preamble, no code fences:
{{
  "missing_links": [
    {{"note": "<rel_path>", "text": "<exact prose>", "suggested": "[[Target Note]]", "rationale": "one line"}},
    ...
  ],
  "orphans": [
    {{"note": "<rel_path>", "rationale": "one line"}},
    ...
  ],
  "index_drift": [
    {{"note": "<rel_path>", "index": "<index file>", "rationale": "one line"}},
    ...
  ]
}}

If a category has no findings, use an empty list [].
Keep rationales brief (under 20 words each).

=== NOTES TO REVIEW ==={notes_block}
"""


def run_lane_b_headless(prompt: str) -> dict | None:
    """Call claude-haiku headless in a temp cwd; return parsed JSON or None."""
    try:
        result = subprocess.run(
            ["claude", "-p", "--model", LANE_B_MODEL],
            input=prompt,
            capture_output=True,
            text=True,
            cwd=tempfile.gettempdir(),  # avoid loading vault CLAUDE.md / hooks
            timeout=LANE_B_TIMEOUT,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None

    if result.returncode != 0:
        return None

    out = result.stdout.strip()
    if not out:
        return None

    # Strip code fences if the model wrapped its output
    if out.startswith("```"):
        lines = out.splitlines()
        out = "\n".join(
            ln for ln in lines if not ln.startswith("```")
        ).strip()

    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return None


def run_lane_b(
    notes: list[Path],
    vault_root: Path,
    skip: bool = False,
) -> dict:
    """Run the headless Lane B pass.  Returns structured dict or empty on skip/failure."""
    empty: dict = {"missing_links": [], "orphans": [], "index_drift": []}
    if skip or not notes:
        return empty

    # Cap note count
    capped = notes[:MAX_NOTES_LANE_B]

    notes_content: list[tuple[str, str]] = []
    for p in capped:
        try:
            rel = str(p.relative_to(vault_root))
        except ValueError:
            rel = str(p)
        try:
            content = p.read_text(encoding="utf-8")
        except OSError:
            continue
        notes_content.append((rel, content))

    if not notes_content:
        return empty

    prompt = build_lane_b_prompt(notes_content)
    data = run_lane_b_headless(prompt)
    if data is None:
        return empty
    return data


# ---------------------------------------------------------------------------
# Queue writer
# ---------------------------------------------------------------------------

def _extract_broken_target(proposal: str) -> str | None:
    """Pull the normalized broken-link target out of a rendered proposal's gsig.

    Proposals carry ``<!-- gsig: broken|<note>|<normalized_target> -->``; returns
    ``<normalized_target>`` for broken proposals, else None.
    """
    marker = "<!-- gsig: "
    i = proposal.find(marker)
    if i == -1:
        return None
    j = proposal.find(" -->", i)
    sig = proposal[i + len(marker): j if j != -1 else len(proposal)].strip()
    parts = sig.split("|", 2)
    if len(parts) == 3 and parts[0] == "broken":
        return parts[2]
    return None


def write_queue(
    vault_root: Path,
    context: str,
    lane_a: LaneAResult,
    lane_b: dict,
    dry_run: bool = False,
    dismissed: set[str] = frozenset(),
    stranded: list[dict] = (),
    memdrift: dict | None = None,
    unprofiled: list[str] = (),
) -> Path:
    """Write (or print in dry_run) the gardener queue file."""
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines: list[str] = [
        "---",
        "date: " + datetime.now().strftime("%Y-%m-%d"),
        'description: "Graph Gardener queue — auto-repairs and link proposals"',
        "tags:",
        "  - gardener",
        "---",
        "",
        f"# Graph Gardener Queue — {context.title()}",
        "",
        f"_Last run: {stamp}_",
        "",
        "## Applied (auto-repairs)",
        "",
    ]

    if lane_a.applied:
        for entry in lane_a.applied:
            lines.append(f"- {entry}")
    else:
        lines.append("_(no auto-repairs this pass)_")

    lines += [
        "",
        "## Proposed",
        "",
        "### Broken links (unresolved)",
        "",
    ]
    # Partition broken-link proposals: auto-memory drift (target is a durable fact
    # trapped in machine-local auto-memory) vs plain broken links.
    drift_map = memdrift or {}
    drift_counts: dict[str, int] = {}
    plain_broken: list[str] = []
    for entry in lane_a.proposals:
        target = _extract_broken_target(entry)
        if target is not None and target in drift_map:
            drift_counts[target] = drift_counts.get(target, 0) + 1
        else:
            plain_broken.append(entry)

    if plain_broken:
        for entry in plain_broken:
            lines.append(f"- {entry}")
    else:
        lines.append("_(none)_")

    lines += ["", "### Unprofiled people", ""]
    rendered_unprofiled = []
    for name in (unprofiled or []):
        sig = proposal_signature("person", "", name)
        if sig in dismissed:
            continue
        rendered_unprofiled.append(
            f"- `{name}` — linked in `org/People & Context.md` but no "
            f"`org/people/{name}.md` profile <!-- gsig: {sig} -->"
        )
    if rendered_unprofiled:
        lines.extend(rendered_unprofiled)
    else:
        lines.append("_(none)_")

    lines += ["", "### Auto-memory drift (promote to vault)", ""]
    rendered_drift = []
    for slug, count in drift_counts.items():
        sig = proposal_signature("memdrift", "", slug)
        if sig in dismissed:
            continue
        filename = drift_map.get(slug, "?")
        note_word = "note" if count == 1 else "notes"
        rendered_drift.append(
            f"- `{slug}` — wikilinked in {count} {note_word} but lives only in "
            f"auto-memory (`{filename}`); promote into the vault <!-- gsig: {sig} -->"
        )
    if rendered_drift:
        lines.extend(rendered_drift)
    else:
        lines.append("_(none)_")

    lines += ["", "### Missing links (LLM suggestions)", ""]
    missing = lane_b.get("missing_links", [])
    if missing:
        rendered_missing = []
        for item in missing:
            note = item.get("note", "?")
            text = item.get("text", "?")
            suggested = item.get("suggested", "?")
            rationale = item.get("rationale", "")
            sig = proposal_signature("missing", note, f"{text}->{suggested}")
            if sig in dismissed:
                continue
            rendered_missing.append(
                f"- `{note}`: \"{text}\" → {suggested}"
                + (f" — {rationale}" if rationale else "")
                + f" <!-- gsig: {sig} -->"
            )
        if rendered_missing:
            lines.extend(rendered_missing)
        else:
            lines.append("_(none)_")
    else:
        lines.append("_(none)_")

    lines += ["", "### Orphans (no [[links]])", ""]
    orphans = lane_b.get("orphans", [])
    if orphans:
        rendered_orphans = []
        for item in orphans:
            note = item.get("note", "?")
            rationale = item.get("rationale", "")
            sig = proposal_signature("orphan", note)
            if sig in dismissed:
                continue
            rendered_orphans.append(
                f"- `{note}`" + (f" — {rationale}" if rationale else "")
                + f" <!-- gsig: {sig} -->"
            )
        if rendered_orphans:
            lines.extend(rendered_orphans)
        else:
            lines.append("_(none)_")
    else:
        lines.append("_(none)_")

    lines += ["", "### Stranded branches", ""]
    rendered_stranded = []
    for item in (stranded or []):
        branch = item.get("branch", "?")
        files = item.get("files", [])
        sig = proposal_signature("branch", "", branch)
        if sig in dismissed:
            continue
        files_str = ", ".join(f"`{f}`" for f in files)
        rendered_stranded.append(
            f"- branch `{branch}` holds net-new notes not on main: {files_str}"
            f" — port or delete <!-- gsig: {sig} -->"
        )
    if rendered_stranded:
        lines.extend(rendered_stranded)
    else:
        lines.append("_(none)_")

    lines += ["", "### Index drift", ""]
    drift = lane_b.get("index_drift", [])
    if drift:
        rendered_drift = []
        for item in drift:
            note = item.get("note", "?")
            index = item.get("index", "?")
            rationale = item.get("rationale", "")
            sig = proposal_signature("drift", note, index)
            if sig in dismissed:
                continue
            # Drop false positives: the note is already wikilinked in the index.
            if note_in_index(note, index, vault_root):
                continue
            rendered_drift.append(
                f"- `{note}` → `{index}`"
                + (f" — {rationale}" if rationale else "")
                + f" <!-- gsig: {sig} -->"
            )
        if rendered_drift:
            lines.extend(rendered_drift)
        else:
            lines.append("_(none)_")
    else:
        lines.append("_(none)_")

    lines.append("")
    content = "\n".join(lines)

    queue_path = vault_root / ".brain" / f"gardener-{context}.md"

    if dry_run:
        print("\n--- GARDENER QUEUE (dry-run, not written) ---")
        print(content)
        print("--- END QUEUE ---\n")
    else:
        queue_path.parent.mkdir(parents=True, exist_ok=True)
        queue_path.write_text(content, encoding="utf-8")

    return queue_path


# ---------------------------------------------------------------------------
# Queue summary (for session-start surfacing)
# ---------------------------------------------------------------------------

def queue_summary(vault_root: Path, context: str) -> str | None:
    """Return a one-line summary if the gardener queue is non-empty, else None.

    Counts applied repairs and total proposed items.
    """
    queue_path = vault_root / ".brain" / f"gardener-{context}.md"
    if not queue_path.exists():
        return None

    try:
        text = queue_path.read_text(encoding="utf-8")
    except OSError:
        return None

    # Count applied repairs (lines under "## Applied" that start with "- ")
    applied = 0
    proposals = 0
    in_applied = False
    in_proposed = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## Applied"):
            in_applied = True
            in_proposed = False
        elif stripped.startswith("## Proposed"):
            in_applied = False
            in_proposed = True
        elif stripped.startswith("##"):
            in_applied = False
            in_proposed = True  # still in proposals section
        elif stripped.startswith("- "):
            if in_applied:
                applied += 1
            elif in_proposed:
                proposals += 1

    if applied == 0 and proposals == 0:
        return None

    # Repairs-only: nothing to act on — transparency line, no CTA, never loud.
    if proposals == 0:
        return (f"🌱 {applied} auto-repair{'s' if applied != 1 else ''} applied "
                f"— see `.brain/gardener-{context}.md`")

    # Proposals pending → actionable nudge, escalating on size or staleness.
    last = load_state(vault_root).get("last_applied_ts")
    days_since = None
    if last:
        try:
            days_since = (datetime.now() - datetime.fromisoformat(last)).days
        except Exception:
            days_since = None

    head = f"{proposals} graph suggestion{'s' if proposals != 1 else ''}"
    if applied:
        head += f" + {applied} auto-repair{'s' if applied != 1 else ''}"

    loud = (
        proposals >= QUEUE_LOUD_THRESHOLD
        or days_since is None
        or days_since >= STALE_GARDEN_DAYS
    )
    if loud:
        age = (
            "never gardened" if days_since is None
            else f"last gardened {days_since} day{'s' if days_since != 1 else ''} ago"
        )
        return f"⚠️ {head} pending, {age} — run `/garden`"
    return f"🌱 {head} pending — run `/garden`"


# ---------------------------------------------------------------------------
# Main entry point (Stop hook)
# ---------------------------------------------------------------------------

def run_gardener(
    session_id: str,
    vault_root: Path,
    dry_run: bool = False,
    notes_override: list[Path] | None = None,
    skip_lane_b: bool = False,
    check_debounce: bool = True,
) -> int:
    """Core gardener logic — callable directly or from the hook entry.

    Returns 0 always (fail-soft contract).
    """
    context = read_context(vault_root)

    # --- Debounce ---
    state = load_state(vault_root)
    if check_debounce and session_id and not dry_run and already_ran(state, session_id):
        log(vault_root, f"already ran for session {session_id[:8]} — skip")
        return 0

    # --- Apply-lock: don't clobber the queue while /garden is resolving it ---
    # (dry-run never writes, so it's exempt — it's how convergence is verified mid-pass.)
    if not dry_run and apply_lock_active(vault_root):
        log(vault_root, "apply-lock held (/garden in progress) — skip queue write")
        return 0

    # --- Scope ---
    notes, new_cursor = collect_touched_notes(vault_root, state, override=notes_override)
    head = head_commit(vault_root)

    if not notes and notes_override is None:
        log(vault_root, "no settled changed notes — skip")
        if not dry_run:
            advanced = {
                **state,
                "last_run_ts": datetime.now().isoformat(),
                "last_gardened_commit": head or state.get("last_gardened_commit"),
                "sweep_cursor": new_cursor,
            }
            if session_id:
                advanced = record_run(advanced, session_id)
            save_state(vault_root, advanced)
        return 0

    log(vault_root, f"gardening {len(notes)} note(s) [session={session_id[:8] if session_id else 'dry-run'}]")
    for n in notes:
        try:
            log(vault_root, f"  scope: {n.relative_to(vault_root)}")
        except ValueError:
            log(vault_root, f"  scope: {n}")

    # --- Suppress-list ---
    dismissed = load_dismissed(vault_root)

    # --- Lane A ---
    lane_a = run_lane_a(
        notes,
        vault_root,
        dry_run=dry_run,
        dismissed=dismissed,
        broken_by_note=broken_links_by_note(vault_root),
    )

    # --- Lane B ---
    lane_b = run_lane_b(notes, vault_root, skip=skip_lane_b)

    # --- Stranded-branch detection (git boundary) ---
    stranded = detect_stranded_branches(vault_root)

    # --- Auto-memory drift detection (machine-local memory boundary) ---
    memdrift = detect_auto_memory_drift(vault_root)

    # --- Unprofiled-people detection (org index vs org/people/ boundary) ---
    unprofiled = detect_unprofiled_people(vault_root)

    # --- Write queue ---
    write_queue(
        vault_root, context, lane_a, lane_b,
        dry_run=dry_run, dismissed=dismissed, stranded=stranded, memdrift=memdrift,
        unprofiled=unprofiled,
    )

    n_applied = len(lane_a.applied)
    n_proposals = len(lane_a.proposals) + len(stranded) + sum(
        len(lane_b.get(k, []))
        for k in ("missing_links", "orphans", "index_drift")
    )
    log(
        vault_root,
        f"done: {n_applied} auto-repair(s), {n_proposals} proposal(s) "
        f"[lane_b={'skipped' if skip_lane_b else 'ran'}]",
    )

    # --- Update state ---
    # Record gardened hashes (post-Lane-A, so auto-repaired notes don't re-propose).
    gardened = dict(state.get("gardened", {}))
    for p in notes:
        try:
            gardened[str(p.relative_to(vault_root))] = content_hash(p)
        except ValueError:
            pass

    if session_id and not dry_run:
        new_state = {
            **state,
            "last_run_ts": datetime.now().isoformat(),
            "last_gardened_commit": head or state.get("last_gardened_commit"),
            "sweep_cursor": new_cursor,
            "gardened": gardened,
        }
        new_state = record_run(new_state, session_id)
        save_state(vault_root, new_state)

    return 0


def main_hook() -> int:
    """Stop-hook entry: read hook JSON from stdin, mark session gardened, spawn detached worker.

    Returns 0 immediately (in milliseconds) — never runs Lane A or Lane B
    synchronously, so the hook timeout is never a concern.  The actual gardening
    happens in the detached --worker subprocess.

    Mirrors notebook-update.py's Popen pattern exactly.
    """
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        event = {}

    session_id: str = event.get("session_id", "")

    vault_root = find_vault_root_from_env()
    if vault_root is None:
        return 0  # not in vault — silently skip

    # --- Apply-lock: /garden owns the queue; don't spawn a worker that would clobber it.
    # Return WITHOUT recording debounce so a later Stop (after the lock clears) can regenerate.
    if apply_lock_active(vault_root):
        log(vault_root, "apply-lock held (/garden in progress) — skip spawn")
        return 0

    # --- Debounce check (fast, no I/O beyond one JSON read) ---
    state = load_state(vault_root)
    if session_id and already_ran(state, session_id):
        log(vault_root, f"already ran for session {session_id[:8]} — skip")
        return 0

    # --- Record NOW so subsequent Stop events this session don't re-spawn ---
    new_state = record_run(state, session_id)
    save_state(vault_root, new_state)
    log(vault_root, f"hook: spawning detached worker [session={session_id[:8] if session_id else 'unknown'}]")

    # --- Spawn detached worker (mirrors notebook-update.py) ---
    popen_kwargs: dict = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "stdin": subprocess.DEVNULL,
    }
    if hasattr(os, "setsid"):
        popen_kwargs["start_new_session"] = True

    try:
        subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--worker",
                "--session", session_id,
                "--vault-root", str(vault_root),
            ],
            **popen_kwargs,
        )
    except OSError:
        pass  # fail-soft — worker not launched, but debounce already recorded

    return 0


def run_worker(session_id: str, vault_root: Path) -> int:
    """Worker mode: run gardening synchronously (spawned detached by main_hook).

    Delegates to run_gardener with debounce disabled — main_hook already recorded
    this session before spawning, so re-checking would always short-circuit.
    """
    return run_gardener(
        session_id=session_id,
        vault_root=vault_root,
        dry_run=False,
        check_debounce=False,
    )


# ---------------------------------------------------------------------------
# CLI entry (dry-run / testing and --worker dispatch)
# ---------------------------------------------------------------------------

_CLI_FLAGS = {"--dry-run", "--notes", "--skip-lane-b", "--vault-root", "--worker", "--session", "--acquire-lock", "--release-lock", "--queue-summary", "--help", "-h"}


def main_cli() -> int:
    """CLI entry for dry-run testing, manual invocation, and --worker dispatch.

    --worker is called by the detached subprocess spawned by main_hook().
    --dry-run / --notes / --skip-lane-b run synchronously (no spawn) exactly
    as before — these are testing / standalone modes.
    """
    parser = argparse.ArgumentParser(
        description="Graph Gardener — standalone / dry-run mode"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print queue instead of writing; do not modify notes or state.",
    )
    parser.add_argument(
        "--notes",
        nargs="*",
        metavar="PATH",
        help="Override note scope (paths relative to vault root or absolute).",
    )
    parser.add_argument(
        "--skip-lane-b",
        action="store_true",
        help="Skip the headless LLM pass (Lane B). Useful for quick Lane-A-only tests.",
    )
    parser.add_argument(
        "--vault-root",
        metavar="PATH",
        help="Explicit vault root (default: auto-detect from cwd).",
    )
    parser.add_argument(
        "--worker",
        action="store_true",
        help="Internal: run gardening synchronously (spawned detached by main_hook).",
    )
    parser.add_argument(
        "--session",
        metavar="SESSION_ID",
        default="",
        help="Session ID passed to worker mode.",
    )
    parser.add_argument(
        "--acquire-lock",
        action="store_true",
        help="Acquire the /garden apply-lock (blocks producer workers), then exit.",
    )
    parser.add_argument(
        "--release-lock",
        action="store_true",
        help="Release the /garden apply-lock (and stamp last-gardened), then exit.",
    )
    parser.add_argument(
        "--queue-summary",
        action="store_true",
        help="Print the gardener queue nudge (or 'nothing pending'), then exit.",
    )
    args = parser.parse_args()

    vault_root: Path | None
    if args.vault_root:
        vault_root = Path(args.vault_root).resolve()
    else:
        vault_root = find_vault_root_from_env()

    if vault_root is None:
        print("ERROR: vault root not found. Use --vault-root or run from inside the vault.", file=sys.stderr)
        return 1

    # --acquire-lock / --release-lock: /garden's apply-lock management, then exit.
    if args.acquire_lock:
        acquire_apply_lock(vault_root, args.session)
        return 0
    if args.release_lock:
        release_apply_lock(vault_root)
        mark_applied(vault_root)
        return 0
    if args.queue_summary:
        s = queue_summary(vault_root, read_context(vault_root))
        print(s if s else "🌱 nothing pending")
        return 0

    # --worker: detached subprocess path — run gardening directly, no spawn.
    if args.worker:
        return run_worker(session_id=args.session, vault_root=vault_root)

    # All other CLI flags: dry-run / manual path — fully synchronous, no spawn.
    notes_override: list[Path] | None = None
    if args.notes is not None:
        notes_override = [
            Path(n).resolve() if Path(n).is_absolute() else (vault_root / n).resolve()
            for n in args.notes
        ]

    return run_gardener(
        session_id="dry-run",
        vault_root=vault_root,
        dry_run=args.dry_run,
        notes_override=notes_override,
        skip_lane_b=args.skip_lane_b,
    )


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # --worker, --dry-run, --notes, --skip-lane-b, --vault-root, --session, --help
    # → CLI entry (synchronous testing modes or detached worker).
    # No CLI flags → hook entry (reads stdin JSON, spawns detached worker, returns fast).
    is_cli = bool(set(sys.argv[1:]) & _CLI_FLAGS) or any(
        a.startswith("--") for a in sys.argv[1:]
    )
    if is_cli:
        try:
            sys.exit(main_cli())
        except Exception as exc:
            print(f"graph_gardener: fatal: {exc}", file=sys.stderr)
            sys.exit(1)
    else:
        try:
            sys.exit(main_hook())
        except Exception as exc:
            print(f"graph_gardener: {exc}", file=sys.stderr)
            sys.exit(0)  # fail-soft: never block the Stop hook
