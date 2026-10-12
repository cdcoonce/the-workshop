"""Characterization of the ``--gaps`` handler in ``graph_cli.main`` and its
``--dismiss`` companion.

The handler had no test of its own: only ``vector_similar_fn`` (the reader it
is fed) is pinned elsewhere. These tests pin what the CLI **emits** for given
inputs, the JSON ``/connect`` and ``/garden`` read, so that moving the ranking
off graphmark's ``gaps()`` onto ``ragmark.gaps.rank_pairs`` has a before/after
harness. They are characterization tests: where today's output is surprising
the test says so and pins it anyway. A pin records what the code does today; it
is not an endorsement, and the owner of a deliberate behavior change is meant
to edit the pin knowingly.

What keeps them behavioral rather than incidental:

* The similarity source is the one seam. The ``similarity`` fixture replaces
  ``graph_cli.vector_similar_fn`` with a deterministic fake reader, so no
  Ragmark index, embedding model or network is involved. If the handler ever
  stops asking that function for its reader, that fixture is the only place to
  re-point.
* Assertions read parsed stdout. Nothing here asserts which graphmark (or
  Ragmark) function ranked the pairs.
* Every flag test uses a fixture on which the flag's effect is observable, and
  compares against the unflagged run, so a handler that ignored the flag turns
  the test red instead of passing on a coincidence.
* The fake reader, like a real index, returns each note's top ``k`` neighbours
  by score. Neighbour lists are directed: a pair can be listed by one side only,
  which is what real top-k truncation produces and what makes ``-k``,
  ``--note`` and ``--near-bridges`` observable.

The band, hub and ``k`` defaults (0.6-0.92 inclusive, hub degree 40, ``k`` 8)
are read below from graphmark's published ``GAPS_DEFAULT_*`` constants.
``graph_cli`` itself takes them from ``ragmark.gaps`` since the migration. The
two sets are equal today, so a wheel whose defaults drifted from graphmark's
turns the tests that sit on those edges red.
"""

from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path

import pytest

graphmark = pytest.importorskip("graphmark")

# Attribute reads, not ``from graphmark import ...``: the smoke test's machinery
# check treats a column-0 ``from <module> import`` as an engine-file reference.
GAPS_DEFAULT_HUB_DEGREE = graphmark.GAPS_DEFAULT_HUB_DEGREE
GAPS_DEFAULT_K = graphmark.GAPS_DEFAULT_K
GAPS_DEFAULT_MAX_SCORE = graphmark.GAPS_DEFAULT_MAX_SCORE
GAPS_DEFAULT_THRESHOLD = graphmark.GAPS_DEFAULT_THRESHOLD
siloed_notes = graphmark.siloed_notes
weaklink_sig = graphmark.weaklink_sig

ENGINE = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(ENGINE))

_spec = importlib.util.spec_from_file_location("graph_cli", ENGINE / "graph_cli.py")
gc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gc)

# Ten notes in nine folders. Basenames are unique so a bare ``[[wikilink]]``
# resolves to exactly one of them.
ALPHA = "brain/alpha.md"
BETA = "brain/beta.md"
GAMMA = "work/gamma.md"
DELTA = "work/delta.md"
EPSILON = "personal/epsilon.md"
ZETA = "org/zeta.md"
ETA = "reference/eta.md"
KAPPA = "reference/kappa.md"
THETA = "thinking/theta.md"
IOTA = "perf/iota.md"
NOTES = (ALPHA, BETA, GAMMA, DELTA, EPSILON, ZETA, ETA, KAPPA, THETA, IOTA)

# Twelve cross-folder pairs, best first, scored 0.90 down to 0.68 in steps of
# 0.02 (all inside the default band, none sharing a folder).
RANKED_PAIRS = [
    (ALPHA, GAMMA),
    (BETA, DELTA),
    (EPSILON, ZETA),
    (ETA, THETA),
    (IOTA, KAPPA),
    (ALPHA, DELTA),
    (BETA, EPSILON),
    (GAMMA, ZETA),
    (DELTA, ETA),
    (EPSILON, THETA),
    (ZETA, IOTA),
    (THETA, KAPPA),
]
RANKED_SCORES = {
    pair: round(0.90 - 0.02 * i, 2) for i, pair in enumerate(RANKED_PAIRS)
}


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


def _write_note(root: Path, rel: str, body: str = "body\n") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    front = ["---", "date: 2026-01-01", 'description: "n"', "tags:", "  - note", "---", ""]
    path.write_text("\n".join(front) + body, encoding="utf-8")
    return path


def make_vault(
    tmp_path: Path,
    links: tuple[tuple[str, str], ...] = (),
    notes: tuple[str, ...] = NOTES,
) -> Path:
    """Write ``notes`` under a fresh root; each ``(src, dst)`` link is a ``[[wikilink]]``."""
    root = tmp_path / "vault"
    root.mkdir(parents=True, exist_ok=True)
    bodies: dict[str, list[str]] = {rel: [] for rel in notes}
    for src, dst in links:
        bodies[src].append(f"see [[{Path(dst).stem}]]")
    for rel, lines in bodies.items():
        _write_note(root, rel, ("\n".join(lines) + "\n") if lines else "body\n")
    return root


