"""Targeted sweep: the gardener spends part of its budget on notes that actually
have broken links, instead of waiting for the round-robin cursor to reach them.

Brokenness comes from graphmark via the graph_cli seam, so the gardener inherits its
resolution rules ([[#anchor]], .base targets, trailing .md) rather than approximating
them a second time. The scan runs inside a session hook, so every failure path must be
soft — a broken scan degrades to the ordinary sweep, never to a broken hook.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

# Load the engine by path, the way every other module in this suite does. The
# vault-side shim this file arrived with (sys.path + ".claude/scripts") only
# resolves in the vendored layout, so running this file on its own failed to
# import; in a full run it happened to work off another module's sys.path edit.
_spec = importlib.util.spec_from_file_location(
    "graph_gardener", Path(__file__).resolve().parent.parent / "engine" / "graph_gardener.py"
)
gg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gg)


class TestNotesWithBrokenLinks:
    def test_returns_sorted_rel_paths_from_the_seam(self, tmp_path, monkeypatch):
        (tmp_path / ".claude" / "scripts").mkdir(parents=True)
        (tmp_path / ".claude" / "scripts" / "graph_cli.py").write_text("#\n")
        payload = json.dumps(
            {
                "z/late.md": [{"display": "X", "reason": "missing", "candidates": []}],
                "a/early.md": [{"display": "Y", "reason": "missing", "candidates": []}],
            }
        )

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
            broken_by_note={
                "brain/index.md": {
                    "Nowhere At All": {"reason": "missing", "candidates": []}
                }
            },
        )
        assert any("Nowhere At All" in p for p in res.proposals)

    def test_an_ambiguous_link_is_worded_as_ambiguous(self, tmp_path):
        # The distinction the old surface could not draw: this link matched THREE notes, so
        # "consider creating or removing" would be wrong advice.
        v = self._vault(tmp_path)
        note = v / "brain" / "index.md"
        note.write_text("See [[Tasks]].\n", encoding="utf-8")
        res = gg.run_lane_a(
            [note], v, dry_run=True,
            broken_by_note={
                "brain/index.md": {
                    "Tasks": {
                        "reason": "ambiguous",
                        "candidates": ["work/Tasks.md", "personal/Tasks.md"],
                    }
                }
            },
        )
        assert len(res.proposals) == 1
        assert "ambiguous" in res.proposals[0]
        assert "work/Tasks.md" in res.proposals[0]
        assert "creating or removing" not in res.proposals[0]

    def test_suggestions_are_shown_as_paths(self, tmp_path):
        # Paths, not stems: four different Index.md files render identically as stems, which is
        # what made the old "did you mean Index, Index, Index, Index?" unactionable.
        v = self._vault(tmp_path)
        note = v / "brain" / "index.md"
        note.write_text("See [[Personal Index]].\n", encoding="utf-8")
        res = gg.run_lane_a(
            [note], v, dry_run=True,
            broken_by_note={
                "brain/index.md": {
                    "Personal Index": {
                        "reason": "missing",
                        "candidates": ["personal/Index.md"],
                    }
                }
            },
        )
        assert "did you mean" in res.proposals[0]
        assert "personal/Index.md" in res.proposals[0]

    def test_a_failed_scan_proposes_nothing(self, tmp_path):
        # None means "scan unavailable". Lane A's own catalog has a different scope than
        # graphmark's graph, so deciding for itself here answered a different question and
        # produced false proposals. Silence beats confident wrong advice; repair still runs.
        v = self._vault(tmp_path)
        note = v / "brain" / "index.md"
        note.write_text("See [[Nowhere At All]].\n", encoding="utf-8")
        res = gg.run_lane_a([note], v, dry_run=True, broken_by_note=None)
        assert res.proposals == []

    def test_auto_repair_still_runs_without_a_scan(self, tmp_path):
        # Skipping proposals must not skip the lane: a cosmetic repair is not a brokenness call.
        v = self._vault(tmp_path)
        (v / "brain" / "North Star.md").write_text("# n\n", encoding="utf-8")
        note = v / "brain" / "index.md"
        note.write_text("See [[north star]].\n", encoding="utf-8")
        res = gg.run_lane_a([note], v, dry_run=False, broken_by_note=None)
        assert res.applied
        assert "[[North Star]]" in note.read_text(encoding="utf-8")

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
    def test_shapes_the_payload_by_display(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            gg, "_graphmark_broken",
            lambda vr: {
                "a.md": [
                    {"display": "X", "reason": "missing", "candidates": ["c.md"]},
                    {"display": "Y", "reason": "ambiguous", "candidates": ["d.md", "e.md"]},
                ],
                "b.md": [{"display": "Z", "reason": "missing", "candidates": []}],
            },
        )
        assert gg.broken_links_by_note(tmp_path) == {
            "a.md": {
                "X": {"reason": "missing", "candidates": ["c.md"]},
                "Y": {"reason": "ambiguous", "candidates": ["d.md", "e.md"]},
            },
            "b.md": {"Z": {"reason": "missing", "candidates": []}},
        }

    def test_malformed_entries_are_dropped_not_fatal(self, tmp_path, monkeypatch):
        # The payload crosses a subprocess boundary inside a session hook; a shape surprise
        # must degrade, never raise.
        monkeypatch.setattr(
            gg, "_graphmark_broken",
            lambda vr: {
                "a.md": ["not a dict", {"no_display": 1}, {"display": "X"}],
                "b.md": "not a list",
            },
        )
        assert gg.broken_links_by_note(tmp_path) == {
            "a.md": {"X": {"reason": "missing", "candidates": []}}
        }

    def test_failed_scan_returns_none_not_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gg, "_graphmark_broken", lambda vr: None)
        assert gg.broken_links_by_note(tmp_path) is None


class TestTargetedSourceSurvivesTheUnchangedFilter:
    """A note whose link broke long ago never changes again, so the
    unchanged-since-gardened filter would suppress it forever."""

    def _note(self, tmp_path, rel, body="# n\n\nbody\n"):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
        return p

    def test_targeted_note_is_kept_even_when_unchanged(self, tmp_path, monkeypatch):
        p = self._note(tmp_path, "thinking/rotted.md")
        gardened = {"thinking/rotted.md": gg.content_hash(p)}  # gardened, never changed

        monkeypatch.setattr(gg, "commit_range_changed_notes", lambda *a, **k: [])
        monkeypatch.setattr(gg, "all_in_scope_notes", lambda vr: [])
        monkeypatch.setattr(gg, "notes_with_broken_links", lambda vr: ["thinking/rotted.md"])
        monkeypatch.setattr(gg, "settled_notes", lambda notes, vr: list(notes))

        notes, _ = gg.collect_touched_notes(tmp_path, {"gardened": gardened})
        assert [str(x.relative_to(tmp_path)) for x in notes] == ["thinking/rotted.md"]

    def test_trickle_notes_are_still_filtered_when_unchanged(self, tmp_path, monkeypatch):
        # The exemption must be scoped to the targeted source; the cost control that
        # keeps the round-robin sweep cheap has to stay in force.
        p = self._note(tmp_path, "brain/settled.md")
        gardened = {"brain/settled.md": gg.content_hash(p)}

        monkeypatch.setattr(gg, "commit_range_changed_notes", lambda *a, **k: [])
        monkeypatch.setattr(gg, "all_in_scope_notes", lambda vr: ["brain/settled.md"])
        monkeypatch.setattr(gg, "notes_with_broken_links", lambda vr: [])
        monkeypatch.setattr(gg, "settled_notes", lambda notes, vr: list(notes))

        notes, _ = gg.collect_touched_notes(tmp_path, {"gardened": gardened})
        assert notes == []

    def test_targeted_notes_are_still_settle_filtered(self, tmp_path, monkeypatch):
        # Exempt from the unchanged filter, NOT from the race guard — a note being
        # edited right now must still be left alone.
        self._note(tmp_path, "thinking/rotted.md")
        monkeypatch.setattr(gg, "commit_range_changed_notes", lambda *a, **k: [])
        monkeypatch.setattr(gg, "all_in_scope_notes", lambda vr: [])
        monkeypatch.setattr(gg, "notes_with_broken_links", lambda vr: ["thinking/rotted.md"])
        monkeypatch.setattr(gg, "settled_notes", lambda notes, vr: [])  # too fresh

        notes, _ = gg.collect_touched_notes(tmp_path, {})
        assert notes == []
