"""``graph_cli.main`` flag dispatch (issue #932).

Every top-level flag must reach its own handler and no other. The graph builder
and each handler are replaced with stubs that return a distinct sentinel, so a
mis-wired ``elif`` (for example ``--gaps`` falling through to ``--stats``)
surfaces as the wrong sentinel on stdout rather than passing on a coincidence.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

pytest.importorskip("graphmark")

ENGINE = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(ENGINE))

_spec = importlib.util.spec_from_file_location("graph_cli_main_dispatch", ENGINE / "graph_cli.py")
gc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gc)


@pytest.fixture
def stubbed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> SimpleNamespace:
    """Replace the graph builder and every handler with a named sentinel."""
    graph = SimpleNamespace(
        nodes={"a.md": object()},
        unresolved={"b.md": ["Ghost"], "a.md": ["Nowhere"]},
    )
    calls: list[tuple] = []

    monkeypatch.setattr(gc, "build", lambda root: (graph, "cfg"))
    for name in ("orphans", "hubs", "clusters", "bridges", "neighborhood", "stats"):
        def _stub(*args, _name=name, **kwargs):
            calls.append((_name, args))
            return {"branch": _name}

        monkeypatch.setattr(gc, name, _stub)
    monkeypatch.setattr(
        gc,
        "diagnose",
        lambda g, display, suggest=5: SimpleNamespace(reason="missing", candidates=[display]),
    )
    monkeypatch.setattr(gc, "vector_similar_fn", lambda root: (lambda rel, k: []))
    monkeypatch.setattr(gc, "active_dismissed_sigs", lambda root: set())
    monkeypatch.setattr(gc, "siloed_notes", lambda g: [])

    # main() imports ragmark.gaps lazily; a stand-in keeps this test independent of ragmark.
    fake_gaps = ModuleType("ragmark.gaps")
    fake_gaps.GAPS_DEFAULT_HUB_DEGREE = 8
    fake_gaps.GAPS_DEFAULT_K = 5
    fake_gaps.GAPS_DEFAULT_MAX_SCORE = 0.92
    fake_gaps.GAPS_DEFAULT_THRESHOLD = 0.6
    fake_gaps.rank_pairs = lambda *a, **k: [("a.md", "z.md", 0.7)]
    fake_pkg = ModuleType("ragmark")
    fake_pkg.gaps = fake_gaps
    monkeypatch.setitem(sys.modules, "ragmark", fake_pkg)
    monkeypatch.setitem(sys.modules, "ragmark.gaps", fake_gaps)
    return SimpleNamespace(root=tmp_path, graph=graph, calls=calls)


def _run(stubbed: SimpleNamespace, capsys: pytest.CaptureFixture, *argv: str):
    rc = gc.main(["--vault-root", str(stubbed.root), *argv])
    assert rc == 0
    return json.loads(capsys.readouterr().out)


@pytest.mark.parametrize(
    ("argv", "branch"),
    [
        (["--orphans"], "orphans"),
        (["--hubs"], "hubs"),
        (["--hubs", "3"], "hubs"),
        (["--clusters"], "clusters"),
        (["--bridges"], "bridges"),
        (["--neighborhood", "a.md"], "neighborhood"),
        (["--stats"], "stats"),
        ([], "stats"),
    ],
)
def test_flag_reaches_its_own_handler(stubbed, capsys, argv, branch) -> None:
    assert _run(stubbed, capsys, *argv) == {"branch": branch}
    assert [name for name, _ in stubbed.calls] == [branch]


def test_hubs_count_is_forwarded(stubbed, capsys) -> None:
    _run(stubbed, capsys, "--hubs", "3")
    assert stubbed.calls == [("hubs", (stubbed.graph, 3))]


def test_neighborhood_depth_is_forwarded(stubbed, capsys) -> None:
    _run(stubbed, capsys, "--neighborhood", "a.md", "--depth", "2")
    assert stubbed.calls == [("neighborhood", (stubbed.graph, "a.md", 2))]


def test_unresolved_emits_sorted_graph_unresolved(stubbed, capsys) -> None:
    out = _run(stubbed, capsys, "--unresolved")
    assert out == {"a.md": ["Nowhere"], "b.md": ["Ghost"]}
    assert list(out) == ["a.md", "b.md"]
    assert stubbed.calls == []


def test_diagnose_broken_emits_reason_entries(stubbed, capsys) -> None:
    out = _run(stubbed, capsys, "--diagnose-broken")
    assert out == {
        "a.md": [{"display": "Nowhere", "reason": "missing", "candidates": ["Nowhere"]}],
        "b.md": [{"display": "Ghost", "reason": "missing", "candidates": ["Ghost"]}],
    }
    assert stubbed.calls == []


def test_gaps_does_not_fall_through_to_stats(stubbed, capsys) -> None:
    out = _run(stubbed, capsys, "--gaps")
    assert out == [{"a": "a.md", "b": "z.md", "score": 0.7, "sig": gc.weaklink_sig("a.md", "z.md")}]
    assert stubbed.calls == []


def test_dismiss_short_circuits_before_the_graph_is_built(
    stubbed, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorded: list[tuple] = []
    monkeypatch.setattr(gc, "record_dismissal", lambda root, a, b: recorded.append((root, a, b)))
    monkeypatch.setattr(gc, "build", lambda root: pytest.fail("dismiss must not build the graph"))
    out = _run(stubbed, capsys, "--dismiss", "a.md", "z.md")
    assert out == {"dismissed": gc.weaklink_sig("a.md", "z.md")}
    assert recorded == [(stubbed.root.resolve(), "a.md", "z.md")]


# --- teeth-pass gap closers (#932 acceptance criterion 2 and handler wiring) ---


def test_vault_root_falls_back_to_env(
    stubbed, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[bool] = []

    def _from_env():
        seen.append(True)
        return stubbed.root

    monkeypatch.setattr(gc.vault_utils, "find_vault_root_from_env", _from_env)
    assert gc.main(["--stats"]) == 0
    assert seen == [True]
    assert json.loads(capsys.readouterr().out) == {"branch": "stats"}


def test_missing_vault_root_is_rejected(
    stubbed, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gc.vault_utils, "find_vault_root_from_env", lambda: None)
    assert gc.main(["--stats"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "vault root not found" in captured.err
    assert stubbed.calls == []


def test_diagnose_broken_orders_notes_and_forwards_suggest(
    stubbed, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple] = []

    def _diag(g, display, suggest=5):
        seen.append((display, suggest))
        return SimpleNamespace(reason="missing", candidates=[])

    monkeypatch.setattr(gc, "diagnose", _diag)
    out = _run(stubbed, capsys, "--diagnose-broken", "--suggest", "2")
    assert list(out) == ["a.md", "b.md"]
    assert seen == [("Nowhere", 2), ("Ghost", 2)]


def test_orphans_receives_cfg(stubbed, capsys) -> None:
    _run(stubbed, capsys, "--orphans")
    assert stubbed.calls == [("orphans", (stubbed.graph, "cfg"))]


def test_hubs_zero_is_not_treated_as_absent(stubbed, capsys) -> None:
    _run(stubbed, capsys, "--hubs", "0")
    assert stubbed.calls == [("hubs", (stubbed.graph, 0))]


@pytest.fixture
def ranked(stubbed, monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Capture rank_pairs kwargs; return many pairs so --top is observable."""
    captured: list[dict] = []

    def _rank(graph, similar_fn, **kwargs):
        captured.append({"similar_fn": similar_fn, **kwargs})
        return [("a.md", f"z{i}.md", 0.7) for i in range(5)]

    monkeypatch.setattr(sys.modules["ragmark.gaps"], "rank_pairs", _rank)
    return captured


