"""Tests for the entry-replay move fuzz rig (``scripts/entry_replay_move_fuzz.py``).

The real measurement runs by hand against a vault's handoff history. What is
cheap to pin here is that the rig can see what it claims to count: a
candidate identical to the baseline adds nothing, a candidate that accepts
what the baseline refused (or changes an accepted output) is a violation, a
new refusal of a content-right merge is a false refusal, and the content
truth refuses to grade a conflict.
"""

from __future__ import annotations

from collections import Counter
from types import SimpleNamespace

from scripts import entry_replay_backtest as backtest
from scripts import entry_replay_move_fuzz as fuzz

POOL = [
    f"- [[proj-{n}]] {word} the {thing} after the {when} review, then record it"
    for n, (word, thing, when) in enumerate(
        [
            ("ship", "release notes", "Monday"),
            ("audit", "plugin cache", "nightly"),
            ("rebase", "guards branch", "promotion"),
            ("measure", "token diet", "listing"),
            ("draft", "hosting table", "budget"),
            ("close", "parity ticket", "deploy"),
            ("watch", "fleet stall", "scout"),
            ("file", "follow-up issue", "landing"),
            ("verify", "self-replay", "backtest"),
            ("prune", "stale worktrees", "sweep"),
            ("pin", "teeth anchors", "refactor"),
            ("triage", "quarantine queue", "drain"),
            ("re-run", "calibration", "eval"),
            ("export", "transcript", "session"),
            ("rotate", "credential file", "hold"),
            ("tag", "image build", "containerd"),
            ("split", "store-first slice", "PRD"),
            ("score", "verdict script", "replay"),
        ]
    )
]


def _wrapping(module: object, handoff_merge: object) -> SimpleNamespace:
    return SimpleNamespace(
        handoff_merge=handoff_merge,
        RefusalError=module.RefusalError,  # type: ignore[attr-defined]
        _items_alike=module._items_alike,  # type: ignore[attr-defined]
        _MOVE_RATIO=module._MOVE_RATIO,  # type: ignore[attr-defined]
    )


def test_an_identical_candidate_adds_nothing() -> None:
    module = backtest.load_candidate()
    stats, _examples = fuzz.run_fuzz(module, module, POOL, cases=200, seed=3)
    assert stats, "the fuzz ran no case"
    assert {key for _pop, key in stats} <= {"both-accept", "both-refuse"}


def test_a_candidate_that_accepts_what_the_baseline_refused_is_a_violation() -> None:
    module = backtest.load_candidate()

    def accept_everything(base: str, tip: str, origin: str, path: str) -> tuple[str, dict]:
        try:
            return module.handoff_merge(base, tip, origin, path)
        except module.RefusalError:
            return origin, {}

    stats, _examples = fuzz.run_fuzz(
        module, _wrapping(module, accept_everything), POOL, cases=200, seed=3
    )
    assert sum(n for (_pop, key), n in stats.items() if key.startswith("VIOLATION")) > 0


def test_a_new_refusal_of_a_content_right_merge_is_a_false_refusal() -> None:
    module = backtest.load_candidate()

    def refuse_everything(base: str, tip: str, origin: str, path: str) -> tuple[str, dict]:
        raise module.RefusalError("refuse")

    stats, _examples = fuzz.run_fuzz(
        module, _wrapping(module, refuse_everything), POOL, cases=200, seed=3
    )
    assert stats[("no-moves", fuzz.FALSE_REFUSAL)] > 0


def test_truth_content_refuses_to_grade_a_conflict_and_applies_disjoint_changes() -> None:
    base = {section: [] for section in fuzz.SECTIONS}
    base["Open threads"] = [("x", "- x item"), ("y", "- y item")]
    tip = {section: list(items) for section, items in base.items()}
    tip["Open threads"] = [("x", "- x item (session)"), ("y", "- y item")]
    origin = {section: list(items) for section, items in base.items()}
    origin["Open threads"] = [("y", "- y item")]
    assert fuzz.truth_content(base, tip, origin, {"x": {"edit"}}, {"x": {"delete"}}) is None

    origin["Open threads"] = [("x", "- x item"), ("y", "- y item (origin)")]
    assert fuzz.truth_content(base, tip, origin, {"x": {"edit"}}, {"y": {"edit"}}) == Counter(
        {"- x item (session)": 1, "- y item (origin)": 1}
    )
