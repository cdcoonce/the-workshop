import importlib.util
import subprocess as _sp
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "graph_gardener", Path(__file__).resolve().parent.parent / "engine" / "graph_gardener.py"
)
gg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gg)

import vault_utils  # noqa: E402


def _git(repo, *args):
    _sp.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _init_repo(tmp_path):
    repo = tmp_path
    _git(repo, "init")
    _git(repo, "config", "user.email", "t@t.t")
    _git(repo, "config", "user.name", "t")
    (repo / "personal").mkdir()
    # Model a real machine: .vault-context present. read_context defaults to
    # "unknown" only when absent (that edge case is covered in test_vault_utils),
    # so the gardener queue lands at gardener-personal.md as the assertions expect.
    (repo / ".vault-context").write_text("personal", encoding="utf-8")
    return repo


def test_backlog_first_run_starts_at_head():
    out, cur = gg.select_backlog_batch(["a.md", "b.md", "c.md"], None, 2)
    assert out == ["a.md", "b.md"]
    assert cur == "b.md"


def test_backlog_resumes_after_cursor():
    out, cur = gg.select_backlog_batch(["a.md", "b.md", "c.md", "d.md"], "b.md", 2)
    assert out == ["c.md", "d.md"]
    assert cur == "d.md"


def test_backlog_wraps_past_end():
    out, cur = gg.select_backlog_batch(["a.md", "b.md", "c.md"], "c.md", 2)
    assert out == ["a.md", "b.md"]
    assert cur == "b.md"


def test_backlog_caps_at_list_size():
    out, cur = gg.select_backlog_batch(["a.md", "b.md"], None, 10)
    assert out == ["a.md", "b.md"]
    assert cur == "b.md"


def test_backlog_empty_list_keeps_cursor():
    out, cur = gg.select_backlog_batch([], "x.md", 5)
    assert out == []
    assert cur == "x.md"


def test_backlog_missing_cursor_restarts_at_head():
    # cursor refers to a note that no longer exists; bisect lands mid-list
    out, cur = gg.select_backlog_batch(["a.md", "c.md", "e.md"], "b.md", 1)
    assert out == ["c.md"]
    assert cur == "c.md"


def test_filter_keeps_never_gardened():
    assert gg.filter_unchanged([("a.md", "h1")], {}) == ["a.md"]


def test_filter_drops_unchanged():
    assert gg.filter_unchanged([("a.md", "h1")], {"a.md": "h1"}) == []


def test_filter_keeps_changed():
    assert gg.filter_unchanged([("a.md", "h2")], {"a.md": "h1"}) == ["a.md"]


def test_filter_mixed_preserves_order():
    cands = [("a.md", "h1"), ("b.md", "h2"), ("c.md", "h3")]
    gardened = {"a.md": "h1", "c.md": "old"}
    assert gg.filter_unchanged(cands, gardened) == ["b.md", "c.md"]


def test_all_in_scope_notes_sorted_and_scoped(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "personal" / "b.md").write_text("b")
    (repo / "personal" / "a.md").write_text("a")
    (repo / "templates").mkdir()
    (repo / "templates" / "t.md").write_text("t")  # excluded scope
    out = gg.all_in_scope_notes(repo)
    assert out == ["personal/a.md", "personal/b.md"]


def test_content_hash_changes_with_content(tmp_path):
    p = tmp_path / "n.md"
    p.write_text("one")
    h1 = gg.content_hash(p)
    p.write_text("two")
    assert h1 != gg.content_hash(p)
    assert gg.content_hash(tmp_path / "missing.md") == ""


def test_commit_range_changed_notes(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "personal" / "a.md").write_text("a1")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "c1")
    base = gg.head_commit(repo)
    assert base
    (repo / "personal" / "a.md").write_text("a2")
    (repo / "personal" / "b.md").write_text("b1")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "c2")
    changed = gg.commit_range_changed_notes(repo, base)
    names = sorted(p.name for p in changed)
    assert names == ["a.md", "b.md"]
    assert gg.commit_range_changed_notes(repo, None) == []


import os as _os
import time as _time


def test_collect_recency_and_backlog(tmp_path):
    repo = _init_repo(tmp_path)
    # Two committed notes, aged past the settle window via mtime backdating.
    a = repo / "personal" / "a.md"
    b = repo / "personal" / "b.md"
    a.write_text("alpha content")
    b.write_text("beta content")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "c1")
    base = gg.head_commit(repo)
    # New commit changes only a.md (recency source).
    a.write_text("alpha changed")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "c2")
    old = _time.time() - 9999
    for p in (a, b):
        _os.utime(p, (old, old))
    state = {"last_gardened_commit": base, "sweep_cursor": None, "gardened": {}}
    notes, cursor = gg.collect_touched_notes(repo, state)
    names = sorted(p.name for p in notes)
    # a.md via recency, a.md+b.md via backlog → deduped union {a,b}
    assert names == ["a.md", "b.md"]
    assert cursor is not None