@pytest.fixture
def similarity(monkeypatch):
    """Install a deterministic cosine reader behind ``graph_cli.vector_similar_fn``.

    ``pairs`` are symmetric ``{(a, b): score}``; ``directed`` entries
    ``{(origin, other): score}`` appear in ``origin``'s neighbour list only.
    The reader returns the top ``k`` neighbours by score, as an index does, so
    ``k`` truncates *before* any band or link filtering. Equal scores keep the
    order they were declared in: a real index promises no path order for ties.
    """

    def install(pairs=None, directed=None):
        neighbours: dict[str, list[tuple[str, float]]] = {}
        for (a, b), score in (pairs or {}).items():
            neighbours.setdefault(a, []).append((b, score))
            neighbours.setdefault(b, []).append((a, score))
        for (origin, other), score in (directed or {}).items():
            neighbours.setdefault(origin, []).append((other, score))

        def reader(rel, k):
            ranked = sorted(neighbours.get(rel, ()), key=lambda hit: -hit[1])
            return ranked[:k]

        monkeypatch.setattr(gc, "vector_similar_fn", lambda vault_root: reader)

    return install


def run(root: Path, capsys, *flags: str) -> tuple[int, str]:
    rc = gc.main(["--vault-root", str(root), *flags])
    return rc, capsys.readouterr().out


def gaps(root: Path, capsys, *flags: str) -> list[dict]:
    """Run ``--gaps``; require exit 0 and exactly one JSON document on stdout."""
    rc, out = run(root, capsys, "--gaps", *flags)
    assert rc == 0
    assert out.endswith("\n") and out.count("\n") == 1, repr(out)
    return json.loads(out)


def ordered(entries: list[dict]) -> list[frozenset]:
    """Entries as an ordered list of unordered pairs (a/b orientation ignored)."""
    return [frozenset((e["a"], e["b"])) for e in entries]


def pair(a: str, b: str) -> frozenset:
    return frozenset((a, b))


# ---------------------------------------------------------------------------
# 1. The default band
# ---------------------------------------------------------------------------


def test_default_band_is_inclusive_at_both_bounds(tmp_path, capsys, similarity):
    lo, hi = GAPS_DEFAULT_THRESHOLD, GAPS_DEFAULT_MAX_SCORE
    root = make_vault(tmp_path)
    similarity(
        {
            (ALPHA, GAMMA): lo,  # exactly the threshold: kept
            (ALPHA, ZETA): math.nextafter(lo, 0.0),  # one ulp under: dropped
            (BETA, DELTA): hi,  # exactly the max: kept
            (BETA, ETA): math.nextafter(hi, math.inf),  # one ulp over: dropped
            (EPSILON, THETA): (lo + hi) / 2,  # inside: kept
            (IOTA, KAPPA): 0.97,  # near-duplicate: dropped
            (GAMMA, IOTA): 0.30,  # unrelated: dropped
        }
    )

    result = gaps(root, capsys)

    assert ordered(result) == [pair(BETA, DELTA), pair(EPSILON, THETA), pair(ALPHA, GAMMA)]
    assert [e["score"] for e in result] == [hi, round((lo + hi) / 2, 4), lo]


def test_threshold_flag_moves_the_lower_bound(tmp_path, capsys, similarity):
    root = make_vault(tmp_path)
    similarity(
        {
            (ALPHA, GAMMA): 0.50,
            (BETA, DELTA): 0.65,
            (EPSILON, ZETA): 0.79,
            (ETA, THETA): 0.80,
            (IOTA, KAPPA): 0.88,
        }
    )

    default = ordered(gaps(root, capsys))
    raised = ordered(gaps(root, capsys, "--threshold", "0.8"))
    lowered = ordered(gaps(root, capsys, "--threshold", "0.5"))

    assert default == [pair(IOTA, KAPPA), pair(ETA, THETA), pair(EPSILON, ZETA), pair(BETA, DELTA)]
    # 0.8 is inclusive: the pair scoring exactly 0.8 stays, 0.79 goes.
    assert raised == [pair(IOTA, KAPPA), pair(ETA, THETA)]
    # 0.5 is inclusive too, and admits what the default band excludes.
    assert lowered == default + [pair(ALPHA, GAMMA)]


def test_max_flag_moves_the_upper_bound(tmp_path, capsys, similarity):
    root = make_vault(tmp_path)
    similarity(
        {
            (BETA, DELTA): 0.65,
            (EPSILON, ZETA): 0.79,
            (ETA, THETA): 0.80,
            (IOTA, KAPPA): 0.88,
            (ALPHA, GAMMA): 0.95,
        }
    )

    default = ordered(gaps(root, capsys))
    lowered = ordered(gaps(root, capsys, "--max", "0.8"))
    raised = ordered(gaps(root, capsys, "--max", "0.95"))

    assert default == [pair(IOTA, KAPPA), pair(ETA, THETA), pair(EPSILON, ZETA), pair(BETA, DELTA)]
    # 0.8 is inclusive: the pair scoring exactly 0.8 stays, 0.88 goes.
    assert lowered == [pair(ETA, THETA), pair(EPSILON, ZETA), pair(BETA, DELTA)]
    # 0.95 is inclusive too, and admits the near-duplicate the default band hides.
    assert raised == [pair(ALPHA, GAMMA)] + default


