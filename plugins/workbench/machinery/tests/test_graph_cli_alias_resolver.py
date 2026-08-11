"""Frontmatter `aliases:` are part of how the vault names notes, so the graph
has to resolve them.

The seam used to implement that itself: graphmark resolved a wikilink by
normalized basename with a path-suffix fallback and never looked at
frontmatter, so `graph_cli` carried an `AliasResolver` to close the gap.
graphmark 0.6 resolves `aliases:` natively — derived from that resolver as its
oracle — so the seam now injects no resolver at all and lets `graphmark.build()`
default the extractor/resolver pair.

These tests are the regression guard for that swap. They assert the *behavior*
still holds through the seam, not that this file implements it; the last test
holds the seam to the delegation, so a reintroduced local resolver fails loudly
rather than silently forking from the package again.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

graphmark = pytest.importorskip("graphmark")

ENGINE = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(ENGINE))

_spec = importlib.util.spec_from_file_location("graph_cli", ENGINE / "graph_cli.py")
gc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gc)


def note(root: Path, rel: str, aliases: list[str] | None = None, body: str = "body\n") -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    front = ["---", "date: 2026-01-01", 'description: "n"']
    if aliases:
        front.append("aliases:")
        front += [f"  - {a}" for a in aliases]
    front += ["tags:", "  - note", "---", ""]
    p.write_text("\n".join(front) + body, encoding="utf-8")
    return p


def vault(tmp_path: Path) -> Path:
    (tmp_path / ".vault-context").write_text("personal", encoding="utf-8")
    return tmp_path


class TestAliasResolution:
    def test_alias_resolves_to_the_note_declaring_it(self, tmp_path):
        root = vault(tmp_path)
        note(root, "thinking/2026-04-11-mood-tracker.md", aliases=["Mood Tracker"])
        note(root, "personal/journal.md", body="see [[Mood Tracker]]\n")

        graph, _ = gc.build(root)
        assert graph.unresolved == {}
        assert "thinking/2026-04-11-mood-tracker.md" in graph.out_links["personal/journal.md"]

    def test_real_note_name_beats_an_alias(self, tmp_path):
        # A note that actually is called X must win; an alias is a fallback, not
        # an override, or renaming a note could silently hijack live links.
        root = vault(tmp_path)
        note(root, "personal/Sahana.md")
        note(root, "org/people/Sahana Nagesh.md", aliases=["Sahana"])
        note(root, "personal/journal.md", body="see [[Sahana]]\n")

        graph, _ = gc.build(root)
        assert graph.out_links["personal/journal.md"] == {"personal/Sahana.md"}

    def test_an_alias_claimed_by_two_notes_stays_unresolved(self, tmp_path):
        # Same rule graphmark applies to colliding basenames: refuse to guess.
        root = vault(tmp_path)
        note(root, "org/people/Amy Cota.md", aliases=["Amy"])
        note(root, "org/people/Amy Donahue.md", aliases=["Amy"])
        note(root, "personal/journal.md", body="see [[Amy]]\n")

        graph, _ = gc.build(root)
        assert graph.unresolved == {"personal/journal.md": ["Amy"]}

    def test_alias_matching_strips_display_anchor_and_extension(self, tmp_path):
        root = vault(tmp_path)
        note(root, "reference/Snowflake.md", aliases=["snowflake-ai-direction"])
        note(
            root,
            "personal/journal.md",
            body="[[snowflake-ai-direction|the direction]] [[snowflake-ai-direction#Scope]] "
            "[[snowflake-ai-direction.md]]\n",
        )

        graph, _ = gc.build(root)
        assert graph.unresolved == {}
        assert graph.out_links["personal/journal.md"] == {"reference/Snowflake.md"}

    def test_alias_is_matched_case_and_separator_insensitively(self, tmp_path):
        # Normalization comes from graphmark's own catalog, so [[Mood Tracker]]
        # and [[mood-tracker]] land on the same key the note names do.
        root = vault(tmp_path)
        note(root, "thinking/tracker.md", aliases=["Mood Tracker"])
        note(root, "personal/journal.md", body="see [[mood-tracker]]\n")

        graph, _ = gc.build(root)
        assert graph.unresolved == {}

    def test_notes_without_aliases_are_unaffected(self, tmp_path):
        root = vault(tmp_path)
        note(root, "personal/journal.md", body="see [[Nothing Here]]\n")

        graph, _ = gc.build(root)
        assert graph.unresolved == {"personal/journal.md": ["Nothing Here"]}

    def test_alias_resolution_comes_from_graphmark_not_from_this_file(self, tmp_path):
        # The behavior above is the package's now. Keeping a local copy of it is
        # exactly the drift this deletion closed, so name the removed symbols:
        # reintroducing one should fail here, not go unnoticed for a release.
        for symbol in ("AliasResolver", "frontmatter_aliases", "_strip_display", "_catalog_key"):
            assert not hasattr(gc, symbol), f"graph_cli should not reimplement {symbol}"

        root = vault(tmp_path)
        note(root, "thinking/tracker.md", aliases=["Mood Tracker"])
        note(root, "personal/journal.md", body="see [[Mood Tracker]]\n")

        # No resolver injected: stock graphmark.build() defaults still resolve the alias.
        graph = graphmark.build(gc.build(root)[1])
        assert graph.unresolved == {}

    def test_a_malformed_frontmatter_block_does_not_break_the_build(self, tmp_path):
        # This runs inside a session hook. A note someone is mid-edit must not
        # take the whole graph down.
        root = vault(tmp_path)
        (root / "personal").mkdir(parents=True, exist_ok=True)
        (root / "personal" / "half-written.md").write_text(
            "---\naliases:\n  - [unclosed\n", encoding="utf-8"
        )
        note(root, "personal/journal.md", body="see [[Nothing Here]]\n")

        graph, _ = gc.build(root)
        assert graph.unresolved == {"personal/journal.md": ["Nothing Here"]}