def test_collect_drops_unchanged_already_gardened(tmp_path):
    repo = _init_repo(tmp_path)
    a = repo / "personal" / "a.md"
    a.write_text("stable content")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "c1")
    old = _time.time() - 9999
    _os.utime(a, (old, old))
    state = {
        "last_gardened_commit": None,
        "sweep_cursor": None,
        "gardened": {"personal/a.md": gg.content_hash(a)},
    }
    notes, _ = gg.collect_touched_notes(repo, state)
    assert notes == []  # unchanged + already gardened → skipped


def test_collect_override_bypasses_detection(tmp_path):
    repo = _init_repo(tmp_path)
    a = repo / "personal" / "a.md"
    a.write_text("x")
    notes, cursor = gg.collect_touched_notes(repo, {}, override=[a])
    assert [p.name for p in notes] == ["a.md"]


def test_lanea_preserves_display_when_repair_degrades_to_slug(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "personal" / "onestream-data-pipeline.md").write_text("x")
    note = repo / "personal" / "doc.md"
    note.write_text("See [[OneStream Data Pipeline]] for details.")
    gg.run_lane_a([note], repo, dry_run=False)
    assert "[[onestream-data-pipeline|OneStream Data Pipeline]]" in note.read_text()


def test_lanea_snaps_to_title_for_case_fix(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "personal" / "North Star.md").write_text("x")
    note = repo / "personal" / "doc.md"
    note.write_text("See [[north star]] today.")
    gg.run_lane_a([note], repo, dry_run=False)
    txt = note.read_text()
    assert "[[North Star]]" in txt
    assert "[[North Star|north star]]" not in txt


def test_lanea_snaps_to_title_when_slug_to_readable(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "personal" / "Claude Workflow.md").write_text("x")
    note = repo / "personal" / "doc.md"
    note.write_text("Using [[claude-workflow]] now.")
    gg.run_lane_a([note], repo, dry_run=False)
    txt = note.read_text()
    assert "[[Claude Workflow]]" in txt
    assert "[[Claude Workflow|claude-workflow]]" not in txt


def test_lanea_keeps_existing_alias_on_slug_repair(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "personal" / "onestream-data-pipeline.md").write_text("x")
    note = repo / "personal" / "doc.md"
    note.write_text("See [[OneStream Data Pipeline|the pipeline]] here.")
    gg.run_lane_a([note], repo, dry_run=False)
    assert "[[onestream-data-pipeline|the pipeline]]" in note.read_text()


# ---------------------------------------------------------------------------
# Apply-lock — race fix (detached workers must not clobber the queue mid-/garden)
# ---------------------------------------------------------------------------

import io as _io
import json as _json
from datetime import datetime as _dt, timedelta as _td

_LOCK_REL = Path(".brain") / ".garden-lock"


def _write_lock(repo, started_iso, session="x"):
    """Write a lock file directly with a chosen `started` timestamp."""
    p = repo / _LOCK_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_json.dumps({"started": started_iso, "session": session}), encoding="utf-8")
    return p


def _broken_note(repo):
    """A note carrying one unresolvable [[link]] so the gardener has a proposal to write."""
    p = repo / "personal" / "note.md"
    p.write_text("---\ndate: 2026-01-01\n---\n\nSee [[Nonexistent Target Note]].\n", encoding="utf-8")
    return p


def _init_vault(tmp_path):
    """A temp repo that find_vault_root accepts (CLAUDE.md + brain/ + perf/)."""
    repo = _init_repo(tmp_path)
    (repo / "CLAUDE.md").write_text("# vault", encoding="utf-8")
    (repo / "brain").mkdir()
    (repo / "perf").mkdir()
    return repo


# --- apply_lock_active unit ---

def test_apply_lock_active_missing_is_false(tmp_path):
    repo = _init_repo(tmp_path)
    assert gg.apply_lock_active(repo) is False


def test_apply_lock_active_fresh_is_true(tmp_path):
    repo = _init_repo(tmp_path)
    _write_lock(repo, _dt.now().isoformat())
    assert gg.apply_lock_active(repo) is True


def test_apply_lock_active_stale_is_false_and_removed(tmp_path):
    repo = _init_repo(tmp_path)
    stale = (_dt.now() - _td(seconds=gg.APPLY_LOCK_TTL_SECONDS + 60)).isoformat()
    _write_lock(repo, stale)
    assert gg.apply_lock_active(repo) is False
    assert not (repo / _LOCK_REL).exists()  # self-heals abandoned lock


def test_apply_lock_active_malformed_is_false_and_removed(tmp_path):
    repo = _init_repo(tmp_path)
    p = repo / _LOCK_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("not json", encoding="utf-8")
    assert gg.apply_lock_active(repo) is False
    assert not (repo / _LOCK_REL).exists()