# ---------------------------------------------------------------------------
# 2. -k and --hub-degree
# ---------------------------------------------------------------------------

# ALPHA's neighbours, best first, listed by ALPHA only. BETA shares ALPHA's
# folder and sits last at 0.74, ninth.
_K_NEIGHBOURS = [GAMMA, DELTA, EPSILON, ZETA, ETA, THETA, IOTA, KAPPA, BETA]
_K_DIRECTED = {
    (ALPHA, other): round(0.90 - 0.02 * i, 2) for i, other in enumerate(_K_NEIGHBOURS)
}


def test_k_flag_limits_how_many_neighbours_are_read_per_note(tmp_path, capsys, similarity):
    root = make_vault(tmp_path)
    similarity(directed=_K_DIRECTED)

    def partners(*flags):
        return [(set(p) - {ALPHA}).pop() for p in ordered(gaps(root, capsys, *flags))]

    assert partners("-k", "1") == _K_NEIGHBOURS[:1]
    assert partners("-k", "3") == _K_NEIGHBOURS[:3]
    assert partners("-k", "9") == _K_NEIGHBOURS


def test_default_k_is_graphmarks_default_neighbour_count(tmp_path, capsys, similarity):
    assert GAPS_DEFAULT_K < len(_K_NEIGHBOURS), "fixture must out-reach the default k"
    root = make_vault(tmp_path)
    similarity(directed=_K_DIRECTED)

    result = gaps(root, capsys)

    assert [(set(p) - {ALPHA}).pop() for p in ordered(result)] == _K_NEIGHBOURS[:GAPS_DEFAULT_K]


def test_hub_degree_flag_demotes_pairs_touching_a_hub(tmp_path, capsys, similarity):
    # ALPHA links out to three notes: undirected degree 3. Its pair outscores
    # the other, so only hub demotion can put it second.
    root = make_vault(tmp_path, links=((ALPHA, BETA), (ALPHA, GAMMA), (ALPHA, DELTA)))
    similarity({(ALPHA, EPSILON): 0.90, (ZETA, ETA): 0.70})
    hub_pair, plain_pair = pair(ALPHA, EPSILON), pair(ZETA, ETA)

    default = ordered(gaps(root, capsys))
    demoted = ordered(gaps(root, capsys, "--hub-degree", "3"))
    just_short = ordered(gaps(root, capsys, "--hub-degree", "4"))

    assert default == [hub_pair, plain_pair]
    # degree >= hub-degree makes a hub; a hub's pair is demoted, never dropped.
    assert demoted == [plain_pair, hub_pair]
    assert just_short == [hub_pair, plain_pair]


def test_default_hub_degree_is_graphmarks_default(tmp_path, capsys, similarity):
    n = GAPS_DEFAULT_HUB_DEGREE
    leaves = tuple(f"reference/leaf{i:03d}.md" for i in range(n))
    spokes = tuple(f"reference/spoke{i:03d}.md" for i in range(n - 1))
    hub, near = "brain/hub.md", "brain/near.md"
    links = tuple((hub, leaf) for leaf in leaves) + tuple((near, s) for s in spokes)
    root = make_vault(tmp_path, links=links, notes=(*NOTES, hub, near, *leaves, *spokes))
    # hub has n neighbours (a hub), near has n - 1 (not one). The hub's pair
    # outscores near's, so only the default hub degree can reorder them.
    similarity({(hub, GAMMA): 0.90, (near, DELTA): 0.70})

    result = ordered(gaps(root, capsys))

    assert result == [pair(near, DELTA), pair(hub, GAMMA)]


# ---------------------------------------------------------------------------
# 3. --top and ranking
# ---------------------------------------------------------------------------


def test_top_defaults_to_ten_and_truncates_the_ranked_list(tmp_path, capsys, similarity):
    root = make_vault(tmp_path)
    similarity(dict(RANKED_SCORES))
    expected = [pair(*p) for p in RANKED_PAIRS]

    everything = ordered(gaps(root, capsys, "--top", "50"))
    default = ordered(gaps(root, capsys))

    assert everything == expected
    assert default == expected[:10]


@pytest.mark.parametrize("top", [1, 3, 11, 12])
def test_top_n_keeps_the_first_n_in_rank_order(tmp_path, capsys, similarity, top):
    root = make_vault(tmp_path)
    similarity(dict(RANKED_SCORES))

    result = ordered(gaps(root, capsys, "--top", str(top)))

    assert result == [pair(*p) for p in RANKED_PAIRS][:top]


def test_top_zero_emits_an_empty_list(tmp_path, capsys, similarity):
    root = make_vault(tmp_path)
    similarity(dict(RANKED_SCORES))

    rc, out = run(root, capsys, "--gaps", "--top", "0")

    assert (rc, out) == (0, "[]\n")


