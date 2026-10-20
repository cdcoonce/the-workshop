"""Whole-map invariant for ENCODING_CORRUPTION_MAP (parent issue #777).

Every key must be ``mojibake(<the character it stands for>)``. The 63 target
characters are listed here as ``\\u`` escapes, independently of the keys: decoding
a key to find its target would make the check circular.
"""

import pytest

from markdown_analyzer import ENCODING_CORRUPTION_MAP, analyze_markdown
from tests.mojibake import mojibake

TARGETS = [
    "\u00d7",  # U+00D7
    "\u00f7",  # U+00F7
    "\u00b1",  # U+00B1
    "\u00b0",  # U+00B0
    "\u00b5",  # U+00B5
    "\u00a9",  # U+00A9
    "\u00ae",  # U+00AE
    "\u00a3",  # U+00A3
    "\u00a5",  # U+00A5
    "\u00bd",  # U+00BD
    "\u00bc",  # U+00BC
    "\u00be",  # U+00BE
    "\u00b2",  # U+00B2
    "\u00b3",  # U+00B3
    "\u00a0",  # U+00A0
    "\u00ab",  # U+00AB
    "\u00bb",  # U+00BB
    "\u00a7",  # U+00A7
    "\u00b6",  # U+00B6
    "\u2260",  # U+2260
    "\u2264",  # U+2264
    "\u2265",  # U+2265
    "\u2248",  # U+2248
    "\u2190",  # U+2190
    "\u2192",  # U+2192
    "\u2191",  # U+2191
    "\u2193",  # U+2193
    "\u2194",  # U+2194
    "\u21d0",  # U+21D0
    "\u21d2",  # U+21D2
    "\u2014",  # U+2014
    "\u2013",  # U+2013
    "\u2022",  # U+2022
    "\u2026",  # U+2026
    "\u2018",  # U+2018
    "\u2019",  # U+2019
    "\u201c",  # U+201C
    "\u201d",  # U+201D
    "\u2122",  # U+2122
    "\u20ac",  # U+20AC
    "\u2713",  # U+2713
    "\u2714",  # U+2714
    "\u2717",  # U+2717
    "\u2718",  # U+2718
    "\u2705",  # U+2705
    "\u274c",  # U+274C
    "\u2500",  # U+2500
    "\u2502",  # U+2502
    "\u250c",  # U+250C
    "\u2510",  # U+2510
    "\u2514",  # U+2514
    "\u2518",  # U+2518
    "\u251c",  # U+251C
    "\u2524",  # U+2524
    "\u252c",  # U+252C
    "\u2534",  # U+2534
    "\u253c",  # U+253C
    "\u2550",  # U+2550
    "\u2551",  # U+2551
    "\u2554",  # U+2554
    "\u2557",  # U+2557
    "\u255a",  # U+255A
    "\u255d",  # U+255D
]

# Map values that are deliberately not the target character itself: the two
# single-quote entries fix to ASCII "'" and the NBSP entry fixes to a plain space.
VALUE_EXCEPTIONS = {
    "\u00a0": " ",
    "\u2018": "'",
    "\u2019": "'",
}


class TestWholeMapInvariant:
    """Every key is the real cp1252 mojibake of its target character."""

    def test_target_list_has_63_distinct_entries(self):
        assert len(TARGETS) == 63
        assert len(set(TARGETS)) == 63

    def test_targets_cover_every_map_key_exactly(self):
        assert {mojibake(t) for t in TARGETS} == set(ENCODING_CORRUPTION_MAP)
        assert len(ENCODING_CORRUPTION_MAP) == 63

    @pytest.mark.parametrize("target", TARGETS)
    def test_key_is_mojibake_of_target_and_fixes_back(self, target):
        key = mojibake(target)
        assert ENCODING_CORRUPTION_MAP[key] == VALUE_EXCEPTIONS.get(target, target)


class TestEndToEnd:
    """A real UTF-8 file read as Windows-1252 is flagged and restored."""

    def test_utf8_file_read_as_cp1252_is_restored(self, tmp_path):
        original = "Revenue \u2014 5 \u00d7 3\u2026 \u201cquoted\u201d \u2713\n"
        path = tmp_path / "doc.md"
        path.write_bytes(original.encode("utf-8"))

        # Mis-read the bytes the way Word/Notepad do; the helper applies the
        # WHATWG rule for the five bytes strict cp1252 refuses to decode.
        garbled = mojibake(path.read_bytes().decode("utf-8"))
        assert garbled != original

        issues = [i for i in analyze_markdown(garbled).issues if i.rule_id == "MD050"]
        assert len(issues) == 1
        assert issues[0].suggested_fix.fixed_code == original.rstrip("\n")