# --- acquire / release ---

def test_acquire_then_release_lock(tmp_path):
    repo = _init_repo(tmp_path)
    gg.acquire_apply_lock(repo, "sess-1")
    assert (repo / _LOCK_REL).exists()
    assert gg.apply_lock_active(repo) is True
    gg.release_apply_lock(repo)
    assert not (repo / _LOCK_REL).exists()


def test_release_lock_is_safe_when_absent(tmp_path):
    repo = _init_repo(tmp_path)
    gg.release_apply_lock(repo)  # must not raise
    assert not (repo / _LOCK_REL).exists()


# --- run_gardener guard ---

def test_run_gardener_writes_queue_when_no_lock(tmp_path):
    repo = _init_repo(tmp_path)
    note = _broken_note(repo)
    rc = gg.run_gardener(
        session_id="s", vault_root=repo,
        notes_override=[note], skip_lane_b=True, check_debounce=False,
    )
    assert rc == 0
    assert (repo / ".brain" / "gardener-personal.md").exists()


def test_run_gardener_skips_write_when_lock_fresh(tmp_path):
    repo = _init_repo(tmp_path)
    note = _broken_note(repo)
    _write_lock(repo, _dt.now().isoformat())
    rc = gg.run_gardener(
        session_id="s", vault_root=repo,
        notes_override=[note], skip_lane_b=True, check_debounce=False,
    )
    assert rc == 0
    assert not (repo / ".brain" / "gardener-personal.md").exists()  # no clobber
    assert (repo / _LOCK_REL).exists()  # fresh lock left intact


def test_run_gardener_proceeds_when_lock_stale(tmp_path):
    repo = _init_repo(tmp_path)
    note = _broken_note(repo)
    _write_lock(repo, (_dt.now() - _td(seconds=gg.APPLY_LOCK_TTL_SECONDS + 60)).isoformat())
    rc = gg.run_gardener(
        session_id="s", vault_root=repo,
        notes_override=[note], skip_lane_b=True, check_debounce=False,
    )
    assert rc == 0
    assert (repo / ".brain" / "gardener-personal.md").exists()  # proceeded
    assert not (repo / _LOCK_REL).exists()  # stale lock cleared


def test_run_gardener_dry_run_ignores_lock(tmp_path, capsys):
    repo = _init_repo(tmp_path)
    note = _broken_note(repo)
    _write_lock(repo, _dt.now().isoformat())
    gg.run_gardener(
        session_id="s", vault_root=repo, dry_run=True,
        notes_override=[note], skip_lane_b=True, check_debounce=False,
    )
    assert "GARDENER QUEUE" in capsys.readouterr().out  # rendered despite lock


# --- main_hook guard ---

def test_main_hook_skips_spawn_when_locked(tmp_path, monkeypatch):
    repo = _init_vault(tmp_path)
    _write_lock(repo, _dt.now().isoformat())
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    monkeypatch.setattr(gg.sys, "stdin", _io.StringIO(_json.dumps({"session_id": "sess-X"})))
    spawned = []
    monkeypatch.setattr(gg.subprocess, "Popen", lambda *a, **k: spawned.append(a))
    rc = gg.main_hook()
    assert rc == 0
    assert spawned == []  # no detached worker launched while apply-lock held
    # debounce NOT recorded → a later Stop (after lock clears) can still regenerate
    assert "sess-X" not in gg.load_state(repo).get("gardened_session_ids", [])


# --- CLI flags the /garden skill uses to acquire / release the lock ---

def test_cli_acquire_then_release_lock(tmp_path, monkeypatch):
    repo = _init_vault(tmp_path)
    monkeypatch.setattr(gg.sys, "argv", ["gg", "--acquire-lock", "--vault-root", str(repo)])
    assert gg.main_cli() == 0
    assert gg.apply_lock_active(repo) is True
    monkeypatch.setattr(gg.sys, "argv", ["gg", "--release-lock", "--vault-root", str(repo)])
    assert gg.main_cli() == 0
    assert not (repo / _LOCK_REL).exists()


# ---------------------------------------------------------------------------
# Path-qualified wikilink resolution (Defect 2) — [[folder/note]] must resolve
# ---------------------------------------------------------------------------

def _src_note(repo, body):
    """A source note (under personal/) whose [[links]] Lane A will inspect."""
    p = repo / "personal" / "src.md"
    p.write_text(body, encoding="utf-8")
    return p


def _scan(*displays, reason="missing", candidates=(), note="personal/src.md"):
    """A graphmark scan result for ``note``, as ``broken_links_by_note`` returns it.

    Lane A no longer decides brokenness for itself — with no scan it proposes nothing — so a test
    that expects a proposal has to say what graphmark reported, exactly as production does.
    """
    return {note: {d: {"reason": reason, "candidates": list(candidates)} for d in displays}}


