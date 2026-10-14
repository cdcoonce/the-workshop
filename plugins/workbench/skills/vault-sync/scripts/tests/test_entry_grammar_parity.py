"""The engine's entry grammar stays the vault-sync entry replay's.

``vault_audit.py``'s ordering detector reads hub-file entries through
``vault_utils.entry_runs``. Both are vendored into the vault
(``.claude/scripts/``) and run standalone there, while ``entry_replay.py``
runs from the plugin's vault-sync skill, so neither can import the other at
runtime and the engine carries its own copy of the grammar. This test is what keeps the copy honest: over hand
fixtures and a seeded generator, every anchor block the replay parses must
hold exactly the entries the audit reads, at the same lines with the same
dates. A block the replay refuses (mixed levels, an undated heading at entry
level) has no replay answer, so that document is skipped, and the generator
must still compare enough documents for the run to mean anything.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

REPLAY_DIR = Path(__file__).resolve().parent.parent
ENGINE_DIR = REPLAY_DIR.parents[2] / "machinery" / "engine"
sys.path.insert(0, str(ENGINE_DIR))
sys.path.insert(0, str(REPLAY_DIR))

import entry_replay  # noqa: E402
import vault_utils  # noqa: E402

Blocks = dict[int, list[tuple[int, str]]]


def _top_level_spans(doc: entry_replay._Doc) -> list[entry_replay._Span]:
    """The replay's anchor spans, minus any nested inside an earlier one."""
    kept: list[entry_replay._Span] = []
    for span in doc.spans:
        if any(o.anchor_idx < span.anchor_idx < o.end_idx for o in kept):
            continue
        kept.append(span)
    return kept


def _replay_blocks(text: str) -> Blocks | None:
    """``{anchor line index: [(entry line index, date), ...]}``, or None on refusal."""
    doc = entry_replay._load_doc(text, strict=False)
    out: Blocks = {}
    for span in _top_level_spans(doc):
        try:
            block = entry_replay._parse_block(
                doc.lines, doc.flags, doc.headings, span.anchor_idx, "<doc>"
            )
        except entry_replay.RefusalError:
            return None
        idx = span.anchor_idx + 1 + len(block.preamble)
        entries: list[tuple[int, str]] = []
        for chunk in block.entries:
            entries.append((idx, chunk.day))
            idx += len(chunk.lines)
        out[span.anchor_idx] = entries
    return out


def _audit_blocks(text: str) -> Blocks:
    return {
        anchor: entries
        for anchor, entries in vault_utils.entry_runs(text.splitlines())
        if anchor is not None
    }


FIXTURES = {
    "key decisions": (
        "# Key Decisions\n\n## Recent\n\n"
        "### 2026-09-02 — newest\n\n- **2026-09-30 — quoted bullet**\n\n"
        "### 2026-09-01 — older\n\nBody.\n"
    ),
    "gotchas qualifiers": (
        "# Gotchas\n\n## Technical\n\n"
        "### Bare (2026-09-03)\n\nBody.\n\n"
        "### Qualified (2026-09-02, [[apipulse]])\n\nBody.\n\n"
        "### Spanned (2026-09-01 onward, [[x]])\n\nBody.\n\n"
        "### Corrected (2026-08-01, corrected 2026-10-01)\n\nBody.\n"
    ),
    "brag doc quarters": (
        "# Brag Doc\n\n## Q3 2026\n\n### Wins\n\n- **2026-09-02 — a**\n\n- **2026-07-01 — b**\n\n"
        "### Growth\n\n- **2026-08-12 — c**\n\n## Q2 2026\n\n### Wins\n\n- **2026-06-01 — d**\n"
    ),
    "fenced example": (
        "# Gotchas\n\n## Technical\n\n### Trap (2026-09-02)\n\n"
        "````md\n```\n### Quoted (2026-09-30)\n- **2026-09-30 — q**\n````\n\n"
        "~~~\n### 2026-09-29 — tilde-fenced\n~~~\n\n### Older (2026-09-01)\n"
    ),
    "invalid dates": (
        "# K\n\n## Recent\n\n### 2026-09-02 — real\n\n#### 2026-13-45 — not a date\n\n"
        "#### Bad (2026-02-30)\n\n- **2026-00-01 — not a date**\n\n### 2026-09-01 — real\n"
    ),
    "deep headings": "# K\n\n## Recent\n\n##### 2026-09-01 — deep\n\n##### Deep (2026-08-01)\n",
    "dated level two": "# K\n\n## 2026-01-01 archive\n\n### 2026-09-02 — a\n\n### 2026-09-01 — b\n",
}


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_audit_reads_the_replays_entries_on_each_fixture(name: str) -> None:
    text = FIXTURES[name]
    replay = _replay_blocks(text)

    assert replay is not None, f"fixture {name!r} must parse under the replay"
    assert any(replay.values()), f"fixture {name!r} must hold entries"
    assert _audit_blocks(text) == replay


_LINES = (
    "# Title",
    "## Technical",
    "## Q3 2026",
    "### Wins",
    "### Growth",
    "## {d} dated anchor",
    "### {d} — lead",
    "### Lead with words {d} later",
    "### Trail ({d})",
    "### Trail ({d}, [[x]])",
    "### Trail ({d} onward, [[x]])",
    "### Trail ({d}) not at the end",
    "#### {d} — deeper",
    "###### Deepest ({d})",
    "### 2026-13-45 — not a date",
    "### Bad (2026-02-30)",
    "- **{d} — a bullet**",
    "- **{d}** short",
    "  - **{d} — indented, never an entry**",
    "* **{d} — star bullet, never an entry**",
    "- **2026-00-01 — not a date**",
    "> ### {d} — quoted",
    "```",
    "```python",
    "````",
    "~~~",
    "    ```",
    "``` with `tick` info",
    "Body text.",
    "",
    "",
    "- a plain bullet",
)


def _random_doc(rng: random.Random) -> str:
    lines = []
    for _ in range(rng.randint(1, 40)):
        day = f"2026-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"
        lines.append(rng.choice(_LINES).replace("{d}", day))
    return "\n".join(lines) + "\n"


def test_audit_reads_the_replays_entries_on_generated_documents() -> None:
    rng = random.Random(20261012)
    compared = with_entries = 0
    for case in range(4000):
        text = _random_doc(rng)
        replay = _replay_blocks(text)
        if replay is None:
            continue
        compared += 1
        with_entries += any(replay.values())
        assert _audit_blocks(text) == replay, f"case {case}:\n{text}"

    assert compared >= 1000, f"only {compared} of 4000 documents parsed under the replay"
    assert with_entries >= 500, f"only {with_entries} compared documents held an entry"