def test_negative_top_drops_the_tail_instead_of_erroring(tmp_path, capsys, similarity):
    # Characterization, not an endorsement: ``--top -1`` is a plain slice, so it
    # returns everything except the last-ranked pair rather than being refused.
    root = make_vault(tmp_path)
    similarity(dict(RANKED_SCORES))

    result = ordered(gaps(root, capsys, "--top", "-1"))

    assert result == [pair(*p) for p in RANKED_PAIRS][:-1]


def test_ranking_is_non_hub_then_cross_folder_then_score_then_path(tmp_path, capsys, similarity):
    # ZETA links out to five notes, so its pair is a hub pair at --hub-degree 5.
    zeta_links = tuple((ZETA, other) for other in (BETA, GAMMA, DELTA, EPSILON, KAPPA))
    root = make_vault(tmp_path, links=zeta_links)
    similarity(
        {
            (ALPHA, BETA): 0.89,  # same folder: ranked after every cross-folder pair
            (DELTA, ETA): 0.80,
            # A 0.70 tie, declared in the opposite order to path order, so only
            # the path tie-break (not declaration order) can put IOTA first.
            (ALPHA, EPSILON): 0.70,
            (ALPHA, IOTA): 0.70,
            (GAMMA, THETA): 0.62,  # cross-folder but lowest score
            (ZETA, ETA): 0.91,  # highest score, but ZETA is a hub
        }
    )

    result = ordered(gaps(root, capsys, "--hub-degree", "5"))

    assert result == [
        # Non-hub, cross-folder, by score; the tie is ordered by path.
        pair(DELTA, ETA),
        pair(ALPHA, IOTA),
        pair(ALPHA, EPSILON),
        pair(GAMMA, THETA),
        # Non-hub, same-folder: after every cross-folder pair, despite 0.89.
        pair(ALPHA, BETA),
        # Hub pairs come last, despite the highest score.
        pair(ZETA, ETA),
    ]


# ---------------------------------------------------------------------------
# 4. --note
# ---------------------------------------------------------------------------


def test_note_flag_restricts_output_to_pairs_involving_that_note(tmp_path, capsys, similarity):
    root = make_vault(tmp_path)
    similarity(dict(RANKED_SCORES))

    everything = ordered(gaps(root, capsys, "--top", "50"))
    only_delta = ordered(gaps(root, capsys, "--note", DELTA, "--top", "50"))

    assert len(everything) == 12
    assert only_delta == [pair(BETA, DELTA), pair(ALPHA, DELTA), pair(DELTA, ETA)]
    assert all(DELTA in p for p in only_delta)
    assert set(only_delta) < set(everything)


def test_note_scans_only_that_notes_own_neighbour_list(tmp_path, capsys, similarity):
    # Characterization, not an endorsement: BETA lists ZETA but ZETA does not
    # list BETA (top-k is directional). ``--note ZETA`` therefore does NOT
    # report the pair, although the pair does involve ZETA and is reported
    # without --note and with ``--note BETA``.
    root = make_vault(tmp_path)
    similarity(directed={(BETA, ZETA): 0.80})
    expected = [pair(BETA, ZETA)]

    assert ordered(gaps(root, capsys)) == expected
    assert ordered(gaps(root, capsys, "--note", BETA)) == expected
    assert gaps(root, capsys, "--note", ZETA) == []


def test_pair_orientation_follows_the_scanned_origin(tmp_path, capsys, similarity):
    # Characterization, not an endorsement. ``a`` is the note the pair was found
    # from when only one side listed the other; when both sides scored it
    # equally the pair comes out path-sorted instead.
    root = make_vault(tmp_path)
    similarity(pairs={(ALPHA, GAMMA): 0.80}, directed={(ZETA, BETA): 0.70})

    both_sides = gaps(root, capsys)
    one_side = [e for e in both_sides if BETA in (e["a"], e["b"])]
    two_side = [e for e in both_sides if GAMMA in (e["a"], e["b"])]

    assert [(e["a"], e["b"]) for e in two_side] == [(ALPHA, GAMMA)]
    assert [(e["a"], e["b"]) for e in one_side] == [(ZETA, BETA)]
    # --note scans one origin, so the requested note is always ``a``.
    scoped = gaps(root, capsys, "--note", GAMMA)
    assert [(e["a"], e["b"]) for e in scoped] == [(GAMMA, ALPHA)]


# ---------------------------------------------------------------------------
# 5. --near-bridges
# ---------------------------------------------------------------------------

# A seven-note ring (no cut vertex inside it) with three notes hanging off it:
# ZETA is a leaf of ALPHA; IOTA and THETA are a two-note tail off KAPPA.
RING_LINKS = (
    (ALPHA, BETA),
    (BETA, GAMMA),
    (GAMMA, DELTA),
    (DELTA, EPSILON),
    (EPSILON, ETA),
    (ETA, KAPPA),
    (KAPPA, ALPHA),
    (ZETA, ALPHA),
    (KAPPA, IOTA),
    (IOTA, THETA),
)
SILOED = {ZETA, IOTA, THETA}