def test_path_link_full_path_resolves(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "personal" / "tasks").mkdir(parents=True)
    (repo / "personal" / "tasks" / "2026-W21-tasks.md").write_text("x")
    note = _src_note(repo, "See [[personal/tasks/2026-W21-tasks]].")
    res = gg.run_lane_a([note], repo, dry_run=True)
    assert res.proposals == []
    assert res.applied == []


def test_path_link_unique_suffix_resolves(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "personal" / "tasks").mkdir(parents=True)
    (repo / "personal" / "tasks" / "2026-W21-tasks.md").write_text("x")
    note = _src_note(repo, "See [[tasks/2026-W21-tasks]].")
    res = gg.run_lane_a([note], repo, dry_run=True)
    assert res.proposals == []


def test_path_link_basename_ambiguous_path_disambiguates(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "personal" / "tasks").mkdir(parents=True)
    (repo / "work" / "tasks").mkdir(parents=True)
    (repo / "personal" / "tasks" / "2026-W21-tasks.md").write_text("x")
    (repo / "work" / "tasks" / "2026-W21-tasks.md").write_text("x")
    note = _src_note(repo, "See [[personal/tasks/2026-W21-tasks]].")
    res = gg.run_lane_a([note], repo, dry_run=True)
    assert res.proposals == []  # the path picks the personal copy


def test_path_link_no_match_is_broken(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "personal" / "tasks").mkdir(parents=True)
    note = _src_note(repo, "See [[personal/tasks/nope]].")
    res = gg.run_lane_a(
        [note], repo, dry_run=True, broken_by_note=_scan("personal/tasks/nope")
    )
    assert len(res.proposals) == 1
    assert "no matching note" in res.proposals[0]
    assert "nope" in res.proposals[0]


def test_path_link_suffix_ambiguous_is_flagged(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "personal" / "a" / "x").mkdir(parents=True)
    (repo / "personal" / "b" / "x").mkdir(parents=True)
    (repo / "personal" / "a" / "x" / "note.md").write_text("x")
    (repo / "personal" / "b" / "x" / "note.md").write_text("x")
    note = _src_note(repo, "See [[x/note]].")
    res = gg.run_lane_a(
        [note],
        repo,
        dry_run=True,
        broken_by_note=_scan(
            "x/note",
            reason="ambiguous",
            candidates=["personal/a/x/note.md", "personal/b/x/note.md"],
        ),
    )
    assert len(res.proposals) == 1
    assert "ambiguous" in res.proposals[0]


def test_path_link_with_alias_resolves(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "personal" / "tasks").mkdir(parents=True)
    (repo / "personal" / "tasks" / "2026-W21-tasks.md").write_text("x")
    note = _src_note(repo, "See [[personal/tasks/2026-W21-tasks|W21]] today.")
    res = gg.run_lane_a([note], repo, dry_run=True)
    assert res.proposals == []


# ---------------------------------------------------------------------------
# Index-drift false-positive filter (Defect 3) — already-indexed notes aren't drift
# ---------------------------------------------------------------------------

def test_note_in_index_bare_link(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "personal" / "Index.md").write_text("- [[hex-custom-ui]] — a note\n", encoding="utf-8")
    assert gg.note_in_index("personal/hex-custom-ui.md", "personal/Index.md", repo) is True


def test_note_in_index_aliased_link(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "personal" / "Index.md").write_text("- [[hex-custom-ui|Hex UI]] — a note\n", encoding="utf-8")
    assert gg.note_in_index("personal/hex-custom-ui.md", "personal/Index.md", repo) is True


def test_note_in_index_path_qualified_link(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "personal" / "Index.md").write_text("- [[personal/learning/hex-custom-ui|x]]\n", encoding="utf-8")
    assert gg.note_in_index("personal/learning/hex-custom-ui.md", "personal/Index.md", repo) is True


def test_note_in_index_absent(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "personal" / "Index.md").write_text("- [[something-else]] — x\n", encoding="utf-8")
    assert gg.note_in_index("personal/hex-custom-ui.md", "personal/Index.md", repo) is False


def test_note_in_index_missing_index_file(tmp_path):
    repo = _init_repo(tmp_path)
    assert gg.note_in_index("personal/x.md", "personal/Nope.md", repo) is False


def test_write_queue_filters_already_indexed_drift(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "personal" / "Index.md").write_text("- [[hex-custom-ui]] — a note\n", encoding="utf-8")
    lane_b = {"missing_links": [], "orphans": [], "index_drift": [
        {"note": "personal/hex-custom-ui.md", "index": "personal/Index.md", "rationale": "r"}
    ]}
    gg.write_queue(repo, "personal", gg.LaneAResult(), lane_b)
    out = (repo / ".brain" / "gardener-personal.md").read_text(encoding="utf-8")
    assert "personal/hex-custom-ui.md` → `personal/Index.md" not in out  # filtered as false positive