def test_gaps_defaults_come_from_ragmark_constants(stubbed, capsys, ranked) -> None:
    out = _run(stubbed, capsys, "--gaps")
    kw = ranked[0]
    assert kw["targets"] == ["a.md"]
    assert (kw["threshold"], kw["k"], kw["max_score"], kw["hub_degree"]) == (0.6, 5, 0.92, 8)
    assert len(out) == 5


def test_gaps_note_restricts_targets(stubbed, capsys, ranked) -> None:
    _run(stubbed, capsys, "--gaps", "--note", "only.md")
    assert ranked[0]["targets"] == ["only.md"]


def test_gaps_near_bridges_uses_siloed_notes(
    stubbed, capsys, ranked, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gc, "siloed_notes", lambda g: ["s1.md", "s2.md"])
    _run(stubbed, capsys, "--gaps", "--near-bridges")
    assert ranked[0]["targets"] == ["s1.md", "s2.md"]


def test_gaps_note_wins_over_near_bridges(
    stubbed, capsys, ranked, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gc, "siloed_notes", lambda g: ["s1.md"])
    _run(stubbed, capsys, "--gaps", "--note", "n.md", "--near-bridges")
    assert ranked[0]["targets"] == ["n.md"]


def test_gaps_top_threshold_and_tuning_are_forwarded(stubbed, capsys, ranked) -> None:
    out = _run(
        stubbed, capsys, "--gaps", "--top", "2", "--threshold", "0.5",
        "--max", "0.8", "-k", "3", "--hub-degree", "4",
    )
    assert len(out) == 2
    kw = ranked[0]
    assert (kw["threshold"], kw["k"], kw["max_score"], kw["hub_degree"]) == (0.5, 3, 0.8, 4)


def test_gaps_filters_transient_targets_and_neighbours(
    stubbed, capsys, ranked, monkeypatch: pytest.MonkeyPatch
) -> None:
    prefix = tuple(gc.TRANSIENT_PREFIXES)[0]
    stubbed.graph.nodes = {"keep.md": object(), prefix + "x.md": object()}
    monkeypatch.setattr(
        gc, "vector_similar_fn",
        lambda root: (lambda rel, k: [("ok.md", 0.7), (prefix + "y.md", 0.9)]),
    )
    _run(stubbed, capsys, "--gaps")
    kw = ranked[0]
    assert kw["targets"] == ["keep.md"]
    assert kw["similar_fn"]("keep.md", 5) == [("ok.md", 0.7)]