def _siloed_in(root: Path) -> set[str]:
    graph, _cfg = gc.build(root)
    return set(siloed_notes(graph))


def test_near_bridges_keeps_only_pairs_a_siloed_note_originates(tmp_path, capsys, similarity):
    root = make_vault(tmp_path, links=RING_LINKS)
    assert _siloed_in(root) == SILOED, "fixture must have exactly these siloed notes"
    similarity(
        {
            (THETA, GAMMA): 0.85,  # siloed - mainland
            (ZETA, DELTA): 0.80,  # siloed - mainland
            (IOTA, BETA): 0.75,  # siloed - mainland
            (THETA, ZETA): 0.70,  # siloed - siloed
            (ALPHA, DELTA): 0.90,  # mainland - mainland
            (BETA, ETA): 0.78,  # mainland - mainland
        }
    )

    unflagged = set(ordered(gaps(root, capsys)))
    near = ordered(gaps(root, capsys, "--near-bridges"))

    assert len(unflagged) == 6, "the flag must have something to remove"
    assert near == [pair(THETA, GAMMA), pair(ZETA, DELTA), pair(IOTA, BETA), pair(THETA, ZETA)]
    assert set(near) < unflagged
    assert all(p & SILOED for p in near)


def test_near_bridges_only_scans_siloed_origins(tmp_path, capsys, similarity):
    # Characterization, not an endorsement: the flag narrows the *scan*, so a
    # pair that only the mainland side lists (GAMMA lists IOTA, IOTA does not
    # list GAMMA) is missed although IOTA is siloed.
    root = make_vault(tmp_path, links=RING_LINKS)
    similarity(directed={(GAMMA, IOTA): 0.72, (IOTA, BETA): 0.74})

    assert set(ordered(gaps(root, capsys))) == {pair(GAMMA, IOTA), pair(IOTA, BETA)}
    near = gaps(root, capsys, "--near-bridges")
    assert [(e["a"], e["b"]) for e in near] == [(IOTA, BETA)]


def test_near_bridges_with_nothing_siloed_emits_an_empty_list(tmp_path, capsys, similarity):
    # No links: every note is an orphan and the graph has no cut vertex, so
    # nothing is "siloed" and the scan has no targets at all.
    root = make_vault(tmp_path)
    assert _siloed_in(root) == set()
    similarity(dict(RANKED_SCORES))

    assert len(gaps(root, capsys, "--top", "50")) == 12
    rc, out = run(root, capsys, "--gaps", "--near-bridges")
    assert (rc, out) == (0, "[]\n")


def test_note_wins_over_near_bridges(tmp_path, capsys, similarity):
    root = make_vault(tmp_path, links=RING_LINKS)
    similarity({(ALPHA, DELTA): 0.90, (THETA, GAMMA): 0.85})

    # ALPHA is not siloed, so --near-bridges alone does not reach its pair ...
    assert ordered(gaps(root, capsys, "--near-bridges")) == [pair(THETA, GAMMA)]
    # ... but an explicit --note takes precedence over the siloed target list.
    assert ordered(gaps(root, capsys, "--note", ALPHA, "--near-bridges")) == [pair(ALPHA, DELTA)]


# ---------------------------------------------------------------------------
# 6. Links, self-matches, dismissal
# ---------------------------------------------------------------------------


def test_linked_pairs_and_self_matches_are_never_suggested(tmp_path, capsys, similarity):
    root = make_vault(tmp_path, links=((ALPHA, BETA), (GAMMA, DELTA)))
    similarity(
        {
            (ALPHA, BETA): 0.80,  # linked ALPHA -> BETA
            (DELTA, GAMMA): 0.78,  # linked GAMMA -> DELTA, listed from DELTA's side too
            (EPSILON, ZETA): 0.76,  # unlinked: the only survivor
        },
        directed={(ETA, ETA): 0.85},  # a note matching itself
    )

    assert ordered(gaps(root, capsys)) == [pair(EPSILON, ZETA)]


def test_dismiss_prints_the_signature_and_hides_only_that_pair(tmp_path, capsys, similarity):
    root = make_vault(tmp_path)
    similarity(dict(RANKED_SCORES))
    before = ordered(gaps(root, capsys, "--top", "50"))
    assert pair(ALPHA, GAMMA) in before

    rc, out = run(root, capsys, "--dismiss", ALPHA, GAMMA)

    assert rc == 0
    assert out.endswith("\n") and out.count("\n") == 1
    assert json.loads(out) == {"dismissed": "weaklink|brain/alpha.md|work/gamma.md"}
    after = ordered(gaps(root, capsys, "--top", "50"))
    assert pair(ALPHA, GAMMA) not in after
    assert after == [p for p in before if p != pair(ALPHA, GAMMA)]
    # The store /connect and /garden document is where the dismissal lands.
    store = json.loads((root / ".claude/data/connect-dismissed.json").read_text())
    assert list(store) == ["weaklink|brain/alpha.md|work/gamma.md"]


