"""Tests for mr_status: one compact MR summary, honest about what it could not read."""

from __future__ import annotations

import mr_status


def mr(**extra) -> dict:
    return {
        "iid": 7,
        "title": "feat: thing",
        "state": "opened",
        "draft": False,
        "source_branch": "feat/thing",
        "target_branch": "dev",
        "has_conflicts": False,
        "detailed_merge_status": "mergeable",
        "head_pipeline": {"id": 99, "status": "success"},
        "web_url": "https://gitlab.com/group/project/-/merge_requests/7",
        **extra,
    }


def note(resolvable: bool, resolved: bool) -> dict:
    return {"resolvable": resolvable, "resolved": resolved}


def discussion(*notes: dict, individual: bool = False) -> dict:
    return {"individual_note": individual, "notes": list(notes)}


APPROVALS = {
    "approvals_required": 1,
    "approvals_left": 1,
    "approved_by": [],
}


class TestUnresolved:
    def test_counts_only_resolvable_unresolved_threads(self):
        discussions = [
            discussion(note(True, False)),
            discussion(note(True, True)),
            discussion(note(False, False), individual=True),
            discussion(note(False, False)),
        ]
        assert mr_status.count_unresolved(discussions) == 1

    def test_thread_with_any_unresolved_resolvable_note_counts(self):
        assert mr_status.count_unresolved([discussion(note(True, True), note(True, False))]) == 1


class TestStatus:
    def test_prints_the_blockers_a_merge_decision_needs(self, glab):
        glab.route(
            merge_requests__7__approvals={"json": APPROVALS},
            merge_requests__7__discussions={
                "json": [discussion(note(True, False)), discussion(note(True, True))]
            },
            merge_requests__7={"json": mr(detailed_merge_status="not_approved")},
        )
        result = glab.run("mr_status.py", "7")
        assert result.returncode == 0, result.stderr
        out = result.stdout
        assert "!7" in out and "feat/thing" in out and "dev" in out
        assert "opened" in out
        assert "pipeline: success" in out
        assert "approvals: 0 of 1" in out
        assert "unresolved threads: 1" in out
        assert "not_approved" in out

    def test_flags_draft_and_conflicts(self, glab):
        glab.route(
            merge_requests__7__approvals={"json": APPROVALS},
            merge_requests__7__discussions={"json": []},
            merge_requests__7={"json": mr(draft=True, has_conflicts=True)},
        )
        out = glab.run("mr_status.py", "7").stdout
        assert "draft" in out
        assert "conflicts" in out

    def test_lists_who_approved(self, glab):
        glab.route(
            merge_requests__7__approvals={
                "json": {
                    "approvals_required": 1,
                    "approvals_left": 0,
                    "approved_by": [{"user": {"username": "grant"}}],
                }
            },
            merge_requests__7__discussions={"json": []},
            merge_requests__7={"json": mr()},
        )
        out = glab.run("mr_status.py", "7").stdout
        assert "approvals: 1 of 1" in out
        assert "grant" in out

    def test_missing_pipeline_is_stated(self, glab):
        glab.route(
            merge_requests__7__approvals={"json": APPROVALS},
            merge_requests__7__discussions={"json": []},
            merge_requests__7={"json": mr(head_pipeline=None)},
        )
        assert "pipeline: none" in glab.run("mr_status.py", "7").stdout

    def test_unreadable_approvals_say_unavailable_not_zero(self, glab):
        glab.route(
            merge_requests__7__approvals={"exit": 1},
            merge_requests__7__discussions={"json": []},
            merge_requests__7={"json": mr()},
        )
        result = glab.run("mr_status.py", "7")
        assert result.returncode == 0
        assert "approvals: unavailable" in result.stdout

    def test_unreadable_discussions_say_unavailable_not_zero(self, glab):
        glab.route(
            merge_requests__7__approvals={"json": APPROVALS},
            merge_requests__7__discussions={"exit": 1},
            merge_requests__7={"json": mr()},
        )
        out = glab.run("mr_status.py", "7").stdout
        assert "unresolved threads: unavailable" in out

    def test_unreadable_mr_is_indeterminate(self, glab):
        glab.route(merge_requests__7={"exit": 1})
        result = glab.run("mr_status.py", "7")
        assert result.returncode == mr_status.INDETERMINATE
        assert "cannot read" in result.stdout


class TestResolution:
    def test_default_finds_the_open_mr_for_the_current_branch(self, glab):
        glab.route(
            merge_requests__7__approvals={"json": APPROVALS},
            merge_requests__7__discussions={"json": []},
            merge_requests__7={"json": mr()},
            **{"merge_requests?source_branch": {"json": [{"iid": 7}]}},
        )
        result = glab.run("mr_status.py")
        assert result.returncode == 0, result.stderr
        assert "!7" in result.stdout
        assert any("source_branch=feat%2Fthing" in " ".join(c) for c in glab.calls())
        assert any("state=opened" in " ".join(c) for c in glab.calls())

    def test_no_open_mr_for_branch_is_indeterminate(self, glab):
        glab.route(**{"merge_requests?source_branch": {"json": []}})
        result = glab.run("mr_status.py")
        assert result.returncode == mr_status.INDETERMINATE
        assert "no open MR" in result.stdout