def test_write_queue_keeps_genuine_drift(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "personal" / "Index.md").write_text("- [[something-else]] — x\n", encoding="utf-8")
    lane_b = {"missing_links": [], "orphans": [], "index_drift": [
        {"note": "personal/newnote.md", "index": "personal/Index.md", "rationale": "r"}
    ]}
    gg.write_queue(repo, "personal", gg.LaneAResult(), lane_b)
    out = (repo / ".brain" / "gardener-personal.md").read_text(encoding="utf-8")
    assert "personal/newnote.md` → `personal/Index.md" in out  # genuine drift kept


# ---------------------------------------------------------------------------
# Code-span scanning (Defect 4) — [[links]] inside code are docs, not real links
# ---------------------------------------------------------------------------

def test_code_span_inline_link_not_flagged(tmp_path):
    repo = _init_repo(tmp_path)
    note = _src_note(repo, "Docs: `[[Nonexistent Example]]` is just syntax.")
    res = gg.run_lane_a([note], repo, dry_run=True)
    assert res.proposals == []


def test_code_span_fenced_link_not_flagged(tmp_path):
    repo = _init_repo(tmp_path)
    note = _src_note(repo, "Example:\n\n```\n[[Nonexistent Example]]\n```\n\ndone.")
    res = gg.run_lane_a([note], repo, dry_run=True)
    assert res.proposals == []


def test_code_span_real_broken_link_still_flagged(tmp_path):
    repo = _init_repo(tmp_path)
    note = _src_note(repo, "See [[Nonexistent Real]] here.")
    res = gg.run_lane_a([note], repo, dry_run=True, broken_by_note=_scan("Nonexistent Real"))
    assert len(res.proposals) == 1
    assert "Nonexistent Real" in res.proposals[0]


def test_code_span_valid_link_outside_code_still_ok(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "personal" / "Real Target.md").write_text("x")
    note = _src_note(repo, "See [[Real Target]] — valid.")
    res = gg.run_lane_a([note], repo, dry_run=True)
    assert res.proposals == []


def test_code_span_mixed_only_real_flagged(tmp_path):
    repo = _init_repo(tmp_path)
    note = _src_note(repo, "Syntax `[[Example Doc]]`, but [[Actually Broken]] is real.")
    # Both displays are in the scan; only the one outside the code span may be proposed.
    res = gg.run_lane_a(
        [note], repo, dry_run=True, broken_by_note=_scan("Example Doc", "Actually Broken")
    )
    assert len(res.proposals) == 1
    assert "Actually Broken" in res.proposals[0]
    assert "Example Doc" not in res.proposals[0]


def test_code_span_autorepair_still_fires_with_code_example(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "personal" / "North Star.md").write_text("x")
    note = _src_note(repo, "Doc `[[example link]]`; see [[north star]] now.")
    gg.run_lane_a([note], repo, dry_run=False)
    txt = note.read_text()
    assert "[[North Star]]" in txt          # case repair fired outside code
    assert "`[[example link]]`" in txt      # code example left untouched


def test_code_spans_detects_inline_and_fenced():
    text = "a `inline` b\n```\nfenced\n```\nplain"
    spans = gg._code_spans(text)
    assert any(text[s:e] == "`inline`" for s, e in spans)
    joined = "".join(text[s:e] for s, e in spans)
    assert "fenced" in joined
    assert gg._code_spans("no code here at all") == []


# ---------------------------------------------------------------------------
# /garden reminder escalation — last-gardened stamp + escalating queue_summary
# ---------------------------------------------------------------------------

def _write_queue_file(repo, proposals=0, applied=0):
    lines = ["---", "date: 2026-01-01", 'description: "q"', "tags:", "  - gardener", "---",
             "", "# Graph Gardener Queue — Personal", "", "_Last run: x_",
             "", "## Applied (auto-repairs)", ""]
    lines += [f"- repair {i}" for i in range(applied)] or ["_(no auto-repairs this pass)_"]
    lines += ["", "## Proposed", "", "### Broken links (unresolved)", ""]
    lines += [f"- `note{i}`: broken `[[X{i}]]` <!-- gsig: broken|n|x{i} -->" for i in range(proposals)] or ["_(none)_"]
    p = repo / ".brain" / "gardener-personal.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


def test_mark_applied_stamps_state(tmp_path):
    repo = _init_repo(tmp_path)
    gg.mark_applied(repo)
    assert "last_applied_ts" in gg.load_state(repo)


