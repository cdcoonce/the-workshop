"""Differential fuzz of the entry-replay handoff merge, with and without moves.

``entry_replay_backtest.py`` measures real vault history, but real handoff
history holds no moved item raced by the other side (0 in 157 commits), so it
cannot show that move pairing never fires on a merge it should accept. This
rig generates three-way handoff merges from real handoff bullets (so the
similarity bars meet realistic text, including bullets about one project)
and runs a *baseline* module (a git ref) and the *working-tree* module on
each, graded against generator ground truth:

* **Violation** -- the candidate accepts what the baseline refused, or
  accepts with different text. A fix meant only to add refusals has none.
* **New refusal** -- the baseline accepted, the candidate refuses. Graded
  against the intended content (``truth_content``): a *true conflict* (both
  sides changed one item differently), the baseline's output was
  *content-wrong*, or it was content-right -- a **false refusal**.
* **Content-wrong accept** -- an accepted merge whose item multiset is not
  the intended one.

Two populations alternate: ``no-moves`` (insert, delete and edit only) and
``moves`` (plus in-section and cross-section moves, with and without an
edit). Fresh inserts are drawn from pool bullets not alike any bullet the
case started from, so an insert is never secretly a version of a deleted
item. The content grade is a multiset: it does not judge order.

Usage, from the workshop repository root::

    uv run python -m scripts.entry_replay_move_fuzz \\
        --vault /path/to/the-vault --since 2026-09-21 [--baseline-ref origin/dev] \\
        [--cases 3000] [--seed 1]

The vault is only ever read (``git log``, ``git show``). Exit 1 when any
violation, false refusal or content-wrong candidate accept was found.
"""

from __future__ import annotations

import argparse
import random
import sys
import tempfile
from collections import Counter, defaultdict
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from scripts.entry_replay_backtest import Vault, load_baseline, load_candidate

