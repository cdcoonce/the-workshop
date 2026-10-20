"""Tests for the ``mojibake`` helper used by the encoding-corruption tests.

The helper builds what Word, Excel and Notepad produce when a UTF-8 file is
opened as Windows-1252, so fixtures are real mojibake rather than hand-typed
Latin-1-style literals (parent issue #777).
"""

import pytest

from tests.mojibake import mojibake

# Explicit inverse of the helper's byte rule, written out independently of it:
# cp1252 characters in 0x80-0x9F back to their byte; C1 controls to themselves.
_CP1252_HIGH = {
    "€": 0x80, "‚": 0x82, "ƒ": 0x83, "„": 0x84,
    "…": 0x85, "†": 0x86, "‡": 0x87, "ˆ": 0x88,
    "‰": 0x89, "Š": 0x8A, "‹": 0x8B, "Œ": 0x8C,
    "Ž": 0x8E, "‘": 0x91, "’": 0x92, "“": 0x93,
    "”": 0x94, "•": 0x95, "–": 0x96, "—": 0x97,
    "˜": 0x98, "™": 0x99, "š": 0x9A, "›": 0x9B,
    "œ": 0x9C, "ž": 0x9E, "Ÿ": 0x9F,
}  # fmt: skip


def _unmojibake(text: str) -> str:
    out = bytearray()
    for ch in text:
        out.append(_CP1252_HIGH.get(ch, ord(ch)))
    return out.decode("utf-8")


class TestMojibakeHelper:
    """The helper applies the WHATWG windows-1252 rule to UTF-8 bytes."""

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("—", "â€”"),
            ("“", "â€œ"),
            ("…", "â€¦"),
            ("×", "Ã—"),
        ],
    )
    def test_defined_bytes(self, text, expected):
        assert mojibake(text) == expected

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("←", "â†\x90"),
            ("”", "â€\x9d"),
        ],
    )
    def test_undefined_bytes_map_to_c1_controls(self, text, expected):
        assert mojibake(text) == expected

    @pytest.mark.parametrize("text", ["—", "“”", "…", "×", "←", "❌", "═╝", "✓ ok"])
    def test_round_trip(self, text):
        assert _unmojibake(mojibake(text)) == text

    @pytest.mark.parametrize("text", ["", "plain ASCII text\nline 2"])
    def test_ascii_and_empty_unchanged(self, text):
        assert mojibake(text) == text

    @pytest.mark.parametrize(
        ("text", "old_key"), [("÷", "\xc3\xb7"), ("©", "\xc2\xa9")]
    )
    def test_latin1_range_matches_existing_keys(self, text, old_key):
        assert mojibake(text) == old_key
