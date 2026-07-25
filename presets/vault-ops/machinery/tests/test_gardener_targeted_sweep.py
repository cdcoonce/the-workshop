"""Targeted sweep: the gardener spends part of its budget on notes that actually
have broken links, instead of waiting for the round-robin cursor to reach them.

Brokenness comes from graphmark via the graph_cli seam, so the gardener inherits its
resolution rules ([[#anchor]], .base targets, trailing .md) rather than approximating
them a second time. The scan runs inside a session hook, so every failure path must be
soft — a broken scan degrades to the ordinary sweep, never to a broken hook.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / ".claude" / "scripts"))

import graph_gardener as gg


class TestNotesWithBrokenLinks:
    def test_returns_sorted_rel_paths_from_the_seam(self, tmp_path, monkeypatch):
        (tmp_path / ".claude" / "scripts").mkdir(parents=True)
        (tmp_path / ".claude" / "scripts" / "graph_cli.py").write_text("#\n")
        payload = json.dumps({"z/late.md": ["[[X]]"], "a/early.md": ["[[Y]]"]})

        def fake_run(cmd, **kw):
            return subprocess.CompletedProcess(cmd, 0, stdout=payload, stderr="")

        monkeypatch.setattr(gg.subprocess, "run", fake_run)
        assert gg.notes_with_broken_links(tmp_path) == ["a/early.md", "z/late.md"]

    def test_missing_seam_script_returns_empty(self, tmp_path):
        assert gg.notes_with_broken_links(tmp_path) == []

    def _with_seam(self, tmp_path):
        (tmp_path / ".claude" / "scripts").mkdir(parents=True)
        (tmp_path / ".claude" / "scripts" / "graph_cli.py").write_text("#\n")

    def test_nonzero_exit_returns_empty(self, tmp_path, monkeypatch):
        self._with_seam(tmp_path)
        monkeypatch.setattr(
            gg.subprocess, "run",
            lambda cmd, **kw: subprocess.CompletedProcess(cmd, 2, stdout="", stderr="boom"),
        )
        assert gg.notes_with_broken_links(tmp_path) == []

    def test_malformed_json_returns_empty(self, tmp_path, monkeypatch):
        self._with_seam(tmp_path)
        monkeypatch.setattr(
            gg.subprocess, "run",
            lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout="{not json", stderr=""),
        )
        assert gg.notes_with_broken_links(tmp_path) == []

    def test_non_dict_payload_returns_empty(self, tmp_path, monkeypatch):
        self._with_seam(tmp_path)
        monkeypatch.setattr(
            gg.subprocess, "run",
            lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout="[1,2]", stderr=""),
        )
        assert gg.notes_with_broken_links(tmp_path) == []

    def test_timeout_returns_empty(self, tmp_path, monkeypatch):
        self._with_seam(tmp_path)

        def boom(cmd, **kw):
            raise subprocess.TimeoutExpired(cmd, 1)

        monkeypatch.setattr(gg.subprocess, "run", boom)
        assert gg.notes_with_broken_links(tmp_path) == []

    def test_missing_uv_returns_empty(self, tmp_path, monkeypatch):
        self._with_seam(tmp_path)

        def boom(cmd, **kw):
            raise FileNotFoundError("uv")

        monkeypatch.setattr(gg.subprocess, "run", boom)
        assert gg.notes_with_broken_links(tmp_path) == []


class TestTargetedSourceFeedsTheSweep:
    def test_broken_notes_are_gardened_without_waiting_for_the_cursor(
        self, tmp_path, monkeypatch
    ):
        # A note far past the cursor alphabetically would normally wait many runs.
        for rel in ("brain/aaa.md", "thinking/zzz-broken.md"):
            p = tmp_path / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("# note\n\nbody text\n", encoding="utf-8")

        monkeypatch.setattr(gg, "commit_range_changed_notes", lambda *a, **k: [])
        monkeypatch.setattr(gg, "all_in_scope_notes", lambda vr: ["brain/aaa.md"])
        monkeypatch.setattr(gg, "notes_with_broken_links", lambda vr: ["thinking/zzz-broken.md"])
        monkeypatch.setattr(gg, "settled_notes", lambda notes, vr: list(notes))

        notes, _ = gg.collect_touched_notes(tmp_path, {})
        rels = {str(p.relative_to(tmp_path)) for p in notes}
        assert "thinking/zzz-broken.md" in rels

    def test_round_robin_trickle_is_preserved(self, tmp_path, monkeypatch):
        # The targeted source must ADD to the sweep, not replace it — other lanes
        # (index drift, orphans, people profiles) rely on eventual full coverage.
        for rel in ("brain/aaa.md", "thinking/zzz-broken.md"):
            p = tmp_path / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("# note\n\nbody\n", encoding="utf-8")

        monkeypatch.setattr(gg, "commit_range_changed_notes", lambda *a, **k: [])
        monkeypatch.setattr(gg, "all_in_scope_notes", lambda vr: ["brain/aaa.md"])
        monkeypatch.setattr(gg, "notes_with_broken_links", lambda vr: ["thinking/zzz-broken.md"])
        monkeypatch.setattr(gg, "settled_notes", lambda notes, vr: list(notes))

        notes, _ = gg.collect_touched_notes(tmp_path, {})
        rels = {str(p.relative_to(tmp_path)) for p in notes}
        assert "brain/aaa.md" in rels

    def test_a_failing_scan_degrades_to_the_ordinary_sweep(self, tmp_path, monkeypatch):
        p = tmp_path / "brain" / "aaa.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# note\n\nbody\n", encoding="utf-8")

        monkeypatch.setattr(gg, "commit_range_changed_notes", lambda *a, **k: [])
        monkeypatch.setattr(gg, "all_in_scope_notes", lambda vr: ["brain/aaa.md"])
        monkeypatch.setattr(gg, "notes_with_broken_links", lambda vr: [])  # scan failed
        monkeypatch.setattr(gg, "settled_notes", lambda notes, vr: list(notes))

        notes, _ = gg.collect_touched_notes(tmp_path, {})
        assert {str(p.relative_to(tmp_path)) for p in notes} == {"brain/aaa.md"}

    def test_targeted_source_is_capped(self, tmp_path, monkeypatch):
        many = []
        for i in range(gg.BROKEN_BATCH + 15):
            rel = f"thinking/n{i:03d}.md"
            p = tmp_path / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("# n\n\nbody\n", encoding="utf-8")
            many.append(rel)

        monkeypatch.setattr(gg, "commit_range_changed_notes", lambda *a, **k: [])
        monkeypatch.setattr(gg, "all_in_scope_notes", lambda vr: [])
        monkeypatch.setattr(gg, "notes_with_broken_links", lambda vr: many)
        monkeypatch.setattr(gg, "settled_notes", lambda notes, vr: list(notes))

        notes, _ = gg.collect_touched_notes(tmp_path, {})
        assert len(notes) <= gg.BROKEN_BATCH

    def test_override_scope_skips_the_targeted_source(self, tmp_path, monkeypatch):
        p = tmp_path / "brain" / "only.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# only\n\nbody\n", encoding="utf-8")
        called = {"n": 0}

        def counted(vr):
            called["n"] += 1
            return ["thinking/other.md"]

        monkeypatch.setattr(gg, "notes_with_broken_links", counted)
        monkeypatch.setattr(gg, "_is_in_scope", lambda p, vr: True)

        notes, _ = gg.collect_touched_notes(tmp_path, {}, override=[p])
        assert [x.name for x in notes] == ["only.md"]
        assert called["n"] == 0  # explicit --notes must not trigger a vault scan


class TestLaneAConsultsGraphmark:
    """graphmark decides what is broken; Lane A keeps repair and suggestion."""

    def _vault(self, tmp_path):
        (tmp_path / "brain").mkdir(parents=True, exist_ok=True)
        return tmp_path

    def test_a_display_graphmark_does_not_report_is_not_proposed(self, tmp_path):
        v = self._vault(tmp_path)
        note = v / "brain" / "index.md"
        note.write_text("See [[Chart.base]] for the board.\n", encoding="utf-8")
        # graphmark resolves or scopes out every link in this note.
        res = gg.run_lane_a([note], v, dry_run=True, broken_by_note={})
        assert res.proposals == []

    def test_a_display_graphmark_reports_is_proposed(self, tmp_path):
        v = self._vault(tmp_path)
        note = v / "brain" / "index.md"
        note.write_text("See [[Nowhere At All]].\n", encoding="utf-8")
        res = gg.run_lane_a(
            [note], v, dry_run=True,
            broken_by_note={"brain/index.md": {"Nowhere At All"}},
        )
        assert any("Nowhere At All" in p for p in res.proposals)

    def test_a_failed_scan_falls_back_to_self_contained_behavior(self, tmp_path):
        v = self._vault(tmp_path)
        note = v / "brain" / "index.md"
        note.write_text("See [[Nowhere At All]].\n", encoding="utf-8")
        # None means "scan unavailable" — must NOT be read as "nothing is broken".
        res = gg.run_lane_a([note], v, dry_run=True, broken_by_note=None)
        assert any("Nowhere At All" in p for p in res.proposals)

    def test_empty_map_is_not_the_same_as_a_failed_scan(self, tmp_path):
        v = self._vault(tmp_path)
        note = v / "brain" / "index.md"
        note.write_text("See [[Nowhere At All]].\n", encoding="utf-8")
        silent = gg.run_lane_a([note], v, dry_run=True, broken_by_note={})
        fallback = gg.run_lane_a([note], v, dry_run=True, broken_by_note=None)
        assert silent.proposals == []
        assert fallback.proposals != []

    def test_cosmetic_auto_repair_still_fires_when_graphmark_says_fine(self, tmp_path):
        # THE regression guard: [[ethan courtman]] resolves fine, so graphmark never
        # reports it — but Lane A must still snap the display to the note's real title.
        v = self._vault(tmp_path)
        (v / "brain" / "Ethan Courtman.md").write_text("# Ethan\n", encoding="utf-8")
        note = v / "brain" / "index.md"
        note.write_text("Ping [[ethan courtman]] about it.\n", encoding="utf-8")

        res = gg.run_lane_a([note], v, dry_run=False, broken_by_note={})
        assert res.applied, "cosmetic repair must not be gated by the brokenness map"
        assert "[[Ethan Courtman]]" in note.read_text(encoding="utf-8")


class TestBrokenLinksByNote:
    def test_shapes_the_payload_into_sets(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            gg, "_graphmark_unresolved",
            lambda vr: {"a.md": ["[[X]]", "[[Y]]"], "b.md": ["[[Z]]"]},
        )
        assert gg.broken_links_by_note(tmp_path) == {
            "a.md": {"[[X]]", "[[Y]]"}, "b.md": {"[[Z]]"}
        }

    def test_failed_scan_returns_none_not_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gg, "_graphmark_unresolved", lambda vr: None)
        assert gg.broken_links_by_note(tmp_path) is None
