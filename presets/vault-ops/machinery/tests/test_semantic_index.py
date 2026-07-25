"""Tests for the semantic index — frontmatter extraction and note chunking.

Covers the pure helpers `_extract_frontmatter` and `chunk_note` from
.claude/scripts/semantic_index.py (GitHub issue #65). These functions are
import-safe: the module imports numpy at top level (already a dependency) but
fastembed only lazily, so no heavy deps are pulled in here.
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(SCRIPTS_DIR))

import semantic_index
from semantic_index import (
    CHUNK_TARGET_WORDS,
    SNIPPET_LEN,
    VAULT_ROOT,
    _extract_frontmatter,
    chunk_note,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _note_path(name: str = "brain/sample.md") -> Path:
    """A path under VAULT_ROOT so chunk_note's relative_to() succeeds.

    The path need not exist on disk — chunk_note operates on the `raw` string
    argument and only uses the path for its vault-relative string.
    """
    return VAULT_ROOT / name


# ---------------------------------------------------------------------------
# _extract_frontmatter
# ---------------------------------------------------------------------------


class TestExtractFrontmatter:
    def test_present_returns_fields_and_body(self) -> None:
        text = (
            "---\n"
            "date: 2026-06-27\n"
            'description: "A short note"\n'
            "---\n"
            "Body line one.\n"
        )
        fields, body = _extract_frontmatter(text)
        assert fields["date"] == "2026-06-27"
        assert fields["description"] == "A short note"
        assert body == "Body line one.\n"

    def test_absent_returns_empty_dict_and_original_text(self) -> None:
        text = "No frontmatter here.\nJust body.\n"
        fields, body = _extract_frontmatter(text)
        assert fields == {}
        assert body == text

    def test_strips_surrounding_quotes_from_values(self) -> None:
        text = "---\n" "single: 'quoted'\n" 'double: "quoted"\n' "---\nbody"
        fields, _ = _extract_frontmatter(text)
        assert fields["single"] == "quoted"
        assert fields["double"] == "quoted"

    def test_lines_without_colon_are_skipped(self) -> None:
        # A bare list item (no colon) must not become a key.
        text = "---\n" "tags:\n" "  - alpha\n" "date: 2026-06-27\n" "---\nbody"
        fields, _ = _extract_frontmatter(text)
        assert "date" in fields
        # The bare list item "  - alpha" has no colon, so it is skipped
        # entirely — it produces no key (neither "- alpha" nor "alpha").
        assert "- alpha" not in fields
        assert "alpha" not in fields
        # "tags" key exists but with an empty value (nothing after the colon).
        assert fields["tags"] == ""

    def test_malformed_unclosed_frontmatter_treated_as_no_frontmatter(self) -> None:
        # Opening fence but no closing fence — regex does not match.
        text = "---\n" "date: 2026-06-27\n" "description: never closed\n"
        fields, body = _extract_frontmatter(text)
        assert fields == {}
        assert body == text

    def test_frontmatter_not_at_start_is_ignored(self) -> None:
        # The regex is anchored with .match(), so leading content blocks it.
        text = "Intro paragraph.\n" "---\n" "date: 2026-06-27\n" "---\nbody"
        fields, body = _extract_frontmatter(text)
        assert fields == {}
        assert body == text

    def test_value_containing_colon_keeps_remainder(self) -> None:
        # partition(":") splits on the first colon only.
        text = "---\n" "url: https://example.com/x\n" "---\nbody"
        fields, _ = _extract_frontmatter(text)
        assert fields["url"] == "https://example.com/x"


# ---------------------------------------------------------------------------
# chunk_note
# ---------------------------------------------------------------------------


class TestChunkNote:
    def test_short_note_no_frontmatter_single_chunk(self) -> None:
        raw = "# Heading\n\nA few short words in one section.\n"
        chunks = chunk_note(_note_path(), raw)
        assert len(chunks) == 1
        assert chunks[0]["note_path"] == "brain/sample.md"

    def test_chunk_carries_note_path_snippet_and_text(self) -> None:
        raw = "# Title\n\nSome body content here.\n"
        chunks = chunk_note(_note_path("work/active/foo.md"), raw)
        chunk = chunks[0]
        assert set(["text", "snippet", "note_path"]).issubset(chunk.keys())
        assert chunk["note_path"] == "work/active/foo.md"
        assert isinstance(chunk["text"], str) and chunk["text"]

    def test_description_emitted_as_standalone_first_chunk(self) -> None:
        raw = (
            "---\n"
            'description: "High signal summary"\n'
            "---\n"
            "# Heading\n\nBody text.\n"
        )
        chunks = chunk_note(_note_path(), raw)
        assert chunks[0]["text"] == "High signal summary"
        # The body becomes at least one additional chunk.
        assert len(chunks) >= 2

    def test_frontmatter_is_stripped_from_body_chunks(self) -> None:
        raw = (
            "---\n"
            "date: 2026-06-27\n"
            'description: "Sum"\n'
            "---\n"
            "# Heading\n\nThe actual body.\n"
        )
        chunks = chunk_note(_note_path(), raw)
        # No body chunk should contain the raw frontmatter fence or fields.
        body_chunks = [c for c in chunks if c["text"] != "Sum"]
        assert body_chunks
        for c in body_chunks:
            assert "---" not in c["text"]
            assert "date: 2026-06-27" not in c["text"]

    def test_long_note_splits_into_multiple_chunks(self) -> None:
        # Two sections each just over the target word count → 2+ chunks.
        big_words = " ".join(["word"] * (CHUNK_TARGET_WORDS + 5))
        raw = f"# Section A\n\n{big_words}\n\n# Section B\n\n{big_words}\n"
        chunks = chunk_note(_note_path(), raw)
        assert len(chunks) >= 2

    def test_oversize_single_section_emitted_alone(self) -> None:
        # One section larger than the window is emitted as its own chunk.
        big = " ".join(["w"] * (CHUNK_TARGET_WORDS + 50))
        raw = f"# Big\n\n{big}\n"
        chunks = chunk_note(_note_path(), raw)
        assert len(chunks) == 1
        assert len(chunks[0]["text"].split()) >= CHUNK_TARGET_WORDS

    def test_small_sections_packed_into_one_window(self) -> None:
        # Several tiny sections that together fit under the target word count
        # should be packed into a single chunk.
        raw = (
            "# A\n\nshort one\n\n"
            "# B\n\nshort two\n\n"
            "# C\n\nshort three\n"
        )
        chunks = chunk_note(_note_path(), raw)
        assert len(chunks) == 1
        # All three sections survive in the packed text.
        assert "short one" in chunks[0]["text"]
        assert "short three" in chunks[0]["text"]

    def test_empty_input_still_emits_one_chunk(self) -> None:
        chunks = chunk_note(_note_path(), "")
        assert len(chunks) == 1
        # Fallback uses the relative path string when there is no content.
        assert chunks[0]["text"] == "brain/sample.md"

    def test_whitespace_only_input_still_emits_one_chunk(self) -> None:
        chunks = chunk_note(_note_path(), "   \n\n\t  \n")
        assert len(chunks) == 1
        # No real content → falls back to the rel path.
        assert chunks[0]["text"] == "brain/sample.md"

    def test_snippet_truncated_to_snippet_len(self) -> None:
        long_line = "x" * (SNIPPET_LEN + 100)
        raw = f"# H\n\n{long_line}\n"
        chunks = chunk_note(_note_path(), raw)
        assert all(len(c["snippet"]) <= SNIPPET_LEN for c in chunks)

    def test_frontmatter_only_no_description_emits_one_chunk(self) -> None:
        # Closing fence followed by a newline → regex matches, body is empty.
        # No description and empty body → the fallback `body.strip() or
        # raw.strip()` yields the stripped raw text (the only non-empty
        # source), so a single chunk is still emitted.
        raw = "---\n" "date: 2026-06-27\n" "---\n\n"
        chunks = chunk_note(_note_path(), raw)
        assert len(chunks) == 1
        assert chunks[0]["text"] == raw.strip()