def test_cli_release_lock_stamps_applied(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    gg.acquire_apply_lock(repo, "s")
    monkeypatch.setattr(gg.sys, "argv", ["gg", "--release-lock", "--vault-root", str(repo)])
    assert gg.main_cli() == 0
    assert not (repo / _LOCK_REL).exists()
    assert "last_applied_ts" in gg.load_state(repo)


def test_queue_summary_empty_is_none(tmp_path):
    repo = _init_repo(tmp_path)
    _write_queue_file(repo, proposals=0, applied=0)
    assert gg.queue_summary(repo, "personal") is None


def test_queue_summary_fresh_proposals_has_cta_no_warning(tmp_path):
    repo = _init_repo(tmp_path)
    _write_queue_file(repo, proposals=3)
    gg.save_state(repo, {"last_applied_ts": _dt.now().isoformat()})
    s = gg.queue_summary(repo, "personal")
    assert "run `/garden`" in s
    assert "⚠️" not in s


def test_queue_summary_loud_when_over_threshold(tmp_path):
    repo = _init_repo(tmp_path)
    _write_queue_file(repo, proposals=gg.QUEUE_LOUD_THRESHOLD)
    gg.save_state(repo, {"last_applied_ts": _dt.now().isoformat()})
    s = gg.queue_summary(repo, "personal")
    assert "⚠️" in s and "run `/garden`" in s


def test_queue_summary_loud_when_stale(tmp_path):
    repo = _init_repo(tmp_path)
    _write_queue_file(repo, proposals=2)
    old = (_dt.now() - _td(days=gg.STALE_GARDEN_DAYS + 1)).isoformat()
    gg.save_state(repo, {"last_applied_ts": old})
    s = gg.queue_summary(repo, "personal")
    assert "⚠️" in s
    assert "day" in s  # mentions the age


def test_queue_summary_loud_when_never_gardened(tmp_path):
    repo = _init_repo(tmp_path)
    _write_queue_file(repo, proposals=2)  # no state → never gardened
    s = gg.queue_summary(repo, "personal")
    assert "⚠️" in s


def test_queue_summary_repairs_only_no_cta(tmp_path):
    repo = _init_repo(tmp_path)
    _write_queue_file(repo, proposals=0, applied=3)
    gg.save_state(repo, {"last_applied_ts": _dt.now().isoformat()})
    s = gg.queue_summary(repo, "personal")
    assert s is not None
    assert "run `/garden`" not in s
    assert "⚠️" not in s


def test_cli_queue_summary_prints(tmp_path, monkeypatch, capsys):
    repo = _init_repo(tmp_path)
    _write_queue_file(repo, proposals=3)
    gg.save_state(repo, {"last_applied_ts": _dt.now().isoformat()})
    monkeypatch.setattr(gg.sys, "argv", ["gg", "--queue-summary", "--vault-root", str(repo)])
    assert gg.main_cli() == 0
    assert "run `/garden`" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Unprofiled-people detector lane (#72) — indexed person, no org/people profile
# ---------------------------------------------------------------------------

def _people_index(repo, names):
    d = repo / "org"
    d.mkdir(exist_ok=True)
    (d / "People & Context.md").write_text(
        "# People\n\n" + "\n".join(f"- [[{n}]] — context" for n in names) + "\n",
        encoding="utf-8",
    )


def _profile(repo, name):
    d = repo / "org" / "people"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.md").write_text("x", encoding="utf-8")


_EMPTY_LANE_B = {"missing_links": [], "orphans": [], "index_drift": []}


def test_detect_unprofiled_finds_name_without_profile(tmp_path):
    repo = _init_repo(tmp_path)
    _people_index(repo, ["Jane Doe", "John Smith"])
    _profile(repo, "John Smith")
    assert gg.detect_unprofiled_people(repo) == ["Jane Doe"]


def test_detect_unprofiled_ignores_profiled(tmp_path):
    repo = _init_repo(tmp_path)
    _people_index(repo, ["John Smith"])
    _profile(repo, "John Smith")
    assert gg.detect_unprofiled_people(repo) == []


def test_detect_unprofiled_missing_index_is_empty(tmp_path):
    repo = _init_repo(tmp_path)
    assert gg.detect_unprofiled_people(repo) == []


def test_detect_unprofiled_skips_path_links(tmp_path):
    # [[org/teams/DAA]] names a note, not a person. Proposing a profile for it
    # yields the nonsense path org/people/org/teams/DAA.md.
    repo = _init_repo(tmp_path)
    _people_index(repo, ["org/teams/DAA", "Jane Doe"])
    assert gg.detect_unprofiled_people(repo) == ["Jane Doe"]


def test_detect_unprofiled_defers_to_graphmark_when_available(tmp_path):
    # graphmark honors frontmatter aliases and path-suffix resolution, which the
    # gardener's own catalog does not. A display graphmark resolved is not an
    # unprofiled person, whatever this file's local matching would say.
    repo = _init_repo(tmp_path)
    _people_index(repo, ["Data Architecture & Analytics", "Jane Doe"])
    broken = {"org/People & Context.md": {"Jane Doe"}}
    assert gg.detect_unprofiled_people(repo, broken_by_note=broken) == ["Jane Doe"]


def test_detect_unprofiled_compares_the_raw_display_like_lane_a(tmp_path):
    repo = _init_repo(tmp_path)
    _people_index(repo, ["Grant|Grant Kerkman"])
    broken = {"org/People & Context.md": {"Grant|Grant Kerkman"}}
    assert gg.detect_unprofiled_people(repo, broken_by_note=broken) == ["Grant"]


def test_detect_unprofiled_falls_back_when_the_scan_is_unavailable(tmp_path):
    # None means "scan failed", not "nothing is broken" — reading it as the
    # latter would silence every proposal.
    repo = _init_repo(tmp_path)
    _people_index(repo, ["Jane Doe"])
    assert gg.detect_unprofiled_people(repo, broken_by_note=None) == ["Jane Doe"]


def test_detect_unprofiled_is_empty_when_the_index_note_has_no_breaks(tmp_path):
    repo = _init_repo(tmp_path)
    _people_index(repo, ["Jane Doe"])
    assert gg.detect_unprofiled_people(repo, broken_by_note={}) == []


# --- #62: direct coverage for normalize / scope / catalog / settle / rollback ---

def test_normalize_lowercases_and_collapses():
    assert gg._normalize("North  Star!") == "north star"
    assert gg._normalize("AMRT-Tool") == "amrt tool"
    assert gg._normalize("  Multi   Space  ") == "multi space"


def test_is_in_scope_and_excluded(tmp_path):
    repo = _init_repo(tmp_path)
    assert gg._is_in_scope(repo / "personal" / "a.md", repo) is True
    assert gg._is_in_scope(repo / "templates" / "t.md", repo) is False
    assert gg._is_in_scope(repo / "README.md", repo) is False
    assert gg._is_excluded(repo / "templates" / "t.md", repo) is True
    assert gg._is_excluded(repo / "personal" / "session-logs" / "x.md", repo) is True


def test_build_note_catalog_normalizes_and_scopes(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "personal" / "North Star.md").write_text("x")
    (repo / "templates").mkdir()
    (repo / "templates" / "Tmpl.md").write_text("x")
    cat = gg.build_note_catalog(repo)
    assert "north star" in cat
    assert "tmpl" not in cat  # excluded dir omitted


def test_settled_notes_filters_recent(tmp_path):
    repo = _init_repo(tmp_path)
    fresh = repo / "personal" / "fresh.md"; fresh.write_text("x")
    old = repo / "personal" / "old.md"; old.write_text("x")
    past = _time.time() - (gg.RACE_SAFETY_SECS + 60)
    _os.utime(old, (past, past))
    out = gg.settled_notes([fresh, old], repo)
    assert old in out
    assert fresh not in out


def test_run_lane_a_rollback_on_write_failure(tmp_path, monkeypatch):
    import pathlib
    repo = _init_repo(tmp_path)
    (repo / "personal" / "North Star.md").write_text("x")
    note = _src_note(repo, "See [[north star]].")  # case-repairable
    orig = pathlib.Path.write_text
    def boom(self, *a, **k):
        if self == note:
            raise OSError("disk full")
        return orig(self, *a, **k)
    monkeypatch.setattr(pathlib.Path, "write_text", boom)
    res = gg.run_lane_a([note], repo, dry_run=False)
    assert not any("North Star" in a for a in res.applied)  # rolled back out of applied
    assert any("write failed" in p for p in res.proposals)


def test_short_substring_link_not_auto_repaired(tmp_path):
    # #63 obsolescence guard: [[AI]] vs a note merely CONTAINING "ai" must NOT auto-rewrite —
    # auto-repair is equality-gated; substring only yields a proposal.
    repo = _init_repo(tmp_path)
    (repo / "personal" / "Brain Dump.md").write_text("x")  # normalizes to "brain dump" (contains "ai")
    note = _src_note(repo, "Topic: [[AI]] research.")
    before = note.read_text()
    res = gg.run_lane_a(
        [note],
        repo,
        dry_run=False,
        broken_by_note=_scan("AI", candidates=["personal/Brain Dump.md"]),
    )
    assert note.read_text() == before  # file untouched — no substring auto-repair
    assert res.applied == []
    assert any("AI" in p for p in res.proposals)  # surfaced as a hint/proposal instead


def test_excluded_path_target_bare_link_not_flagged(tmp_path):
    # A link to a real note under templates/ (graph-excluded) can never resolve → suppress, don't flag.
    repo = _init_repo(tmp_path)
    (repo / "templates").mkdir()
    (repo / "templates" / "Request Form.md").write_text("x", encoding="utf-8")
    note = _src_note(repo, "See [[Request Form]] for the template.")
    res = gg.run_lane_a([note], repo, dry_run=True)
    assert res.proposals == []


def test_excluded_path_style_link_not_flagged(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "templates" / "sub").mkdir(parents=True)
    (repo / "templates" / "sub" / "Form.md").write_text("x", encoding="utf-8")
    note = _src_note(repo, "See [[templates/sub/Form]] here.")
    res = gg.run_lane_a([note], repo, dry_run=True)
    assert res.proposals == []


def test_genuinely_broken_link_still_flagged_with_excluded_set(tmp_path):
    # Regression guard: a link matching nothing anywhere (incl. excluded dirs) is STILL flagged.
    repo = _init_repo(tmp_path)
    (repo / "templates").mkdir()
    (repo / "templates" / "Request Form.md").write_text("x", encoding="utf-8")
    note = _src_note(repo, "See [[Totally Missing Note]].")
    res = gg.run_lane_a([note], repo, dry_run=True, broken_by_note=_scan("Totally Missing Note"))
    assert len(res.proposals) == 1
    assert "Totally Missing Note" in res.proposals[0]


def test_detect_unprofiled_excludes_nonperson_note(tmp_path):
    # A name linked in People & Context that resolves to a real note elsewhere
    # (e.g. [[North Star]] → brain/North Star.md) is NOT an unprofiled person.
    repo = _init_repo(tmp_path)
    _people_index(repo, ["North Star", "Jane Doe"])
    (repo / "brain").mkdir(exist_ok=True)
    (repo / "brain" / "North Star.md").write_text("x", encoding="utf-8")
    assert gg.detect_unprofiled_people(repo) == ["Jane Doe"]


def test_person_signature():
    assert gg.proposal_signature("person", "", "Jane Doe") == "unprofiled|jane doe"


def test_write_queue_renders_unprofiled(tmp_path):
    repo = _init_repo(tmp_path)
    gg.write_queue(repo, "personal", gg.LaneAResult(), _EMPTY_LANE_B, unprofiled=["Jane Doe"])
    out = (repo / ".brain" / "gardener-personal.md").read_text(encoding="utf-8")
    assert "### Unprofiled people" in out
    assert "Jane Doe" in out
    assert "unprofiled|jane doe" in out


def test_write_queue_unprofiled_suppressed_when_dismissed(tmp_path):
    repo = _init_repo(tmp_path)
    gg.write_queue(repo, "personal", gg.LaneAResult(), _EMPTY_LANE_B,
                   unprofiled=["Jane Doe"], dismissed={"unprofiled|jane doe"})
    out = (repo / ".brain" / "gardener-personal.md").read_text(encoding="utf-8")
    assert "Jane Doe" not in out  # suppressed


# ---------------------------------------------------------------------------
# Lane B model sourcing — owner-owned vault_scope.BATCH_MODEL (#431)
#
# The owner's value comes from a real config file in a real vault (#691), not
# from a module injected under the name `vault_scope`.
# ---------------------------------------------------------------------------

_LANE_B_STDOUT = '{"missing_links": [], "orphans": [], "index_drift": []}'


def _capture_claude_argv(monkeypatch, captured):
    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        return _sp.CompletedProcess(argv, 0, stdout=_LANE_B_STDOUT, stderr="")

    monkeypatch.setattr(gg.subprocess, "run", fake_run)


def test_run_lane_b_headless_passes_model_to_claude_argv(monkeypatch):
    captured = {}
    _capture_claude_argv(monkeypatch, captured)
    gg.run_lane_b_headless("prompt text", "claude-opus-5")
    assert captured["argv"] == ["claude", "-p", "--model", "claude-opus-5"]


def test_run_lane_b_uses_custom_owner_model(tmp_path, monkeypatch, owner_scope):
    repo = _init_repo(tmp_path)
    note = _src_note(repo, "some note content long enough to send")
    owner_scope(BATCH_MODEL="claude-opus-5")

    captured = {}
    _capture_claude_argv(monkeypatch, captured)
    gg.run_lane_b([note], repo)
    assert captured["argv"] == ["claude", "-p", "--model", "claude-opus-5"]


def test_run_lane_b_falls_back_when_owner_value_absent(
    tmp_path, monkeypatch, owner_scope
):
    repo = _init_repo(tmp_path)
    note = _src_note(repo, "some note content long enough to send")
    owner_scope(TASKS_DIR="custom/tasks")  # a config defining no BATCH_MODEL

    captured = {}
    _capture_claude_argv(monkeypatch, captured)
    gg.run_lane_b([note], repo)
    assert captured["argv"] == ["claude", "-p", "--model", vault_utils.DEFAULT_BATCH_MODEL]