HANDOFF = ".brain/handoff-personal.md"
SECTIONS = ("Resume from here", "Open threads", "Done")
FALSE_REFUSAL = "new-refusal: baseline output content-right (FALSE REFUSAL)"
_FRONTMATTER = (
    '---\ndate: 2026-09-15\ndescription: "d"\ntags: [handoff]\n---\n# H\n\n_Updated 2026-10-10_\n\n'
)
_EDITS = (
    lambda text: text + " (updated 2026-10-11)",
    lambda text: text + "; CI green",
    lambda text: text.replace("the ", "a ", 1),
    lambda text: text[: max(20, len(text) * 2 // 3)] + " -- rewritten tail",
    lambda text: "- ~~" + text[2:] + "~~ done",
)

Doc = dict[str, list[tuple[str, str]]]  # section -> [(item id, text)]
Truth = dict[str, set[str]]  # item id -> {"delete", "edit", "move"}


def bullet_pool(vault: Vault, since: str, limit: int = 60) -> list[str]:
    """Distinct top-level bullets of at least 25 characters from recent handoff revisions."""
    revs = vault.git("log", f"--since={since}", "--format=%H", "--", HANDOFF).stdout.split()
    pool: set[str] = set()
    for rev in revs[:limit]:
        text = vault.blob(rev, HANDOFF) or ""
        pool.update(line for line in text.split("\n") if line.startswith("- ") and len(line) >= 27)
    return sorted(pool)


def render(doc: Doc) -> str:
    body = "".join(
        f"## {section}\n\n" + "".join(text + "\n" for _iid, text in doc[section]) + "\n"
        for section in SECTIONS
    )
    return _FRONTMATTER + body + "## Mode\n\nVault first.\n"


def mutate(
    doc: Doc, rng: random.Random, side: str, moves: bool, fresh: Iterator[str]
) -> tuple[Doc, Truth]:
    """Apply one to three random edits; return the new doc and which base items changed how."""
    doc = {section: list(items) for section, items in doc.items()}
    truth: Truth = defaultdict(set)
    kinds = ["insert", "delete", "edit"]
    if moves:
        kinds += ["move", "xmove", "move_edit", "xmove_edit"]
    for _ in range(rng.randint(1, 3)):
        kind = rng.choice(kinds)
        section = rng.choice(SECTIONS)
        items = doc[section]
        if kind == "insert":
            text = next(fresh, None)
            if text is not None:
                items.insert(rng.randint(0, len(items)), (f"{side}{rng.random()}", text))
            continue
        if not items:
            continue
        index = rng.randrange(len(items))
        iid, text = items[index]
        if kind == "delete":
            items.pop(index)
            truth[iid].add("delete")
        elif kind == "edit":
            items[index] = (iid, rng.choice(_EDITS)(text))
            truth[iid].add("edit")
        else:
            items.pop(index)
            new = rng.choice(_EDITS)(text) if kind.endswith("_edit") else text
            dest = rng.choice([s for s in SECTIONS if s != section]) if kind.startswith("x") else section
            doc[dest].insert(rng.randint(0, len(doc[dest])), (iid, new))
            truth[iid].add("move")
    return doc, truth


def truth_content(base: Doc, tip: Doc, origin: Doc, tip_truth: Truth, origin_truth: Truth) -> Counter[str] | None:
    """The intended item multiset, or None when both sides changed one item differently."""
    base_text = {iid: text for items in base.values() for iid, text in items}
    tip_text = {iid: text for items in tip.values() for iid, text in items}
    origin_text = {iid: text for items in origin.values() for iid, text in items}
    out: Counter[str] = Counter()
    for iid in base_text:
        by_tip, by_origin = bool(tip_truth.get(iid)), bool(origin_truth.get(iid))
        if by_tip and by_origin:
            if tip_text.get(iid) != origin_text.get(iid):
                return None
            if tip_text.get(iid) is not None:
                out[tip_text[iid]] += 1
            continue
        side = tip_text if by_tip else origin_text
        if side.get(iid) is not None:
            out[side[iid]] += 1
    for iid, text in [*tip_text.items(), *origin_text.items()]:
        if iid not in base_text:
            out[text] += 1
    return out


def _items_of(text: str) -> Counter[str]:
    return Counter(line for line in text.split("\n") if line.startswith("- "))


def _merge(module: Any, base: str, tip: str, origin: str) -> str | tuple[str, str]:
    try:
        return module.handoff_merge(base, tip, origin, HANDOFF)[0]
    except module.RefusalError as exc:
        return ("refuse", str(exc))
    except Exception as exc:  # noqa: BLE001 -- a crash is a finding, not a rig failure
        return ("crash", repr(exc))


def run_fuzz(
    baseline: Any, candidate: Any, pool: list[str], cases: int, seed: int
) -> tuple[Counter[tuple[str, str]], dict[str, list[Any]]]:
    """Run ``cases`` generated merges through both modules; tally by population and outcome."""
    rng = random.Random(seed)
    alike = {
        (a, b)
        for a in pool
        for b in pool
        if a != b and candidate._items_alike((a,), (b,), candidate._MOVE_RATIO)
    }
    stats: Counter[tuple[str, str]] = Counter()
    examples: dict[str, list[Any]] = defaultdict(list)
    for case in range(cases):
        population = "moves" if case % 2 else "no-moves"
        shuffled = rng.sample(pool, len(pool))
        picked = shuffled[:12]
        fresh = iter([p for p in shuffled[12:] if not any((p, q) in alike for q in picked)])
        base: Doc = {
            section: [(f"b{section}{i}", picked[4 * n + i]) for i in range(rng.randint(2, 4))]
            for n, section in enumerate(SECTIONS)
        }
        tip, tip_truth = mutate(base, rng, "t", population == "moves", fresh)
        origin, origin_truth = mutate(base, rng, "o", population == "moves", fresh)
        texts = render(base), render(tip), render(origin)
        old, new = _merge(baseline, *texts), _merge(candidate, *texts)
        intended = truth_content(base, tip, origin, tip_truth, origin_truth)
        if isinstance(new, tuple) and new[0] == "crash":
            key = "candidate-crash"
        elif isinstance(new, str) and not isinstance(old, str):
            key = "VIOLATION candidate-accepts-baseline-refused"
        elif isinstance(new, str) and new != old:
            key = "VIOLATION outputs-differ"
        elif isinstance(new, str):
            wrong = intended is not None and _items_of(new) != intended
            key = "both-accept CONTENT-WRONG" if wrong else "both-accept"
        elif not isinstance(old, str):
            key = "both-refuse"
        elif intended is None:
            key = "new-refusal: true conflict"
        elif _items_of(old) != intended:
            key = "new-refusal: baseline output content-wrong"
        else:
            key = FALSE_REFUSAL
        stats[population, key] += 1
        if key.startswith(("VIOLATION", "candidate-crash", "both-accept CONTENT")) or key == FALSE_REFUSAL:
            examples[key].append((texts, new if isinstance(new, tuple) else None))
    return stats, examples


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Differential fuzz of the entry-replay handoff merge.")
    parser.add_argument("--vault", required=True, type=Path, help="path to the vault repository")
    parser.add_argument("--since", required=True, help="YYYY-MM-DD cutoff for the bullet pool")
    parser.add_argument("--baseline-ref", default="origin/dev", help="workshop ref of the baseline")
    parser.add_argument("--cases", type=int, default=3000)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args(argv)

    vault = Vault(args.vault.resolve())
    if vault.git("rev-parse", "--git-dir").returncode != 0:
        print(f"error: {args.vault} is not a git repository", file=sys.stderr)
        return 2
    pool = bullet_pool(vault, args.since)
    if len(pool) < 24:
        print(f"error: only {len(pool)} handoff bullets since {args.since}; need 24", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory() as tmp:
        baseline = load_baseline(args.baseline_ref, Path(tmp))
        candidate = load_candidate()
    stats, examples = run_fuzz(baseline, candidate, pool, args.cases, args.seed)
    print(f"pool {len(pool)} bullets, {args.cases} cases, seed {args.seed}, baseline {args.baseline_ref}")
    for (population, key), count in sorted(stats.items()):
        print(f"  {population:9s} {key:60s} {count}")
    for key, found in examples.items():
        print(f"\n{key}: {len(found)} (first shown)")
        print(found[0][1] or "\n".join(found[0][0]))
    return 1 if examples else 0


if __name__ == "__main__":
    raise SystemExit(main())