def test_dismissal_is_order_independent(tmp_path, capsys, similarity):
    root = make_vault(tmp_path)
    similarity(dict(RANKED_SCORES))

    rc, out = run(root, capsys, "--dismiss", GAMMA, ALPHA)

    assert rc == 0
    assert json.loads(out) == {"dismissed": weaklink_sig(ALPHA, GAMMA)}
    assert json.loads(out) == {"dismissed": "weaklink|brain/alpha.md|work/gamma.md"}
    assert pair(ALPHA, GAMMA) not in ordered(gaps(root, capsys, "--top", "50"))


def test_dismissal_expires_when_either_note_changes(tmp_path, capsys, similarity):
    root = make_vault(tmp_path)
    similarity(dict(RANKED_SCORES))
    before = ordered(gaps(root, capsys, "--top", "50"))
    run(root, capsys, "--dismiss", ALPHA, GAMMA)
    assert pair(ALPHA, GAMMA) not in ordered(gaps(root, capsys, "--top", "50"))

    with (root / GAMMA).open("a", encoding="utf-8") as f:
        f.write("\nEdited after the dismissal.\n")

    assert ordered(gaps(root, capsys, "--top", "50")) == before


def test_dismissed_pairs_do_not_consume_top_slots(tmp_path, capsys, similarity):
    root = make_vault(tmp_path)
    similarity(dict(RANKED_SCORES))
    expected = [pair(*p) for p in RANKED_PAIRS]
    assert ordered(gaps(root, capsys, "--top", "3")) == expected[:3]

    run(root, capsys, "--dismiss", *RANKED_PAIRS[0])

    # Dismissal is applied before truncation: the list backfills to three.
    assert ordered(gaps(root, capsys, "--top", "3")) == expected[1:4]


def test_dismiss_needs_no_similarity_reader_and_wins_over_gaps(tmp_path, capsys, monkeypatch):
    def reader_factory(vault_root):
        raise AssertionError("--dismiss must not build the similarity reader")

    monkeypatch.setattr(gc, "vector_similar_fn", reader_factory)
    root = make_vault(tmp_path)

    rc, out = run(root, capsys, "--gaps", "--dismiss", ALPHA, GAMMA)

    assert rc == 0
    assert json.loads(out) == {"dismissed": "weaklink|brain/alpha.md|work/gamma.md"}


def test_dismissing_an_unknown_note_raises_instead_of_emitting_json(tmp_path, capsys):
    # Characterization, not an endorsement: a bad path surfaces as the library's
    # ValueError (a traceback), not as a JSON error object or a clean exit 1.
    root = make_vault(tmp_path)

    with pytest.raises(ValueError, match="note not found"):
        gc.main(["--vault-root", str(root), "--dismiss", ALPHA, "brain/ghost.md"])

    assert capsys.readouterr().out == ""
    assert not (root / ".claude/data/connect-dismissed.json").exists()


# ---------------------------------------------------------------------------
# 7. Transient exclusion
# ---------------------------------------------------------------------------


def _transient_path(prefix: str) -> str:
    return prefix + "ledger.md" if prefix.endswith("/") else prefix


@pytest.mark.parametrize("prefix", gc.TRANSIENT_PREFIXES)
def test_transient_note_never_appears_as_a_neighbour(tmp_path, capsys, similarity, prefix):
    transient = _transient_path(prefix)
    root = make_vault(tmp_path, notes=(*NOTES, transient))
    # Both notes list the transient one as a qualifying match.
    similarity({(ALPHA, transient): 0.85, (GAMMA, transient): 0.80, (BETA, DELTA): 0.75})

    result = gaps(root, capsys)

    assert ordered(result) == [pair(BETA, DELTA)]


@pytest.mark.parametrize("explicit_note", [False, True], ids=["scanned", "--note"])
@pytest.mark.parametrize("prefix", gc.TRANSIENT_PREFIXES)
def test_transient_note_is_never_scanned_as_an_origin(
    tmp_path, capsys, similarity, prefix, explicit_note
):
    transient = _transient_path(prefix)
    root = make_vault(tmp_path, notes=(*NOTES, transient))
    # Only the transient note lists a match, so the pair exists only if the
    # transient note itself is scanned.
    similarity(directed={(transient, ALPHA): 0.85})
    flags = ("--note", transient) if explicit_note else ()

    assert gaps(root, capsys, *flags) == []


# ---------------------------------------------------------------------------
# 8. Output format and exit codes
# ---------------------------------------------------------------------------


def test_entry_shape_is_a_b_score_sig_on_one_line(tmp_path, capsys, similarity):
    root = make_vault(tmp_path)
    similarity({(GAMMA, ALPHA): 0.876543})

    rc, out = run(root, capsys, "--gaps")

    assert rc == 0
    # /connect and /garden read exactly these four keys; the score is rounded
    # to four places and the signature is graphmark's path-sorted weaklink sig.
    assert out == (
        '[{"a": "brain/alpha.md", "b": "work/gamma.md", "score": 0.8765, '
        '"sig": "weaklink|brain/alpha.md|work/gamma.md"}]\n'
    )
    [entry] = json.loads(out)
    assert set(entry) == {"a", "b", "score", "sig"}
    assert entry["sig"] == weaklink_sig(entry["a"], entry["b"])


def test_non_ascii_note_names_are_emitted_verbatim(tmp_path, capsys, similarity):
    cafe = "brain/café.md"
    root = make_vault(tmp_path, notes=(*NOTES, cafe))
    similarity({(cafe, GAMMA): 0.80})

    rc, out = run(root, capsys, "--gaps")

    assert rc == 0
    assert "café" in out and "\\u" not in out


def test_normal_run_exits_zero_with_exactly_one_json_document(tmp_path, capsys, similarity):
    root = make_vault(tmp_path)
    similarity(dict(RANKED_SCORES))

    rc, out = run(root, capsys, "--gaps")

    assert rc == 0
    assert out.endswith("\n") and out.count("\n") == 1
    assert isinstance(json.loads(out), list) and len(json.loads(out)) == 10


@pytest.mark.parametrize(
    ("pairs", "links", "flags"),
    [
        pytest.param({}, (), (), id="reader-has-no-neighbours"),
        pytest.param({(ALPHA, GAMMA): 0.30}, (), (), id="all-below-the-band"),
        pytest.param({(ALPHA, GAMMA): 0.99}, (), (), id="all-above-the-band"),
        pytest.param({(ALPHA, GAMMA): 0.80}, ((ALPHA, GAMMA),), (), id="all-already-linked"),
        pytest.param(dict(RANKED_SCORES), (), ("--note", "brain/ghost.md"), id="unknown-note"),
        pytest.param(dict(RANKED_SCORES), (), ("--top", "0"), id="top-zero"),
    ],
)
def test_an_empty_result_emits_an_empty_json_list(
    tmp_path, capsys, similarity, pairs, links, flags
):
    root = make_vault(tmp_path, links=links)
    similarity(pairs)

    rc, out = run(root, capsys, "--gaps", *flags)

    assert (rc, out) == (0, "[]\n")


def test_nan_score_is_dropped_by_the_band(tmp_path, capsys, similarity):
    # Deliberate change from the graphmark-gaps era, which let a NaN score slip
    # through (``score < threshold`` is False for NaN) and emitted bare ``NaN``,
    # which is not strict JSON. ragmark.gaps.rank_pairs requires
    # ``threshold <= score <= max_score``, which NaN fails, so it never reaches
    # the output.
    root = make_vault(tmp_path)
    similarity({(ALPHA, GAMMA): float("nan")})

    rc, out = run(root, capsys, "--gaps")

    assert (rc, out) == (0, "[]\n")


# ---------------------------------------------------------------------------
# 9. Wiring to the similarity reader
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fails_at", ["build", "read"])
def test_a_similarity_failure_propagates_and_emits_nothing(
    tmp_path, capsys, monkeypatch, fails_at
):
    # Whatever the reader raises (a corrupt index, say) is not swallowed into a
    # partial or empty result: the exception reaches the caller and stdout stays
    # empty. The index-state errors themselves are pinned in
    # test_graph_cli_root_resolution.py.
    def broken_reader(rel, k):
        raise RuntimeError("index corrupt")

    def factory(vault_root):
        if fails_at == "build":
            raise RuntimeError("index corrupt")
        return broken_reader

    monkeypatch.setattr(gc, "vector_similar_fn", factory)
    root = make_vault(tmp_path)

    with pytest.raises(RuntimeError, match="index corrupt"):
        gc.main(["--vault-root", str(root), "--gaps"])

    assert capsys.readouterr().out == ""


def test_the_reader_is_built_for_the_resolved_vault_root(tmp_path, capsys, monkeypatch):
    built_for = []

    def factory(vault_root):
        built_for.append(vault_root)
        return lambda rel, k: []

    monkeypatch.setattr(gc, "vector_similar_fn", factory)
    root = make_vault(tmp_path)
    (tmp_path / "elsewhere").mkdir()
    spelled = tmp_path / "elsewhere" / ".." / "vault"

    rc, out = run(spelled, capsys, "--gaps")

    assert (rc, out) == (0, "[]\n")
    assert built_for == [root.resolve()]


# ---------------------------------------------------------------------------
# 9. Behavior the handler inherits from the ranking library
# ---------------------------------------------------------------------------
# Since the migration to ragmark.gaps.rank_pairs these decisions live in the
# installed wheel, not in this handler. Mutating the wheel's source left each one
# unguarded, so a ragmark release that changed it would have passed this suite.

# A path containing the signature separator, and four paths whose unescaped
# signatures would collide: ("brain/a.md", "work/b.md|reference/c1.md") and
# ("brain/a.md|work/b.md", "reference/c1.md") both join to
# "brain/a.md|work/b.md|reference/c1.md".
PIPE_NOTE = "reference/p|q.md"
TWIN_A1, TWIN_A2 = "brain/a.md", "work/b.md|reference/c1.md"
TWIN_B1, TWIN_B2 = "brain/a.md|work/b.md", "reference/c1.md"


def test_dismissed_pair_with_a_pipe_in_its_path_stays_dismissed(tmp_path, capsys, similarity):
    root = make_vault(tmp_path, notes=(*NOTES, PIPE_NOTE))
    similarity({(PIPE_NOTE, GAMMA): 0.80})
    assert pair(PIPE_NOTE, GAMMA) in ordered(gaps(root, capsys))

    rc, out = run(root, capsys, "--dismiss", PIPE_NOTE, GAMMA)

    assert rc == 0
    assert json.loads(out) == {"dismissed": weaklink_sig(PIPE_NOTE, GAMMA)}
    assert json.loads(out)["dismissed"].startswith("weaklink2|")
    assert pair(PIPE_NOTE, GAMMA) not in ordered(gaps(root, capsys))


def test_pairs_whose_paths_join_to_the_same_string_do_not_share_a_dismissal(
    tmp_path, capsys, similarity
):
    root = make_vault(tmp_path, notes=(TWIN_A1, TWIN_A2, TWIN_B1, TWIN_B2))
    similarity({(TWIN_A1, TWIN_A2): 0.80, (TWIN_B1, TWIN_B2): 0.70})
    assert ordered(gaps(root, capsys)) == [pair(TWIN_A1, TWIN_A2), pair(TWIN_B1, TWIN_B2)]

    run(root, capsys, "--dismiss", TWIN_A1, TWIN_A2)

    # Only the dismissed pair goes; its colliding twin stays visible.
    assert ordered(gaps(root, capsys)) == [pair(TWIN_B1, TWIN_B2)]


def test_hub_degree_counts_a_mutual_link_once(tmp_path, capsys, similarity):
    # ALPHA and each of BETA, GAMMA, DELTA link to one another: three neighbours,
    # so the undirected simple-graph degree is 3, not 6.
    links = (
        (ALPHA, BETA), (BETA, ALPHA),
        (ALPHA, GAMMA), (GAMMA, ALPHA),
        (ALPHA, DELTA), (DELTA, ALPHA),
    )
    root = make_vault(tmp_path, links=links)
    similarity({(ALPHA, EPSILON): 0.90, (ZETA, ETA): 0.70})
    hub_pair, plain_pair = pair(ALPHA, EPSILON), pair(ZETA, ETA)

    assert ordered(gaps(root, capsys, "--hub-degree", "4")) == [hub_pair, plain_pair]
    assert ordered(gaps(root, capsys, "--hub-degree", "3")) == [plain_pair, hub_pair]


def test_a_pair_listed_by_both_sides_keeps_the_higher_score_and_its_orientation(
    tmp_path, capsys, similarity
):
    # Cosine similarity is symmetric, so a real index lists a pair with one score;
    # an asymmetric reader is the only way to tell which score wins.
    root = make_vault(tmp_path)
    similarity(directed={(ALPHA, ZETA): 0.85, (ZETA, ALPHA): 0.70})

    entries = gaps(root, capsys)

    assert [(e["a"], e["b"], e["score"]) for e in entries] == [(ALPHA, ZETA, 0.85)]


def test_a_neighbour_outside_the_graph_is_emitted_not_dropped_or_fatal(
    tmp_path, capsys, similarity
):
    # Characterization, not an endorsement (ragmark#203). The index can know
    # notes the graph lacks. Neither graphmark's gaps() nor rank_pairs checks that
    # a neighbour is a graph node, so the pair is emitted; a ranking that looked a
    # neighbour's degree up unguarded would raise KeyError.
    ghost = "reference/not-in-the-graph.md"
    root = make_vault(tmp_path)
    similarity(directed={(ALPHA, ghost): 0.80})

    entries = gaps(root, capsys)

    assert [(e["a"], e["b"]) for e in entries] == [(ALPHA, ghost)]


def test_importing_graph_cli_does_not_require_ragmark(monkeypatch):
    # cold_read_evidence, graph_gardener and wrap_up_audit import graph_cli
    # in-process for build()/diagnose(), some under an environment that has
    # graphmark only; ragmark must stay a lazy import inside main().
    monkeypatch.setitem(sys.modules, "ragmark", None)
    monkeypatch.setitem(sys.modules, "ragmark.gaps", None)
    spec = importlib.util.spec_from_file_location("graph_cli_without_ragmark", ENGINE / "graph_cli.py")
    module = importlib.util.module_from_spec(spec)

    spec.loader.exec_module(module)

    assert callable(module.build) and callable(module.main)


def test_a_root_level_note_has_no_folder_so_a_root_pair_ranks_below_a_cross_folder_pair(
    tmp_path, capsys, similarity
):
    # Root-level notes are not graph nodes, but --note scans any path it is given and the
    # index can list root-level neighbours. A root-level note has no top-level folder, so two
    # of them count as the same folder and rank after a cross-folder pair despite a higher score.
    root_note, other_root_note = "rootnote.md", "other-root.md"
    root = make_vault(tmp_path)
    similarity(directed={(root_note, other_root_note): 0.90, (root_note, ALPHA): 0.70})

    entries = gaps(root, capsys, "--note", root_note)

    assert [(e["a"], e["b"]) for e in entries] == [(root_note, ALPHA), (root_note, other_root_note)]
